"""M5b-3 -- la migracion estampa lo que falta sin ampliar nada."""
import json
from pathlib import Path

import pytest

from app.policies.models import DENY, NARRATOR, PLAYER, REFERENCE, SECRET
from app.policies.visibility_migration import (
    FALLBACK,
    RESTRICTIVENESS,
    migrate_dataset,
    most_restrictive,
    normalize_level,
    stamp_edge,
    stamp_node,
)

MUESTRA = Path(__file__).resolve().parents[1] / "examples" / "sample_graph.json"


# --- niveles ---------------------------------------------------------------
@pytest.mark.parametrize("bueno", [PLAYER, NARRATOR, SECRET, REFERENCE, DENY])
def test_los_niveles_del_vocabulario_se_reconocen(bueno):
    assert normalize_level(bueno) == bueno
    assert normalize_level(f"  {bueno.upper()}  ") == bueno


@pytest.mark.parametrize("malo", [None, "", "   ", "publico", 3, [], {}, True])
def test_lo_que_no_es_un_nivel_no_se_reconoce(malo):
    assert normalize_level(malo) is None


def test_el_orden_de_restriccion_cubre_todo_el_vocabulario():
    """Si alguien anade un nivel al contrato y no aqui, la migracion mentiria."""
    from app.policies.models import ALL_STORED_LEVELS

    assert set(RESTRICTIVENESS) == set(ALL_STORED_LEVELS)


# --- herencia --------------------------------------------------------------
def test_gana_el_extremo_mas_restrictivo():
    assert most_restrictive([PLAYER, SECRET]) == SECRET
    assert most_restrictive([SECRET, PLAYER]) == SECRET
    assert most_restrictive([PLAYER, REFERENCE]) == REFERENCE
    assert most_restrictive([NARRATOR, DENY]) == DENY


def test_dos_extremos_visibles_dan_una_arista_visible():
    assert most_restrictive([PLAYER, PLAYER]) == PLAYER


def test_un_extremo_ilegible_no_se_ignora():
    """Ignorarlo haria la arista mas visible que el nodo que toca."""
    assert most_restrictive([PLAYER, None]) == FALLBACK
    assert most_restrictive([PLAYER, "publico"]) == FALLBACK


def test_sin_extremos_cae_al_defecto_restrictivo():
    assert most_restrictive([]) == FALLBACK


# --- estampado -------------------------------------------------------------
def test_un_nodo_sin_visibilidad_pasa_a_secret():
    nodo, cambiado = stamp_node({"id": "n1"})
    assert cambiado and nodo["visibility"] == SECRET


def test_la_migracion_nunca_amplia_lo_ya_declarado():
    """Aunque `secret` sea mas restrictivo de lo que este nodo merece."""
    nodo, cambiado = stamp_node({"id": "n1", "visibility": PLAYER})
    assert not cambiado and nodo["visibility"] == PLAYER


def test_una_arista_hereda_del_extremo_mas_restrictivo():
    nodos = {"a": {"visibility": PLAYER}, "b": {"visibility": SECRET}}
    arista, cambiado = stamp_edge({"from": "a", "to": "b"}, nodos)
    assert cambiado and arista["visibility"] == SECRET


def test_una_arista_rota_no_se_vuelve_visible():
    """Un extremo inexistente es una arista rota, no una arista publica."""
    arista, _ = stamp_edge({"from": "a", "to": "fantasma"}, {"a": {"visibility": PLAYER}})
    assert arista["visibility"] == FALLBACK


def test_stamp_no_muta_la_entrada():
    original = {"id": "n1"}
    stamp_node(original)
    assert original == {"id": "n1"}


# --- conjunto completo ------------------------------------------------------
def test_migrar_es_idempotente():
    doc = {"nodes": [{"id": "a"}], "edges": [{"from": "a", "to": "a"}]}
    una, r1 = migrate_dataset(doc)
    dos, r2 = migrate_dataset(una)
    assert una == dos
    assert r1["nodos_estampados"] == 1 and r2["nodos_estampados"] == 0
    assert r1["aristas_estampadas"] == 1 and r2["aristas_estampadas"] == 0


def test_el_recuento_refleja_lo_que_de_verdad_se_toco():
    doc = {
        "nodes": [{"id": "a", "visibility": PLAYER}, {"id": "b"}],
        "edges": [{"from": "a", "to": "b"}],
    }
    _, recuento = migrate_dataset(doc)
    assert recuento == {
        "nodos_totales": 2,
        "nodos_estampados": 1,
        "aristas_totales": 1,
        "aristas_estampadas": 1,
    }


def test_tras_migrar_no_queda_nada_sin_nivel_valido():
    doc = {
        "nodes": [{"id": "a"}, {"id": "b", "visibility": "publico"}],
        "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "z"}],
    }
    migrado, _ = migrate_dataset(doc)
    for item in migrado["nodes"] + migrado["edges"]:
        assert normalize_level(item.get("visibility")) is not None


# --- el conjunto de muestra ya migrado -------------------------------------
def test_la_muestra_del_repositorio_esta_completamente_estampada():
    """Si vuelve a faltar visibilidad en la muestra, el cierre la dejaria muda."""
    doc = json.loads(MUESTRA.read_text(encoding="utf-8"))
    for item in doc["nodes"] + doc["edges"]:
        assert normalize_level(item.get("visibility")) is not None, item


def test_migrar_la_muestra_ya_no_cambia_nada():
    doc = json.loads(MUESTRA.read_text(encoding="utf-8"))
    _, recuento = migrate_dataset(doc)
    assert recuento["nodos_estampados"] == 0
    assert recuento["aristas_estampadas"] == 0
