# -*- coding: utf-8 -*-
"""ESCRITOR DE NOMBRES HUMANOS — CORTE 6B-2(a).

## LA PROPIEDAD

Un administrador autorizado puede asignar o modificar el nombre humano de un
WORKSPACE desde la web, modificando exclusivamente ``metadata.label`` dentro
del ``perfil-operador.json`` que ya es la autoridad real de ese contexto
(diagnosticado y leído por ``presentacion_etiquetas.py``, Corte 6B-1), sin
alterar la identidad del workspace ni el resto de la bóveda.

## ALCANCE DE ESTE CORTE — SOLO WORKSPACE, NO PARTIDA (C2)

El encargo (C2) prohíbe un escritor de partida sin contrato ni parser: hoy
``<juego>/partidas/<p>/manifiesto-partida.json`` es JSON sin esquema, leído
como objeto suelto por ``presentacion_etiquetas._label_declarado``. Definir
YA un contrato versionable para ese fichero (aunque sea mínimo) exige tocar el
registro de contratos V3 (``CONTRACT_CLASSES``, un ``.schema.json`` nuevo en
``contracts/knowledge-v3/v1/``, el validador compartido) — una superficie que
ningún otro corte de este programa ha tocado sin su propia ronda de revisión.
Eso ya no es "un contrato mínimo pequeño": es una decisión de modelo nueva
(cómo entra un contrato de PARTIDA en una familia de contratos pensada para
documentos de EXTRACCIÓN). Por eso este corte se declara **6B-2a** (workspace,
usando ``GameProfile`` que YA es la autoridad de validación existente) y dejo
**6B-2b** (contrato de partida + su escritor) como corte separado explícito.
La identidad de la partida sigue siendo la carpeta descubierta por
``vault_scope.clasificar`` — este módulo no la toca en absoluto.

## CÓMO SE SERIALIZA (condición del encargo)

``GameProfile`` es la autoridad de VALIDACIÓN, en la entrada y en la salida:
se usa ``GameProfile.from_dict(datos, validate=True)`` para decidir si el
perfil es editable, y otra vez tras la mutación para comprobar que el
documento de salida sigue siendo válido. Pero la serialización NUNCA pasa por
``GameProfile.to_json()``: ese método reordena claves y cambia el formato
(medido en el diagnóstico previo: 3995 -> 3487 bytes, con las claves
reordenadas), lo que fabricaría un diff enorme sobre el documento del
operador y dispararía conflictos a cualquier otro editor externo del mismo
fichero. En su lugar se MUTA el ``dict`` ya parseado (``json.loads`` del
fichero tal cual está en disco) y se vuelve a serializar con
``json.dumps(indent=2)``.

**Dos promesas DISTINTAS, no una sola (R1, revisión independiente de PR
#258, segunda ronda)** — antes este párrafo las mezclaba y prometía de más:

  1. **NO-OP = NO ESCRIBE.** Si el label deseado ya es el label actual, la
     función no toca el fichero en absoluto: mismos bytes, mismo hash,
     ningún ``os.replace``. Ésta es la única situación con byte-a-byte
     garantizado.
  2. **Cambio REAL = preserva SEMÁNTICAMENTE toda clave de ``metadata``
     desconocida** (ningún valor se pierde ni se reordena EN EL DICT: se
     muta el original, nunca se reconstruye desde el dataclass). Lo que
     esto NO promete es un diff mínimo en BYTES: si el perfil en disco
     estaba en un formato distinto al que produce este módulo (el caso
     real: una sola línea compacta, no ``indent=2``), la reserialización
     SÍ reformatea el documento entero -- misma indentación para todas las
     claves, aunque el CONTENIDO semántico de las que no se tocaron sea
     idéntico. Preservar el formato byte a byte del original en un cambio
     real exigiría otra técnica (parcheo de texto en vez de
     parseo+reserialización completa) y **no se cuela aquí sin decirlo**:
     si algún día se necesita, es una ampliación explícita de este módulo,
     no una promesa ya cumplida por V1.

## LOS TRES ESTADOS (C1)

    CONFORME     -> editable.
    LEGIBLE_NO_CONFORME -> legible, NO editable, con causa explícita:
                    "metadata fuera del contrato de escritura".
    INVALIDO     -> fail-closed actual (ni siquiera se puede leer como JSON).

El escritor JAMÁS normaliza ni elimina claves extra para forzar conformidad:
un perfil LEGIBLE_NO_CONFORME se queda exactamente como está.

## LA HUELLA (concurrencia optimista)

La autoridad de "¿cambió el fichero desde que lo leí?" es ``sha256`` del
contenido. ``st_size``/``(st_dev, st_ino)`` acompañan como identidad, pero
``mtime``/``mtime_ns`` NUNCA deciden nada: escrituras separadas por ~50µs
pueden compartirlos. Se revalida DOS VECES: al empezar la escritura (contra
la huella que el cliente capturó en el GET) y otra vez justo antes de
``os.replace`` (la ventana de TOCTOU). Cualquier discrepancia detectada por
cualquiera de las dos comprobaciones es 409, y **lo que escribió el otro
sigue en disco intacto**.

**Lo que esto NO es (revisión independiente de PR #258, D4):** la segunda
comprobación REDUCE la ventana de TOCTOU a dos revalidaciones, no la CIERRA.
Entre la segunda huella (``huella_justo_antes``) y el ``os.replace`` real no
hay ningún cerrojo (``O_EXCL``/``flock``) que impida a un tercer escritor
colarse en ese hueco residual: si lo hace, su escritura se pierde en
silencio, con 302/200 conforme y sin 409. Cerrar esa ventana exige un
cerrojo real y queda fuera de este corte — es deuda declarada, no una
garantía de este módulo.

## EL DESTINO SEGURO SE EJERCE, NO SE LISTA

``destino_admite_escritura_segura`` corre canarios reales
(``.s9k-probe-<token>``) en el directorio concreto: creación exclusiva,
reemplazo atómico con el temporal en el MISMO ``st_dev``, ``fsync`` de
fichero y de directorio, y relectura coherente por un descriptor nuevo. Se
cachea por directorio la primera vez que se intenta escribir ahí — no al
arrancar el proceso — y los canarios se limpian en un ``finally``: si algo
revienta a mitad de sonda, no deja basura que ``sources_catalog`` confunda
con una fuente.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
import unicodedata
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from app import sources_catalog

#: Prefijo de TODO fichero efímero que este módulo deja caer en una carpeta de
#: bóveda: canarios de la sonda y temporales de escritura atómica. Un fichero
#: con este prefijo nunca es una fuente ni un rechazo declarable:
#: ``sources_catalog`` lo excluye explícitamente de la enumeración (ver ahí).
PREFIJO_EFIMERO = ".s9k-probe-"


# ---------------------------------------------------------------------------
# Huella (fingerprint) — sha256 como autoridad, tamaño/inodo como identidad
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Huella:
    sha256: str
    st_size: int
    st_dev: int
    st_ino: int

    def a_texto(self) -> str:
        return f"{self.sha256}:{self.st_size}:{self.st_dev}:{self.st_ino}"

    @classmethod
    def desde_texto(cls, texto: str) -> "Huella":
        try:
            sha, size, dev, ino = texto.split(":")
            return cls(sha256=sha, st_size=int(size), st_dev=int(dev), st_ino=int(ino))
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"huella con formato inválido: {texto!r}") from exc

    def coincide_contenido(self, otra: "Huella") -> bool:
        """La única comparación que decide un conflicto: el CONTENIDO.

        `st_size`/`st_dev`/`st_ino` viajan para diagnóstico (una discrepancia
        ahí sin que cambie el hash sería un fichero movido/reemplazado con el
        mismo contenido), pero NUNCA deciden un 409 por sí solos.
        """
        return self.sha256 == otra.sha256


def huella_de(ruta: Path) -> Huella:
    contenido = ruta.read_bytes()
    st = ruta.stat()
    return Huella(
        sha256=hashlib.sha256(contenido).hexdigest(),
        st_size=st.st_size,
        st_dev=st.st_dev,
        st_ino=st.st_ino,
    )


# ---------------------------------------------------------------------------
# Errores
# ---------------------------------------------------------------------------

class EscrituraRechazadaError(Exception):
    """El perfil no está en un estado que se pueda editar (C1)."""

    def __init__(self, estado: "EstadoPerfil", causa: str):
        self.estado = estado
        self.causa = causa
        super().__init__(causa)


class ConflictoEscrituraError(Exception):
    """409 — el fichero cambió desde que se leyó. Lo ajeno sigue en disco."""


class DestinoNoSeguroError(Exception):
    """El predicado de destino seguro dijo que NO, con su motivo."""


class RutaNoSeguraError(Exception):
    """symlink, fuera de bóveda, o cualquier otra ruta que no se toca."""


class EntradaInvalidaError(Exception):
    """D3 (revisión independiente de PR #258) — el label no cumple el
    contrato de entrada del SERVIDOR (longitud o caracteres de control). El
    `maxlength` del HTML es cosmética del cliente, no un límite real: un POST
    directo sin pasar por el formulario colaba 200 KB, saltos de línea y
    caracteres de control (incluido NUL) crudos al documento del operador."""


# ---------------------------------------------------------------------------
# C1 — los tres estados del perfil
# ---------------------------------------------------------------------------

class EstadoPerfil(str, Enum):
    CONFORME = "conforme"
    LEGIBLE_NO_CONFORME = "legible_no_conforme"
    INVALIDO = "invalido"


CAUSA_NO_CONFORME = "metadata fuera del contrato de escritura"


@dataclass
class LecturaPerfil:
    estado: EstadoPerfil
    datos: Optional[dict]
    huella: Optional[Huella]
    causa: Optional[str]
    label_actual: str


def _label_declarado(datos: dict) -> str:
    metadata = datos.get("metadata")
    if not isinstance(metadata, dict):
        return ""
    label = metadata.get("label")
    return label.strip() if isinstance(label, str) and label.strip() else ""


#: Huella sentinela para "el manifiesto de partida todavía no existe". A
#: diferencia de `perfil-operador.json` (siempre existe: es la autoridad de
#: identidad del workspace), `manifiesto-partida.json` es OPCIONAL -- una
#: partida ya descubierta por `sources_catalog.partidas_descubiertas_en_boveda`
#: puede no tener manifiesto todavía, y este módulo NO la crea al leer, solo
#: al escribir un cambio REAL. `sha256` no es un hash hexadecimal válido a
#: propósito: no puede coincidir jamás con el de un fichero real.
_SHA_AUSENTE = "ausente-sin-manifiesto-de-partida"


def huella_ausente() -> Huella:
    """La huella que representa "no hay fichero todavía". Comparable con
    `coincide_contenido` igual que cualquier otra huella: dos "ausente" son
    la misma huella, un "ausente" nunca coincide con un fichero real."""
    return Huella(sha256=_SHA_AUSENTE, st_size=0, st_dev=0, st_ino=0)


def _huella_actual_o_ausente(ruta: Path) -> Huella:
    try:
        return huella_de(ruta)
    except OSError:
        return huella_ausente()


def _manifiesto_partida_from_dict(datos: dict):
    """Import diferido por simetría con `_game_profile_from_dict`, aunque
    aquí el contrato vive en este mismo paquete (`app.partida_manifest_contract`)
    y no exige cargar `data-engine`."""
    from app.partida_manifest_contract import (  # noqa: PLC0415
        ManifiestoPartida,
        ManifiestoPartidaInvalidoError,
    )

    try:
        return ManifiestoPartida.from_dict(datos, validate=True), None
    except ManifiestoPartidaInvalidoError as exc:
        return None, str(exc)


CAUSA_NO_CONFORME_PARTIDA = "metadata fuera del contrato de escritura de partida"


@dataclass
class LecturaManifiestoPartida:
    """Mismo contenedor que `LecturaPerfil` (C1: los tres estados), para el
    manifiesto de partida. Se declara aparte -- no se reutiliza la clase de
    perfil -- porque un manifiesto AUSENTE es CONFORME con `datos={}` y
    `huella_ausente()`, un estado que `leer_estado_perfil` no conoce (el
    perfil siempre existe)."""

    estado: EstadoPerfil
    datos: Optional[dict]
    huella: Optional[Huella]
    causa: Optional[str]
    label_actual: str


def leer_estado_manifiesto_partida(ruta_manifiesto: Path) -> LecturaManifiestoPartida:
    """Los TRES estados de C1 para `manifiesto-partida.json`, con un cuarto
    caso degenerado (AUSENTE) que colapsa a CONFORME: sin fichero no hay
    ninguna clave fuera de contrato que reportar, y es el estado normal de
    una partida recién descubierta que el operador todavía no ha nombrado."""
    try:
        contenido = ruta_manifiesto.read_bytes()
    except FileNotFoundError:
        return LecturaManifiestoPartida(
            EstadoPerfil.CONFORME, {}, huella_ausente(), None, ""
        )
    except OSError as exc:
        return LecturaManifiestoPartida(
            EstadoPerfil.INVALIDO, None, None,
            f"no se pudo leer el manifiesto de partida: {exc}", "",
        )
    try:
        datos = json.loads(contenido.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        return LecturaManifiestoPartida(
            EstadoPerfil.INVALIDO, None, None,
            f"el manifiesto de partida no es JSON válido: {exc}", "",
        )
    if not isinstance(datos, dict):
        return LecturaManifiestoPartida(
            EstadoPerfil.INVALIDO, None, None,
            "el manifiesto de partida no es un objeto JSON", "",
        )

    st = ruta_manifiesto.stat()
    huella = Huella(
        sha256=hashlib.sha256(contenido).hexdigest(),
        st_size=st.st_size, st_dev=st.st_dev, st_ino=st.st_ino,
    )
    label_actual = _label_declarado(datos)

    _manifiesto, error = _manifiesto_partida_from_dict(datos)
    if error is not None:
        return LecturaManifiestoPartida(
            EstadoPerfil.LEGIBLE_NO_CONFORME, datos, huella,
            CAUSA_NO_CONFORME_PARTIDA, label_actual,
        )
    return LecturaManifiestoPartida(EstadoPerfil.CONFORME, datos, huella, None, label_actual)


def _game_profile_from_dict(datos: dict):
    """Import diferido: evita que el visor cargue todo `data-engine` al
    importar este módulo si nunca se ejercita la escritura."""
    from knowledge_v3.contracts.game_profile import GameProfile  # noqa: PLC0415
    from knowledge_v3.contracts.base import V3ContractError  # noqa: PLC0415

    try:
        return GameProfile.from_dict(datos, validate=True), None
    except V3ContractError as exc:
        return None, str(exc)


def leer_estado_perfil(ruta_perfil: Path) -> LecturaPerfil:
    """Los TRES estados de C1, medidos sobre el fichero tal cual está.

    Nunca normaliza, nunca corrige: sólo diagnostica.
    """
    try:
        contenido = ruta_perfil.read_bytes()
    except OSError as exc:
        return LecturaPerfil(EstadoPerfil.INVALIDO, None, None,
                              f"no se pudo leer el perfil: {exc}", "")
    try:
        datos = json.loads(contenido.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        return LecturaPerfil(EstadoPerfil.INVALIDO, None, None,
                              f"el perfil no es JSON válido: {exc}", "")
    if not isinstance(datos, dict):
        return LecturaPerfil(EstadoPerfil.INVALIDO, None, None,
                              "el perfil no es un objeto JSON", "")

    st = ruta_perfil.stat()
    huella = Huella(
        sha256=hashlib.sha256(contenido).hexdigest(),
        st_size=st.st_size, st_dev=st.st_dev, st_ino=st.st_ino,
    )
    label_actual = _label_declarado(datos)

    _perfil, error = _game_profile_from_dict(datos)
    if error is not None:
        return LecturaPerfil(EstadoPerfil.LEGIBLE_NO_CONFORME, datos, huella,
                              CAUSA_NO_CONFORME, label_actual)
    return LecturaPerfil(EstadoPerfil.CONFORME, datos, huella, None, label_actual)


# ---------------------------------------------------------------------------
# El predicado de destino seguro — se EJERCE, no se lista
# ---------------------------------------------------------------------------

#: Cache por directorio: se puebla al PRIMER intento de edición en ese
#: destino, no al arrancar el proceso (coste real de sonda, no gratis).
_cache_destino: dict[str, tuple[bool, str]] = {}


def _fsync_directorio(directorio: Path) -> None:
    dirfd = os.open(str(directorio), os.O_RDONLY)
    try:
        os.fsync(dirfd)
    finally:
        os.close(dirfd)


def _probar_destino(directorio: Path) -> tuple[bool, str]:
    token = secrets.token_hex(8)
    canario = directorio / f"{PREFIJO_EFIMERO}{token}"
    temporal = directorio / f"{PREFIJO_EFIMERO}{token}.tmp"
    try:
        # 1) creación exclusiva
        fd = os.open(str(canario), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(fd, b"s9k-probe-v1")
            os.fsync(fd)
        finally:
            os.close(fd)

        # 2) el temporal del reemplazo tiene que vivir en el MISMO st_dev
        if os.stat(str(canario)).st_dev != os.stat(str(directorio)).st_dev:
            return False, "el directorio no permite un temporal en el mismo dispositivo (st_dev distinto)"

        # 3) reemplazo atómico real, con fsync del fichero nuevo
        contenido_v2 = b"s9k-probe-v2"
        with open(temporal, "wb") as f:
            f.write(contenido_v2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(temporal), str(canario))

        # 4) fsync del directorio: el reemplazo tiene que sobrevivir
        _fsync_directorio(directorio)

        # 5) relectura coherente por un DESCRIPTOR NUEVO
        releido = canario.read_bytes()
        if releido != contenido_v2:
            return False, "la relectura tras el reemplazo no refleja lo escrito"

        return True, ""
    except OSError as exc:
        return False, f"el directorio no admite escritura segura: {exc}"
    finally:
        for p in (canario, temporal):
            try:
                p.unlink()
            except OSError:
                pass


def destino_admite_escritura_segura(directorio: Path, *, forzar: bool = False) -> tuple[bool, str]:
    """`(True, "")` si el destino soporta reemplazo atómico seguro, si no
    `(False, motivo)`. Cacheado por directorio tras el primer intento."""
    clave = str(directorio)
    if not forzar and clave in _cache_destino:
        return _cache_destino[clave]
    resultado = _probar_destino(directorio)
    _cache_destino[clave] = resultado
    return resultado


# ---------------------------------------------------------------------------
# Seguridad de ruta — nunca symlinks, nunca fuera de bóveda, nunca mkdir
# ---------------------------------------------------------------------------

def _asegurar_ruta_segura(ruta_perfil: Path, *, permitir_ausente: bool = False) -> None:
    """`permitir_ausente=True` (6B-2b, `manifiesto-partida.json`) admite que
    `ruta_perfil` todavía no exista: se resuelve sin exigir el componente
    final (`resolve(strict=False)`), pero la raíz de bóvedas SÍ tiene que
    existir siempre -- si no, no hay nada contra lo que comprobar el ámbito."""
    if ruta_perfil.is_symlink():
        raise RutaNoSeguraError("el perfil es un symlink: rechazado")
    carpeta = ruta_perfil.parent
    if carpeta.is_symlink():
        raise RutaNoSeguraError("la carpeta del juego es un symlink: rechazada")

    raiz = sources_catalog.raiz_de_bovedas()
    if raiz is None:
        return
    try:
        resuelto = ruta_perfil.resolve(strict=not permitir_ausente)
        raiz_resuelta = raiz.resolve(strict=True)
    except OSError as exc:
        raise RutaNoSeguraError(f"no se pudo resolver la ruta del perfil: {exc}") from exc
    if raiz_resuelta != resuelto and raiz_resuelta not in resuelto.parents:
        raise RutaNoSeguraError("la ruta resuelta del perfil cae fuera de la bóveda")


# ---------------------------------------------------------------------------
# Escritura atómica — nunca `to_json()`, muta el dict original
# ---------------------------------------------------------------------------

def _escribir_atomico(ruta: Path, datos: dict) -> None:
    directorio = ruta.parent
    contenido = json.dumps(datos, indent=2, ensure_ascii=False) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=PREFIJO_EFIMERO, suffix=".tmp", dir=str(directorio))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(contenido)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(ruta))
        _fsync_directorio(directorio)
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# D3 (revisión independiente de PR #258) — contrato de entrada del label,
# medido EN EL SERVIDOR. El `maxlength="200"` del HTML es una comodidad del
# cliente, no una garantía: un POST directo se lo salta.
# ---------------------------------------------------------------------------

#: Mismo tope que el `maxlength` del formulario — declarado una sola vez
#: aquí, para que servidor y cliente no puedan divergir por accidente.
LONGITUD_MAXIMA_LABEL = 200

#: R3 (revisión independiente de PR #258, segunda ronda): el primer filtro
#: sólo cubría C0 (`ord(c) < 0x20`) y DEL (`0x7F`). Se colaban crudos: C1
#: (U+0080-U+009F, categoría `Cc` igual que C0/DEL), separadores de línea/
#: párrafo Unicode (U+2028 `Zl`, U+2029 `Zp`), y caracteres de FORMATO
#: invisibles (categoría `Cf`): cero-ancho (U+200B) y los overrides
#: bidireccionales que el gate de Trojan Source de este repo ya vigila en
#: OTRA superficie (U+202E, U+2066-U+2069). Por CATEGORÍA Unicode, no por
#: rango cerrado a mano, para no tener que perseguir el próximo punto de
#: código de la misma familia uno a uno.
_CATEGORIAS_DE_CONTROL_PROHIBIDAS = frozenset({"Cc", "Cf", "Zl", "Zp"})


def _label_entrada_invalida(texto: str) -> Optional[str]:
    """`None` si `texto` cumple el contrato de entrada; si no, el motivo del
    rechazo. Sólo se llama con el valor YA recortado (`strip()`) y NO vacío:
    un label vacío es la señal de borrado (D2), no una entrada a validar."""
    if len(texto) > LONGITUD_MAXIMA_LABEL:
        return f"el nombre humano no puede superar los {LONGITUD_MAXIMA_LABEL} caracteres"
    if any(unicodedata.category(c) in _CATEGORIAS_DE_CONTROL_PROHIBIDAS for c in texto):
        return (
            "el nombre humano no puede contener caracteres de control, de "
            "formato invisible (cero-ancho, overrides bidireccionales) ni "
            "separadores Unicode de línea o párrafo"
        )
    return None


# ---------------------------------------------------------------------------
# La operación completa
# ---------------------------------------------------------------------------

def escribir_label_workspace(
    carpeta_juego: Path,
    nuevo_label: str,
    huella_cliente: Huella,
) -> LecturaPerfil:
    """Escribe o BORRA `metadata.label` en el `perfil-operador.json` de
    `carpeta_juego`.

    `nuevo_label` vacío (o sólo espacios) BORRA `metadata.label` (D2,
    revisión independiente de PR #258): un guardado accidental de un campo
    vacío deja de ser permanente desde la web. No es un error: es la salida
    natural de "no quiero nombre humano aquí".

    Nunca crea la carpeta (`carpeta_juego` tiene que existir y ser resuelta
    por la MISMA autoridad que ya usa `presentacion_etiquetas`: el llamador
    la obtiene de ahí, no la compone). Lanza:

      - `EntradaInvalidaError` si el label (no vacío) excede el tope de
        longitud o trae caracteres de control (D3).
      - `EscrituraRechazadaError` si el perfil no está CONFORME (C1).
      - `RutaNoSeguraError` si la ruta es un symlink o cae fuera de bóveda.
      - `DestinoNoSeguroError` si el predicado de destino seguro dice que no.
      - `ConflictoEscrituraError` (409) si la huella no coincide, ahora o
        justo antes de escribir.

    NO-OP = NO ESCRIBE (R1, revisión independiente de PR #258, segunda
    ronda): si `nuevo_label` normalizado ya es exactamente el label actual
    (incluido el caso "sin label y se pide borrar sin label"), la función
    NO toca el fichero: cero bytes, cero `os.replace`, mismo hash. Ésta es
    la ÚNICA situación con byte-a-byte garantizado.

    Para un cambio REAL, la garantía es más estrecha de lo que este módulo
    prometía antes: se preserva SEMÁNTICAMENTE toda clave de `metadata`
    desconocida (nada se pierde, nada se reordena en el `dict`), pero NO se
    promete un diff mínimo en bytes. Si el perfil en disco estaba en un
    formato distinto al de salida de este módulo (el caso real: una sola
    línea compacta, no `indent=2`), la reserialización reformatea el
    documento entero. Preservar el formato byte a byte en un cambio real
    exigiría parchear el texto en vez de parsear+reserializar, y eso no
    está hecho aquí.
    """
    ruta_perfil = carpeta_juego / sources_catalog.NOMBRE_PERFIL
    _asegurar_ruta_segura(ruta_perfil)

    valor_normalizado = nuevo_label.strip()
    if valor_normalizado:
        motivo_entrada = _label_entrada_invalida(valor_normalizado)
        if motivo_entrada is not None:
            raise EntradaInvalidaError(motivo_entrada)

    lectura = leer_estado_perfil(ruta_perfil)
    if lectura.estado != EstadoPerfil.CONFORME:
        raise EscrituraRechazadaError(lectura.estado, lectura.causa or "perfil no editable")

    if not lectura.huella.coincide_contenido(huella_cliente):
        raise ConflictoEscrituraError(
            "el perfil cambió desde que se leyó: la huella no coincide. "
            "El contenido escrito por quien lo cambió sigue en disco."
        )

    if valor_normalizado == lectura.label_actual:
        # R1 — NO-OP: nada que escribir. Cubre tanto "borrar sobre un perfil
        # que ya no tiene label" como "guardar el mismo label que ya está".
        # Ni se ejerce el predicado de destino (no hay escritura que
        # proteger) ni se toca `datos`/`metadata`: un `pop` sobre una
        # `metadata` que no existía la CREARÍA como `{}` por el propio
        # `datos["metadata"] = metadata` de abajo, y eso ya es un cambio en
        # el fichero aunque no haya ningún label que borrar.
        return lectura

    ok, motivo = destino_admite_escritura_segura(carpeta_juego)
    if not ok:
        raise DestinoNoSeguroError(
            f"legible pero no admite edición segura de metadata desde S9-Knowledge: {motivo}"
        )

    # MUTA el dict original — nunca reconstruye desde el dataclass, nunca
    # `to_json()`. Esto llega hasta aquí porque ES un cambio real (el no-op
    # ya salió arriba sin tocar nada): preserva toda clave de `metadata`
    # desconocida y su ORDEN dentro del dict, pero NO promete bytes
    # mínimos -- `_escribir_atomico` reserializa el documento entero con
    # `json.dumps(indent=2)`, que reformatea un original compacto aunque el
    # contenido semántico no tocado sea idéntico (ver docstring del módulo).
    datos = lectura.datos
    metadata = datos.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        datos["metadata"] = metadata
    if valor_normalizado:
        metadata["label"] = valor_normalizado
    else:
        # D2 — vacío BORRA la clave, nunca escribe cadena vacía.
        metadata.pop("label", None)

    # Autoridad de validación TAMBIÉN en la salida.
    _perfil_salida, error_salida = _game_profile_from_dict(datos)
    if error_salida is not None:  # pragma: no cover - no debería alcanzarse
        raise EscrituraRechazadaError(EstadoPerfil.LEGIBLE_NO_CONFORME, CAUSA_NO_CONFORME)

    # Revalidación JUSTO ANTES de escribir: REDUCE la ventana de TOCTOU a dos
    # comprobaciones, no la cierra (D4 — ver el aviso en el docstring del
    # módulo: sin cerrojo real, un tercero puede colarse entre esta
    # comprobación y `os.replace`).
    huella_justo_antes = huella_de(ruta_perfil)
    if not huella_justo_antes.coincide_contenido(huella_cliente):
        raise ConflictoEscrituraError(
            "el perfil cambió justo antes de escribir: la huella no coincide. "
            "El contenido escrito por quien lo cambió sigue en disco."
        )

    _escribir_atomico(ruta_perfil, datos)
    return leer_estado_perfil(ruta_perfil)


# ---------------------------------------------------------------------------
# CORTE 6B-2(b) — el nombre humano de la PARTIDA. Contrato en
# `app.partida_manifest_contract` (ManifiestoPartida); todo lo demás -- huella,
# escritura atómica, destino seguro, contrato de ENTRADA del label -- se
# REUTILIZA de arriba, sin duplicar ninguna de esas reglas.
# ---------------------------------------------------------------------------

def escribir_label_partida(
    carpeta_partida: Path,
    nuevo_label: str,
    huella_cliente: Huella,
) -> LecturaManifiestoPartida:
    """Escribe o BORRA `metadata.label` en el `manifiesto-partida.json` de
    `carpeta_partida`.

    Mismo contrato de comportamiento que `escribir_label_workspace`, con dos
    diferencias que vienen de que el manifiesto de partida es OPCIONAL (a
    diferencia del perfil, que siempre existe):

      - Sin manifiesto todavía, `leer_estado_manifiesto_partida` lo trata
        como CONFORME con `datos={}` y `huella_ausente()`. Escribir un label
        real en ese estado CREA el fichero (con `_escribir_atomico`, que no
        exige que el destino exista de antemano); esto NO "crea la partida"
        -- la partida ya existía, descubierta por
        `sources_catalog.partidas_descubiertas_en_boveda` antes de que el
        llamador pudiera siquiera ofrecer este formulario (decisión del
        operador, C2: "conceder es crear", no "nombrar es crear").
      - `nuevo_label` vacío sobre un manifiesto AUSENTE es un NO-OP que
        jamás crea el fichero: no hay nada que borrar y no se fabrica un
        `manifiesto-partida.json` vacío solo por haber pulsado "Guardar".

    `carpeta_partida` la resuelve el llamador con la MISMA autoridad que ya
    usa la presentación (`presentacion_etiquetas.carpeta_de_juego_de_workspace`
    + `<juego>/partidas/<partida_id>`), nunca componiendo la ruta a mano desde
    un `partida_id` sin validar contra la enumeración real de la bóveda.

    Lanza las mismas excepciones que `escribir_label_workspace`
    (`EntradaInvalidaError`, `EscrituraRechazadaError`, `RutaNoSeguraError`,
    `DestinoNoSeguroError`, `ConflictoEscrituraError`).
    """
    ruta_manifiesto = carpeta_partida / sources_catalog.NOMBRE_MANIFIESTO_PARTIDA
    _asegurar_ruta_segura(ruta_manifiesto, permitir_ausente=True)

    valor_normalizado = nuevo_label.strip()
    if valor_normalizado:
        motivo_entrada = _label_entrada_invalida(valor_normalizado)
        if motivo_entrada is not None:
            raise EntradaInvalidaError(motivo_entrada)

    lectura = leer_estado_manifiesto_partida(ruta_manifiesto)
    if lectura.estado != EstadoPerfil.CONFORME:
        raise EscrituraRechazadaError(lectura.estado, lectura.causa or "manifiesto no editable")

    if not lectura.huella.coincide_contenido(huella_cliente):
        raise ConflictoEscrituraError(
            "el manifiesto de partida cambió desde que se leyó (o se creó "
            "mientras tanto): la huella no coincide. El contenido escrito "
            "por quien lo cambió sigue en disco."
        )

    if valor_normalizado == lectura.label_actual:
        # NO-OP (mismo R1 que el workspace): incluye "borrar sobre un
        # manifiesto ausente o sin label" -- no se crea ningún fichero.
        return lectura

    ok, motivo = destino_admite_escritura_segura(carpeta_partida)
    if not ok:
        raise DestinoNoSeguroError(
            f"legible pero no admite edición segura de metadata desde S9-Knowledge: {motivo}"
        )

    # MUTA el dict (o el `{}` fresco de un manifiesto ausente) -- nunca
    # reconstruye desde el dataclass del contrato, nunca una serialización
    # propia que reordene claves.
    datos = lectura.datos if lectura.datos is not None else {}
    metadata = datos.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        datos["metadata"] = metadata
    if valor_normalizado:
        metadata["label"] = valor_normalizado
    else:
        metadata.pop("label", None)

    _manifiesto_salida, error_salida = _manifiesto_partida_from_dict(datos)
    if error_salida is not None:  # pragma: no cover - no debería alcanzarse
        raise EscrituraRechazadaError(EstadoPerfil.LEGIBLE_NO_CONFORME, CAUSA_NO_CONFORME_PARTIDA)

    # Revalidación JUSTO ANTES de escribir (mismo D4: reduce la ventana de
    # TOCTOU, no la cierra). Para un manifiesto que todavía no existía, esto
    # comprueba que SIGUE sin existir -- si un tercero lo creó mientras
    # tanto, es un conflicto real y se rechaza igual que cualquier otro.
    huella_justo_antes = _huella_actual_o_ausente(ruta_manifiesto)
    if not huella_justo_antes.coincide_contenido(huella_cliente):
        raise ConflictoEscrituraError(
            "el manifiesto de partida cambió justo antes de escribir: la "
            "huella no coincide. El contenido escrito por quien lo cambió "
            "sigue en disco."
        )

    _escribir_atomico(ruta_manifiesto, datos)
    return leer_estado_manifiesto_partida(ruta_manifiesto)
