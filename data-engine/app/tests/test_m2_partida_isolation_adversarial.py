# -*- coding: utf-8 -*-
"""Bateria adversarial de M2 (docs/v3/49-multipartida-diseno.md, INVARIANTE 1).

Objetivo: romper el aislamiento por partida por CUALQUIER camino, no solo el
que ya ejercitan los tests unitarios de cada pieza. Cubre:

1. Escenarios end-to-end del resolutor completo (catalogo + historial +
   cascada + emision), con homonimos EXACTOS entre dos partidas del mismo
   juego, por cada via de fuga conocida.
2. La asimetria declarada de `InMemoryEntityCatalog.get()` (sin filtrar): se
   rastrean TODOS los call sites de produccion, no solo los de test.
3. El empate partida/capa-juego en `ResolutionHistory.lookup()`.
4. Mutacion de cada cerradura por separado y de las dos a la vez.
5. Retrocompatibilidad: material sin `partida_id` se resuelve identico a como
   lo hacia antes de M2 (el resolutor con `partida_id=None` en todo debe
   producir el mismo documento que antes de que existiera el campo).
6. Contratos: `partida_id` malformado, mezcla en un mismo grupo de
   correferencia, round-trip sin inyeccion.

No repite tests ya existentes en `test_knowledge_v3_resolution_mutations.py`
(`check_aislamiento_de_partida`, `check_juego_no_captura_entidad_de_partida`,
`test_invariante_resolutor_ciego_entre_partidas`, etc.) salvo cuando hace falta
un escenario end-to-end mas rico que el que ya cubren.
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

from knowledge_v3.contracts import EntityMention, EntityResolution, V3ContractError  # noqa: E402
from knowledge_v3.contracts.base import schema_validator  # noqa: E402
from knowledge_v3.resolution import (  # noqa: E402
    CatalogEntity,
    EntityCatalog,
    EntityResolver,
    HistoryEntry,
    InMemoryEntityCatalog,
    NullGlossarySource,
    ResolutionHistory,
    ResolutionInputError,
    ResolutionRequest,
    normalize_surface,
)
from knowledge_v3.resolution import cascade as cascade_mod  # noqa: E402
from knowledge_v3.resolution import catalog as catalog_mod  # noqa: E402
from knowledge_v3.resolution import history as history_mod  # noqa: E402
from knowledge_v3.resolution import resolver as resolver_mod  # noqa: E402

WS = F.WORKSPACE


def resolver(**kwargs):
    kwargs.setdefault("glossary", NullGlossarySource())
    return EntityResolver(F.catalog_with_partidas(), **kwargs)


# ==========================================================================
# 1) Escenarios end-to-end, cada via de fuga conocida
# ==========================================================================
class TestFugasEndToEnd:
    def test_a_historial_poblado_por_A_no_alcanza_a_B_misma_superficie(self):
        """(a) A resuelve 'Capitan Verros' -> se fija en el historial de A.

        Una consulta desde B con la MISMA superficie normalizada no debe
        heredar esa identidad: ni como candidato de historial, ni como
        `selected_entity_id`.
        """
        catalog = InMemoryEntityCatalog(
            (
                CatalogEntity(
                    "entity:verros-a", WS, "Character", "Capitan Verros",
                    partida_id=F.PARTIDA_A,
                ),
                CatalogEntity(
                    "entity:verros-b", WS, "Character", "Capitan Verros",
                    partida_id=F.PARTIDA_B,
                ),
            )
        )
        history = ResolutionHistory()
        res = EntityResolver(catalog, history=history)
        out_a = res.resolve(
            ResolutionRequest.of(
                F.mention("mention:1", "Capitan Verros", partida_id=F.PARTIDA_A)
            )
        )
        assert out_a.resolution.selected_entity_id == "entity:verros-a"
        assert len(history) == 1

        out_b = res.resolve(
            ResolutionRequest.of(
                F.mention("mention:2", "Capitan Verros", partida_id=F.PARTIDA_B)
            )
        )
        assert out_b.resolution.selected_entity_id != "entity:verros-a"
        assert out_b.resolution.selected_entity_id == "entity:verros-b"
        assert "entity:verros-a" not in out_b.resolution.candidate_entity_ids
        assert "HISTORY_SESSION" not in out_b.resolution.reason_codes or (
            out_b.resolution.selected_entity_id != "entity:verros-a"
        )

    def test_a_historial_de_A_no_fuga_cuando_B_no_tiene_catalogo_propio(self):
        """Variante mas dura de (a): B NO tiene entidad propia en el catalogo.

        Sin homonimo propio de B, si la fuga existiera el resolutor enlazaria
        directamente con la entidad de A via historial. Debe, en cambio,
        tratarla como desconocida (CREATE_* o REVIEW), nunca LINK a A.
        """
        catalog = InMemoryEntityCatalog(
            (
                CatalogEntity(
                    "entity:verros-a", WS, "Character", "Capitan Verros",
                    partida_id=F.PARTIDA_A,
                ),
            )
        )
        history = ResolutionHistory()
        res = EntityResolver(catalog, history=history)
        res.resolve(
            ResolutionRequest.of(
                F.mention("mention:1", "Capitan Verros", partida_id=F.PARTIDA_A)
            )
        )
        out_b = res.resolve(
            ResolutionRequest.of(
                F.mention("mention:2", "Capitan Verros", partida_id=F.PARTIDA_B)
            )
        )
        assert out_b.resolution.selected_entity_id != "entity:verros-a"
        assert out_b.resolution.action != "LINK_EXISTING"

    def test_b_entidad_de_a_promovida_a_catalogo_no_es_vista_por_b(self):
        """(b) 'Promocion' de A a catalogo (misma tabla, sigue con partida_id=A).

        Simula que la entidad de A ya paso a formar parte del catalogo (no
        solo del historial). Una consulta de B, con o sin historial de por
        medio, no debe verla como candidata.
        """
        catalog = InMemoryEntityCatalog(
            (
                CatalogEntity(
                    "entity:verros-a", WS, "Character", "Capitan Verros",
                    partida_id=F.PARTIDA_A,
                ),
            )
        )
        res = EntityResolver(catalog)
        out_b = res.resolve(
            ResolutionRequest.of(
                F.mention("mention:1", "Capitan Verros", partida_id=F.PARTIDA_B)
            )
        )
        assert out_b.resolution.selected_entity_id != "entity:verros-a"
        assert "entity:verros-a" not in out_b.resolution.candidate_entity_ids
        assert out_b.resolution.action != "LINK_EXISTING"

    def test_c_capa_juego_no_captura_entidad_de_partida_con_homonimo_en_lore(self):
        """(c) Resolucion en capa juego (None) con homonimo en la partida A.

        Ademas del caso ya cubierto en mutations (sin homonimo de lore), aqui
        el LORE SI tiene una entidad con el mismo nombre: hay que comprobar
        que el lore captura LA SUYA, no la de A, y que A nunca aparece entre
        los candidatos de la resolucion de capa juego.
        """
        catalog = InMemoryEntityCatalog(
            (
                CatalogEntity("entity:verros-lore", WS, "Character", "Capitan Verros"),
                CatalogEntity(
                    "entity:verros-a", WS, "Character", "Capitan Verros",
                    partida_id=F.PARTIDA_A,
                ),
            )
        )
        res = EntityResolver(catalog)
        out = res.resolve(
            ResolutionRequest.of(F.mention("mention:1", "Capitan Verros", partida_id=None))
        )
        assert out.resolution.selected_entity_id == "entity:verros-lore"
        assert "entity:verros-a" not in out.resolution.candidate_entity_ids

    def test_d_grupo_con_partida_id_mixto_se_rechaza_con_error_claro(self):
        """(d) Un grupo de correferencia con menciones de A y B: rechazo explicito.

        `_read_envelope` debe fallar con `ResolutionInputError` (no procesar
        en silencio adoptando la partida de la primera mencion).
        """
        req = ResolutionRequest.of(
            F.mention("mention:1", "Capitan Verros", partida_id=F.PARTIDA_A),
            F.mention("mention:2", "Capitan Verros", partida_id=F.PARTIDA_B),
        )
        with pytest.raises(ResolutionInputError):
            resolver().resolve(req)

    def test_d_grupo_mixto_partida_vs_capa_juego_tambien_se_rechaza(self):
        """(d) variante: una mencion de partida A y otra de capa juego (None)."""
        req = ResolutionRequest.of(
            F.mention("mention:1", "Capitan Verros", partida_id=F.PARTIDA_A),
            F.mention("mention:2", "Capitan Verros", partida_id=None),
        )
        with pytest.raises(ResolutionInputError):
            resolver().resolve(req)

    def test_e_partida_scope_ausente_no_ve_candidatos_de_partida(self):
        """(e) `partida_scope=None` (defecto) NO ve entidades con `partida_id` fijado.

        Ejercita `EntityCatalog.entities()` directamente (no solo via
        resolver) para que quede fijado a nivel de interfaz, no solo de
        integracion end-to-end.
        """
        catalog = F.catalog_with_partidas()
        visible_default = catalog.entities(WS)
        visible_explicit_none = catalog.entities(WS, partida_scope=None)
        assert visible_default == visible_explicit_none
        assert all(e.partida_id is None for e in visible_default)
        assert "entity:aldric-alpha" not in {e.entity_id for e in visible_default}
        assert "entity:aldric-beta" not in {e.entity_id for e in visible_default}


# ==========================================================================
# 2) La asimetria declarada de InMemoryEntityCatalog.get()
# ==========================================================================
class TestAsimetriaGet:
    def test_get_sin_filtrar_devuelve_entidad_de_otra_partida_directo(self):
        """Documenta la asimetria: `get()` de bajo nivel NO filtra por partida.

        Esto es DELIBERADO segun la documentacion del modulo (chequeo de
        propiedad para `history_entry_allowed`). El peligro es que algun otro
        camino de produccion la use como si filtrase.
        """
        catalog = F.catalog_with_partidas()
        # Pedimos la entidad de alpha con scope de beta: si "get" filtrase,
        # devolveria None. Comprobamos que efectivamente NO filtra (para saber
        # que cualquier consumidor debe tratarlo como consulta de propiedad,
        # nunca como fuente de candidatos).
        entity = catalog.get(WS, "entity:aldric-alpha", partida_scope=F.PARTIDA_B)
        assert entity is not None
        assert entity.partida_id == F.PARTIDA_A

    def test_unico_call_site_de_produccion_es_history_entry_allowed(self):
        """Rastreo estatico de todos los `catalog.get(` / `.get(` de produccion.

        Si aparece un NUEVO call site de `EntityCatalog.get()` en produccion
        que no sea la comprobacion de propiedad de `history_entry_allowed`,
        este test debe fallar y forzar su revision: es exactamente el patron
        de fuga que la asimetria hace posible.
        """
        import ast

        # Directorios de produccion a auditar: todo el subsistema de
        # resolucion, mas el punto de entrada legado `review/resolver.py`
        # (que M2 dice explicitamente que NO toca, pero conviene comprobar).
        src_dirs = [
            Path(catalog_mod.__file__).resolve().parent,
            Path(catalog_mod.__file__).resolve().parents[1] / "review",
        ]
        production_files = [
            p
            for d in src_dirs
            if d.is_dir()
            for p in d.glob("*.py")
            if not p.name.startswith("test_")
        ]
        # Solo cuentan las llamadas `<algo llamado catalog>.get(...)`: son las
        # unicas que pueden ser un `EntityCatalog.get()` real. Filtra el ruido
        # de `dict.get()` (`self._by_workspace.get(...)`, `bucket.get(...)`,
        # `totals.get(...)`, etc.) que domina un grep/AST ingenuo.
        call_sites = []
        for path in production_files:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get"
                ):
                    continue
                receiver = node.func.value
                receiver_name = getattr(receiver, "id", None) or getattr(
                    receiver, "attr", None
                )
                if receiver_name and "catalog" in receiver_name.lower():
                    call_sites.append((path.name, node.lineno, receiver_name))
        # Se conoce y se acepta exactamente un call site de produccion: el de
        # `cascade.py::history_entry_allowed`. Cualquier otro es una sorpresa
        # y, dada la asimetria documentada, un candidato a P0.
        assert call_sites == [("cascade.py", 261, "catalog")], (
            f"call sites de <catalog>.get() inesperados: {call_sites}. Si es "
            f"uno nuevo, comprobar que NO alimenta candidatos de resolucion "
            f"sin pasar por filter_partida_scope."
        )

    def test_entities_si_filtra_por_partida_a_diferencia_de_get(self):
        """Contraste explicito: `entities()` SI filtra; `get()` NO. Ambas cosas a la vez."""
        catalog = F.catalog_with_partidas()
        via_entities = {
            e.entity_id for e in catalog.entities(WS, partida_scope=F.PARTIDA_B)
        }
        assert "entity:aldric-alpha" not in via_entities
        via_get = catalog.get(WS, "entity:aldric-alpha", partida_scope=F.PARTIDA_B)
        assert via_get is not None


# ==========================================================================
# 3) El empate partida/capa-juego en lookup()
# ==========================================================================
class TestEmpateHistorial:
    def test_partida_diverge_del_lore_gana_la_entrada_propia_de_partida(self):
        """Misma superficie fijada en la partida Y en la capa juego: gana la propia.

        Escenario de divergencia real: la partida decidio que "Umbra" es OTRA
        entidad distinta de la del lore. El fallback a capa juego NO debe
        re-unificarlas: `lookup(partida_scope=Y)` debe devolver la entrada de
        Y, no la de la capa juego, aunque ambas existan para la misma
        superficie normalizada.
        """
        history = ResolutionHistory()
        history.record(
            workspace=WS, surfaces=["Umbra"], entity_id="entity:umbra-lore",
            entity_type="Faction", action="LINK_EXISTING", confidence=0.9,
            resolution_id="resolution:lore", partida_id=None,
        )
        history.record(
            workspace=WS, surfaces=["Umbra"], entity_id="entity:umbra-alpha",
            entity_type="Character", action="CREATE_PROVISIONAL", confidence=0.5,
            resolution_id="resolution:alpha", partida_id=F.PARTIDA_A,
        )
        entry = history.lookup(WS, "Umbra", partida_scope=F.PARTIDA_A)
        assert entry is not None
        assert entry.entity_id == "entity:umbra-alpha"
        assert entry.partida_id == F.PARTIDA_A

    def test_empate_es_deterministico_repetido(self):
        """El desempate no depende del orden de escritura ni se degrada con el tiempo."""
        history_ab = ResolutionHistory()
        history_ba = ResolutionHistory()
        for h in (history_ab, history_ba):
            pass
        history_ab.record(
            workspace=WS, surfaces=["Umbra"], entity_id="entity:umbra-lore",
            entity_type="Faction", action="LINK_EXISTING", confidence=0.9,
            resolution_id="resolution:lore", partida_id=None,
        )
        history_ab.record(
            workspace=WS, surfaces=["Umbra"], entity_id="entity:umbra-alpha",
            entity_type="Character", action="CREATE_PROVISIONAL", confidence=0.5,
            resolution_id="resolution:alpha", partida_id=F.PARTIDA_A,
        )
        history_ba.record(
            workspace=WS, surfaces=["Umbra"], entity_id="entity:umbra-alpha",
            entity_type="Character", action="CREATE_PROVISIONAL", confidence=0.5,
            resolution_id="resolution:alpha", partida_id=F.PARTIDA_A,
        )
        history_ba.record(
            workspace=WS, surfaces=["Umbra"], entity_id="entity:umbra-lore",
            entity_type="Faction", action="LINK_EXISTING", confidence=0.9,
            resolution_id="resolution:lore", partida_id=None,
        )
        for h in (history_ab, history_ba):
            assert h.lookup(WS, "Umbra", partida_scope=F.PARTIDA_A).entity_id == (
                "entity:umbra-alpha"
            )
            assert h.lookup(WS, "Umbra", partida_scope=None).entity_id == "entity:umbra-lore"

    def test_solo_lore_en_historial_partida_hereda_capa_juego(self):
        """Sin entrada propia de la partida, SI cae al lore (direccion permitida)."""
        history = ResolutionHistory()
        history.record(
            workspace=WS, surfaces=["Umbra"], entity_id="entity:umbra-lore",
            entity_type="Faction", action="LINK_EXISTING", confidence=0.9,
            resolution_id="resolution:lore", partida_id=None,
        )
        entry = history.lookup(WS, "Umbra", partida_scope=F.PARTIDA_A)
        assert entry is not None
        assert entry.entity_id == "entity:umbra-lore"

    def test_solo_partida_en_historial_no_es_vista_desde_capa_juego(self):
        """Direccion inversa PROHIBIDA: capa juego nunca ve la entrada de una partida."""
        history = ResolutionHistory()
        history.record(
            workspace=WS, surfaces=["Umbra"], entity_id="entity:umbra-alpha",
            entity_type="Character", action="CREATE_PROVISIONAL", confidence=0.5,
            resolution_id="resolution:alpha", partida_id=F.PARTIDA_A,
        )
        entry = history.lookup(WS, "Umbra", partida_scope=None)
        assert entry is None


# ==========================================================================
# 4) Mutacion: cada cerradura por separado, y las dos a la vez
# ==========================================================================
def _run_two_partidas_scenario(res: EntityResolver) -> tuple[str | None, str | None]:
    out_a = res.resolve(
        ResolutionRequest.of(F.mention("mention:1", "Aldric", partida_id=F.PARTIDA_A))
    )
    out_b = res.resolve(
        ResolutionRequest.of(F.mention("mention:2", "Aldric", partida_id=F.PARTIDA_B))
    )
    return out_a.resolution.selected_entity_id, out_b.resolution.selected_entity_id


class TestMutacionDeCerraduras:
    def test_ambas_cerraduras_intactas_no_fusionan(self):
        res = EntityResolver(F.catalog_with_partidas())
        id_a, id_b = _run_two_partidas_scenario(res)
        assert id_a == "entity:aldric-alpha"
        assert id_b == "entity:aldric-beta"

    def test_quitar_solo_filter_partida_scope_el_catalogo_sigue_prefiltrando(
        self, monkeypatch
    ):
        """Quitar `filter_partida_scope` (defensa de la cascada) sola no basta para
        romper el invariante si `EntityCatalog.entities()` YA filtro aguas arriba
        (que es el camino real de `resolver.resolve`). Documenta que la segunda
        cerradura de la cascada es defensa en profundidad, no la unica barrera.
        """
        monkeypatch.setattr(
            cascade_mod, "filter_partida_scope", lambda entities, partida_scope: tuple(entities)
        )
        res = EntityResolver(F.catalog_with_partidas())
        id_a, id_b = _run_two_partidas_scenario(res)
        assert id_a == "entity:aldric-alpha"
        assert id_b == "entity:aldric-beta"

    def test_quitar_solo_filtro_del_catalogo_la_cascada_sigue_defendiendo(self):
        """Con un catalogo DEFECTUOSO (no filtra `entities()`), la cascada real
        (`filter_partida_scope`, intacta) debe seguir bastando para el invariante.
        """
        class LeakyPartidaCatalog(InMemoryEntityCatalog):
            def entities(self, workspace, *, partida_scope=None):
                # Ignora partida_scope a proposito (bug realista, Cypher sin
                # `WHERE partida_id IS NULL OR partida_id = $scope`): devuelve
                # TODO lo del workspace, de cualquier partida.
                bucket = self._by_workspace.get(workspace, {})
                return tuple(bucket[k] for k in sorted(bucket))

        base = F.catalog_with_partidas()
        leaky = LeakyPartidaCatalog()
        for ws in base.workspaces():
            for eid in sorted(base._by_workspace[ws]):
                leaky.add(base._by_workspace[ws][eid])
        res = EntityResolver(leaky)
        id_a, id_b = _run_two_partidas_scenario(res)
        assert id_a == "entity:aldric-alpha"
        assert id_b == "entity:aldric-beta"

    def test_quitar_las_dos_cerraduras_el_invariante_cae_y_los_tests_lo_cazan(
        self, monkeypatch
    ):
        """Mutacion doble: `filter_partida_scope` neutralizada Y catalogo con fuga.

        Con las dos cerraduras caidas a la vez, el invariante SI se rompe: el
        propio test de invariante (equivalente al de mutations) debe fallar,
        demostrando que hacen falta las dos, no solo una, para sostenerlo.
        """
        class LeakyPartidaCatalog(InMemoryEntityCatalog):
            def entities(self, workspace, *, partida_scope=None):
                return tuple(self._by_workspace.get(workspace, {}).values())

        base = F.catalog_with_partidas()
        leaky = LeakyPartidaCatalog()
        for ws in base.workspaces():
            for eid in sorted(base._by_workspace[ws]):
                leaky.add(base._by_workspace[ws][eid])

        monkeypatch.setattr(
            cascade_mod, "filter_partida_scope", lambda entities, partida_scope: tuple(entities)
        )
        res = EntityResolver(leaky)
        out_b = res.resolve(
            ResolutionRequest.of(F.mention("mention:2", "Aldric", partida_id=F.PARTIDA_B))
        )
        # Con las dos cerraduras caidas, alpha SI entra como candidato de beta:
        # esto es justo la prueba de que la mutacion doble rompe el invariante
        # (si este assert empezase a fallar, alguna cerradura sobrante lo
        # estaria sosteniendo igual y el test de mutacion perderia sentido).
        assert "entity:aldric-alpha" in out_b.resolution.candidate_entity_ids

    def test_codigo_partida_isolated_SI_aparece_cuando_el_catalogo_tiene_fuga(
        self, monkeypatch
    ):
        """Trazabilidad, camino DEFENSA EN PROFUNDIDAD: con un catalogo que NO
        prefiltra por partida, `filter_partida_scope` de la cascada es quien
        descarta, y ENTONCES si se anota `PARTIDA_ISOLATED`.
        """
        class LeakyPartidaCatalog(InMemoryEntityCatalog):
            def entities(self, workspace, *, partida_scope=None):
                bucket = self._by_workspace.get(workspace, {})
                return tuple(bucket[k] for k in sorted(bucket))

        catalog = LeakyPartidaCatalog(
            (
                CatalogEntity(
                    "entity:verros-a", WS, "Character", "Capitan Verros",
                    partida_id=F.PARTIDA_A,
                ),
            )
        )
        res = EntityResolver(catalog)
        out = res.resolve(
            ResolutionRequest.of(
                F.mention("mention:1", "Capitan Verros", partida_id=F.PARTIDA_B)
            )
        )
        assert "PARTIDA_ISOLATED" in out.resolution.reason_codes
        cascade_meta = out.resolution.metadata["cascade"]
        assert cascade_meta["discarded_other_partida"] == 1

    def test_HALLAZGO_partida_isolated_NO_aparece_en_el_camino_honesto(self):
        """HALLAZGO (trazabilidad, P2): con el catalogo REAL (que ya filtra en
        `entities(partida_scope=...)`, el camino de produccion normal via
        `EntityResolver.resolve`), un homonimo descartado por pertenecer a
        OTRA partida deja CERO rastro en `reason_codes` o en
        `metadata['cascade']['discarded_other_partida']`.

        Esto es una consecuencia directa de que el filtrado real ocurre ANTES
        de `run_cascade` (en `EntityCatalog.entities()`), no dentro de ella:
        `filter_partida_scope`/`discarded_other_partida` solo cuentan lo que
        la SEGUNDA cerradura (defensa en profundidad) tuvo que tirar, y con un
        catalogo correcto esa cifra es siempre 0. El docstring de `cascade.py`
        ("el codigo PARTIDA_ISOLATED aparece en los diagnosticos cuando se
        filtra") es cierto solo para el camino de la mutacion/bug, no para el
        camino normal — un humano revisando por que 'Capitan Verros' de la
        partida B salio como CREATE_PROVISIONAL no tiene forma de distinguir,
        leyendo la resolucion, "habia un homonimo en otra partida" de "no
        habia nada parecido en ningun sitio". El mismo hueco existe, por
        construccion identica, para WORKSPACE_ISOLATED.
        """
        catalog = InMemoryEntityCatalog(
            (
                CatalogEntity(
                    "entity:verros-a", WS, "Character", "Capitan Verros",
                    partida_id=F.PARTIDA_A,
                ),
            )
        )
        res = EntityResolver(catalog)
        out = res.resolve(
            ResolutionRequest.of(
                F.mention("mention:1", "Capitan Verros", partida_id=F.PARTIDA_B)
            )
        )
        # El aislamiento SI se sostiene (no hay fusion, esto no es P0):
        assert out.resolution.selected_entity_id != "entity:verros-a"
        # ... pero la traza NO lo refleja (el hallazgo real, P2):
        assert "PARTIDA_ISOLATED" not in out.resolution.reason_codes
        assert out.resolution.metadata["cascade"]["discarded_other_partida"] == 0
        # DECISION DE M3 (docs/v3/49, "M3 implementado", pendiente 4): este
        # hueco NO se cierra en el writer. `writer/admission.py` juzga UN
        # documento de plan ya sellado -- nunca ve la lista de candidatos que
        # el resolutor descarto para llegar a esa decision, esa informacion
        # muere dentro de `CascadeResult` varios pasos antes de que exista un
        # plan que sellar. Cerrarlo exigiria transportar el descarte HASTA el
        # plan (un campo nuevo en `ClaimProposal`/`GraphMutationPlan`, con su
        # propio bump/tag de freeze, §9), que es cirugia de contrato, no de
        # admision. Queda como TODO explicito de un bloque futuro si un
        # operador necesita de verdad esa trazabilidad en produccion.

    def test_codigo_partida_isolated_ausente_cuando_no_hay_descarte(self):
        """Simetria: si no hay nada que descartar por partida, el codigo no aparece."""
        res = EntityResolver(F.catalog())
        out = res.resolve(ResolutionRequest.of(F.mention("mention:1", "Daiki")))
        assert "PARTIDA_ISOLATED" not in out.resolution.reason_codes


# ==========================================================================
# 5) Retrocompatibilidad: material existente, mismo resultado
# ==========================================================================
class TestRetrocompatibilidad:
    def test_corpus_preexistente_sin_partida_produce_resultado_identico(self):
        """Todo `CATALOG_ENTITIES` es capa juego (`partida_id=None`, preexistente a
        M2). Resolver con el resolutor de M2 debe dar EXACTAMENTE el mismo
        `action`/`selected_entity_id`/`confidence`/`reason_codes` que antes de
        que existiera `partida_scope` (equivalente a `partida_scope=None`, el
        valor por defecto, sin declarar nada de M2 en la mencion).
        """
        cases = [
            ("Daiki", "LINK_EXISTING", "entity:daiki"),
            ("El Magistrado", "LINK_EXISTING", "entity:daiki"),
            ("Daiki-san", "LINK_EXISTING", "entity:daiki"),
        ]
        for surface, expected_action, expected_id in cases:
            out = resolver().resolve(
                ResolutionRequest.of(F.mention("mention:x", surface, partida_id=None))
            )
            assert out.resolution.action == expected_action
            assert out.resolution.selected_entity_id == expected_id
            assert out.resolution.partida_id is None
            assert "PARTIDA_ISOLATED" not in out.resolution.reason_codes

    def test_mencion_sin_declarar_partida_id_en_absoluto_es_igual_a_none(self):
        """El campo es opcional: omitirlo del todo se comporta como `None`."""
        req_omitido = ResolutionRequest.of(F.mention("mention:1", "Daiki"))
        req_explicito = ResolutionRequest.of(
            F.mention("mention:2", "Daiki", partida_id=None)
        )
        out_omitido = resolver().resolve(req_omitido)
        out_explicito = resolver(config=None).resolve(req_explicito)
        assert out_omitido.resolution.action == out_explicito.resolution.action
        assert (
            out_omitido.resolution.selected_entity_id
            == out_explicito.resolution.selected_entity_id
        )
        assert out_omitido.resolution.partida_id is None


# ==========================================================================
# 6) Contratos: partida_id malformado, mezcla, round-trip
# ==========================================================================
class TestContratosPartidaId:
    @pytest.mark.parametrize(
        "bad_value",
        ["", "  ", "partida con espacios", "a" * 201, "/etc/passwd", "\n", "ñ"],
    )
    def test_partida_id_malformado_falla_validacion_de_esquema(self, bad_value):
        mention = F.mention("mention:1", "Daiki", partida_id="partida:ok")
        doc = mention.to_dict()
        doc["partida_id"] = bad_value
        with pytest.raises(Exception):
            schema_validator.validate_document(doc)

    def test_partida_id_vacio_en_python_ya_se_rechaza_antes_del_esquema(self):
        """`CatalogEntity` ya lo hace (ver test_knowledge_v3_resolution.py); aqui
        se comprueba el equivalente en el contrato `EntityMention`: el modelo
        Python acepta `""` porque no valida en `__init__` (solo dataclass), asi
        que la barrera real para el mensaje es el esquema JSON, no Python.
        Documentamos ese reparto de responsabilidad explicitamente.
        """
        mention = F.mention("mention:1", "Daiki", partida_id="")
        doc = mention.to_dict()
        assert doc["partida_id"] == ""
        with pytest.raises(Exception):
            schema_validator.validate_document(doc)

    def test_round_trip_sin_partida_id_no_inyecta_null(self):
        mention = F.mention("mention:1", "Daiki", partida_id=None)
        doc = mention.to_dict()
        assert "partida_id" not in doc
        schema_validator.validate_document(doc)

    def test_round_trip_con_partida_id_se_conserva(self):
        mention = F.mention("mention:1", "Daiki", partida_id="partida:alpha")
        doc = mention.to_dict()
        assert doc["partida_id"] == "partida:alpha"
        schema_validator.validate_document(doc)

    def test_resolution_hereda_partida_id_de_las_menciones_en_el_documento(self):
        out = resolver().resolve(
            ResolutionRequest.of(F.mention("mention:1", "Aldric", partida_id=F.PARTIDA_A))
        )
        doc = out.resolution.to_dict()
        assert doc.get("partida_id") == F.PARTIDA_A
        schema_validator.validate_document(doc)

    def test_resolution_sin_partida_no_inyecta_null_en_el_documento(self):
        out = resolver().resolve(
            ResolutionRequest.of(F.mention("mention:1", "Daiki", partida_id=None))
        )
        doc = out.resolution.to_dict()
        assert "partida_id" not in doc
        schema_validator.validate_document(doc)

    def test_fixtures_gold_existentes_sin_partida_id_siguen_validando(self):
        """Retrocompatibilidad de fixtures del propio subsistema (no solo datasets
        congelados de benchmarks): `CATALOG_ENTITIES`/menciones sin partida no
        deben requerir ningun cambio para seguir siendo documentos validos.
        """
        mention = F.mention("mention:1", "Daiki")
        doc = mention.to_dict()
        assert "partida_id" not in doc
        schema_validator.validate_document(doc)
