# -*- coding: utf-8 -*-
"""Procedencia navegable: lo que se puede comprobar SIN Neo4j.

El recorrido de verdad se demuestra contra Neo4j real
(`artifacts/equipo1-procedencia/demostracion_procedencia_navegable.py`, y la
suite `test_knowledge_v3_e2e_neo4j_real`). Aqui viven las propiedades que no
necesitan contenedor y que, por eso mismo, corren SIEMPRE:

* la proyeccion de un documento de contrato a propiedades planas no inventa
  campos ni se traga en silencio los que Neo4j no admite;
* las consultas construidas pasan la guardia anti-destructiva (`Query` la
  aplica en su `__post_init__`): ni un `MERGE`, ni un `DELETE`, ni un
  `SET n = $props` en todo el modulo;
* el volcado es idempotente: repetido sobre el mismo estado no CREA nada;
* la identidad que viaja en las aristas es la durable del contrato, nunca un
  `elementId`.

El doble de driver es de MENTIRA pero no es complaciente: mantiene un estado
consultable y responde a las consultas de existencia con lo que de verdad hay,
de modo que "no duplica" se OBSERVA (segundo volcado con `total_created == 0`
y estado identico), no se presume.
"""
from __future__ import annotations

import re

import pytest

from knowledge_v3.writer import provenance as P
from knowledge_v3.writer.errors import WriterAbort

WS = "ws-procedencia"

ASSET = {
    "contract_version": "1.0.0",
    "workspace": WS,
    "source_asset_id": "sa-1",
    "source_hash": {"algorithm": "sha256", "value": "abc"},
    "provider_trace": [{"provider": "local"}],
    "produced_by_step": "normalize",
    "asset_id": "sa-1",
    "collection_id": "collection:pruebas",
    "game_profile": "generic",
    "source_kind": "MARKDOWN",
    "mime_type": "text/markdown",
    "content_hash": {"algorithm": "sha256", "value": "abc"},
    "byte_size": 42,
    "original_name": "nota.md",
    "original_location": "memoria",
    "created_at": "2026-01-01T00:00:00Z",
    "ingested_at": "2026-01-01T00:00:00Z",
    "language_hint": "es",
    "privacy_class": "INTERNAL",
    "copyright_class": "OWN",
    "processing_policy": {"allow_external_providers": False},
}

EPISODIO = {
    "contract_version": "1.0.0",
    "workspace": WS,
    "source_asset_id": "sa-1",
    "source_hash": {"algorithm": "sha256", "value": "abc"},
    "provider_trace": [],
    "produced_by_step": "normalize",
    "episode_id": "ep-1",
    "asset_id": "sa-1",
    "sequence": 0,
    "modality": "TEXT",
    "text": "Ilaria Vandreth lidera la Casa del Ciervo.",
    "content_hash": {"algorithm": "sha256", "value": "def"},
    "quality": {"ocr_confidence": None},
}

FRAGMENTO = {
    "contract_version": "1.0.0",
    "workspace": WS,
    "source_asset_id": "sa-1",
    "source_hash": {"algorithm": "sha256", "value": "abc"},
    "provider_trace": [],
    "produced_by_step": "extract",
    "fragment_id": "ef-1",
    "episode_id": "ep-1",
    "literal_text": "Ilaria Vandreth lidera la Casa del Ciervo.",
    "normalized_text": "ilaria vandreth lidera la casa del ciervo",
    "start": 0,
    "end": 41,
    "media_type": "EMBEDDED_TEXT",
    "confidence": 0.9,
}

ASERCION = {
    "assertion_id": "assertion:1",
    "evidencia": ["ef-1"],
    "subject_entity_id": "entity:ilaria",
    "object_entity_id": "entity:casa",
    "partida_id": None,
}


# ==========================================================================
# Doble de driver: estado consultable, respuestas honestas
# ==========================================================================
_NODO = re.compile(r"^MATCH \(n:(\w+) \{")
_CREA_NODO = re.compile(r"^CREATE \(n:(\w+) \$props\)")
_REL_EXISTE = re.compile(r"^MATCH \(a:(\w+) \{\w+: \$a, workspace: \$ws\}\)-\[r:(\w+)\]->\(b:(\w+)")
_CREA_REL = re.compile(r"^MATCH \(a:(\w+) .*?MATCH \(b:(\w+) .*?CREATE \(a\)-\[:(\w+)\]->\(b\)", re.S)


class FakeTx:
    """Grafo de mentira con estado. Responde lo que de verdad hay guardado."""

    def __init__(self, aserciones=()):
        self.nodos: dict[tuple[str, str, str], dict] = {}
        self.aristas: set[tuple] = set()
        self.aserciones = list(aserciones)
        self.consultas: list[str] = []

    def run(self, cypher, params=None):
        params = params or {}
        self.consultas.append(cypher)
        ws = params.get("ws")

        if "n.evidence_fragment_ids AS evidencia" in cypher:
            ids = params.get("ids")
            return [a for a in self.aserciones if not ids or a["assertion_id"] in ids]

        m = _CREA_NODO.match(cypher)
        if m:
            props = params["props"]
            clave = (m.group(1), props[P.IDENTITY_FIELD[m.group(1)]], props["workspace"])
            assert clave not in self.nodos, "creacion duplicada: %s" % (clave,)
            self.nodos[clave] = props
            return [{"id": clave[1]}]

        m = _REL_EXISTE.match(cypher)
        if m and "RETURN 1 AS existe" in cypher:
            clave = (m.group(1), params["a"], m.group(2), m.group(3), params["b"], ws)
            return [{"existe": 1}] if clave in self.aristas else []

        m = _CREA_REL.match(cypher)
        if m:
            de, hacia, rel = m.group(1), m.group(2), m.group(3)
            if (de, params["a"], ws) not in {(l, i, w) for (l, i, w) in self.nodos} and \
                    not self._existe_extremo(de, params["a"], ws):
                return []
            if not self._existe_extremo(hacia, params["b"], ws):
                return []
            self.aristas.add((de, params["a"], rel, hacia, params["b"], ws))
            return [{"id": params["a"]}]

        m = _NODO.match(cypher)
        if m and "LIMIT 1" in cypher:
            clave = (m.group(1), params["id"], ws)
            return [{"id": params["id"]}] if clave in self.nodos else []

        raise AssertionError("consulta no prevista por el doble: %s" % cypher)

    def _existe_extremo(self, label, node_id, ws):
        if (label, node_id, ws) in self.nodos:
            return True
        # Entidades y aserciones las escribe el writer, no este modulo: el
        # doble las da por presentes si se declararon en el estado inicial.
        return (label, node_id, ws) in self.externos

    externos: set = set()

    def estado(self):
        return (
            sorted((k, tuple(sorted(v.items(), key=lambda kv: kv[0])))
                   for k, v in self.nodos.items()),
            sorted(self.aristas),
        )


def tx_preparado():
    tx = FakeTx(aserciones=[dict(ASERCION)])
    tx.externos = {
        ("V3Assertion", "assertion:1", WS),
        ("V3Entity", "entity:ilaria", WS),
        ("V3Entity", "entity:casa", WS),
    }
    return tx


def volcar(tx, **over):
    datos = dict(
        workspace=WS,
        source_asset=ASSET,
        episodes=[EPISODIO],
        fragments=[FRAGMENTO],
        assertion_ids=["assertion:1"],
    )
    datos.update(over)
    return P.persist_provenance_tx(tx, **datos)


# ==========================================================================
# Proyeccion del documento
# ==========================================================================
def test_la_proyeccion_conserva_los_escalares_del_contrato():
    props, _omitidos = P.flatten_document(FRAGMENTO)
    assert props["fragment_id"] == "ef-1"
    assert props["literal_text"] == FRAGMENTO["literal_text"]
    assert props["start"] == 0 and props["end"] == 41
    assert props["confidence"] == pytest.approx(0.9)


def test_el_bloque_de_hash_se_proyecta_a_su_valor_y_no_se_pierde():
    props, _ = P.flatten_document(ASSET)
    assert props["content_hash_value"] == "abc"
    assert "content_hash" not in props


def test_lo_que_neo4j_no_admite_se_DECLARA_omitido_en_vez_de_desaparecer():
    """Un mapa anidado no cabe en una propiedad. Que no quepa se dice."""
    _props, omitidos = P.flatten_document(ASSET)
    assert "processing_policy" in omitidos
    assert "provider_trace" in omitidos


def test_el_workspace_no_lo_pone_el_documento_sino_el_escritor():
    props, _ = P.flatten_document({**ASSET, "workspace": "otro"})
    assert "workspace" not in props


# ==========================================================================
# Guardia anti-destructiva
# ==========================================================================
def test_ninguna_consulta_del_modulo_es_destructiva():
    """`Query.__post_init__` corre `assert_safe`: construirlas ya lo prueba."""
    consultas = [
        P.create_provenance_node(P.LABEL_EVIDENCE, {"fragment_id": "ef-1", "workspace": WS}),
        P.create_provenance_relation(P.LABEL_EPISODE, "ep-1", P.REL_HAS_FRAGMENT,
                                     P.LABEL_EVIDENCE, "ef-1", WS, None),
        P.relation_exists(P.LABEL_ASSERTION, "assertion:1", P.REL_SUPPORTED_BY,
                          P.LABEL_EVIDENCE, "ef-1", WS),
        P.trace_query(WS, "assertion:1"),
    ]
    for q in consultas:
        for prohibido in ("MERGE", "DELETE", "DETACH", "REMOVE", "DROP"):
            assert prohibido not in q.cypher.upper(), q.cypher


def test_una_etiqueta_desconocida_no_llega_a_construir_consulta():
    with pytest.raises(WriterAbort):
        P.create_provenance_node("V3LoQueSea", {"x": 1})


# ==========================================================================
# Volcado
# ==========================================================================
def test_el_volcado_escribe_los_tres_nodos_y_las_cinco_aristas():
    tx = tx_preparado()
    out = volcar(tx)
    assert out.nodes_created == {
        P.LABEL_SOURCE: 1, P.LABEL_EPISODE: 1, P.LABEL_EVIDENCE: 1}
    assert out.relations_created == {
        P.REL_HAS_EPISODE: 1, P.REL_HAS_FRAGMENT: 1,
        P.REL_SUPPORTED_BY: 1, P.REL_HAS_SUBJECT: 1, P.REL_HAS_OBJECT: 1}
    assert out.total_created == 8


def test_repetir_el_volcado_no_CREA_nada_y_deja_el_estado_identico():
    tx = tx_preparado()
    volcar(tx)
    antes = tx.estado()
    assert antes[0] and antes[1], "el estado medido esta vacio: no probaria nada"

    out2 = volcar(tx)
    assert out2.total_created == 0, out2.to_dict()
    assert out2.nodes_reused == {
        P.LABEL_SOURCE: 1, P.LABEL_EPISODE: 1, P.LABEL_EVIDENCE: 1}
    assert tx.estado() == antes


def test_las_aristas_viajan_con_la_identidad_DURABLE_del_contrato():
    tx = tx_preparado()
    volcar(tx)
    assert ("V3Source", "sa-1", P.REL_HAS_EPISODE, "V3Episode", "ep-1", WS) in tx.aristas
    assert ("V3Episode", "ep-1", P.REL_HAS_FRAGMENT, "V3Evidence", "ef-1", WS) in tx.aristas
    assert ("V3Assertion", "assertion:1", P.REL_SUPPORTED_BY,
            "V3Evidence", "ef-1", WS) in tx.aristas
    for consulta in tx.consultas:
        assert "elementId" not in consulta, consulta


def test_el_nodo_de_procedencia_no_lleva_visibilidad_y_por_eso_no_publica_nada():
    """Sin `visibility`, el motor de politicas cierra en DENY. Es lo querido."""
    tx = tx_preparado()
    volcar(tx)
    for props in tx.nodos.values():
        assert "visibility" not in props
        assert "known_by" not in props


def test_una_evidencia_sin_su_episodio_no_finge_haber_enlazado():
    """Si el extremo no existe, la arista se cuenta como NO creada."""
    tx = tx_preparado()
    out = volcar(tx, episodes=[], fragments=[{**FRAGMENTO, "episode_id": "ep-ausente"}])
    assert out.relations_created.get(P.REL_HAS_FRAGMENT, 0) == 0
    assert out.nodes_created[P.LABEL_EVIDENCE] == 1


def test_un_documento_sin_identidad_aborta_en_vez_de_escribir_un_nodo_anonimo():
    tx = tx_preparado()
    sin_id = {k: v for k, v in FRAGMENTO.items() if k != "fragment_id"}
    with pytest.raises(WriterAbort):
        volcar(tx, fragments=[sin_id])


def test_el_recorrido_encadena_los_tramos_en_UN_patron_sin_producto_cartesiano():
    """Dos `MATCH` sueltos darian filas sin relacion; aqui el camino es uno."""
    cypher = P.trace_query(WS, "assertion:1").cypher
    assert cypher.count("MATCH") == 1
    for tramo in (P.REL_SUPPORTED_BY, P.REL_HAS_FRAGMENT, P.REL_HAS_EPISODE):
        assert f"[:{tramo}]" in cypher
    assert "literal_text" in cypher
