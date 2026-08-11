"""Fuentes que declaran el esquema, para releases sintéticas de las pruebas.

`create_manifest` y `verify_release_identity` ya no aceptan un literal escrito
a mano: leen la versión de esquema del código de la propia release. Una release
de prueba sin esos ficheros no es una release, y por eso el manifiesto aborta y
el verificador responde UNKNOWN. Estas ayudas plantan los fuentes mínimos con
las MISMAS constantes que el repositorio real.
"""
from __future__ import annotations

from pathlib import Path

#: Se leen del repositorio de verdad para que las pruebas no fijen un número
#: que pueda quedarse atrás cuando suba el esquema.
_REPO = Path(__file__).resolve().parents[2]


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def plant_schema_sources(release_dir: Path) -> None:
    """Copia a `release_dir` los ficheros que declaran versión y rango."""
    for rel in (
        "viewer/app/auth/db.py",
        "viewer/app/auth/schema_compat.py",
        "data-engine/app/jobs/job_store.py",
    ):
        _copy(_REPO / rel, release_dir / rel)


def declared_auth_db_version() -> int:
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "_s9k_sv_fixture", _REPO / "deploy" / "scripts" / "schema_versions.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_s9k_sv_fixture"] = mod
    spec.loader.exec_module(mod)
    return mod.declared_versions(_REPO)["auth_db"]
