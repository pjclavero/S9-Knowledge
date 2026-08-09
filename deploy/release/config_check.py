#!/usr/bin/env python3
"""Comprobador de configuración de despliegue de S9 Knowledge.

Contrasta un entorno (fichero ``viewer.env`` y/o el entorno del proceso, más el
sistema de ficheros local si se pide) contra ``deploy/release/spec.py`` y emite
un veredicto por requisito y un veredicto global.

Reglas duras, en este orden de prioridad:

  1. Una ausencia o invalidez de un requisito CRITICAL produce ERROR. Nunca OK.
     Ni con `--quiet`, ni con `--json`, ni si todo lo demás está bien.
  2. Un fallo INTERNO del comprobador (fichero ilegible, excepción inesperada)
     produce código 3. Nunca 0: "no pude comprobar" no es "está bien".
  3. Los secretos se comprueban por RUTA y por permisos. Su contenido no se lee,
     no se imprime, no se hashea y no aparece en la salida JSON.

Códigos de salida:
    0  OK       — todo lo crítico y lo recomendado está en su sitio
    1  WARNING  — nada crítico falla, pero hay recomendaciones incumplidas
    2  ERROR    — al menos un requisito crítico falla
    3  INTERNAL — el comprobador no pudo completar la comprobación

Uso típico (nunca contra producción desde aquí; se copia al host y se ejecuta allí):
    python3 deploy/release/config_check.py --env-file /etc/s9-knowledge/viewer.env
    python3 deploy/release/config_check.py --env-file X --check-filesystem --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import spec  # noqa: E402
from spec import Level, Status, worst  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

# Marcador que sustituye a cualquier valor sensible en toda la salida.
REDACTED = "<redactado>"


class InternalCheckError(RuntimeError):
    """El comprobador no pudo hacer su trabajo. Se traduce en código 3."""


@dataclass
class Finding:
    check: str
    target: str
    status: str
    level: str
    message: str

    def line(self) -> str:
        return f"[{self.status:<7}] {self.check:<22} {self.target:<42} {self.message}"


def _status_for(level: Level) -> Status:
    """Un incumplimiento CRITICAL es ERROR; el resto, WARNING."""
    return Status.ERROR if level is Level.CRITICAL else Status.WARNING


# ---------------------------------------------------------------------------
# Carga del entorno a comprobar
# ---------------------------------------------------------------------------

_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$")


def load_env_file(path: Path) -> dict[str, str]:
    """Lee un fichero estilo ``viewer.env``.

    No evalúa el fichero con el shell (evitando ejecución de contenido ajeno) y
    no interpola variables. Los comentarios de línea completa se ignoran; los
    comentarios en línea NO se recortan salvo que vayan precedidos de espacio,
    igual que hace systemd con EnvironmentFile.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InternalCheckError(f"no se pudo leer {path}: {exc}") from exc

    env: dict[str, str] = {}
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _ENV_LINE.match(line)
        if not match:
            continue
        name, value = match.group(1), match.group(2)
        value = re.sub(r"\s+#.*$", "", value).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        env[name] = value
    return env


# ---------------------------------------------------------------------------
# Comprobaciones
# ---------------------------------------------------------------------------

def check_env_vars(env: dict[str, str], *, production: bool) -> list[Finding]:
    findings: list[Finding] = []
    for var in spec.ENV_VARS:
        value = env.get(var.name)
        has_value = value is not None and value != ""

        # Un secreto puede satisfacerse con su variante *_FILE.
        if not has_value and var.file_alternative:
            alt = env.get(var.file_alternative)
            if alt:
                findings.append(Finding(
                    "env", var.name, Status.OK.value, var.level.value,
                    f"satisfecha por {var.file_alternative} -> {alt} "
                    f"(contenido no leído)",
                ))
                continue

        if not has_value:
            hint = ""
            if var.default_in_code:
                hint = (f"; el código caería al valor por defecto "
                        f"{REDACTED if var.secret else var.default_in_code!r}")
            findings.append(Finding(
                "env", var.name, _status_for(var.level).value, var.level.value,
                f"AUSENTE — {var.purpose}{hint}",
            ))
            continue

        # Presente: validar el valor. Nunca se imprime si es secreto.
        shown = REDACTED if var.secret else repr(value)

        if var.secret:
            # Único chequeo posible sobre un secreto sin revelarlo: que no sea
            # un placeholder conocido y que tenga longitud mínima.
            lowered = value.lower()
            # Marcadores de posición concretos. Deliberadamente NO se incluye
            # la subcadena "secret" a secas: un secreto aleatorio legítimo puede
            # contenerla por casualidad, y rechazarlo sería un falso positivo
            # que empuja al operador a ignorar el comprobador.
            if any(bad in lowered for bad in ("change-me", "changeme", "chgme",
                                              "placeholder", "your-secret",
                                              "secret-here", "rellenar", "to-do",
                                              "xxxxx")) or lowered in (
                                                  "default", "example", "secret",
                                                  "password", "test"):
                findings.append(Finding(
                    "env", var.name, Status.ERROR.value, var.level.value,
                    "valor de marcador de posición detectado (contenido no mostrado)",
                ))
                continue
            if len(value) < 32:
                findings.append(Finding(
                    "env", var.name, _status_for(var.level).value, var.level.value,
                    f"demasiado corto ({len(value)} caracteres, mínimo 32)",
                ))
                continue
            findings.append(Finding("env", var.name, Status.OK.value, var.level.value,
                                    f"definida ({REDACTED})"))
            continue

        if var.validator:
            error = var.validator(value)
            if error:
                findings.append(Finding("env", var.name, _status_for(var.level).value,
                                        var.level.value, error))
                continue

        findings.append(Finding("env", var.name, Status.OK.value, var.level.value,
                                f"= {shown}"))

    # El proveedor mock en producción sirve datos de ejemplo: es un fallo grave.
    if production and env.get("S9K_GRAPH_PROVIDER") == "mock":
        findings.append(Finding(
            "env", "S9K_GRAPH_PROVIDER", Status.ERROR.value, Level.CRITICAL.value,
            "'mock' en un despliegue de producción: serviría el grafo de ejemplo",
        ))

    for name in spec.MUST_BE_OFF:
        value = env.get(name)
        if value and value.strip().lower() in {"true", "1", "yes"}:
            findings.append(Finding(
                "flag", name, Status.ERROR.value, Level.CRITICAL.value,
                "ACTIVADA — esta release no autoriza esa operación",
            ))
        else:
            findings.append(Finding("flag", name, Status.OK.value, Level.OPTIONAL.value,
                                    "apagada o sin definir"))
    return findings


def check_files(env: dict[str, str]) -> list[Finding]:
    """Ficheros requeridos: existencia, tipo y permisos. Nunca contenido."""
    findings: list[Finding] = []
    for req in spec.REQUIRED_FILES:
        path = Path(req.path)
        try:
            info = path.lstat()
        except FileNotFoundError:
            findings.append(Finding("file", req.path, _status_for(req.level).value,
                                    req.level.value, f"AUSENTE — {req.purpose}"))
            continue
        except OSError as exc:
            raise InternalCheckError(f"no se pudo consultar {path}: {exc}") from exc

        if not stat.S_ISREG(info.st_mode):
            findings.append(Finding("file", req.path, _status_for(req.level).value,
                                    req.level.value, "existe pero no es un fichero regular"))
            continue

        mode = stat.S_IMODE(info.st_mode)
        if req.max_mode is not None and mode & ~req.max_mode:
            findings.append(Finding(
                "file", req.path, _status_for(req.level).value, req.level.value,
                f"permisos {oct(mode)} más laxos que el máximo {oct(req.max_mode)}",
            ))
            continue
        findings.append(Finding("file", req.path, Status.OK.value, req.level.value,
                                f"presente, modo {oct(mode)}"
                                + (" (contenido no leído)" if req.secret else "")))

    # Los ficheros de secreto referenciados por variables *_FILE también existen
    # como requisito, aunque la ruta la elija el operador.
    for var in spec.ENV_VARS:
        if not var.file_alternative:
            continue
        referenced = env.get(var.file_alternative)
        if not referenced:
            continue
        path = Path(referenced)
        if not path.is_file():
            findings.append(Finding(
                "secret-ref", var.file_alternative, _status_for(var.level).value,
                var.level.value,
                f"{referenced} no existe: la variable apunta a un secreto ausente",
            ))
        else:
            mode = stat.S_IMODE(path.stat().st_mode)
            status = Status.OK if not mode & 0o007 else _status_for(var.level)
            findings.append(Finding(
                "secret-ref", var.file_alternative, status.value, var.level.value,
                f"{referenced} presente, modo {oct(mode)} (contenido no leído)"
                + ("" if status is Status.OK else "; legible por 'otros'"),
            ))
    return findings


def check_dirs(env: dict[str, str]) -> list[Finding]:
    findings: list[Finding] = []
    for req in spec.REQUIRED_DIRS:
        path = Path(req.path)
        if not path.is_dir():
            findings.append(Finding("dir", req.path, _status_for(req.level).value,
                                    req.level.value, f"AUSENTE — {req.purpose}"))
            continue
        mode = stat.S_IMODE(path.stat().st_mode)
        if req.max_mode is not None and mode & ~req.max_mode:
            findings.append(Finding(
                "dir", req.path, Status.WARNING.value, req.level.value,
                f"permisos {oct(mode)} más laxos que el máximo {oct(req.max_mode)}",
            ))
            continue
        findings.append(Finding("dir", req.path, Status.OK.value, req.level.value,
                                f"presente, modo {oct(mode)}"))

    # El directorio de auth.db debe preexistir: el visor NO lo crea y aborta.
    auth_db = env.get("S9K_AUTH_DB_PATH")
    if auth_db:
        parent = Path(auth_db).parent
        if not parent.is_dir():
            findings.append(Finding(
                "dir", str(parent), Status.ERROR.value, Level.CRITICAL.value,
                "directorio de auth.db ausente; el visor no lo crea y no arrancará",
            ))
    return findings


def _parse_version(text: str) -> tuple[int, ...] | None:
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    if not match:
        return None
    return tuple(int(g) for g in match.groups() if g is not None)


def check_versions(*, check_neo4j: bool) -> list[Finding]:
    findings: list[Finding] = []
    by_component = {req.component: req for req in spec.VERSION_REQUIREMENTS}

    py_req = by_component["python"]
    current = sys.version_info[:2]
    lo, hi = py_req.min_version[:2], py_req.below_version[:2]
    status = Status.OK if lo <= current < hi else _status_for(py_req.level)
    findings.append(Finding(
        "version", "python", status.value, py_req.level.value,
        f"{'.'.join(map(str, current))} "
        f"(exigido >={'.'.join(map(str, lo))},<{'.'.join(map(str, hi))}); {py_req.note}",
    ))

    neo_req = by_component["neo4j"]
    if not check_neo4j:
        findings.append(Finding(
            "version", "neo4j", Status.WARNING.value, neo_req.level.value,
            "NO COMPROBABLE sin acceso a la máquina destino: se requiere consultar "
            "el servidor real (`CALL dbms.components()` o la imagen del contenedor)",
        ))
    else:
        binary = shutil.which("neo4j-admin") or shutil.which("cypher-shell")
        if not binary:
            findings.append(Finding(
                "version", "neo4j", Status.WARNING.value, neo_req.level.value,
                "ni neo4j-admin ni cypher-shell en PATH: versión no verificada",
            ))
        else:
            try:
                out = subprocess.run([binary, "--version"], capture_output=True,
                                     text=True, timeout=20, check=False).stdout
            except (OSError, subprocess.SubprocessError) as exc:
                raise InternalCheckError(f"fallo consultando {binary}: {exc}") from exc
            parsed = _parse_version(out)
            if parsed is None:
                findings.append(Finding("version", "neo4j", Status.WARNING.value,
                                        neo_req.level.value,
                                        f"salida de versión no interpretable: {out.strip()!r}"))
            else:
                ok = neo_req.min_version <= parsed[:len(neo_req.min_version)] < neo_req.below_version
                findings.append(Finding(
                    "version", "neo4j",
                    (Status.OK if ok else _status_for(neo_req.level)).value,
                    neo_req.level.value,
                    f"{'.'.join(map(str, parsed))}; {neo_req.note}",
                ))
    return findings


def check_dependencies() -> list[Finding]:
    """Comprueba que las dependencias declaradas están instaladas y en rango."""
    findings: list[Finding] = []
    req_file = REPO_ROOT / "viewer" / "requirements.txt"
    try:
        lines = req_file.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise InternalCheckError(f"no se pudo leer {req_file}: {exc}") from exc

    try:
        from importlib import metadata
    except ImportError as exc:  # pragma: no cover
        raise InternalCheckError(f"importlib.metadata no disponible: {exc}") from exc

    for line in lines:
        line = line.split("#")[0].strip()
        if not line:
            continue
        name = re.split(r"[<>=!\[]", line, maxsplit=1)[0].strip()
        if not name:
            continue
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            findings.append(Finding("dep", name, Status.ERROR.value,
                                    Level.CRITICAL.value,
                                    f"NO INSTALADA (declarada como {line})"))
            continue

        # Estar instalada no basta: hay que estar DENTRO del rango declarado.
        # Comprobar solo la presencia daba OK a una fastapi anterior a la
        # exigida, que es justo el fallo que este comprobador debe cazar.
        spec_text = line[len(name):].strip()
        if not spec_text:
            findings.append(Finding("dep", name, Status.OK.value, Level.CRITICAL.value,
                                    f"instalada {installed} (sin rango declarado)"))
            continue
        try:
            from packaging.requirements import Requirement
            requirement = Requirement(line)
        except ImportError:
            findings.append(Finding(
                "dep", name, Status.WARNING.value, Level.CRITICAL.value,
                f"instalada {installed}; rango {spec_text} NO verificado "
                "(falta el paquete 'packaging')",
            ))
            continue
        except Exception as exc:  # noqa: BLE001
            raise InternalCheckError(
                f"no se pudo interpretar la línea de requisito {line!r}: {exc}"
            ) from exc

        if requirement.specifier.contains(installed, prereleases=True):
            findings.append(Finding("dep", name, Status.OK.value, Level.CRITICAL.value,
                                    f"instalada {installed}, dentro de {spec_text}"))
        else:
            findings.append(Finding(
                "dep", name, Status.ERROR.value, Level.CRITICAL.value,
                f"instalada {installed}, FUERA del rango declarado {spec_text}",
            ))
    return findings


def check_systemd(*, check_units: bool) -> list[Finding]:
    findings: list[Finding] = []
    for unit, level, purpose in spec.SYSTEMD_UNITS:
        if not check_units or not shutil.which("systemctl"):
            findings.append(Finding(
                "unit", unit, Status.WARNING.value, level.value,
                "NO COMPROBABLE aquí: requiere systemd en la máquina destino",
            ))
            continue
        result = subprocess.run(["systemctl", "is-enabled", unit],
                                capture_output=True, text=True, check=False)
        state = result.stdout.strip() or result.stderr.strip()
        status = Status.OK if result.returncode == 0 else _status_for(level)
        findings.append(Finding("unit", unit, status.value, level.value,
                                f"{state} — {purpose}"))
    return findings


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------

def run_checks(env: dict[str, str], *, production: bool, check_filesystem: bool,
               check_units: bool, check_neo4j: bool) -> list[Finding]:
    findings = check_env_vars(env, production=production)
    findings += check_versions(check_neo4j=check_neo4j)
    findings += check_dependencies()
    if check_filesystem:
        findings += check_files(env)
        findings += check_dirs(env)
    else:
        findings.append(Finding(
            "filesystem", "(todo)", Status.WARNING.value, Level.CRITICAL.value,
            "NO COMPROBADO: ficheros, secretos, directorios y permisos exigen "
            "ejecutar este comprobador EN la máquina destino (--check-filesystem)",
        ))
    findings += check_systemd(check_units=check_units)
    return findings


def verdict(findings: list[Finding]) -> Status:
    """Veredicto global.

    Salvaguarda explícita: si algún requisito CRITICAL no acabó en OK, el
    veredicto es ERROR aunque la agregación por severidad dijera otra cosa.
    """
    global_status = worst([Status(f.status) for f in findings])
    critical_failed = any(f.level == Level.CRITICAL.value and f.status != Status.OK.value
                          for f in findings)
    if critical_failed and global_status is not Status.ERROR:
        return Status.ERROR
    return global_status


EXIT_CODES = {Status.OK: 0, Status.WARNING: 1, Status.ERROR: 2}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env-file", help="fichero estilo viewer.env a comprobar")
    parser.add_argument("--use-process-env", action="store_true",
                        help="incorporar también el entorno del proceso actual")
    parser.add_argument("--production", action="store_true",
                        help="aplica las reglas extra de producción (prohíbe mock)")
    parser.add_argument("--check-filesystem", action="store_true",
                        help="comprobar ficheros, secretos, directorios y permisos")
    parser.add_argument("--check-units", action="store_true",
                        help="consultar systemd por las unidades declaradas")
    parser.add_argument("--check-neo4j", action="store_true",
                        help="consultar la versión de Neo4j con las herramientas locales")
    parser.add_argument("--json", action="store_true", help="salida JSON")
    parser.add_argument("--quiet", action="store_true",
                        help="ocultar los requisitos en OK (los fallos SIEMPRE se muestran)")
    args = parser.parse_args(argv)

    try:
        env: dict[str, str] = {}
        if args.env_file:
            env.update(load_env_file(Path(args.env_file)))
        if args.use_process_env or not args.env_file:
            env.update({k: v for k, v in os.environ.items() if k.startswith("S9K_")})

        findings = run_checks(env, production=args.production,
                              check_filesystem=args.check_filesystem,
                              check_units=args.check_units,
                              check_neo4j=args.check_neo4j)
        status = verdict(findings)
    except InternalCheckError as exc:
        print(f"INTERNAL: el comprobador no pudo completar la comprobación: {exc}",
              file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001
        print(f"INTERNAL: fallo inesperado del comprobador: {exc!r}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps({
            "status": status.value,
            "exit_code": EXIT_CODES[status],
            "counts": {s.value: sum(1 for f in findings if f.status == s.value)
                       for s in Status},
            "findings": [asdict(f) for f in findings],
        }, indent=2, ensure_ascii=False))
    else:
        for finding in findings:
            if args.quiet and finding.status == Status.OK.value:
                continue
            print(finding.line())
        counts = {s.value: sum(1 for f in findings if f.status == s.value) for s in Status}
        print("")
        print(f"OK={counts['OK']}  WARNING={counts['WARNING']}  ERROR={counts['ERROR']}")
        print(f"VEREDICTO GLOBAL: {status.value}")
        if status is Status.ERROR:
            print("El despliegue NO debe continuar.")

    return EXIT_CODES[status]


if __name__ == "__main__":
    sys.exit(main())
