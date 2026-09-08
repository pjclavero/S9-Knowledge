# -*- coding: utf-8 -*-
"""Pruebas del subsistema C de V3: resolucion de identidad.

Cubre normalizacion, similitud, catalogo, glosario, historial, cascada,
decision y emision del contrato congelado. Las pruebas de MUTACION de las
reglas duras (workspace y tipos) viven aparte, en
`test_knowledge_v3_resolution_mutations.py`.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("jsonschema")

_HERE = Path(__file__).resolve().parent
_APP_DIR = _HERE.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))


def _load_resolution_fixtures():
    """Carga las fixtures por ruta, no por `sys.path` (ver su docstring)."""
    name = "s9k_v3_resolution_fixtures"
    if name in sys.modules:
        return sys.modules[name]
    path = _HERE / "test_knowledge_v3_resolution_fixtures.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


F = _load_resolution_fixtures()

from knowledge_v3.contracts import EntityResolution, V3ContractError  # noqa: E402
from knowledge_v3.resolution import (  # noqa: E402
    DEFAULT_CONFIG,
    CatalogEntity,
    EmbeddingProvider,
    EmbeddingSimilarity,
    EntityResolver,
    HistoryEntry,
    InMemoryEntityCatalog,
    InMemoryGlossarySource,
    Neo4jEntityCatalog,
    NullGlossarySource,
    NullSimilarity,
    ResolutionConfig,
    ResolutionConfigError,
    ResolutionHistory,
    ResolutionInputError,
    ResolutionRequest,
    TrigramJaccardSimilarity,
    derive_entity_id,
    derive_resolution_id,
    filter_partida_scope,
    filter_workspace,
    normalize_surface,
    types_compatible,
)
from knowledge_v3.resolution.glossary import GlossaryStoreSource  # noqa: E402
from knowledge_v3.resolution.normalization import (  # noqa: E402
    char_ngrams,
    jaccard,
    token_set,
)
from knowledge_v3.resolution.similarity import edit_ratio, levenshtein  # noqa: E402

WS = F.WORKSPACE
OTHER = F.OTHER_WORKSPACE


def resolver(**kwargs) -> EntityResolver:
    kwargs.setdefault("catalog", F.catalog())
    kwargs.setdefault("glossary", F.glossary())
    return EntityResolver(**kwargs)


def resolve(res: EntityResolver, surface: str, **kwargs):
    mention_id = kwargs.pop("mention_id", "mention:" + normalize_surface(surface).replace(" ", "-"))
    record = kwargs.pop("record_history", False)
    request_kwargs = {k: kwargs.pop(k) for k in ("context_entity_ids", "game_profile") if k in kwargs}
    req = ResolutionRequest.of(F.mention(mention_id, surface, **kwargs), **request_kwargs)
    return res.resolve(req, record_history=record)


# ==========================================================================
# 1. Normalizacion
# ==========================================================================
class TestNormalizacion:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Daiki", "daiki"),
            ("DAIKI", "daiki"),
            ("  Daiki  ", "daiki"),
            ("Daiki, el Magistrado", "daiki el magistrado"),
            ("Ómnibus", "omnibus"),
            ("Casa-del-Ciervo", "casa del ciervo"),
            ("«Umbra»", "umbra"),
            ("", ""),
        ],
    )
    def test_formas_equivalentes_colapsan(self, raw, expected):
        assert normalize_surface(raw) == expected

    def test_no_colapsa_erratas(self):
        """Normalizar NO es corregir: `Daiqui` sigue siendo distinto de `Daiki`.

        Si la normalizacion arreglara las erratas, el error de ASR quedaria
        escondido y no habria forma de medirlo ni de exigir glosario.
        """
        assert normalize_surface("Daiqui") != normalize_surface("Daiki")

    def test_tokens_y_ngramas(self):
        assert token_set("Casa del Ciervo") == frozenset({"casa", "del", "ciervo"})
        assert "  d" in char_ngrams("Daiki")
        assert char_ngrams("") == frozenset()

    def test_jaccard_de_vacios_es_cero(self):
        """Dos vacios NO son "identicos": no hay nada que comparar."""
        assert jaccard(frozenset(), frozenset()) == 0.0


# ==========================================================================
# 2. Similitud de superficie
# ==========================================================================
class TestSimilitud:
    def setup_method(self):
        self.sim = TrigramJaccardSimilarity()

    def test_identidad_y_simetria(self):
        assert self.sim.score("Daiki", "daiki") == 1.0
        assert self.sim.score("Daiki", "Daiqui") == self.sim.score("Daiqui", "Daiki")

    def test_erratas_puntuan_mas_que_desconocidos(self):
        errata = self.sim.score("Tamori", "Tamory")
        ajeno = self.sim.score("Tamori", "Kobayashi")
        assert errata > ajeno
        assert ajeno < 0.2

    def test_reordenamiento_de_tokens(self):
        assert self.sim.score("Familia Tamori", "Tamori Familia") == 1.0

    def test_limite_declarado_no_hay_semantica(self):
        """Limite HONESTO del modelo por defecto, medido y no solo documentado.

        `"el magistrado"` es un alias real de Daiki y esta similitud lo puntua
        tan bajo que ni siquiera llega a ser candidato. Por eso existen el paso
        de alias y el de glosario: si esta senal bastara, no harian falta.
        """
        assert self.sim.score("el magistrado", "Daiki") < DEFAULT_CONFIG.similarity_min

    def test_techo_por_debajo_del_umbral_de_enlace(self):
        """La similitud SOLA no puede enlazar, por construccion de la config."""
        cfg = DEFAULT_CONFIG
        assert cfg.similarity_weight < cfg.link_min_score

    def test_similitud_mas_contexto_si_puede_enlazar(self):
        """"Nunca enlaza SOLA" no es "nunca enlaza": con el contexto, sí.

        Cifras medidas: base 0.756 (similitud), 0.786 con el bonus de tipo —
        `REVIEW` —, y 0.906 si la entidad ya está en el contexto del episodio.
        Dos señales independientes valen más que una; ese es el diseño.
        """
        cat = InMemoryEntityCatalog(
            [CatalogEntity("entity:kobayashi", WS, "Character", "Kobayashi Ryu")]
        )
        res = resolver(catalog=cat, glossary=NullGlossarySource())
        sin_ctx = resolve(res, "Kobayashy Ryu")
        con_ctx = resolve(res, "Kobayashy Ryu", context_entity_ids=("entity:kobayashi",))
        assert sin_ctx.action == "REVIEW"
        assert con_ctx.action == "LINK_EXISTING"
        assert con_ctx.candidates[0].base_score < DEFAULT_CONFIG.link_min_score

    def test_null_similarity_es_ablacion_limpia(self):
        assert NullSimilarity().score("Daiki", "Daiki") == 0.0

    def test_levenshtein_y_edit_ratio(self):
        assert levenshtein("daiki", "daiki") == 0
        assert levenshtein("daiki", "daiqui") == 2
        assert edit_ratio("", "daiki") == 0.0
        assert edit_ratio("daiki", "daiki") == 1.0

    def test_embeddings_usan_el_proveedor_inyectado(self):
        """`EmbeddingSimilarity` esta implementada; el PROVEEDOR es el enganche."""

        class FakeProvider(EmbeddingProvider):
            name = "fake-1.0"

            def __init__(self):
                self.calls = 0

            def embed(self, texts):
                self.calls += 1
                return [[1.0, 0.0] if "daiki" in t else [0.0, 1.0] for t in texts]

        provider = FakeProvider()
        sim = EmbeddingSimilarity(provider)
        assert sim.name == "embedding:fake-1.0"
        assert sim.score("Daiki", "Umbra") == 0.0
        calls = provider.calls
        sim.score("Daiki", "Umbra")  # cacheado: no vuelve a llamar al proveedor
        assert provider.calls == calls


# ==========================================================================
# 3. Catalogo
# ==========================================================================
class TestCatalogo:
    def test_normaliza_nombre_y_alias_con_la_misma_funcion(self):
        e = CatalogEntity("entity:x", WS, "Character", "Daiki, el Magistrado", aliases=("Daiki-san",))
        assert e.normalized_name == "daiki el magistrado"
        assert "daiki san" in e.normalized_aliases
        assert e.all_normalized_forms() == frozenset({"daiki el magistrado", "daiki san"})

    def test_rechaza_tipo_fuera_del_catalogo_congelado(self):
        with pytest.raises(ValueError):
            CatalogEntity("entity:x", WS, "PERSON", "Daiki")

    def test_tipo_nulo_es_legitimo(self):
        assert CatalogEntity("entity:x", WS, None, "Daiki").entity_type is None

    def test_orden_estable_independiente_de_la_insercion(self):
        a = CatalogEntity("entity:b", WS, "Character", "B")
        b = CatalogEntity("entity:a", WS, "Character", "A")
        assert [e.entity_id for e in InMemoryEntityCatalog([a, b]).entities(WS)] == [
            e.entity_id for e in InMemoryEntityCatalog([b, a]).entities(WS)
        ]

    def test_entidades_de_otro_workspace_no_aparecen(self):
        ids = [e.entity_id for e in F.catalog().entities(WS)]
        assert "entity:daiki-tinieblas" not in ids

    def test_neo4j_consulta_el_grafo_y_aisla_por_workspace(self):
        """El enganche ya NO es un `NotImplementedError`: consulta de verdad.

        Aqui se comprueba la DISCIPLINA de la consulta con un driver falso que
        registra lo que se le pide: que el workspace viaje en los PARAMETROS
        (no filtrado en Python despues) y que la sentencia sea de solo lectura.
        Que la consulta devuelva lo que hay en un Neo4j real se mide en
        `test_knowledge_v3_carril_b_neo4j_real.py`, contra un contenedor.
        """
        vistas = []

        class _Sesion:
            def __enter__(self_):
                return self_

            def __exit__(self_, *a):
                return False

            def run(self_, cypher, params=None):
                vistas.append((cypher, dict(params or {})))
                return []

        class _Driver:
            def session(self_, **kw):
                return _Sesion()

        assert Neo4jEntityCatalog(driver=_Driver()).entities(WS) == ()
        cypher, params = vistas[0]
        assert params["ws"] == WS
        assert "n.workspace = $ws" in cypher
        for prohibida in ("CREATE", "MERGE", "SET ", "DELETE", "REMOVE"):
            assert prohibida not in cypher.upper()

    def test_neo4j_locate_no_elige_entre_dos_bovedas(self):
        """Un `entity_id` en dos workspaces es una violacion, no un empate."""

        class _Sesion:
            def __init__(self_, filas):
                self_.filas = filas

            def __enter__(self_):
                return self_

            def __exit__(self_, *a):
                return False

            def run(self_, cypher, params=None):
                return self_.filas

        class _Driver:
            def __init__(self_, filas):
                self_.filas = filas

            def session(self_, **kw):
                return _Sesion(self_.filas)

        assert Neo4jEntityCatalog(_Driver([{"workspace": WS}])).locate("entity:x") == WS
        assert Neo4jEntityCatalog(_Driver([])).locate("entity:x") is None
        dos = [{"workspace": WS}, {"workspace": "otra"}]
        assert Neo4jEntityCatalog(_Driver(dos)).locate("entity:x") is None

    def test_glossary_store_source_tambien_es_enganche(self):
        with pytest.raises(NotImplementedError):
            GlossaryStoreSource(store=object()).lookup(WS, "daiki")

    # -- M2: ambito de partida (docs/v3/49-multipartida-diseno.md) ---------
    def test_rechaza_partida_id_vacio(self):
        with pytest.raises(ValueError):
            CatalogEntity("entity:x", WS, "Character", "Daiki", partida_id="")

    def test_partida_id_none_es_capa_juego_por_defecto(self):
        assert CatalogEntity("entity:x", WS, "Character", "Daiki").partida_id is None

    def test_entities_sin_partida_scope_solo_ve_capa_juego(self):
        """Comportamiento por defecto: identico al de antes de M2.

        Todo `F.CATALOG_ENTITIES` es capa juego (`partida_id=None`); pedir
        `entities(WS)` sin `partida_scope` no cambia ni un id.
        """
        before = {e.entity_id for e in F.CATALOG_ENTITIES if e.workspace == WS}
        after = {e.entity_id for e in F.catalog().entities(WS)}
        assert before == after

    def test_entities_con_partida_scope_ve_partida_propia_y_capa_juego(self):
        catalog = F.catalog_with_partidas()
        ids = {e.entity_id for e in catalog.entities(WS, partida_scope=F.PARTIDA_A)}
        assert "entity:aldric-alpha" in ids
        assert "entity:daiki" in ids  # capa juego, visible desde cualquier partida
        assert "entity:aldric-beta" not in ids  # otra partida: invisible

    def test_entities_partida_scope_none_no_ve_ninguna_partida(self):
        """Direccion UNICA: la capa juego NO ve entidades de ninguna partida."""
        catalog = F.catalog_with_partidas()
        ids = {e.entity_id for e in catalog.entities(WS, partida_scope=None)}
        assert "entity:aldric-alpha" not in ids
        assert "entity:aldric-beta" not in ids
        assert "entity:daiki" in ids

    def test_filter_partida_scope_es_puro_y_total(self):
        entities = list(F.PARTIDA_ENTITIES)
        kept = filter_partida_scope(entities, F.PARTIDA_A)
        assert kept == (F.PARTIDA_ENTITIES[0],)
        assert all(e.partida_id in (None, F.PARTIDA_A) for e in kept)

    def test_get_es_busqueda_directa_no_filtrada_por_partida(self):
        """`InMemoryEntityCatalog.get` es DELIBERADAMENTE unrestricted (ver su
        docstring): lo usan las comprobaciones de PROPIEDAD del historial
        (`history_entry_allowed`), que necesitan saber la verdad completa de un
        `entity_id` ya conocido, no la vista recortada de la cascada. La
        visibilidad para la cascada la impone `entities()`/`filter_partida_scope`,
        no `get()`."""
        catalog = F.catalog_with_partidas()
        assert catalog.get(WS, "entity:aldric-beta", partida_scope=F.PARTIDA_A) is not None
        assert catalog.get(WS, "entity:aldric-beta").partida_id == F.PARTIDA_B


# ==========================================================================
# 4. Glosario
# ==========================================================================
class TestGlosario:
    def test_encuentra_forma_erronea_de_asr(self):
        hits = F.glossary().lookup(WS, "daiqui")
        assert [h.canonical_term for h in hits] == ["Daiki"]
        assert hits[0].kind == "error_form"
        assert hits[0].degraded is True

    def test_no_cruza_workspaces(self):
        """El mismo termino existe en `tinieblas`; consultar `leyenda` no lo ve."""
        assert F.glossary().lookup(OTHER, "daiqui")  # existe alli
        hits = F.glossary().lookup(WS, "daiqui")
        assert all(h.confidence != 0.99 for h in hits)

    def test_orden_estable_escritas_antes_que_degradadas(self):
        gl = InMemoryGlossarySource(
            [{"workspace": WS, "canonical_term": "X", "error_forms": ["z"], "aliases": ["z"]}]
        )
        assert [h.kind for h in gl.lookup(WS, "z")] == ["alias", "error_form"]

    def test_termino_deshabilitado_se_ignora(self):
        gl = InMemoryGlossarySource(
            [{"workspace": WS, "canonical_term": "X", "aliases": ["z"], "enabled": False}]
        )
        assert gl.lookup(WS, "z") == ()

    def test_null_glossary_es_la_ablacion_sin_glosario(self):
        assert NullGlossarySource().lookup(WS, "daiqui") == ()


# ==========================================================================
# 5. Identificadores derivados
# ==========================================================================
class TestIdentificadoresDerivados:
    def test_misma_terna_mismo_id(self):
        kw = dict(workspace=WS, normalized_surface="consejo umbra", entity_type="Faction",
                  prefix="entity:prov:")
        assert derive_entity_id(**kw) == derive_entity_id(**kw)

    def test_el_workspace_forma_parte_de_la_identidad(self):
        a = derive_entity_id(workspace=WS, normalized_surface="ilya", entity_type="Character",
                             prefix="entity:prov:")
        b = derive_entity_id(workspace=OTHER, normalized_surface="ilya", entity_type="Character",
                             prefix="entity:prov:")
        assert a != b

    def test_el_tipo_forma_parte_de_la_identidad(self):
        a = derive_entity_id(workspace=WS, normalized_surface="umbra", entity_type="Faction",
                             prefix="entity:prov:")
        b = derive_entity_id(workspace=WS, normalized_surface="umbra", entity_type="Location",
                             prefix="entity:prov:")
        assert a != b

    def test_el_separador_evita_concatenaciones_ambiguas(self):
        a = derive_entity_id(workspace="ab", normalized_surface="c", entity_type=None,
                             prefix="entity:prov:")
        b = derive_entity_id(workspace="a", normalized_surface="bc", entity_type=None,
                             prefix="entity:prov:")
        assert a != b

    def test_resolution_id_no_depende_del_orden_de_menciones(self):
        a = derive_resolution_id(workspace=WS, mention_ids=["mention:1", "mention:2"])
        b = derive_resolution_id(workspace=WS, mention_ids=["mention:2", "mention:1"])
        assert a == b

    def test_sin_superficie_no_hay_identidad_que_derivar(self):
        with pytest.raises(ValueError):
            derive_entity_id(workspace=WS, normalized_surface="   ", entity_type=None,
                             prefix="entity:prov:")


# ==========================================================================
# 6. Historial
# ==========================================================================
class TestHistorial:
    def test_memoriza_y_recupera_por_workspace(self):
        h = ResolutionHistory()
        assert h.record(workspace=WS, surfaces=["Ilya"], entity_id="entity:x",
                        entity_type="Character", action="LINK_EXISTING", confidence=0.9,
                        resolution_id="resolution:1") == 1
        assert h.lookup(WS, "ilya").entity_id == "entity:x"
        assert h.lookup(OTHER, "ilya") is None

    def test_no_memoriza_dudas(self):
        h = ResolutionHistory()
        for action in ("REVIEW", "SPLIT"):
            assert h.record(workspace=WS, surfaces=["Ilya"], entity_id="entity:x",
                            entity_type=None, action=action, confidence=0.9,
                            resolution_id="resolution:1") == 0
        assert len(h) == 0

    def test_respeta_el_minimo_de_confianza(self):
        h = ResolutionHistory()
        assert h.record(workspace=WS, surfaces=["Ilya"], entity_id="entity:x",
                        entity_type=None, action="CREATE_PROVISIONAL", confidence=0.2,
                        resolution_id="resolution:1", min_confidence=0.5) == 0

    def test_gana_la_de_mayor_confianza_no_la_ultima(self):
        """El resultado no puede depender del orden de recorrido del corpus."""
        h = ResolutionHistory()
        h.record(workspace=WS, surfaces=["Ilya"], entity_id="entity:a", entity_type=None,
                 action="LINK_EXISTING", confidence=0.95, resolution_id="resolution:1")
        h.record(workspace=WS, surfaces=["Ilya"], entity_id="entity:b", entity_type=None,
                 action="LINK_EXISTING", confidence=0.60, resolution_id="resolution:2")
        assert h.lookup(WS, "ilya").entity_id == "entity:a"

    def test_invalidacion_por_entidad_borra_todas_sus_superficies(self):
        h = ResolutionHistory()
        h.record(workspace=WS, surfaces=["Ilya", "Ilya Petrovna"], entity_id="entity:x",
                 entity_type=None, action="LINK_EXISTING", confidence=0.9,
                 resolution_id="resolution:1")
        assert h.invalidate_entity(WS, "entity:x") == 2
        assert len(h) == 0

    def test_invalidacion_por_resolucion_y_por_workspace(self):
        h = ResolutionHistory()
        h.record(workspace=WS, surfaces=["A"], entity_id="entity:x", entity_type=None,
                 action="LINK_EXISTING", confidence=0.9, resolution_id="resolution:1")
        h.record(workspace=OTHER, surfaces=["B"], entity_id="entity:y", entity_type=None,
                 action="LINK_EXISTING", confidence=0.9, resolution_id="resolution:2")
        assert h.invalidate_resolution("resolution:1") == 1
        assert h.invalidate_workspace(OTHER) == 1
        assert h.clear() == 0

    def test_entradas_en_orden_estable(self):
        h = ResolutionHistory(entries=[
            HistoryEntry(WS, "b", "entity:b", None, "LINK_EXISTING", 0.9, "resolution:2"),
            HistoryEntry(WS, "a", "entity:a", None, "LINK_EXISTING", 0.9, "resolution:1"),
        ])
        assert [e.normalized_surface for e in h.entries()] == ["a", "b"]

    # -- M2: ambito de partida (docs/v3/49-multipartida-diseno.md) ---------
    def test_partida_id_por_defecto_es_capa_juego(self):
        assert HistoryEntry(WS, "a", "entity:a", None, "LINK_EXISTING", 0.9, "r:1").partida_id is None

    def test_misma_superficie_dos_partidas_son_entradas_distintas(self):
        """No es la misma ranura de indice: es la premisa del Invariante 1."""
        h = ResolutionHistory()
        h.record(workspace=WS, surfaces=["Aldric"], entity_id="entity:aldric-alpha",
                 entity_type="Character", action="LINK_EXISTING", confidence=0.9,
                 resolution_id="r:1", partida_id=F.PARTIDA_A)
        h.record(workspace=WS, surfaces=["Aldric"], entity_id="entity:aldric-beta",
                 entity_type="Character", action="LINK_EXISTING", confidence=0.9,
                 resolution_id="r:2", partida_id=F.PARTIDA_B)
        assert len(h) == 2
        assert h.lookup(WS, "Aldric", partida_scope=F.PARTIDA_A).entity_id == "entity:aldric-alpha"
        assert h.lookup(WS, "Aldric", partida_scope=F.PARTIDA_B).entity_id == "entity:aldric-beta"

    def test_lookup_sin_partida_scope_no_ve_ninguna_partida(self):
        h = ResolutionHistory()
        h.record(workspace=WS, surfaces=["Aldric"], entity_id="entity:aldric-alpha",
                 entity_type="Character", action="LINK_EXISTING", confidence=0.9,
                 resolution_id="r:1", partida_id=F.PARTIDA_A)
        assert h.lookup(WS, "Aldric") is None
        assert h.lookup(WS, "Aldric", partida_scope=None) is None

    def test_lookup_desde_partida_cae_a_la_capa_juego_si_no_hay_propia(self):
        h = ResolutionHistory()
        h.record(workspace=WS, surfaces=["Daiki"], entity_id="entity:daiki",
                 entity_type="Character", action="LINK_EXISTING", confidence=0.9,
                 resolution_id="r:1")  # partida_id=None: capa juego
        assert h.lookup(WS, "Daiki", partida_scope=F.PARTIDA_A).entity_id == "entity:daiki"

    def test_entrada_propia_de_la_partida_gana_a_la_de_capa_juego(self):
        """Mas especifico gana: si hay entrada propia, no se cae a la compartida."""
        h = ResolutionHistory()
        h.record(workspace=WS, surfaces=["Umbra"], entity_id="entity:umbra-juego",
                 entity_type="Faction", action="LINK_EXISTING", confidence=0.9,
                 resolution_id="r:1")
        h.record(workspace=WS, surfaces=["Umbra"], entity_id="entity:umbra-partida",
                 entity_type="Faction", action="LINK_EXISTING", confidence=0.9,
                 resolution_id="r:2", partida_id=F.PARTIDA_A)
        assert h.lookup(WS, "Umbra", partida_scope=F.PARTIDA_A).entity_id == "entity:umbra-partida"

    def test_invalidate_surface_respeta_partida(self):
        h = ResolutionHistory()
        h.record(workspace=WS, surfaces=["Aldric"], entity_id="entity:aldric-alpha",
                 entity_type="Character", action="LINK_EXISTING", confidence=0.9,
                 resolution_id="r:1", partida_id=F.PARTIDA_A)
        h.record(workspace=WS, surfaces=["Aldric"], entity_id="entity:aldric-beta",
                 entity_type="Character", action="LINK_EXISTING", confidence=0.9,
                 resolution_id="r:2", partida_id=F.PARTIDA_B)
        assert h.invalidate_surface(WS, "Aldric", partida_id=F.PARTIDA_A) == 1
        assert len(h) == 1
        assert h.lookup(WS, "Aldric", partida_scope=F.PARTIDA_B) is not None


# ==========================================================================
# 7. Configuracion
# ==========================================================================
class TestConfiguracion:
    def test_umbrales_incoherentes_se_rechazan_al_construir(self):
        with pytest.raises(ResolutionConfigError):
            ResolutionConfig(link_min_score=0.5, review_min_score=0.8)

    def test_paso_desconocido_se_rechaza(self):
        with pytest.raises(ResolutionConfigError):
            ResolutionConfig(step_order=("exact", "telepatia"))
        with pytest.raises(ResolutionConfigError):
            ResolutionConfig(disabled_steps=frozenset({"telepatia"}))

    def test_prefijo_invalido_para_stable_id(self):
        with pytest.raises(ResolutionConfigError):
            ResolutionConfig(provisional_id_prefix=":prov:")

    def test_without_produce_ablaciones(self):
        cfg = DEFAULT_CONFIG.without("glossary", "similarity")
        assert "glossary" not in cfg.active_generators()
        assert "similarity" not in cfg.active_generators()
        assert "glossary" not in DEFAULT_CONFIG.disabled_steps  # inmutable


# ==========================================================================
# 8. Cascada y decision
# ==========================================================================
class TestCascada:
    def test_exact_enlaza(self):
        out = resolve(resolver(), "Daiki")
        assert out.action == "LINK_EXISTING"
        assert out.resolution.selected_entity_id == "entity:daiki"
        assert "EXACT_NAME" in out.resolution.reason_codes

    def test_por_defecto_la_cascada_se_recorre_entera(self):
        """El cortocircuito NO es el defecto: no es neutro (ver TestCortocircuito)."""
        out = resolve(resolver(), "Daiki")
        assert out.steps_run == ("exact", "history", "alias", "glossary", "similarity")
        assert out.short_circuited is False

    def test_alias_enlaza(self):
        out = resolve(resolver(), "El Magistrado")
        assert out.action == "LINK_EXISTING"
        assert out.resolution.selected_entity_id == "entity:daiki"
        assert "EXACT_ALIAS" in out.resolution.reason_codes

    def test_glosario_rescata_una_forma_erronea_de_asr(self):
        out = resolve(resolver(), "Daiqui")
        assert out.action == "LINK_EXISTING"
        assert out.resolution.selected_entity_id == "entity:daiki"
        assert "GLOSSARY_VARIANT" in out.resolution.reason_codes

    def test_sin_glosario_la_misma_forma_no_se_enlaza(self):
        """Ablacion "sin glosario": la decision cambia, y cambia a peor.

        Es la medida honesta de cuanto aporta el glosario: sin el, `"Daiqui"`
        deja de enlazar con Daiki.
        """
        out = resolve(resolver(glossary=NullGlossarySource()), "Daiqui")
        assert out.action != "LINK_EXISTING"

    def test_similitud_sola_no_enlaza_manda_a_revision(self):
        out = resolve(resolver(), "Casa del Cuervoo", types=(("Faction", 0.9),))
        assert out.action == "REVIEW"
        assert "SURFACE_SIMILARITY" in out.resolution.reason_codes

    def test_ambiguedad_entre_dos_candidatos_iguales(self):
        """Dos entidades comparten el alias `Kaede`: elegir una seria una moneda al aire."""
        out = resolve(resolver(), "Kaede")
        assert out.action == "REVIEW"
        assert "AMBIGUOUS_CANDIDATES" in out.resolution.reason_codes
        assert set(out.resolution.candidate_entity_ids) >= {"entity:kaede-a", "entity:kaede-b"}

    def test_contexto_desempata_una_ambiguedad(self):
        """El bonus de contexto es pequeno a proposito, pero rompe empates."""
        out = resolve(resolver(), "Kaede", context_entity_ids=("entity:kaede-b",))
        assert out.action == "LINK_EXISTING"
        assert out.resolution.selected_entity_id == "entity:kaede-b"
        assert "CONTEXT_SUPPORT" in out.resolution.reason_codes

    def test_entidad_desconocida_crea_nueva(self):
        out = resolve(resolver(), "Kobayashi Ryu", confidence=0.95)
        assert out.action == "CREATE_NEW"
        assert out.resolution.assigned_entity_id.startswith("entity:new:")
        assert out.resolution.selected_entity_id is None

    def test_confianza_baja_crea_provisional_no_canonica(self):
        out = resolve(resolver(), "Kobayashi Ryu", confidence=0.40)
        assert out.action == "CREATE_PROVISIONAL"
        assert out.resolution.confidence <= DEFAULT_CONFIG.provisional_confidence_cap

    def test_mencion_sin_tipo_nunca_crea_canonica(self):
        out = resolve(resolver(), "Kobayashi Ryu", types=(), confidence=0.99)
        assert out.action == "CREATE_PROVISIONAL"
        assert "UNTYPED_MENTION" in out.resolution.reason_codes
        assert out.resolution.entity_type is None

    def test_un_parecido_remoto_impide_acunar_canonica(self):
        """Si algo del catalogo ya se le parece, huele a variante, no a entidad nueva."""
        out = resolve(resolver(), "Casa del Ciervoo", types=(("Faction", 0.99),), confidence=0.99)
        assert out.action in ("REVIEW", "CREATE_PROVISIONAL")
        assert out.action != "CREATE_NEW"

    def test_orden_de_candidatos_totalmente_determinista(self):
        a = resolve(resolver(), "Kaede")
        b = resolve(resolver(), "Kaede")
        assert a.resolution.candidate_entity_ids == b.resolution.candidate_entity_ids
        assert a.resolution.to_json() == b.resolution.to_json()

    def test_empate_perfecto_se_rompe_por_entity_id(self):
        cat = InMemoryEntityCatalog([
            CatalogEntity("entity:zz", WS, "Character", "Ilya"),
            CatalogEntity("entity:aa", WS, "Character", "Ilya"),
        ])
        out = resolve(resolver(catalog=cat), "Ilya")
        assert out.candidates[0].entity_id == "entity:aa"
        # ...aunque el desempate sea estable, dos candidatos identicos siguen
        # siendo ambiguos: no se enlaza, se revisa.
        assert out.action == "REVIEW"


# ==========================================================================
# 9. Invariante 1 — workspace
# ==========================================================================
class TestWorkspace:
    def test_homonimo_de_otra_boveda_no_es_candidato(self):
        out = resolve(resolver(), "Daiki")
        assert "entity:daiki-tinieblas" not in out.resolution.candidate_entity_ids

    def test_la_misma_superficie_resuelve_distinto_en_cada_boveda(self):
        """`Daiki` existe en las dos bovedas y son entidades DISTINTAS."""
        res = resolver()
        a = resolve(res, "Daiki")
        b = resolve(res, "Daiki", mention_id="mention:otro", workspace=OTHER)
        assert a.resolution.selected_entity_id == "entity:daiki"
        assert b.resolution.selected_entity_id == "entity:daiki-tinieblas"
        assert a.resolution.selected_entity_id != b.resolution.selected_entity_id

    def test_catalogo_defectuoso_no_rompe_el_aislamiento(self):
        """Aunque la fuente de datos filtre, el resolutor no."""
        out = resolve(resolver(catalog=F.LeakyCatalog()), "Daiki")
        assert "entity:daiki-tinieblas" not in out.resolution.candidate_entity_ids
        assert out.resolution.selected_entity_id == "entity:daiki"
        assert "WORKSPACE_ISOLATED" in out.resolution.reason_codes

    def test_filter_workspace_es_puro_y_total(self):
        entities = list(F.CATALOG_ENTITIES)
        kept = filter_workspace(entities, WS)
        assert all(e.workspace == WS for e in kept)
        assert len(kept) < len(entities)

    def test_historial_de_otra_boveda_no_contamina(self):
        h = ResolutionHistory()
        h.record(workspace=OTHER, surfaces=["Kobayashi Ryu"], entity_id="entity:intruso",
                 entity_type="Character", action="LINK_EXISTING", confidence=0.99,
                 resolution_id="resolution:x")
        out = resolve(resolver(history=h), "Kobayashi Ryu")
        assert "entity:intruso" not in out.resolution.candidate_entity_ids

    def test_menciones_de_workspaces_distintos_en_un_grupo_son_error(self):
        req = ResolutionRequest.of(
            F.mention("mention:1", "Daiki"),
            F.mention("mention:2", "Daiki", workspace=OTHER),
        )
        with pytest.raises(ResolutionInputError):
            resolver().resolve(req)


# ==========================================================================
# 9b. Invariante 1 (M2) — partida
# ==========================================================================
class TestPartida:
    """docs/v3/49-multipartida-diseno.md. Ver tambien
    `test_knowledge_v3_resolution_mutations.py::TestMutacionPartida` para las
    pruebas de mutacion de la doble cerradura."""

    def test_homonimo_de_otra_partida_no_es_candidato(self):
        out = resolve(
            resolver(catalog=F.catalog_with_partidas()), "Aldric", partida_id=F.PARTIDA_A
        )
        assert "entity:aldric-beta" not in out.resolution.candidate_entity_ids
        assert out.resolution.selected_entity_id == "entity:aldric-alpha"

    def test_la_misma_superficie_resuelve_distinto_en_cada_partida(self):
        res = resolver(catalog=F.catalog_with_partidas())
        a = resolve(res, "Aldric", partida_id=F.PARTIDA_A)
        b = resolve(res, "Aldric", mention_id="mention:otro", partida_id=F.PARTIDA_B)
        assert a.resolution.selected_entity_id == "entity:aldric-alpha"
        assert b.resolution.selected_entity_id == "entity:aldric-beta"
        assert a.resolution.selected_entity_id != b.resolution.selected_entity_id

    def test_partida_ve_la_capa_juego(self):
        out = resolve(resolver(catalog=F.catalog_with_partidas()), "Daiki", partida_id=F.PARTIDA_A)
        assert out.resolution.selected_entity_id == "entity:daiki"

    def test_capa_juego_no_ve_entidades_de_partida(self):
        out = resolve(resolver(catalog=F.catalog_with_partidas()), "Aldric", partida_id=None)
        assert "entity:aldric-alpha" not in out.resolution.candidate_entity_ids
        assert "entity:aldric-beta" not in out.resolution.candidate_entity_ids
        assert out.resolution.action != "LINK_EXISTING"

    def test_menciones_de_partidas_distintas_en_un_grupo_son_error(self):
        req = ResolutionRequest.of(
            F.mention("mention:1", "Aldric", partida_id=F.PARTIDA_A),
            F.mention("mention:2", "Aldric", partida_id=F.PARTIDA_B),
        )
        with pytest.raises(ResolutionInputError):
            resolver(catalog=F.catalog_with_partidas()).resolve(req)

    def test_partida_none_vs_partida_declarada_en_un_grupo_tambien_es_error(self):
        req = ResolutionRequest.of(
            F.mention("mention:1", "Aldric", partida_id=None),
            F.mention("mention:2", "Aldric", partida_id=F.PARTIDA_A),
        )
        with pytest.raises(ResolutionInputError):
            resolver(catalog=F.catalog_with_partidas()).resolve(req)

    def test_la_resolucion_hereda_el_partida_id_de_las_menciones(self):
        out = resolve(resolver(catalog=F.catalog_with_partidas()), "Aldric", partida_id=F.PARTIDA_A)
        assert out.resolution.partida_id == F.PARTIDA_A

    def test_resolucion_de_capa_juego_declara_partida_id_none(self):
        out = resolve(resolver(), "Daiki")
        assert out.resolution.partida_id is None

    def test_la_resolucion_de_partida_sobrevive_al_round_trip_del_contrato(self):
        out = resolve(resolver(catalog=F.catalog_with_partidas()), "Aldric", partida_id=F.PARTIDA_A)
        payload = out.resolution.to_dict()
        assert payload["partida_id"] == F.PARTIDA_A
        restored = EntityResolution.from_dict(payload)
        assert restored.partida_id == F.PARTIDA_A

    def test_partida_id_none_se_omite_en_to_dict(self):
        """Mismo criterio que `metadata`: `None` no ensucia el documento serializado."""
        out = resolve(resolver(), "Daiki")
        assert "partida_id" not in out.resolution.to_dict()


# ==========================================================================
# 10. Invariante 2 — tipos
# ==========================================================================
class TestTipos:
    def test_compatibilidad(self):
        assert types_compatible("Character", "Character")
        assert not types_compatible("Character", "Location")
        assert types_compatible(None, "Location"), "no tipar no es afirmar nada"
        assert types_compatible("Character", None)

    def test_tipo_en_conflicto_no_enlaza_aunque_el_nombre_sea_exacto(self):
        """`Umbra` es una `Faction` en el catalogo y llega como `Location`."""
        out = resolve(resolver(), "Umbra", types=(("Location", 0.95),))
        assert out.action == "REVIEW"
        assert "TYPE_CONFLICT" in out.resolution.reason_codes
        assert out.resolution.selected_entity_id is None

    def test_tipo_compatible_da_bonus(self):
        out = resolve(resolver(), "Umbra", types=(("Faction", 0.95),))
        assert out.action == "LINK_EXISTING"
        assert "TYPE_COMPATIBLE" in out.resolution.reason_codes

    def test_mencion_sin_tipo_puede_enlazar(self):
        out = resolve(resolver(), "Umbra", types=())
        assert out.action == "LINK_EXISTING"
        assert "TYPE_UNKNOWN" in out.resolution.reason_codes

    def test_al_enlazar_manda_el_tipo_de_la_entidad_existente(self):
        out = resolve(resolver(), "Umbra", types=())
        assert out.resolution.entity_type == "Faction"

    def test_tipo_agregado_suma_confianzas_no_votos(self):
        from knowledge_v3.resolution import aggregate_type

        mentions = [
            F.mention("mention:1", "X", types=(("Character", 0.95),)),
            F.mention("mention:2", "X", types=(("Location", 0.30),)),
            F.mention("mention:3", "X", types=(("Location", 0.30),)),
        ]
        assert aggregate_type(mentions) == "Character"

    def test_confianza_agregada_es_la_del_eslabon_mas_debil(self):
        from knowledge_v3.resolution import aggregate_confidence

        mentions = [
            F.mention("mention:1", "X", confidence=0.95),
            F.mention("mention:2", "X", confidence=0.40),
        ]
        assert aggregate_confidence(mentions) == 0.40


# ==========================================================================
# 11. Historial dentro del resolutor
# ==========================================================================
class TestHistorialEnCascada:
    def test_la_segunda_mencion_hereda_la_identidad_de_la_primera(self):
        """Caso `Ilya` del enunciado: una vez decidido, las siguientes van igual."""
        res = resolver(catalog=InMemoryEntityCatalog(), glossary=NullGlossarySource())
        first = resolve(res, "Ilya Petrovna", confidence=0.95, record_history=True)
        assert first.action == "CREATE_NEW"
        second = resolve(res, "Ilya Petrovna", mention_id="mention:2", confidence=0.95,
                         record_history=True)
        assert second.action == "LINK_EXISTING"
        assert second.resolution.selected_entity_id == first.resolution.assigned_entity_id
        assert "HISTORY_SESSION" in second.resolution.reason_codes

    def test_el_historial_abarata_la_cascada_solo_con_cortocircuito(self):
        """El ahorro existe, pero hay que pedirlo: `short_circuit=True`.

        Con la configuracion por defecto la cascada se recorre entera aunque el
        historial ya sepa la respuesta. Es el precio de que el cortocircuito no
        sea neutro (H4): se prefiere pagar coste a cambiar decisiones.
        """
        res = resolver(catalog=InMemoryEntityCatalog(), glossary=NullGlossarySource(),
                       config=ResolutionConfig(short_circuit=True))
        first = resolve(res, "Ilya Petrovna", confidence=0.95, record_history=True)
        second = resolve(res, "Ilya Petrovna", mention_id="mention:2", confidence=0.95)
        assert "similarity" in first.steps_run
        assert "similarity" not in second.steps_run
        assert len(second.steps_run) < len(first.steps_run)

    def test_una_provisional_se_reutiliza_en_la_misma_sesion(self):
        res = resolver(catalog=InMemoryEntityCatalog(), glossary=NullGlossarySource())
        first = resolve(res, "Consejo Umbra", types=(("Faction", 0.4),), confidence=0.4,
                        record_history=True)
        assert first.action == "CREATE_PROVISIONAL"
        second = resolve(res, "Consejo Umbra", mention_id="mention:2",
                         types=(("Faction", 0.4),), confidence=0.4)
        assert second.resolution.selected_entity_id == first.resolution.assigned_entity_id

    def test_el_historial_no_pisa_un_match_exacto(self):
        """Un historial rancio no gana al nombre canonico... pero tampoco se ignora.

        `exact` (1.03 con bonus de tipo) sigue por delante de `history` (1.00),
        asi que la identidad correcta encabeza el ranking. Ahora bien: 0.03 de
        margen esta por debajo de `ambiguity_margin`, y eso es exactamente una
        ambiguedad. La respuesta honesta es `REVIEW`, no elegir en silencio.
        """
        h = ResolutionHistory()
        h.record(workspace=WS, surfaces=["Daiki"], entity_id="entity:kaede-a",
                 entity_type="Character", action="LINK_EXISTING", confidence=0.99,
                 resolution_id="resolution:viejo")
        out = resolve(resolver(history=h), "Daiki")
        assert out.candidates[0].entity_id == "entity:daiki"
        assert out.action == "REVIEW"
        assert "AMBIGUOUS_CANDIDATES" in out.resolution.reason_codes

    def test_el_historial_no_oculta_un_conflicto_de_tipos(self):
        h = ResolutionHistory()
        h.record(workspace=WS, surfaces=["Ilya"], entity_id="entity:ilya-faccion",
                 entity_type="Faction", action="LINK_EXISTING", confidence=0.99,
                 resolution_id="resolution:viejo")
        out = resolve(resolver(catalog=InMemoryEntityCatalog(), history=h), "Ilya",
                      types=(("Character", 0.95),))
        assert out.action == "REVIEW"
        assert "TYPE_CONFLICT" in out.resolution.reason_codes

    def test_invalidar_el_historial_devuelve_la_decision_original(self):
        res = resolver(catalog=InMemoryEntityCatalog(), glossary=NullGlossarySource())
        first = resolve(res, "Ilya Petrovna", confidence=0.95, record_history=True)
        res.history.invalidate_entity(WS, first.resolution.assigned_entity_id)
        again = resolve(res, "Ilya Petrovna", mention_id="mention:3", confidence=0.95)
        assert again.action == "CREATE_NEW"
        assert again.resolution.assigned_entity_id == first.resolution.assigned_entity_id

    def test_ablacion_sin_historial(self):
        cfg = ResolutionConfig(use_history=False)
        res = resolver(catalog=InMemoryEntityCatalog(), glossary=NullGlossarySource(), config=cfg)
        first = resolve(res, "Ilya Petrovna", confidence=0.95, record_history=True)
        second = resolve(res, "Ilya Petrovna", mention_id="mention:2", confidence=0.95)
        assert second.action == "CREATE_NEW"
        assert second.resolution.assigned_entity_id == first.resolution.assigned_entity_id

    def test_resolve_all_alimenta_el_historial_en_orden(self):
        res = resolver(catalog=InMemoryEntityCatalog(), glossary=NullGlossarySource())
        outs = res.resolve_all([
            ResolutionRequest.of(F.mention("mention:1", "Ilya Petrovna", confidence=0.95)),
            ResolutionRequest.of(F.mention("mention:2", "Ilya Petrovna", confidence=0.95)),
            ResolutionRequest.of(F.mention("mention:3", "Ilya Petrovna", confidence=0.95)),
        ])
        assert [o.action for o in outs] == ["CREATE_NEW", "LINK_EXISTING", "LINK_EXISTING"]
        assert len({o.entity_id for o in outs}) == 1


# ==========================================================================
# 12. Estabilidad entre pasadas
# ==========================================================================
class TestEstabilidadEntrePasadas:
    def _pasada(self):
        res = resolver(catalog=InMemoryEntityCatalog(), glossary=NullGlossarySource())
        outs = res.resolve_all([
            ResolutionRequest.of(F.mention("mention:1", "Consejo Umbra",
                                           types=(("Faction", 0.5),), confidence=0.5)),
            ResolutionRequest.of(F.mention("mention:2", "Ilya Petrovna", confidence=0.95)),
        ])
        return [o.resolution for o in outs]

    def test_las_provisionales_reciben_el_mismo_id_en_dos_pasadas(self):
        a, b = self._pasada(), self._pasada()
        assert [r.assigned_entity_id for r in a] == [r.assigned_entity_id for r in b]
        assert a[0].assigned_entity_id.startswith("entity:prov:")

    def test_el_documento_entero_es_identico_byte_a_byte(self):
        a, b = self._pasada(), self._pasada()
        assert [r.to_json() for r in a] == [r.to_json() for r in b]

    def test_dos_bovedas_con_la_misma_superficie_no_colisionan(self):
        res_a = resolver(catalog=InMemoryEntityCatalog(), glossary=NullGlossarySource())
        res_b = resolver(catalog=InMemoryEntityCatalog(), glossary=NullGlossarySource())
        a = resolve(res_a, "Ilya Petrovna", confidence=0.95)
        b = resolve(res_b, "Ilya Petrovna", confidence=0.95, workspace=OTHER)
        assert a.resolution.assigned_entity_id != b.resolution.assigned_entity_id


# ==========================================================================
# 13. Contrato emitido
# ==========================================================================
class TestContratoEmitido:
    def test_el_documento_valida_contra_el_schema_congelado(self):
        for surface, kwargs in [
            ("Daiki", {}),
            ("Kaede", {}),
            ("Umbra", {"types": (("Location", 0.9),)}),
            ("Kobayashi Ryu", {"confidence": 0.95}),
            ("Kobayashi Ryu", {"confidence": 0.30}),
        ]:
            out = resolve(resolver(), surface, **kwargs)
            out.resolution.validate()
            assert isinstance(out.resolution, EntityResolution)

    def test_roundtrip_exacto(self):
        out = resolve(resolver(), "Daiki")
        again = EntityResolution.from_json(out.resolution.to_json())
        assert again == out.resolution

    def test_las_creaciones_traen_assigned_y_no_selected(self):
        out = resolve(resolver(), "Kobayashi Ryu", confidence=0.95)
        assert out.resolution.assigned_entity_id is not None
        assert out.resolution.selected_entity_id is None
        assert out.resolution.entity_id() == out.resolution.assigned_entity_id

    def test_los_enlaces_traen_selected_y_no_assigned(self):
        out = resolve(resolver(), "Daiki")
        assert out.resolution.assigned_entity_id is None
        assert out.resolution.selected_entity_id in out.resolution.candidate_entity_ids

    def test_review_no_fija_identidad(self):
        out = resolve(resolver(), "Kaede")
        assert out.resolution.selected_entity_id is None
        assert out.resolution.assigned_entity_id is None
        assert out.resolution.entity_id() is None

    def test_siempre_hay_al_menos_un_reason_code(self):
        for surface in ("Daiki", "Kaede", "Kobayashi Ryu", "Daiqui"):
            out = resolve(resolver(), surface)
            assert out.resolution.reason_codes

    def test_la_traza_de_proveedor_es_local_y_apunta_al_paso_emisor(self):
        out = resolve(resolver(), "Daiki")
        trace = out.resolution.provider_trace
        assert [s["provider"] for s in trace] == ["local"]
        assert out.resolution.produced_by_step == trace[0]["step"]

    def test_la_metadata_explica_la_decision(self):
        out = resolve(resolver(), "Kaede")
        cascade = out.resolution.metadata["cascade"]
        assert cascade["steps_run"]
        assert [c["entity_id"] for c in cascade["candidates"]] == list(
            out.resolution.candidate_entity_ids
        )

    def test_sin_evidencia_se_bloquea_en_vez_de_inventarla(self):
        """El contrato exige `evidence` minItems 1 y este resolutor no fabrica ninguna."""
        req = ResolutionRequest.of(F.mention("mention:1", "Daiki", evidence=()))
        with pytest.raises(ResolutionInputError):
            resolver().resolve(req)

    def test_grupo_vacio_es_error(self):
        with pytest.raises(ResolutionInputError):
            ResolutionRequest(mentions=())

    def test_mention_ids_duplicados_son_error(self):
        req = ResolutionRequest.of(
            F.mention("mention:1", "Daiki"), F.mention("mention:1", "Daiki-san")
        )
        with pytest.raises(ResolutionInputError):
            resolver().resolve(req)

    def test_grupo_de_varias_menciones_produce_una_sola_resolucion(self):
        req = ResolutionRequest.of(
            F.mention("mention:1", "Daiki", evidence=("fragment:a",)),
            F.mention("mention:2", "El Magistrado", evidence=("fragment:b",)),
        )
        out = resolver().resolve(req)
        assert out.resolution.mention_ids == ["mention:1", "mention:2"]
        assert out.resolution.evidence == ["fragment:a", "fragment:b"]
        assert out.resolution.selected_entity_id == "entity:daiki"

    def test_el_resolutor_no_emite_split(self):
        """Limite declarado: agrupar/desagrupar menciones es del extractor.

        El contrato admite `SPLIT`, pero este subsistema recibe los grupos ya
        formados y no los parte. Documentarlo como limite es mas honesto que
        emitir un `SPLIT` que nadie ha calculado.
        """
        actions = {
            resolve(resolver(), s, **kw).action
            for s, kw in [("Daiki", {}), ("Kaede", {}), ("Umbra", {"types": (("Location", 0.9),)}),
                          ("Kobayashi Ryu", {"confidence": 0.95}), ("Daiqui", {})]
        }
        assert "SPLIT" not in actions

    def test_validate_output_es_una_puerta_real(self):
        cfg = ResolutionConfig(validate_output=False)
        out = resolve(resolver(config=cfg), "Daiki")
        out.resolution.validate()  # sigue siendo valido; la puerta no lo maquilla


# ==========================================================================
# 14. Ablaciones de configuracion
# ==========================================================================
class TestAblaciones:
    def test_el_cortocircuito_ahorra_pasos_cuando_no_hay_rival(self):
        con = resolve(resolver(config=ResolutionConfig(short_circuit=True)), "Daiki")
        sin = resolve(resolver(), "Daiki")
        assert con.resolution.action == sin.resolution.action == "LINK_EXISTING"
        assert len(con.steps_run) < len(sin.steps_run)

    def test_umbral_de_enlace_mas_estricto_manda_a_revision(self):
        cfg = ResolutionConfig(link_min_score=0.999, review_min_score=0.5)
        out = resolve(resolver(config=cfg), "El Magistrado")
        assert out.action == "REVIEW"

    def test_prohibir_create_new_deja_solo_provisionales(self):
        cfg = ResolutionConfig(allow_create_new=False)
        out = resolve(resolver(config=cfg), "Kobayashi Ryu", confidence=0.99)
        assert out.action == "CREATE_PROVISIONAL"

    def test_margen_de_ambiguedad_a_cero_permite_desempatar(self):
        cfg = ResolutionConfig(ambiguity_margin=0.0)
        out = resolve(resolver(config=cfg), "Kaede")
        assert out.action == "LINK_EXISTING"
        assert out.resolution.selected_entity_id == "entity:kaede-a"

    def test_orden_de_pasos_configurable(self):
        cfg = ResolutionConfig(step_order=("history", "exact", "alias", "glossary", "similarity"))
        out = resolve(resolver(config=cfg), "Daiki")
        assert out.resolution.selected_entity_id == "entity:daiki"


# ==========================================================================
# 15. Cortocircuito — H4: NO es neutro, y se prueba que no lo es
# ==========================================================================
class TestCortocircuito:
    """El cortocircuito cambia decisiones. Está desactivado por defecto y aquí
    se documenta ejecutablemente en qué caso cambia y hacia dónde."""

    def _con_rival_de_historial(self, short_circuit: bool):
        h = ResolutionHistory()
        h.record(workspace=WS, surfaces=["Kaede"], entity_id="entity:kaede-a",
                 entity_type="Character", action="LINK_EXISTING", confidence=0.99,
                 resolution_id="resolution:previa")
        res = resolver(history=h, config=ResolutionConfig(short_circuit=short_circuit))
        return resolve(res, "Kaede")

    def test_cortar_convierte_una_ambiguedad_en_un_enlace(self):
        """El caso concreto que obligó a desactivarlo por defecto.

        Con corte, el historial (0.97) gana y la cascada nunca llega a `alias`,
        donde esperaba `entity:kaede-b` a 0.95. Sin corte, esos 0.02 de margen
        son una ambigüedad y la respuesta es `REVIEW`.
        """
        cortado = self._con_rival_de_historial(True)
        entero = self._con_rival_de_historial(False)
        assert cortado.action == "LINK_EXISTING"
        assert entero.action == "REVIEW"
        assert cortado.steps_run == ("exact", "history")
        assert entero.steps_run == ("exact", "history", "alias", "glossary", "similarity")

    def test_el_defecto_es_la_variante_conservadora(self):
        assert DEFAULT_CONFIG.short_circuit is False
        assert self._con_rival_de_historial(DEFAULT_CONFIG.short_circuit).action == "REVIEW"

    def test_no_corta_cuando_ya_hay_dos_candidatos(self):
        res = resolver(config=ResolutionConfig(short_circuit=True))
        out = resolve(res, "Kaede")
        assert out.short_circuited is False
        assert out.action == "REVIEW"


# ==========================================================================
# 16. H3/H7 — confianza heredada y procedencia del historial
# ==========================================================================
class TestConfianzaHeredada:
    def _dos_menciones_de_una_provisional(self):
        res = resolver(catalog=InMemoryEntityCatalog(), glossary=NullGlossarySource())
        primera = resolve(res, "Consejo Umbra", types=(("Faction", 0.45),),
                          confidence=0.45, record_history=True)
        segunda = resolve(res, "Consejo Umbra", mention_id="mention:2",
                          types=(("Faction", 0.45),), confidence=0.45)
        return primera, segunda

    def test_una_duda_heredada_no_se_convierte_en_certeza(self):
        """H3: sin esto, el eco de una provisional de 0.45 salía con 1.00."""
        primera, segunda = self._dos_menciones_de_una_provisional()
        assert primera.action == "CREATE_PROVISIONAL"
        assert segunda.action == "LINK_EXISTING"
        assert segunda.resolution.confidence == primera.resolution.confidence == 0.45
        assert "INHERITED_CONFIDENCE" in segunda.resolution.reason_codes

    def test_la_identidad_si_se_hereda_solo_la_certeza_no(self):
        primera, segunda = self._dos_menciones_de_una_provisional()
        assert segunda.resolution.selected_entity_id == primera.resolution.assigned_entity_id

    def test_el_contrato_delata_el_enlace_por_historial(self):
        """H7: `FROM_HISTORY` marca las identidades que el catálogo no conoce."""
        _, segunda = self._dos_menciones_de_una_provisional()
        assert "FROM_HISTORY" in segunda.resolution.reason_codes
        assert "HISTORY_SESSION" in segunda.resolution.reason_codes
        candidato = segunda.resolution.metadata["cascade"]["candidates"][0]
        assert candidato["from_history"] is True
        assert candidato["inherited_confidence"] == 0.45

    def test_no_se_rebaja_lo_que_el_presente_sostiene_por_si_solo(self):
        """Si el nombre exacto también coincide, no hay nada que heredar."""
        h = ResolutionHistory()
        h.record(workspace=WS, surfaces=["Daiki"], entity_id="entity:daiki",
                 entity_type="Character", action="CREATE_PROVISIONAL", confidence=0.41,
                 resolution_id="resolution:previa")
        out = resolve(resolver(history=h), "Daiki")
        assert out.action == "LINK_EXISTING"
        assert out.resolution.confidence == 1.0
        assert "INHERITED_CONFIDENCE" not in out.resolution.reason_codes


# ==========================================================================
# 17. H5 — colisión del identificador derivado
# ==========================================================================
class TestColisionDeIdDerivado:
    def _resolutor_con_rivales_debiles(self):
        # `similarity_min` bajo para que aparezcan candidatos flojos: hace falta
        # una decisión de CREACIÓN que tenga candidatos, que es la única
        # situación en la que el id derivado puede colisionar.
        return resolver(config=ResolutionConfig(similarity_min=0.05))

    def test_sin_colision_se_crea_normalmente(self):
        out = resolve(self._resolutor_con_rivales_debiles(), "Kobayashi Ryu", confidence=0.99)
        assert out.action == "CREATE_NEW"
        assert out.resolution.candidate_entity_ids, "el caso debe tener candidatos"
        assert out.resolution.assigned_entity_id not in out.resolution.candidate_entity_ids

    def test_una_colision_degrada_a_revision_en_vez_de_emitir_invalido(self, monkeypatch):
        """El validador rechazaría `assigned_entity_id` ya presente entre los
        candidatos (no se estaría creando nada). Se degrada a `REVIEW`."""
        from knowledge_v3.resolution import resolver as resolver_mod

        monkeypatch.setattr(resolver_mod, "derive_entity_id", lambda **kw: "entity:daiki")
        out = resolve(self._resolutor_con_rivales_debiles(), "Kobayashi Ryu", confidence=0.99)
        assert out.action == "REVIEW"
        assert "PROVISIONAL_ID_COLLISION" in out.resolution.reason_codes
        assert out.resolution.assigned_entity_id is None
        assert out.resolution.selected_entity_id is None
        out.resolution.validate()


# ==========================================================================
# 18. SPLIT reservado a integración
# ==========================================================================
class TestSplitReservado:
    def test_el_resolutor_rechaza_una_decision_split_que_le_llegue(self):
        """Decisión del organizador: `SPLIT` lo emite la revisión humana en
        integración. Este resolutor ni lo emite ni lo acepta."""
        out = resolve(resolver(), "Daiki")
        doc = EntityResolution.from_dict(
            {
                **out.resolution.to_dict(),
                "action": "SPLIT",
                "selected_entity_id": None,
                "assigned_entity_id": None,
                "mention_ids": ["mention:1", "mention:2"],
                "split_groups": [["mention:1"], ["mention:2"]],
            }
        )
        with pytest.raises(ResolutionInputError):
            resolver().ingest_decision(doc, surfaces=["Daiki"])

    def test_una_decision_externa_no_split_si_alimenta_el_historial(self):
        res = resolver(catalog=InMemoryEntityCatalog(), glossary=NullGlossarySource())
        primera = resolve(res, "Ilya Petrovna", confidence=0.95)
        assert res.ingest_decision(primera.resolution, surfaces=["Ilya Petrovna"]) == 1
        segunda = resolve(res, "Ilya Petrovna", mention_id="mention:2", confidence=0.95)
        assert segunda.action == "LINK_EXISTING"
        assert segunda.resolution.selected_entity_id == primera.resolution.assigned_entity_id


class TestDeterminanteInicialCarril7:
    """CARRIL 7: `LINK_EXISTING` frente a `CREATE_PROVISIONAL`.

    Defecto reproducido sobre el producto: la superficie que produce el
    extractor arrastra el determinante del espanol natural (`"la Marea Negra"`,
    `"del Consejo de Umbra"`), pero los pasos `exact` y `alias` de la cascada
    comparan por IGUALDAD de cadena normalizada. Sin variante sin determinante,
    la unica senal que podia alcanzar a la entidad existente era `similarity`,
    cuyo techo (`similarity_weight` = 0.88) esta por DEBAJO del umbral de enlace
    (`link_min_score` = 0.90) POR DISENO. La resolucion correcta no era
    improbable: era ESTRUCTURALMENTE inalcanzable.

    El arreglo no toca ningun umbral. Anade la variante para que el dato llegue
    a las guardias que ya existian; la de ambiguedad sigue mandando a `REVIEW`.
    """

    @staticmethod
    def _faccion(entity_id: str, nombre: str, aliases=()) -> CatalogEntity:
        return CatalogEntity(
            entity_id=entity_id, workspace=WS, entity_type="Faction",
            canonical_name=nombre, aliases=aliases,
        )

    @staticmethod
    def _resolver_con(*entidades) -> EntityResolver:
        return EntityResolver(
            catalog=InMemoryEntityCatalog(entidades),
            glossary=NullGlossarySource(),
            similarity=TrigramJaccardSimilarity(),
        )

    def test_la_variante_sin_determinante_se_deriva_pero_la_literal_se_conserva(self):
        from knowledge_v3.resolution.normalization import surface_variants

        assert surface_variants("la Marea Negra") == ("la marea negra", "marea negra")
        assert surface_variants("del Consejo de Umbra") == (
            "del consejo de umbra", "consejo de umbra",
        )
        # Sin determinante inicial no se inventa variante alguna.
        assert surface_variants("Marea Negra") == ("marea negra",)
        # Un determinante que NO encabeza no se toca: "de Ambar" no es "Ambar".
        assert surface_variants("Casa de la Moneda") == ("casa de la moneda",)
        # Si quitarlo dejaria la cadena vacia, no se quita.
        assert surface_variants("La") == ("la",)

    def test_caso_1_el_articulo_no_impide_enlazar_con_el_nombre_exacto(self):
        """`"la Marea Negra"` debe enlazar con `"Marea Negra"`, igual que sin
        articulo, y por la senal FUERTE (`EXACT_NAME`), no por similitud."""
        marea = self._faccion("entity:faction:marea-negra", "Marea Negra",
                              aliases=("la Marea",))
        res = self._resolver_con(marea)

        sin_art = resolve(res, "Marea Negra", types=(("Faction", 0.92),))
        con_art = resolve(res, "la Marea Negra", types=(("Faction", 0.92),))

        assert sin_art.action == "LINK_EXISTING"
        assert con_art.action == "LINK_EXISTING", "el articulo degradaba a REVIEW"
        # Identidad durable, no posicion.
        assert con_art.entity_id == "entity:faction:marea-negra"
        assert con_art.entity_id == sin_art.entity_id
        # Y por la senal fuerte: si enlazase por SURFACE_SIMILARITY seria un
        # umbral relajado, no el dato llegando a la guardia.
        assert "EXACT_NAME" in con_art.resolution.reason_codes
        assert con_art.resolution.confidence == sin_art.resolution.confidence

    def test_caso_2_los_objetos_existentes_resuelven_a_su_entity_id_real(self):
        """Superficies literales del escenario multipartida de tanda 6."""
        cofradia = self._faccion("entity:cofradia-ambar", "Cofradia de Ambar")
        consejo = self._faccion("entity:consejo-umbra", "Consejo de Umbra")
        res = self._resolver_con(cofradia, consejo)

        for superficie, esperado in (
            ("la Cofradia de Ambar", "entity:cofradia-ambar"),
            ("del Consejo de Umbra", "entity:consejo-umbra"),
        ):
            out = resolve(res, superficie, types=(("Faction", 0.92),))
            assert out.action == "LINK_EXISTING", f"{superficie} -> {out.action}"
            # No `CREATE_PROVISIONAL`: el id es el REAL, no uno derivado.
            assert out.entity_id == esperado
            assert not out.entity_id.startswith(DEFAULT_CONFIG.provisional_id_prefix)

    def test_caso_3_la_ambiguedad_genuina_sigue_degradando(self):
        """Condicion de aceptacion, no adorno: si hay dos candidatos realmente
        plausibles, `REVIEW` sigue siendo la respuesta correcta. Aqui las DOS
        entidades declaran el MISMO alias exacto, asi que la ambiguedad no
        depende de ningun umbral."""
        negra = self._faccion("entity:faction:marea-negra", "Marea Negra",
                              aliases=("la Marea",))
        roja = self._faccion("entity:faction:marea-roja", "Marea Roja",
                             aliases=("la Marea",))
        res = self._resolver_con(negra, roja)

        out = resolve(res, "la Marea", types=(("Faction", 0.92),))
        assert out.action == "REVIEW"
        assert out.entity_id is None
        assert "AMBIGUOUS_CANDIDATES" in out.resolution.reason_codes
        # Explicito: la variante NO ha elegido ganador por ser mas corta.
        assert out.entity_id not in (negra.entity_id, roja.entity_id)

    def test_la_variante_no_relaja_ningun_umbral(self):
        """Control: el arreglo vive en la construccion de superficies, no en la
        configuracion. Ningun umbral de decision cambia."""
        assert DEFAULT_CONFIG.link_min_score == 0.90
        assert DEFAULT_CONFIG.review_min_score == 0.60
        assert DEFAULT_CONFIG.ambiguity_margin == 0.10
        assert DEFAULT_CONFIG.similarity_weight == 0.88
        assert DEFAULT_CONFIG.similarity_weight < DEFAULT_CONFIG.link_min_score
