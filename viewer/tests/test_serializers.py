from app.serializers import serialize_edge, serialize_node


def test_confidence_0_9_becomes_90_percent():
    node = {"id": "n1", "label": "Test", "type": "Character", "confidence": 0.9}
    result = serialize_node(node)
    assert result["confidence_label"] == "90%"


def test_serialize_node_survives_missing_fields():
    result = serialize_node({"id": "n1"})
    assert result["label"] == ""
    assert result["aliases"] == []
    assert result["confidence_label"] == ""
    assert result["technical"] == {}


def test_serialize_node_hides_technical_fields_from_top_level():
    node = {"id": "n1", "label": "Test", "created_at": "2026-01-01", "extractor_version": "1.4.0"}
    result = serialize_node(node)
    assert "created_at" not in result
    assert result["technical"]["created_at"] == "2026-01-01"
    assert result["technical"]["extractor_version"] == "1.4.0"


def test_serialize_edge_translates_relation_type():
    edge = {"id": "e1", "from": "a", "to": "b", "type": "APPEARS_IN", "confidence": 0.75}
    result = serialize_edge(edge)
    assert result["label"] == "aparece en"
    assert result["confidence_label"] == "75%"


# ---------------------------------------------------------------------------
# `entity_id` NO cae hacia `id` ni hacia `element_id`
# ---------------------------------------------------------------------------
#
# POR QUE ESTAS PRUEBAS EXISTEN
# -----------------------------
# La regla vivia SOLO en un comentario dentro de `serialize_node`. Un revisor
# escribio el fallback (`node.get("entity_id") or node.get("id") or ...`) y las
# 960 pruebas de servidor, las de navegador y las de JS siguieron verdes: la
# regla era indetectable si alguien la violaba.
#
# Y es una regla con consecuencia real. Con el proveedor de Neo4j,
# `_node_to_dict` pone el `element_id` crudo en `id`. El indice de busqueda del
# visor (`graph-core.js`) indexa `entity_id` —y ningun otro identificador—, asi
# que el fallback convertiria el `elementId` en un identificador BUSCABLE que el
# dominio no reconoce y que ademas se regenera al restaurar un dump. Es justo lo
# que `graph_core_spec.js` promete impedir; pero esa prueba de JS solo demuestra
# que el CLIENTE no indexa `node.id`: es ciega a un servidor que lo copie dentro
# de `entity_id`. La barrera tiene que estar tambien de este lado.

def test_entity_id_no_se_rellena_desde_id():
    """Si el proveedor no da `entity_id`, aqui no hay `entity_id`."""
    result = serialize_node({"id": "4:9f1c2b3a-0000-4000-8000-000000000001:17",
                             "label": "Nodo de Neo4j"})
    assert result["entity_id"] == "", (
        "serialize_node ha rellenado `entity_id` desde `id`: con Neo4j eso mete "
        f"el elementId crudo en el indice de busqueda ({result['entity_id']!r})")


def test_entity_id_no_se_rellena_desde_element_id():
    """Tampoco por la otra puerta: `element_id` es la clave cruda del driver."""
    result = serialize_node({"element_id": "4:9f1c2b3a-0000-4000-8000-000000000001:17",
                             "label": "Nodo de Neo4j"})
    assert result["entity_id"] == "", (
        "serialize_node ha rellenado `entity_id` desde `element_id`: "
        f"({result['entity_id']!r})")


def test_el_element_id_crudo_no_aparece_en_ningun_campo_indexado():
    """Congela la consecuencia, no solo la causa.

    El indice del visor se construye con label · type_label · type ·
    short_summary · entity_id (ver `graph-core.js`). Ninguno de esos cinco
    campos puede contener el identificador tecnico del driver, venga por donde
    venga.
    """
    crudo = "4:9f1c2b3a-0000-4000-8000-000000000001:17"
    result = serialize_node({"id": crudo, "element_id": crudo,
                             "label": "Nodo de Neo4j", "type": "Character"})
    campos_indexados = ("label", "type_label", "type", "short_summary", "entity_id")
    filtrados = [c for c in campos_indexados if crudo in str(result.get(c) or "")]
    assert filtrados == [], (
        "el elementId tecnico se ha colado en campos que el visor INDEXA: "
        f"{filtrados}; se volveria buscable")


def test_entity_id_se_entrega_tal_cual_cuando_el_proveedor_si_lo_da():
    """Contrapeso: la regla es «no inventarlo», no «no entregarlo».

    Sin este caso, un `serialize_node` que devolviese `entity_id` vacio SIEMPRE
    pasaria las tres pruebas de arriba y romperia la busqueda por identificador
    sin que nada enrojeciese.
    """
    result = serialize_node({"id": "4:abc:17", "entity_id": "n_agasha_tamori",
                             "label": "Agasha Tamori"})
    assert result["entity_id"] == "n_agasha_tamori"
    assert result["id"] == "4:abc:17", "el campo tecnico `id` sigue siendo el del proveedor"
