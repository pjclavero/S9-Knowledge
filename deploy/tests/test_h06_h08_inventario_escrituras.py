# -*- coding: utf-8 -*-
"""H-06 + H-08 (§3) — INVENTARIO ESTRUCTURAL de las escrituras persistentes del servicio.

POR QUE EXISTE
--------------
El contrato exige "inventariar PRIMERO TODAS las escrituras persistentes de visor
y worker (derivado de codigo/config cuando sea posible); no mover solo los dos
ficheros conocidos". Un inventario escrito a mano se pudre en la primera
funcionalidad nueva. Este test lo DERIVA del codigo:

  * recorre por AST los modulos del visor (``viewer/app``) y el CIERRE ESTATICO de
    importaciones del worker (``data-engine/app/jobs/worker.py`` y todo lo que
    importa dentro de ``data-engine/app``);
  * cuenta los sitios de escritura persistente de cada modulo (``open`` en modo
    escritura, ``os.open`` con flags de creacion/escritura, ``write_text``,
    ``mkdir``/``makedirs``, ``replace``/``rename``/``link``/``unlink``, ``shutil``,
    ``tempfile``, ``chmod``/``chown`` y ``sqlite3.connect`` que no sea ``mode=ro``);
  * lo compara con la tabla ``INVENTARIO`` de abajo, que da a cada modulo un
    TECHO y dice a que variable/ruta del state root pertenece lo que escribe.

FALLA si aparece un sitio de escritura NUEVO (un modulo no declarado con
escrituras, o uno declarado que supera su techo): el autor tiene que decidir
donde vive lo que escribe (bajo el state root, 0600/0700) y declararlo aqui y
en ``deploy/README.md``. Bajar el techo (menos escrituras) nunca falla.

TECHO DECLARADO
---------------
Es un conteo de SITIOS DE LLAMADA, no un analisis de flujo de datos: no ve una
escritura hecha por reflexion, por un subproceso (``subprocess``) ni por una
libreria de terceros; el cierre del worker es estatico (no sigue ``importlib``
dinamico). Las rutas concretas que cada sitio escribe las gobierna
``service_state.effective_paths`` y las valida el arranque fail-closed.

CLASES
------
STATE   escribe bajo el state root (variable indicada); lo cubre el arranque fail-closed
TMP     temporal del proceso (``tempfile``/directorio efimero): no es estado
EXTERNO escribe fuera del state root por diseno (boveda del operador, catalogo)
CLI     herramienta de operador/offline que NO corre en el servicio (se ejecuta con
        ``runuser -u s9knowledge --`` si toca estado; rechazo de root cuando aplica)
REPO    datos del repositorio / dev (no existen en la release)
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
APP_MOTOR = RAIZ / "data-engine" / "app"

_ESCRIBE_METODOS = {
    "write_text", "write_bytes", "touch", "mkdir", "makedirs", "rmdir", "unlink",
    "symlink", "link", "chmod", "chown", "utime", "truncate", "rmtree", "copytree",
}
_ESCRIBE_FUNCS_MODULO = {
    "os": {"replace", "rename", "remove", "unlink", "makedirs", "mkdir", "link", "symlink",
           "chmod", "chown", "lchown", "truncate", "utime", "rmdir", "removedirs"},
    "shutil": {"copy", "copy2", "copyfile", "copytree", "move", "rmtree", "copymode", "copystat"},
    "tempfile": {"mkstemp", "mkdtemp", "NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile"},
}
_FLAGS_ESCRITURA = {"O_CREAT", "O_WRONLY", "O_RDWR", "O_APPEND", "O_TRUNC", "O_EXCL"}


def _modo_escritura(modo) -> bool:
    return isinstance(modo, str) and any(c in modo for c in "wax+")


def _es_sqlite_solo_lectura(llamada: ast.Call) -> bool:
    if not llamada.args:
        return False
    texto = ast.unparse(llamada.args[0])
    return "mode=ro" in texto


def contar_escrituras(codigo: str) -> int:
    """Numero de sitios de escritura persistente en ``codigo`` (AST)."""
    try:
        arbol = ast.parse(codigo)
    except SyntaxError:
        return 0
    n = 0
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call):
            continue
        f = nodo.func
        nombre = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
        if nombre is None:
            continue
        propietario = ast.unparse(f.value) if isinstance(f, ast.Attribute) else None
        if nombre == "open":
            if propietario == "os":
                flags = {x.attr for x in ast.walk(nodo.args[1])
                         if isinstance(x, ast.Attribute)} if len(nodo.args) > 1 else set()
                if flags & _FLAGS_ESCRITURA:
                    n += 1
                continue
            # builtin open(ruta, modo) / Path.open(modo) / io.open / codecs.open
            modo = None
            pos = 1 if (propietario is None or propietario in ("io", "codecs", "gzip", "bz2", "lzma")) else 0
            if len(nodo.args) > pos and isinstance(nodo.args[pos], ast.Constant):
                modo = nodo.args[pos].value
            for k in nodo.keywords:
                if k.arg == "mode" and isinstance(k.value, ast.Constant):
                    modo = k.value.value
            if _modo_escritura(modo):
                n += 1
        elif nombre == "fdopen":
            modo = nodo.args[1].value if len(nodo.args) > 1 and isinstance(nodo.args[1], ast.Constant) else None
            if _modo_escritura(modo):
                n += 1
        elif nombre == "connect" and propietario == "sqlite3":
            if not _es_sqlite_solo_lectura(nodo):
                n += 1
        elif propietario in _ESCRIBE_FUNCS_MODULO and nombre in _ESCRIBE_FUNCS_MODULO[propietario]:
            n += 1
        elif nombre in _ESCRIBE_METODOS and isinstance(f, ast.Attribute) \
                and propietario not in _ESCRIBE_FUNCS_MODULO:
            n += 1
    return n


def ficheros_viewer():
    for f in sorted((RAIZ / "viewer" / "app").rglob("*.py")):
        rel = f.relative_to(RAIZ).as_posix()
        if "/tests/" in rel or f.name.startswith("test_") or f.name == "conftest.py" or ".bak" in rel:
            continue
        yield f


def cierre_del_worker():
    """Modulos de data-engine/app alcanzables por importacion estatica desde worker.py."""
    vistos, pila = set(), [APP_MOTOR / "jobs" / "worker.py"]

    def resolver(nombre: str):
        partes = nombre.split(".")
        for k in range(len(partes), 0, -1):
            base = APP_MOTOR.joinpath(*partes[:k])
            if base.with_suffix(".py").is_file():
                return base.with_suffix(".py")
            if (base / "__init__.py").is_file():
                return base / "__init__.py"
        return None

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
                    pkg = f.parent.relative_to(APP_MOTOR).parts
                    base = list(pkg[: len(pkg) - (n.level - 1)])
                    modulo = base + (n.module.split(".") if n.module else [])
                    nombres = [".".join(modulo)] + [".".join(modulo + [a.name]) for a in n.names]
            for nm in nombres:
                r = resolver(nm)
                if r is not None and r not in vistos:
                    pila.append(r)
    return sorted(vistos)


def ficheros_worker():
    for f in cierre_del_worker():
        rel = f.relative_to(RAIZ).as_posix()
        if "/tests/" in rel or f.name.startswith("test_") or ".bak" in rel:
            continue
        yield f


# ---------------------------------------------------------------------------
# LA TABLA: modulo -> (techo, clase, de donde sale lo que escribe)
# ---------------------------------------------------------------------------
INVENTARIO = {
    # ---- VISOR ------------------------------------------------------------
    "viewer/app/auth/db.py": (7, "STATE", "S9K_AUTH_DB_PATH: auth.db(-wal,-shm), .lock, .bak.vN (nacen 0600)"),
    "viewer/app/auth/bootstrap.py": (1, "STATE", "S9K_AUTH_DB_PATH: sello del primer admin"),
    "viewer/app/auth/csrf_bootstrap.py": (7, "STATE", "S9K_AUTH_DB_PATH (junto a ella): .csrf_secret 0600"),
    "viewer/app/cli/auth.py": (1, "CLI", "mkdir del directorio de auth.db; solo como s9knowledge (rechazo de root)"),
    "viewer/app/routers/admin.py": (1, "STATE", "S9K_AUTH_DB_PATH: mkdir del directorio de auth.db"),
    "viewer/app/main.py": (1, "STATE", "S9K_AUTH_DB_PATH: mkdir del directorio de auth.db al arrancar"),
    "viewer/app/health/storage.py": (5, "STATE", "S9K_HEALTH_REPORT_PATH: health.json 0600 (lo escribe el healthcheck)"),
    "viewer/app/services/v3_review.py": (0, "STATE", "S9K_V3_REVIEW_DECISIONS_PATH / junto a S9K_V3_REVIEW_DATABASE_PATH: decisions.jsonl, audit.jsonl (via open_private_append)"),
    "viewer/app/services/v3_glossary_candidates.py": (0, "STATE", "S9K_V3_GLOSSARY_CANDIDATES_DIR / junto a decisions (via open_private_append)"),
    "viewer/app/services/v3_review_store.py": (3, "STATE", "S9K_V3_REVIEW_DATABASE_PATH: review.sqlite3 (la CREA el despliegue; el runtime solo abre)"),
    "viewer/app/service_identity.py": (3, "STATE", "open_private_append: JSONL de decisiones/auditoria/candidatos, 0600 en directorio 0700"),
    "viewer/app/services/review_console.py": (3, "TMP", "S9K_REVIEW_LAB_DIR o tempdir; consola de revision APAGADA por defecto (PR-1)"),
    "viewer/app/vault_writer.py": (8, "EXTERNAL_OPERATOR_CONTENT", "S9K_VAULT_ROOT: perfil-operador.json en la boveda del operador (fuera del state root; escribe solo si el FS ya concede permiso; sin chown/chmod, sin fallback ni copia bajo STATE)"),
    # ---- WORKER (cierre estatico de worker.py) ----------------------------
    "data-engine/app/jobs/job_store.py": (5, "STATE", "S9K_JOBS_DB: jobs.db(-wal,-shm) (nace 0600)"),
    "data-engine/app/knowledge_v3/review_decisions.py": (1, "STATE", "S9K_V3_REVIEW_DATABASE_PATH: lectura de decisiones (conexion sqlite)"),
    "data-engine/app/knowledge_v3/review_paths.py": (1, "STATE", "S9K_V3_REVIEW_DATABASE_PATH: inspeccion (conexion sqlite)"),
    "data-engine/app/knowledge_v3/review_export.py": (5, "STATE", "S9K_V3_REVIEW_PROPOSALS_DIR: propuestas (UMask=0077 de la unidad)"),
    "data-engine/app/knowledge_v3/pipeline/ingest_cli.py": (7, "STATE", "S9K_V3_REVIEW_PROPOSALS_DIR + informes de la ingesta"),
    "data-engine/app/knowledge_v3/ledger/store.py": (2, "STATE", "ledger de la ingesta"),
    "data-engine/app/knowledge_v3/writer/audit.py": (3, "STATE", "auditoria del escritor (ruta que se le pasa)"),
    "data-engine/app/knowledge_v3/writer/idempotency.py": (4, "STATE", "indice de idempotencia del escritor"),
    "data-engine/app/knowledge_v3/service_state.py": (4, "STATE", "sondas efimeras de acceso (se borran)"),
    # Alcanzables por importacion estatica pero NO ejecutados en la ruta del
    # worker (modulos de herramientas): sus escrituras estan DECLARADAS, no ocultas.
    "data-engine/app/external_ai/cache.py": (2, "STATE", "S9K_EXTERNAL_AI_CACHE_DIR: cache de IA externa, por defecto <state root>/external_ai_cache (ya no en la release)"),
    "data-engine/app/glossary/glossary_store.py": (2, "STATE", "S9K_GLOSSARY_DB: glossary.db, por defecto <state root>/glossary (ya no en la release)"),
    "data-engine/app/review/export_import.py": (4, "CLI", "export/import offline de revision (herramienta de operador)"),
}
#: Modulos del cierre del worker que son HERRAMIENTAS de operador/offline o datos de
#: repositorio, con escrituras reales, pero que el servicio NO ejecuta en su ruta:
#: se declaran con clase y SIN techo exigido (se listan para que no pasen en silencio).
FUERA_DEL_SERVICIO = {
    "data-engine/app/knowledge_v3/writer/cli.py": "CLI",
    "data-engine/app/knowledge_v3/writer/cli_rollback.py": "CLI",
    "data-engine/app/knowledge_v3/benchmarks/cli.py": "CLI",
}


def _rel(f: Path) -> str:
    return f.relative_to(RAIZ).as_posix()


def _conteos():
    viewer = {_rel(f): contar_escrituras(f.read_text(encoding="utf-8")) for f in ficheros_viewer()}
    worker = {_rel(f): contar_escrituras(f.read_text(encoding="utf-8")) for f in ficheros_worker()}
    return viewer, worker


def test_el_detector_no_esta_roto():
    """DETECTOR ROTO si el escaner no ve lo que sabemos que existe."""
    viewer, worker = _conteos()
    assert sum(viewer.values()) >= 25, ("el escaner del visor ve %d sitios" % sum(viewer.values()))
    assert sum(worker.values()) >= 20, ("el escaner del worker ve %d sitios" % sum(worker.values()))
    assert viewer["viewer/app/auth/db.py"] >= 5
    assert "data-engine/app/jobs/job_store.py" in worker and len(worker) > 20, len(worker)
    assert contar_escrituras("open('x','w')") == 1
    assert contar_escrituras("open('x')") == 0
    assert contar_escrituras("from pathlib import Path\nPath('x').open('a')") == 1
    assert contar_escrituras("import sqlite3\nsqlite3.connect(f'file:{p}?mode=ro', uri=True)") == 0
    assert contar_escrituras("import sqlite3\nsqlite3.connect(p)") == 1
    assert contar_escrituras("import os\nos.open(p, os.O_WRONLY | os.O_CREAT, 0o600)") == 1


def test_ninguna_escritura_persistente_nueva_fuera_de_lo_declarado():
    viewer, worker = _conteos()
    actual = {**viewer, **worker}
    nuevos, superan = [], []
    for ruta, n in sorted(actual.items()):
        if n == 0:
            continue
        if ruta in FUERA_DEL_SERVICIO:
            continue
        if ruta not in INVENTARIO:
            nuevos.append("%s (%d sitio(s))" % (ruta, n))
        elif n > INVENTARIO[ruta][0]:
            superan.append("%s: %d > techo %d" % (ruta, n, INVENTARIO[ruta][0]))
    assert not nuevos and not superan, (
        "ESCRITURA PERSISTENTE NUEVA sin declarar. Decide DONDE vive lo que escribe "
        "(bajo el state root, 0600/0700, una variable de ruta que valide "
        "service_state.effective_paths) y declarala en INVENTARIO y en "
        "deploy/README.md.\n  sin declarar: %s\n  por encima del techo: %s" % (nuevos, superan))


def test_el_inventario_no_declara_modulos_que_ya_no_existen():
    for ruta in list(INVENTARIO) + list(FUERA_DEL_SERVICIO):
        assert (RAIZ / ruta).is_file(), "INVENTARIO obsoleto: %s ya no existe" % ruta


def test_cada_entrada_del_inventario_tiene_clase_y_gobierno():
    clases = {"STATE", "TMP", "EXTERNAL_OPERATOR_CONTENT", "CLI"}
    for ruta, (techo, clase, gobierno) in INVENTARIO.items():
        assert clase in clases and gobierno.strip() and techo >= 0, ruta


def test_toda_escritura_de_clase_STATE_del_visor_pertenece_a_una_variable_de_ruta_de_la_autoridad():
    """Lo que el inventario llama STATE y se gobierna por variable tiene que ser una de
    las que valida la autoridad (``STATE_PATH_VARS``)."""
    import importlib.util
    import sys

    nombre = "_s9k_service_state"
    if nombre not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            nombre, APP_MOTOR / "knowledge_v3" / "service_state.py")
        m = importlib.util.module_from_spec(spec)
        sys.modules[nombre] = m
        spec.loader.exec_module(m)
    ss = sys.modules[nombre]
    for ruta, (_t, clase, gobierno) in INVENTARIO.items():
        if clase != "STATE":
            continue
        variables = [tok.rstrip(":,") for tok in gobierno.replace("/", " ").split()
                     if tok.startswith("S9K_")]
        for v in variables:
            assert v in ss.STATE_PATH_VARS, "%s: %s no es una variable de ruta de la autoridad" % (ruta, v)


#: §7 · CLASIFICACION de lo persistente (no solo de lo que escribe codigo): las cuatro clases.
CLASIFICACION = {
    "auth.db(-wal,-shm)": "STATE", "review.sqlite3(-wal,-shm)": "STATE", "jobs.db(-wal,-shm)": "STATE",
    "decisions.jsonl": "STATE", "audit.jsonl": "STATE", "glossary-candidates": "STATE",
    "glossary.db": "STATE", "cache de IA externa": "STATE", ".csrf_secret": "STATE",
    "password Neo4j (/etc/s9-knowledge/secrets)": "SECRET", "viewer.env": "SECRET",
    "releases (codigo, venvs, templates)": "RELEASE",
    "backups (raiz separada del state)": "BACKUP",
    "bóveda del operador (S9K_VAULT_ROOT, perfil-operador.json)": "EXTERNAL_OPERATOR_CONTENT",
}


def test_la_clasificacion_usa_las_cinco_clases_del_contrato():
    assert set(CLASIFICACION.values()) == {"STATE", "SECRET", "RELEASE", "BACKUP", "EXTERNAL_OPERATOR_CONTENT"}
    readme = (RAIZ / "deploy" / "README.md").read_text(encoding="utf-8")
    for clave in CLASIFICACION:
        assert clave.split("(")[0].strip() in readme, "el README no clasifica %s" % clave


def test_hay_inventario_documentado_en_el_readme():
    readme = (RAIZ / "deploy" / "README.md").read_text(encoding="utf-8")
    assert "Inventario de escrituras persistentes" in readme
    for ruta in ("viewer/app/auth/db.py", "viewer/app/services/v3_review.py",
                 "data-engine/app/jobs/job_store.py"):
        assert ruta in readme, "el README no inventaria %s" % ruta
