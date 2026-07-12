from app.labels import entity_type_label, relation_label


def test_entity_type_character_translates_to_spanish():
    assert entity_type_label("Character") == "Personaje"


def test_entity_type_unknown_falls_back_to_raw_value():
    assert entity_type_label("SomethingNew") == "SomethingNew"


def test_relation_label_uses_dictionary_when_no_override():
    # APPEARS_IN -> "aparece en" coincide tanto en el diccionario real de
    # data-engine (schemas.rpg_schema.RELATION_LABELS_ES) como en el fallback
    # local, así que el test es estable independientemente de cuál se use.
    assert relation_label("APPEARS_IN") == "aparece en"


def test_relation_label_prefers_explicit_override():
    assert relation_label("RELATED_TO", "una etiqueta custom") == "una etiqueta custom"
