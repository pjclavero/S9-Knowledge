"""CALIBRACIÓN DEL INSTRUMENTO. Se ejecuta ANTES de medir nada.

Regla del operador que este guion implementa al pie de la letra:

    «Una afirmación no constituye evidencia porque exista un test verde. La
    evidencia aparece cuando: sabes qué comportamiento afirma; calibras el
    mecanismo que lo mide; introduces una violación; el sistema se pone rojo;
    reviertes; vuelve a verde.»

Qué protege la puerta
---------------------
``run_bench.py`` se niega a medir si esta calibración no existe, no pasó, o no
corresponde a lo que va a medir. "Corresponder" son DOS hashes:

  * ``sha_del_instrumento`` — TODOS los módulos del laboratorio, **incluidos el
    juez (`calibracion.py`) y el guion de medida (`run_bench.py`) y el doble de
    driver (`fake_neo4j.py`)**. En v2.0 el hash sólo cubría lo medido, no al
    juez: se podía neutralizar ``_ok()`` o sabotear el driver falso y la puerta
    seguía imprimiendo "instrumento calibrado".
  * ``sha_del_sistema_medido`` — el árbol ``viewer/app/**``. Un cambio en el
    visor invalida la calibración aunque el laboratorio no se toque; si no, una
    calibración vieja avala cifras de un sistema que ya es otro.

Pruebas
-------
  C0  META         — el juez sabe fallar: una afirmación falsa debe salir roja.
  C1  eje PÁGINA   — N+1 por elemento devuelto.   inyectar -> rojo, revertir -> verde
  C1b ceguera de v1 — MEDIDA a tres tamaños, no afirmada en prosa.
  C2  eje DATASET  — N+1 por entidad del grafo.   inyectar -> rojo, revertir -> verde
  C3  eje GRADO    — N+1 por relación del nodo.   real -> rojo, control -> verde, real -> rojo
  C4  CACHÉ        — generador cambiado -> invalidada; **fichero manipulado -> invalidada**
  C5  PRESUPUESTO  — regresión inyectada -> techo roto, revertir -> cumple
  C6  ESTADÍSTICA  — regresión de latencia -> "peor"; ruido puro -> "indistinguible"
  C7  N+1 PARCIAL  — 1 consulta cada 2, cada 3, cada 5 y cada sqrt(n) elementos:
                     las cuatro deben salir rojas (el umbral fijo de v2.0 declaraba
                     sanas tres de ellas).
  C8  DRIVER FALSO — el contador de consultas Cypher, contrastado con un contador
                     independiente; saboteado -> rojo.
  C9a SATURACIÓN   — el criterio de v2.1 (`da == db`) es CIEGO justo en
                     /api/graph?limit=300 y da FALSOS POSITIVOS en /api/sources;
                     el criterio nuevo ve uno y deja de inventarse el otro.
  C9b SATURACIÓN   — ABLACIÓN: las tres cláusulas del criterio son necesarias.
  C10 HASH SISTEMA — mutar `viewer/app/static/js/graph.js` mueve el hash. Con el
                     filtro de v2.1 (`.py`/`.html`) no lo movía: 16 ficheros
                     invisibles, el motor de pintado del grafo entre ellos.
  C11 N+1 CON TOPE — `min(2*g+3, T)` da serie PLANA; sin la señal de carga el
                     veredicto era "constante, pendiente 0.0" para un endpoint
                     que hace T consultas por petición.

Y dentro de C4, la parte (c): el ataque COHERENTE (fichero manipulado *y*
sidecar recalculado) engaña a `obtener()`, y `verificar_a_fondo` lo caza porque
el generador es determinista y el sha esperado es calculable.

Nada queda aplicado: todos los parches viven en memoria y se revierten en el
mismo proceso.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ / "viewer"))
sys.path.insert(0, str(AQUI))

import arnes  # noqa: E402
import cache  # noqa: E402
import dataset  # noqa: E402
import detector  # noqa: E402
import estadistica  # noqa: E402
from dataset import Parametros  # noqa: E402

# TODOS los módulos del laboratorio, el juez incluido.
MODULOS_DEL_ARNES = (
    "arnes.py", "cache.py", "calibracion.py", "dataset.py", "detector.py",
    "estadistica.py", "fake_neo4j.py", "instrumentation.py", "run_bench.py",
)

# Los tres tamaños del eje del dataset deben LLENAR la página de 50: con n=10 la
# página trae 10 elementos y el N+1 por página añade 10 llamadas en vez de 50,
# lo que introduce un crecimiento espurio que no viene del tamaño del grafo sino
# de que la primera página se queda corta.
TAMANOS_EJE_DATASET = (100, 250, 500)
PAGINAS = (10, 50, 100)


def sha_del_instrumento() -> str:
    h = hashlib.sha256()
    for nombre in MODULOS_DEL_ARNES:
        h.update(nombre.encode("utf-8"))
        h.update((AQUI / nombre).read_bytes())
    return h.hexdigest()


def ficheros_del_sistema_medido() -> list[Path]:
    """TODO fichero versionable bajo ``viewer/app/**``.

    Defecto de v2.0: la lista se filtraba por ``suffix in (".py", ".html")``.
    Medido: dejaba fuera 16 ficheros —4 ``.js``, 3 ``.css`` y 9 ``.json``—,
    entre ellos ``static/js/graph.js``, que es EL MOTOR DE PINTADO DEL GRAFO,
    es decir el objeto mismo de este carril. Mutar ``graph.js`` no movía el
    hash y ``run_bench.py`` seguía midiendo con una calibración que decía
    corresponder a ese sistema. El hash no cubría lo que su nombre promete.

    v2.1 no filtra por extensión: si está bajo ``viewer/app/`` y no es un
    artefacto de compilación de Python, cuenta.
    """
    base = RAIZ / "viewer" / "app"
    return sorted(
        p for p in base.rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and p.suffix not in (".pyc", ".pyo")
    )


def sha_del_sistema_medido() -> str:
    """Hash del árbol del visor. Si cambia el sistema, la calibración caduca."""
    ficheros = ficheros_del_sistema_medido()
    h = hashlib.sha256()
    for p in ficheros:
        h.update(str(p.relative_to(RAIZ)).encode("utf-8"))
        h.update(p.read_bytes())
    return h.hexdigest()


@contextlib.contextmanager
def parche(objeto, atributo: str, valor):
    """Sustituye un atributo y lo devuelve SIEMPRE a su sitio."""
    original = getattr(objeto, atributo)
    setattr(objeto, atributo, valor)
    try:
        yield original
    finally:
        setattr(objeto, atributo, original)


def _grado(grafo: dict, nid: str) -> int:
    return sum(1 for e in grafo["edges"] if e["from"] == nid or e["to"] == nid)


def _ok(nombre: str, condicion: bool, detalle: dict) -> dict:
    print(f"  [{'OK ' if condicion else 'FALLO'}] {nombre}", flush=True)
    return {"nombre": nombre, "superada": bool(condicion), **detalle}


# ---------------------------------------------------------------------------
# C0 — META: ¿sabe fallar el juez?
# ---------------------------------------------------------------------------

def c0_el_juez_sabe_fallar() -> dict:
    """Si alguien neutraliza ``_ok`` (por ejemplo ``condicion = True``), TODAS las
    calibraciones pasarían vacuamente y la puerta quedaría contenta. Aquí se le
    da al juez una afirmación deliberadamente falsa y se exige que la marque.
    """
    falsa = _ok("C0.interna (debe salir FALLO: es falsa a propósito)", 1 == 2, {})
    verdadera = _ok("C0.interna (debe salir OK)", 1 == 1, {})
    superada = falsa["superada"] is False and verdadera["superada"] is True
    print(f"  [{'OK ' if superada else 'FALLO'}] C0 META: el juez sabe fallar", flush=True)
    return {
        "nombre": "C0 META: el juez distingue verdadero de falso",
        "superada": superada,
        "afirmacion_falsa_marcada_como": falsa["superada"],
        "afirmacion_verdadera_marcada_como": verdadera["superada"],
        "nota": (
            "Sin esta prueba, neutralizar `_ok` hace pasar vacuamente C1-C8. "
            "Además `calibracion.py` está ahora dentro del hash del instrumento."
        ),
    }


# ---------------------------------------------------------------------------
# Parches de N+1 reutilizables
# ---------------------------------------------------------------------------

def _hacer_parche_por_pagina(original, cada: int | str):
    """Una consulta extra por cada ``cada`` elementos de la página.

    ``cada='sqrt'`` dispara sqrt(len(pagina)) consultas: crecimiento real pero
    marcadamente sublineal.
    """
    def _parcheado(self, *a, **kw):
        page, total = original(self, *a, **kw)
        if cada == "sqrt":
            objetivo = page[: int(math.sqrt(len(page)))]
        else:
            objetivo = page[:: int(cada)]
        for item in objetivo:
            self._base.entity(item.get("id"))
        return page, total
    return _parcheado


def _hacer_parche_por_dataset(original):
    def _parcheado(self, *a, **kw):
        page, total = original(self, *a, **kw)
        for i in range(total):
            self._base.entity(f"p_{i:07d}")
        return page, total
    return _parcheado


def _medidas_pagina(cliente, contador) -> dict[int, int]:
    return {
        k: arnes.llamadas_de(cliente, contador, f"/api/entities?offset=0&limit={k}")
        for k in PAGINAS
    }


# ---------------------------------------------------------------------------
# C1 — eje PÁGINA
# ---------------------------------------------------------------------------

def c1_eje_pagina(cliente, contador) -> dict:
    from app.authz.filtered_provider import PolicyFilteredProvider

    original = PolicyFilteredProvider.list_entities
    verde_antes = detector.dictaminar("pagina", "api_entities", _medidas_pagina(cliente, contador))

    with parche(PolicyFilteredProvider, "list_entities",
                _hacer_parche_por_pagina(original, 1)):
        rojo = detector.dictaminar("pagina", "api_entities", _medidas_pagina(cliente, contador))

    verde_despues = detector.dictaminar("pagina", "api_entities", _medidas_pagina(cliente, contador))

    return _ok(
        "C1 eje PÁGINA: N+1 por elemento devuelto",
        verde_antes.veredicto == "constante"
        and rojo.veredicto == "N+1"
        and verde_despues.como_dict() == verde_antes.como_dict(),
        {
            "verde_antes": verde_antes.como_dict(),
            "rojo_con_violacion": rojo.como_dict(),
            "verde_tras_revertir": verde_despues.como_dict(),
        },
    )


# ---------------------------------------------------------------------------
# C7 — N+1 PARCIALES (sublineales)
# ---------------------------------------------------------------------------

def c7_n_mas_1_parciales(cliente, contador) -> dict:
    """El umbral fijo de 0.5 llamadas/elemento de v2.0 declaraba SANOS estos tres.

    Se inyecta una consulta cada 2, cada 3, cada 5 y cada sqrt(n) elementos de
    la página. Las cuatro son N+1 reales. Las cuatro deben salir rojas.
    """
    from app.authz.filtered_provider import PolicyFilteredProvider

    original = PolicyFilteredProvider.list_entities
    casos = {"1_de_cada_2": 2, "1_de_cada_3": 3, "1_de_cada_5": 5, "sqrt": "sqrt"}
    resultados = {}
    for nombre, cada in casos.items():
        with parche(PolicyFilteredProvider, "list_entities",
                    _hacer_parche_por_pagina(original, cada)):
            d = detector.dictaminar("pagina", f"api_entities[{nombre}]",
                                    _medidas_pagina(cliente, contador))
        resultados[nombre] = d.como_dict()

    control = detector.dictaminar("pagina", "api_entities[sin_defecto]",
                                  _medidas_pagina(cliente, contador))

    todos_rojos = all(r["veredicto"] == "N+1" for r in resultados.values())
    return _ok(
        "C7 N+1 PARCIALES: 1 consulta cada 2 / 3 / 5 / sqrt(n) elementos",
        todos_rojos and control.veredicto == "constante",
        {
            "casos": resultados,
            "control_sin_defecto": control.como_dict(),
            "pendientes": {k: v["pendiente"] for k, v in resultados.items()},
            "nota": (
                "Con el umbral fijo de 0.5 de v2.0, sólo '1_de_cada_2' (pendiente "
                "0.50) salía rojo; 1/3 (0.33), 1/5 (0.20) y sqrt (0.08) se "
                "declaraban 'constante'. El criterio de crecimiento los ve todos."
            ),
        },
    )


# ---------------------------------------------------------------------------
# C2 + C1b — eje DATASET, medido SECUENCIALMENTE
# ---------------------------------------------------------------------------

def c2_eje_dataset_y_c1b() -> tuple[dict, dict]:
    """Un cliente vivo a la vez.

    En v2.0 esta prueba mantenía dos clientes simultáneos sobre el MISMO objeto
    ``app`` global: ``dependency_overrides`` es un diccionario compartido y
    ganaba el último, así que el "cliente de n=10" leía el grafo de 500 y su
    contador marcaba 0. El rojo salía por aritmética sobre un cero fantasma
    (501/490 = 1.0224), no por el defecto. Aquí cada tamaño se monta, se mide
    entero —sano, con N+1 de dataset y con N+1 de página— y se desmonta.
    """
    from app.authz.filtered_provider import PolicyFilteredProvider

    url_fija = "/api/entities?offset=0&limit=50"
    sano: dict[int, int] = {}
    con_n1_dataset: dict[int, int] = {}
    con_n1_pagina: dict[int, int] = {}

    for n in TAMANOS_EJE_DATASET:
        cliente, contador, app, _ = arnes.montar(Parametros(n_entities=n))
        try:
            original = PolicyFilteredProvider.list_entities
            sano[n] = arnes.llamadas_de(cliente, contador, url_fija)
            with parche(PolicyFilteredProvider, "list_entities",
                        _hacer_parche_por_dataset(original)):
                con_n1_dataset[n] = arnes.llamadas_de(cliente, contador, url_fija)
            with parche(PolicyFilteredProvider, "list_entities",
                        _hacer_parche_por_pagina(original, 1)):
                con_n1_pagina[n] = arnes.llamadas_de(cliente, contador, url_fija)
        finally:
            app.dependency_overrides.clear()

    verde = detector.dictaminar("dataset", "api_entities", sano)
    rojo = detector.dictaminar("dataset", "api_entities", con_n1_dataset)
    ceguera = detector.dictaminar("dataset", "api_entities[N+1 por página]", con_n1_pagina)

    c2 = _ok(
        "C2 eje DATASET: N+1 por entidad del grafo (clientes secuenciales)",
        verde.veredicto == "constante"
        and all(v > 0 for v in sano.values())  # ningún contador fantasma a 0
        and rojo.veredicto == "N+1",
        {
            "llamadas_sano_por_tamano": {str(k): v for k, v in sano.items()},
            "verde_sin_violacion": verde.como_dict(),
            "rojo_con_violacion": rojo.como_dict(),
        },
    )
    c1b = _ok(
        "C1b ceguera del eje DATASET ante el N+1 por página (defecto de v1), MEDIDA",
        ceguera.veredicto == "constante"
        and len(set(con_n1_pagina.values())) == 1,
        {
            "llamadas_con_defecto_a_pagina_fija": {str(k): v for k, v in con_n1_pagina.items()},
            "dictamen_eje_dataset": ceguera.como_dict(),
            "nota": (
                "Mismo defecto, mismo `limit=50`, tres tamaños de grafo: el mismo "
                "número de llamadas siempre. El eje del dataset da pendiente 0.0 y "
                "dice 'constante'; el eje de página dice 'N+1'. Por eso el detector "
                "de v1 fallaba su propia calibración."
            ),
        },
    )
    return c2, c1b


# ---------------------------------------------------------------------------
# C3 — eje GRADO (hubs)
# ---------------------------------------------------------------------------

def c3_eje_grado(cliente, contador, grafo, ids: list[str]) -> dict:
    from app.providers.mock_provider import MockGraphProvider

    grados = {nid: _grado(grafo, nid) for nid in ids}

    def medir() -> dict[int, int]:
        return {grados[nid]: arnes.llamadas_de(cliente, contador, f"/api/entities/{nid}")
                for nid in ids}

    rojo_real = detector.dictaminar("grado", "api_entity_detalle", medir())

    # CONTROL VERDE (control de calibración, no propuesta de arreglo): sin
    # relaciones que resolver, el coste no depende del grado.
    with parche(MockGraphProvider, "relations_for_entity", lambda self, eid: ([], [])):
        verde_control = detector.dictaminar("grado", "api_entity_detalle", medir())
    rojo_de_nuevo = detector.dictaminar("grado", "api_entity_detalle", medir())

    return _ok(
        "C3 eje GRADO: N+1 por relación del nodo (defecto REAL, hubs)",
        rojo_real.veredicto == "N+1"
        and verde_control.veredicto == "constante"
        and rojo_de_nuevo.como_dict() == rojo_real.como_dict(),
        {
            "grados": {k: v for k, v in grados.items()},
            "rojo_codigo_real": rojo_real.como_dict(),
            "verde_control_sin_relaciones": verde_control.como_dict(),
            "rojo_tras_revertir": rojo_de_nuevo.como_dict(),
        },
    )


# ---------------------------------------------------------------------------
# C4 — CACHÉ: generador Y contenido
# ---------------------------------------------------------------------------

def c4_cache(tmp: Path) -> dict:
    import shutil

    raiz = tmp / "cache_calibracion"
    shutil.rmtree(raiz, ignore_errors=True)
    p = Parametros(n_entities=20)

    e1 = cache.obtener(p, raiz)
    e2 = cache.obtener(p, raiz)  # sin tocar nada: REUTILIZA

    # -- (a) generador estropeado -------------------------------------------
    buenas = list(dataset.VISIBILITIES)
    dataset.VISIBILITIES[:] = ["public", "narrator", "secret", "reference"]
    guardia_salto = False
    try:
        dataset.verificar_visibilidad_valida()
    except ValueError:
        guardia_salto = True
    with parche(dataset, "verificar_visibilidad_valida", lambda: None):
        e_malo = cache.obtener(p, raiz)
        contenido_malo = e1.ruta.read_text(encoding="utf-8")
    dataset.VISIBILITIES[:] = buenas
    e3 = cache.obtener(p, raiz)
    contenido_bueno = e1.ruta.read_text(encoding="utf-8")

    # -- (b) FICHERO MANIPULADO, sidecar intacto ----------------------------
    # Ataque exacto del revisor contra v2.0: truncar el dataset a 2 nodos con el
    # defecto histórico y dejar el sidecar como estaba. v2.0 lo daba por bueno.
    sidecar_antes = cache.leer_sidecar(e1.ruta)
    e1.ruta.write_text(
        json.dumps({
            "workspace": dataset.WORKSPACE,
            "nodes": [
                {"id": "p_0000000", "label": "manipulado", "visibility": "public"},
                {"id": "p_0000001", "label": "manipulado", "visibility": "public"},
            ],
            "edges": [],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    sidecar_sin_tocar = cache.leer_sidecar(e1.ruta) == sidecar_antes
    e_manipulado = cache.obtener(p, raiz)
    contenido_restaurado = e1.ruta.read_text(encoding="utf-8")

    # -- (c) ATAQUE COHERENTE: fichero manipulado Y sidecar recalculado -------
    # Límite que le quedaba a v2.1: la huella sólo detecta manipulación
    # INCOHERENTE. Si el atacante recalcula el sidecar, `obtener()` dice
    # "reutilizado" y el defecto revive. Aquí se monta el ataque completo, se
    # comprueba que `obtener()` PICA, y se demuestra que el sha correcto es
    # CALCULABLE (generador determinista) y `verificar_a_fondo` lo caza.
    veneno = json.dumps({
        "workspace": dataset.WORKSPACE,
        "nodes": [{"id": "p_0000000", "label": "coherente", "visibility": "public"}],
        "edges": [],
    }, ensure_ascii=False)
    e1.ruta.write_text(veneno, encoding="utf-8")
    sidecar_falsificado = dict(sidecar_antes or {})
    sidecar_falsificado["sha256_fichero"] = cache.sha_de_fichero(e1.ruta)
    sidecar_falsificado["bytes"] = e1.ruta.stat().st_size
    cache._sidecar(e1.ruta).write_text(
        json.dumps(sidecar_falsificado, indent=2, ensure_ascii=False), encoding="utf-8")

    e_coherente = cache.obtener(p, raiz)          # pica: "reutilizado"
    forense = cache.verificar_a_fondo(p, raiz)    # no pica: recalcula
    e1.ruta.write_text(contenido_restaurado, encoding="utf-8")
    cache.obtener(p, raiz)                        # deja la caché sana otra vez
    forense_sano = cache.verificar_a_fondo(p, raiz)

    # -- (d) sidecar borrado -------------------------------------------------
    (e1.ruta.with_suffix(e1.ruta.suffix + ".huella.json")).unlink()
    e4 = cache.obtener(p, raiz)
    e5 = cache.obtener(p, raiz)

    return _ok(
        "C4 CACHÉ: invalida por generador Y por contenido del fichero",
        e1.estado == "generado"
        and e2.estado == "reutilizado"
        and guardia_salto
        and e_malo.estado == "regenerado_por_huella"
        and '"visibility": "public"' in contenido_malo
        and e3.estado == "regenerado_por_huella"
        and '"visibility": "public"' not in contenido_bueno
        and sidecar_sin_tocar
        and e_manipulado.estado == "regenerado_por_contenido"
        and '"visibility": "public"' not in contenido_restaurado
        and len(json.loads(contenido_restaurado)["nodes"]) == 20
        # (c) el ataque coherente: obtener() pica, verificar_a_fondo NO
        and e_coherente.estado == "reutilizado"
        and forense["integro"] is False
        and forense["el_sidecar_miente"] is True
        and forense_sano["integro"] is True
        and forense_sano["el_sidecar_miente"] is False
        and e4.estado == "regenerado_sin_huella"
        and e5.estado == "reutilizado",
        {
            "estados": [e1.estado, e2.estado, e_malo.estado, e3.estado,
                        e_manipulado.estado, e4.estado, e5.estado],
            "guardia_de_vocabulario_tambien_salta": guardia_salto,
            "a_generador_roto": {
                "huella_sana": e3.huella,
                "huella_rota": e_malo.huella,
                "el_fichero_cacheado_tenia_el_defecto": '"visibility": "public"' in contenido_malo,
                "tras_regenerar_desaparece": '"visibility": "public"' not in contenido_bueno,
            },
            "c_ataque_coherente": {
                "ataque": "truncado a 1 nodo con visibility=public Y sidecar RECALCULADO",
                "obtener_dice": e_coherente.estado,
                "obtener_pica": e_coherente.estado == "reutilizado",
                "verificar_a_fondo_con_el_ataque": forense,
                "verificar_a_fondo_con_la_cache_sana": forense_sano,
                "por_que_no_va_en_obtener": (
                    "recalcular el sha esperado exige REGENERAR el dataset entero, "
                    "que es exactamente lo que la caché evita. Queda declarado: "
                    "`obtener()` detecta manipulación incoherente; el ataque "
                    "coherente se caza con `verificar_a_fondo`, y aquí queda "
                    "demostrado que es detectable, no una esperanza."
                ),
            },
            "b_fichero_manipulado": {
                "ataque": "truncado a 2 nodos con visibility=public, sidecar intacto",
                "sidecar_no_se_toco": sidecar_sin_tocar,
                "v20_habria_dicho": "reutilizado (la huella del generador seguía cuadrando)",
                "v21_dice": e_manipulado.estado,
                "nodos_tras_regenerar": len(json.loads(contenido_restaurado)["nodes"]),
                "defecto_presente_tras_regenerar": '"visibility": "public"' in contenido_restaurado,
            },
        },
    )


# ---------------------------------------------------------------------------
# C5 — PRESUPUESTOS
# ---------------------------------------------------------------------------

def c5_presupuesto(cliente, contador) -> dict:
    from app.authz.filtered_provider import PolicyFilteredProvider

    url = "/api/entities?offset=0&limit=50"
    base = arnes.llamadas_de(cliente, contador, url)
    presupuestos = {"api_entities_p50": {"llamadas_fuente": float(base)}}

    def medido() -> dict:
        return {"api_entities_p50": {"llamadas_fuente": float(
            arnes.llamadas_de(cliente, contador, url))}}

    verde_antes = detector.comprobar_presupuestos(medido(), presupuestos)

    original = PolicyFilteredProvider.list_entities

    def con_regresion(self, *a, **kw):
        page, total = original(self, *a, **kw)
        for item in page[:5]:
            self._base.entity(item.get("id"))
        return page, total

    with parche(PolicyFilteredProvider, "list_entities", con_regresion):
        rojo = detector.comprobar_presupuestos(medido(), presupuestos)
    verde_despues = detector.comprobar_presupuestos(medido(), presupuestos)

    return _ok(
        "C5 PRESUPUESTO de llamadas: regresión inyectada rompe el techo",
        verde_antes == [] and len(rojo) == 1 and verde_despues == [],
        {
            "presupuesto": presupuestos,
            "verde_antes": [i.como_dict() for i in verde_antes],
            "rojo_con_regresion": [i.como_dict() for i in rojo],
            "verde_tras_revertir": [i.como_dict() for i in verde_despues],
        },
    )


# ---------------------------------------------------------------------------
# C6 — ESTADÍSTICA
# ---------------------------------------------------------------------------

def c6_estadistica(cliente) -> dict:
    from app.authz.filtered_provider import PolicyFilteredProvider

    url = "/api/entities?offset=0&limit=50"
    reps = 40
    base = estadistica.resumir(arnes.tiempos_de(cliente, url, reps))
    repeticion = estadistica.resumir(arnes.tiempos_de(cliente, url, reps))
    ruido = estadistica.comparar(base, repeticion)

    original = PolicyFilteredProvider.list_entities
    RETARDO_S = 0.005

    def con_retardo(self, *a, **kw):
        time.sleep(RETARDO_S)
        return original(self, *a, **kw)

    with parche(PolicyFilteredProvider, "list_entities", con_retardo):
        lenta = estadistica.resumir(arnes.tiempos_de(cliente, url, reps))
    tras_revertir = estadistica.resumir(arnes.tiempos_de(cliente, url, reps))

    efecto = estadistica.comparar(base, lenta)
    vuelta = estadistica.comparar(base, tras_revertir)

    return _ok(
        "C6 ESTADÍSTICA: efecto real -> 'peor'; ruido puro -> 'indistinguible'",
        ruido.veredicto == "indistinguible del ruido"
        and efecto.veredicto == "peor"
        and vuelta.veredicto == "indistinguible del ruido",
        {
            "retardo_inyectado_ms": RETARDO_S * 1000,
            "base": base.como_dict(),
            "misma_medida_repetida": ruido.como_dict(),
            "con_retardo": efecto.como_dict(),
            "tras_revertir": vuelta.como_dict(),
        },
    )


# ---------------------------------------------------------------------------
# C8 — El DOBLE DE DRIVER también se calibra
# ---------------------------------------------------------------------------

def c8_driver_falso() -> dict:
    """La tabla de consultas Cypher salía de un mecanismo nunca visto en rojo.

    Aquí se contrasta ``FakeDriver.n_consultas`` con un contador INDEPENDIENTE
    instalado en ``FakeSession.run`` (otra función, otro sitio). Coinciden ->
    verde. Saboteado el registro del driver -> discrepancia -> rojo. Y un
    control directo: tres ``session.run`` deben contarse como exactamente tres.
    """
    import fake_neo4j
    from fake_neo4j import FakeDriver, FakeSession, proveedor_neo4j_falso

    grafo = dataset.generate(120)
    independiente = {"n": 0}
    run_original = FakeSession.run

    def run_contado(self, query, params=None):
        independiente["n"] += 1
        return run_original(self, query, params)

    def ejercitar(prov) -> None:
        prov.counts(dataset.WORKSPACE)
        prov.entity_types(dataset.WORKSPACE)
        prov.graph(dataset.WORKSPACE, limit=100)
        prov.list_entities(dataset.WORKSPACE, limit=50)
        prov.entity("p_0000060")
        prov.relations_for_entity("p_0000060")
        prov.quality_metrics(dataset.WORKSPACE)

    with parche(FakeSession, "run", run_contado):
        # -- control directo: 3 consultas son 3 --------------------------------
        prov, driver = proveedor_neo4j_falso(grafo)
        driver.reset()
        independiente["n"] = 0
        with driver.session() as s:
            s.run("MATCH (n) RETURN count(n) AS c")
            s.run("MATCH (n) RETURN count(n) AS c")
            s.run("MATCH (n) RETURN count(n) AS c")
        control_directo = (driver.n_consultas, independiente["n"])

        # -- verde: driver y contador independiente coinciden ------------------
        prov, driver = proveedor_neo4j_falso(grafo)
        driver.reset()
        independiente["n"] = 0
        ejercitar(prov)
        verde = (driver.n_consultas, independiente["n"])

        # -- rojo: se sabotea el driver para contar la mitad -------------------
        ejecutar_original = FakeDriver._ejecutar
        estado = {"i": 0}

        def ejecutar_saboteado(self, query, params):
            filas = self._filas_para(query, params)
            estado["i"] += 1
            if estado["i"] % 2 == 0:  # registra sólo una de cada dos
                self.registros.append(
                    fake_neo4j.Registro(" ".join(query.split()), dict(params), len(filas))
                )
            return fake_neo4j.FakeResult(filas)

        with parche(FakeDriver, "_ejecutar", ejecutar_saboteado):
            prov, driver = proveedor_neo4j_falso(grafo)
            driver.reset()
            independiente["n"] = 0
            estado["i"] = 0
            ejercitar(prov)
            rojo = (driver.n_consultas, independiente["n"])

        # -- verde de nuevo ----------------------------------------------------
        prov, driver = proveedor_neo4j_falso(grafo)
        driver.reset()
        independiente["n"] = 0
        ejercitar(prov)
        verde_otra_vez = (driver.n_consultas, independiente["n"])

    return _ok(
        "C8 DRIVER FALSO: el contador de Cypher contrastado con un contador independiente",
        control_directo == (3, 3)
        and verde[0] == verde[1] and verde[0] > 0
        and rojo[0] != rojo[1]
        and verde_otra_vez == verde,
        {
            "control_directo_3_consultas": {"driver": control_directo[0],
                                            "independiente": control_directo[1]},
            "verde": {"driver": verde[0], "independiente": verde[1], "coinciden": verde[0] == verde[1]},
            "rojo_driver_saboteado": {"driver": rojo[0], "independiente": rojo[1],
                                      "discrepancia_detectada": rojo[0] != rojo[1]},
            "verde_tras_revertir": {"driver": verde_otra_vez[0],
                                    "independiente": verde_otra_vez[1]},
            "limite_que_sigue_en_pie": (
                "Este control calibra el RECUENTO de consultas. El número de FILAS "
                "que devuelve el doble sigue siendo plausible y no exacto: el doble "
                "no ejecuta Cypher."
            ),
        },
    )


# ---------------------------------------------------------------------------
# C9 — SATURACIÓN (cero cobertura en v2.0)
# ---------------------------------------------------------------------------

TAMANOS_SATURACION = (10, 100, 250, 500)


def _saturado_v20(da: dict, db: dict) -> bool:
    """El criterio de v2.0, tal cual estaba en ``run_bench.discontinuidades``.

    Se conserva AQUÍ, y sólo aquí, como control negativo: es lo que hay que
    ver fallar para que el criterio nuevo signifique algo.
    """
    return bool(da) and da == db


def c9_saturacion() -> tuple[dict, dict]:
    """Mide de VERDAD las series de desglose y contrasta los dos criterios.

    Nada de fixtures: se monta el visor a tres tamaños y se leen los tamaños
    reales de ``/api/graph?limit=300`` y ``/api/sources``.
    """
    urls = {
        "api_graph_300": "/api/graph?limit=300",
        "api_sources": "/api/sources",
    }
    desgloses: dict[str, list[dict[str, int]]] = {k: [] for k in urls}
    for n in TAMANOS_SATURACION:
        cliente, _contador, app, _ = arnes.montar(Parametros(n_entities=n))
        try:
            for nombre, url in urls.items():
                datos = cliente.get(url).json()
                desgloses[nombre].append({
                    k: len(datos[k]) for k in arnes.CLAVES_LISTA
                    if isinstance(datos.get(k), list)
                })
        finally:
            app.dependency_overrides.clear()

    series = {
        nombre: {k: [d[k] for d in ds] for k in ds[0]}
        for nombre, ds in desgloses.items()
    }
    tramos = list(range(len(TAMANOS_SATURACION) - 1))

    def v21(nombre: str, **ablacion) -> list[bool]:
        return [detector.analizar_saturacion(urls[nombre], series[nombre], i, **ablacion)["saturado"]
                for i in tramos]

    def v20(nombre: str) -> list[bool]:
        return [_saturado_v20(desgloses[nombre][i], desgloses[nombre][i + 1]) for i in tramos]

    graf_v20, graf_v21 = v20("api_graph_300"), v21("api_graph_300")
    src_v20, src_v21 = v20("api_sources"), v21("api_sources")

    # El tramo donde el visor satura de verdad es el último (250 -> 500).
    ultimo = detector.analizar_saturacion(urls["api_graph_300"], series["api_graph_300"], tramos[-1])
    aristas_bajan = any(c["componente"] == "edges" for c in ultimo["componentes_que_decrecen"])

    c9a = _ok(
        "C9a SATURACIÓN: el criterio de v2.0 es CIEGO en /api/graph?limit=300; el de v2.1 lo ve",
        # Falso negativo de v2.0 en el tramo real de saturación...
        graf_v20[-1] is False
        # ...y falsos positivos de v2.0 en un endpoint que no satura.
        and any(src_v20)
        # v2.1: ve la saturación real y deja de inventarse la falsa.
        and graf_v21[-1] is True
        and not any(src_v21)
        # y registra el colapso de aristas, que es la parte grave.
        and aristas_bajan,
        {
            "tamanos": list(TAMANOS_SATURACION),
            "desglose_api_graph_300": desgloses["api_graph_300"],
            "desglose_api_sources": desgloses["api_sources"],
            "api_graph_300": {"criterio_v20": graf_v20, "criterio_v21": graf_v21},
            "api_sources": {"criterio_v20": src_v20, "criterio_v21": src_v21},
            "componentes_saturados_en_el_ultimo_tramo": ultimo["componentes_saturados"],
            "componentes_que_decrecen_en_el_ultimo_tramo": ultimo["componentes_que_decrecen"],
            "nota": (
                "v2.0 comparaba diccionarios enteros con `da == db`. En el tramo real "
                "el desglose pasa de {nodes:250, edges:750} a {nodes:300, edges:550}: "
                "difieren, luego 'no saturado'. Y en /api/sources, plano en 4 mientras "
                "aún no ha empezado a crecer, decía 'saturado'."
            ),
        },
    )

    # -- ABLACIONES sobre el MISMO código, cláusula a cláusula -----------------
    # `exigir_acotado` se ablaciona sobre la serie MEDIDA arriba. Las otras dos
    # necesitan formas de serie que este dataset no produce, así que se declaran
    # explícitas: son series SINTÉTICAS, no medidas, y aquí queda dicho.
    sin_acotado = v21("api_graph_300", exigir_acotado=False)

    def dos_criterios(url: str, serie: dict[str, list[int]], idx: int, **abl):
        con = detector.analizar_saturacion(url, serie, idx)["saturado"]
        sin = detector.analizar_saturacion(url, serie, idx, **abl)["saturado"]
        return con, sin

    # Componente constante desde el primer tamaño: nunca creció, luego no hay
    # techo que demostrar. Es la forma pura del falso positivo de `api_sources`.
    serie_constante = {"sources": [4, 4, 4]}
    con_crec, sin_crec = dos_criterios(
        "/api/sources", serie_constante, 0, exigir_crecimiento_previo=False)

    # Meseta transitoria muy por debajo de su máximo: pausa, no techo. Es la
    # forma del falso positivo de `api_graph_300_filtro_tipo` entre 100 y 101.
    serie_meseta_baja = {"nodes": [2, 13, 13, 63]}
    con_max, sin_max = dos_criterios(
        "/api/graph?limit=300&entity_type=Character", serie_meseta_baja, 1,
        exigir_maximo=False)

    c9b = _ok(
        "C9b SATURACIÓN: las tres cláusulas del criterio son NECESARIAS (ablación)",
        # Sin "acotado por el techo", el limit=300 de los NODOS se le achaca a
        # las ARISTAS (que llegan a 750) y aparece saturación donde no la hay.
        any(sin_acotado[:-1]) and not any(graf_v21[:-1])
        # Sin "creció antes", un componente constante pasa por techo.
        and sin_crec is True and con_crec is False
        # Sin "en su máximo", una meseta transitoria pasa por techo.
        and sin_max is True and con_max is False,
        {
            "ablacion_exigir_acotado": {
                "serie": "MEDIDA en esta misma prueba",
                "api_graph_300_con_clausula": graf_v21,
                "api_graph_300_sin_clausula": sin_acotado,
                "por_que": "las aristas llegan a 750 y el limit=300 no las acota",
            },
            "ablacion_exigir_crecimiento_previo": {
                "serie": {"SINTETICA": serie_constante},
                "con_clausula": con_crec,
                "sin_clausula": sin_crec,
                "por_que": "un componente que nunca creció no demuestra ningún techo",
            },
            "ablacion_exigir_maximo": {
                "serie": {"SINTETICA": serie_meseta_baja},
                "con_clausula": con_max,
                "sin_clausula": sin_max,
                "por_que": "meseta en 13 con máximo 63: es una pausa, no un techo",
            },
        },
    )
    return c9a, c9b


# ---------------------------------------------------------------------------
# C10 — el hash del SISTEMA MEDIDO cubre lo que dice cubrir
# ---------------------------------------------------------------------------

def c10_hash_del_sistema() -> dict:
    """Muta ``static/js/graph.js`` en disco y exige que el hash se mueva.

    El fichero se restaura SIEMPRE (bytes originales, verificados) y el hash
    debe volver exactamente al de partida.
    """
    objetivo = RAIZ / "viewer" / "app" / "static" / "js" / "graph.js"
    ficheros = ficheros_del_sistema_medido()
    por_extension: dict[str, int] = {}
    for p in ficheros:
        por_extension[p.suffix] = por_extension.get(p.suffix, 0) + 1

    # Lo que cubría v2.0, para poder nombrar lo que se le escapaba.
    fuera_de_v20 = [str(p.relative_to(RAIZ)) for p in ficheros
                    if p.suffix not in (".py", ".html")]

    antes = sha_del_sistema_medido()
    original = objetivo.read_bytes()
    try:
        objetivo.write_bytes(original + b"\n// mutacion de calibracion\n")
        mutado = sha_del_sistema_medido()
    finally:
        objetivo.write_bytes(original)
    restaurado = sha_del_sistema_medido()

    return _ok(
        "C10 HASH DEL SISTEMA: mutar static/js/graph.js invalida la calibración",
        objetivo.exists()
        and objetivo.read_bytes() == original
        and mutado != antes
        and restaurado == antes
        and len(fuera_de_v20) > 0,
        {
            "fichero_mutado": str(objetivo.relative_to(RAIZ)),
            "sha_antes": antes[:16],
            "sha_con_mutacion": mutado[:16],
            "sha_tras_revertir": restaurado[:16],
            "el_hash_se_movio": mutado != antes,
            "ficheros_cubiertos": len(ficheros),
            "por_extension": por_extension,
            "invisibles_para_v20": fuera_de_v20,
            "nota": (
                "Con el filtro de v2.0 (`suffix in ('.py','.html')`) esta misma "
                "mutación dejaba el hash INTACTO: graph.js —el motor de pintado "
                "del grafo, objeto de este carril— no entraba en la huella."
            ),
        },
    )


# ---------------------------------------------------------------------------
# C11 — N+1 CON TOPE: la serie plana que el detector firmaba como "constante"
# ---------------------------------------------------------------------------

TOPE_INYECTADO = 40


def c11_n_mas_1_con_tope(cliente, contador, grafo, ids: list[str]) -> dict:
    """Inyecta ``min(2*g+3, TOPE)`` y exige que el detector NO diga "constante".

    Es el hueco que quedaba: en cuanto todos los puntos superan el tope, la
    serie de llamadas es plana, ``pendiente = 0.0`` y v2.0 dictaminaba
    "constante" para un endpoint que hace TOPE consultas por petición. El tope
    real de este control es 40, no 300, para que el grafo de calibración
    (grados 120) tenga puntos por encima sin necesitar hubs gigantes.
    """
    from app.providers.mock_provider import MockGraphProvider

    # El defecto sólo se manifiesta cuando TODOS los puntos superan el tope: es
    # entonces cuando la serie de llamadas se aplana. Con un nodo por debajo,
    # la serie todavía sube y el detector acierta por accidente.
    todos = {nid: _grado(grafo, nid) for nid in ids}
    grados = {nid: g for nid, g in todos.items() if g > TOPE_INYECTADO}
    if len(grados) < detector.PUNTOS_MINIMOS:
        return _ok(
            "C11 N+1 CON TOPE: serie plana por saturación NO se firma como 'constante'",
            False,
            {"error": f"hacen falta {detector.PUNTOS_MINIMOS} nodos de grado > "
                      f"{TOPE_INYECTADO}; hay {len(grados)}", "grados": todos},
        )
    ids = list(grados)
    original = MockGraphProvider.relations_for_entity

    def con_tope(self, eid):
        sal, ent = original(self, eid)
        # Recorta la CARGA devuelta: el proveedor deja de crecer al llegar al
        # tope, exactamente como haría un `limit` en la consulta.
        return sal[:TOPE_INYECTADO], ent[:max(0, TOPE_INYECTADO - len(sal))]

    def medir():
        llamadas, carga = {}, {}
        for nid in ids:
            g = grados[nid]
            resp = cliente.get(f"/api/entities/{nid}")
            llamadas[g] = arnes.llamadas_de(cliente, contador, f"/api/entities/{nid}")
            carga[g] = arnes.elementos_en(resp)
        return llamadas, carga

    with parche(MockGraphProvider, "relations_for_entity", con_tope):
        llamadas, carga = medir()
        # (a) el detector SIN la señal de carga: es lo que hacía v2.0.
        sin_señal = detector.dictaminar("grado", "api_entity_detalle", llamadas)
        # (b) el detector CON la señal de carga: v2.1.
        con_señal = detector.dictaminar("grado", "api_entity_detalle", llamadas, carga=carga)
        # (c) el guardia de MAGNITUD, que es el que pone el número encima de la
        #     mesa aunque el crecimiento sea 0.
        techo = {"api_entity_detalle": {"llamadas_fuente": 10.0}}
        medido_alto = {"api_entity_detalle": {"llamadas_fuente": float(max(llamadas.values()))}}
        rojo_presupuesto = detector.comprobar_presupuestos(medido_alto, techo)

    # -- revertido: el defecto real vuelve a verse como N+1 --------------------
    llamadas_reales, carga_real = medir()
    tras_revertir = detector.dictaminar(
        "grado", "api_entity_detalle", llamadas_reales, carga=carga_real)

    plana = len(set(llamadas.values())) == 1

    return _ok(
        "C11 N+1 CON TOPE: serie plana por saturación NO se firma como 'constante'",
        plana
        and sin_señal.veredicto == "constante" and sin_señal.pendiente == 0.0
        and con_señal.veredicto == "no concluyente" and con_señal.carga_saturada is True
        and len(rojo_presupuesto) == 1
        and tras_revertir.veredicto == "N+1",
        {
            "tope_inyectado": TOPE_INYECTADO,
            "llamadas_con_tope": {str(k): v for k, v in sorted(llamadas.items())},
            "carga_con_tope": {str(k): v for k, v in sorted(carga.items())},
            "serie_de_llamadas_es_plana": plana,
            "v20_sin_señal_de_carga": sin_señal.como_dict(),
            "v21_con_señal_de_carga": con_señal.como_dict(),
            "presupuesto_absoluto_rojo": [i.como_dict() for i in rojo_presupuesto],
            "tras_revertir": tras_revertir.como_dict(),
            "nota": (
                "Sin la señal de carga el veredicto es 'constante, pendiente 0.0' "
                f"para un endpoint que hace {max(llamadas.values())} consultas por "
                "petición. El crecimiento por sí solo no basta: hace falta también "
                "un guardia de MAGNITUD, que en v2.0 no se invocaba desde "
                "run_bench.py."
            ),
        },
    )


# ---------------------------------------------------------------------------

def main() -> int:
    tmp = Path("/tmp/s9k-perf-v2-calibracion")
    tmp.mkdir(parents=True, exist_ok=True)

    print("== Calibración del instrumento (antes de medir nada) ==", flush=True)

    pruebas = [c0_el_juez_sabe_fallar()]

    p_hub = Parametros(n_entities=250, hubs=3, grado_hub=120)
    cliente_h, contador_h, app_h, entrada_h = arnes.montar(p_hub)
    grafo_hub = json.loads(entrada_h.ruta.read_text(encoding="utf-8"))
    ids_grado = ["p_0000200", "p_0000002", "p_0000001", "p_0000000"]
    try:
        pruebas.append(c1_eje_pagina(cliente_h, contador_h))
        pruebas.append(c7_n_mas_1_parciales(cliente_h, contador_h))
        pruebas.append(c3_eje_grado(cliente_h, contador_h, grafo_hub, ids_grado))
        pruebas.append(c11_n_mas_1_con_tope(cliente_h, contador_h, grafo_hub, ids_grado))
        pruebas.append(c5_presupuesto(cliente_h, contador_h))
        pruebas.append(c6_estadistica(cliente_h))
    finally:
        app_h.dependency_overrides.clear()

    c2, c1b = c2_eje_dataset_y_c1b()
    pruebas.append(c2)
    pruebas.append(c1b)
    pruebas.append(c4_cache(tmp))
    pruebas.append(c8_driver_falso())
    c9a, c9b = c9_saturacion()
    pruebas.append(c9a)
    pruebas.append(c9b)
    pruebas.append(c10_hash_del_sistema())

    calibrado = all(p["superada"] for p in pruebas)
    informe = {
        "generado": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "entorno": arnes.entorno(),
        "sha_del_instrumento": sha_del_instrumento(),
        "modulos_cubiertos_por_el_hash": list(MODULOS_DEL_ARNES),
        "sha_del_sistema_medido": sha_del_sistema_medido(),
        "criterio_del_detector": {
            "regla": "crecimiento total > 0 y monótono => N+1; plano => constante; "
                     "no monótono => no concluyente",
            "crecimiento_minimo": detector.CRECIMIENTO_MINIMO,
            "puntos_minimos": detector.PUNTOS_MINIMOS,
        },
        "pruebas": pruebas,
        "instrumento_calibrado": calibrado,
    }
    salida = AQUI / "resultados" / "calibracion.json"
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps(informe, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nInstrumento calibrado: {'SÍ' if calibrado else 'NO'}  ->  {salida}")
    return 0 if calibrado else 1


if __name__ == "__main__":
    raise SystemExit(main())
