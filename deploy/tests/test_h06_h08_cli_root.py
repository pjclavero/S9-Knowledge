# -*- coding: utf-8 -*-
"""H-06 + H-08 ronda 2 · H-1 — NINGUNA CLI ni escritor crea estado como root.

EL DEFECTO (revisión independiente, P1)
---------------------------------------
Solo la CLI de auth rechazaba a root. ``python -m app.cli.health check`` como root
dejaba ``health/health.json root:root``; ``glossary_cli.py stats`` como root creaba
``glossary/`` 0755 y ``glossary.db`` 0644 de root; ``cli/jobs.py`` con la base ausente
creaba ``jobs.db`` de root; y aun por ``runuser`` el ``GlossaryStore`` y los
directorios intermedios nacían con la umask (0755/0644). Cualquiera de ellos deja al
servicio sin arrancar (la comprobación de arranque es fail-closed).

LA GARANTÍA
-----------
1. UNA guarda canónica en la autoridad (``service_state.reject_root_cli`` /
   ``cli_root_rejection``): rc ESTABLE 4 + comando canónico
   (``deploy/scripts/s9k-cli.sh <herramienta>``), ANTES de tocar nada.
2. GATE ESTRUCTURAL: toda entrada ``__main__`` de ``viewer/app`` y ``data-engine/app``
   cuyo CIERRE ESTÁTICO de importaciones llega a un escritor de clase STATE (la tabla
   ``INVENTARIO`` de ``test_h06_h08_inventario_escrituras.py``) llama a la guarda, o
   está declarada aquí con su razón. Cada ``__main__`` de ``deploy/scripts`` está
   clasificado (instalador root por diseño). Una CLI nueva sin guarda pone esto rojo.
3. Puntos de estrangulamiento en los escritores (``refuse_root_state_write``): root
   no crea ni abre estado bajo el state root aunque entre por otra puerta.
4. Modos de la autoridad, no de la umask (``ensure_private_dir``/``create_private_file``).

TECHO DECLARADO
---------------
El cierre es ESTÁTICO (``import``/``from``): no sigue ``importlib`` por ruta, ni
``subprocess``, ni reflexión. La guarda se exige por PRESENCIA de la llamada en el
módulo; el ORDEN (antes de tocar nada) lo prueban los tests por efecto de abajo,
uno por CLI: root -> rc 4 y NADA creado. Root real (no simulado) va a VM112
(escenario F).
"""
from __future__ import annotations

import ast
import importlib.util
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
VIEWER_APP = RAIZ / "viewer" / "app"
MOTOR_APP = RAIZ / "data-engine" / "app"
SCRIPTS = RAIZ / "deploy" / "scripts"
EUID = os.geteuid()

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_h06_h08_inventario_escrituras as inv  # noqa: E402


def _cargar_ss():
    nombre = "_s9k_service_state"
    if nombre in sys.modules:
        return sys.modules[nombre]
    spec = importlib.util.spec_from_file_location(nombre, MOTOR_APP / "knowledge_v3" / "service_state.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = m
    spec.loader.exec_module(m)
    return m


ss = _cargar_ss()

#: Entradas ``__main__`` que llegan a un escritor STATE y NO usan la guarda de CLI, con
#: la razón. Añadir aquí exige una razón; quitar una guarda sin declararla pone rojo.
SIN_GUARDA_DECLARADA = {
    "data-engine/app/jobs/worker.py": "SERVICIO, no CLI: enforce('worker') rechaza root (rc 3) "
                                      "antes de abrir la cola; y job_store._connect rechaza root "
                                      "bajo el state root",
}
#: Los ``__main__`` de deploy/scripts son INSTALADORES: corren como root por diseño (los
#: invoca deploy.sh). Lo que crean lo crean con chown explícito o lo corrige la migración.
INSTALADORES = {
    "deploy/scripts/detect_state.py": "solo lectura (mode=ro)",
    "deploy/scripts/estado_instalacion.py": "registro en <state>/deploy (subárbol del instalador, root:root)",
    "deploy/scripts/migrar_estado.py": "la migración: chown/chmod a la identidad de la autoridad",
    "deploy/scripts/migrate_sqlite.py": "paso 4 (antes del 5b, que corrige propietario y modos)",
    "deploy/scripts/preflight_ensayo_rc.py": "preflight de solo lectura",
    "deploy/scripts/preflight_https.py": "red, no estado",
    "deploy/scripts/preflight_setup_admin.py": "petición HTTP al visor; registro en <state>/deploy",
    "deploy/scripts/retention.py": "releases (RELEASE), no estado",
    "deploy/scripts/review_store.py": "crea review.sqlite3 con chown/chmod explícitos de la autoridad (C1)",
    "deploy/scripts/schema_versions.py": "lee versiones de esquema del código",
    "deploy/scripts/verify_release_identity.py": "lee /proc y el manifiesto",
}
#: La autoridad: su ``__main__`` lo usa root (get/check/paths) y el servicio (access/deny).
AUTORIDAD = "data-engine/app/knowledge_v3/service_state.py"
GUARDAS = {"reject_root_cli", "cli_root_rejection"}


def _rel(p: Path) -> str:
    return p.relative_to(RAIZ).as_posix()


def _tiene_main(arbol: ast.AST) -> bool:
    for n in ast.walk(arbol):
        if isinstance(n, ast.If) and isinstance(n.test, ast.Compare):
            t = ast.unparse(n.test)
            if "__name__" in t and "__main__" in t:
                return True
    return False


def _mains():
    out = []
    for base in (VIEWER_APP, MOTOR_APP, SCRIPTS):
        for f in sorted(base.rglob("*.py")):
            rel = _rel(f)
            if "/tests/" in rel or f.name.startswith("test_") or f.name == "conftest.py" or ".bak" in rel:
                continue
            try:
                arbol = ast.parse(f.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            if _tiene_main(arbol):
                out.append(f)
    return out


def _cierre(inicio: Path, app: Path = None) -> set:
    """Módulos del repo alcanzables por importación ESTÁTICA desde ``inicio`` (rutas
    relativas a la raíz; ``app`` = el paquete contra el que se resuelven los imports)."""
    if app is None:
        app = VIEWER_APP if _rel(inicio).startswith("viewer/") else MOTOR_APP

    def resolver(nombre: str):
        partes = nombre.split(".")
        if app == VIEWER_APP:
            if partes[0] != "app":
                return None
            partes = partes[1:]
        for k in range(len(partes), 0, -1):
            b = app.joinpath(*partes[:k])
            if b.with_suffix(".py").is_file():
                return b.with_suffix(".py")
            if (b / "__init__.py").is_file():
                return b / "__init__.py"
        return None

    vistos, pila = set(), [inicio]
    while pila:
        f = pila.pop()
        if f in vistos:
            continue
        vistos.add(f)
        try:
            arbol = ast.parse(f.read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        for n in ast.walk(arbol):
            nombres = []
            if isinstance(n, ast.Import):
                nombres = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                if n.level == 0 and n.module:
                    nombres = [n.module] + ["%s.%s" % (n.module, a.name) for a in n.names]
                elif n.level > 0:
                    try:
                        pkg = list(f.parent.relative_to(app).parts)
                    except ValueError:
                        continue
                    base = pkg[: len(pkg) - (n.level - 1)]
                    mod = base + (n.module.split(".") if n.module else [])
                    if app == VIEWER_APP:
                        mod = ["app"] + mod
                    nombres = [".".join(mod)] + [".".join(mod + [a.name]) for a in n.names]
            for nm in nombres:
                r = resolver(nm)
                if r is not None and r not in vistos:
                    pila.append(r)
    return {_rel(x) for x in vistos if RAIZ in x.parents}


def _escritores_state() -> set:
    return {r for r, (_t, clase, _g) in inv.INVENTARIO.items() if clase == "STATE"} - {AUTORIDAD}


def _llama_a_la_guarda(f: Path) -> set:
    """Nombres de herramienta pasados a la guarda (literal) en ``f``; set() si no la llama."""
    nombres = set()
    for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Call):
            fn = n.func
            nom = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else None)
            if nom in GUARDAS:
                if n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                    nombres.add(n.args[0].value)
                else:
                    nombres.add("?")
    return nombres


def clis_de_estado() -> dict:
    """{cli: escritores STATE que alcanza} para cada ``__main__`` de viewer/motor."""
    escritores = _escritores_state()
    out = {}
    for f in _mains():
        rel = _rel(f)
        if rel.startswith("deploy/") or rel == AUTORIDAD:
            continue
        toca = _cierre(f) & escritores
        if toca:
            out[rel] = toca
    return out


# ---------------------------------------------------------------------------
# 1. GATE ESTRUCTURAL
# ---------------------------------------------------------------------------

def test_el_detector_no_esta_roto():
    """DETECTOR ROTO si el gate no ve lo que sabemos que existe."""
    clis = clis_de_estado()
    for conocida in ("viewer/app/cli/auth.py", "viewer/app/cli/health.py", "data-engine/app/cli/jobs.py",
                     "data-engine/app/glossary/glossary_cli.py", "data-engine/app/cli/external_ai.py"):
        assert conocida in clis, "DETECTOR ROTO: %s no se ve como CLI de estado (%s)" % (conocida, sorted(clis))
    assert len(clis) >= 12, sorted(clis)
    assert len(_mains()) >= 40


def test_toda_cli_que_alcanza_estado_llama_a_la_guarda_canonica():
    sin_guarda = []
    for cli, toca in sorted(clis_de_estado().items()):
        if cli in SIN_GUARDA_DECLARADA:
            continue
        if not _llama_a_la_guarda(RAIZ / cli):
            sin_guarda.append("%s (alcanza %s)" % (cli, sorted(toca)[:3]))
    assert not sin_guarda, (
        "CLI SIN GUARDA DE ROOT: estas entradas pueden crear/abrir estado del servicio y no "
        "llaman a service_state.reject_root_cli('<herramienta>') (rc 4 + comando canónico) "
        "antes de tocar nada; como root dejarían ficheros root:root en el estado vivo. "
        "Añádela (y la herramienta a s9k_cli_destino de lib.sh) o decláralo en "
        "SIN_GUARDA_DECLARADA con su razón: %s" % sin_guarda)


def test_las_excepciones_declaradas_siguen_existiendo_y_siguen_sin_guarda():
    clis = clis_de_estado()
    for cli in SIN_GUARDA_DECLARADA:
        assert cli in clis, "excepción obsoleta: %s ya no alcanza estado" % cli


def test_cada_main_de_deploy_scripts_esta_clasificado_como_instalador():
    mains = {_rel(f) for f in _mains() if _rel(f).startswith("deploy/scripts/")}
    assert mains == set(INSTALADORES), (
        "un __main__ de deploy/scripts sin clasificar (o una clasificación obsoleta): "
        "nuevos=%s obsoletos=%s" % (sorted(mains - set(INSTALADORES)), sorted(set(INSTALADORES) - mains)))


def _tabla_s9k_cli() -> dict:
    texto = (SCRIPTS / "lib.sh").read_text(encoding="utf-8")
    i = texto.index("s9k_cli_destino() {")
    cuerpo = texto[i:texto.index("\n}\n", i)]
    return dict(re.findall(r'^\s+([a-z0-9-]+)\)\s+echo "([^"]+)"', cuerpo, re.M))


def test_cada_herramienta_de_la_guarda_tiene_su_entrada_en_el_envoltorio_y_viceversa():
    """El comando canónico que imprime la guarda (``s9k-cli.sh <herramienta>``) tiene que
    funcionar: cada nombre usado en la guarda está en ``s9k_cli_destino`` y apunta a la CLI."""
    tabla = _tabla_s9k_cli()
    usados = {}
    for cli in clis_de_estado():
        for nombre in _llama_a_la_guarda(RAIZ / cli):
            usados[nombre] = cli
    assert "?" not in usados, "la guarda se llama sin un nombre literal de herramienta"
    assert set(usados) == set(tabla), (sorted(set(usados) ^ set(tabla)))
    for nombre, cli in usados.items():
        comp, directorio, modo, objetivo = tabla[nombre].split("|")
        if modo == "-m":
            base = RAIZ / directorio
            destino = base.joinpath(*objetivo.split(".")).with_suffix(".py")
            if comp == "viewer":
                destino = RAIZ / "viewer" / Path(*objetivo.split(".")).with_suffix(".py")
        else:
            destino = RAIZ / comp / objetivo
        assert destino == RAIZ / cli, "%s apunta a %s, no a %s" % (nombre, destino, cli)


def test_el_envoltorio_canonico_existe_y_usa_runuser():
    f = SCRIPTS / "s9k-cli.sh"
    assert f.is_file() and os.access(f, os.X_OK)
    lib = (SCRIPTS / "lib.sh").read_text(encoding="utf-8")
    i = lib.index("s9k_cli() {")
    cuerpo = lib[i:lib.index("\n}\n", i)]
    assert 'exec runuser -u "${user}" --' in cuerpo and "umask 0077" in cuerpo
    assert ss.CLI_WRAPPER == "deploy/scripts/s9k-cli.sh"


def test_el_gate_detecta_una_cli_nueva_sin_guarda(tmp_path):
    """El detector ve una CLI nueva que abre la cola SIN guarda (el caso que el gate existe
    para evitar). Se planta FUERA del árbol (tmp) y se resuelve contra el motor real: el
    árbol del repositorio no se toca."""
    plantada = tmp_path / "zz_h06_cli_plantada.py"
    plantada.write_text("from jobs import job_store\n\n\nif __name__ == '__main__':\n"
                        "    job_store.init_db()\n", encoding="utf-8")
    assert _tiene_main(ast.parse(plantada.read_text(encoding="utf-8")))
    assert _cierre(plantada, MOTOR_APP) & _escritores_state() == {"data-engine/app/jobs/job_store.py"}
    assert not _llama_a_la_guarda(plantada)
    con_guarda = tmp_path / "zz_h06_cli_con_guarda.py"
    con_guarda.write_text("from jobs import job_store\n\n\nif __name__ == '__main__':\n"
                          "    from knowledge_v3.service_state import reject_root_cli\n"
                          "    reject_root_cli('jobs')\n    job_store.init_db()\n", encoding="utf-8")
    assert _llama_a_la_guarda(con_guarda) == {"jobs"}


# ---------------------------------------------------------------------------
# 2. POR EFECTO: cada CLI, como root (simulado en su proceso), sale con 4 SIN crear nada
# ---------------------------------------------------------------------------

#: (herramienta, cómo se ejecuta, argv). La guarda va ANTES del parser: el argv da igual.
CASOS_CLI = [
    ("jobs", ("path", "data-engine/app/cli/jobs.py"), ["counts"]),
    ("media-jobs", ("path", "data-engine/app/cli/media_jobs.py"), ["--help"]),
    ("glossary", ("path", "data-engine/app/glossary/glossary_cli.py"), ["stats", "--workspace", "w"]),
    ("external-ai", ("path", "data-engine/app/cli/external_ai.py"), ["--help"]),
    ("job-store", ("path", "data-engine/app/jobs/job_store.py"), ["--init"]),
    ("ingest", ("mod", "knowledge_v3.pipeline.ingest_cli"), ["--help"]),
    ("pipeline-runner", ("mod", "knowledge_v3.pipeline.runner"), ["--help"]),
    ("semantic-bench", ("mod", "knowledge_v3.extraction.semantic_bench"), ["--help"]),
    ("writer", ("mod", "knowledge_v3.writer.cli"), ["--help"]),
    ("writer-rollback", ("mod", "knowledge_v3.writer.cli_rollback"), ["--help"]),
    ("writer-schema", ("mod", "knowledge_v3.writer.schema_cli"), ["--help"]),
    ("relations", ("mod", "relations.cli"), ["--help"]),
    ("relations-benchmark", ("mod", "relations.benchmark.cli"), ["--help"]),
    ("relations-calibration", ("mod", "relations.calibration.cli"), ["--help"]),
    ("relations-nvidia", ("mod", "relations.calibration.nvidia_cli"), ["--help"]),
]

_ARRANQUE = (
    "import os, runpy, sys\n"
    "if os.environ.get('H06_FALSO_ROOT') == '1':\n"
    "    os.geteuid = lambda: 0\n"
    "kind, objetivo = sys.argv[1], sys.argv[2]\n"
    "sys.argv = [objetivo] + sys.argv[3:]\n"
    "if kind == 'path':\n"
    "    runpy.run_path(objetivo, run_name='__main__')\n"
    "else:\n"
    "    sys.path.insert(0, os.getcwd())\n"
    "    runpy.run_module(objetivo, run_name='__main__', alter_sys=True)\n"
)


def _ejecutar(kind_obj, argv, env_extra, falso_root=True, umask=None):
    kind, objetivo = kind_obj
    if kind == "path":
        objetivo = str(RAIZ / objetivo)
    env = {k: v for k, v in os.environ.items() if not k.startswith("S9K_")}
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "H06_FALSO_ROOT": "1" if falso_root else "0"})
    env.update(env_extra)

    def _pre():
        if umask is not None:
            os.umask(umask)

    return subprocess.run([sys.executable, "-c", _ARRANQUE, kind, objetivo, *argv], cwd=str(MOTOR_APP),
                          env=env, capture_output=True, text=True, timeout=180, preexec_fn=_pre)


def _foto(raiz: Path):
    return sorted((p.relative_to(raiz).as_posix(), stat.S_IMODE(os.lstat(p).st_mode))
                  for p in raiz.rglob("*")) if raiz.exists() else None


def test_la_tabla_de_casos_cubre_todas_las_herramientas():
    assert {c[0] for c in CASOS_CLI} | {"auth", "health"} == set(_tabla_s9k_cli())


@pytest.mark.parametrize("herramienta,kind_obj,argv", CASOS_CLI, ids=[c[0] for c in CASOS_CLI])
def test_N10_cada_cli_como_root_sale_con_4_sin_crear_nada(tmp_path, herramienta, kind_obj, argv):
    st = tmp_path / "st"
    st.mkdir(mode=0o700)
    (st / "jobs").mkdir(mode=0o700)
    antes = _foto(st)
    env = {"S9K_STATE_ROOT": str(st), "S9K_JOBS_DB": str(st / "jobs" / "jobs.db"),
           "S9K_GLOSSARY_DB": "", "S9K_EXTERNAL_AI_CACHE_DIR": str(st / "external_ai_cache")}
    r = _ejecutar(kind_obj, argv, env)
    assert r.returncode == ss.CLI_ROOT_RC, (herramienta, r.returncode, r.stderr[-800:])
    assert "RECHAZADO" in r.stderr and ("s9k-cli.sh %s" % herramienta) in r.stderr, r.stderr[-400:]
    assert _foto(st) == antes, "la CLI %s creó algo como root: %s" % (herramienta, _foto(st))


def test_job_store_ruta_despliegue_sigue_disponible_para_root(tmp_path):
    """``--ruta-despliegue`` es de SOLO LECTURA y deploy.sh lo usa como root: no se rechaza."""
    r = _ejecutar(("path", "data-engine/app/jobs/job_store.py"),
                  ["--ruta-despliegue", "--state-root", str(tmp_path / "st")], {})
    assert r.returncode == 0 and r.stdout.strip().endswith("jobs.db"), (r.returncode, r.stderr[-400:])
    assert not (tmp_path / "st").exists()


@pytest.mark.skipif(EUID == 0, reason="mide al usuario sin privilegios (el camino correcto)")
def test_P8_jobs_por_el_camino_correcto_con_umask_022_crea_0700_0600(tmp_path):
    db = tmp_path / "st" / "n1" / "n2" / "jobs.db"
    r = _ejecutar(("path", "data-engine/app/cli/jobs.py"), ["counts"],
                  {"S9K_JOBS_DB": str(db), "S9K_STATE_ROOT": str(tmp_path / "st")},
                  falso_root=False, umask=0o022)
    assert r.returncode == 0, r.stderr[-600:]
    for d in (tmp_path / "st", tmp_path / "st" / "n1", tmp_path / "st" / "n1" / "n2"):
        assert stat.S_IMODE(d.stat().st_mode) == 0o700, (d, oct(stat.S_IMODE(d.stat().st_mode)))
    assert stat.S_IMODE(db.stat().st_mode) == 0o600, oct(stat.S_IMODE(db.stat().st_mode))
    for suf in ("-wal", "-shm"):
        p = Path(str(db) + suf)
        if p.exists():
            assert stat.S_IMODE(p.stat().st_mode) == 0o600, p


@pytest.mark.skipif(EUID == 0, reason="mide al usuario sin privilegios (el camino correcto)")
def test_P8_glossary_por_el_camino_correcto_con_umask_022_crea_0700_0600(tmp_path):
    st = tmp_path / "st"
    st.mkdir(mode=0o700)
    r = _ejecutar(("path", "data-engine/app/glossary/glossary_cli.py"), ["stats", "--workspace", "w"],
                  {"S9K_STATE_ROOT": str(st)}, falso_root=False, umask=0o022)
    assert r.returncode == 0, r.stderr[-600:]
    assert stat.S_IMODE((st / "glossary").stat().st_mode) == 0o700
    db = st / "glossary" / "glossary.db"
    assert stat.S_IMODE(db.stat().st_mode) == 0o600, oct(stat.S_IMODE(db.stat().st_mode))
    for suf in ("-wal", "-shm"):
        p = Path(str(db) + suf)
        if p.exists():
            assert stat.S_IMODE(p.stat().st_mode) == 0o600, p


# ---------------------------------------------------------------------------
# 3. ESTRANGULAMIENTO de los escritores: root no crea estado aunque no pase por una CLI
# ---------------------------------------------------------------------------

def test_refuse_root_state_write_solo_actua_como_root_y_bajo_el_state_root(tmp_path):
    st = tmp_path / "st"
    env = {"S9K_STATE_ROOT": str(st)}
    with pytest.raises(ss.RootStateWriteError):
        ss.refuse_root_state_write(st / "jobs" / "jobs.db", env=env, euid=0)
    with pytest.raises(ss.RootStateWriteError):
        ss.refuse_root_state_write(st, env=env, euid=0)
    ss.refuse_root_state_write(tmp_path / "fuera" / "x.db", env=env, euid=0)   # fuera: no actua
    ss.refuse_root_state_write(st / "jobs" / "jobs.db", env=env, euid=1000)   # no root: no actua


_SONDA_ESCRITOR = (
    "import os, sys\n"
    "os.geteuid = lambda: 0\n"
    "sys.path.insert(0, %r)\n"
    "from knowledge_v3 import service_state as ss\n"
    "try:\n"
    "    exec(sys.argv[1])\n"
    "except ss.RootStateWriteError as exc:\n"
    "    print('RECHAZO', exc); sys.exit(7)\n"
    "except PermissionError as exc:\n"
    "    print('RECHAZO-PERM', exc); sys.exit(7)\n"
) % str(MOTOR_APP)


@pytest.mark.parametrize("codigo", [
    "from glossary.glossary_store import GlossaryStore; GlossaryStore()",
    "from jobs import job_store; job_store.init_db(os.environ['S9K_JOBS_DB'])",
    "from jobs import job_store; job_store._connect(os.environ['S9K_JOBS_DB'])",
    "from external_ai.cache import ResponseCache; ResponseCache(enabled=True)",
], ids=["glossary_store", "job_store.init_db", "job_store._connect", "external_ai.cache"])
def test_los_escritores_del_motor_no_crean_estado_como_root(tmp_path, codigo):
    st = tmp_path / "st"
    st.mkdir(mode=0o700)
    (st / "jobs").mkdir(mode=0o700)
    antes = _foto(st)
    env = {k: v for k, v in os.environ.items() if not k.startswith("S9K_")}
    env.update({"S9K_STATE_ROOT": str(st), "S9K_JOBS_DB": str(st / "jobs" / "jobs.db"),
                "PYTHONDONTWRITEBYTECODE": "1"})
    r = subprocess.run([sys.executable, "-c", _SONDA_ESCRITOR, codigo], cwd=str(MOTOR_APP), env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 7 and "RECHAZO" in r.stdout, (r.returncode, r.stdout[-300:], r.stderr[-600:])
    assert _foto(st) == antes, _foto(st)


# ---------------------------------------------------------------------------
# 4. MODOS de la autoridad, no de la umask
# ---------------------------------------------------------------------------

def test_ensure_private_dir_crea_cada_componente_0700_y_no_toca_lo_existente(tmp_path):
    existente = tmp_path / "ya"
    existente.mkdir(mode=0o755)
    existente.chmod(0o755)
    antes = os.umask(0o022)
    try:
        ss.ensure_private_dir(existente / "a" / "b" / "c")
    finally:
        os.umask(antes)
    assert stat.S_IMODE(existente.stat().st_mode) == 0o755, "tocó un directorio preexistente"
    for d in (existente / "a", existente / "a" / "b", existente / "a" / "b" / "c"):
        assert stat.S_IMODE(d.stat().st_mode) == 0o700, (d, oct(stat.S_IMODE(d.stat().st_mode)))


@pytest.mark.parametrize("mascara", [0o022, 0o277])
def test_create_private_file_y_open_private_write_dan_0600_con_cualquier_umask(tmp_path, mascara):
    antes = os.umask(mascara)
    try:
        assert ss.create_private_file(tmp_path / "a.db") is True
        assert ss.create_private_file(tmp_path / "a.db") is False
        fd = ss.open_private_write(tmp_path / "b.json")
        os.close(fd)
    finally:
        os.umask(antes)
    for n in ("a.db", "b.json"):
        assert stat.S_IMODE((tmp_path / n).stat().st_mode) == 0o600, n


def test_el_mensaje_de_rechazo_es_canonico():
    m = ss.cli_root_rejection("jobs", euid=0)
    assert m and "s9k-cli.sh jobs" in m and "runuser -u s9knowledge --" in m
    assert ss.cli_root_rejection("jobs", euid=1000) is None
    assert ss.CLI_ROOT_RC == 4
