"""
test_resolve_release_commit.py — laboratorio Git REAL de la regresión forward-ref.

Reproduce el escenario de producción que rompió el deploy hacia RC5: desplegar
un tag/commit que TODAVÍA no está materializado en el object store local. El
patrón antiguo `$(git rev-parse "$ref" || printf '%s' "$ref")` imprimía el ref
DOS veces (una git a stdout aunque falle, otra el fallback), produciendo un
valor corrupto ("<sha>\n<sha>") que rompía el checkout con "invalid refspec".

Estos tests NO usan mocks de comandos: crean repositorios git de verdad (bare
origin + clones) y ejecutan la función bash real `resolve_release_commit` de
deploy/scripts/lib.sh. La prueba de regresión demuestra que el patrón antiguo
falla y que la función nueva pasa exactamente en el mismo escenario.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
LIB_SH = SCRIPTS_DIR / "lib.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git no disponible"
)

FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _git(cwd: Path, *args: str, check: bool = True, url: bool = False) -> str:
    env_cfg = [
        "-c", "user.email=lab@s9k.test",
        "-c", "user.name=s9k-lab",
        "-c", "commit.gpgsign=false",
        "-c", "init.defaultBranch=main",
        "-c", "protocol.file.allow=always",
    ]
    proc = subprocess.run(
        ["git", *env_cfg, *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} falló ({proc.returncode}): {proc.stderr}"
        )
    return proc.stdout.strip()


def resolve(ref: str, work_dir: Path, repo_url: str | None = None,
            allow_branch: bool = False) -> subprocess.CompletedProcess[str]:
    """Invoca la función bash real y captura stdout/stderr/rc por separado."""
    args = [ref, "--work-dir", str(work_dir)]
    if repo_url is not None:
        args += ["--repo-url", repo_url]
    if allow_branch:
        args += ["--allow-branch"]
    script = f'set -Eeuo pipefail; . "{LIB_SH}"; resolve_release_commit "$@"'
    return subprocess.run(
        ["bash", "-c", script, "_", *args],
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def lab(tmp_path: Path) -> dict:
    """Monta el laboratorio: origin bare con commit A; tag anotado sobre B.

    - origin (bare): contiene A, B y el tag anotado deploy-test-rc (-> B).
    - operativo: clon que SOLO conoce A (no tiene B ni el tag materializados).
    Simula exactamente producción antes de un deploy hacia delante.
    """
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "--bare")

    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "clone", str(origin), ".")
    (seed / "file.txt").write_text("A\n")
    _git(seed, "add", "file.txt")
    _git(seed, "commit", "-m", "commit A")
    _git(seed, "push", "origin", "main")
    sha_a = _git(seed, "rev-parse", "HEAD")

    # Clon operativo que solo conoce A (estado "current" en producción).
    operativo = tmp_path / "operativo"
    operativo.mkdir()
    _git(operativo, "clone", str(origin), ".")
    assert _git(operativo, "rev-parse", "HEAD") == sha_a

    # Segundo clon crea B + tag anotado y lo publica; el operativo NO lo trae.
    dev = tmp_path / "dev"
    dev.mkdir()
    _git(dev, "clone", str(origin), ".")
    (dev / "file.txt").write_text("B\n")
    _git(dev, "add", "file.txt")
    _git(dev, "commit", "-m", "commit B")
    sha_b = _git(dev, "rev-parse", "HEAD")
    _git(dev, "tag", "-a", "deploy-test-rc", "-m", "release B")
    _git(dev, "tag", "deploy-test-lightweight")  # tag ligero sobre B
    _git(dev, "push", "origin", "main")
    _git(dev, "push", "origin", "deploy-test-rc")
    _git(dev, "push", "origin", "deploy-test-lightweight")

    return {
        "origin": origin,
        "operativo": operativo,
        "url": str(origin),
        "sha_a": sha_a,
        "sha_b": sha_b,
    }


# ---------------------------------------------------------------------------
# PRUEBA DE REGRESIÓN: el patrón antiguo falla; la función nueva pasa.
# ---------------------------------------------------------------------------
def test_regression_old_pattern_duplicates_new_pattern_clean(lab: dict) -> None:
    op = lab["operativo"]
    # El operativo NO tiene el tag. El patrón ANTIGUO duplica el ref.
    old = subprocess.run(
        ["bash", "-c",
         'git -C "$1" rev-parse "$2" 2>/dev/null || printf "%s" "$2"',
         "_", str(op), "deploy-test-rc"],
        capture_output=True, text=True,
    )
    # rev-parse imprime el ref (a stdout) Y falla -> el fallback lo imprime de
    # nuevo: el valor contiene "deploy-test-rc" dos veces (multilínea).
    assert old.stdout.count("deploy-test-rc") == 2, (
        f"el patrón antiguo debería duplicar el ref, dio: {old.stdout!r}"
    )

    # La función NUEVA, en el MISMO estado, hace fetch seguro y da UN SHA limpio.
    new = resolve("deploy-test-rc", op, repo_url=lab["url"])
    assert new.returncode == 0, new.stderr
    assert new.stdout.strip() == lab["sha_b"]
    assert FULL_SHA_RE.match(new.stdout.strip())
    assert "deploy-test-rc" not in new.stdout  # nunca el ref original
    assert new.stdout.count("\n") == 1  # exactamente una línea


# ---------------------------------------------------------------------------
# Resolución correcta de cada tipo de ref ausente localmente.
# ---------------------------------------------------------------------------
def test_annotated_tag_absent_locally(lab: dict) -> None:
    r = resolve("deploy-test-rc", lab["operativo"], repo_url=lab["url"])
    assert r.returncode == 0
    assert r.stdout.strip() == lab["sha_b"]


def test_lightweight_tag_absent_locally(lab: dict) -> None:
    r = resolve("deploy-test-lightweight", lab["operativo"], repo_url=lab["url"])
    assert r.returncode == 0
    assert r.stdout.strip() == lab["sha_b"]


def test_full_sha_absent_but_reachable_via_origin(lab: dict) -> None:
    r = resolve(lab["sha_b"], lab["operativo"], repo_url=lab["url"])
    assert r.returncode == 0
    assert r.stdout.strip() == lab["sha_b"]


def test_commit_already_present_no_url_needed(lab: dict) -> None:
    # A ya está en el operativo: resuelve en local sin necesitar --repo-url
    # (caso rollback hacia un commit ya presente).
    r = resolve(lab["sha_a"], lab["operativo"])
    assert r.returncode == 0
    assert r.stdout.strip() == lab["sha_a"]


def test_idempotent_repeat(lab: dict) -> None:
    first = resolve("deploy-test-rc", lab["operativo"], repo_url=lab["url"])
    second = resolve("deploy-test-rc", lab["operativo"], repo_url=lab["url"])
    assert first.stdout == second.stdout == lab["sha_b"] + "\n"


# ---------------------------------------------------------------------------
# Fallos que DEBEN devolver rc!=0 y stdout vacío (nunca el ref).
# ---------------------------------------------------------------------------
def test_nonexistent_sha_fails(lab: dict) -> None:
    fake = "0" * 40
    r = resolve(fake, lab["operativo"], repo_url=lab["url"])
    assert r.returncode != 0
    assert r.stdout.strip() == ""


def test_nonexistent_tag_fails(lab: dict) -> None:
    r = resolve("deploy-does-not-exist", lab["operativo"], repo_url=lab["url"])
    assert r.returncode != 0
    assert r.stdout.strip() == ""


def test_absent_without_url_fails_cleanly(lab: dict) -> None:
    r = resolve("deploy-test-rc", lab["operativo"])  # sin --repo-url
    assert r.returncode == 1
    assert r.stdout.strip() == ""
    assert "deploy-test-rc" not in r.stdout


def test_unreachable_origin_fails(lab: dict, tmp_path: Path) -> None:
    r = resolve("deploy-test-rc", lab["operativo"],
                repo_url=str(tmp_path / "no-existe.git"))
    assert r.returncode != 0
    assert r.stdout.strip() == ""


# ---------------------------------------------------------------------------
# Endurecimiento: inyección de opciones, refs ambiguas, multilínea, no-commit.
# ---------------------------------------------------------------------------
def test_ref_starting_with_dash_rejected(lab: dict) -> None:
    r = resolve("--upload-pack=touch /tmp/pwned", lab["operativo"],
                repo_url=lab["url"])
    assert r.returncode == 2
    assert r.stdout.strip() == ""
    assert not Path("/tmp/pwned").exists()


def test_ref_with_newline_rejected(lab: dict) -> None:
    r = resolve("deploy-test-rc\nrm -rf /", lab["operativo"], repo_url=lab["url"])
    assert r.returncode == 2
    assert r.stdout.strip() == ""


def test_ref_with_space_rejected(lab: dict) -> None:
    r = resolve("deploy test", lab["operativo"], repo_url=lab["url"])
    assert r.returncode == 2


def test_short_sha_too_short_rejected(lab: dict) -> None:
    r = resolve("abc", lab["operativo"], repo_url=lab["url"])
    assert r.returncode == 2


def test_non_deploy_branch_rejected_in_release_mode(lab: dict) -> None:
    # 'main' es una branch: en modo release (sin --allow-branch) se rechaza.
    r = resolve("main", lab["operativo"], repo_url=lab["url"])
    assert r.returncode == 2
    assert r.stdout.strip() == ""


def test_branch_allowed_only_with_flag(lab: dict) -> None:
    # Con --allow-branch (entorno dev), 'main' resuelve al commit del tip.
    r = resolve("main", lab["operativo"], repo_url=lab["url"], allow_branch=True)
    assert r.returncode == 0
    assert FULL_SHA_RE.match(r.stdout.strip())


def test_object_that_is_not_a_commit_rejected(lab: dict) -> None:
    # SHA de un blob (contenido de file.txt en A): no es un commit -> rechazado.
    blob = _git(lab["operativo"], "rev-parse", "HEAD:file.txt")
    r = resolve(blob, lab["operativo"])
    assert r.returncode != 0
    assert r.stdout.strip() == ""


# ---------------------------------------------------------------------------
# Shallow clone: el objeto ausente se materializa igual vía fetch.
# ---------------------------------------------------------------------------
def test_shallow_clone_forward_ref(lab: dict, tmp_path: Path) -> None:
    shallow = tmp_path / "shallow"
    shallow.mkdir()
    _git(shallow, "clone", "--depth", "1", str(lab["origin"]), ".")
    r = resolve("deploy-test-rc", shallow, repo_url=lab["url"])
    assert r.returncode == 0
    assert r.stdout.strip() == lab["sha_b"]
