# -*- coding: utf-8 -*-
"""Fabricas de transporte OPT-IN para los modos con proveedor del benchmark.

NADA de este modulo se ejecuta por defecto. Importarlo NO abre red: solo define
constructores. La red unicamente puede abrirse si:

  1. el modo pertenece a `runner.PROVIDER_MODES`, y
  2. se ha superado la DOBLE LLAVE (`--enable-providers` + `S9K_BENCH_PROVIDERS=1`),
     comprobada por `runner.require_provider_authorization` ANTES de llamar aqui,
     y ademas el NUCLEO (`runner.run_benchmark`/`run_source`) exige que el
     transporte/proveedor este INYECTADO: nunca delega en el registry (B1).

Ningun test de `app/tests/` debe invocar estas fabricas contra red real: los
tests inyectan dobles o parchean `urlopen`.

TIMEOUT
-------
`relations.local_llm_shadow.LocalLLMConfig.timeout` vale 30 s y el pipeline lo
construye internamente (no es configurable desde el benchmark sin tocar
`pipeline.py`, que esta fuera de alcance). Cuando se INYECTA un `transport`, el
tiempo de espera efectivo es el del transporte: por eso este modulo aplica
`runner.PROVIDER_LOCAL_TIMEOUT_S`.

MEDICION REAL (ronda 2): el p50 medido contra el Ollama vivo fue de **97,8 s** y
el maximo observado **175,7 s** -- no los "10-65 s" que afirmaban los
comentarios anteriores (refutado). Con 30 s casi todas las llamadas expirarian y
el benchmark mediria TIMEOUTS en lugar de CALIDAD.

VALIDACION DEL ENDPOINT (B5)
----------------------------
`normalize_local_endpoint` exige esquema `http`/`https` y host no vacio, y
RECHAZA credenciales embebidas en la URL. Antes aceptaba cualquier cadena: con
`file:///...` se fabricaba un run con "Ollama real: EXECUTED", llamadas contadas
y latencias medidas SIN una sola conexion de red, y con `ftp://` se abriria
conexion a un host/puerto arbitrarios.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlsplit, urlunsplit

from .runner import PROVIDER_LOCAL_TIMEOUT_S, BenchmarkError, ProviderTransportError

# Endpoint del LLM local. SIN default a infraestructura real: si no se aporta
# ni por argumento ni por entorno, la fabrica falla cerrada.
LOCAL_ENDPOINT_ENV = "S9K_BENCH_OLLAMA_ENDPOINT"

# Raiz REAL del arbol de la aplicacion (`data-engine/app`): NO depende del
# directorio de invocacion (N12).
_REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_MODEL_ENV = "S9K_BENCH_OLLAMA_MODEL"

# Ruta canonica del endpoint OpenAI-compatible de chat.
CHAT_COMPLETIONS_PATH = "/chat/completions"
OPENAI_PREFIX = "/v1"

# Esquemas admitidos para CUALQUIER endpoint de proveedor (B5).
ALLOWED_SCHEMES = frozenset({"http", "https"})

# Tope DURO de bytes leidos de una respuesta (N2). `max_response_bytes` del
# pipeline (65536) se aplicaba DESPUES de haber leido y parseado el cuerpo
# entero: una respuesta de 200 MB llegaba a memoria (RSS 25 MB -> 627 MB).
MAX_RESPONSE_BYTES = 1_048_576  # 1 MiB
_READ_CHUNK = 65_536

# Margen del deadline de RELOJ DE PARED por llamada (N2). `urlopen(timeout=)` es
# por operacion de socket: un servidor que gotea 1 byte/s mantuvo viva una
# llamada 60 s con `timeout=2`. El deadline se comprueba entre trozos de lectura.
WALL_CLOCK_MARGIN_S = 30


def _split_checked(endpoint: str, *, what: str):
    """`urlsplit` + validacion de esquema/host/credenciales. NO abre red.

    ORDEN (N5): las CREDENCIALES se comprueban ANTES que el host y NINGUNA rama
    vuelca la URL cruda. `http://tok:SECRETO@/v1` tiene credenciales y no tiene
    host: con el orden anterior ganaba la rama de host, que imprimia
    `endpoint!r` entero y filtraba el secreto a stderr (y a los logs de CI, donde
    un `S9K_NVIDIA_BASE_URL` mal escrito es un error humano plausible).

    N10: `urlsplit(...).port` lanza `ValueError` con un puerto fuera de rango
    (`http://host:99999/v1`); se traduce a `BenchmarkError` para que la CLI
    devuelva `EXIT_BENCHMARK_ERROR` en vez de una traza cruda con rc=1.
    """
    try:
        parts = urlsplit(endpoint)
        username, password, hostname = parts.username, parts.password, parts.hostname
        port = parts.port  # puede lanzar ValueError (puerto fuera de rango)
    except ValueError as exc:
        raise BenchmarkError(
            f"{what} malformado ({type(exc).__name__}): puerto o autoridad "
            "invalidos. La URL cruda NO se reproduce aqui (puede contener "
            "credenciales)."
        ) from exc
    # 1) credenciales PRIMERO: si las hay, se rechaza sin mirar nada mas.
    if username or password:
        raise BenchmarkError(
            f"{what} con credenciales embebidas en la URL: RECHAZADO. "
            "Las credenciales acabarian en el texto de los errores de transporte "
            "y en el informe. Usa el entorno para los secretos."
        )
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise BenchmarkError(
            f"{what} con esquema no permitido: {parts.scheme or '(vacio)'!r}. "
            f"Solo se admiten {sorted(ALLOWED_SCHEMES)}: un esquema como file://, "
            "ftp:// o gopher:// fabricaria un run con 'proveedor EXECUTED' sin "
            "conexion real (o abriria conexion a un servicio arbitrario)."
        )
    if not hostname:
        raise BenchmarkError(
            f"{what} sin host. Se exige host explicito. (La URL cruda no se "
            "reproduce: puede contener credenciales.)")
    if " " in hostname or "\t" in hostname:
        raise BenchmarkError(
            f"{what} con espacios en el host: RECHAZADO ({hostname.strip()!r}).")
    # N9: puerto 0 no es un destino valido (y desaparecia de la atestacion).
    if port == 0:
        raise BenchmarkError(
            f"{what} con puerto 0: no es un destino valido y ademas desaparecia "
            "de la atestacion publicada.")
    return parts


def _host_for_attestation(parts) -> str:
    """Host de la atestacion CONSERVANDO los corchetes de IPv6 (N9).

    `parts.hostname` devuelve `::1` para `http://[::1]:11434/v1`, y concatenarlo
    producia `http://::1:11434`, una atestacion ambigua e irreconstruible.
    """
    host = parts.hostname or ""
    if ":" in host:  # IPv6
        return f"[{host}]"
    return host


def endpoint_attestation(endpoint: str) -> str:
    """`esquema://host:puerto` SIN credenciales, ruta ni query: para el informe.

    La atestacion de seguridad debe ser auditable sin filtrar secretos.
    """
    parts = _split_checked(endpoint, what="endpoint")
    port = parts.port
    return (f"{parts.scheme.lower()}://{_host_for_attestation(parts)}"
            + (f":{port}" if port else ""))


def normalize_local_endpoint(endpoint: str) -> str:
    """Normaliza el endpoint del LLM local a la ruta de chat OpenAI-compatible.

    REGLA (defecto D2). Antes se hacia POST a la URL tal cual, asi que la forma
    natural de pasar la base OpenAI-compatible de Ollama
    (`http://host:11434/v1`) producia un 404 SILENCIOSO: 18 llamadas fallidas
    contadas como si el modelo hubiera contestado mal. La regla es:

      * termina ya en `/chat/completions`  -> se deja tal cual.
      * termina en `/v1`                   -> se le anade `/chat/completions`.
      * cualquier otra base (`http://host:11434`) -> se le anade
        `/v1/chat/completions`.

    Las barras finales se recortan siempre. La normalizacion NO abre red.

    VALIDACION (B5): antes de normalizar se exige esquema `http`/`https`, host no
    vacio y AUSENCIA de credenciales en la URL; cualquier otra cosa es
    `BenchmarkError`. La cadena vacia se conserva vacia para que la fabrica pueda
    emitir su propio error "falta endpoint".
    """
    url = (endpoint or "").strip().rstrip("/")
    if not url:
        return url
    parts = _split_checked(url, what="endpoint del LLM local")
    # N9: la normalizacion sustituye la RUTA con `urlunsplit`, no concatena
    # sufijos al final de la cadena. Concatenar producia `.../v1?k=X/chat/completions`
    # para una base con query -- una URL que SIEMPRE da 404, la misma clase de
    # defecto que D2. La query se CONSERVA (algunas pasarelas la usan); el
    # fragmento se descarta porque no se envia en una peticion HTTP.
    path = (parts.path or "").rstrip("/")
    # NB-2 (ronda 4): la deteccion de sufijo es INSENSIBLE A MAYUSCULAS. Antes,
    # `HTTP://HOST/V1` no casaba con `/v1` y producia `.../V1/v1/chat/completions`
    # (404 seguro), la misma clase de defecto que D2. Se compara sobre la ruta en
    # minusculas pero se CONSERVA la casacion original del usuario en la salida.
    path_lower = path.lower()
    if path_lower.endswith(CHAT_COMPLETIONS_PATH):
        new_path = path
    elif path_lower.endswith(OPENAI_PREFIX):
        new_path = path + CHAT_COMPLETIONS_PATH
    else:
        new_path = path + OPENAI_PREFIX + CHAT_COMPLETIONS_PATH
    netloc = _host_for_attestation(parts) + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme.lower(), netloc, new_path, parts.query, ""))


# ---------------------------------------------------------------------------
# Apertura HTTP endurecida (N1 + N2)
# ---------------------------------------------------------------------------
class _NoCrossOriginRedirect(urllib.request.HTTPRedirectHandler):
    """Rechaza CUALQUIER redireccion que cambie esquema, host o puerto (N1).

    Con el manejador por defecto, un 302 llevaba la peticion a otro host y su
    respuesta se aceptaba como si fuera del modelo.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        old = urlsplit(req.full_url)
        new = urlsplit(newurl)
        same = (
            old.scheme.lower() == new.scheme.lower()
            and (old.hostname or "") == (new.hostname or "")
            and old.port == new.port
        )
        if not same:
            raise urllib.error.HTTPError(
                req.full_url, code,
                "redireccion entre origenes BLOQUEADA "
                f"({old.scheme}://{old.hostname}:{old.port} -> "
                f"{new.scheme}://{new.hostname}:{new.port}): la respuesta de otro "
                "host NO es la del modelo",
                headers, fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# N6 -- el endurecimiento NO puede depender de un global mutable.
#
# Antes, `_open` comparaba `urllib.request.urlopen is _STDLIB_URLOPEN` y, si
# diferian, se SALTABA `_NoCrossOriginRedirect`. Es decir: un control de
# seguridad que cualquier mock, `responses`, `vcrpy` o instrumentacion que
# reemplazase ese global desactivaba en silencio. Ahora el opener endurecido se
# usa SIEMPRE y la costura de test es EXPLICITA: el parametro `opener=` de
# `build_local_transport` (o, para los tests que parchean el modulo, `_OPENER`).
_STDLIB_URLOPEN = urllib.request.urlopen

# Costura de test EXPLICITA: si vale `None` (caso normal y unico en produccion)
# se usa el opener endurecido. Un test puede asignar aqui un callable
# `(req, timeout) -> respuesta`.
_OPENER: Optional[Callable] = None


def _hardened_opener():
    """Opener con el manejador de redirecciones endurecido. NO abre red al crearse."""
    return urllib.request.build_opener(_NoCrossOriginRedirect())


def _open(req, timeout: float, opener: Optional[Callable] = None):
    seam = opener or _OPENER
    if seam is not None:  # costura EXPLICITA (tests), nunca una ruta de red real
        return seam(req, timeout=timeout)
    # Sin costura explicita SIEMPRE se usa el opener endurecido: parchear
    # `urllib.request.urlopen` ya NO desactiva `_NoCrossOriginRedirect`.
    return _hardened_opener().open(req, timeout=timeout)


def _read_bounded(resp, *, deadline: float, url: str) -> bytes:
    """Lee como mucho `MAX_RESPONSE_BYTES` y aborta al pasar el deadline (N2)."""
    try:
        chunks: list[bytes] = []
        total = 0
        while True:
            if time.monotonic() > deadline:
                raise ProviderTransportError(
                    "deadline de reloj de pared superado leyendo la respuesta; "
                    f"endpoint normalizado: {url}"
                )
            chunk = resp.read(_READ_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise ProviderTransportError(
                    f"respuesta demasiado grande (> {MAX_RESPONSE_BYTES} bytes): "
                    f"lectura ABORTADA; endpoint normalizado: {url}"
                )
            chunks.append(chunk)
        return b"".join(chunks)
    except TypeError:
        # Doble de test cuyo `read()` no acepta argumentos: se lee entero pero se
        # sigue aplicando el tope de tamano.
        raw = resp.read()
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ProviderTransportError(
                f"respuesta demasiado grande (> {MAX_RESPONSE_BYTES} bytes); "
                f"endpoint normalizado: {url}"
            )
        return raw


def build_local_transport(
    endpoint: Optional[str] = None,
    *,
    model: Optional[str] = None,
    timeout_s: int = PROVIDER_LOCAL_TIMEOUT_S,
    opener: Optional[Callable] = None,
) -> Callable[[list], tuple]:
    """Transporte OpenAI-compatible para el LLM local (Ollama).

    Devuelve `transport(messages) -> (response_json, latency_ms)`, la firma que
    espera `LocalLLMConfig.transport`. El timeout es el de ESTE transporte
    (>= 120 s): ver la nota de cabecera. Ademas del timeout por operacion de
    socket se aplica un DEADLINE de reloj de pared y un tope de bytes leidos.
    """
    # N13: endpoint EXPLICITO, sin fallback silencioso al entorno. Construir el
    # transporte a proposito no implicaba saber a donde apuntaba: con
    # `S9K_BENCH_OLLAMA_ENDPOINT` apuntando a un host atacante, un llamante de la
    # API publica abria 5 conexiones a ese host sin haber nombrado ningun
    # destino. Quien quiera usar el entorno debe leerlo y pasarlo (lo hace la CLI,
    # que ademas publica la atestacion del endpoint en el informe).
    if endpoint is None or not str(endpoint).strip():
        del_entorno = os.environ.get(LOCAL_ENDPOINT_ENV)
        raise BenchmarkError(
            "no hay endpoint del LLM local: la fabrica exige el endpoint "
            "EXPLICITO (argumento `endpoint`); ya NO se toma de "
            f"{LOCAL_ENDPOINT_ENV} de forma implicita"
            + (f" (hay un {LOCAL_ENDPOINT_ENV} definido: pasalo explicitamente si "
               "es el destino que quieres)" if del_entorno else "")
            + ". Sin endpoint NO se abre ninguna conexion."
        )
    endpoint = str(endpoint)
    if timeout_s < 120:
        raise BenchmarkError(
            f"timeout del LLM local demasiado bajo ({timeout_s}s): con la latencia "
            "REAL medida de Ollama (p50 97,8 s; maximo 175,7 s) se medirian "
            "timeouts, no calidad. Minimo 120 s."
        )
    model_name = model or os.environ.get(LOCAL_MODEL_ENV) or "local-llm"
    url = normalize_local_endpoint(endpoint)  # valida esquema/host/credenciales

    def transport(messages: list) -> tuple:
        body = json.dumps(
            {"model": model_name, "messages": messages, "stream": False,
             "temperature": 0},
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        t0 = time.monotonic()
        deadline = t0 + timeout_s + WALL_CLOCK_MARGIN_S
        # Cualquier fallo de RED / HTTP / parseo es un fallo de TRANSPORTE: se
        # eleva como `ProviderTransportError` para que el evaluador lo marque
        # como `transport_error:` y NUNCA se confunda con una respuesta mal
        # formada del modelo (defecto D1).
        try:
            with _open(req, timeout_s, opener=opener) as resp:
                raw = _read_bounded(resp, deadline=deadline, url=url)
        except ProviderTransportError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderTransportError(
                f"fallo de transporte contra el LLM local ({type(exc).__name__}); "
                f"endpoint normalizado: {url}"
            ) from exc
        latency_ms = int((time.monotonic() - t0) * 1000)
        if time.monotonic() > deadline:
            raise ProviderTransportError(
                f"deadline de reloj de pared superado ({latency_ms} ms); "
                f"endpoint normalizado: {url}"
            )
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise ProviderTransportError(
                f"respuesta no parseable como JSON ({type(exc).__name__}); "
                f"endpoint normalizado: {url}"
            ) from exc
        # Validacion de FORMA OpenAI: sin choices[0].message.content no hay
        # respuesta del modelo que juzgar; es transporte, no calidad.
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderTransportError(
                "la respuesta no tiene la forma OpenAI esperada "
                f"(choices[0].message.content ausente); endpoint normalizado: {url}"
            ) from exc
        if not isinstance(content, str):
            raise ProviderTransportError(
                "choices[0].message.content no es texto; "
                f"endpoint normalizado: {url}"
            )
        return data, latency_ms

    return transport


def build_external_provider(provider: Any = None) -> Any:
    """Proveedor externo (NVIDIA) en modo sombra: OBJETO REAL, nunca `None`.

    Antes esta funcion era la IDENTIDAD y devolvia SIEMPRE `None` (N5), con dos
    consecuencias graves: el nucleo delegaba en el registry de
    `relations.external_ai_shadow` (que lee la clave del entorno y abre red por su
    cuenta, B1) y el informe publicaba `external_ai=FAILED_CLOSED` y `Red: none`
    aunque hubiera habido POSTs reales (B2).

    Ahora construye explicitamente el proveedor del registry de `external_ai`,
    exigiendo API key y validando el `base_url`. Falla CERRADO con
    `BenchmarkError` si falta cualquiera de las dos cosas. Construirlo NO abre red.
    """
    if provider is not None:
        return provider
    from external_ai import registry as _registry

    cfg = _registry.nvidia_config()
    if not cfg.get("api_key_present"):
        raise BenchmarkError(
            "IA externa habilitada pero S9K_NVIDIA_API_KEY ausente: FALLO CERRADO. "
            "No se construye proveedor y no se abre ninguna conexion."
        )
    _split_checked(str(cfg.get("base_url") or ""), what="base_url de la IA externa")
    try:
        # N12: `repo_root` era `Path.cwd()`, es decir el directorio desde el que
        # se invocase el proceso. Fallaba cerrado, pero el destino/config del
        # proveedor no debe depender de donde se lance el comando: se usa la raiz
        # REAL del arbol de la aplicacion (`data-engine/app`), derivada del propio
        # modulo.
        return _registry.get_provider("nvidia", repo_root=_REPO_ROOT)
    except BenchmarkError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BenchmarkError(
            f"no se pudo construir el proveedor externo ({type(exc).__name__}): "
            "FALLO CERRADO, sin red."
        ) from exc


def external_endpoint_attestation() -> str:
    """`esquema://host:puerto` del proveedor externo, sin credenciales."""
    from external_ai import registry as _registry

    return endpoint_attestation(str(_registry.nvidia_config().get("base_url") or ""))


__all__ = [
    "LOCAL_ENDPOINT_ENV",
    "LOCAL_MODEL_ENV",
    "CHAT_COMPLETIONS_PATH",
    "ALLOWED_SCHEMES",
    "MAX_RESPONSE_BYTES",
    "normalize_local_endpoint",
    "endpoint_attestation",
    "external_endpoint_attestation",
    "build_local_transport",
    "build_external_provider",
]
