# -*- coding: utf-8 -*-
"""UNA autoridad para la identidad de servicio y el estado privado (H-06 + H-08).

POR QUE ESTE MODULO EXISTE
--------------------------
Antes de este carril habia al menos TRES politicas de propietario y de modo:
la unidad del visor (root, sin ``User=``), la unidad del worker (``www-data``,
``UMask=0077``) y la plantilla Ansible (``www-data`` repetido en cuatro sitios);
y ``auth.db`` nacia con la umask del proceso (0644), ``review.sqlite3`` con
0660 y ``.csrf_secret`` con 0600. Cada una de esas cifras era una verdad
distinta del mismo hecho.

AQUI, y SOLO AQUI, se declaran las cuatro cifras del contrato (§22):

  * ``SERVICE_USER`` / ``SERVICE_GROUP``  -> ``s9knowledge`` (no ``www-data``);
  * STATE ROOT  -> ``DEFAULT_STATE_ROOT`` (la raiz que ya existia; no se crea
    una segunda) y las rutas que cuelgan de ella;
  * ``FILE_MODE``  -> 0600;
  * ``DIR_MODE``   -> 0700.

De aqui beben, por CLI (``python3 service_state.py get ...``) o por import:
``deploy.sh``, ``lib.sh``, ``validate_deploy.sh``, ``review_store.py``,
``migrar_estado.py``, el preflight de arranque del visor y del worker, y los
tests que cruzan las unidades systemd y Ansible contra estas constantes.
Las unidades son ficheros estaticos (systemd no tiene AST): no pueden leer
este modulo, asi que un test estructural las compara con el (gate M12).

DIRECCION DE IMPORTACION
------------------------
Mismo patron que ``review_paths``: el resolvedor vive en el motor y es el
visor quien lo importa (motor y visor publican dos paquetes ``app``).

LO QUE ESTE MODULO NO AFIRMA (TECHO DECLARADO, §14)
---------------------------------------------------
* Mide propietario, modo, tipo, enlaces simbolicos y acceso EFECTIVO del
  proceso. Detecta la PRESENCIA de ACL POSIX extendidas (xattr) y falla
  cerrado si las hay, pero no las interpreta.
* No audita capacidades de Linux, SELinux/AppArmor ni montajes: 0600 es el
  objetivo, no una prueba de aislamiento absoluto frente a root.
* Fuera del servicio por diseno: ``<state>/deploy`` (registros del
  instalador, ``root:root``) y la boveda de Obsidian (``S9K_VAULT_ROOT``,
  del operador).
"""
from __future__ import annotations

import argparse
import grp
import os
import pwd
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

__all__ = [
    "SERVICE_USER", "SERVICE_GROUP", "DEFAULT_STATE_ROOT", "FILE_MODE",
    "DIR_MODE", "UNIT_UMASK", "UNIT_UMASK_INT", "ENFORCE_ENV", "STATE_ROOT_ENV",
    "ADMIN_SUBTREES", "SERVICE_SUBDIRS", "STATE_PATH_VARS",
    "REVIEW_DECISIONS_ENV", "GLOSSARY_DIR_ENV", "RUNUSER_PREFIX",
    "Violation", "ServiceStateError", "effective_paths", "inspect_state",
    "inspect_process_identity", "probe_effective", "probe_denied", "enforce", "canonical_cli_command",
    "mode_is_private", "expected_ids", "format_violations",
]

# --------------------------------------------------------------------------
# LAS CUATRO CIFRAS DEL CONTRATO (§22)
# --------------------------------------------------------------------------
SERVICE_USER = "s9knowledge"
SERVICE_GROUP = "s9knowledge"
DEFAULT_STATE_ROOT = "/var/lib/s9-knowledge"
FILE_MODE = 0o600
DIR_MODE = 0o700
#: ``UMask=`` de las unidades: es ``~FILE_MODE & 0o777 & ~DIR_MODE ...`` en
#: octal de cuatro cifras; derivado para que no sea una quinta cifra suelta.
UNIT_UMASK_INT = 0o777 & ~DIR_MODE
UNIT_UMASK = "%04o" % UNIT_UMASK_INT

#: Variable que ENCIENDE la comprobacion de arranque. La fijan las unidades
#: systemd de produccion; en desarrollo y CI no esta y el servicio arranca con
#: los defectos de desarrollo (TECHO DECLARADO: sin la variable no hay
#: comprobacion; ``validate_deploy.sh`` la exige en la unidad).
ENFORCE_ENV = "S9K_STATE_ENFORCE"
#: Raiz del estado que ve el proceso. Es la MISMA raiz del despliegue
#: (``S9K_STATE_ROOT`` de lib.sh); aqui solo se hace visible al runtime.
STATE_ROOT_ENV = "S9K_STATE_ROOT"

#: Subarboles del state root que NO son del servicio sino de quien instala
#: (``root:root``): el servicio no los lee ni los escribe.
ADMIN_SUBTREES = ("deploy",)

#: Directorios del state root que pertenecen al servicio. Una sola lista para
#: Ansible (rol ``common``), ``deploy.sh`` y los tests.
SERVICE_SUBDIRS = (
    "auth", "jobs", "state", "output", "staging", "backups",
    "reviews-v3", "reviews-v3/proposals", "health",
)

REVIEW_DECISIONS_ENV = "S9K_V3_REVIEW_DECISIONS_PATH"
GLOSSARY_DIR_ENV = "S9K_V3_GLOSSARY_CANDIDATES_DIR"
_REVIEW_DB_ENV = "S9K_V3_REVIEW_DATABASE_PATH"
_PROPOSALS_ENV = "S9K_V3_REVIEW_PROPOSALS_DIR"
_AUTH_DB_ENV = "S9K_AUTH_DB_PATH"
_JOBS_DB_ENV = "S9K_JOBS_DB"
_HEALTH_ENV = "S9K_HEALTH_REPORT_PATH"
_BACKUP_ENV = "S9K_BACKUP_DIR"

#: Variable -> (tipo, clave logica). Inventario de rutas de estado que se
#: declaran por entorno (el resto del inventario esta en deploy/README.md).
STATE_PATH_VARS = {
    _AUTH_DB_ENV: ("file", "auth_db"),
    _JOBS_DB_ENV: ("file", "jobs_db"),
    _REVIEW_DB_ENV: ("file", "review_db"),
    _PROPOSALS_ENV: ("dir", "proposals"),
    REVIEW_DECISIONS_ENV: ("file", "decisions"),
    GLOSSARY_DIR_ENV: ("dir", "glossary"),
    _HEALTH_ENV: ("file", "health_report"),
    _BACKUP_ENV: ("dir", "backups"),
}

#: Prefijo canonico para ejecutar la CLI de auth u otra herramienta que ESCRIBE
#: estado (§12). Un solo sitio: README, helpers y el rechazo del propio CLI.
RUNUSER_PREFIX = ("runuser", "-u", SERVICE_USER, "--")

#: Variables que cada rol EXIGE declaradas (no se admite el defecto de
#: desarrollo, que cae dentro de la release).
REQUIRED_BY_ROLE = {
    "viewer": (_AUTH_DB_ENV, _JOBS_DB_ENV, _REVIEW_DB_ENV, _PROPOSALS_ENV),
    "worker": (_JOBS_DB_ENV, _REVIEW_DB_ENV, _PROPOSALS_ENV),
    "health": (_AUTH_DB_ENV, _JOBS_DB_ENV),
}

#: Prefijos en los que NUNCA puede vivir estado mutable (la release es codigo).
RELEASE_PREFIXES = ("/opt/s9-knowledge/releases", "/opt/s9-knowledge/current")

_ACL_XATTRS = ("system.posix_acl_access", "system.posix_acl_default")
_REPO_ROOT = Path(__file__).resolve().parents[3]


def canonical_cli_command(*args: str) -> str:
    """El comando canonico para una herramienta que escribe estado (§12)."""
    return " ".join(RUNUSER_PREFIX + tuple(args))


def mode_is_private(mode: int, *, directory: bool) -> bool:
    """¿Es ``mode`` tan restrictivo como el canonico y aun utilizable?

    Privado = sin bit alguno para grupo/otros y sin bits especiales; utilizable
    = el propietario conserva rw (rwx en directorios). No exige la igualdad
    exacta con 0600/0700 (un 0400 es mas estricto, no un fallo, §13/§14); lo
    que fija el modo exacto es la migracion (``migrar_estado.py``).
    """
    perm = stat.S_IMODE(mode)
    if perm & 0o7077:
        return False
    necesario = 0o700 if directory else 0o600
    return (perm & necesario) == necesario


# --------------------------------------------------------------------------
# Hallazgos
# --------------------------------------------------------------------------
OWNER = "OWNER"
MODE = "MODE"
TYPE = "TYPE"
SYMLINK = "SYMLINK"
OUTSIDE_STATE = "OUTSIDE_STATE"
IN_RELEASE = "IN_RELEASE"
NOT_ABSOLUTE = "NOT_ABSOLUTE"
MISSING_VAR = "MISSING_VAR"
NO_STATE_ROOT = "NO_STATE_ROOT"
NO_ACCESS = "NO_ACCESS"
ACL = "ACL"
IDENTITY = "IDENTITY"
UNREADABLE = "UNREADABLE"


@dataclass(frozen=True)
class Violation:
    code: str
    path: str
    detail: str

    def message(self) -> str:
        return "%s [%s]: %s" % (self.path, self.code, self.detail)


class ServiceStateError(RuntimeError):
    """El estado o la identidad no cumplen el contrato: el servicio NO arranca."""

    def __init__(self, violations: Sequence[Violation]):
        self.violations = tuple(violations)
        super().__init__(format_violations(self.violations))


def format_violations(violations: Iterable[Violation]) -> str:
    lineas = ["STATE_CONTRACT_VIOLATION (estado/identidad del servicio, H-06/H-08):"]
    lineas += ["  - " + v.message() for v in violations]
    lineas.append("  El servicio no arranca (fail-closed). Reparacion: ejecutar el "
                  "despliegue (deploy.sh migra y corrige propietario y modos); "
                  "no abrir permisos a mano.")
    return "\n".join(lineas)


def expected_ids(user: str = SERVICE_USER, group: str = SERVICE_GROUP):
    """(uid, gid) del usuario/grupo de servicio, o ``(None, None)`` si no existen."""
    try:
        uid = pwd.getpwnam(user).pw_uid
    except KeyError:
        uid = None
    try:
        gid = grp.getgrnam(group).gr_gid
    except KeyError:
        gid = None
    return uid, gid


def _nombre_uid(uid: int) -> str:
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def _nombre_gid(gid: int) -> str:
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return str(gid)


# --------------------------------------------------------------------------
# Rutas efectivas (UNA derivacion para visor, worker y despliegue)
# --------------------------------------------------------------------------
def effective_paths(env: Mapping[str, str], *, role: str = "viewer"):
    """Rutas de estado que el proceso USARA, segun el entorno.

    Devuelve ``(rutas, violaciones)``: ``rutas`` = ``{clave_logica: Path}`` para
    lo declarado o derivable; ``violaciones`` = variables exigidas al ``role``
    que faltan, vacias o relativas. Las derivaciones replican la del visor
    (``decisions.jsonl`` junto a ``review.sqlite3``; ``audit.jsonl`` junto a
    las decisiones; candidatos de glosario junto a las decisiones) y el visor
    DELEGA aqui, de modo que no hay una segunda derivacion.
    """
    violaciones: list = []
    rutas: dict = {}
    requeridas = REQUIRED_BY_ROLE.get(role, ())
    for var, (_tipo, clave) in STATE_PATH_VARS.items():
        crudo = (env.get(var) or "").strip()
        if not crudo:
            if var in requeridas:
                violaciones.append(Violation(
                    MISSING_VAR, var, "no declarada: el servicio caeria al "
                    "defecto de desarrollo DENTRO de la release"))
            continue
        if not os.path.isabs(crudo):
            violaciones.append(Violation(
                NOT_ABSOLUTE, var, "no es una ruta absoluta (%s)" % crudo))
            continue
        rutas[clave] = Path(os.path.normpath(crudo))
    if role == "viewer":
        if "decisions" not in rutas and "review_db" in rutas:
            rutas["decisions"] = rutas["review_db"].with_name("decisions.jsonl")
        if "decisions" in rutas:
            rutas["audit"] = rutas["decisions"].with_name("audit.jsonl")
            if "glossary" not in rutas:
                rutas["glossary"] = rutas["decisions"].parent / "glossary-candidates"
    return rutas, violaciones


def derived_decisions_path(env: Mapping[str, str]) -> Optional[Path]:
    """Ruta de ``decisions.jsonl`` derivada del entorno (None si no se puede)."""
    rutas, _ = effective_paths(env, role="viewer")
    return rutas.get("decisions")


def _bajo(ruta: Path, raiz: Path) -> bool:
    try:
        ruta.relative_to(raiz)
        return True
    except ValueError:
        return False


# --------------------------------------------------------------------------
# Inspeccion
# --------------------------------------------------------------------------
def _acl_presente(path: str) -> bool:
    try:
        nombres = os.listxattr(path, follow_symlinks=False)
    except (OSError, AttributeError):
        return False
    return any(n in nombres for n in _ACL_XATTRS)


def _revisar_entrada(path: str, st: os.stat_result, uid: Optional[int],
                     gid: Optional[int], user: str, group: str,
                     out: list) -> None:
    es_dir = stat.S_ISDIR(st.st_mode)
    if stat.S_ISLNK(st.st_mode):
        out.append(Violation(SYMLINK, path, "es un enlace simbolico; el estado "
                             "del servicio no admite symlinks"))
        return
    if not (es_dir or stat.S_ISREG(st.st_mode)):
        out.append(Violation(TYPE, path, "tipo no admitido en el estado "
                             "(solo ficheros regulares y directorios)"))
        return
    if (uid is not None and st.st_uid != uid) or (gid is not None and st.st_gid != gid):
        out.append(Violation(
            OWNER, path, "tiene owner %s:%s; esperado %s:%s" % (
                _nombre_uid(st.st_uid), _nombre_gid(st.st_gid), user, group)))
    if not mode_is_private(st.st_mode, directory=es_dir):
        out.append(Violation(
            MODE, path, "tiene modo %04o; maximo permitido %04o (%s)" % (
                stat.S_IMODE(st.st_mode), DIR_MODE if es_dir else FILE_MODE,
                "directorio privado" if es_dir else "fichero privado")))
    if _acl_presente(path):
        out.append(Violation(
            ACL, path, "tiene ACL POSIX extendida: el modo ya no describe el "
            "acceso real (no se auditan ACL; techo declarado)"))


def inspect_state(state_root, *, uid: Optional[int] = None, gid: Optional[int] = None,
                  user: str = SERVICE_USER, group: str = SERVICE_GROUP,
                  declared: Optional[Mapping[str, Path]] = None,
                  skip: Sequence[str] = ADMIN_SUBTREES,
                  release_prefixes: Sequence[str] = RELEASE_PREFIXES,
                  max_entries: int = 200000):
    """Mira el state root SIN tocarlo. Devuelve la lista de ``Violation``.

    * raiz: existe, es directorio real (no symlink), propietario y modo;
    * arbol completo (salvo ``skip``): propietario, modo, tipo, symlinks, ACL;
    * ``declared``: cada ruta declarada cuelga de la raiz (no de la release,
      ni de otro sitio) y, si existe, es del tipo esperado.

    ``uid``/``gid`` por defecto son los del usuario de servicio real; en tests
    se inyectan los del proceso. Si el usuario no existe y no se inyecta,
    el propio hecho es una violacion (IDENTITY).
    """
    out: list = []
    if uid is None or gid is None:
        real_uid, real_gid = expected_ids(user, group)
        uid = real_uid if uid is None else uid
        gid = real_gid if gid is None else gid
        if real_uid is None and uid is None:
            out.append(Violation(IDENTITY, user, "el usuario de servicio no "
                                 "existe en este sistema"))
        if real_gid is None and gid is None:
            out.append(Violation(IDENTITY, group, "el grupo de servicio no "
                                 "existe en este sistema"))
    raiz = Path(state_root)
    if not raiz.is_absolute():
        out.append(Violation(NOT_ABSOLUTE, str(raiz), "el state root no es absoluto"))
        return out
    try:
        st = os.lstat(raiz)
    except FileNotFoundError:
        out.append(Violation(NO_STATE_ROOT, str(raiz), "el state root no existe"))
        return out
    except OSError as exc:
        out.append(Violation(UNREADABLE, str(raiz), "no se puede inspeccionar: %s" % exc.strerror))
        return out
    if not stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode):
        out.append(Violation(TYPE, str(raiz), "el state root no es un directorio"))
        return out
    _revisar_entrada(str(raiz), st, uid, gid, user, group, out)
    if stat.S_ISLNK(st.st_mode):
        return out

    skip_abs = {os.path.join(str(raiz), s) for s in skip}
    visto = 0
    pila = [str(raiz)]
    while pila:
        actual = pila.pop()
        try:
            with os.scandir(actual) as it:
                entradas = list(it)
        except OSError as exc:
            out.append(Violation(UNREADABLE, actual, "directorio ilegible o "
                                 "inaccesible: %s" % exc.strerror))
            continue
        for e in entradas:
            if e.path in skip_abs:
                continue
            visto += 1
            if visto > max_entries:
                out.append(Violation(TYPE, str(raiz), "el arbol supera %d entradas; "
                                     "no se audita entero (techo)" % max_entries))
                return out
            try:
                est = e.stat(follow_symlinks=False)
            except OSError as exc:
                out.append(Violation(UNREADABLE, e.path, "no se puede inspeccionar: %s" % exc.strerror))
                continue
            _revisar_entrada(e.path, est, uid, gid, user, group, out)
            if stat.S_ISDIR(est.st_mode):
                pila.append(e.path)

    for clave, ruta in sorted((declared or {}).items()):
        _revisar_declarada(clave, Path(ruta), raiz, release_prefixes, out)
    return out


def _revisar_declarada(clave: str, ruta: Path, raiz: Path,
                       release_prefixes: Sequence[str], out: list) -> None:
    for pfx in release_prefixes:
        if _bajo(ruta, Path(pfx)):
            out.append(Violation(IN_RELEASE, str(ruta), "%s: estado mutable "
                       "dentro de la release (%s); la release es codigo" % (clave, pfx)))
            return
    if _bajo(ruta, _REPO_ROOT) and not _bajo(ruta, raiz):
        out.append(Violation(IN_RELEASE, str(ruta), "%s: estado mutable bajo el "
                   "arbol del repositorio/release" % clave))
        return
    if not _bajo(ruta, raiz):
        out.append(Violation(OUTSIDE_STATE, str(ruta), "%s: no cuelga del state "
                   "root %s" % (clave, raiz)))
        return
    # Ningun componente entre la raiz y la ruta puede ser un symlink.
    parcial = raiz
    for parte in ruta.relative_to(raiz).parts:
        parcial = parcial / parte
        if os.path.islink(parcial):
            out.append(Violation(SYMLINK, str(parcial), "%s: componente de la "
                       "ruta que es un enlace simbolico" % clave))
            return


def _acceso(path: str, modos: int) -> bool:
    return os.access(path, modos)


def inspect_effective_access(state_root, declared: Mapping[str, Path]):
    """Acceso EFECTIVO del proceso actual (R/W/X real, no bits de modo)."""
    out: list = []
    raiz = str(state_root)
    if os.path.isdir(raiz) and not _acceso(raiz, os.R_OK | os.W_OK | os.X_OK):
        out.append(Violation(NO_ACCESS, raiz, "el proceso (uid %d) no puede "
                   "leer/escribir/atravesar el state root" % os.geteuid()))
    for clave, ruta in sorted(declared.items()):
        ruta = str(ruta)
        if os.path.isdir(ruta):
            if not _acceso(ruta, os.R_OK | os.W_OK | os.X_OK):
                out.append(Violation(NO_ACCESS, ruta, "%s: directorio no "
                           "escribible/legible por el proceso" % clave))
        elif os.path.isfile(ruta):
            if not _acceso(ruta, os.R_OK | os.W_OK):
                out.append(Violation(NO_ACCESS, ruta, "%s: fichero no "
                           "legible/escribible por el proceso" % clave))
        else:
            padre = os.path.dirname(ruta)
            if os.path.isdir(padre) and not _acceso(padre, os.W_OK | os.X_OK):
                out.append(Violation(NO_ACCESS, padre, "%s: no se puede crear "
                           "en el directorio padre" % clave))
    return out


def _probar_directorio(ruta: str, etiqueta: str, out: list) -> None:
    """Crea, escribe, lee y borra un temporal: acceso REAL de escritura."""
    tmp = os.path.join(ruta, ".s9k-probe-%d" % os.getpid())
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
        try:
            os.write(fd, b"probe")
        finally:
            os.close(fd)
        with open(tmp, "rb") as fh:
            fh.read()
    except OSError as exc:
        out.append(Violation(NO_ACCESS, ruta, "%s: no se puede crear/escribir/leer (%s)"
                             % (etiqueta, exc.strerror)))
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def probe_effective(state_root, declared: Mapping[str, Path]):
    """Acceso EFECTIVO por efecto, sin sqlite: abre y escribe de verdad.

    Se ejecuta COMO el usuario de servicio (``runuser -u``). Para cada ruta
    declarada: directorio -> temporal creado/escrito/leido/borrado; fichero
    existente -> abierto en lectura+escritura SIN modificarlo; fichero
    ausente -> su directorio padre se prueba como directorio.
    """
    out: list = []
    if os.geteuid() == 0:
        return [Violation(IDENTITY, "proceso", "la prueba por efecto se ejecuta "
                "como el usuario de servicio, no como root")]
    raiz = str(state_root)
    _probar_directorio(raiz, "state root", out)
    for clave, ruta in sorted(declared.items()):
        ruta = str(ruta)
        if os.path.isdir(ruta):
            _probar_directorio(ruta, clave, out)
        elif os.path.isfile(ruta):
            try:
                with open(ruta, "r+b") as fh:
                    fh.read(1)
            except OSError as exc:
                out.append(Violation(NO_ACCESS, ruta, "%s: no se abre en lectura+escritura (%s)"
                                     % (clave, exc.strerror)))
        else:
            padre = os.path.dirname(ruta)
            if os.path.isdir(padre):
                _probar_directorio(padre, clave, out)
    return out


def probe_denied(state_root, declared: Mapping[str, Path]):
    """Otro usuario local NO accede al estado (N15/N16). Se ejecuta como ``nobody``."""
    out: list = []
    if os.geteuid() == 0:
        return [Violation(IDENTITY, "proceso", "la prueba de denegacion se ejecuta "
                "como un usuario sin privilegios, no como root")]
    raiz = str(state_root)
    try:
        os.listdir(raiz)
        out.append(Violation(MODE, raiz, "un usuario ajeno puede LISTAR el state root"))
    except OSError:
        pass
    for clave, ruta in sorted(declared.items()):
        ruta = str(ruta)
        for candidato in (ruta, ruta + "-wal", ruta + "-shm"):
            if not os.path.lexists(candidato):
                # Con la raiz cerrada no se puede ni preguntar; ausente o
                # inaccesible son equivalentes para esta prueba.
                continue
            try:
                if os.path.isdir(candidato):
                    os.listdir(candidato)
                else:
                    with open(candidato, "rb") as fh:
                        fh.read(1)
                out.append(Violation(MODE, candidato, "%s: un usuario ajeno LEE esta "
                                     "ruta (debe estar denegado)" % clave))
            except OSError:
                continue
    return out


def inspect_process_identity(user: str = SERVICE_USER, *,
                             euid: Optional[int] = None):
    """El proceso corre como el usuario de servicio y NO como root."""
    euid = os.geteuid() if euid is None else euid
    if euid == 0:
        return [Violation(IDENTITY, "proceso", "corre como root (uid 0); el "
                "servicio corre como %s. Una ruta alternativa de arranque "
                "(unidad sin User=, docker, nohup) no esta permitida" % user)]
    uid, _ = expected_ids(user, SERVICE_GROUP)
    if uid is None:
        return [Violation(IDENTITY, user, "el usuario de servicio no existe")]
    if euid != uid:
        return [Violation(IDENTITY, "proceso", "corre como uid %d (%s); "
                "esperado %s (uid %d)" % (euid, _nombre_uid(euid), user, uid))]
    return []


def enforce(role: str, env: Optional[Mapping[str, str]] = None, *,
            uid: Optional[int] = None, gid: Optional[int] = None,
            euid: Optional[int] = None, force: bool = False) -> bool:
    """Comprobacion de ARRANQUE (viewer y worker). Fail-closed.

    Devuelve ``False`` sin hacer nada si no esta encendida (``S9K_STATE_ENFORCE``
    ausente y ``force`` falso: desarrollo/CI, techo declarado). Si esta
    encendida y algo no cumple, levanta ``ServiceStateError`` con el
    diagnostico concreto (owner real vs esperado, modo real vs maximo...).
    ``uid/gid/euid`` se inyectan en tests; en produccion salen del sistema.
    """
    env = os.environ if env is None else env
    if not force and (env.get(ENFORCE_ENV) or "").strip().lower() not in ("1", "true", "yes"):
        return False
    violaciones: list = []
    violaciones += inspect_process_identity(euid=euid)
    raiz = (env.get(STATE_ROOT_ENV) or "").strip()
    if not raiz:
        violaciones.append(Violation(
            NO_STATE_ROOT, STATE_ROOT_ENV, "no declarada: el servicio no sabe "
            "cual es su state root"))
        raise ServiceStateError(violaciones)
    rutas, faltan = effective_paths(env, role=role)
    violaciones += faltan
    violaciones += inspect_state(raiz, uid=uid, gid=gid, declared=rutas)
    violaciones += inspect_effective_access(raiz, rutas)
    if violaciones:
        raise ServiceStateError(violaciones)
    return True


# --------------------------------------------------------------------------
# CLI (para bash y Ansible: una sola fuente de las cifras)
# --------------------------------------------------------------------------
def _leer_env_file(ruta: str) -> dict:
    """Lee un EnvironmentFile ``VAR=valor`` (sin comentarios finales)."""
    datos: dict = {}
    for linea in Path(ruta).read_text(encoding="utf-8").splitlines():
        s = linea.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        datos[k.strip()] = v
    return datos


_GETTERS = {
    "service_user": lambda: SERVICE_USER,
    "service_group": lambda: SERVICE_GROUP,
    "state_root": lambda: DEFAULT_STATE_ROOT,
    "file_mode": lambda: "%04o" % FILE_MODE,
    "dir_mode": lambda: "%04o" % DIR_MODE,
    "umask": lambda: UNIT_UMASK,
    "subdirs": lambda: "\n".join(SERVICE_SUBDIRS),
    "runuser_prefix": lambda: " ".join(RUNUSER_PREFIX),
}


def env_de(ruta: str) -> dict:
    return _leer_env_file(ruta)


def _rutas_de_stdin() -> dict:
    rutas: dict = {}
    for linea in sys.stdin.read().splitlines():
        if "=" in linea:
            k, v = linea.split("=", 1)
            rutas[k.strip()] = Path(v.strip())
    return rutas


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="orden", required=True)
    g = sub.add_parser("get", help="imprime una cifra de la autoridad")
    g.add_argument("clave", choices=sorted(_GETTERS))
    v = sub.add_parser("validate-env", help="las rutas de estado de un env-file "
                       "cuelgan del state root y estan declaradas (misma funcion "
                       "que el arranque)")
    v.add_argument("--env-file", required=True)
    v.add_argument("--state-root", default=DEFAULT_STATE_ROOT)
    v.add_argument("--role", default="viewer", choices=sorted(REQUIRED_BY_ROLE))
    c = sub.add_parser("check", help="inspecciona el state root (solo lectura)")
    c.add_argument("--state-root", default=DEFAULT_STATE_ROOT)
    c.add_argument("--env-file", default=None)
    c.add_argument("--role", default="viewer", choices=sorted(REQUIRED_BY_ROLE))
    c.add_argument("--uid", type=int, default=None)
    c.add_argument("--gid", type=int, default=None)
    a = sub.add_parser("access", help="acceso EFECTIVO por efecto del proceso actual (se "
                       "ejecuta con runuser como el usuario de servicio)")
    a.add_argument("--state-root", default=DEFAULT_STATE_ROOT)
    pp = sub.add_parser("paths", help="imprime clave=ruta de las rutas de estado efectivas "
                        "(lo ejecuta root; el usuario de servicio no puede leer /etc)")
    pp.add_argument("--env-file", required=True)
    pp.add_argument("--role", default="viewer", choices=sorted(REQUIRED_BY_ROLE))
    a.add_argument("--paths-stdin", action="store_true",
                   help="las rutas llegan por stdin como clave=ruta (salida de `paths`)")
    d = sub.add_parser("deny", help="un usuario ajeno NO accede al estado (se "
                       "ejecuta con runuser como nobody)")
    d.add_argument("--state-root", default=DEFAULT_STATE_ROOT)
    d.add_argument("--paths-stdin", action="store_true")
    args = ap.parse_args(argv)

    if args.orden == "get":
        print(_GETTERS[args.clave]())
        return 0
    env = {}
    if args.orden in ("validate-env", "check") and getattr(args, "env_file", None):
        env = _leer_env_file(args.env_file)
    if args.orden == "validate-env":
        rutas, faltan = effective_paths(env, role=args.role)
        viol = list(faltan)
        for clave, ruta in sorted(rutas.items()):
            _revisar_declarada(clave, ruta, Path(args.state_root), RELEASE_PREFIXES, viol)
        declarada = (env.get(STATE_ROOT_ENV) or "").strip()
        if not declarada:
            viol.append(Violation(NO_STATE_ROOT, STATE_ROOT_ENV,
                        "no declarada: el arranque fail-closed del servicio no sabria cual "
                        "es su state root (declarar %s=%s)" % (STATE_ROOT_ENV, args.state_root)))
        elif os.path.normpath(declarada) != os.path.normpath(args.state_root):
            viol.append(Violation(NO_STATE_ROOT, STATE_ROOT_ENV,
                        "vale %s pero el despliegue usa %s" % (declarada, args.state_root)))
    elif args.orden == "check":
        rutas, faltan = effective_paths(env, role=args.role) if env else ({}, [])
        viol = list(faltan) + inspect_state(args.state_root, uid=args.uid, gid=args.gid,
                                            declared=rutas)
    elif args.orden == "paths":
        rutas, faltan = effective_paths(env_de(args.env_file), role=args.role)
        if faltan:
            print(format_violations(faltan), file=sys.stderr)
            return 3
        for clave, ruta in sorted(rutas.items()):
            print("%s=%s" % (clave, ruta))
        return 0
    elif args.orden == "deny":
        rutas = _rutas_de_stdin() if args.paths_stdin else {}
        viol = probe_denied(args.state_root, rutas)
    else:  # access
        rutas = _rutas_de_stdin() if args.paths_stdin else {}
        viol = inspect_process_identity() + probe_effective(args.state_root, rutas)
    if viol:
        print(format_violations(viol), file=sys.stderr)
        return 3
    print("OK")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
