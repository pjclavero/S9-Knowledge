"""test_supply_chain_config.py — invariantes de SUPPLY CHAIN / Dependabot.

Contrato de referencia: docs/coordination/dependabot-analysis.md (Equipo B / B-SEC-1).

AUTOCONTENIDO: `.github/dependabot.yml` es área compartida (lo aplica el Organizador
por PR de integración) y HOY no existe en main. Q NO edita `.github/**`. Aquí
definimos como FIXTURE el YAML de dependabot de referencia PROPUESTO y validamos
sus invariantes de política. En la integración, el `.github/dependabot.yml` real
deberá cumplir estas mismas reglas.

Reglas: version==2; ecosistemas existentes (pip, github-actions); SIN auto-merge
(en especial de major); las Actions deben poder pinnearse por SHA de 40 hex.
"""
from __future__ import annotations

import re

import pytest
import yaml

# YAML de dependabot de REFERENCIA (calcado de dependabot-analysis.md). NO se
# escribe en .github/; vive solo como fixture para fijar la política.
REFERENCE_DEPENDABOT_YAML = """
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/data-engine"
    schedule: { interval: "weekly" }
    open-pull-requests-limit: 5
    groups:
      patch-minor: { update-types: ["patch", "minor"] }
    labels: ["dependencies", "data-engine"]
  - package-ecosystem: "pip"
    directory: "/viewer"
    schedule: { interval: "weekly" }
    open-pull-requests-limit: 5
    groups:
      patch-minor: { update-types: ["patch", "minor"] }
    labels: ["dependencies", "viewer"]
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule: { interval: "weekly" }
    open-pull-requests-limit: 3
    labels: ["ci", "dependencies"]
"""

KNOWN_ECOSYSTEMS = frozenset({"pip", "github-actions", "npm", "docker", "gradle", "maven"})
REQUIRED_ECOSYSTEMS = frozenset({"pip", "github-actions"})
SHA40 = re.compile(r"^[0-9a-f]{40}$")


def validate_dependabot(cfg: object, *, forbid_automerge: bool = True) -> list[str]:
    """Valida una config de dependabot. Devuelve códigos de veto (vacío == OK).

    `forbid_automerge` existe SOLO para el test de mutación.
    """
    v: list[str] = []
    if not isinstance(cfg, dict):
        return ["CONFIG_MALFORMED"]

    if cfg.get("version") != 2:
        v.append("VERSION_NOT_2")

    updates = cfg.get("updates")
    if not isinstance(updates, list) or not updates:
        v.append("NO_UPDATES")
        updates = []

    seen_ecos: set[str] = set()
    for i, upd in enumerate(updates):
        if not isinstance(upd, dict):
            v.append(f"UPDATE_MALFORMED:{i}")
            continue
        eco = upd.get("package-ecosystem")
        if eco not in KNOWN_ECOSYSTEMS:
            v.append(f"ECOSYSTEM_UNKNOWN:{eco}")
        else:
            seen_ecos.add(eco)

        # Sin auto-merge: ni flag propio ni update-types con semver-major "auto".
        if forbid_automerge:
            if _has_automerge(upd):
                v.append(f"AUTOMERGE_ENABLED:{i}")
            if _has_major_automerge(upd):
                v.append(f"AUTOMERGE_MAJOR:{i}")

    for eco in REQUIRED_ECOSYSTEMS:
        if eco not in seen_ecos:
            v.append(f"ECOSYSTEM_MISSING:{eco}")

    return v


def _has_automerge(upd: dict) -> bool:
    for key in ("auto-merge", "automerge", "auto_merge"):
        val = upd.get(key)
        if val is True or (isinstance(val, str) and val.lower() in {"true", "on", "yes"}):
            return True
        if isinstance(val, dict) and val.get("enabled") is True:
            return True
    return False


def _has_major_automerge(upd: dict) -> bool:
    """True si la config auto-mergearía majors (política prohibida)."""
    am = upd.get("auto-merge") or upd.get("automerge") or {}
    if isinstance(am, dict):
        for ut in am.get("update-types", []) or []:
            if "major" in str(ut).lower():
                return True
    return False


def is_action_pinnable(uses: str, sha: str) -> bool:
    """Una Action puede pinnearse si `uses` referencia repo@sha de 40 hex."""
    if "@" not in uses:
        return False
    if not SHA40.match(sha):
        return False
    return True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def reference_config() -> dict:
    return yaml.safe_load(REFERENCE_DEPENDABOT_YAML)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_reference_config_is_valid(reference_config):
    assert validate_dependabot(reference_config) == []


def test_version_must_be_2(reference_config):
    cfg = dict(reference_config)
    cfg["version"] = 1
    assert "VERSION_NOT_2" in validate_dependabot(cfg)


def test_required_ecosystems_present(reference_config):
    ecos = {u["package-ecosystem"] for u in reference_config["updates"]}
    assert REQUIRED_ECOSYSTEMS <= ecos


def test_reject_missing_required_ecosystem(reference_config):
    cfg = yaml.safe_load(REFERENCE_DEPENDABOT_YAML)
    cfg["updates"] = [u for u in cfg["updates"] if u["package-ecosystem"] != "github-actions"]
    assert "ECOSYSTEM_MISSING:github-actions" in validate_dependabot(cfg)


def test_reject_unknown_ecosystem(reference_config):
    cfg = yaml.safe_load(REFERENCE_DEPENDABOT_YAML)
    cfg["updates"].append({"package-ecosystem": "cargo-cult", "directory": "/"})
    assert "ECOSYSTEM_UNKNOWN:cargo-cult" in validate_dependabot(cfg)


def test_reference_config_has_no_automerge(reference_config):
    # Ninguna entrada de la config de referencia habilita auto-merge.
    assert all(not _has_automerge(u) for u in reference_config["updates"])


def test_action_is_pinnable():
    assert is_action_pinnable("actions/checkout@v4", "a" * 40) is True
    assert is_action_pinnable("actions/checkout@v4", "v4") is False  # tag, no SHA
    assert is_action_pinnable("actions-no-ref", "a" * 40) is False


# ---------------------------------------------------------------------------
# MUTATION CHECK
# Mutación: habilitar auto-merge de major. Si la política dejara de prohibir el
# auto-merge de majors, un update roto se fusionaría solo (RK-09). La validación
# estricta DEBE vetarlo.
# ---------------------------------------------------------------------------
@pytest.mark.mutation
def test_mutation_enabling_major_automerge_breaks(reference_config):
    cfg = yaml.safe_load(REFERENCE_DEPENDABOT_YAML)
    cfg["updates"][0]["auto-merge"] = {"update-types": ["version-update:semver-major"]}
    strict = validate_dependabot(cfg)                       # política activa
    relaxed = validate_dependabot(cfg, forbid_automerge=False)  # política relajada (mutante)
    assert any(x.startswith("AUTOMERGE_MAJOR") for x in strict)
    assert not any(x.startswith("AUTOMERGE_MAJOR") for x in relaxed)
