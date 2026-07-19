"""Q — invariantes de SUPPLY CHAIN sobre el `.github/dependabot.yml` REAL.

Tras la integración de B-SEC-1 (#44), `.github/dependabot.yml` existe en main. Q lo
LEE (no lo edita: `.github/**` es área del Organizador) y comprueba su política.
MUTATION check: habilitar auto-merge de major debe hacer fallar la validación.
"""
from __future__ import annotations

import pytest

yaml = pytest.importorskip("yaml", reason="PyYAML requerido para validar dependabot.yml")


def _load_real_dependabot(repo_root):
    path = repo_root / ".github" / "dependabot.yml"
    assert path.is_file(), "El .github/dependabot.yml real debe existir tras integrar #44"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _has_automerge(cfg: dict) -> bool:
    """True si la configuración habilita cualquier forma de auto-merge."""
    import re
    blob = yaml.safe_dump(cfg)
    return bool(re.search(r"auto.?merge", blob, re.IGNORECASE))


def test_dependabot_version_2(repo_root):
    cfg = _load_real_dependabot(repo_root)
    assert cfg.get("version") == 2


def test_dependabot_covers_real_ecosystems(repo_root):
    cfg = _load_real_dependabot(repo_root)
    ecos = {u.get("package-ecosystem") for u in cfg.get("updates", [])}
    assert "pip" in ecos
    assert "github-actions" in ecos
    # npm/docker no deben aparecer si no existen manifiestos reales.
    assert "npm" not in ecos
    assert "docker" not in ecos


def test_dependabot_has_no_automerge(repo_root):
    cfg = _load_real_dependabot(repo_root)
    assert _has_automerge(cfg) is False


@pytest.mark.mutation
def test_mutation_major_automerge_is_rejected(repo_root):
    """La config real NO tiene auto-merge; una versión mutada con auto-merge de
    major DEBE ser rechazada por la validación (regla load-bearing)."""
    cfg = _load_real_dependabot(repo_root)
    assert _has_automerge(cfg) is False  # real: conforme
    mutated = dict(cfg)
    mutated["automerge"] = {"update-types": ["version-update:semver-major"]}
    assert _has_automerge(mutated) is True  # la mutación se detecta -> se rechazaría
