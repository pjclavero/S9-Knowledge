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
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

__all__ = [
    "SERVICE_USER", "SERVICE_GROUP", "DEFAULT_STATE_ROOT", "FILE_MODE",
    "DIR_MODE", "UNIT_UMASK", "UNIT_UMASK_INT", "ENFORCE_ENV", "STATE_ROOT_ENV",
    "ADMIN_SUBTREES", "SERVICE_SUBDIRS", "STATE_PATH_VARS", "effective_state_root", "default_state_path",
    "inspect_secret", "probe_secret", "VALIDATION_EXCEPTION_ENV", "VALIDATION_EXCEPTION_VALUE",
    "DEFAULT_BACKUP_ROOT", "SECRETS_DIR", "SECRET_DIR_MODE", "SECRET_FILE_MAX_MODE",
    "CONFIG_DIR_MODE", "inspect_backup_root", "exception_declared",
    "REVIEW_DECISIONS_ENV", "GLOSSARY_DIR_ENV", "RUNUSER_PREFIX",
    "Violation", "ServiceStateError", "effective_paths", "inspect_state",
    "inspect_process_identity", "probe_effective", "probe_denied", "enforce", "canonical_cli_command",
    "mode_is_private", "expected_ids", "format_violations",
    # ronda 2: H-1 (CLIs/escritores), C-1, C-5 y C-7
    "CLI_ROOT_RC", "CLI_WRAPPER", "RootStateWriteError", "cli_root_rejection", "reject_root_cli",
    "refuse_root_state_write", "ensure_private_dir", "create_private_file", "open_private_write",
    "BACKUP_ENVS", "SYSTEM_DIRS", "KNOWN_TOP_LEVEL", "inspect_dedicated_state_root",
    "inspect_legacy_backups", "parse_unit", "inspect_unit_identity", "PRIVILEGED_GROUPS",
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

#: EXCEPCION EXPLICITA de tests/laboratorio (fase 2, §12). La comprobacion de
#: arranque es SIEMPRE obligatoria y fail-closed: ausencia de configuracion NO
#: significa "modo test". Solo este valor, declarado a proposito (los conftest de
#: la suite lo fijan), la omite, y la omision se ANUNCIA en el log. Esta variable
#: en un entorno/unidad operativa es un hallazgo que PARA el despliegue.
VALIDATION_EXCEPTION_ENV = "S9K_STATE_VALIDATION"
VALIDATION_EXCEPTION_VALUE = "disabled-explicit-for-tests"
#: Nombre HISTORICO (H-06 corte 1) que ya no gobierna nada; si aparece en una
#: unidad o env operativo se rechaza para que nadie crea que sigue siendo el interruptor.
ENFORCE_ENV = "S9K_STATE_ENFORCE"
#: Override OPCIONAL del state root. Si no se declara, el state root es
#: ``DEFAULT_STATE_ROOT`` (``effective_state_root``): ZERO-TERMINAL, nadie edita
#: .env para esto. Una sola funcion decide la raiz efectiva para todos.
STATE_ROOT_ENV = "S9K_STATE_ROOT"
#: Raiz de BACKUPS: SEPARADA del state vivo (nada root-owned dentro del state).
#: root:s9knowledge 0750 -> el healthcheck (s9knowledge) lee, no escribe.
DEFAULT_BACKUP_ROOT = "/var/backups/s9-knowledge"
#: SECRETOS provisionados (no son estado): se quedan en /etc, root:s9knowledge,
#: directorio 0750, fichero 0640 o mas restrictivo; el servicio los LEE, no los escribe.
SECRETS_DIR = "/etc/s9-knowledge/secrets"
SECRET_DIR_MODE = 0o750
SECRET_FILE_MAX_MODE = 0o640
CONFIG_DIR_MODE = 0o710

#: Subarboles del state root que NO son del servicio sino de quien instala
#: (``root:root``): el servicio no los lee ni los escribe.
ADMIN_SUBTREES = ("deploy",)

#: Directorios del state root que pertenecen al servicio. Una sola lista para
#: Ansible (rol ``common``), ``deploy.sh`` y los tests.
SERVICE_SUBDIRS = (
    "auth", "jobs", "state", "output", "staging",
    "reviews-v3", "reviews-v3/proposals", "health",
)

def _review_paths():
    """`review_paths` por ruta (misma instancia `_s9k_review_paths` que usan los guiones): el
    nombre de las variables de revision se LEE de su autoridad, no se repite aqui (N18 de C1)."""
    import importlib.util  # noqa: PLC0415
    nombre = "_s9k_review_paths"
    if nombre in sys.modules:
        return sys.modules[nombre]
    spec = importlib.util.spec_from_file_location(nombre, Path(__file__).with_name("review_paths.py"))
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    return modulo


_RP = _review_paths()
REVIEW_DECISIONS_ENV = _RP.REVIEW_DECISIONS_ENV
GLOSSARY_DIR_ENV = "S9K_V3_GLOSSARY_CANDIDATES_DIR"
_REVIEW_DB_ENV = _RP.REVIEW_DB_ENV
_PROPOSALS_ENV = _RP.PROPOSALS_DIR_ENV
_AUTH_DB_ENV = "S9K_AUTH_DB_PATH"
_JOBS_DB_ENV = "S9K_JOBS_DB"
_HEALTH_ENV = "S9K_HEALTH_REPORT_PATH"
_BACKUP_ENV = "S9K_BACKUP_DIR"
#: Las DOS variables que declaran la raiz de backups (el healthcheck acepta ambas:
#: ``S9K_BACKUP_ROOT`` y el nombre antiguo ``S9K_BACKUP_DIR``). Ninguna puede caer
#: dentro del state root (C-1, ronda 2).
BACKUP_ENVS = ("S9K_BACKUP_ROOT", _BACKUP_ENV)

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
    "S9K_GLOSSARY_DB": ("file", "glossary_db"),
    "S9K_EXTERNAL_AI_CACHE_DIR": ("dir", "external_ai_cache"),
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


# --------------------------------------------------------------------------
# H-1 (ronda 2) · CLIs y escritores: root NUNCA crea estado del servicio
# --------------------------------------------------------------------------
#: rc ESTABLE de toda CLI que rechaza a root (el que ya usaba la CLI de auth).
CLI_ROOT_RC = 4
#: Envoltorio canonico: lo ejecuta root (o sudo) y cambia al usuario de servicio
#: con ``runuser``; el entorno lo lee root de /etc/s9-knowledge y lo exporta.
CLI_WRAPPER = "deploy/scripts/s9k-cli.sh"


class RootStateWriteError(PermissionError):
    """Un proceso root iba a crear o escribir estado del servicio (N10/N14)."""


def cli_root_rejection(tool: str, *, euid: Optional[int] = None) -> Optional[str]:
    """Mensaje canonico de rechazo si el proceso es root; ``None`` si no lo es.

    UNA funcion para todas las CLIs que pueden crear o escribir estado: la de auth,
    la de salud, ``jobs``, ``glossary``... Ninguna "crea como root y arregla luego"
    (§12): un ``auth.db-wal``/``health.json``/``glossary.db`` de ``root:root`` deja al
    servicio sin arrancar. El mensaje da el comando canonico.
    """
    euid = os.geteuid() if euid is None else euid
    if euid != 0:
        return None
    return ("RECHAZADO: «%s» puede crear o escribir estado del servicio y no se ejecuta como "
            "root: lo dejaria root:root e inutilizable para %s.\n"
            "Use el envoltorio canonico (como root; cambia a %s con runuser):\n"
            "    %s %s <argumentos>\n"
            "o, a mano: %s"
            % (tool, SERVICE_USER, SERVICE_USER, CLI_WRAPPER, tool,
               canonical_cli_command("<python>", "<cli>", "<argumentos>")))


def reject_root_cli(tool: str, *, euid: Optional[int] = None) -> None:
    """Guarda canonica de CLI: si es root, explica el comando canonico y sale con
    ``CLI_ROOT_RC`` ANTES de tocar nada (ni ``mkdir``, ni ``sqlite3.connect``)."""
    mensaje = cli_root_rejection(tool, euid=euid)
    if mensaje is not None:
        sys.stderr.write(mensaje + "\n")
        sys.stderr.flush()
        raise SystemExit(CLI_ROOT_RC)


def _bajo_state_root(ruta, env: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    raiz = Path(effective_state_root(env))
    try:
        p = Path(os.path.abspath(str(ruta)))
    except (TypeError, ValueError):
        return False
    return p == raiz or _bajo(p, raiz)


def refuse_root_state_write(ruta, *, env: Optional[Mapping[str, str]] = None,
                            euid: Optional[int] = None) -> None:
    """Punto de estrangulamiento de los ESCRITORES (defensa en profundidad de H-1).

    Si el proceso es root y ``ruta`` cuelga del state root efectivo, levanta
    ``RootStateWriteError`` en vez de crear un fichero o directorio de root dentro
    del estado vivo. Cubre la entrada que no pase por una CLI con guarda (un
    ``python -c``, una herramienta nueva). Fuera del state root (tests, desarrollo)
    no actua. El despliegue (root) no usa estos escritores: crea con ``chown``
    explicito y corrige con ``migrar_estado.py``.
    """
    euid = os.geteuid() if euid is None else euid
    if euid == 0 and _bajo_state_root(ruta, env):
        raise RootStateWriteError(
            13, "un proceso root iba a crear/escribir estado del servicio (%s); %s"
            % (ruta, "ejecute como %s: %s" % (SERVICE_USER, CLI_WRAPPER)), str(ruta))


def ensure_private_dir(ruta) -> Path:
    """Crea ``ruta`` y los padres que falten con ``DIR_MODE`` EXACTO (no la umask).

    ``Path.mkdir(parents=True, mode=...)`` solo aplica el modo al ultimo componente:
    los intermedios nacen con ``0777 & ~umask`` (0755 con umask 022). Aqui cada
    componente que se crea recibe ``DIR_MODE``; los que ya existian NO se tocan.
    """
    p = Path(ruta)
    faltan = []
    q = p
    while not os.path.lexists(q):
        faltan.append(q)
        if q.parent == q:
            break
        q = q.parent
    for d in reversed(faltan):
        refuse_root_state_write(d)
        try:
            os.mkdir(d, DIR_MODE)
        except FileExistsError:
            continue
        os.chmod(d, DIR_MODE)
    return p


def create_private_file(ruta) -> bool:
    """Crea ``ruta`` vacio con ``FILE_MODE`` EXACTO si no existe (``O_EXCL``, sin seguir
    symlinks). Devuelve True si lo creo. Los ``-wal``/``-shm`` de SQLite heredan el modo
    de la base, asi que una base creada aqui los arrastra a 0600."""
    refuse_root_state_write(ruta)
    try:
        fd = os.open(str(ruta), os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, FILE_MODE)
    except FileExistsError:
        return False
    try:
        os.fchmod(fd, FILE_MODE)
    finally:
        os.close(fd)
    return True


def open_private_write(ruta, *, append: bool = False):
    """Descriptor de escritura de un fichero de estado con ``FILE_MODE`` EXACTO.

    Crea con ``FILE_MODE`` y lo FIJA con ``fchmod`` (la umask no decide); trunca salvo
    ``append``. Devuelve el descriptor crudo (el llamador lo envuelve con ``os.fdopen``)."""
    refuse_root_state_write(ruta)
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | (os.O_APPEND if append else os.O_TRUNC)
    fd = os.open(str(ruta), flags, FILE_MODE)
    try:
        os.fchmod(fd, FILE_MODE)
    except OSError:
        os.close(fd)
        raise
    return fd


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


def effective_state_root(env: Mapping[str, str]) -> str:
    """El state root EFECTIVO y canonico: UNA sola funcion para visor, worker y despliegue.

    Config explicita (``S9K_STATE_ROOT``) si existe; si no, el default seguro del
    producto (``DEFAULT_STATE_ROOT``). El administrador no edita .env para esto.
    """
    return os.path.normpath((env.get(STATE_ROOT_ENV) or "").strip() or DEFAULT_STATE_ROOT)


def default_state_path(*partes: str, env: Optional[Mapping[str, str]] = None) -> Path:
    """Ruta por defecto de un artefacto mutable: SIEMPRE bajo el state root efectivo.

    Para los escritores que antes caian en ``<release>/state/...`` (cache de IA
    externa, ``glossary.db``): ningun default puede quedar dentro de la release.
    """
    env = os.environ if env is None else env
    return Path(effective_state_root(env)).joinpath(*partes)


def exception_declared(env: Mapping[str, str]) -> bool:
    """¿Hay una excepcion EXPLICITA de tests/laboratorio? Solo el valor exacto cuenta."""
    return (env.get(VALIDATION_EXCEPTION_ENV) or "") == VALIDATION_EXCEPTION_VALUE


def inspect_backup_root(backup_root, state_root) -> list:
    """El backup vive FUERA del state vivo (TD-H06-01): nada root-owned dentro de el."""
    br, sr = Path(os.path.normpath(str(backup_root))), Path(os.path.normpath(str(state_root)))
    if br == sr or _bajo(br, sr) or _bajo(sr, br):
        return [Violation(OUTSIDE_STATE, str(br), "la raiz de backups esta DENTRO (o contiene) "
                          "el state root %s: un backup como root dejaria ficheros root:root en el "
                          "estado vivo" % sr)]
    return []


def inspect_secret(path, *, gid=None, group: str = SERVICE_GROUP) -> list:
    """Politica SECRET: fichero root:<grupo de servicio>, modo <= 0640, no symlink.

    El servicio LEE y no escribe: el grupo no tiene bit de escritura ni otros ningun bit.
    Los directorios que lo contienen (config 0710, secrets 0750) son root:<grupo> y ningun
    otro usuario los lista.
    """
    out: list = []
    p = str(path)
    try:
        st = os.lstat(p)
    except FileNotFoundError:
        return [Violation(UNREADABLE, p, "el secreto no existe")]
    except OSError as exc:
        return [Violation(UNREADABLE, p, "no se puede inspeccionar: %s" % exc.strerror)]
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        return [Violation(TYPE, p, "el secreto no es un fichero regular (symlink o tipo raro)")]
    if gid is None:
        _u, gid = expected_ids(SERVICE_USER, group)
    if st.st_uid != 0 or (gid is not None and st.st_gid != gid):
        out.append(Violation(OWNER, p, "tiene owner %s:%s; esperado root:%s" % (
            _nombre_uid(st.st_uid), _nombre_gid(st.st_gid), group)))
    if stat.S_IMODE(st.st_mode) & ~SECRET_FILE_MAX_MODE:
        out.append(Violation(MODE, p, "tiene modo %04o; maximo permitido %04o (lectura para el "
                             "grupo de servicio, nada para otros)" % (stat.S_IMODE(st.st_mode),
                                                                       SECRET_FILE_MAX_MODE)))
    if _acl_presente(p):
        out.append(Violation(ACL, p, "tiene ACL POSIX extendida (no se auditan; techo declarado)"))
    return out


def probe_secret(path) -> list:
    """POR EFECTO (como el usuario de servicio): lee el secreto y NO puede escribirlo."""
    out: list = []
    p = str(path)
    if os.geteuid() == 0:
        return [Violation(IDENTITY, "proceso", "la prueba del secreto se ejecuta como el usuario de servicio")]
    try:
        with open(p, "rb") as fh:
            fh.read(1)
    except OSError as exc:
        out.append(Violation(NO_ACCESS, p, "el servicio NO puede leer su secreto (%s)" % exc.strerror))
    try:
        with open(p, "r+b"):
            out.append(Violation(MODE, p, "el servicio PUEDE escribir su secreto (debe ser solo lectura)"))
    except OSError:
        pass
    return out


# --------------------------------------------------------------------------
# C-5 (ronda 2) · el state root es un directorio DEDICADO al servicio
# --------------------------------------------------------------------------
NOT_DEDICATED = "NOT_DEDICATED"
FOREIGN = "FOREIGN"

#: Directorios del sistema que NUNCA pueden ser el state root: la migracion haria
#: ``chown -R``/``chmod 0700`` sobre ellos (o sobre lo ajeno que contienen).
SYSTEM_DIRS = frozenset({
    "/", "/bin", "/boot", "/dev", "/etc", "/home", "/lib", "/lib32", "/lib64", "/libx32",
    "/media", "/mnt", "/opt", "/proc", "/root", "/run", "/sbin", "/srv", "/sys", "/tmp",
    "/usr", "/usr/bin", "/usr/lib", "/usr/local", "/usr/sbin", "/usr/share",
    "/var", "/var/lib", "/var/tmp", "/var/log", "/var/cache", "/var/backups", "/var/opt",
    "/var/spool", "/var/mail", "/var/run", "/var/local",
    "/opt/s9-knowledge", "/etc/s9-knowledge",
})

#: Entradas de PRIMER NIVEL que puede contener el state root. Una sola lista: los
#: subdirectorios del servicio, los del instalador, los defaults de los escritores
#: que cuelgan del state root (``glossary``, ``external_ai_cache``) y ``backups``
#: (legado: solo vacio, lo retira la migracion; con contenido es C-1). Las rutas que
#: declare el entorno se suman a esta lista en cada comprobacion.
KNOWN_TOP_LEVEL = tuple(sorted(
    {s.split("/")[0] for s in SERVICE_SUBDIRS} | set(ADMIN_SUBTREES)
    | {"glossary", "external_ai_cache", "backups"}))
#: Residuos efimeros de las sondas de acceso (``_probar_directorio``) que un proceso
#: matado puede dejar en la raiz: no son "contenido ajeno".
_PREFIJO_SONDA = ".s9k-probe-"


def inspect_dedicated_state_root(state_root, declared: Optional[Mapping[str, Path]] = None) -> list:
    """El state root es DEDICADO (C-5): ni del sistema, ni compartido, ni con contenido ajeno.

    Se llama ANTES de cualquier ``chown``/``chmod`` (validate-env en el paso 2b, y la
    migracion antes de su paso 2): una raiz equivocada (``/``, ``/var/lib``, un
    directorio 1777 con ficheros de otros) no se "corrige", se PARA. Una raiz ausente
    (instalacion fresh) no es un hallazgo: la crea la migracion.
    """
    out: list = []
    raiz = os.path.normpath(str(state_root))
    if not os.path.isabs(raiz):
        return [Violation(NOT_ABSOLUTE, raiz, "el state root no es absoluto")]
    if raiz in SYSTEM_DIRS:
        return [Violation(NOT_DEDICATED, raiz, "es un directorio del SISTEMA: el state root tiene "
                          "que ser un directorio dedicado al servicio (p. ej. %s); la migracion "
                          "haria chown/chmod sobre el" % DEFAULT_STATE_ROOT)]
    for critico in RELEASE_PREFIXES + (os.path.dirname(SECRETS_DIR),):
        if _bajo(Path(critico), Path(raiz)):
            return [Violation(NOT_DEDICATED, raiz, "contiene %s (release o configuracion): no es "
                              "un directorio dedicado al estado" % critico)]
    try:
        st = os.lstat(raiz)
    except FileNotFoundError:
        return out
    except OSError as exc:
        return [Violation(UNREADABLE, raiz, "no se puede inspeccionar: %s" % exc.strerror)]
    if not stat.S_ISDIR(st.st_mode):
        return out      # symlink / tipo: lo dice inspect_state y la migracion (SYMLINK/TIPO)
    modo = stat.S_IMODE(st.st_mode)
    if modo & stat.S_ISVTX:
        out.append(Violation(NOT_DEDICATED, raiz, "tiene el bit sticky (%04o): es un directorio "
                             "compartido, no dedicado al servicio" % modo))
    if modo & 0o002:
        out.append(Violation(NOT_DEDICATED, raiz, "es escribible por OTROS (%04o): cualquier "
                             "usuario puede dejar ahi ficheros que la migracion se apropiaria" % modo))
    try:
        entradas = os.listdir(raiz)
    except PermissionError as exc:
        # Un state root 0700 de s9knowledge NO es listable por otro usuario: para quien no
        # es root eso es lo esperado (no un hallazgo). El despliegue lo comprueba como root,
        # que si lo lista; si ni root puede, es un hallazgo.
        if os.geteuid() == 0:
            out.append(Violation(UNREADABLE, raiz, "no se puede listar: %s" % exc.strerror))
        return out
    except OSError as exc:
        out.append(Violation(UNREADABLE, raiz, "no se puede listar: %s" % exc.strerror))
        return out
    conocidas = set(KNOWN_TOP_LEVEL)
    for ruta in (declared or {}).values():
        try:
            conocidas.add(Path(ruta).relative_to(raiz).parts[0])
        except (ValueError, IndexError):
            continue
    ajenas = sorted(e for e in entradas if e not in conocidas and not e.startswith(_PREFIJO_SONDA))
    if ajenas:
        out.append(Violation(FOREIGN, raiz, "contiene %d entrada(s) de primer nivel AJENAS al "
                             "servicio (%s%s); conocidas: %s. No se migra un directorio que no es "
                             "solo del servicio" % (len(ajenas), ", ".join(ajenas[:10]),
                                                    ", ..." if len(ajenas) > 10 else "",
                                                    ", ".join(sorted(conocidas)))))
    return out


def inspect_legacy_backups(state_root) -> list:
    """C-1 · ``<state>/backups`` con contenido es una precondicion que el operador resuelve
    ANTES de parar nada (los backups viven fuera del state vivo; moverlos es decision suya)."""
    ruta = os.path.join(os.path.normpath(str(state_root)), "backups")
    if os.path.islink(ruta):
        return [Violation(SYMLINK, ruta, "es un enlace simbolico")]
    if not os.path.isdir(ruta):
        return []
    try:
        contenido = os.listdir(ruta)
    except OSError as exc:
        return [Violation(UNREADABLE, ruta, "ilegible: %s" % exc.strerror)]
    if contenido:
        return [Violation(OUTSIDE_STATE, ruta, "contiene %d elemento(s): los backups viven FUERA "
                          "del state root (raiz separada, p. ej. %s, root:%s 0750). RECETA: "
                          "`mkdir -p %s && mv %s/* %s/` (como root) y repita el despliegue; "
                          "nada se ha parado ni tocado" % (len(contenido), DEFAULT_BACKUP_ROOT,
                                                         SERVICE_GROUP, DEFAULT_BACKUP_ROOT, ruta,
                                                         DEFAULT_BACKUP_ROOT))]
    return []


# --------------------------------------------------------------------------
# C-7 (ronda 2) · gate de unidad con la semantica de systemd (ULTIMO valor)
# --------------------------------------------------------------------------
#: Grupos que dan privilegios por pertenencia: una unidad del servicio no los pide.
PRIVILEGED_GROUPS = ("root", "sudo", "wheel", "adm", "docker", "shadow", "disk", "lxd",
                     "libvirt", "systemd-journal", "kvm")
#: Claves que fijan la IDENTIDAD o los privilegios: cada una UNA vez como mucho.
IDENTITY_KEYS = ("User", "Group", "UMask", "DynamicUser", "NoNewPrivileges",
                 "CapabilityBoundingSet", "AmbientCapabilities", "SupplementaryGroups",
                 "PermissionsStartOnly")
_EXEC_KEYS = ("ExecStart", "ExecStartPre", "ExecStartPost", "ExecStop", "ExecStopPost",
              "ExecReload", "ExecCondition")
_VERDADERO = ("1", "yes", "true", "on")
_ELEVADORES = ("sudo", "su", "pkexec", "doas", "runuser", "setpriv", "capsh", "chroot")


def parse_unit(texto: str) -> dict:
    """``{seccion: [(clave, valor), ...]}`` en ORDEN, como lo lee systemd: comentarios
    ``#``/``;``, espacios alrededor de ``=`` y lineas continuadas con ``\\``."""
    secciones: dict = {}
    actual = None
    pendiente = ""
    for cruda in texto.splitlines():
        linea = pendiente + cruda.strip() if pendiente else cruda.strip()
        if linea.endswith("\\"):
            pendiente = linea[:-1] + " "
            continue
        pendiente = ""
        if not linea or linea[0] in "#;":
            continue
        if linea.startswith("[") and linea.endswith("]"):
            actual = linea[1:-1].strip()
            secciones.setdefault(actual, [])
            continue
        if "=" not in linea or actual is None:
            continue
        k, v = linea.split("=", 1)
        secciones[actual].append((k.strip(), v.strip()))
    return secciones


def inspect_unit_identity(texto: str) -> list:
    """Errores de IDENTIDAD/PRIVILEGIOS de una unidad (una cadena por hallazgo).

    Semantica de systemd: vale el ULTIMO valor de cada clave, asi que una clave de
    identidad repetida es en si misma un hallazgo (la linea que se lee no es la que
    se ve). Exige ``User``/``Group``/``UMask`` de la autoridad, ``NoNewPrivileges``
    verdadero, ``CapabilityBoundingSet=`` declarado VACIO y sin ``AmbientCapabilities``,
    sin ``DynamicUser``, sin ``PermissionsStartOnly``, sin grupos privilegiados y sin
    ``ExecStart*`` con prefijo ``+``/``!`` o lanzado por sudo/su/runuser...
    """
    errores: list = []
    servicio = parse_unit(texto).get("Service", [])
    valores: dict = {}
    for k, v in servicio:
        valores.setdefault(k, []).append(v)

    def ultimo(clave: str) -> str:
        return valores.get(clave, [""])[-1]

    for clave in IDENTITY_KEYS:
        n = len(valores.get(clave, []))
        if n > 1:
            errores.append("clave de identidad duplicada: %s= aparece %d veces (systemd usa la "
                           "ULTIMA: %r); una sola declaracion" % (clave, n, ultimo(clave)))
    if ultimo("User") != SERVICE_USER:
        errores.append("User= es '%s'; esperado '%s' (la autoridad); ni root ni otro nombre"
                       % (ultimo("User"), SERVICE_USER))
    if ultimo("Group") != SERVICE_GROUP:
        errores.append("Group= es '%s'; esperado '%s' (la autoridad)" % (ultimo("Group"), SERVICE_GROUP))
    if ultimo("UMask") != UNIT_UMASK:
        errores.append("UMask= es '%s'; esperado '%s' (la autoridad)" % (ultimo("UMask"), UNIT_UMASK))
    if ultimo("DynamicUser").lower() in _VERDADERO:
        errores.append("DynamicUser= activo: systemd asignaria otro uid y el estado no seria suyo")
    if ultimo("NoNewPrivileges").lower() not in ("yes", "true"):
        errores.append("NoNewPrivileges= es '%s'; esperado yes/true (sin elevacion)" % ultimo("NoNewPrivileges"))
    if "CapabilityBoundingSet" not in valores or ultimo("CapabilityBoundingSet") != "":
        errores.append("CapabilityBoundingSet no esta vacio ('%s') o no se declara: el servicio "
                       "no lleva capabilities (CapabilityBoundingSet= vacio)" % ultimo("CapabilityBoundingSet"))
    if any(v for v in valores.get("AmbientCapabilities", [])):
        errores.append("AmbientCapabilities= no vacio (%s): el servicio no lleva capabilities"
                       % ultimo("AmbientCapabilities"))
    if ultimo("PermissionsStartOnly").lower() in _VERDADERO:
        errores.append("PermissionsStartOnly= activo: partes de la unidad correrian como root")
    grupos = set(" ".join(valores.get("SupplementaryGroups", [])).split())
    if grupos & set(PRIVILEGED_GROUPS):
        errores.append("SupplementaryGroups= incluye un grupo privilegiado: %s"
                       % ", ".join(sorted(grupos & set(PRIVILEGED_GROUPS))))
    for clave in _EXEC_KEYS:
        for v in valores.get(clave, []):
            prefijo = re.match(r"^[@\-:+!|]*", v).group(0)
            if "+" in prefijo or "!" in prefijo:
                errores.append("%s= con prefijo '%s': se ejecutaria con privilegios completos "
                               "(+) o sin cambiar de usuario (!)" % (clave, prefijo))
            argv0 = v[len(prefijo):].split(" ", 1)[0]
            if os.path.basename(argv0) in _ELEVADORES:
                errores.append("%s= lanza %s: el servicio no cambia de identidad ni eleva"
                               % (clave, os.path.basename(argv0)))
    # (S9K_STATE_VALIDATION/ENFORCE en la unidad lo rechaza validate_deploy.sh en TODO el
    # fichero; en el entorno EFECTIVO -drop-ins, EnvironmentFile, /proc- lo mira el paso
    # 14a del despliegue y el healthcheck: C-6.)
    return errores


def enforce(role: str, env: Optional[Mapping[str, str]] = None, *,
            uid: Optional[int] = None, gid: Optional[int] = None,
            euid: Optional[int] = None) -> bool:
    """Comprobacion de ARRANQUE (visor y worker): OBLIGATORIA y fail-closed.

    No depende de ninguna variable que ponga la unidad. Solo una excepcion
    EXPLICITA de tests/laboratorio (``VALIDATION_EXCEPTION_ENV``) la omite y devuelve
    ``False`` dejando constancia en el log. Si no, comprueba identidad (proceso =
    usuario de servicio, nunca root), rutas efectivas (declaradas, bajo el state root,
    no en la release, sin symlinks), propietario/modo/tipo/ACL de todo el arbol y
    acceso efectivo; cualquier hallazgo levanta ``ServiceStateError`` con el
    diagnostico concreto. ``uid/gid/euid`` se inyectan en tests.
    """
    env = os.environ if env is None else env
    if exception_declared(env):
        import logging  # noqa: PLC0415
        logging.getLogger("s9k.state").warning(
            "COMPROBACION DE ESTADO OMITIDA por excepcion explicita de tests/laboratorio (%s)",
            VALIDATION_EXCEPTION_ENV)
        return False
    violaciones: list = []
    violaciones += inspect_process_identity(euid=euid)
    raiz = effective_state_root(env)
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
    "backup_root": lambda: DEFAULT_BACKUP_ROOT,
    "secrets_dir": lambda: SECRETS_DIR,
    "secret_dir_mode": lambda: "%04o" % SECRET_DIR_MODE,
    "secret_file_mode": lambda: "%04o" % SECRET_FILE_MAX_MODE,
    "config_dir_mode": lambda: "%04o" % CONFIG_DIR_MODE,
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
    sc = sub.add_parser("secret-check", help="politica SECRET de uno o varios ficheros (root)")
    sc.add_argument("ficheros", nargs="+")
    sp = sub.add_parser("secret-probe", help="el usuario de servicio LEE y no ESCRIBE sus secretos "
                        "(se ejecuta con runuser)")
    sp.add_argument("ficheros", nargs="+")
    uc = sub.add_parser("unit-check", help="identidad y privilegios de una unidad systemd con la "
                        "semantica de systemd (ultimo valor; C-7). Una linea por hallazgo.")
    uc.add_argument("unidad")
    args = ap.parse_args(argv)

    if args.orden == "get":
        print(_GETTERS[args.clave]())
        return 0
    if args.orden == "unit-check":
        try:
            errores = inspect_unit_identity(Path(args.unidad).read_text(encoding="utf-8"))
        except OSError as exc:
            errores = ["no se puede leer la unidad %s: %s" % (args.unidad, exc.strerror)]
        for e in errores:
            print(e)
        return 3 if errores else 0
    env = {}
    if args.orden in ("validate-env", "check") and getattr(args, "env_file", None):
        env = _leer_env_file(args.env_file)
    if args.orden == "validate-env":
        rutas, faltan = effective_paths(env, role=args.role)
        viol = list(faltan)
        for clave, ruta in sorted(rutas.items()):
            _revisar_declarada(clave, ruta, Path(args.state_root), RELEASE_PREFIXES, viol)
        declarada = (env.get(STATE_ROOT_ENV) or "").strip()
        if declarada and os.path.normpath(declarada) != os.path.normpath(args.state_root):
            viol.append(Violation(NO_STATE_ROOT, STATE_ROOT_ENV,
                        "vale %s pero el despliegue usa %s: el state root no se determina "
                        "de forma inequivoca" % (declarada, args.state_root)))
        elif not declarada and os.path.normpath(args.state_root) != os.path.normpath(DEFAULT_STATE_ROOT):
            viol.append(Violation(NO_STATE_ROOT, STATE_ROOT_ENV,
                        "el despliegue usa el state root NO canonico %s y el entorno no declara "
                        "S9K_STATE_ROOT: el servicio usaria %s. Declare el override o use el "
                        "default" % (args.state_root, DEFAULT_STATE_ROOT)))
        for var in (VALIDATION_EXCEPTION_ENV, ENFORCE_ENV):
            if (env.get(var) or "").strip():
                viol.append(Violation(IDENTITY, var, "esta variable es una excepcion de tests/"
                            "laboratorio (o un interruptor retirado) y NO puede estar en una "
                            "instalacion operativa"))
        # C-1: la raiz de backups, por CUALQUIERA de sus dos nombres, fuera del state root.
        for var_backup in BACKUP_ENVS:
            backup = (env.get(var_backup) or "").strip()
            if not backup:
                continue
            if not os.path.isabs(backup):
                viol.append(Violation(NOT_ABSOLUTE, var_backup, "no es absoluta"))
            else:
                viol += [Violation(v.code, "%s=%s" % (var_backup, v.path), v.detail)
                         for v in inspect_backup_root(backup, args.state_root)]
        if args.role == "viewer":
            # C-1 y C-5: precondiciones del DISCO, aun en solo lectura y ANTES de parar nada
            # (viewer.env declara el superconjunto de rutas; worker.env se cruza con el).
            viol += inspect_legacy_backups(args.state_root)
            viol += inspect_dedicated_state_root(args.state_root, rutas)
    elif args.orden == "check":
        rutas, faltan = effective_paths(env, role=args.role) if env else ({}, [])
        viol = list(faltan) + inspect_state(args.state_root, uid=args.uid, gid=args.gid,
                                            declared=rutas)
    elif args.orden in ("secret-check", "secret-probe"):
        viol = []
        for f in args.ficheros:
            viol += inspect_secret(f) if args.orden == "secret-check" else probe_secret(f)
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
