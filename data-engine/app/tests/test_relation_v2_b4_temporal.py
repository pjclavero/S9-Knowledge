# -*- coding: utf-8 -*-
"""Bloque 4 (motor de relaciones v2): TEMPORALIDAD y VIGENCIA como modulo robusto.

Tests REALES de `relations.temporal_v2`. Cubren los casos obligatorios de la spec
B4: presente, pasado, futuro, fecha absoluta, fecha relativa, intervalo, inicio,
final, vigente, terminada, planeada, hipotetica, recurrente, "ya no", "todavia no",
cambio de estado (transicion sin sobrescribir historia), contradiccion temporal
aparente (dos fuentes en momentos distintos) y referencia no resoluble.

Todas las frases son GENERALES del espanol con entidades/eventos INVENTADOS (NO
calcos del corpus de benchmark): validan las REGLAS morfologicas/lexicas, no textos
concretos. Cada assert muerde (estado de vigencia + clase temporal del contrato y,
donde aplica, las senales). Sin skip/xfail ni asserts triviales.
"""
from __future__ import annotations

from dataclasses import dataclass

from relations.temporal_v2 import (
    STATE_TO_STATUS,
    TEMPORAL_V2_VERSION,
    TemporalResolution,
    TemporalState,
    resolve_for_pair,
    resolve_temporal,
    segment_transitions,
    temporal_scope_for_pair,
)
from relations import temporality


# ---------------------------------------------------------------------------
# Utillaje determinista
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _FakePair:
    """Par minimo con los offsets que consume `resolve_for_pair`."""

    subject_start: int
    subject_end: int
    object_start: int
    object_end: int


def _pair(seg: str, subj: str, obj: str) -> _FakePair:
    s = seg.index(subj)
    o = seg.index(obj)
    return _FakePair(s, s + len(subj), o, o + len(obj))


# ---------------------------------------------------------------------------
# Contrato / version del modulo
# ---------------------------------------------------------------------------
def test_version_is_stable_string():
    assert TEMPORAL_V2_VERSION == "relation-temporal-v2-1.0.0"


def test_resolution_is_frozen_and_deterministic():
    seg = "El gremio Velaróbil respalda al Concilio de Tharn."
    a = resolve_temporal(seg)
    b = resolve_temporal(seg)
    assert isinstance(a, TemporalResolution)
    assert (a.state, a.temporal_status, a.rationale) == (b.state, b.temporal_status, b.rationale)
    try:
        a.state = TemporalState.ENDED  # type: ignore[misc]
        raised = False
    except Exception:
        raised = True
    assert raised


def test_scope_prefix_is_read_back_by_harness_mapper():
    # INVARIANTE CLAVE: la clase que emite v2 es la que el arnes deriva del scope
    # (temporality.temporal_status_of), sin reclasificar.
    for seg, expected in [
        ("Norvia gobierna el Ducado de Aldsmere.", "PRESENT"),
        ("Norvia gobernó el Ducado de Aldsmere en el 812.", "PAST"),
        ("Norvia gobernará el Ducado de Aldsmere.", "FUTURE"),
        ("Norvia ya no gobierna el Ducado de Aldsmere.", "ENDED"),
    ]:
        res = resolve_temporal(seg)
        assert res.temporal_status == expected, (seg, res.temporal_status)
        assert temporality.temporal_status_of(res.to_scope_string()) == expected


# ---------------------------------------------------------------------------
# Presente / vigente
# ---------------------------------------------------------------------------
def test_present_copula_is_active_present():
    res = resolve_temporal("Brannoc es aliado del Clan Verroth.")
    assert res.temporal_status == "PRESENT"
    assert res.state == TemporalState.ACTIVE


def test_unmarked_relational_assertion_defaults_to_present_not_atemporal():
    # Sin marca temporal alguna, una asercion de relacion es presente por defecto
    # (regla general del espanol), NO ATEMPORAL: v1 la dejaba sin alcance.
    res = resolve_temporal("El santuario de Ilmyr custodia la Corona de Vael.")
    assert res.temporal_status == "PRESENT"
    assert res.rationale in ("present_default",)
    # y por tanto tiene alcance materializable (v1 lo suprimia):
    assert res.has_temporal_signal is True


# ---------------------------------------------------------------------------
# Pasado (morfologia ampliada: preterito sg/pl e imperfecto)
# ---------------------------------------------------------------------------
def test_past_preterite_singular():
    res = resolve_temporal("Sedric fundó la Cofradia de Espadas.")
    assert res.temporal_status == "PAST"
    assert res.state == TemporalState.ENDED


def test_past_preterite_plural_is_detected():
    # v1 (regex \\w+o) NO capturaba el preterito plural -aron/-ieron.
    res = resolve_temporal("Los cartografos de Oslen trazaron la ruta del Meridiano.")
    assert res.temporal_status == "PAST"
    res2 = resolve_temporal("Los centinelas de Brumal sirvieron a la Casa Quen.")
    assert res2.temporal_status == "PAST"


def test_past_imperfect_is_detected():
    # v1 tampoco capturaba el imperfecto -aba/-aban.
    res = resolve_temporal("Ilka lideraba la vanguardia del Pacto de Nornel.")
    assert res.temporal_status == "PAST"


# ---------------------------------------------------------------------------
# Futuro / planeado
# ---------------------------------------------------------------------------
def test_future_tense_is_planned():
    res = resolve_temporal("Drago competirá por el trono de Karsheim.")
    assert res.temporal_status == "FUTURE"
    assert res.state == TemporalState.PLANNED


def test_future_lexical_plan():
    res = resolve_temporal("El Concilio planea nombrar regente a Merla.")
    assert res.temporal_status == "FUTURE"
    assert res.state == TemporalState.PLANNED


# ---------------------------------------------------------------------------
# Fecha absoluta / relativa / intervalo
# ---------------------------------------------------------------------------
def test_absolute_date_is_event_time():
    res = resolve_temporal("La Orden de Fresno cayó en el 947.")
    assert res.temporal_status == "PAST"
    assert "947" in res.dates
    assert res.signals.event_time == "947"


def test_relative_expression_is_captured():
    res = resolve_temporal("Tres años después, Kesar heredó el bastón de Umbral.")
    assert res.temporal_status == "PAST"
    assert any("despues" in r for r in res.signals.relative_to)


def test_explicit_interval_populates_bounds():
    res = resolve_temporal("La alianza entre Zorn y Halbrek duró entre 300 y 380.")
    assert res.interval == ("300", "380")
    assert res.temporal_status in ("PAST", "ENDED")


# ---------------------------------------------------------------------------
# Inicio / final de vigencia (desde / hasta)
# ---------------------------------------------------------------------------
def test_since_opens_valid_from():
    res = resolve_temporal("Vorka sirve al Trono de Ceniza desde el 1120.")
    assert res.temporal_status == "ONGOING"
    assert res.signals.valid_from == "1120"


def test_until_closes_valid_to_and_ends():
    res = resolve_temporal("Peren custodió el Faro de Nix hasta el 1180.")
    assert res.temporal_status == "ENDED"
    assert res.signals.valid_to == "1180"


# ---------------------------------------------------------------------------
# Terminada (cese explicito) / antiguo cargo / sucesion
# ---------------------------------------------------------------------------
def test_ended_relationship_explicit_cue():
    res = resolve_temporal("Galto ya no pertenece a la Hermandad de Sal.")
    assert res.temporal_status == "ENDED"
    assert res.state == TemporalState.ENDED


def test_former_title_is_ended():
    res = resolve_temporal("Odra, antigua capitana de la Guardia Bruna, se retiró.")
    assert res.temporal_status == "ENDED"


# ---------------------------------------------------------------------------
# Vigente / en curso (continuidad)
# ---------------------------------------------------------------------------
def test_ongoing_continuity_cue():
    res = resolve_temporal("Nael todavia dirige el Gremio de Faroleros.")
    assert res.temporal_status == "ONGOING"
    assert res.state == TemporalState.ACTIVE


# ---------------------------------------------------------------------------
# Planeada (todavia no) / hipotetica
# ---------------------------------------------------------------------------
def test_not_yet_is_pending_future():
    res = resolve_temporal("Sombra todavia no ha jurado lealtad al Kan de Vurr.")
    assert res.temporal_status == "FUTURE"
    assert res.state == TemporalState.PLANNED
    assert res.signals.is_pending is True


def test_hypothetical_conditional_is_future_not_present():
    # El demostrativo "esta" (esta rivalidad) NO debe leerse como el verbo "esta":
    # un condicional es no-actual -> FUTURE.
    res = resolve_temporal("Esta rivalidad podría desatar la Guerra de las Mareas.")
    assert res.temporal_status == "FUTURE"
    assert res.state == TemporalState.HYPOTHETICAL
    assert res.signals.is_potential is True


# ---------------------------------------------------------------------------
# Recurrente / habitual (cuantificador universal + presente)
# ---------------------------------------------------------------------------
def test_recurring_universal_quantifier_maps_to_ongoing():
    res = resolve_temporal("Cada portador del Sello Rúnico jura ante el Ateneo.")
    assert res.temporal_status == "ONGOING"
    assert res.state == TemporalState.RECURRING
    assert res.signals.is_recurring is True


def test_recurring_generic_todo():
    res = resolve_temporal("Todo miembro del Circulo respeta la Ley de Umbra.")
    assert res.state == TemporalState.RECURRING
    assert res.temporal_status == "ONGOING"


# ---------------------------------------------------------------------------
# Referencia no resoluble
# ---------------------------------------------------------------------------
def test_unresolvable_reference_is_unknown_atemporal():
    for txt in ["", "   ", "\n\t"]:
        res = resolve_temporal(txt)
        assert res.state == TemporalState.UNKNOWN
        assert res.temporal_status == "ATEMPORAL"
        # sin fechas ni intervalo, un UNKNOWN no aporta alcance:
        assert res.has_temporal_signal is False


def test_state_to_status_mapping_is_coherent_with_harness_classes():
    # Cada clase mapeada es una clase valida del contrato que mide el arnes.
    for status in STATE_TO_STATUS.values():
        assert status in temporality.TEMPORAL_CLASSES


# ---------------------------------------------------------------------------
# Cambio de estado / transicion SIN sobrescribir historia
# ---------------------------------------------------------------------------
def test_transition_ally_to_enemy_is_layered_not_overwritten():
    # aliado (pasado) -> ya no aliado -> enemigo (ahora): fases SEPARADAS.
    seg = ("Fenrik fue aliado del Clan Osric, ya no lo respalda, "
           "y ahora es enemigo declarado de esa casa.")
    phases = segment_transitions(seg)
    assert len(phases) >= 3, [p.text for p in phases]
    statuses = [p.resolution.temporal_status for p in phases]
    # la primera fase es pasada, hay un cese, y la ultima es presente/vigente:
    assert statuses[0] == "PAST"
    assert any(p.resolution.state == TemporalState.ENDED for p in phases)
    assert statuses[-1] == "PRESENT"
    # las fases son objetos distintos: resolver una no muta otra.
    assert phases[0].resolution is not phases[-1].resolution


def test_no_transition_returns_single_phase():
    seg = "Ludra preside el Consejo de Marfil."
    phases = segment_transitions(seg)
    assert len(phases) == 1
    assert phases[0].resolution.temporal_status == "PRESENT"


# ---------------------------------------------------------------------------
# Contradiccion temporal aparente (dos fuentes en momentos distintos)
# ---------------------------------------------------------------------------
def test_apparent_contradiction_resolves_per_source_without_collapsing():
    # Dos aserciones sobre el MISMO par en momentos distintos: cada una conserva su
    # propia clase; no se colapsan ni se contradicen (una es pasada, otra vigente).
    early = resolve_temporal("En el 400, Boran servía al Reino de Talm.")
    late = resolve_temporal("Boran ya no sirve al Reino de Talm.")
    assert early.temporal_status == "PAST"
    assert late.temporal_status == "ENDED"
    # el eje temporal del contrato distingue ambas fuentes (no se colapsan):
    assert early.temporal_status != late.temporal_status
    # ninguna resolucion muta a la otra (objetos independientes):
    assert early is not late


# ---------------------------------------------------------------------------
# Adaptador de pipeline (ventana acotada a la frase del par)
# ---------------------------------------------------------------------------
def test_resolve_for_pair_scopes_to_sentence_of_the_pair():
    seg = ("Marn cayó en desgracia hace tiempo. "
           "Hoy, Marn lidera la Liga de Cendra sin oposicion.")
    pair = _pair(seg, "Marn lidera", "Liga de Cendra")
    res = resolve_for_pair(seg, pair)
    # la ventana del par es la 2a frase (presente), NO la 1a (pasado):
    assert res.temporal_status == "PRESENT"


def test_temporal_scope_for_pair_returns_parseable_prefix_or_none():
    seg = "Quel firmó el Tratado de Hierro en el 1002."
    pair = _pair(seg, "Quel", "Tratado de Hierro")
    scope = temporal_scope_for_pair(seg, pair)
    assert isinstance(scope, str)
    assert temporality.temporal_status_of(scope) == "PAST"
