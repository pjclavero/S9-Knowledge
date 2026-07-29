from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "dev" / "create_workspace.py"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def test_crea_y_valida_workspace_minimo(tmp_path: Path) -> None:
    result = run("campana_2", "--root", str(tmp_path))
    assert result.returncode == 0, result.stderr
    target = tmp_path / "campana_2"
    assert {p.name for p in target.iterdir()} == {
        "workspace.json", "sources", "profiles", "ledger", "audit"
    }
    metadata = json.loads((target / "workspace.json").read_text(encoding="utf-8"))
    assert metadata["workspace"] == "campana_2"
    assert metadata["profile_workspace_must_equal"] == "campana_2"
    assert metadata["writer_environment"]["S9K_WRITER_WORKSPACE"] == "campana_2"
    assert run("campana_2", "--validate", str(target)).returncode == 0


def test_rechaza_nombre_inseguro_y_no_sobrescribe(tmp_path: Path) -> None:
    assert run("../escape", "--root", str(tmp_path)).returncode == 1
    assert run("estable", "--root", str(tmp_path)).returncode == 0
    assert run("estable", "--root", str(tmp_path)).returncode == 1


def test_validacion_detecta_workspace_inconsistente(tmp_path: Path) -> None:
    assert run("uno", "--root", str(tmp_path)).returncode == 0
    metadata = tmp_path / "uno" / "workspace.json"
    data = json.loads(metadata.read_text(encoding="utf-8"))
    data["workspace"] = "otro"
    metadata.write_text(json.dumps(data), encoding="utf-8")
    result = run("--validate", str(tmp_path / "uno"))
    assert result.returncode == 1
    assert "no coincide" in result.stderr
