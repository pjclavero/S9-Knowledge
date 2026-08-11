"""CALIBRACIÓN DEL INSTRUMENTO. Se ejecuta ANTES de medir nada.

Regla del operador que este guion implementa al pie de la letra:

    «Una afirmación no constituye evidencia porque exista un test verde. La
    evidencia aparece cuando: sabes qué comportamiento afirma; calibras el
    mecanismo que lo mide; introduces una violación; el sistema se pone rojo;
    reviertes; vuelve a verde.»

Un instrumento que nunca se ha visto rojo no mide nada. Aquí se le enseña rojo
y verde a cada mecanismo, y se deja constancia en
``resultados/calibracion.json``. ``run_bench.py`` se niega a emitir cifras si
ese fichero no existe, no está calibrado, o corresponde a otra versión del
instrumento (se compara el hash de los módulos del arnés).

Contenido
---------
  C1  eje PÁGINA   — N+1 por elemento devuelto.      inyectar -> rojo, revertir -> verde
  C1b ceguera de v1 — el eje DATASET no ve ese N+1.  se deja registrada
  C2  eje DATASET  — N+1 por entidad del grafo.      inyectar -> rojo, revertir -> verde
  C3  eje GRADO    — N+1 por relación del nodo.      real -> rojo, control -> verde, real -> rojo
  C4  CACHÉ        — datos cambiados -> invalidada;  iguales -> reutilizada
  C5  PRESUPUESTO  — regresión inyectada -> techo roto, revertir -> cumple
  C6  ESTADÍSTICA  — regresión de latencia -> "peor"; ruido puro -> "indistinguible"

Nada queda aplicado: todos los parches viven en memoria y se revierten en el
mismo proceso.
"""
from __future__ import annotations

import hashlib
import json
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

MODULOS_DEL_ARNES = ("arnes.py", "cache.py", "dataset.py", "detector.py",
                     "estadistica.py", "instrumentation.py")


def sha_del_instrumento() -> str:
    h = hashlib.sha256()
    for nombre in MODULOS_DEL_ARNES:
        h.update((AQUI / nombre).read_bytes())
    return h.hexdigest()


def _grado(grafo: dict, nid: str) -> int:
    return sum(1 for e in grafo["edges"] if e["from"] == nid or e["to"] == nid)


def _ok(nombre: str, condicion: bool, detalle: dict) -> dict:
    print(f"  [{'OK ' if condicion else 'FALLO'}] {nombre}", flush=True)
    return {"nombre": nombre, "superada": bool(condicion), **detalle}


# ---------------------------------------------------------------------------
# C1 / C1b — eje PÁGINA, y la ceguera del eje DATASET ante ese mismo N+1
# ---------------------------------------------------------------------------

PAGINAS = (10, 100)


def _medidas_pagina(cliente, contador) -> dict[int, int]:
    return {
        k: arnes.llamadas_de(cliente, contador, f"/api/entities?offset=0&limit={k}")
        for k in PAGINAS
    }


def c1_eje_pagina(cliente, contador) -> tuple[dict, dict]:
    from app.authz.filtered_provider import PolicyFilteredProvider

    original = PolicyFilteredProvider.list_entities

    def con_n_mas_1_por_pagina(self, *a, **kw):
        """El listado, más una consulta por elemento DEVUELTO."""
        page, total = original(self, *a, **kw)
        for item in page:
            self._base.entity(item.get("id"))
        return page, total

    verde_antes = detector.dictaminar("pagina", "api_entities", _medidas_pagina(cliente, contador))

    PolicyFilteredProvider.list_entities = con_n_mas_1_por_pagina
    try:
        rojo = detector.dictaminar("pagina", "api_entities", _medidas_pagina(cliente, contador))
        # C1b: el ÚNICO eje que tenía v1 —el del dataset— no ve este N+1, porque
        # con página fija el número de llamadas no depende del tamaño del grafo.
        llamadas_pagina_fija_con_defecto = arnes.llamadas_de(
            cliente, contador, "/api/entities?offset=0&limit=50")
    finally:
        PolicyFilteredProvider.list_entities = original

    verde_despues = detector.dictaminar("pagina", "api_entities", _medidas_pagina(cliente, contador))

    c1 = _ok(
        "C1 eje PÁGINA: N+1 por elemento devuelto",
        verde_antes.veredicto == "constante"
        and rojo.veredicto == "N+1"
        and verde_despues.veredicto == "constante"
        and verde_despues.como_dict() == verde_antes.como_dict(),
        {
            "verde_antes": verde_antes.como_dict(),
            "rojo_con_violacion": rojo.como_dict(),
            "verde_tras_revertir": verde_despues.como_dict(),
        },
    )
    c1b = {
        "nombre": "C1b ceguera del eje DATASET ante el N+1 por página (defecto de v1)",
        "llamadas_con_defecto_a_pagina_fija": llamadas_pagina_fija_con_defecto,
        "nota": (
            "Con limit=50 el defecto añade 50 llamadas SEA CUAL SEA el tamaño del "
            "grafo: el eje del dataset da pendiente 0 y lo declara 'constante'. "
            "Por eso el detector de v1 fallaba su propia calibración."
        ),
    }
    return c1, c1b


# ---------------------------------------------------------------------------
# C2 — eje DATASET
# ---------------------------------------------------------------------------

def c2_eje_dataset(clientes: dict[int, tuple]) -> dict:
    from app.authz.filtered_provider import PolicyFilteredProvider

    original = PolicyFilteredProvider.list_entities
    url = "/api/entities?offset=0&limit=50"

    def con_n_mas_1_por_dataset(self, *a, **kw):
        """El listado, más una consulta por entidad DEL GRAFO (no de la página)."""
        page, total = original(self, *a, **kw)
        for i in range(total):
            self._base.entity(f"p_{i:07d}")
        return page, total

    def medir() -> dict[int, int]:
        return {n: arnes.llamadas_de(c, cont, url) for n, (c, cont) in clientes.items()}

    verde_antes = detector.dictaminar("dataset", "api_entities", medir())
    PolicyFilteredProvider.list_entities = con_n_mas_1_por_dataset
    try:
        rojo = detector.dictaminar("dataset", "api_entities", medir())
    finally:
        PolicyFilteredProvider.list_entities = original
    verde_despues = detector.dictaminar("dataset", "api_entities", medir())

    return _ok(
        "C2 eje DATASET: N+1 por entidad del grafo",
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
# C3 — eje GRADO (hubs)
# ---------------------------------------------------------------------------

def c3_eje_grado(cliente, contador, grafo, id_bajo: str, id_hub: str) -> dict:
    from app.providers.mock_provider import MockGraphProvider

    g_bajo, g_hub = _grado(grafo, id_bajo), _grado(grafo, id_hub)

    def medir() -> dict[int, int]:
        return {
            g_bajo: arnes.llamadas_de(cliente, contador, f"/api/entities/{id_bajo}"),
            g_hub: arnes.llamadas_de(cliente, contador, f"/api/entities/{id_hub}"),
        }

    # Estado real del sistema: la ficha de entidad pide una entidad por arista.
    rojo_real = detector.dictaminar("grado", "api_entity_detalle", medir())

    # CONTROL VERDE (no es una propuesta de arreglo, es un control de calibración):
    # si el nodo no tuviera relaciones que resolver, el coste no dependería del
    # grado. Debe verse VERDE.
    original = MockGraphProvider.relations_for_entity
    MockGraphProvider.relations_for_entity = lambda self, eid: ([], [])
    try:
        verde_control = detector.dictaminar("grado", "api_entity_detalle", medir())
    finally:
        MockGraphProvider.relations_for_entity = original
    rojo_de_nuevo = detector.dictaminar("grado", "api_entity_detalle", medir())

    return _ok(
        "C3 eje GRADO: N+1 por relación del nodo (defecto REAL, hubs)",
        rojo_real.veredicto == "N+1"
        and verde_control.veredicto == "constante"
        and rojo_de_nuevo.como_dict() == rojo_real.como_dict(),
        {
            "grado_nodo_bajo": g_bajo,
            "grado_hub": g_hub,
            "rojo_codigo_real": rojo_real.como_dict(),
            "verde_control_sin_relaciones": verde_control.como_dict(),
            "rojo_tras_revertir": rojo_de_nuevo.como_dict(),
        },
    )


# ---------------------------------------------------------------------------
# C4 — CACHÉ CON HUELLA
# ---------------------------------------------------------------------------

def c4_cache(tmp: Path) -> dict:
    import shutil

    raiz = tmp / "cache_calibracion"
    shutil.rmtree(raiz, ignore_errors=True)  # se parte siempre de caché vacía
    p = Parametros(n_entities=20)

    e1 = cache.obtener(p, raiz)
    e2 = cache.obtener(p, raiz)  # sin tocar nada: debe REUTILIZAR

    # Ahora se "estropea" el generador igual que ocurrió de verdad en v1: un
    # nivel de visibilidad fuera del vocabulario del motor. Se regenera el
    # fichero con el generador malo.
    buenas = list(dataset.VISIBILITIES)
    dataset.VISIBILITIES[:] = ["public", "narrator", "secret", "reference"]

    # Segunda línea de defensa, independiente de la caché: el generador se niega
    # a escribir un nivel fuera del vocabulario del motor. Se comprueba que SÍ
    # salta, y luego se desactiva para poder fabricar el fichero rancio que
    # necesita esta calibración.
    guardia_salto = False
    try:
        dataset.verificar_visibilidad_valida()
    except ValueError:
        guardia_salto = True
    verificar_original = dataset.verificar_visibilidad_valida
    dataset.verificar_visibilidad_valida = lambda: None
    try:
        e_malo = cache.obtener(p, raiz)
        contenido_malo = e1.ruta.read_text(encoding="utf-8")
    finally:
        dataset.verificar_visibilidad_valida = verificar_original
    dataset.VISIBILITIES[:] = buenas  # el generador queda arreglado

    # Con la regla de v1 (`if not ruta.exists()`) el fichero MALO se habría
    # reutilizado tal cual: el defecto vuelve sin avisar.
    regla_v1_habria_reutilizado = e1.ruta.exists()
    tenia_el_defecto = '"visibility": "public"' in contenido_malo

    e3 = cache.obtener(p, raiz)  # regla de v2: la huella no cuadra -> regenerar
    contenido_bueno = e1.ruta.read_text(encoding="utf-8")

    # Y si alguien borra el sidecar, no se fía: regenera.
    (e1.ruta.with_suffix(e1.ruta.suffix + ".huella.json")).unlink()
    e4 = cache.obtener(p, raiz)
    e5 = cache.obtener(p, raiz)

    return _ok(
        "C4 CACHÉ: la huella invalida sola cuando cambian datos o generador",
        e1.estado == "generado"
        and e2.estado == "reutilizado"
        and e_malo.estado == "regenerado_por_huella"
        and tenia_el_defecto
        and regla_v1_habria_reutilizado
        and e3.estado == "regenerado_por_huella"
        and '"visibility": "public"' not in contenido_bueno
        and e4.estado == "regenerado_sin_huella"
        and e5.estado == "reutilizado"
        and guardia_salto,
        {
            "estados": [e1.estado, e2.estado, e_malo.estado, e3.estado, e4.estado, e5.estado],
            "guardia_de_vocabulario_tambien_salta": guardia_salto,
            "huella_con_generador_sano": e3.huella,
            "huella_con_generador_roto": e_malo.huella,
            "el_fichero_cacheado_tenia_el_defecto": tenia_el_defecto,
            "la_regla_de_v1_lo_habria_reutilizado": regla_v1_habria_reutilizado,
            "tras_v2_el_defecto_desaparece": '"visibility": "public"' not in contenido_bueno,
        },
    )


# ---------------------------------------------------------------------------
# C5 — PRESUPUESTOS: una regresión inyectada rompe el techo
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
        for item in page[:5]:  # regresión pequeña a propósito: 5 consultas extra
            self._base.entity(item.get("id"))
        return page, total

    PolicyFilteredProvider.list_entities = con_regresion
    try:
        rojo = detector.comprobar_presupuestos(medido(), presupuestos)
    finally:
        PolicyFilteredProvider.list_entities = original
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
# C6 — ESTADÍSTICA: ¿distingue un efecto real del ruido de medida?
# ---------------------------------------------------------------------------

def c6_estadistica(cliente) -> dict:
    from app.authz.filtered_provider import PolicyFilteredProvider

    url = "/api/entities?offset=0&limit=50"
    reps = 40
    base = estadistica.resumir(arnes.tiempos_de(cliente, url, reps))
    repeticion = estadistica.resumir(arnes.tiempos_de(cliente, url, reps))
    ruido = estadistica.comparar(base, repeticion)

    original = PolicyFilteredProvider.list_entities
    RETARDO_S = 0.005  # 5 ms: regresión de latencia deliberada

    def con_retardo(self, *a, **kw):
        time.sleep(RETARDO_S)
        return original(self, *a, **kw)

    PolicyFilteredProvider.list_entities = con_retardo
    try:
        lenta = estadistica.resumir(arnes.tiempos_de(cliente, url, reps))
    finally:
        PolicyFilteredProvider.list_entities = original
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

def main() -> int:
    tmp = Path("/tmp/s9k-perf-v2-calibracion")
    tmp.mkdir(parents=True, exist_ok=True)

    print("== Calibración del instrumento (antes de medir nada) ==", flush=True)

    # Cliente de trabajo: 100 entidades, con hubs para el eje del grado.
    p_hub = Parametros(n_entities=250, hubs=3, grado_hub=120)
    cliente_h, contador_h, app_h, entrada_h = arnes.montar(p_hub)
    grafo_hub = json.loads(entrada_h.ruta.read_text(encoding="utf-8"))
    id_hub = dataset.ids_hub(p_hub)[0]
    id_bajo = "p_0000200"

    pruebas = []
    c1, c1b = c1_eje_pagina(cliente_h, contador_h)
    pruebas.append(c1)
    pruebas.append(c3_eje_grado(cliente_h, contador_h, grafo_hub, id_bajo, id_hub))
    pruebas.append(c5_presupuesto(cliente_h, contador_h))
    pruebas.append(c6_estadistica(cliente_h))
    app_h.dependency_overrides.clear()

    # Eje dataset: hacen falta dos tamaños.
    clientes = {}
    apps = []
    for n in (10, 500):
        c, cont, a, _ = arnes.montar(Parametros(n_entities=n))
        clientes[n] = (c, cont)
        apps.append(a)
    pruebas.append(c2_eje_dataset(clientes))
    for a in apps:
        a.dependency_overrides.clear()

    pruebas.append(c4_cache(tmp))

    calibrado = all(p["superada"] for p in pruebas)
    informe = {
        "generado": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "entorno": arnes.entorno(),
        "sha_del_instrumento": sha_del_instrumento(),
        "umbral_por_elemento": detector.UMBRAL_POR_ELEMENTO,
        "pruebas": pruebas,
        "ceguera_documentada_de_v1": c1b,
        "instrumento_calibrado": calibrado,
    }
    salida = AQUI / "resultados" / "calibracion.json"
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps(informe, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nInstrumento calibrado: {'SÍ' if calibrado else 'NO'}  ->  {salida}")
    return 0 if calibrado else 1


if __name__ == "__main__":
    raise SystemExit(main())
