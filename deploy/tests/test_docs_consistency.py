"""
test_docs_consistency.py — pruebas del validador de coherencia documental.

Dos bloques:

  * Pruebas de unidad sobre `scan_doc` (patrones obsoletos, bloques históricos).
  * **Tabla de calibración C0–C13** sobre un repositorio Git SINTÉTICO. Cada
    fila rompe UNA condición y exige rojo; el baseline (C0) y la reversión
    (FIN) exigen verde. Un gate sólo cuenta como gate si se le ha visto en
    rojo: hasta este fichero, las ~300 líneas del punto 0 no tenían ni una
    prueba, y la tabla del PR vivía en la descripción, no en CI.

El repositorio sintético existe para poder mentirle a Git sin tocar el real:
tiene su propia historia, su propio `origin/main` y sus propios workflows, así
que las filas que dependen de ancestría y desfase (C6–C10) son ejecutables y
deterministas en cualquier máquina y en CI.
"""
from __future__ import annotations

import importlib.util
import subprocess
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


# --- Bloque 1: unidad sobre scan_doc -------------------------------------

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


# --- Bloque 2: repositorio sintético y tabla de calibración --------------

PROD_TAG = "deploy-v9.9.9-rcX"
PROD_COMMIT = "47bc3147fdab0000000000000000000000000000"

CI_YML = """\
name: CI
on:
  push:
    branches:
      - '**'
  pull_request:
    branches: [ main ]
jobs:
  a:
    name: Job A
    runs-on: ubuntu-latest
    steps: [{run: 'true'}]
  b:
    name: Job B
    runs-on: ubuntu-latest
    steps: [{run: 'true'}]
  c:
    name: Job C (no exigido)
    runs-on: ubuntu-latest
    steps: [{run: 'true'}]
"""


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


class Sandbox:
    """Repositorio sintético + acceso al validador apuntando a él."""

    def __init__(self, mod, root: Path):
        self.mod = mod
        self.root = root

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def read(self, rel: str) -> str:
        return (self.root / rel).read_text(encoding="utf-8")

    def status(self) -> dict:
        return yaml.safe_load(self.read("docs/project-status.yaml"))

    def set_status(self, data: dict) -> None:
        self.write("docs/project-status.yaml", yaml.safe_dump(data, allow_unicode=True))

    def patch_dev(self, **kw) -> None:
        data = self.status()
        data["development"].update(kw)
        self.set_status(data)

    def run(self) -> int:
        return self.mod.main()

    def findings(self) -> list[str]:
        """Contradicciones, sin pasar por el rc, para poder leer el motivo."""
        data = self.status()
        wf = self.mod._load_workflows()
        dev = data.get("development", {})
        out: list[str] = []
        for rel in self.mod.DOCS:
            out += self.mod.scan_doc(self.root / rel)
        out += self.mod.check_canonical(data.get("production", {}))
        out += self.mod.check_git_authority(dev)
        out += self.mod.check_development(dev)
        out += self.mod.check_ci_claims(wf)
        out += self.mod.check_ci_job_counts(dev, wf)
        out += self.mod.check_workflows_do_not_skip_git(wf)
        return out


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch) -> Sandbox:
    root = tmp_path / "repo"
    root.mkdir()
    mod = _load()
    monkeypatch.setattr(mod, "REPO", root)
    monkeypatch.setattr(mod, "STATUS_YAML", root / "docs" / "project-status.yaml")
    monkeypatch.delenv(mod.SKIP_GIT_ENV, raising=False)
    box = Sandbox(mod, root)

    box.write(".github/workflows/ci.yml", CI_YML)
    for rel in ("ROADMAP.md", "CHANGELOG.md", "viewer/README.md"):
        box.write(rel, "# Doc\n\nNada que contradiga el estado.\n")
    box.write(
        "docs/archivados/02-current-state.md",
        f"# Estado canónico\n\nProducción: `{PROD_TAG}` en el commit `{PROD_COMMIT}`.\n",
    )
    box.write("docs/coordination/risk-register.md", "# Riesgos\n\n| RK-00 | nada |\n")

    # La historia sintética es NO MONÓTONA a propósito: #101 → #105 → #103.
    #
    # La versión anterior era #101 → #102, monótona creciente, y por eso era
    # INCAPAZ de expresar el caso que `_merged_prs` declara load-bearing («en
    # `main` real el #160 se fusionó antes que el #158»): con una historia
    # creciente, ordenar por número y ordenar por fecha dan lo mismo, así que
    # sustituir el orden cronológico por `sorted(reverse=True)` no ponía roja
    # ni una prueba. Aquí el último fusionado es el #103 y el mayor es el
    # #105: C14a/C14b enrojecen si se vuelve al orden numérico.
    _git(root, "init", "--quiet", "-b", "main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    box.write("README.md", "# Repo\n\nBase.\n")
    _git(root, "add", "-A")
    _git(root, "commit", "--quiet", "-m", "base (#101)")
    box.write("README.md", "# Repo\n\nSegundo.\n")
    _git(root, "add", "-A")
    _git(root, "commit", "--quiet", "-m", "carril largo, abierto antes (#105)")
    box.write("README.md", "# Repo\n\nTercero.\n")
    _git(root, "add", "-A")
    _git(root, "commit", "--quiet", "-m", "carril corto, abierto despues (#103)")
    head = _git(root, "rev-parse", "HEAD")
    prev = _git(root, "rev-parse", "HEAD~1")
    _git(root, "update-ref", "refs/remotes/origin/main", head)

    # Un commit REAL que no está en la historia de `main` (para C10).
    _git(root, "checkout", "--quiet", "-b", "lateral", prev)
    box.write("side.txt", "rama lateral\n")
    _git(root, "add", "-A")
    _git(root, "commit", "--quiet", "-m", "lateral (#104)")
    off_main = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "--quiet", "main")

    box.head, box.prev, box.off_main = head, prev, off_main

    box.write(
        "README.md",
        "# Repo\n\n"
        f"> **Desarrollo (`main`, commit `{head[:7]}`, último PR mergeado #103):** "
        "motor V3.\n",
    )
    box.set_status({
        "production": {
            "production_tag": PROD_TAG,
            "commit": PROD_COMMIT,
            "production_release_id": "deploy--00000000-000000",
        },
        "development": {
            "main_commit": head,
            "latest_merged_pr": 103,
            "max_lag_commits": 3,
            "ci_jobs_running": 3,
            "ci_checks_required": 2,
            "ci_running_but_not_required": ["Job C (no exigido)"],
            "completed_programs": [
                {
                    "name": "Carril Z",
                    "state": "CERRADO",
                    "doc_forbids": ["carril z pendiente"],
                },
            ],
        },
    })
    return box


# C0 — baseline: el sandbox tiene que estar VERDE, o ninguna otra fila mide nada.
def test_c0_baseline_verde(sandbox: Sandbox):
    assert sandbox.findings() == []
    assert sandbox.run() == 0


# C1 — un documento atribuye a `main` un SHA falso.
def test_c1_doc_con_sha_falso(sandbox: Sandbox):
    sandbox.write("README.md", "Desarrollo (`main`, commit `1111111`).\n")
    assert any("atribuye a `main`" in f for f in sandbox.findings())
    assert sandbox.run() == 1


# C1b — el patrón RX_MAIN_SHA es DELIBERADAMENTE ESTRECHO: esta redacción, que
# también atribuye un SHA a `main`, NO se detecta. Se prueba para que la
# estrechez conste como decisión medida y no como cobertura imaginada.
@pytest.mark.xfail(reason="RX_MAIN_SHA no cubre esta redacción (estrechez declarada)", strict=True)
def test_c1b_estrechez_declarada_del_patron(sandbox: Sandbox):
    sandbox.write("README.md", "La punta de `main` es hoy 1111111.\n")
    assert any("atribuye a `main`" in f for f in sandbox.findings())


# C2 — un documento cita un último PR falso.
def test_c2_ultimo_pr_falso(sandbox: Sandbox):
    sandbox.write("README.md", "El último PR mergeado #4242 cerró el carril.\n")
    assert any("#4242" in f for f in sandbox.findings())
    assert sandbox.run() == 1


# C3 — frase obsoleta conocida.
def test_c3_frase_obsoleta(sandbox: Sandbox):
    sandbox.write("ROADMAP.md", "El acceso externo usa Basic Auth como autenticación.\n")
    assert any("basic-auth-vigente" in f for f in sandbox.findings())
    assert sandbox.run() == 1


# C4 — un programa CERRADO descrito como pendiente.
def test_c4_programa_cerrado_descrito_pendiente(sandbox: Sandbox):
    sandbox.write("CHANGELOG.md", "Queda el Carril Z pendiente de arrancar.\n")
    assert any("Carril Z" in f for f in sandbox.findings())
    assert sandbox.run() == 1


# C4b — afirmación sobre los DISPARADORES de CI que `ci.yml` desmiente.
# Es el defecto exacto que hizo NO CONFORME a `bf03ca7`: hasta ahora pasaba en
# verde porque el validador no abría un solo workflow.
def test_c4b_afirmacion_falsa_sobre_disparadores_de_ci(sandbox: Sandbox):
    sandbox.write("ROADMAP.md", "Las ramas `test/**` no disparan CI hasta abrir el PR.\n")
    assert any("on.push.branches" in f for f in sandbox.findings())
    assert sandbox.run() == 1


# C4c — la simétrica: si `ci.yml` VUELVE a una lista blanca, la frase «toda
# rama dispara CI» pasa a ser mentira y también enrojece.
#
# La aserción exige que el hallazgo CITE la lista blanca leída. Sin eso, C4c no
# era sensible al fallo del parser: con la clave `on:` de YAML 1.1 rota,
# `_push_branches` devuelve `[]`, `universal` cae a `False` y C4c acertaba por
# el motivo equivocado (sólo C4b enrojecía). Ahora un parser roto produce
# «limita on.push.branches a []» y esta fila se pone roja.
def test_c4c_lista_blanca_contradice_toda_rama(sandbox: Sandbox):
    sandbox.write(".github/workflows/ci.yml", CI_YML.replace("- '**'", "- 'main'\n      - 'feat/**'"))
    sandbox.write("ROADMAP.md", "Desde #160, toda rama dispara CI el día que nace.\n")
    findings = sandbox.findings()
    assert any("limita on.push.branches" in f for f in findings), findings
    assert any("'main', 'feat/**'" in f for f in findings), findings
    assert sandbox.run() == 1


# C4c2 — el parser de `on:` (clave booleana de YAML 1.1) sobre el `ci.yml` REAL.
# Es la premisa de la que dependen C4b y C4c: si deja de leerse, todas las
# afirmaciones sobre disparadores se juzgarían contra una lista vacía.
def test_c4c2_el_parser_lee_los_disparadores_del_ci_real():
    mod = _load()
    ci = mod._load_workflows().get("ci.yml")
    assert ci is not None
    assert mod._push_branches(ci) == ["**"], mod._push_branches(ci)


# C4c3 — la otra dirección de RX_ALL_CI, con redacciones que la versión
# histórica del patrón («toda[s] … rama[s] … dispara») no cubría.
@pytest.mark.parametrize("frase", [
    "Desde #160, toda rama dispara CI el día que nace.",
    "Cada rama dispara CI desde el primer push.",
    "Cualquier rama lanza CI sin lista blanca.",
    "Todas las ramas ejecutan CI.",
    "Hay CI en todas las ramas.",
])
def test_c4c3_lista_blanca_contra_varias_redacciones(sandbox: Sandbox, frase: str):
    sandbox.write(".github/workflows/ci.yml", CI_YML.replace("- '**'", "- 'main'"))
    sandbox.write("ROADMAP.md", frase + "\n")
    assert any("limita on.push.branches" in f for f in sandbox.findings()), frase
    assert sandbox.run() == 1


# C4d — DIEZ redacciones falsas que enrojecen.
#
# Las CINCO primeras son las que el revisor metió en `README.md` el 2026-08-12
# y que pasaron las cinco en verde contra el repo real. (La sexta de su lista,
# «cada rama dispara CI», es CIERTA hoy: marcarla sería un falso positivo, y su
# cobertura es la dirección simétrica, C4c3.) Las dos siguientes son variantes
# de la misma familia. Las TRES últimas venían de C4e y se mueven aquí en la
# segunda revisión: no eran paráfrasis léxicamente abiertas sino idiomas
# cerrados —y «se limita a» es la exclusividad que ya estaba implementada—,
# así que declararlas incobrables era pereza, no honestidad.
@pytest.mark.parametrize("frase", [
    "Las ramas `ops/**` siguen sin disparar CI.",
    "CI no se dispara en ramas `ops/**`.",
    "El push a `test/**` no lanza CI.",
    "CI unicamente corre en `main`.",
    "Solo las ramas de la lista blanca disparan CI.",
    "Las ramas `docs/**` no ejecutan CI.",
    "CI no corre en las ramas de documentacion.",
    "CI queda excluido en las ramas `docs/**`.",
    "CI se limita a `main` y `feat/**`.",
    "Las ramas `test/**` estan fuera del alcance de CI.",
])
def test_c4d_redacciones_negativas_falsas_enrojecen(sandbox: Sandbox, frase: str):
    sandbox.write("ROADMAP.md", frase + "\n")
    assert any("on.push.branches" in f for f in sandbox.findings()), frase
    assert sandbox.run() == 1


# C4e — ESTRECHEZ QUE QUEDA, declarada y no supuesta. CUATRO frases.
#
# `RX_NO_CI` cubre negación explícita («no …»), negación por «sin …»,
# exclusividad («solo/únicamente …», «se limita a») y tres idiomas fijos de
# exclusión («excluido», «fuera del alcance»). Lo que queda fuera NO es
# vocabulario que se pueda enumerar:
#
#   * «el workflow ignora las ramas `ops/**`» — ni siquiera contiene el token
#     «CI»: cazarla exigiría razonar sobre el sujeto de la frase;
#   * «arranca al abrir el PR, nunca en el push» — la negación está desplazada
#     al disparador, no al hecho de correr;
#   * «es invisible para CI» — metáfora, y la familia de metáforas es infinita;
#   * «hay una lista blanca de prefijos de rama» — describe un mecanismo sin
#     negar nada; sólo es falsa por lo que el `ci.yml` dice HOY.
#
# Perseguirlas con regex daría un gate ruidoso, y un gate ruidoso se ignora.
# `strict=True`: el día que se cubra alguna, esta prueba se pondrá roja por
# XPASS y habrá que mover la frase a C4d, como se hizo con las otras tres.
@pytest.mark.xfail(reason="RX_NO_CI no cubre estas cuatro (estrechez declarada, no enumerable)", strict=True)
@pytest.mark.parametrize("frase", [
    "El workflow ignora las ramas `ops/**`.",
    "CI arranca al abrir el PR, nunca en el push a la rama.",
    "Hay una lista blanca de prefijos de rama para CI.",
    "El push a `ops/**` es invisible para CI.",
])
def test_c4e_estrechez_declarada_de_r5(sandbox: Sandbox, frase: str):
    sandbox.write("ROADMAP.md", frase + "\n")
    assert any("on.push.branches" in f for f in sandbox.findings()), frase


# C5 — el documento canónico pierde el commit de producción.
def test_c5_canonico_pierde_commit_de_produccion(sandbox: Sandbox):
    sandbox.write("docs/archivados/02-current-state.md", f"# Estado\n\n`{PROD_TAG}`.\n")
    assert any("no menciona commit=" in f for f in sandbox.findings())
    assert sandbox.run() == 1


# C6 — YAML y documentos mienten a la vez, coherentes entre sí. Es EL caso: la
# coherencia interna es perfecta y aun así el commit no existe en Git.
def test_c6_yaml_y_docs_mienten_coherentemente(sandbox: Sandbox):
    fake = "1" * 40
    sandbox.patch_dev(main_commit=fake, latest_merged_pr=4242)
    sandbox.write(
        "README.md",
        "Desarrollo (`main`, commit `1111111`, último PR mergeado #4242).\n",
    )
    findings = sandbox.findings()
    # Ninguna contradicción INTERNA: la única queja viene de Git.
    assert not any("atribuye a `main`" in f for f in findings), findings
    assert any("NO EXISTE en el repositorio" in f for f in findings), findings
    assert any("latest_merged_pr" in f for f in findings), findings
    assert sandbox.run() == 1


# C7 — `main_commit` real pero desfasado por encima de la ventana declarada.
def test_c7_desfase_por_encima_de_la_ventana(sandbox: Sandbox):
    sandbox.patch_dev(main_commit=sandbox.prev, max_lag_commits=0)
    sandbox.write(
        "README.md",
        f"Desarrollo (`main`, commit `{sandbox.prev[:7]}`, último PR mergeado #103).\n",
    )
    assert any("commits por detras" in f for f in sandbox.findings())
    assert sandbox.run() == 1


# C8 — el mismo desfase de 1 commit con tolerancia 0 enrojece por el PR además
# del commit: el dato del último PR también quedó atrás.
def test_c8_ultimo_pr_desfasado_con_tolerancia_cero(sandbox: Sandbox):
    sandbox.patch_dev(main_commit=sandbox.prev, latest_merged_pr=105, max_lag_commits=0)
    sandbox.write(
        "README.md",
        f"Desarrollo (`main`, commit `{sandbox.prev[:7]}`, último PR mergeado #105).\n",
    )
    assert any("se han fusionado" in f for f in sandbox.findings())
    assert sandbox.run() == 1


# C9 — MISMO desfase, dentro de la tolerancia: verde.
#
# Corrección respecto a la tabla del PR: allí C9 se ejecutó tocando sólo el
# YAML, de modo que el resultado lo decidía la comparación documento↔YAML, no
# la ventana `max_lag_commits` que la fila dice medir. Aquí los documentos se
# mueven CON el YAML, así que el único mecanismo que puede hablar es la
# ventana. `test_c9b` demuestra el otro mecanismo por separado.
def test_c9_desfase_dentro_de_la_ventana_es_verde(sandbox: Sandbox):
    sandbox.patch_dev(main_commit=sandbox.prev, latest_merged_pr=105, max_lag_commits=3)
    sandbox.write(
        "README.md",
        f"Desarrollo (`main`, commit `{sandbox.prev[:7]}`, último PR mergeado #105).\n",
    )
    assert sandbox.findings() == []
    assert sandbox.run() == 0


# C9b — el mecanismo que C9 NO está midiendo: mover sólo el YAML enrojece por
# desacuerdo con el documento, con tolerancia amplia y desfase de 1.
def test_c9b_mover_solo_el_yaml_enrojece_por_otro_motivo(sandbox: Sandbox):
    sandbox.patch_dev(main_commit=sandbox.prev, max_lag_commits=3)
    findings = sandbox.findings()
    assert any("atribuye a `main`" in f for f in findings), findings
    assert not any("commits por detras" in f for f in findings), findings
    assert sandbox.run() == 1


# C10 — commit REAL pero fuera de la historia de `main`.
def test_c10_commit_fuera_de_la_historia_de_main(sandbox: Sandbox):
    sandbox.patch_dev(main_commit=sandbox.off_main)
    sandbox.write(
        "README.md",
        f"Desarrollo (`main`, commit `{sandbox.off_main[:7]}`, último PR mergeado #103).\n",
    )
    assert any("no esta en la historia" in f for f in sandbox.findings())
    assert sandbox.run() == 1


# C11 — sin `main` resoluble: ROJO con motivo, nunca verde silencioso.
def test_c11_sin_main_resoluble_es_rojo(sandbox: Sandbox, monkeypatch):
    monkeypatch.setattr(sandbox.mod, "_resolve_main", lambda: (None, None))
    findings = sandbox.findings()
    assert any("no se ha podido resolver" in f for f in findings), findings
    assert sandbox.run() == 1


# C11b — la válvula manual da rc=0, pero el TITULAR tiene que decir que no se
# ha comprobado contra Git. Antes imprimía «DOCUMENTACION COHERENTE» a secas
# tras un AVISO: quien lee la última línea del log se llevaba la mentira.
def test_c11b_skip_git_lo_dice_en_el_titular(sandbox: Sandbox, monkeypatch, capsys):
    monkeypatch.setenv(sandbox.mod.SKIP_GIT_ENV, "1")
    # La misma mentira coherente de C6, que el punto 0 mataría si estuviera activo.
    sandbox.patch_dev(main_commit="1" * 40, latest_merged_pr=4242)
    sandbox.write(
        "README.md",
        "Desarrollo (`main`, commit `1111111`, último PR mergeado #4242).\n",
    )
    assert sandbox.run() == 0
    out = capsys.readouterr().out
    assert "COHERENTE (SIN VERIFICAR CONTRA GIT)" in out, out


# C12 — `S9_DOCS_SKIP_GIT` en un workflow es un verde ciego automatizado.
def test_c12_skip_git_en_un_workflow_enrojece(sandbox: Sandbox):
    sandbox.write(
        ".github/workflows/ci.yml",
        CI_YML.replace("name: CI\n", "name: CI\nenv:\n  S9_DOCS_SKIP_GIT: '1'\n"),
    )
    assert any("S9_DOCS_SKIP_GIT" in f for f in sandbox.findings())
    assert sandbox.run() == 1


def test_c12b_los_workflows_reales_no_desactivan_el_punto_0():
    """La misma comprobación, sobre los workflows VERSIONADOS de este repo."""
    mod = _load()
    assert mod.check_workflows_do_not_skip_git(mod._load_workflows()) == []


# C13 — los números de RK-20 (14/11) se contrastan contra los workflows.
# Antes vivían en el mismo YAML que este gate exige verificar contra Git y
# nada los miraba: ponerlos a 99/99 daba verde.
def test_c13_numero_de_jobs_inventado_enrojece(sandbox: Sandbox):
    sandbox.patch_dev(ci_jobs_running=99, ci_checks_required=99)
    assert any("ci_jobs_running" in f for f in sandbox.findings())
    assert sandbox.run() == 1


def test_c13b_aritmetica_de_checks_requeridos(sandbox: Sandbox):
    sandbox.patch_dev(ci_checks_required=3)  # 3 jobs - 1 no exigido = 2, no 3
    assert any("ci_checks_required" in f for f in sandbox.findings())
    assert sandbox.run() == 1


def test_c13c_job_no_exigido_que_no_existe(sandbox: Sandbox):
    sandbox.patch_dev(ci_running_but_not_required=["Job Fantasma"], ci_checks_required=2)
    assert any("Job Fantasma" in f for f in sandbox.findings())
    assert sandbox.run() == 1


# C14a — `_merged_prs` devuelve orden CRONOLÓGICO, no numérico.
#
# El comentario de la función declara este caso load-bearing («en `main` real
# el #160 se fusionó antes que el #158») y hasta aquí nada lo ejercía: la
# historia sintética era monótona creciente y sustituir el orden por
# `sorted(prs, reverse=True)` no ponía roja ni una prueba. Con la historia
# #101 → #105 → #103, el último es el #103 y el mayor es el #105.
def test_c14a_merged_prs_es_cronologico_no_numerico(sandbox: Sandbox):
    prs = sandbox.mod._merged_prs("main")
    assert prs == [103, 105, 101], prs
    assert prs != sorted(prs, reverse=True), "la historia sintética no distingue ambos órdenes"


# C14b — el mismo defecto, extremo a extremo: con tolerancia 0, declarar el
# #103 es correcto (es el último fusionado) y el gate está VERDE. Con orden
# numérico el #103 pasaría a ser «1 PR por detrás del #105» y enrojecería:
# un falso rojo que acusaría a una documentación correcta.
def test_c14b_ultimo_pr_no_monotono_con_tolerancia_cero_es_verde(sandbox: Sandbox):
    sandbox.patch_dev(latest_merged_pr=103, max_lag_commits=0)
    assert sandbox.findings() == []
    assert sandbox.run() == 0


# C15a — `_resolve_main` PREFIERE `origin/main` sobre el `main` local, que en un
# worktree puede llevar días parado. Es la única función del punto 0 que no
# tenía prueba: C11 la monkeypatchea entera, así que el rescate del clon
# superficial sólo enrojecía por accidente del entorno.
def test_c15a_resolve_main_prefiere_origin_main(sandbox: Sandbox):
    _git(sandbox.root, "checkout", "--quiet", "--detach", sandbox.head)
    _git(sandbox.root, "branch", "--quiet", "-f", "main", sandbox.prev)
    sha, ref = sandbox.mod._resolve_main()
    assert (sha, ref) == (sandbox.head, "origin/main"), (sha, ref)


# C15b — sin `origin/main`, cae al `main` local y lo DICE en el `ref`.
def test_c15b_resolve_main_cae_al_main_local(sandbox: Sandbox):
    _git(sandbox.root, "update-ref", "-d", "refs/remotes/origin/main")
    sha, ref = sandbox.mod._resolve_main()
    assert (sha, ref) == (sandbox.head, "main"), (sha, ref)


# C15c — sin ninguna de las dos y sin remoto del que traerlas, `_resolve_main`
# devuelve (None, None) y el gate se pone ROJO con motivo. Es C11 sin
# monkeypatch: aquí la función se ejecuta de verdad.
def test_c15c_resolve_main_sin_nada_es_rojo_de_verdad(sandbox: Sandbox):
    _git(sandbox.root, "checkout", "--quiet", "--detach", sandbox.head)
    _git(sandbox.root, "branch", "--quiet", "-D", "main")
    _git(sandbox.root, "update-ref", "-d", "refs/remotes/origin/main")
    assert sandbox.mod._resolve_main() == (None, None)
    assert any("no se ha podido resolver" in f for f in sandbox.findings())
    assert sandbox.run() == 1


# C15d — el RESCATE DEL CLON SUPERFICIAL, que era el único superviviente de la
# primera revisión: borrar entero el bloque `--unshallow` + `fetch` de
# `_resolve_main` no ponía roja ni una fila. Es el código que puso rojo el
# primer CI de este PR, y hasta aquí sólo lo «cubría» un accidente del entorno
# (`Deployment scripts validation` hace checkout superficial), no la tabla.
#
# El clon es de verdad superficial (`--depth 1` sobre `file://`) y se le
# quitan `origin/main` y `main`: exactamente lo que ve CI con `fetch-depth: 1`.
# La única salida es traerlo del remoto. Que no se degrade a verde ya lo dice
# C15c; esta fila dice que el rescate FUNCIONA.
def test_c15d_rescate_del_clon_superficial(sandbox: Sandbox, tmp_path: Path, monkeypatch):
    clone = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "--quiet", "--depth", "1", "--branch", "main",
         f"file://{sandbox.root}", str(clone)],
        check=True, capture_output=True,
    )
    assert _git(clone, "rev-parse", "--is-shallow-repository") == "true"
    _git(clone, "checkout", "--quiet", "--detach", "HEAD")
    _git(clone, "branch", "--quiet", "-D", "main")
    _git(clone, "update-ref", "-d", "refs/remotes/origin/main")

    monkeypatch.setattr(sandbox.mod, "REPO", clone)
    # Punto de partida: `main` NO es resoluble con lo que hay en el clon.
    assert sandbox.mod._try_local_main() == (None, None)
    # …y aun así `_resolve_main` lo recupera, sin degradarse a verde.
    sha, ref = sandbox.mod._resolve_main()
    assert sha == sandbox.head, (sha, ref)
    assert ref is not None


# C16 — `development.main_commit` debe ser un SHA COMPLETO de 40 hex. Un SHA
# abreviado es ambiguo (colisiona antes) y hace indistinguibles dos commits;
# hasta aquí, quitar esa exigencia del validador no ponía roja ninguna fila.
def test_c16_main_commit_abreviado_enrojece(sandbox: Sandbox):
    short = sandbox.head[:7]
    sandbox.patch_dev(main_commit=short)
    sandbox.write(
        "README.md",
        f"Desarrollo (`main`, commit `{short}`, último PR mergeado #103).\n",
    )
    findings = sandbox.findings()
    # El commit EXISTE y está en `main`: la única queja es la longitud.
    assert any("no es un SHA completo de 40 hex" in f for f in findings), findings
    assert not any("NO EXISTE" in f or "no esta en la historia" in f for f in findings), findings
    assert sandbox.run() == 1


# FIN — revertido todo, el sandbox vuelve a verde (la reversión de la
# calibración, no una repetición de C0: se rompe y se deshace en la misma
# prueba).
def test_fin_romper_y_revertir_vuelve_a_verde(sandbox: Sandbox):
    original = sandbox.read("README.md")
    sandbox.write("README.md", "Desarrollo (`main`, commit `1111111`).\n")
    assert sandbox.run() == 1
    sandbox.write("README.md", original)
    assert sandbox.run() == 0
