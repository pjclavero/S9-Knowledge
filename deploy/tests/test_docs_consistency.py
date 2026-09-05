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
import json
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
        out += self.mod.check_ci_verified(dev)
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


# C4f — FALSOS POSITIVOS: prosa legítima que NO debe morder.
#
# «Ruido cero» estaba mal medido: comprobar que el texto de HOY sigue verde es
# suficiencia, no ausencia de falsos positivos. En la tercera revisión, cuatro
# de estas ocho frases enrojecían, porque las alternativas de la familia (e) no
# exigían que el objeto fueran RAMAS. La primera es literalmente la tesis de
# `RK-20b` escrita en prosa, y la cuarta es un descargo de alcance
# frecuentísimo en `CHANGELOG.md` y `ROADMAP.md`, que están en `DOCS`: el gate
# mordía nuestro propio texto correcto, y un gate así se acaba desactivando.
#
# Ahora la familia (e) está anclada a `_BRANCH`. R5 sólo puede juzgar QUÉ RAMAS
# disparan CI, que es lo único que `on.push.branches` dice; cualquier otra
# afirmación sobre CI cae fuera de su competencia y debe pasar en verde.
@pytest.mark.parametrize("frase", [
    "CI se limita a informar: no bloquea el merge.",
    "El job de CI se limita a 20 minutos de ejecucion.",
    "CI se limita a 14 jobs por PR.",
    "Ese refactor queda fuera del alcance de este PR; CI no cambia.",
    "El alcance de CI se revisa cada trimestre.",
    "La cobertura queda fuera del alcance de este bloque.",
    "CI excluye los ficheros generados del recuento.",
    "Este PR se limita a documentacion.",
])
def test_c4f_prosa_legitima_no_enrojece(sandbox: Sandbox, frase: str):
    sandbox.write("ROADMAP.md", frase + "\n")
    assert sandbox.findings() == [], frase
    assert sandbox.run() == 0


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


# C7 — DESFASE POR ENCIMA DEL UMBRAL: AVISO, NO ERROR. (Rediseño 2026-08-13.)
#
# Antes esto era rojo, y por eso la puerta se AUTO-INVALIDABA en cada merge:
# con PRs de 10+ commits el refresco caducaba en el momento de fusionarse, y
# `main` pasó casi toda la sesión del 2026-08-13 en rojo bloqueando a la vez
# todas las ramas abiertas. `main_commit` documenta el commit SOBRE EL QUE SE
# MIDIERON las cifras: envejecer no lo vuelve falso. Que se hayan fusionado
# commits detrás no demuestra ninguna contradicción, sólo demuestra que hubo
# merges. Lo que sí sería falso —SHA inexistente, no-ancestro, PR ausente,
# cifras que no cuadran— sigue en rojo, y lo prueba C21c.
def test_c7_desfase_por_encima_del_umbral_es_aviso_no_error(sandbox: Sandbox, capsys):
    sandbox.patch_dev(main_commit=sandbox.prev, max_lag_commits=0)
    sandbox.write(
        "README.md",
        f"Desarrollo (`main`, commit `{sandbox.prev[:7]}`, último PR mergeado #103).\n",
    )
    assert sandbox.findings() == []
    assert sandbox.run() == 0
    out = capsys.readouterr().out
    # El desfase no desaparece: se anuncia, y además califica el titular.
    assert "AVISO" in out and "commits por detras" in out, out
    assert "COHERENTE (DESFASADA" in out, out


# C8 — el mismo reloj para el PR declarado: que hayan entrado PR después no lo
# vuelve falso. Que ESTÉ en la historia sí es un hecho, y sigue en rojo (C6).
def test_c8_ultimo_pr_desfasado_es_aviso_no_error(sandbox: Sandbox, capsys):
    sandbox.patch_dev(main_commit=sandbox.prev, latest_merged_pr=105, max_lag_commits=0)
    sandbox.write(
        "README.md",
        f"Desarrollo (`main`, commit `{sandbox.prev[:7]}`, último PR mergeado #105).\n",
    )
    assert sandbox.findings() == []
    assert sandbox.run() == 0
    out = capsys.readouterr().out
    assert "se han fusionado" in out, out
    assert "PR fusionados despues del declarado" in out, out


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
#
# El bloque tiene TRES líneas y cada una tiene ahora su fila, porque cubrirlo
# «como un todo» enmascaraba su redundancia: `--unshallow` aquí (por la
# ancestría de abajo), el `fetch` normal en C15f y `FETCH_HEAD` en C15e.
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

    # Y AHORA LO QUE DE VERDAD ATA `--unshallow` A SU RAZÓN DE SER.
    #
    # Recuperar el SHA no exige `--unshallow`: en un clon superficial el
    # `fetch` normal ya trae `origin/main`, así que hasta aquí esta fila
    # pasaba por un mecanismo DISTINTO del que anunciaba —la misma forma del
    # defecto que hubo que corregir en C9—. `--unshallow` existe para que el
    # punto 0 pueda calcular **ancestría** (`merge-base --is-ancestor`) y
    # **desfase** (`rev-list --count`), que es justo lo que una historia
    # truncada a un commit no permite. Con la historia completa, el commit
    # anterior EXISTE y ambas preguntas se pueden responder.
    assert sandbox.mod._git_rc("merge-base", "--is-ancestor", sandbox.prev, sha) == 0
    assert sandbox.mod._git("rev-list", "--count", f"{sandbox.prev}..{sha}") == "1"
    assert _git(clone, "rev-parse", "--is-shallow-repository") == "false"


# C15e — la salida por `FETCH_HEAD`, que C15d NO ejerce.
#
# En C15d el `fetch` actualiza oportunistamente `refs/remotes/origin/main`
# porque el clon tiene el refspec por defecto, así que `_try_local_main`
# vuelve a encontrarlo y la rama de `FETCH_HEAD` queda muerta. `actions/checkout`
# configura un refspec RESTRINGIDO: ahí el fetch explícito deja el resultado
# sólo en `FETCH_HEAD`, y esa rama es la única salida. Se reproduce quitando
# `remote.origin.fetch`.
def test_c15e_salida_por_fetch_head(sandbox: Sandbox, tmp_path: Path, monkeypatch):
    clone = tmp_path / "norefspec"
    subprocess.run(
        ["git", "clone", "--quiet", "--depth", "1", "--branch", "main",
         f"file://{sandbox.root}", str(clone)],
        check=True, capture_output=True,
    )
    _git(clone, "checkout", "--quiet", "--detach", "HEAD")
    _git(clone, "branch", "--quiet", "-D", "main")
    _git(clone, "update-ref", "-d", "refs/remotes/origin/main")
    _git(clone, "config", "--unset", "remote.origin.fetch")

    monkeypatch.setattr(sandbox.mod, "REPO", clone)
    assert sandbox.mod._try_local_main() == (None, None)
    sha, ref = sandbox.mod._resolve_main()
    assert sha == sandbox.head, (sha, ref)
    assert "FETCH_HEAD" in str(ref), ref


# C15f — el `fetch` NORMAL, que ni C15d ni C15e ejercen.
#
# En un clon superficial, `fetch --unshallow origin main` ya trae la rama, así
# que el `fetch` de después es redundante y borrarlo no ponía roja ninguna
# fila. Su caso propio es el clon COMPLETO al que le faltan las dos
# referencias: ahí la rama de `--unshallow` ni se entra (`is-shallow` es
# `false`) y el `fetch` normal es la única salida.
def test_c15f_fetch_normal_en_clon_completo(sandbox: Sandbox, tmp_path: Path, monkeypatch):
    clone = tmp_path / "completo"
    subprocess.run(
        ["git", "clone", "--quiet", "--branch", "main", f"file://{sandbox.root}", str(clone)],
        check=True, capture_output=True,
    )
    assert _git(clone, "rev-parse", "--is-shallow-repository") == "false"
    _git(clone, "checkout", "--quiet", "--detach", "HEAD")
    _git(clone, "branch", "--quiet", "-D", "main")
    _git(clone, "update-ref", "-d", "refs/remotes/origin/main")

    monkeypatch.setattr(sandbox.mod, "REPO", clone)
    assert sandbox.mod._try_local_main() == (None, None)
    sha, ref = sandbox.mod._resolve_main()
    assert sha == sandbox.head, (sha, ref)


# --- C17: el clon superficial TAL COMO ES EN CI ---------------------------
#
# C15d/C15e/C15f tenían un aprobado fácil que sólo se vio cuando `main` se
# puso rojo el 2026-08-12: las tres parten de que `main` NO es resoluble, y
# por eso el rescate se ejecuta. En CI REAL eso es FALSO. `actions/checkout`
# con `fetch-depth: 1` deja creados `main` **y** `origin/main`, así que
# `_try_local_main` acierta a la primera, `_resolve_main` vuelve antes de
# llegar al `--unshallow` y el punto 0 se ejecuta sobre UN commit de historia.
# Consecuencia medida en `main@0dfa788`: el gate acusó a `main_commit` de «NO
# EXISTE en el repositorio» siendo un ancestro perfectamente real.
#
# Estas dos filas ejercen esa forma —la de verdad— y no la que convenía.
def _clon_estilo_ci(sandbox: Sandbox, dest: Path) -> Path:
    """Clon superficial CON `main` y `origin/main`, como lo deja checkout."""
    subprocess.run(
        ["git", "clone", "--quiet", "--depth", "1", "--branch", "main",
         f"file://{sandbox.root}", str(dest)],
        check=True, capture_output=True,
    )
    assert _git(dest, "rev-parse", "--is-shallow-repository") == "true"
    assert _git(dest, "rev-list", "--count", "HEAD") == "1"
    return dest


# C17a — con la historia truncada pero completable, el gate NO acusa en falso:
# profundiza y responde lo correcto sobre un ancestro real.
def test_c17a_clon_superficial_de_ci_no_acusa_en_falso(sandbox: Sandbox, tmp_path: Path, monkeypatch):
    clone = _clon_estilo_ci(sandbox, tmp_path / "ci")
    monkeypatch.setattr(sandbox.mod, "REPO", clone)
    # La premisa que C15d/e/f NO cumplen: aquí `main` SÍ se resuelve solo.
    assert sandbox.mod._try_local_main()[0] == sandbox.head
    # `prev` es un ancestro REAL, invisible con un commit de historia.
    assert sandbox.mod._git("rev-parse", "--verify", "--quiet",
                            f"{sandbox.prev}^{{commit}}") is None

    findings = sandbox.mod.check_git_authority(
        {"main_commit": sandbox.prev, "latest_merged_pr": 105, "max_lag_commits": 3}
    )
    assert findings == [], findings
    assert _git(clone, "rev-parse", "--is-shallow-repository") == "false"


# C17b — si la historia NO se puede completar, sigue siendo ROJO (fail-closed)
# pero con el diagnóstico VERDADERO: «no se ha podido comprobar», nunca «no
# existe». Acusar de mentir a un documento correcto quema el gate.
def test_c17b_sin_poder_completar_dice_la_verdad(sandbox: Sandbox, tmp_path: Path, monkeypatch):
    clone = _clon_estilo_ci(sandbox, tmp_path / "ci2")
    _git(clone, "remote", "remove", "origin")  # ya no hay de dónde traer nada
    monkeypatch.setattr(sandbox.mod, "REPO", clone)

    findings = sandbox.mod.check_git_authority(
        {"main_commit": sandbox.prev, "latest_merged_pr": 105, "max_lag_commits": 3}
    )
    assert any("NO SE HA PODIDO COMPROBAR" in f for f in findings), findings
    assert not any("NO EXISTE" in f for f in findings), findings
    # Y ni una queja sobre la ventana de PR, que sobre un commit de historia
    # sólo puede decir tonterías.
    assert not any("ultimos PR fusionados" in f for f in findings), findings


# C18 — `_merged_prs` se lee del SHA RESUELTO, no del nombre simbólico.
#
# El arreglo existía sin prueba: revertirlo dejaba 0 filas rojas, porque en el
# sandbox `origin/main` y el SHA resuelto nunca divergen. Es la misma familia
# que el orden de `_merged_prs` en la primera revisión — un arreglo que no
# puede ponerse rojo no es un hallazgo, es una opinión.
#
# Aquí divergen de verdad, y por el mecanismo real: `_resolve_main` fija el
# SHA, y el `fetch --unshallow` del rescate MUEVE `refs/remotes/origin/main`
# bajo los pies (el remoto ha avanzado por otra rama mientras tanto). Leer del
# nombre simbólico después de eso responde sobre OTRA historia.
def test_c18_merged_prs_no_se_lee_del_nombre_simbolico(sandbox: Sandbox, tmp_path: Path, monkeypatch):
    clone = _clon_estilo_ci(sandbox, tmp_path / "movida")
    # El remoto avanza por otra línea DESPUÉS de que el clon fijara su ref.
    _git(sandbox.root, "checkout", "--quiet", "--detach", sandbox.head)
    _git(sandbox.root, "branch", "--quiet", "-f", "main", sandbox.off_main)

    monkeypatch.setattr(sandbox.mod, "REPO", clone)
    findings = sandbox.mod.check_git_authority(
        {"main_commit": sandbox.head, "latest_merged_pr": 103, "max_lag_commits": 3}
    )
    # La ref simbólica ha cambiado bajo los pies…
    assert _git(clone, "rev-parse", "origin/main") == sandbox.off_main
    # …y aun así el veredicto habla del commit que se resolvió y se validó.
    assert findings == [], findings


# C19a — HISTORIA TRUNCADA: un valor DECLARADO que no se ha podido comprobar se
# dice en ROJO, no se asume.
#
# La fuga medida el 2026-08-13: con la punta como `main_commit`, la existencia
# y la ancestría son triviales, la ventana de PR se saltaba en silencio, y un
# `latest_merged_pr` INVENTADO pasaba en VERDE. El mismo defecto que ya se
# había corregido para `S9_DOCS_SKIP_GIT`, reapareciendo por otra puerta.
def test_c19a_pr_declarado_sin_poder_comprobarse_es_rojo(sandbox: Sandbox, tmp_path: Path, monkeypatch):
    clone = _clon_estilo_ci(sandbox, tmp_path / "trunc")
    _git(clone, "remote", "remove", "origin")
    monkeypatch.setattr(sandbox.mod, "REPO", clone)

    findings = sandbox.mod.check_git_authority(
        {"main_commit": sandbox.head, "latest_merged_pr": 4242, "max_lag_commits": 3}
    )
    assert any("#4242" in f and "NO SE HA PODIDO COMPROBAR" in f for f in findings), findings


# C19b — y si no hay nada declarado que comprobar, el rc puede ser 0, pero EL
# TITULAR tiene que decir que la historia estaba truncada. Quien lee la última
# línea de un log no puede llevarse un «COHERENTE» a secas.
def test_c19b_el_titular_dice_que_la_historia_estaba_truncada(
    sandbox: Sandbox, tmp_path: Path, monkeypatch, capsys,
):
    clone = _clon_estilo_ci(sandbox, tmp_path / "trunc2")
    _git(clone, "remote", "remove", "origin")
    # El árbol de trabajo del sandbox (documentos y YAML) sobre el clon.
    for src in sandbox.root.rglob("*"):
        if ".git/" in str(src) or not src.is_file():
            continue
        dst = clone / src.relative_to(sandbox.root)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())

    data = sandbox.status()
    data["development"]["main_commit"] = sandbox.head
    data["development"].pop("latest_merged_pr")  # nada declarado que comprobar
    (clone / "docs/project-status.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    (clone / "README.md").write_text(f"# Repo\n\n`main` va por `{sandbox.head[:7]}`.\n",
                                     encoding="utf-8")

    monkeypatch.setattr(sandbox.mod, "REPO", clone)
    monkeypatch.setattr(sandbox.mod, "STATUS_YAML", clone / "docs/project-status.yaml")
    assert sandbox.mod.main() == 0
    out = capsys.readouterr().out
    assert "COHERENTE (HISTORIA TRUNCADA)" in out, out


# C20 — `latest_ci` SÍ se valida, y contra la propiedad REAL.
#
# Hasta este carril era el único campo del bloque `development` que no miraba
# nadie: declarar `latest_ci: "green"` sobre un commit con la CI en rojo pasaba
# en verde, y se dejó escrito como limitación con `xfail(strict=True)`. El
# oráculo sigue estando FUERA (el estado de CI de un commit vive en GitHub),
# así que no se finge cobertura ni se mete una llamada de red obligatoria: se
# INYECTA por `S9K_CI_ORACLE`, y su ausencia se declara en el titular.
#
# Y lo que se comprueba es la semántica verdadera: `latest_ci` es la CI de
# `development.main_commit` —el commit YA VERIFICADO desde el que se tomó la
# fotografía—, NO la del commit que contiene el YAML, que es imposible por
# construcción. Estas cuatro filas fijan las dos direcciones.


def _oraculo(tmp_path: Path, mapa: dict, monkeypatch, mod) -> None:
    ruta = tmp_path / "ci-oraculo.json"
    ruta.write_text(json.dumps(mapa), encoding="utf-8")
    monkeypatch.setenv(mod.CI_ORACLE_ENV, str(ruta))


# C20a — CONTROL POSITIVO: con oráculo, `latest_ci` mentiroso es ROJO.
def test_c20a_latest_ci_mentiroso_es_rojo(sandbox: Sandbox, tmp_path: Path, monkeypatch):
    _oraculo(tmp_path, {sandbox.head: "red"}, monkeypatch, sandbox.mod)
    sandbox.patch_dev(latest_ci="green")  # sobre un commit cuya CI está roja
    findings = sandbox.findings()
    assert any("latest_ci" in f and "green" in f and "red" in f for f in findings), findings


# C20b — …y con el oráculo diciendo lo mismo que el YAML, VERDE. Sin esta fila
# la anterior no demuestra nada: un gate que siempre enrojece tampoco mide.
def test_c20b_latest_ci_veraz_queda_verde(sandbox: Sandbox, tmp_path: Path, monkeypatch):
    _oraculo(tmp_path, {sandbox.head: "success"}, monkeypatch, sandbox.mod)
    sandbox.patch_dev(latest_ci="green")
    assert sandbox.findings() == [], sandbox.findings()


# C20c — FAIL-CLOSED: si el oráculo no conoce `main_commit`, el valor
# declarado NO se ha podido comprobar, y eso se dice en ROJO (misma doctrina
# que C19a con la historia truncada), no se asume.
def test_c20c_oraculo_que_no_conoce_el_commit_es_rojo(
    sandbox: Sandbox, tmp_path: Path, monkeypatch,
):
    _oraculo(tmp_path, {"0" * 40: "green"}, monkeypatch, sandbox.mod)
    sandbox.patch_dev(latest_ci="green")
    findings = sandbox.findings()
    assert any("latest_ci" in f and "NO SE HA PODIDO COMPROBAR" in f for f in findings), findings


# C20d — sin oráculo el rc puede ser 0, pero EL TITULAR tiene que decir que la
# CI no se ha verificado. Un «COHERENTE» a secas sobre un campo no comprobado
# es la fuga que este script ya cerró dos veces por otras puertas.
def test_c20d_sin_oraculo_el_titular_lo_declara(sandbox: Sandbox, monkeypatch, capsys):
    monkeypatch.delenv(sandbox.mod.CI_ORACLE_ENV, raising=False)
    sandbox.patch_dev(latest_ci="green")
    assert sandbox.run() == 0
    out = capsys.readouterr().out
    assert "COHERENTE (CI NO VERIFICADA)" in out, out
    assert "COHERENTE: sin contradicciones" not in out, out


# --- C21: envejecer NO es mentir, pero mentir sigue siendo rojo -----------
#
# El rediseño del 2026-08-13 sólo vale si la línea entre HECHO y RELOJ está
# donde se dice. Estas tres filas la fijan en el MISMO escenario desfasado, que
# es la única forma de demostrar que lo que cambió fue el criterio y no la
# capacidad de detectar.

# C21a — el escenario LEGÍTIMO de hoy: un merge grande deja el bloque muy por
# detrás y no hay ninguna contradicción. VERDE. Esto es lo que ponía `main` en
# rojo y bloqueaba a todos los carriles a la vez.
def test_c21a_merge_normal_grande_queda_verde(sandbox: Sandbox):
    # Diez merges detrás del commit documentado, umbral 3.
    for i in range(10):
        sandbox.write("relleno.txt", f"commit {i}\n")
        _git(sandbox.root, "add", "relleno.txt")
        _git(sandbox.root, "commit", "--quiet", "-m", f"trabajo de otro carril (#{200 + i})")
    nuevo = _git(sandbox.root, "rev-parse", "HEAD")
    _git(sandbox.root, "update-ref", "refs/remotes/origin/main", nuevo)

    lag = _git(sandbox.root, "rev-list", "--count", f"{sandbox.head}..{nuevo}")
    assert lag == "10", lag
    assert sandbox.findings() == [], sandbox.findings()
    assert sandbox.run() == 0


# C21b — …y ese verde NO es mudo: el titular lo dice. Un desfase que sólo
# aparece a media página no lo lee nadie; en la última línea, sí. (Es la misma
# doctrina que ya obligó a calificar `S9_DOCS_SKIP_GIT` y la historia truncada.)
def test_c21b_el_titular_declara_el_desfase(sandbox: Sandbox, capsys):
    sandbox.patch_dev(max_lag_commits=0, latest_merged_pr=101)
    sandbox.write(
        "README.md",
        f"Desarrollo (`main`, commit `{sandbox.head[:7]}`, último PR mergeado #101).\n",
    )
    assert sandbox.run() == 0
    out = capsys.readouterr().out
    assert "COHERENTE (DESFASADA" in out, out
    assert "COHERENTE: sin contradicciones" not in out, out


# C21c — MISMO desfase, pero mintiendo: sigue ROJO, una fila por contradicción.
# Ninguna de estas la salva el rediseño.
@pytest.mark.parametrize("caso,parche,esperado", [
    ("SHA inexistente", {"main_commit": "1" * 40}, "NO EXISTE"),
    ("SHA fuera de la historia de main", {"main_commit": "OFF_MAIN"}, "no esta en la historia"),
    ("SHA abreviado", {"main_commit": "SHORT"}, "40 hex"),
    ("PR que no esta en la historia", {"latest_merged_pr": 4242}, "no aparece entre"),
    ("contador de jobs inventado", {"ci_jobs_running": 99}, "ci_jobs_running"),
    ("aritmetica de checks requeridos", {"ci_checks_required": 3}, "ci_checks_required"),
])
def test_c21c_con_el_mismo_desfase_la_mentira_sigue_roja(sandbox: Sandbox, caso, parche, esperado):
    parche = dict(parche)
    if parche.get("main_commit") == "OFF_MAIN":
        parche["main_commit"] = sandbox.off_main
    if parche.get("main_commit") == "SHORT":
        parche["main_commit"] = sandbox.head[:7]
    # Umbral 0: el bloque está desfasado y aun así el veredicto lo decide la
    # contradicción, no el reloj.
    sandbox.patch_dev(max_lag_commits=0, **parche)
    findings = sandbox.findings()
    assert any(esperado in f for f in findings), (caso, findings)
    assert sandbox.run() == 1, caso


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
