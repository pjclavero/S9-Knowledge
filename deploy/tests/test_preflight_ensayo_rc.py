# -*- coding: utf-8 -*-
"""CALIBRACION de la lista de comprobacion previa al ensayo RC.

Una comprobacion que nunca se ha visto en rojo no es una comprobacion: es una
frase. Aqui cada punto de `deploy/scripts/preflight_ensayo_rc.py` se somete a
dos ejercicios:

1. sobre un entorno correcto sale VERDE (o PENDIENTE, si depende de algo que
   todavia no existe y esta declarado como tal);
2. sobre el MISMO entorno con UNA sola mutacion —la que rompe ese invariante
   en el mundo real— sale ROJO.

La mutacion no es inventada: es el fallo que ya se midio. Almacen que el
escritor y el visor resuelven distinto, directorio de fuentes vacio,
interruptor escrito con el nombre del hueco en vez de con su letra, credencial
en el entorno en vez de en un fichero 0600.

Y se calibra tambien el propio instrumento: el canario tiene que dar ROJO, y el
codigo de salida tiene que ser distinto de 0 en cuanto algo queda PENDIENTE.
AUSENCIA != CERO.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import sys
import stat
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUION = REPO_ROOT / "deploy" / "scripts" / "preflight_ensayo_rc.py"

_spec = importlib.util.spec_from_file_location("_preflight_ensayo_rc", GUION)
assert _spec and _spec.loader
pf = importlib.util.module_from_spec(_spec)
# El modulo se registra ANTES de ejecutarlo: `@dataclass` resuelve anotaciones
# mirando `sys.modules[cls.__module__]`, y sin registrar revienta al importar.
sys.modules[_spec.name] = pf
_spec.loader.exec_module(pf)

WS = "ensayo-rc"


@pytest.fixture
def entorno(tmp_path: Path) -> dict:
    """Un despliegue correcto para el ensayo, entero en `tmp_path`.

    `tmp_path` esta FUERA del arbol del repositorio a proposito: es justo lo
    que varias comprobaciones exigen del estado persistente.
    """
    raiz = tmp_path / "state"
    propuestas = raiz / "reviews-v3" / "proposals"
    propuestas.mkdir(parents=True)
    (raiz / "reviews-v3").mkdir(exist_ok=True)
    fuentes = tmp_path / "fuentes"
    fuentes.mkdir()
    (fuentes / "cronica-de-ejemplo.md").write_text("texto\n", encoding="utf-8")
    (raiz / "scanner").mkdir()
    secreto = tmp_path / "secrets" / "neo4j_password"
    secreto.parent.mkdir()
    secreto.write_text("no-se-lee-nunca\n", encoding="utf-8")
    secreto.chmod(0o600)
    return {
        # El commit que ESTE arbol tiene desplegado: el entorno correcto es el
        # que declara el arbol sobre el que va a correr el ensayo.
        "S9K_ENSAYO_COMMIT": pf._head_del_arbol() or "",
        "S9K_STATE_ROOT": str(raiz),
        "S9K_INGEST_SOURCES_DIR": str(fuentes),
        "S9K_V3_REVIEW_PROPOSALS_DIR": str(propuestas),
        "S9K_V3_REVIEW_DATABASE_PATH": str(raiz / "reviews-v3" / "review.sqlite3"),
        "S9K_SCANNER_STATE_PATH": str(raiz / "scanner" / "visto.sqlite3"),
        "S9K_PANEL_B_ENABLED": "true",
        "S9K_PANEL_C_ENABLED": "true",
        "S9K_PANEL_F_ENABLED": "true",
        "S9K_PANEL_G_ENABLED": "true",
        "S9K_PANEL_RESULTADO_ENABLED": "true",
        "S9K_AUTH_ENABLED": "true",
        "S9K_ALLOW_REAL_INGEST": "1",
        "S9K_WRITER_WORKSPACE": WS,
        "S9K_DEFAULT_WORKSPACE": WS,
        "S9K_GRAPH_PROVIDER": "neo4j",
        "S9K_NEO4J_URI": "bolt://127.0.0.1:7687",
        "S9K_NEO4J_USER": "s9k_writer",
        "S9K_NEO4J_PASSWORD_FILE": str(secreto),
    }


def _correr(entorno: dict) -> dict:
    ctx = pf.Contexto(env=dict(entorno), workspace=WS)
    return {r.id: r for r in pf.ejecutar(ctx)}


# ---------------------------------------------------------------------------
# El instrumento
# ---------------------------------------------------------------------------

def test_el_canario_da_rojo(entorno):
    """Si el canario saliera verde, el guion no sabria dar rojo y no sirve."""
    assert pf.canario(pf.Contexto(env=entorno, workspace=WS)).estado == pf.ROJO


def test_main_aborta_si_el_canario_no_da_rojo(monkeypatch, entorno, capsys):
    monkeypatch.setattr(
        pf, "canario",
        lambda ctx: pf.Resultado("canario", pf.VERDE, "instrumento mudo"))
    assert pf.main(["--workspace", WS]) == 3


#: Lo unico que el guion puede importar. `jq` no esta instalado en las maquinas
#: de trabajo y un vigia que lo usaba giro en vacio sin emitir nada; cualquier
#: herramienta externa vuelve a abrir esa puerta, y `subprocess` es la puerta.
IMPORTS_PERMITIDOS = {
    "__future__", "argparse", "importlib", "importlib.util", "os", "stat",
    "sys", "dataclasses", "pathlib", "typing", "urllib.parse",
}


def test_el_guion_solo_usa_biblioteca_estandar():
    """Se PARSEA el arbol: contar apariciones de texto da falsos negativos."""
    arbol = ast.parse(GUION.read_text(encoding="utf-8"))
    usados = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            usados.update(a.name for a in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0:
            usados.add(nodo.module or "")
    assert usados <= IMPORTS_PERMITIDOS, usados - IMPORTS_PERMITIDOS


# ---------------------------------------------------------------------------
# Verde de referencia
# ---------------------------------------------------------------------------

def test_entorno_correcto_no_produce_ni_un_rojo(entorno):
    r = _correr(entorno)
    rojos = {k: v.detalle for k, v in r.items() if v.estado == pf.ROJO}
    assert rojos == {}


def test_la_unica_pendiente_estructural_es_la_del_carril_a(entorno):
    """El worker contra Neo4j real y el escaner son lo unico sin observar.

    Con el escaner declarado, la unica PENDIENTE que queda es la dependencia
    del carril A. Y que quede PENDIENTE BLOQUEA: no autoriza el ensayo.
    """
    r = _correr(entorno)
    pendientes = {k for k, v in r.items() if v.estado == pf.PENDIENTE}
    assert pendientes == {"worker.observa_grafo"}
    assert pf.codigo_de_salida(list(r.values())) == 1


def test_pendiente_no_es_verde(entorno):
    """AUSENCIA != CERO: una comprobacion que no pudo mirar no autoriza."""
    resultados = [pf.Resultado("x", pf.VERDE, ""), pf.Resultado("y", pf.PENDIENTE, "")]
    assert pf.codigo_de_salida(resultados) != 0


# ---------------------------------------------------------------------------
# Una mutacion por invariante: cada punto tiene que saber ponerse rojo
# ---------------------------------------------------------------------------

def test_fuentes_vacias_dan_rojo(entorno, tmp_path):
    """Directorio de fuentes vacio: el paso 1 deja de ser usable SIN error."""
    vacio = tmp_path / "vacio"
    vacio.mkdir()
    entorno["S9K_INGEST_SOURCES_DIR"] = str(vacio)
    assert _correr(entorno)["fuentes.pobladas"].estado == pf.ROJO


def test_fuentes_sin_declarar_dan_rojo(entorno):
    del entorno["S9K_INGEST_SOURCES_DIR"]
    assert _correr(entorno)["fuentes.pobladas"].estado == pf.ROJO


@pytest.mark.parametrize("letra", sorted(pf.HUECOS_DEL_ENSAYO))
def test_un_hueco_apagado_da_rojo(entorno, letra):
    del entorno[f"S9K_PANEL_{letra}_ENABLED"]
    assert _correr(entorno)["paneles.por_letra"].estado == pf.ROJO


def test_valor_que_no_enciende_da_rojo(entorno):
    """El chasis solo acepta 'true' o '1': 'si' deja el panel apagado."""
    entorno["S9K_PANEL_C_ENABLED"] = "si"
    assert _correr(entorno)["paneles.por_letra"].estado == pf.ROJO


def test_interruptor_por_nombre_da_rojo(entorno):
    """Con el nombre del hueco en vez de la letra no monta nada."""
    entorno["S9K_PANEL_REVIEW_ENABLED"] = "true"
    assert _correr(entorno)["paneles.sin_nombres"].estado == pf.ROJO


def test_pantalla_de_resultado_apagada_da_rojo(entorno):
    entorno["S9K_PANEL_RESULTADO_ENABLED"] = "false"
    assert _correr(entorno)["resultado.navegable"].estado == pf.ROJO


def test_propuestas_sin_declarar_da_rojo(entorno):
    del entorno["S9K_V3_REVIEW_PROPOSALS_DIR"]
    assert _correr(entorno)["propuestas.declarada"].estado == pf.ROJO


def test_propuestas_inexistente_da_rojo(entorno, tmp_path):
    """Apuntarla a algo inexistente daba consola vacia y MUDA."""
    entorno["S9K_V3_REVIEW_PROPOSALS_DIR"] = str(tmp_path / "no" / "existe")
    assert _correr(entorno)["propuestas.utilizable"].estado == pf.ROJO


def test_propuestas_solo_lectura_da_rojo(entorno, tmp_path):
    if os.geteuid() == 0:
        pytest.skip("como root los permisos no frenan la escritura")
    ruta = Path(entorno["S9K_V3_REVIEW_PROPOSALS_DIR"])
    modo = stat.S_IMODE(ruta.stat().st_mode)
    ruta.chmod(0o500)
    try:
        assert _correr(entorno)["propuestas.utilizable"].estado == pf.ROJO
    finally:
        ruta.chmod(modo)


def test_propuestas_dentro_del_repositorio_da_rojo(entorno):
    """Un redespliegue se lleva por delante la cola de revision."""
    entorno["S9K_V3_REVIEW_PROPOSALS_DIR"] = str(
        REPO_ROOT / "viewer" / "output" / "reviews-v3" / "proposals")
    assert _correr(entorno)["propuestas.declarada"].estado == pf.ROJO


def test_derivacion_unica_detecta_dos_verdades(entorno, monkeypatch, tmp_path):
    """Si el resolvedor del producto devuelve otra ruta, hay dos almacenes."""
    otra = tmp_path / "otra"
    otra.mkdir()
    falso = type("M", (), {"default_proposals_dir": staticmethod(lambda: otra)})
    monkeypatch.setattr(pf, "_review_paths", lambda *a, **k: falso)
    assert _correr(entorno)["propuestas.derivacion_unica"].estado == pf.ROJO


def test_resolvedor_incargable_queda_pendiente(entorno, monkeypatch):
    """No poder mirar no es estar bien."""
    def revienta(*a, **k):
        raise ImportError("sin motor")
    monkeypatch.setattr(pf, "_review_paths", revienta)
    assert _correr(entorno)["propuestas.derivacion_unica"].estado == pf.PENDIENTE


def test_review_db_sin_declarar_da_rojo(entorno):
    """Cada proceso caeria en el defecto de SU arbol: dos review.sqlite3."""
    del entorno["S9K_V3_REVIEW_DATABASE_PATH"]
    assert _correr(entorno)["review_db.compartida"].estado == pf.ROJO


def test_review_db_que_el_motor_resuelve_distinto_da_rojo(entorno, monkeypatch, tmp_path):
    falso = type("M", (), {"default_decisions_db": staticmethod(
        lambda: tmp_path / "otro" / "review.sqlite3")})
    monkeypatch.setattr(pf, "_review_decisions", lambda *a, **k: falso)
    assert _correr(entorno)["review_db.compartida"].estado == pf.ROJO


def test_review_db_dentro_del_repositorio_da_rojo(entorno):
    entorno["S9K_V3_REVIEW_DATABASE_PATH"] = str(
        REPO_ROOT / "viewer" / "output" / "reviews-v3" / "review.sqlite3")
    assert _correr(entorno)["review_db.compartida"].estado == pf.ROJO


def test_estado_repartido_en_dos_volumenes_da_rojo(entorno, tmp_path):
    """Separar los volumenes es como vuelve el falso exito POR DESPLIEGUE."""
    aparte = tmp_path / "otro-volumen" / "proposals"
    aparte.mkdir(parents=True)
    entorno["S9K_V3_REVIEW_PROPOSALS_DIR"] = str(aparte)
    assert _correr(entorno)["estado.persistente"].estado == pf.ROJO


def test_sin_state_root_da_rojo(entorno):
    del entorno["S9K_STATE_ROOT"]
    assert _correr(entorno)["estado.persistente"].estado == pf.ROJO


def test_escaner_sin_estado_durable_queda_pendiente(entorno):
    """Reiniciar no debe reprocesarlo todo. Hoy no hay estado que mirar."""
    del entorno["S9K_SCANNER_STATE_PATH"]
    r = _correr(entorno)["reinicio.no_reprocesa"]
    assert r.estado == pf.PENDIENTE
    assert "reprocesa" in r.detalle or "ingeridos" in r.detalle


def test_estado_del_escaner_en_el_repositorio_da_rojo(entorno):
    entorno["S9K_SCANNER_STATE_PATH"] = str(REPO_ROOT / "viewer" / "output" / "visto.db")
    assert _correr(entorno)["reinicio.no_reprocesa"].estado == pf.ROJO


def test_auth_apagada_da_rojo(entorno):
    entorno["S9K_AUTH_ENABLED"] = "false"
    assert _correr(entorno)["auth.activa"].estado == pf.ROJO


def test_sin_permiso_de_escritura_no_hay_boton(entorno):
    """Sin esto la pantalla NO ofrece el boton y el POST da APPLY_NOT_ENABLED."""
    entorno["S9K_ALLOW_REAL_INGEST"] = "true"  # el codigo exige exactamente "1"
    assert _correr(entorno)["apply.habilitado"].estado == pf.ROJO


def test_writer_en_otro_workspace_da_rojo(entorno):
    entorno["S9K_WRITER_WORKSPACE"] = "otra-partida"
    assert _correr(entorno)["apply.habilitado"].estado == pf.ROJO


def test_visor_y_writer_en_workspaces_distintos_dan_rojo(entorno):
    """Leer en uno y escribir en otro sin que se note es el fallo de aislamiento."""
    entorno["S9K_DEFAULT_WORKSPACE"] = "otro-mundo"
    assert _correr(entorno)["aislamiento.workspace"].estado == pf.ROJO


def test_secreto_en_el_entorno_da_rojo(entorno):
    entorno["S9K_NEO4J_PASSWORD"] = "loquesea"
    r = _correr(entorno)["neo4j.credencial"]
    assert r.estado == pf.ROJO
    assert "loquesea" not in r.detalle


def test_credencial_con_permisos_abiertos_da_rojo(entorno):
    Path(entorno["S9K_NEO4J_PASSWORD_FILE"]).chmod(0o644)
    assert _correr(entorno)["neo4j.credencial"].estado == pf.ROJO


def test_credencial_inexistente_da_rojo(entorno, tmp_path):
    entorno["S9K_NEO4J_PASSWORD_FILE"] = str(tmp_path / "no-esta")
    assert _correr(entorno)["neo4j.credencial"].estado == pf.ROJO


def test_usuario_administrador_da_rojo(entorno):
    """Minimo privilegio: el ensayo no corre como el administrador del grafo."""
    entorno["S9K_NEO4J_USER"] = "neo4j"
    assert _correr(entorno)["neo4j.credencial"].estado == pf.ROJO


def test_ninguna_salida_lleva_el_secreto(entorno):
    """Ni un valor de credencial por ninguna superficie del guion."""
    for resultado in _correr(entorno).values():
        assert "no-se-lee-nunca" not in resultado.detalle


def test_remoto_sin_cifrar_da_rojo(entorno):
    entorno["S9K_NEO4J_URI"] = "bolt://un-host-remoto:7687"
    assert _correr(entorno)["neo4j.transporte"].estado == pf.ROJO


def test_certificado_sin_verificar_da_rojo(entorno):
    """'+ssc' es una ruta de repuesto silenciosa: acepta autofirmados."""
    entorno["S9K_NEO4J_URI"] = "neo4j+ssc://un-host-remoto:7687"
    assert _correr(entorno)["neo4j.transporte"].estado == pf.ROJO


def test_cifrado_sin_ca_queda_pendiente(entorno):
    entorno["S9K_NEO4J_URI"] = "neo4j+s://un-host-remoto:7687"
    assert _correr(entorno)["neo4j.transporte"].estado == pf.PENDIENTE


def test_cifrado_con_ca_presente_es_verde(entorno, tmp_path):
    ca = tmp_path / "ca.pem"
    ca.write_text("-----BEGIN CERTIFICATE-----\n", encoding="utf-8")
    entorno["S9K_NEO4J_URI"] = "neo4j+s://un-host-remoto:7687"
    entorno["S9K_NEO4J_CA_FILE"] = str(ca)
    assert _correr(entorno)["neo4j.transporte"].estado == pf.VERDE


def test_grafo_mock_da_rojo(entorno):
    """Un mock daria el recorrido por bueno sin tocar el grafo."""
    entorno["S9K_GRAPH_PROVIDER"] = "mock"
    assert _correr(entorno)["worker.observa_grafo"].estado == pf.ROJO


def test_la_dependencia_del_carril_a_esta_declarada(entorno):
    r = _correr(entorno)["worker.observa_grafo"]
    assert r.estado == pf.PENDIENTE
    assert "CARRIL A" in r.detalle


def test_una_comprobacion_que_revienta_es_rojo(entorno, monkeypatch):
    """Nunca se traga una excepcion: un hueco en la lista seria un falso verde."""
    def revienta(ctx):
        raise RuntimeError("boom")
    monkeypatch.setattr(pf, "COMPROBACIONES", (("x.revienta", revienta),))
    resultados = pf.ejecutar(pf.Contexto(env=entorno, workspace=WS))
    assert [r.estado for r in resultados] == [pf.ROJO]


# ---------------------------------------------------------------------------
# Arreglos de la revision independiente
# ---------------------------------------------------------------------------

def test_el_testigo_no_queda_en_el_almacen(entorno, monkeypatch):
    """Un guion de SOLO LECTURA no deja basura donde mira el operador.

    Medido en la revision: sin `finally`, un fallo en el `unlink` dejaba
    `.s9k-preflight-testigo` residual en el almacen de propuestas. El desenlace
    era ROJO --no un falso verde-- pero el fichero se quedaba.
    """
    almacen = Path(entorno["S9K_V3_REVIEW_PROPOSALS_DIR"])
    original = Path.is_file

    def revienta_tras_escribir(self, *a, **k):
        if self.name == ".s9k-preflight-testigo":
            raise OSError("fallo DESPUES de escribir el testigo")
        return original(self, *a, **k)

    monkeypatch.setattr(Path, "is_file", revienta_tras_escribir)
    resultado = _correr(entorno)["propuestas.utilizable"]
    monkeypatch.undo()

    assert resultado.estado == pf.ROJO
    residuales = [p.name for p in almacen.iterdir()]
    assert residuales == [], residuales


def test_un_testigo_irretirable_se_dice(entorno, monkeypatch):
    """Si ni siquiera se puede borrar, el operador se entera: no se tapa."""
    original = Path.unlink

    def unlink_que_falla(self, *a, **k):
        if self.name == ".s9k-preflight-testigo":
            raise OSError("no se pudo retirar")
        return original(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", unlink_que_falla)
    resultado = _correr(entorno)["propuestas.utilizable"]
    monkeypatch.undo()
    Path(entorno["S9K_V3_REVIEW_PROPOSALS_DIR"], ".s9k-preflight-testigo").unlink()

    assert resultado.estado == pf.ROJO
    assert "testigo" in resultado.detalle


def test_el_testigo_se_retira_en_el_camino_feliz(entorno):
    almacen = Path(entorno["S9K_V3_REVIEW_PROPOSALS_DIR"])
    assert _correr(entorno)["propuestas.utilizable"].estado == pf.VERDE
    assert list(almacen.iterdir()) == []


def test_state_root_degenerado_da_rojo(entorno):
    """`S9K_STATE_ROOT=/` hace que TODO caiga dentro: puerta que no cierra."""
    entorno["S9K_STATE_ROOT"] = "/"
    assert _correr(entorno)["estado.persistente"].estado == pf.ROJO


# ---------------------------------------------------------------------------
# El secreto no sale por NINGUNA superficie -- cerrado por los dos lados
# ---------------------------------------------------------------------------
# El test de `detalle` no miraba `stdout`/`stderr`: calibrado por mutacion, una
# fuga por `print()` en `main()` dejaba toda la suite en verde. Se cierra (a)
# ejecutando `main()` y mirando la salida, y (b) afirmando por AST que el guion
# no LEE el contenido de la credencial. Lo segundo es lo que convierte la
# disciplina en estructura: aunque manana alguien anada una traza, no tendra
# el valor que filtrar.

#: Lo que NO se puede hacer con el fichero de credencial: leer su contenido.
LECTURAS_DE_CONTENIDO = {"read_text", "read_bytes", "read", "readline",
                         "readlines", "open"}


def test_main_imprime_su_propio_recuento(entorno, monkeypatch, capsys):
    """Lo que no imprime la maquina se cuenta a mano, y a mano ya salio mal."""
    for clave, valor in entorno.items():
        monkeypatch.setenv(clave, valor)
    pf.main(["--workspace", WS])
    salida = capsys.readouterr().out
    linea = next(l for l in salida.splitlines() if l.startswith("RECUENTO"))
    assert f"TOTAL {len(pf.COMPROBACIONES)}" in linea
    for estado in (pf.ROJO, pf.PENDIENTE, pf.VERDE):
        esperado = sum(1 for l in salida.splitlines() if l.startswith(estado))
        assert f"{estado} {esperado}" in linea


def test_main_no_imprime_el_secreto(entorno, monkeypatch, capsys):
    """`main()` entero, con la salida capturada. Incluye el veredicto."""
    for clave, valor in entorno.items():
        monkeypatch.setenv(clave, valor)
    codigo = pf.main(["--workspace", WS])
    salida = capsys.readouterr()
    assert codigo == 1  # PENDIENTE del carril A: no autoriza
    assert "no-se-lee-nunca" not in salida.out
    assert "no-se-lee-nunca" not in salida.err


def test_el_guion_no_lee_el_contenido_de_la_credencial():
    """Se PARSEA la funcion: de la credencial se miran metadatos, no el valor."""
    arbol = ast.parse(GUION.read_text(encoding="utf-8"))
    funcion = next(
        n for n in ast.walk(arbol)
        if isinstance(n, ast.FunctionDef) and n.name == "credencial_por_fichero"
    )
    lecturas = []
    for nodo in ast.walk(funcion):
        if not isinstance(nodo, ast.Call):
            continue
        objetivo = nodo.func
        nombre = (objetivo.attr if isinstance(objetivo, ast.Attribute)
                  else objetivo.id if isinstance(objetivo, ast.Name) else None)
        if nombre in LECTURAS_DE_CONTENIDO:
            lecturas.append(nombre)
    assert lecturas == [], lecturas


def test_otro_arbol_da_rojo(entorno):
    """Un agente reanudado perdio su worktree y siguio en otro 30 ficheros
    por detras de `main`, creyendo que era el suyo. Un ensayo sobre el arbol
    equivocado juzga un producto que no es el que se va a desplegar, y no se
    distingue de uno bueno.
    """
    entorno["S9K_ENSAYO_COMMIT"] = "0" * 40
    assert _correr(entorno)["arbol.declarado"].estado == pf.ROJO


@pytest.mark.parametrize("declarado", ["e", "e7", "e75f19", "no-es-un-sha", "zzzzzzz"])
def test_un_commit_truncado_o_no_hexadecimal_da_rojo(entorno, declarado):
    """La misma puerta degenerada que `S9K_STATE_ROOT=/`, y en el punto cuya
    razon de ser es que el arbol no mienta: un prefijo de un caracter casaba
    con cualquier arbol cuyo HEAD empezara por el, y salia VERDE.
    """
    entorno["S9K_ENSAYO_COMMIT"] = declarado
    assert _correr(entorno)["arbol.declarado"].estado == pf.ROJO


def test_el_commit_declarado_en_mayusculas_es_verde(entorno):
    """Direccion segura, pero un falso rojo es ruido evitable."""
    entorno["S9K_ENSAYO_COMMIT"] = (pf._head_del_arbol() or "").upper()
    assert _correr(entorno)["arbol.declarado"].estado == pf.VERDE


def test_un_prefijo_legitimo_es_verde(entorno):
    """Siete digitos bastan: es lo que identifica un commit, no una letra."""
    entorno["S9K_ENSAYO_COMMIT"] = (pf._head_del_arbol() or "")[:7]
    assert _correr(entorno)["arbol.declarado"].estado == pf.VERDE


def test_arbol_sin_declarar_queda_pendiente(entorno):
    del entorno["S9K_ENSAYO_COMMIT"]
    assert _correr(entorno)["arbol.declarado"].estado == pf.PENDIENTE


def test_arbol_ilegible_queda_pendiente(entorno, monkeypatch):
    """No poder mirar el arbol no es que el arbol este bien."""
    monkeypatch.setattr(pf, "_head_del_arbol", lambda *a, **k: None)
    assert _correr(entorno)["arbol.declarado"].estado == pf.PENDIENTE


def test_el_head_se_lee_sin_invocar_git(entorno):
    """Se resuelve leyendo `.git` (incluido el de un worktree enlazado)."""
    cabeza = pf._head_del_arbol()
    assert cabeza and len(cabeza) == 40 and all(c in "0123456789abcdef" for c in cabeza)
    assert _correr(entorno)["arbol.declarado"].estado == pf.VERDE


def test_la_declaracion_de_apply_es_la_del_producto():
    """Los nombres que lee `apply.habilitado` son los que exige el writer.

    El guion los escribe como literales (importar el visor arrastraria FastAPI
    a una comprobacion de solo lectura). Esta prueba ata esa segunda copia a la
    ORIGINAL: si el producto renombra una variable, el preflight diria "boton
    disponible" sobre un despliegue que contesta APPLY_NOT_ENABLED.
    """
    fuente = (REPO_ROOT / "viewer" / "app" / "services" / "v3_apply.py").read_text(
        encoding="utf-8")
    arbol = ast.parse(fuente)
    constantes = {}
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Assign) and isinstance(nodo.value, ast.Constant):
            for destino in nodo.targets:
                if isinstance(destino, ast.Name):
                    constantes[destino.id] = nodo.value.value
    assert constantes.get("ENV_ALLOW_REAL_INGEST") == "S9K_ALLOW_REAL_INGEST"
    assert constantes.get("ENV_WRITER_WORKSPACE") == "S9K_WRITER_WORKSPACE"
