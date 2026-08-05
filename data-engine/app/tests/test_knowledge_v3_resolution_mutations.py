# -*- coding: utf-8 -*-
"""Pruebas de MUTACION de las reglas duras del resolutor de identidad.

Un test que pasa no demuestra que la regla que dice comprobar sea la que sostiene
el resultado. Estas pruebas lo demuestran al reves: rompen la regla a proposito
y exigen que la comprobacion se ponga ROJA. Si una mutacion no rompe nada, la
comprobacion correspondiente era decorativa y hay que reescribirla.

Reglas cubiertas:

  1. Filtro de workspace (catalogo, glosario e historial).
  2. Respeto de tipos (compatibilidad y umbral de anulacion).
  3. Determinismo de los identificadores derivados.
  4. Desempate determinista y umbral de ambiguedad.

Las mutaciones se aplican con `monkeypatch` y desaparecen al terminar el test:
el codigo de produccion no se toca.
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

from knowledge_v3.resolution import (  # noqa: E402
    EntityResolver,
    InMemoryEntityCatalog,
    NullGlossarySource,
    ResolutionConfig,
    ResolutionHistory,
    ResolutionRequest,
)
from knowledge_v3.resolution import cascade as cascade_mod  # noqa: E402
from knowledge_v3.resolution import resolver as resolver_mod  # noqa: E402
from knowledge_v3.resolution.glossary import InMemoryGlossarySource  # noqa: E402

WS = F.WORKSPACE
OTHER = F.OTHER_WORKSPACE


# ==========================================================================
# Comprobaciones bajo prueba
#
# Cada una es la asercion que el subsistema debe sostener. Se ejecutan dos
# veces: intactas (verde) y con la regla mutada (deben ponerse rojas).
# ==========================================================================
def check_aislamiento_de_workspace() -> None:
    """Un homonimo de otra boveda nunca puede ser candidato ni resultado."""
    res = EntityResolver(F.LeakyCatalog(), glossary=F.glossary())
    out = res.resolve(ResolutionRequest.of(F.mention("mention:1", "Daiki")))
    assert "entity:daiki-tinieblas" not in out.resolution.candidate_entity_ids
    assert out.resolution.selected_entity_id == "entity:daiki"


def check_aislamiento_del_glosario() -> None:
    """El glosario de otra boveda no puede explicar una superficie de esta.

    Montaje: `"Casa del Siervo"` es forma erronea de `"Casa del Ciervo"` SOLO en
    el glosario de `leyenda`. La mencion llega en `tinieblas`, donde existe una
    entidad homonima (`entity:casa-ciervo-tinieblas`) pero ninguna entrada de
    glosario. El unico camino a un enlace pasa por que el glosario cruce
    bovedas; el filtro del catalogo, por si solo, no lo impediria.
    """
    res = EntityResolver(F.catalog(), glossary=F.glossary())
    out = res.resolve(
        ResolutionRequest.of(
            F.mention("mention:1", "Casa del Siervo", workspace=OTHER,
                      types=(("Faction", 0.9),))
        )
    )
    assert "GLOSSARY_VARIANT" not in out.resolution.reason_codes
    assert out.resolution.selected_entity_id != "entity:casa-ciervo-tinieblas"


def check_aislamiento_del_historial(history=None) -> None:
    """Lo decidido en una boveda no condiciona a otra.

    Se prueba contra un historial DEFECTUOSO (`LeakyHistory`, cuyo `lookup`
    ignora el workspace) porque la garantia no puede depender de que el indice
    este bien tecleado: la sostiene `history_entry_allowed`, no la clave.
    """
    history = F.LeakyHistory() if history is None else history
    history.record(
        workspace=OTHER, surfaces=["Kobayashi Ryu"], entity_id="entity:intruso",
        entity_type="Character", action="LINK_EXISTING", confidence=0.99,
        resolution_id="resolution:x",
    )
    res = EntityResolver(F.catalog(), glossary=NullGlossarySource(), history=history)
    out = res.resolve(ResolutionRequest.of(F.mention("mention:1", "Kobayashi Ryu")))
    assert "entity:intruso" not in out.resolution.candidate_entity_ids
    assert out.resolution.selected_entity_id is None


def check_aislamiento_de_partida() -> None:
    """Un homonimo de OTRA partida del mismo juego nunca es candidato ni resultado.

    INVARIANTE 1 de M2 (docs/v3/49-multipartida-diseno.md), gemelo exacto de
    `check_aislamiento_de_workspace`. Se prueba contra `LeakyCatalog` (que
    ignora `partida_scope`, ver su docstring) porque la garantia no puede
    depender de que la fuente de datos filtre bien: la sostiene
    `filter_partida_scope`, defensa en profundidad en la cascada.
    """
    catalog = F.LeakyCatalog((*F.CATALOG_ENTITIES, *F.PARTIDA_ENTITIES))
    res = EntityResolver(catalog, glossary=NullGlossarySource())
    out = res.resolve(
        ResolutionRequest.of(F.mention("mention:1", "Aldric", partida_id=F.PARTIDA_A))
    )
    assert "entity:aldric-beta" not in out.resolution.candidate_entity_ids
    assert out.resolution.selected_entity_id == "entity:aldric-alpha"


def check_aislamiento_del_historial_de_partida(history=None) -> None:
    """Lo decidido en una partida no condiciona a otra partida del mismo juego.

    Gemelo de `check_aislamiento_del_historial`. `LeakyHistory` ignora tambien
    `partida_scope` (ver su docstring): la garantia la sostiene
    `history_entry_allowed`, no el indice.
    """
    history = F.LeakyHistory() if history is None else history
    history.record(
        workspace=WS, surfaces=["Ex Nihilo"], entity_id="entity:intruso-partida",
        entity_type="Character", action="LINK_EXISTING", confidence=0.99,
        resolution_id="resolution:y", partida_id=F.PARTIDA_B,
    )
    res = EntityResolver(F.catalog_with_partidas(), glossary=NullGlossarySource(), history=history)
    out = res.resolve(
        ResolutionRequest.of(F.mention("mention:1", "Ex Nihilo", partida_id=F.PARTIDA_A))
    )
    assert "entity:intruso-partida" not in out.resolution.candidate_entity_ids
    assert out.resolution.selected_entity_id is None


def check_juego_no_captura_entidad_de_partida() -> None:
    """La capa juego (partida_id=None) NUNCA ve una entidad nacida en una partida.

    Direccion UNICA del Invariante 1: al reves SI hay visibilidad (partida ve
    capa juego), pero el lore compartido no puede "capturar" una entidad de
    mesa por que comparta nombre.
    """
    res = EntityResolver(F.catalog_with_partidas(), glossary=NullGlossarySource())
    out = res.resolve(ResolutionRequest.of(F.mention("mention:1", "Aldric", partida_id=None)))
    assert "entity:aldric-alpha" not in out.resolution.candidate_entity_ids
    assert "entity:aldric-beta" not in out.resolution.candidate_entity_ids
    assert out.resolution.action != "LINK_EXISTING"


def check_partida_ve_capa_juego() -> None:
    """Una partida SI ve (y puede enlazar con) la capa juego compartida."""
    res = EntityResolver(F.catalog_with_partidas(), glossary=F.glossary())
    out = res.resolve(ResolutionRequest.of(F.mention("mention:1", "Daiki", partida_id=F.PARTIDA_A)))
    assert out.resolution.action == "LINK_EXISTING"
    assert out.resolution.selected_entity_id == "entity:daiki"


def check_respeto_de_tipos() -> None:
    """Una mencion `Location` no se enlaza con una `Faction` aunque el nombre sea exacto."""
    res = EntityResolver(F.catalog(), glossary=F.glossary())
    out = res.resolve(
        ResolutionRequest.of(
            F.mention("mention:1", "Umbra", types=(("Location", 0.95),))
        )
    )
    assert out.resolution.action == "REVIEW"
    assert out.resolution.selected_entity_id is None
    assert "TYPE_CONFLICT" in out.resolution.reason_codes


def check_estabilidad_de_provisionales() -> None:
    """La misma entidad provisional recibe el mismo id en dos pasadas."""
    ids = []
    for _ in range(2):
        res = EntityResolver(InMemoryEntityCatalog(), glossary=NullGlossarySource())
        out = res.resolve(
            ResolutionRequest.of(
                F.mention("mention:1", "Consejo Umbra",
                          types=(("Faction", 0.4),), confidence=0.4)
            )
        )
        assert out.resolution.action == "CREATE_PROVISIONAL"
        ids.append(out.resolution.assigned_entity_id)
    assert ids[0] == ids[1]


def check_ambiguedad_no_se_resuelve_a_dedo(config: ResolutionConfig | None = None) -> None:
    """Dos candidatos indistinguibles van a REVIEW, no al primero de la lista."""
    res = EntityResolver(F.catalog(), glossary=F.glossary(), config=config)
    out = res.resolve(ResolutionRequest.of(F.mention("mention:1", "Kaede")))
    assert out.resolution.action == "REVIEW"
    assert "AMBIGUOUS_CANDIDATES" in out.resolution.reason_codes


ALL_CHECKS = (
    check_aislamiento_de_workspace,
    check_aislamiento_del_glosario,
    check_aislamiento_del_historial,
    check_aislamiento_de_partida,
    check_aislamiento_del_historial_de_partida,
    check_juego_no_captura_entidad_de_partida,
    check_partida_ve_capa_juego,
    check_respeto_de_tipos,
    check_estabilidad_de_provisionales,
    check_ambiguedad_no_se_resuelve_a_dedo,
)


@pytest.mark.parametrize("check", ALL_CHECKS, ids=lambda c: c.__name__)
def test_las_comprobaciones_pasan_sobre_el_codigo_intacto(check):
    """Linea base: sin mutar nada, todo lo anterior se sostiene."""
    check()


# ==========================================================================
# 1. Mutacion: quitar el filtro de workspace
# ==========================================================================
class TestMutacionWorkspace:
    def test_sin_filtro_de_workspace_en_la_cascada_se_pone_rojo(self, monkeypatch):
        """La mutacion canonica: `filter_workspace` deja de filtrar."""
        monkeypatch.setattr(
            cascade_mod, "filter_workspace", lambda entities, workspace: tuple(entities)
        )
        with pytest.raises(AssertionError):
            check_aislamiento_de_workspace()

    def test_sin_filtro_el_homonimo_ajeno_entra_como_candidato(self, monkeypatch):
        """Se comprueba QUE rompe la mutacion, no solo que rompe algo."""
        monkeypatch.setattr(
            cascade_mod, "filter_workspace", lambda entities, workspace: tuple(entities)
        )
        res = EntityResolver(F.LeakyCatalog(), glossary=F.glossary())
        out = res.resolve(ResolutionRequest.of(F.mention("mention:1", "Daiki")))
        assert "entity:daiki-tinieblas" in out.resolution.candidate_entity_ids

    def test_glosario_que_ignora_el_workspace_se_pone_rojo(self, monkeypatch):
        original = InMemoryGlossarySource.lookup

        def leaky_lookup(self, workspace, normalized_surface):
            hits: list = []
            for ws in (workspace, WS, OTHER):
                for hit in original(self, ws, normalized_surface):
                    if hit not in hits:
                        hits.append(hit)
            return tuple(hits)

        monkeypatch.setattr(InMemoryGlossarySource, "lookup", leaky_lookup)
        with pytest.raises(AssertionError):
            check_aislamiento_del_glosario()

    def test_un_historial_defectuoso_no_rompe_el_aislamiento(self):
        """Linea base explicita: con `LeakyHistory` la garantia se sostiene."""
        check_aislamiento_del_historial()

    def test_sin_la_cerradura_del_historial_se_pone_rojo(self, monkeypatch):
        """La mutacion canonica de H2: `history_entry_allowed` deja pasar todo."""
        monkeypatch.setattr(
            cascade_mod, "history_entry_allowed", lambda entry, ctx, catalog: True
        )
        with pytest.raises(AssertionError):
            check_aislamiento_del_historial()

    def test_sin_la_cerradura_el_intruso_llega_a_enlazarse(self, monkeypatch):
        """Que rompe exactamente la mutacion: un LINK_EXISTING entre bovedas."""
        monkeypatch.setattr(
            cascade_mod, "history_entry_allowed", lambda entry, ctx, catalog: True
        )
        history = F.LeakyHistory()
        history.record(
            workspace=OTHER, surfaces=["Kobayashi Ryu"], entity_id="entity:intruso",
            entity_type="Character", action="LINK_EXISTING", confidence=0.99,
            resolution_id="resolution:x",
        )
        res = EntityResolver(F.catalog(), glossary=NullGlossarySource(), history=history)
        out = res.resolve(ResolutionRequest.of(F.mention("mention:1", "Kobayashi Ryu")))
        assert out.resolution.selected_entity_id == "entity:intruso"

    def test_la_segunda_comprobacion_usa_el_catalogo(self):
        """Una entrada con el workspace bien puesto pero que apunta a una
        entidad de otra boveda tampoco pasa: la coteja `EntityCatalog.locate`."""
        history = ResolutionHistory()
        history.record(
            workspace=WS, surfaces=["Kobayashi Ryu"], entity_id="entity:daiki-tinieblas",
            entity_type="Character", action="LINK_EXISTING", confidence=0.99,
            resolution_id="resolution:x",
        )
        res = EntityResolver(F.catalog(), glossary=NullGlossarySource(), history=history)
        out = res.resolve(ResolutionRequest.of(F.mention("mention:1", "Kobayashi Ryu")))
        assert "entity:daiki-tinieblas" not in out.resolution.candidate_entity_ids

    def test_la_mutacion_no_afecta_a_las_demas_reglas(self, monkeypatch):
        """Una mutacion de workspace no debe romper comprobaciones ajenas.

        Si rompiera todas, no estaria midiendo la regla sino el ruido.
        """
        monkeypatch.setattr(
            cascade_mod, "filter_workspace", lambda entities, workspace: tuple(entities)
        )
        check_respeto_de_tipos()
        check_estabilidad_de_provisionales()


# ==========================================================================
# 1b. Mutacion: quitar el filtro de PARTIDA (M2, INVARIANTE 1)
# ==========================================================================
class TestMutacionPartida:
    """Gemela exacta de `TestMutacionWorkspace`, para el segundo eje de M2.

    Cada mutacion aqui repite, campo por campo, una mutacion de workspace de
    mas arriba: es literalmente el mismo patron de doble cerradura clonado
    (docs/v3/49-multipartida-diseno.md #2.3), y las pruebas lo demuestran
    rompiendolo de la misma manera.
    """

    def test_sin_filtro_de_partida_en_la_cascada_se_pone_rojo(self, monkeypatch):
        """La mutacion canonica: `filter_partida_scope` deja de filtrar."""
        monkeypatch.setattr(
            cascade_mod, "filter_partida_scope", lambda entities, partida_scope: tuple(entities)
        )
        with pytest.raises(AssertionError):
            check_aislamiento_de_partida()

    def test_sin_filtro_el_homonimo_de_otra_partida_entra_como_candidato(self, monkeypatch):
        """Se comprueba QUE rompe la mutacion, no solo que rompe algo."""
        monkeypatch.setattr(
            cascade_mod, "filter_partida_scope", lambda entities, partida_scope: tuple(entities)
        )
        catalog = F.LeakyCatalog((*F.CATALOG_ENTITIES, *F.PARTIDA_ENTITIES))
        res = EntityResolver(catalog, glossary=NullGlossarySource())
        out = res.resolve(
            ResolutionRequest.of(F.mention("mention:1", "Aldric", partida_id=F.PARTIDA_A))
        )
        assert "entity:aldric-beta" in out.resolution.candidate_entity_ids

    def test_sin_filtro_de_partida_la_capa_juego_tampoco_se_defiende(self, monkeypatch):
        """La misma mutacion tambien rompe la direccion juego -> partida.

        Usa `LeakyCatalog` (no `catalog_with_partidas()`): con el catalogo REAL
        el filtro ya ocurre en `EntityCatalog.entities(partida_scope=...)`
        antes de que la cascada vea nada, asi que mutar solo
        `filter_partida_scope` no bastaria para demostrar nada con el. La
        defensa en profundidad se demuestra con la fuente que NO filtra.
        """
        monkeypatch.setattr(
            cascade_mod, "filter_partida_scope", lambda entities, partida_scope: tuple(entities)
        )
        catalog = F.LeakyCatalog((*F.CATALOG_ENTITIES, *F.PARTIDA_ENTITIES))
        res = EntityResolver(catalog, glossary=NullGlossarySource())
        out = res.resolve(ResolutionRequest.of(F.mention("mention:1", "Aldric", partida_id=None)))
        assert "entity:aldric-alpha" in out.resolution.candidate_entity_ids

    def test_un_historial_defectuoso_no_rompe_el_aislamiento_de_partida(self):
        """Linea base explicita: con `LeakyHistory` la garantia se sostiene."""
        check_aislamiento_del_historial_de_partida()

    def test_sin_la_cerradura_del_historial_se_pone_rojo_para_partida(self, monkeypatch):
        """La mutacion canonica: `history_entry_allowed` deja pasar todo."""
        monkeypatch.setattr(
            cascade_mod, "history_entry_allowed", lambda entry, ctx, catalog: True
        )
        with pytest.raises(AssertionError):
            check_aislamiento_del_historial_de_partida()

    def test_sin_la_cerradura_el_intruso_de_otra_partida_llega_a_enlazarse(self, monkeypatch):
        """Que rompe exactamente la mutacion: un LINK_EXISTING entre partidas."""
        monkeypatch.setattr(
            cascade_mod, "history_entry_allowed", lambda entry, ctx, catalog: True
        )
        history = F.LeakyHistory()
        history.record(
            workspace=WS, surfaces=["Ex Nihilo"], entity_id="entity:intruso-partida",
            entity_type="Character", action="LINK_EXISTING", confidence=0.99,
            resolution_id="resolution:y", partida_id=F.PARTIDA_B,
        )
        res = EntityResolver(
            F.catalog_with_partidas(), glossary=NullGlossarySource(), history=history
        )
        out = res.resolve(
            ResolutionRequest.of(F.mention("mention:1", "Ex Nihilo", partida_id=F.PARTIDA_A))
        )
        assert out.resolution.selected_entity_id == "entity:intruso-partida"

    def test_la_cuarta_comprobacion_usa_el_catalogo_no_solo_la_entrada(self):
        """Una entrada que MIENTE sobre su partida tampoco basta.

        `history_entry_allowed` no se fia solo de `entry.partida_id` (chequeo
        2): tambien coteja contra `catalog.get(...).partida_id` (chequeo 4).
        Aqui la entrada dice `partida_id=PARTIDA_A` pero apunta a una entidad
        que el catalogo real atribuye a `PARTIDA_B` — la mentira en el VALOR de
        la entrada no debe bastar para colarse.
        """
        history = ResolutionHistory()
        history.record(
            workspace=WS, surfaces=["Aldric"], entity_id="entity:aldric-beta",
            entity_type="Character", action="LINK_EXISTING", confidence=0.99,
            resolution_id="resolution:z", partida_id=F.PARTIDA_A,
        )
        res = EntityResolver(
            F.catalog_with_partidas(), glossary=NullGlossarySource(), history=history
        )
        out = res.resolve(
            ResolutionRequest.of(F.mention("mention:1", "Aldric", partida_id=F.PARTIDA_A))
        )
        assert "entity:aldric-beta" not in out.resolution.candidate_entity_ids

    def test_la_mutacion_de_partida_no_afecta_a_las_demas_reglas(self, monkeypatch):
        """Una mutacion de partida no debe romper comprobaciones ajenas."""
        monkeypatch.setattr(
            cascade_mod, "filter_partida_scope", lambda entities, partida_scope: tuple(entities)
        )
        check_aislamiento_de_workspace()
        check_respeto_de_tipos()
        check_estabilidad_de_provisionales()

    def test_invariante_resolutor_ciego_entre_partidas(self):
        """EL test del invariante: dos partidas, mismo nombre, CERO fusion.

        Codigo intacto, sin mutar nada: es la propia definicion operativa del
        Invariante 1 de M2 — "una entidad nacida en una partida JAMAS se
        fusiona con una entidad de otra partida" — comprobada en las dos
        direcciones a la vez.
        """
        catalog = F.catalog_with_partidas()

        out_a = EntityResolver(catalog, glossary=NullGlossarySource()).resolve(
            ResolutionRequest.of(F.mention("mention:1", "Aldric", partida_id=F.PARTIDA_A))
        )
        assert out_a.resolution.selected_entity_id == "entity:aldric-alpha"
        assert "entity:aldric-beta" not in out_a.resolution.candidate_entity_ids

        out_b = EntityResolver(catalog, glossary=NullGlossarySource()).resolve(
            ResolutionRequest.of(F.mention("mention:2", "Aldric", partida_id=F.PARTIDA_B))
        )
        assert out_b.resolution.selected_entity_id == "entity:aldric-beta"
        assert "entity:aldric-alpha" not in out_b.resolution.candidate_entity_ids

        assert out_a.resolution.selected_entity_id != out_b.resolution.selected_entity_id


# ==========================================================================
# 2. Mutacion: quitar el respeto de tipos
# ==========================================================================
class TestMutacionTipos:
    def test_sin_compatibilidad_de_tipos_se_pone_rojo(self, monkeypatch):
        """`types_compatible` pasa a decir que todo es compatible."""
        monkeypatch.setattr(cascade_mod, "types_compatible", lambda a, b: True)
        with pytest.raises(AssertionError):
            check_respeto_de_tipos()

    def test_sin_respeto_de_tipos_un_location_se_enlaza_a_una_faction(self, monkeypatch):
        monkeypatch.setattr(cascade_mod, "types_compatible", lambda a, b: True)
        res = EntityResolver(F.catalog(), glossary=F.glossary())
        out = res.resolve(
            ResolutionRequest.of(
                F.mention("mention:1", "Umbra", types=(("Location", 0.95),))
            )
        )
        assert out.resolution.action == "LINK_EXISTING"
        assert out.resolution.selected_entity_id == "entity:umbra-faccion"

    def test_hacen_falta_LAS_DOS_cerraduras_para_abrir_la_puerta(self, monkeypatch):
        """El respeto de tipos tiene dos cerraduras y hay que forzar las dos.

        La penalizacion (`type_conflict_penalty`) hunde la puntuacion por debajo
        del umbral de enlace, y el umbral de anulacion (`type_override_score`,
        inalcanzable por defecto) manda a `REVIEW` antes incluso de mirarla.
        Solo anulando ambas reaparece el enlace peligroso: es la demostracion de
        que ninguna de las dos sobra.
        """
        res = EntityResolver(
            F.catalog(), glossary=F.glossary(),
            config=ResolutionConfig(type_override_score=0.0, type_conflict_penalty=0.0),
        )
        out = res.resolve(
            ResolutionRequest.of(
                F.mention("mention:1", "Umbra", types=(("Location", 0.95),))
            )
        )
        assert out.resolution.action == "LINK_EXISTING"

    def test_anular_la_penalizacion_no_basta_para_enlazar(self, monkeypatch):
        """Defensa en profundidad: la penalizacion es un peso, la regla es la regla.

        Aunque la penalizacion de tipos se ponga a cero, el conflicto sigue
        mandando a `REVIEW`. Si esta prueba se pusiera verde en `LINK_EXISTING`,
        significaria que el respeto de tipos era solo un numero.
        """
        res = EntityResolver(
            F.catalog(), glossary=F.glossary(),
            config=ResolutionConfig(type_conflict_penalty=0.0),
        )
        out = res.resolve(
            ResolutionRequest.of(
                F.mention("mention:1", "Umbra", types=(("Location", 0.95),))
            )
        )
        assert out.resolution.action == "REVIEW"

    def test_ablacionar_el_paso_de_tipos_no_abre_la_puerta(self):
        """`disabled_steps={'types'}` quita el bonus, NO el invariante.

        REGRESION H1. Este test pasaba antes por OMISION: sin
        `context_entity_ids` el candidato se quedaba en 1.00 y no alcanzaba el
        umbral de anulacion. Con el bonus de contexto llegaba a 1.12 y, al
        compararse contra la puntuacion SIN recortar, superaba el 1.01 que se
        creia inalcanzable: `LINK_EXISTING` de una `Location` a una `Faction`,
        ademas con el `entity_type` reetiquetado en silencio. Ahora la
        comparacion usa la puntuacion recortada, que si esta acotada por 1.0.
        """
        res = EntityResolver(
            F.catalog(), glossary=F.glossary(),
            config=ResolutionConfig(disabled_steps=frozenset({"types"})),
        )
        out = res.resolve(
            ResolutionRequest.of(
                F.mention("mention:1", "Umbra", types=(("Location", 0.95),)),
                context_entity_ids=("entity:umbra-faccion",),
            )
        )
        assert out.candidates[0].raw_score > 1.0, "el caso debe saturar el techo"
        assert out.resolution.action == "REVIEW"
        assert "TYPE_CONFLICT" in out.resolution.reason_codes
        assert out.resolution.selected_entity_id is None
        assert out.resolution.entity_type == "Location", "sin reetiquetado silencioso"

    def test_el_umbral_de_anulacion_se_compara_contra_una_magnitud_acotada(self):
        """La cota solo es cota si lo que compara esta acotado (H1)."""
        res = EntityResolver(F.catalog(), glossary=F.glossary())
        out = res.resolve(
            ResolutionRequest.of(
                F.mention("mention:1", "Umbra", types=(("Location", 0.95),)),
                context_entity_ids=("entity:umbra-faccion",),
            )
        )
        assert all(c.score <= 1.0 for c in out.candidates)
        assert ResolutionConfig().type_override_score > 1.0
        assert out.resolution.action == "REVIEW"


# ==========================================================================
# 3. Mutacion: identificadores no deterministas
# ==========================================================================
class TestMutacionDeterminismo:
    def test_un_id_derivado_no_determinista_se_pone_rojo(self, monkeypatch):
        counter = {"n": 0}
        original = resolver_mod.derive_entity_id

        def unstable(**kwargs):
            counter["n"] += 1
            return f"{original(**kwargs)}-{counter['n']}"

        monkeypatch.setattr(resolver_mod, "derive_entity_id", unstable)
        with pytest.raises(AssertionError):
            check_estabilidad_de_provisionales()

    def test_quitar_el_workspace_del_id_derivado_provoca_colision(self, monkeypatch):
        """Sin workspace en el hash, dos bovedas comparten identidad provisional."""
        original = resolver_mod.derive_entity_id

        def sin_workspace(**kwargs):
            return original(**{**kwargs, "workspace": "unico"})

        monkeypatch.setattr(resolver_mod, "derive_entity_id", sin_workspace)
        ids = []
        for ws in (WS, OTHER):
            res = EntityResolver(InMemoryEntityCatalog(), glossary=NullGlossarySource())
            out = res.resolve(
                ResolutionRequest.of(
                    F.mention("mention:1", "Consejo Umbra", workspace=ws,
                              types=(("Faction", 0.4),), confidence=0.4)
                )
            )
            ids.append(out.resolution.assigned_entity_id)
        assert ids[0] == ids[1], "la mutacion debe provocar exactamente esta colision"

    def test_sin_la_mutacion_no_hay_colision_entre_bovedas(self):
        ids = []
        for ws in (WS, OTHER):
            res = EntityResolver(InMemoryEntityCatalog(), glossary=NullGlossarySource())
            out = res.resolve(
                ResolutionRequest.of(
                    F.mention("mention:1", "Consejo Umbra", workspace=ws,
                              types=(("Faction", 0.4),), confidence=0.4)
                )
            )
            ids.append(out.resolution.assigned_entity_id)
        assert ids[0] != ids[1]


# ==========================================================================
# 4. Mutacion: desempate y ambiguedad
# ==========================================================================
class TestMutacionAmbiguedad:
    def test_margen_de_ambiguedad_a_cero_se_pone_rojo(self):
        """Sin margen, el resolutor elige "el primero" y eso es una moneda al aire."""
        with pytest.raises(AssertionError):
            check_ambiguedad_no_se_resuelve_a_dedo(ResolutionConfig(ambiguity_margin=0.0))

    def test_orden_de_candidatos_invertido_no_cambia_la_decision(self, monkeypatch):
        """El desempate no puede depender del orden de llegada de los candidatos.

        Se invierte el orden en que el catalogo entrega las entidades; la
        decision debe ser identica byte a byte.
        """
        base = EntityResolver(F.catalog(), glossary=F.glossary()).resolve(
            ResolutionRequest.of(F.mention("mention:1", "Kaede"))
        )

        class ReversedCatalog(InMemoryEntityCatalog):
            def entities(self, workspace, *, partida_scope=None):
                return tuple(
                    reversed(super().entities(workspace, partida_scope=partida_scope))
                )

        flipped = EntityResolver(
            ReversedCatalog(F.CATALOG_ENTITIES), glossary=F.glossary()
        ).resolve(ResolutionRequest.of(F.mention("mention:1", "Kaede")))
        assert base.resolution.to_json() == flipped.resolution.to_json()
