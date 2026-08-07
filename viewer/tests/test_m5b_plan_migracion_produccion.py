"""El PLAN de migracion de produccion, probado en seco antes de tocar el grafo.

`scripts/m5b/migrar_visibilidad.py` es el unico codigo de esta entrega que
escribe en produccion. Su parte peligrosa no es hablar con Neo4j --eso se ve
fallar-- sino DECIDIR mal en silencio: estampar de mas, ampliar algo ya
declarado, o dejar una arista mas visible que el nodo que toca.

Todo eso es logica pura sobre un estado leido, asi que se prueba sin base de
datos, con estados sinteticos que incluyen los casos que el grafo real tiene y
los que ojala no tenga.
"""
import importlib.util
import json
from pathlib import Path

import pytest

RUTA = Path(__file__).resolve().parents[2] / "scripts" / "m5b" / "migrar_visibilidad.py"

spec = importlib.util.spec_from_file_location("m5b_migrar_visibilidad", RUTA)
mig = importlib.util.module_from_spec(spec)
import sys  # noqa: E402

sys.modules[spec.name] = mig
spec.loader.exec_module(mig)


def estado(nodos, relaciones):
    return {
        "nodos": [{"id": i, "etiqueta": "N", "actual": v} for i, v in nodos],
        "relaciones": [
            {"id": i, "tipo": "R", "actual": v, "origen": a, "destino": b}
            for i, v, a, b in relaciones
        ],
    }


# --- lo que NO debe tocar ---------------------------------------------------
def test_no_toca_lo_que_ya_tiene_nivel_valido():
    """El alcance autorizado es estampar lo que falta, no revisar lo que hay."""
    plan = mig.construir_plan(estado([("n1", "player"), ("n2", "secret")], []))
    assert plan["acciones"] == []
    assert plan["errores"] == []


def test_no_recorta_un_nivel_permisivo_ya_declarado():
    """Aunque `player` sea mas abierto de lo que la herencia daria."""
    plan = mig.construir_plan(
        estado([("n1", "secret"), ("n2", "secret")], [("r1", "player", "secret", "secret")])
    )
    assert plan["acciones"] == []


# --- lo que SI debe tocar ---------------------------------------------------
def test_un_nodo_sin_nivel_va_a_secret_por_fallback():
    plan = mig.construir_plan(estado([("n1", "")], []))
    (a,) = plan["acciones"]
    assert (a["clase"], a["despues"], a["fuente"]) == ("nodo", "secret", "migration_fail_closed")


def test_una_relacion_hereda_el_extremo_mas_restrictivo():
    plan = mig.construir_plan(
        estado([("a", "player"), ("b", "narrator")], [("r1", "", "player", "narrator")])
    )
    (a,) = plan["acciones"]
    assert a["despues"] == "narrator"
    assert a["fuente"] == "migration_inherited"


def test_dos_extremos_visibles_dan_una_relacion_visible():
    """Sin esto, un migrador que pusiera `secret` a todo pasaria los demas tests."""
    plan = mig.construir_plan(estado([("a", "player"), ("b", "player")],
                                     [("r1", "", "player", "player")]))
    assert plan["acciones"][0]["despues"] == "player"


def test_un_extremo_ilegible_no_produce_una_relacion_abierta():
    plan = mig.construir_plan(estado([("a", "player")], [("r1", "", "player", "")]))
    (a,) = plan["acciones"]
    assert a["despues"] == "secret"
    assert a["motivo"] == "extremo_ilegible_o_ausente_fallback"


# --- invariante de monotonia ------------------------------------------------
@pytest.mark.parametrize("va", mig.NIVELES_INFORME)
@pytest.mark.parametrize("vb", mig.NIVELES_INFORME)
def test_el_plan_nunca_deja_una_relacion_menos_restringida_que_sus_extremos(va, vb):
    plan = mig.construir_plan(estado([("a", va), ("b", vb)], [("r1", "", va, vb)]))
    nivel = plan["acciones"][0]["despues"]
    assert mig.RESTRICTIVENESS[nivel] >= mig.RESTRICTIVENESS[va]
    assert mig.RESTRICTIVENESS[nivel] >= mig.RESTRICTIVENESS[vb]
    assert plan["errores"] == []


def test_una_violacion_de_monotonia_preexistente_se_reporta_como_error():
    """Un `player` declarado sobre una arista que toca un secreto es un error
    que la migracion DEBE ensenar, no arreglar por su cuenta: recortar un nivel
    ya declarado esta fuera del alcance autorizado."""
    plan = mig.construir_plan(
        estado([("a", "player"), ("b", "secret")], [("r1", "player", "player", "secret")])
    )
    assert plan["acciones"] == []
    assert len(plan["errores"]) == 1
    assert "monotonia_violada" in plan["errores"][0]["motivo"]


# --- firma y contabilidad ---------------------------------------------------
def test_el_hash_cambia_si_cambia_una_sola_decision():
    base = mig.construir_plan(estado([("n1", "")], []))
    otro = mig.construir_plan(estado([("n1", ""), ("n2", "")], []))
    assert mig.plan_sha(base) != mig.plan_sha(otro)


def test_el_hash_es_estable_para_el_mismo_estado():
    e = estado([("n1", ""), ("n2", "player")], [("r1", "", "", "player")])
    assert mig.plan_sha(mig.construir_plan(e)) == mig.plan_sha(mig.construir_plan(e))


def test_el_total_de_objetos_es_el_que_se_va_a_verificar_despues():
    e = estado([("n%d" % i, "") for i in range(199)],
               [("r%d" % i, "", "", "") for i in range(140)])
    plan = mig.construir_plan(e)
    assert plan["totales"] == {"nodos": 199, "relaciones": 140, "objetos": 339}
    assert len(plan["acciones"]) == 339  # nada queda sin decidir


def test_el_informe_no_deja_filas_desconocidas():
    e = estado([("n1", ""), ("n2", "player")], [("r1", "", "", "player")])
    texto = mig.informe(e, mig.construir_plan(e))
    assert "| Nodos | 2 |" in texto
    assert "Errores           : 0" in texto


# --- sentencias de escritura ------------------------------------------------
def test_las_sentencias_solo_escriben_los_dos_campos_de_visibilidad():
    """El limite duro del alcance autorizado, comprobado sobre el Cypher real."""
    e = estado([("n1", ""), ("n2", "")], [("r1", "", "", "")])
    for s in mig.sentencias_apply(mig.construir_plan(e)):
        cuerpo = s.upper()
        assert "DELETE" not in cuerpo and "REMOVE" not in cuerpo
        assert "MERGE" not in cuerpo and "CREATE" not in cuerpo
        # Exactamente dos asignaciones, y ambas de visibilidad.
        asignaciones = [x for x in s.split("SET")[1].split("RETURN")[0].split(",\n")]
        assert len(asignaciones) == 2
        assert all("visibility" in a for a in asignaciones)


def test_las_sentencias_apuntan_solo_a_los_ids_del_plan():
    e = estado([("n1", ""), ("n2", "player")], [])
    (s,) = mig.sentencias_apply(mig.construir_plan(e))
    assert '"n1"' in s and '"n2"' not in s


def test_sin_nada_que_hacer_no_se_genera_ninguna_escritura():
    plan = mig.construir_plan(estado([("n1", "player")], []))
    assert mig.sentencias_apply(plan) == []
