"""Bootstrap seguro del secreto CSRF para una instalación de fábrica.

Con `S9K_AUTH_ENABLED=true` el arranque exige un secreto CSRF fuerte (ver
`app.auth.security.enforce_auth_security`). Antes de este módulo, una
instalación nueva que copiara `.env.example` a `.env` y arrancara sin tocar
nada más se encontraba con el arranque abortado: no había valor, y ponerlo
significaba abrir un terminal y fabricar uno a mano. Eso es exactamente lo
que la propiedad "instalación cerrada de fábrica" prohíbe.

No se acepta un valor fijo en `.env.example` (el repo es público: un secreto
en el repo no es un secreto) ni ningún valor por defecto adivinable en
código. La única alternativa legítima es generarlo EN LA MÁQUINA, la primera
vez, y persistirlo para que los arranques siguientes lo reutilicen — si no se
persistiera, cada reinicio invalidaría todas las sesiones vivas en silencio.

Reglas de este módulo:
- El secreto NUNCA se imprime: no en logs, no en la UI, no en argv, no en
  mensajes de error. Sólo vive en el fichero y en memoria del proceso.
- Si `S9K_CSRF_SECRET` viene explícito (no vacío) en el entorno, ese valor
  manda tal cual: no se toca, no se persiste, no se compara con el fichero.
  Quien lo fija a mano conserva la última palabra (producción con múltiples
  instancias, por ejemplo, necesita un secreto compartido explícito).
- El fichero se guarda junto a la auth DB (mismo directorio que
  `S9K_AUTH_DB_PATH`), con permisos `0600`, y sólo cuando esa ruta es
  absoluta. Si no lo es, este módulo no hace nada: `validate_auth_db_path`
  es quien diagnostica esa ruta y aborta el arranque por su cuenta. Con el
  default de fábrica (`DEFAULT_AUTH_DB_PATH` en `app.auth.config`), ese
  directorio está DENTRO del árbol del repositorio (`viewer/state/`,
  cubierto por `.gitignore`: nunca entra en `git add`/`commit`, pero un
  `tar`/`zip`/`rsync` del directorio completo SÍ lo incluye).
- Un fallo de E/S (disco lleno, permisos, ruta no escribible) se propaga
  como `CsrfSecretBootstrapError`: fail-closed. Nunca un secreto "de
  emergencia" que sólo vive en memoria del proceso.
"""
from __future__ import annotations

import logging
import os
import secrets
import tempfile
from pathlib import Path

log = logging.getLogger("s9k.auth.csrf_bootstrap")

#: Nombre del fichero que guarda el secreto generado, junto a la auth DB.
CSRF_SECRET_FILENAME = ".csrf_secret"

#: Bytes de entropía del secreto generado (antes de codificar en url-safe).
_GENERATED_SECRET_BYTES = 48

#: Reintentos de la reclamación del fichero ante un residuo vacío que
#: reaparece (dos hilos/procesos limpiando y regenerando a la vez). Un
#: número, no un bucle sin límite: si esto no converge en unos pocos
#: intentos, algo más está mal y hay que fallar cerrado, no colgarse.
_MAX_INTENTOS_RECLAMACION = 10


class CsrfSecretBootstrapError(RuntimeError):
    """La generación/lectura del secreto CSRF persistido falló. Fail-closed."""


def secret_file_path(auth_db_path: str) -> Path:
    """Ruta del fichero de secreto persistido, junto a la auth DB."""
    return Path(auth_db_path).parent / CSRF_SECRET_FILENAME


def _leer_secreto_existente(secret_path: Path) -> str | None:
    """Contenido del fichero si existe y NO está vacío; `None` en otro caso.

    Deja propagar cualquier `OSError` que no sea "no existe": una base
    ilegible por permisos, por ejemplo, no debe confundirse con "aún no
    hay secreto".
    """
    if not secret_path.exists():
        return None
    texto = secret_path.read_text(encoding="utf-8").strip()
    return texto or None


def resolve_csrf_secret(configured_secret: str, auth_db_path: str) -> str:
    """Devuelve el secreto CSRF a usar, generándolo/persistiéndolo si falta.

    - `configured_secret` no vacío -> se devuelve tal cual (gana lo
      explícito, sin tocar disco).
    - vacío y `auth_db_path` absoluto -> lee el fichero persistido junto a
      la DB; si no existe (o está vacío/corrupto), genera uno nuevo, lo
      escribe con permisos `0600` de forma atómica y lo devuelve.
    - vacío y `auth_db_path` NO absoluto (o vacío) -> devuelve `""` sin
      tocar disco: no es responsabilidad de este módulo diagnosticar esa
      ruta, lo hace `validate_auth_db_path`.

    SEGURO ANTE VARIOS PROCESOS ARRANCANDO A LA VEZ (`uvicorn --workers N`,
    gunicorn, varios contenedores compartiendo el mismo `S9K_AUTH_DB_PATH`
    en una instalación nueva). La reclamación del fichero usa `os.link`
    sobre un temporal ya escrito por completo, NUNCA `os.replace`: `replace`
    pisa el destino incondicionalmente, así que N procesos que no ven
    todavía el fichero generarían N secretos distintos y el ÚLTIMO en
    escribir ganaría en disco mientras los demás seguirían firmando EN
    MEMORIA con un secreto que ya no coincide con el fichero — CSRF y
    sesiones fallarían de forma intermitente, que es la peor manera de
    fallar. `os.link` falla con `FileExistsError` si el destino ya existe:
    sólo UNO reclama el nombre, y el resto relee el secreto del ganador en
    vez de quedarse con el propio.
    """
    value = (configured_secret or "").strip()
    if value:
        return configured_secret

    if not auth_db_path or not Path(auth_db_path).is_absolute():
        return ""

    secret_path = secret_file_path(auth_db_path)
    try:
        existente = _leer_secreto_existente(secret_path)
        if existente:
            return existente

        secret_path.parent.mkdir(parents=True, exist_ok=True)

        # `mkstemp`, no `f".tmp-{os.getpid()}"`: el PID identifica un
        # PROCESO, no un HILO. Varios hilos del MISMO proceso (un servidor
        # ASGI multi-hilo, o estos mismos hilos de test) comparten PID, así
        # que un nombre basado sólo en él colisiona entre hilos —cada uno
        # menos uno recibiría `FileExistsError` al crear su propio temporal,
        # antes incluso de llegar a la reclamación por `os.link`—. `mkstemp`
        # garantiza unicidad real entre procesos e hilos.
        new_secret = secrets.token_urlsafe(_GENERATED_SECRET_BYTES)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(secret_path.parent), prefix=f"{secret_path.name}.tmp-",
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(new_secret)
            os.chmod(tmp_path, 0o600)

            # RECLAMACIÓN por reintento acotado, NUNCA por un `unlink()`
            # incondicional antes de competir: un `unlink()` a ciegas del
            # destino "porque antes lo vimos vacío" puede borrar el fichero
            # de OTRO hilo/proceso que acaba de ganar la carrera un instante
            # antes (visto de verdad: con el unlink incondicional, un
            # tercer hilo podía leer el secreto del ganador A justo antes de
            # que un hilo B lo desalojara y lo sustituyera por el suyo — tres
            # secretos "correctos" por separado, divergentes entre sí). Aquí
            # sólo se retira el residuo si, EN EL MOMENTO de fallar el link,
            # sigue estando vacío/corrupto; si no, es un ganador legítimo y
            # se relee, sin tocarlo.
            for _intento in range(_MAX_INTENTOS_RECLAMACION):
                try:
                    os.link(str(tmp_path), str(secret_path))
                    break
                except FileExistsError:
                    try:
                        inodo_residuo = os.stat(secret_path)
                    except FileNotFoundError:
                        inodo_residuo = None
                    ganador = _leer_secreto_existente(secret_path)
                    if ganador:
                        return ganador
                    # Vacío/corrupto TODAVÍA en este instante: residuo de un
                    # disco lleno a mitad de una escritura anterior, no un
                    # ganador. Se retira y se reintenta la reclamación.
                    #
                    # Ventana residual, más estrecha (no bulletproof: dos
                    # `stat()` separados, no un único fd bloqueado): entre
                    # `inodo_residuo` y este `unlink()` otro hilo/proceso
                    # podría haber retirado el mismo residuo vacío y
                    # reclamado el nombre con SU secreto ya. Comparar el
                    # inodo antes de retirar evita borrar ese fichero ajeno:
                    # si cambió, ya no es el residuo que se leyó vacío, así
                    # que no se toca (el siguiente intento del bucle lo
                    # relee y, si ahora tiene contenido, lo devuelve).
                    if inodo_residuo is not None:
                        try:
                            actual = os.stat(secret_path)
                            mismo_fichero = (
                                (actual.st_dev, actual.st_ino)
                                == (inodo_residuo.st_dev, inodo_residuo.st_ino)
                            )
                            if mismo_fichero:
                                secret_path.unlink()
                        except FileNotFoundError:
                            pass
            else:
                raise CsrfSecretBootstrapError(
                    "no se pudo reclamar el secreto CSRF tras "
                    f"{_MAX_INTENTOS_RECLAMACION} intentos: residuo vacío "
                    "persistente en disco"
                )
        finally:
            tmp_path.unlink(missing_ok=True)

        log.info(
            "secreto CSRF generado y persistido en %s (permisos 0600, "
            "instalacion de fabrica).",
            secret_path,
        )
        return new_secret
    except OSError as exc:
        log.error(
            "no se pudo generar/leer el secreto CSRF persistido en %s: %s",
            secret_path, type(exc).__name__,
        )
        raise CsrfSecretBootstrapError(
            "no se pudo generar/leer el secreto CSRF persistido en disco"
        ) from exc
