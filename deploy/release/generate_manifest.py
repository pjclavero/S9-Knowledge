#!/usr/bin/env python3
"""Genera el manifiesto de release: *qué exactamente desplegaríamos*.

Todo lo que escribe se deriva del repositorio (git, código, ficheros de
dependencias) o de ``spec.py``. No consulta ninguna máquina, no abre conexiones
de red y no lee ningún secreto.

Uso:
    python3 deploy/release/generate_manifest.py                 # a stdout
    python3 deploy/release/generate_manifest.py -o deploy/release/RELEASE_MANIFEST.json
    python3 deploy/release/generate_manifest.py --format md     # versión legible

Códigos de salida: 0 generado; 2 fallo interno (repo no legible, git ausente…).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import spec  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_VERSION = "1.0.0"


class ManifestError(RuntimeError):
    """Fallo al construir el manifiesto. Nunca se degrada a un manifiesto parcial."""


# ---------------------------------------------------------------------------
# Hechos extraídos del repositorio
# ---------------------------------------------------------------------------

def _git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
        raise ManifestError(f"no se pudo ejecutar git {' '.join(args)}: {exc}") from exc
    if out.returncode != 0:
        raise ManifestError(f"git {' '.join(args)} falló: {out.stderr.strip()}")
    return out.stdout.strip()


def git_facts() -> dict:
    commit = _git("rev-parse", "HEAD")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    dirty = bool(_git("status", "--porcelain"))
    describe = ""
    try:
        describe = _git("describe", "--tags", "--always")
    except ManifestError:
        describe = commit[:12]
    return {
        "commit": commit,
        "short_commit": commit[:12],
        "branch": branch,
        "describe": describe,
        "worktree_dirty": dirty,
    }


def app_version() -> str:
    """Versión declarada por la propia aplicación.

    Se lee del literal del constructor de FastAPI en lugar de importarlo, para
    no arrastrar dependencias ni ejecutar el arranque de la app.
    """
    main_py = REPO_ROOT / "viewer" / "app" / "main.py"
    text = main_py.read_text(encoding="utf-8")
    match = re.search(r'FastAPI\((?:[^)]*?)version="([^"]+)"', text, re.S)
    if not match:
        raise ManifestError(
            f"no se encontró la versión de la app en {main_py}; el manifiesto no "
            "puede inventarla"
        )
    return match.group(1)


def auth_schema_version() -> int:
    """Versión de esquema de auth.db, leída del código que la aplica."""
    db_py = REPO_ROOT / "viewer" / "app" / "auth" / "db.py"
    match = re.search(r"^SCHEMA_VERSION\s*=\s*(\d+)", db_py.read_text(encoding="utf-8"), re.M)
    if not match:
        raise ManifestError(f"no se encontró SCHEMA_VERSION en {db_py}")
    return int(match.group(1))


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise ManifestError(f"fichero requerido para el manifiesto ausente: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def dependency_fingerprints() -> dict:
    return {
        "viewer/requirements.txt": _sha256_file(REPO_ROOT / "viewer" / "requirements.txt"),
        "data-engine/requirements.lock": _sha256_file(
            REPO_ROOT / "data-engine" / "requirements.lock"
        ),
    }


def declared_python() -> str:
    """Python exigido por CI: es el único que se prueba de verdad."""
    ci = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    versions = sorted(set(re.findall(r"python-version:\s*['\"]?([0-9.]+)", ci.read_text("utf-8"))))
    if not versions:
        raise ManifestError(f"no se pudo determinar la versión de Python en {ci}")
    return ",".join(versions)


# ---------------------------------------------------------------------------
# Construcción del manifiesto
# ---------------------------------------------------------------------------

def build_manifest() -> dict:
    git = git_facts()
    auth_v = auth_schema_version()

    declared_versions = {
        req.component: f">={'.'.join(map(str, req.min_version))},"
                       f"<{'.'.join(map(str, req.below_version))}"
        for req in spec.VERSION_REQUIREMENTS
    }

    return {
        "manifest_version": MANIFEST_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_by": "deploy/release/generate_manifest.py",
        "generator_note": (
            "Manifiesto de CANDIDATURA, derivado del repositorio. No describe "
            "ninguna máquina y no ha desplegado nada. El manifiesto de una "
            "release INSTALADA lo escribe deploy/scripts/lib.sh::create_manifest "
            "en el host destino."
        ),

        "release": {
            "app_version": app_version(),
            "git_commit": git["commit"],
            "git_short_commit": git["short_commit"],
            "git_branch": git["branch"],
            "git_describe": git["describe"],
            "worktree_dirty": git["worktree_dirty"],
            "deploy_tag": None,
            "deploy_tag_note": (
                "No existe todavía ningún tag deploy-v3-*; cortarlo es requisito "
                "previo a desplegar (docs/project-status.yaml: next_release.blockers)."
            ),
        },

        "components": [
            {"name": c.name, "path": c.path, "purpose": c.purpose, "deployed": c.deployed}
            for c in spec.COMPONENTS
        ],

        "schema_versions": {
            "auth_db": auth_v,
            "jobs_db": 1,
            "graph": "sin versionar (Neo4j no lleva número de esquema en este proyecto)",
        },

        "migrations_required": [
            {
                "id": m.id, "component": m.component, "reversible": m.reversible,
                "description": m.description, "rationale": m.rationale,
            }
            for m in spec.MIGRATIONS if m.required
        ],
        "migrations_not_required": [
            {
                "id": m.id, "component": m.component, "reversible": m.reversible,
                "description": m.description, "rationale": m.rationale,
            }
            for m in spec.MIGRATIONS if not m.required
        ],

        "configuration": {
            "config_file": "/etc/s9-knowledge/viewer.env",
            "template": "deploy/config/viewer.env.example",
            "checker": "deploy/release/config_check.py",
            "required_env": [
                {
                    "name": v.name, "level": v.level.value, "purpose": v.purpose,
                    "secret": v.secret, "file_alternative": v.file_alternative,
                    "default_in_code": v.default_in_code,
                }
                for v in spec.ENV_VARS
            ],
            "must_be_off": list(spec.MUST_BE_OFF),
            "secret_references": [
                {"path": f.path, "level": f.level.value, "purpose": f.purpose,
                 "max_mode": oct(f.max_mode) if f.max_mode else None,
                 "note": "referenciado por ruta; su contenido no se lee ni se imprime"}
                for f in spec.REQUIRED_FILES if f.secret
            ],
            "required_directories": [
                {"path": d.path, "level": d.level.value, "purpose": d.purpose,
                 "max_mode": oct(d.max_mode) if d.max_mode else None}
                for d in spec.REQUIRED_DIRS
            ],
        },

        "runtime_versions": {
            "python_tested_in_ci": declared_python(),
            "requirements": declared_versions,
            "neo4j_verified": "5.26.0-community (VM105 y servicio de CI)",
            "dependency_fingerprints": dependency_fingerprints(),
        },

        "services": [
            {"unit": unit, "level": level.value, "purpose": purpose}
            for unit, level, purpose in spec.SYSTEMD_UNITS
        ],

        "healthchecks": {
            "command": "python -m app.cli.health check",
            "exit_codes": {"0": "healthy", "1": "degraded", "2": "unhealthy",
                           "3": "error de configuración"},
            "http": ["GET /admin/health", "GET /api/admin/health (requiere rol admin)"],
            "no_public_health_endpoint": (
                "No existe /health sin autenticar. Cualquier sonda externa que "
                "espere /health obtendrá 404 o una redirección al login."
            ),
            "known_open_incident": (
                "El healthcheck de VM105 termina en `failed` (código 2) porque el "
                "componente `backups` reporta copias rancias. Es un aviso legítimo, "
                "no un falso positivo: desplegar sin resolverlo deja el timer en rojo "
                "desde el minuto uno y enmascara fallos posteriores."
            ),
        },

        "smoke_tests": {
            "runner": "deploy/release/smoke_lab.py",
            "scope": "laboratorio (in-process, proveedor mock o Neo4j efímero)",
            "checks": [{"id": cid, "asserts": desc} for cid, desc in spec.SMOKE_CHECKS],
        },

        "rollback": {
            "runbook": "docs/61-release-manifest-y-rollback.md",
            "keeps_previous_releases": 3,
            "steps": [
                {"order": s.order, "action": s.action, "detail": s.detail}
                for s in spec.ROLLBACK_PLAN
            ],
            "irreversible_migrations": [
                m.id for m in spec.MIGRATIONS if m.required and not m.reversible
            ],
            "recovery_metrics": list(spec.RECOVERY_METRICS),
        },

        "explicit_non_goals": [
            "NO se migra el grafo legacy (decisión NO APPLY del operador).",
            "NO se activa la ingesta real: S9K_ALLOW_REAL_INGEST permanece sin definir.",
            "NO se reduce la revisión humana: el piloto det∧NVIDIA sigue con "
            "auditoría del 100%.",
            "NO se instala el backup automático propuesto en deploy/propuestas/: "
            "sigue siendo una propuesta.",
        ],
    }


# ---------------------------------------------------------------------------
# Salida legible
# ---------------------------------------------------------------------------

def to_markdown(m: dict) -> str:
    lines: list[str] = []
    add = lines.append
    rel = m["release"]
    add(f"# Manifiesto de release — S9 Knowledge {rel['app_version']}")
    add("")
    add(f"- Commit: `{rel['git_commit']}` (rama `{rel['git_branch']}`)")
    add(f"- Generado: {m['generated_at']} por `{m['generated_by']}`")
    add(f"- Tag de despliegue: {rel['deploy_tag'] or '**ninguno todavía**'}")
    add("")
    add("## Versiones de esquema")
    for k, v in m["schema_versions"].items():
        add(f"- `{k}`: {v}")
    add("")
    add("## Migraciones NECESARIAS")
    for mig in m["migrations_required"]:
        add(f"- **{mig['id']}** ({mig['component']}, "
            f"{'reversible' if mig['reversible'] else 'IRREVERSIBLE'}): {mig['description']}")
        add(f"  - {mig['rationale']}")
    add("")
    add("## Migraciones explícitamente NO necesarias")
    for mig in m["migrations_not_required"]:
        add(f"- **{mig['id']}** ({mig['component']}): {mig['description']}")
        add(f"  - {mig['rationale']}")
    add("")
    add("## Configuración crítica")
    for var in m["configuration"]["required_env"]:
        if var["level"] == "CRITICAL":
            secret = " *(secreto: no se imprime)*" if var["secret"] else ""
            add(f"- `{var['name']}`{secret} — {var['purpose']}")
    add("")
    add("## Secretos (por ruta, nunca por valor)")
    for s in m["configuration"]["secret_references"]:
        add(f"- `{s['path']}` (máx. {s['max_mode']}) — {s['purpose']}")
    add("")
    add("## Métricas de recuperación")
    for met in m["rollback"]["recovery_metrics"]:
        add(f"- **{met['metric']}**: {met['value']} (medido: {met['measured']}) — {met['detail']}")
    add("")
    add("## Fuera de alcance (explícito)")
    for item in m["explicit_non_goals"]:
        add(f"- {item}")
    add("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-o", "--output", help="fichero de salida (por defecto stdout)")
    parser.add_argument("--format", choices=("json", "md"), default="json")
    args = parser.parse_args(argv)

    try:
        manifest = build_manifest()
        text = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
                if args.format == "json" else to_markdown(manifest))
    except ManifestError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - un fallo inesperado nunca sale con 0
        print(f"ERROR interno generando el manifiesto: {exc!r}", file=sys.stderr)
        return 2

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"manifiesto escrito en {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
