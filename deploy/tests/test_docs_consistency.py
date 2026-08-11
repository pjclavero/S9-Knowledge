"""
test_docs_consistency.py — pruebas del validador de coherencia documental.

Verifica que scripts/check_docs_consistency.py:
  1. detecta afirmaciones obsoletas;
  2. respeta los bloques históricos marcados;
  3. respeta las negaciones ("Basic Auth retirada" no es un fallo);
  4. da coherente sobre el repositorio real (los docs versionados están al día);
  5. CALIBRACIÓN DEL PUNTO 0: cada violación conocida se pone roja de verdad.

Sobre el punto 5. La calibración de ese mecanismo vivía sólo en el cuerpo de un
PR, y el cuerpo de un PR no se ejecuta. El defecto que cierra era mudo: el
validador imprimía «DOCUMENTACION COHERENTE» mientras el YAML declaraba
`fb4a6fe`/#144 con `main` real 19 commits y 19 PR por delante. Nada impide que
una edición futura lo devuelva a ciego con CI en verde — salvo estas pruebas.

Cada una sigue el mismo ciclo: repositorio de mentira COHERENTE (verde), UNA
violación introducida, exigencia de rojo. Y con control negativo donde procede:
un gate que enrojece siempre tampoco vale.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[2]
CHECKER = REPO / "scripts" / "check_docs_consistency.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_docs_consistency", CHECKER)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_repo_docs_are_coherent():
    """El estado versionado no debe contener contradicciones conocidas."""
    mod = _load()
    assert mod.main() == 0


def test_detects_obsolete_basic_auth(tmp_path: Path):
    mod = _load()
    doc = tmp_path / "x.md"
    doc.write_text("El acceso externo usa nginx + Basic Auth como autenticación.\n")
    findings = mod.scan_doc(doc)
    assert any("basic-auth-vigente" in f for f in findings), findings


def test_negation_suppresses_basic_auth(tmp_path: Path):
    mod = _load()
    doc = tmp_path / "x.md"
    doc.write_text("Basic Auth retirada del proxy; autenticación en la app.\n")
    assert mod.scan_doc(doc) == []


def test_historical_block_is_ignored(tmp_path: Path):
    mod = _load()
    doc = tmp_path / "x.md"
    doc.write_text(
        "# Guía vigente\n"
        "Todo correcto.\n"
        "## HISTÓRICO — diseño inicial\n"
        "En su día el visor solo tenía Basic Auth y 220 tests.\n"
    )
    # La frase obsoleta vive bajo un encabezado histórico -> no se marca.
    assert mod.scan_doc(doc) == []


def test_inline_ignore_marker(tmp_path: Path):
    mod = _load()
    doc = tmp_path / "x.md"
    doc.write_text("Antes: Basic Auth en el proxy. <!-- consistency:ignore -->\n")
    assert mod.scan_doc(doc) == []


def test_detects_fixed_test_count(tmp_path: Path):
    mod = _load()
    doc = tmp_path / "x.md"
    doc.write_text("La suite tiene 220 tests verdes.\n")
    findings = mod.scan_doc(doc)
    assert any("tests-fijos" in f for f in findings), findings


# ---------------------------------------------------------------------------
# Calibración del PUNTO 0: la autoridad es Git, no el YAML.
# ---------------------------------------------------------------------------

PROD_TAG = "deploy-v0.3.0-rc5.1"
PROD_COMMIT = "47bc3147fdab"

CI_TODA_RAMA = textwrap.dedent("""\
    name: CI
    on:
      push:
        branches:
          - '**'
    jobs:
      uno:
        name: Job Uno
      dos:
        name: Job Dos
    """)


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def write_status(repo: Path, **over) -> None:
    dev = {
        "main_commit": over.get("main_commit"),
        "latest_merged_pr": over.get("latest_merged_pr"),
        "max_lag_commits": over.get("max_lag_commits", 3),
        "max_test_age_days": over.get("max_test_age_days", 30),
        "ci_jobs_running": over.get("ci_jobs_running", 2),
        "ci_checks_required": over.get("ci_checks_required", 1),
        "ci_required_checks": over.get("ci_required_checks", ["Job Uno"]),
        "ci_running_but_not_required": over.get(
            "ci_running_but_not_required", ["Job Dos"]),
        "completed_programs": over.get("completed_programs", []),
    }
    if "tests" in over:
        dev["tests"] = over["tests"]
    data = {
        "development": dev,
        "production": {"production_tag": PROD_TAG, "commit": PROD_COMMIT},
    }
    (repo / "docs" / "project-status.yaml").write_text(yaml.safe_dump(data))


def write_docs(repo: Path, main_short: str, pr: int, extra: str = "") -> None:
    (repo / "README.md").write_text(
        f"# R\n\n`main`, commit `{main_short}`, ultimo PR mergeado #{pr}.\n{extra}"
    )
    for rel in ("ROADMAP.md", "CHANGELOG.md"):
        (repo / rel).write_text("# doc\nnada que objetar.\n")
    (repo / "viewer" / "README.md").write_text("# visor\nnada que objetar.\n")
    (repo / "docs" / "archivados" / "02-current-state.md").write_text(
        f"# canonico\nproduccion {PROD_TAG} en {PROD_COMMIT}.\n"
    )


@pytest.fixture
def fake_repo(tmp_path: Path):
    """Repositorio mínimo con historia de `main` y documentación coherente.

    `refs/remotes/origin/main` se crea a mano: así `_resolve_main` lo encuentra
    sin red y sin remoto de verdad.

    Los asuntos de los commits imitan el orden real de `main`, donde el #160 se
    fusionó ANTES que el #158 — el caso que hace que «el último PR» no sea «el
    de número mayor».
    """
    repo = tmp_path / "repo"
    (repo / "docs" / "archivados").mkdir(parents=True)
    (repo / "scripts").mkdir()
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / "viewer").mkdir()

    _git(tmp_path, "init", "-q", "-b", "main", str(repo))
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")

    shas: list[str] = []
    for subject in ("inicial", "algo (#160)", "otra cosa (#158)"):
        (repo / "f.txt").write_text(subject)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", subject)
        shas.append(_git(repo, "rev-parse", "HEAD"))
    _git(repo, "update-ref", "refs/remotes/origin/main", shas[-1])

    (repo / ".github" / "workflows" / "ci.yml").write_text(CI_TODA_RAMA)
    write_status(repo, main_commit=shas[-1], latest_merged_pr=158)
    write_docs(repo, main_short=shas[-1][:7], pr=158)
    return repo, shas


def check(repo: Path, env: dict | None = None) -> tuple[int, str]:
    """Ejecuta el validador APUNTANDO AL REPOSITORIO DE MENTIRA."""
    mod = _load()
    mod.REPO = repo
    mod.STATUS_YAML = repo / "docs" / "project-status.yaml"
    old = dict(os.environ)
    os.environ.pop(mod.SKIP_GIT_ENV, None)
    if env:
        os.environ.update(env)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = mod.main()
    finally:
        os.environ.clear()
        os.environ.update(old)
    return rc, buf.getvalue()


# --- C0: control positivo. Sin esto, un rojo permanente pasaría por éxito.
def test_c0_baseline_coherente(fake_repo):
    repo, _ = fake_repo
    rc, out = check(repo)
    assert rc == 0, out


# --- C1/C2: el documento contradice al YAML
def test_c1_doc_atribuye_a_main_un_sha_falso(fake_repo):
    repo, _ = fake_repo
    write_docs(repo, main_short="deadbee", pr=158)
    rc, out = check(repo)
    assert rc == 1 and "atribuye a `main`" in out, out


def test_c2_doc_cita_un_ultimo_pr_falso(fake_repo):
    repo, shas = fake_repo
    write_docs(repo, main_short=shas[-1][:7], pr=999)
    rc, out = check(repo)
    assert rc == 1 and "#999" in out, out


# --- C3/C4: frases prohibidas
def test_c3_frase_obsoleta_conocida(fake_repo):
    repo, shas = fake_repo
    write_docs(repo, main_short=shas[-1][:7], pr=158,
               extra="\nEl acceso se protege con Basic Auth.\n")
    rc, out = check(repo)
    assert rc == 1 and "basic-auth-vigente" in out, out


def test_c4_programa_cerrado_descrito_como_pendiente(fake_repo):
    repo, shas = fake_repo
    write_status(repo, main_commit=shas[-1], latest_merged_pr=158,
                 completed_programs=[{"name": "M5b", "state": "CERRADO",
                                      "doc_forbids": ["M5b pendiente"]}])
    write_docs(repo, main_short=shas[-1][:7], pr=158, extra="\nM5b pendiente\n")
    rc, out = check(repo)
    assert rc == 1 and "M5b" in out, out


# --- C5: el documento canónico deja de mencionar producción
def test_c5_canonico_sin_commit_de_produccion(fake_repo):
    repo, _ = fake_repo
    (repo / "docs" / "archivados" / "02-current-state.md").write_text("# vacio\n")
    rc, out = check(repo)
    assert rc == 1 and "02-current-state" in out, out


# --- C6: EL CASO QUE ANTES PASABA EN VERDE ---------------------------------
def test_c6_yaml_y_docs_mienten_a_la_vez(fake_repo):
    """Coherencia interna perfecta describiendo un repositorio inexistente.

    Es el fallo original: el YAML era la «fuente de verdad» y nadie comprobaba
    la fuente de verdad. Sin el punto 0, esto da rc=0.
    """
    repo, _ = fake_repo
    inventado = "1" * 40
    write_status(repo, main_commit=inventado, latest_merged_pr=4242)
    write_docs(repo, main_short=inventado[:7], pr=4242)
    rc, out = check(repo)
    assert rc == 1, out
    assert "NO EXISTE" in out, out
    assert "#4242" in out, out


# --- C7/C8/C9: desfase real, con y sin tolerancia --------------------------
def test_c7_main_commit_real_pero_desfasado(fake_repo):
    """El caso que estaba VIVO en el entregable, con la tolerancia agotada."""
    repo, shas = fake_repo
    write_status(repo, main_commit=shas[0], latest_merged_pr=158,
                 max_lag_commits=1)
    write_docs(repo, main_short=shas[0][:7], pr=158)
    rc, out = check(repo)
    assert rc == 1 and "commits por detras" in out, out


def test_c8_desfase_de_uno_con_tolerancia_cero(fake_repo):
    repo, shas = fake_repo
    write_status(repo, main_commit=shas[-2], latest_merged_pr=160,
                 max_lag_commits=0)
    write_docs(repo, main_short=shas[-2][:7], pr=160)
    rc, out = check(repo)
    assert rc == 1 and "maximo declarado es 0" in out, out


def test_c9_mismo_desfase_dentro_de_la_tolerancia(fake_repo):
    """Complemento de C8: el MISMO desfase, tolerado, tiene que dar VERDE.

    Sin esta fila C8 no prueba nada, porque un gate que enrojece siempre
    también «detectaría» el desfase.

    Ojo al montaje: hay que reescribir la documentación entera para que apunte
    al commit desfasado. Si sólo se cambia el YAML, el rojo llega por otra vía
    —la contradicción documento->YAML— y la fila mediría otra cosa. Esa
    confusión ocurrió de verdad durante la revisión.
    """
    repo, shas = fake_repo
    write_status(repo, main_commit=shas[-2], latest_merged_pr=160,
                 max_lag_commits=3)
    write_docs(repo, main_short=shas[-2][:7], pr=160)
    rc, out = check(repo)
    assert rc == 0, out


def test_c10_commit_real_pero_fuera_de_la_historia_de_main(fake_repo):
    repo, shas = fake_repo
    # El commit lateral se fabrica con `commit-tree`, SIN pasar por el árbol de
    # trabajo: un `checkout` a otra rama se llevaría por delante la
    # documentación del fixture y la prueba fallaría por un motivo que no es el
    # que quiere medir.
    tree = _git(repo, "rev-parse", f"{shas[0]}^{{tree}}")
    lateral = _git(repo, "commit-tree", tree, "-p", shas[0], "-m", "lateral")
    write_status(repo, main_commit=lateral, latest_merged_pr=158)
    write_docs(repo, main_short=lateral[:7], pr=158)
    rc, out = check(repo)
    assert rc == 1 and "no esta en la historia" in out, out


# --- C11: sin Git NO se pasa a verde en silencio ---------------------------
def _cegar_git(repo: Path) -> None:
    _git(repo, "update-ref", "-d", "refs/remotes/origin/main")
    _git(repo, "branch", "-m", "main", "otra-cosa")


def test_c11_sin_main_resoluble_es_rojo(fake_repo):
    repo, _ = fake_repo
    _cegar_git(repo)
    rc, out = check(repo)
    assert rc == 1 and "no se ha podido resolver" in out, out


def test_c11b_la_exencion_es_explicita_y_lo_dice_en_el_titular(fake_repo):
    """`S9_DOCS_SKIP_GIT=1` puede saltarse el punto 0, pero NO puede mentir.

    Antes imprimía «DOCUMENTACION COHERENTE» a secas: un verde con aspecto de
    verificado sin serlo. El titular tiene que declarar su propio alcance.
    """
    repo, _ = fake_repo
    _cegar_git(repo)
    rc, out = check(repo, env={"S9_DOCS_SKIP_GIT": "1"})
    assert rc == 0, out
    assert "SIN VERIFICAR CONTRA GIT" in out, out


# --- R5: la configuración de CI también es código, y también manda ---------
def test_r5_afirmacion_falsa_sobre_disparadores_de_ci(fake_repo):
    """«`test/**` no dispara CI» con `branches: ['**']` en `ci.yml`.

    Es el defecto exacto que dejó NO CONFORME al trabajo revisado, y pasaba en
    verde porque el gate nunca leía `ci.yml`.
    """
    repo, shas = fake_repo
    write_docs(repo, main_short=shas[-1][:7], pr=158,
               extra="\nEl prefijo `test/**` no dispara CI en push.\n")
    rc, out = check(repo)
    assert rc == 1 and "no dispara CI" in out, out


def test_r5b_con_lista_blanca_la_misma_frase_puede_ser_cierta(fake_repo):
    """Control negativo: si `ci.yml` vuelve a una lista blanca, no se opina."""
    repo, shas = fake_repo
    (repo / ".github" / "workflows" / "ci.yml").write_text(textwrap.dedent("""\
        name: CI
        on:
          push:
            branches: ['main', 'feat/**']
        jobs:
          uno:
            name: Job Uno
          dos:
            name: Job Dos
        """))
    write_docs(repo, main_short=shas[-1][:7], pr=158,
               extra="\nEl prefijo `test/**` no dispara CI en push.\n")
    rc, out = check(repo)
    assert rc == 0, out


# --- R7: los números de CI se derivan de los workflows, no se escriben -----
def test_r7_inventario_de_ci_inventado(fake_repo):
    """`99/99` pasaba en verde: era prosa numérica dentro del propio YAML."""
    repo, shas = fake_repo
    write_status(repo, main_commit=shas[-1], latest_merged_pr=158,
                 ci_jobs_running=99, ci_checks_required=99)
    rc, out = check(repo)
    assert rc == 1 and "ci_jobs_running" in out, out


def test_r7b_nombre_de_check_que_no_existe(fake_repo):
    repo, shas = fake_repo
    write_status(repo, main_commit=shas[-1], latest_merged_pr=158,
                 ci_required_checks=["Job Fantasma"])
    rc, out = check(repo)
    assert rc == 1 and "Job Fantasma" in out, out


def test_r7c_particion_incoherente(fake_repo):
    """`no requeridos` debe ser exactamente «todos menos los requeridos»."""
    repo, shas = fake_repo
    write_status(repo, main_commit=shas[-1], latest_merged_pr=158,
                 ci_running_but_not_required=["Job Uno"])
    rc, out = check(repo)
    assert rc == 1 and "ci_running_but_not_required" in out, out


# --- R4: la marca `stale` caduca -------------------------------------------
def test_r4_medicion_vieja_sin_marcar_stale(fake_repo):
    repo, shas = fake_repo
    write_status(repo, main_commit=shas[-1], latest_merged_pr=158,
                 tests={"commit": shas[0], "measured_at": "2026-08-01",
                        "collected": 7284})
    rc, out = check(repo)
    assert rc == 1 and "stale" in out, out


def test_r4b_medicion_marcada_pero_caducada(fake_repo):
    repo, shas = fake_repo
    write_status(repo, main_commit=shas[-1], latest_merged_pr=158,
                 max_test_age_days=1,
                 tests={"commit": shas[0], "measured_at": "2020-01-01",
                        "collected": 7284, "stale": True})
    rc, out = check(repo)
    assert rc == 1 and "caduco" in out, out


def test_r4c_medicion_del_commit_actual_no_caduca(fake_repo):
    """Control negativo: si la medida ES la de `main`, no se exige nada."""
    repo, shas = fake_repo
    write_status(repo, main_commit=shas[-1], latest_merged_pr=158,
                 tests={"commit": shas[-1], "measured_at": "2020-01-01",
                        "collected": 7284})
    rc, out = check(repo)
    assert rc == 0, out


# --- O2: la puerta trasera no puede colarse en un workflow -----------------
def test_o2_la_variable_de_exencion_no_esta_en_ningun_workflow():
    """`S9_DOCS_SKIP_GIT` desactiva el punto 0 entero.

    El meta-gate que lo detectaría no es requerido (RK-20), así que un PR podría
    añadirla a un `env:` y fusionar con el gate ciego y en verde. Esto lo impide
    desde un check que SÍ es requerido.
    """
    wf_dir = REPO / ".github" / "workflows"
    ofensores = sorted(
        p.name for p in wf_dir.glob("*.yml")
        if "S9_DOCS_SKIP_GIT" in p.read_text(encoding="utf-8")
    )
    assert not ofensores, (
        f"{ofensores} desactivan la verificacion contra Git del validador "
        f"documental; si es intencionado se discute, no se cuela"
    )
