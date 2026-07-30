# -*- coding: utf-8 -*-
"""E2E GLOBAL: catorce escenarios por la RUTA COMPLETA, mas SKIPS y REPRODUCIBILIDAD.

QUE ANADE ESTE FICHERO Y QUE NO
-------------------------------
`test_knowledge_v3_e2e.py` ya cubre las diez pruebas CONJUNTAS del §8: pares de
etapas (normalizador+extractor, extractor+motor, motor+ledger), las ablaciones
de proveedor y las defensas (workspace ajeno, plan no firmado, proveedor
corrupto). Todas entran por EPISODIOS del gold.

Aqui NO se repite nada de eso. Lo que falta y se cubre aqui es el eje
ORTOGONAL: la ruta completa desde BYTES (normalizador real incluido) recorrida
UNA VEZ POR CADA CLASE DE FENOMENO que el sistema dice saber distinguir —
factividad, negacion, cesacion, pregunta, contrafactual, predicados rivales,
identidad sin resolver, revision y correccion humanas, alias, OCR y proveedor
caido. La pregunta que responde no es "se sostienen dos etapas juntas" sino
"que sale por el otro extremo cuando entra ESTE texto".

MATERIAL
--------
El texto de cada escenario es CORTO y esta escrito para el escenario, pero las
ENTIDADES son las reales del split `dev` (`Ilaria Vandreth`, `Casa del Ciervo`,
`Daiki Oharu`) y entran por el catalogo y el glosario reales del workspace. No
se fabrica ninguna entidad: si se fabricara, el resolutor enlazaria contra un
mundo inventado y el escenario no diria nada.

La razon de no usar los episodios del gold tal cual es MEDIDA, no comodidad: la
cadena en `local_only` sobre las seis fuentes de `dev` produce CERO claims (el
extractor determinista necesita una de sus frases de relacion literales, y la
prosa del gold no las lleva). Sin claims no hay decision, y sin decision no hay
escenario que observar. Queda anotado como hallazgo en el artefacto.

LIMITES QUE ESTE FICHERO RESPETA
--------------------------------
  * Neo4j                nunca se abre. El writer va SIEMPRE en dry-run y donde
                         hay que demostrar que no se toca el grafo se le pasa el
                         `ExplodingDriver` de los fixtures.
  * Ollama / NVIDIA      no se llaman. El carril de proveedor entra por el
                         puerto guionizado `ScriptedExternalPort` de los
                         fixtures. El carril REAL lo mide el coordinador en la
                         puerta 5; aqui solo se comprueba el CABLEADO.
  * Produccion           no se modifica. Los dos defectos encontrados van con
                         `xfail(strict=True)`, no con un parche.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("jsonschema")

_APP_DIR = Path(__file__).resolve().parents[1]
_TESTS_DIR = Path(__file__).resolve().parent
for _p in (str(_APP_DIR), str(_TESTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_knowledge_v3_e2e_fixtures import (  # noqa: E402
    NOW,
    WORKSPACE,
    ExplodingDriver,
    ExplodingExternalPort,
    ScriptedExternalPort,
    base_config,
    gold_dev,
    snapshot_entities,
)

from knowledge_v3.extraction import cues as _cues  # noqa: E402
from knowledge_v3.multimodal.base import IngestOptions, SourceInput  # noqa: E402
from knowledge_v3.pipeline import KnowledgePipeline, bridge  # noqa: E402
from knowledge_v3.pipeline.pipeline import SourceCase  # noqa: E402
from knowledge_v3.review_export import review_documents  # noqa: E402


# ===========================================================================
# ARNES
# ===========================================================================
@pytest.fixture(scope="module")
def gold():
    return gold_dev()


@pytest.fixture(scope="module")
def entities(gold):
    return snapshot_entities(gold)


def raw_case(source_id: str, text: str) -> SourceCase:
    """Una fuente de BYTES. La cadena arranca en el normalizador de verdad.

    No se pre-cocina ningun episodio ni ningun fragmento: el normalizador los
    deriva del texto, y por eso este arnes ejercita la etapa 1 que la entrada
    por episodios se salta.
    """
    return SourceCase(
        source_id=source_id,
        source=SourceInput(
            data=text.encode("utf-8"),
            original_name=f"{source_id}.md",
            original_location=f"mem://{source_id}",
            mime_type="text/markdown",
            source_kind="MARKDOWN",
        ),
        ingest_options=IngestOptions(
            workspace=WORKSPACE,
            collection_id="collection:pruebas",
            ingested_at=NOW,
            created_at=NOW,
            game_profile="generic",
            language_hint="es",
        ),
    )


def run_text(gold, entities, source_id: str, text: str, **overrides):
    """La cadena ENTERA sobre un texto. Devuelve `(pipeline, SourceRun)`.

    El driver por defecto es el que ESTALLA: cualquier escenario que tocase
    Neo4j fallaria aqui en voz alta en lugar de pasar en silencio.
    """
    overrides.setdefault("writer_driver", ExplodingDriver())
    p = KnowledgePipeline(base_config(gold, **overrides))
    result = p.run([raw_case(source_id, text)], catalog_entities=entities)
    return p, result.runs[0]


def semantic_payload(
    quote: str,
    predicates,
    *,
    subject: str = "Ilaria Vandreth",
    subject_type: str = "Character",
    obj: str = "Casa del Ciervo",
    object_type: str = "Faction",
    relation_phrase: str = "lidera",
):
    """Payload SEMANTICO para el puerto guionizado, anclado en una cita literal.

    Es la forma que pide el extractor semantico real: el filtro antialucinacion,
    el tope de confianza externo y la validacion de candidatos los ejecuta el
    subsistema, no este arnes. Si la cita dejara de estar en el episodio,
    `payload.anchor_in_episode` lo tumbaria — que es lo que debe hacer.
    """
    return {
        "mentions": [
            {
                "local_ref": "m1",
                "surface": subject,
                "type_candidates": [{"type": subject_type, "confidence": 0.8}],
                "evidence_quote": quote,
            },
            {
                "local_ref": "m2",
                "surface": obj,
                "type_candidates": [{"type": object_type, "confidence": 0.8}],
                "evidence_quote": quote,
            },
        ],
        "claims": [
            {
                "subject_ref": "m1",
                "object_ref": "m2",
                "relation_phrase": relation_phrase,
                "predicate_candidates": list(predicates),
                "direction_candidates": [
                    {"direction": "SUBJECT_TO_OBJECT", "confidence": 0.9}
                ],
                "evidence_quote": quote,
                "negated": False,
                "epistemic_status": "ASSERTED",
                "temporal_expressions": [],
                "temporal_resolution_required": False,
            }
        ],
        "abstentions": [],
    }


def codes(decision) -> list[str]:
    return sorted(f.code for f in decision.findings)


def only_decision(run):
    assert len(run.decisions) == 1, [d.decision for d in run.decisions]
    return run.decisions[0]


def assert_llego_al_final(run) -> None:
    """La cadena recorrio las siete etapas: normalizar -> ... -> writer."""
    assert run.stopped_at is None, (run.stopped_at, run.stop_reason)
    for stage in ("normalize", "extract", "reconcile", "resolve", "engine"):
        assert stage in run.stage_latency_ms, sorted(run.stage_latency_ms)


def assert_normalizador_hizo_su_trabajo(run) -> None:
    """Etapa 1 de verdad: el asset, los episodios y los fragmentos son SUYOS."""
    assert run.asset is not None
    assert run.episodes, "el normalizador no produjo ningun episodio"
    assert run.fragments, "el normalizador no produjo ningun fragmento"
    # Identificadores DERIVADOS, no redactados: la entrada por bytes se
    # distingue de la entrada por episodios justo en esto.
    assert run.episodes[0].episode_id.startswith("ep-"), run.episodes[0].episode_id
    assert run.normalization_report, "no hay informe de normalizacion"


def assert_dry_run_simulado(run) -> None:
    """El writer simulo y NO toco el driver (que habria estallado)."""
    assert run.write_result is not None, "el plan no llego al writer"
    assert run.write_result.outcome == "SIMULATED", run.write_result.outcome
    assert run.write_result.codes == [], run.write_result.codes


def assert_no_hubo_escritura(run) -> None:
    """Sin plan aprobado no hay ni siquiera simulacion de operaciones."""
    if run.write_result is not None:
        assert run.write_result.outcome != "APPLIED", run.write_result.outcome
    assert not run.ledger_entries, run.ledger_entries


# Textos de los escenarios. Se declaran juntos para que se lean como una
# tabla: es el mismo par sujeto/objeto en todos, y lo unico que cambia es el
# MARCO. Asi la diferencia de salida solo puede venir del marco.
T_HECHO = "Ilaria Vandreth lidera la Casa del Ciervo."
T_NEGACION = "Daiki Oharu no lidera la Casa del Ciervo."
T_CESACION = "Ilaria Vandreth ya no lidera la Casa del Ciervo."
T_NEG_CESACION = "Ilaria Vandreth no dimitio de su cargo y lidera la Casa del Ciervo."
T_PREGUNTA = "¿Ilaria Vandreth lidera la Casa del Ciervo?"
T_CONTRAFACTUAL = "De haber sobrevivido al asedio, Ilaria Vandreth lidera la Casa del Ciervo."
T_MIEMBRO = "Ilaria Vandreth es miembro de la Casa del Ciervo."
T_ALIAS = "Vandreth lidera la Casa del Ciervo."
T_OCR = "Ilaria Vandreth lidera la Casa de1 Ciervo."
T_DESCONOCIDA = "Kestrel Umbrio lidera la Casa del Ciervo."


# ===========================================================================
# E2E-01  HECHO DETERMINISTA
# ===========================================================================
class TestE2E01HechoDeterminista:
    """Texto afirmativo limpio, sin proveedor: ACCEPT y plan simulado.

    Es el escenario de referencia: todos los demas se leen contra este. Si este
    no llegase entero al writer, ningun otro resultado significaria nada.
    """

    def test_la_ruta_completa_termina_en_un_dry_run_simulado(self, gold, entities):
        _, run = run_text(gold, entities, "e2e-01", T_HECHO)

        assert_normalizador_hizo_su_trabajo(run)
        assert_llego_al_final(run)

        # Extractor: dos menciones y UN claim, sin diagnosticos de contexto.
        assert len(run.mentions) == 2, [m.surface for m in run.mentions]
        assert len(run.claims) == 1
        assert run.diagnostics == [], run.diagnostics

        # Resolutor: las dos menciones enlazan contra el catalogo real.
        assert len(run.resolutions) == 2
        assert {r.action for r in run.resolutions} == {"LINK_EXISTING"}

        # Motor: ACCEPT con la evidencia verificada literalmente.
        decision = only_decision(run)
        assert decision.decision == "ACCEPT"
        assert decision.predicate == "LEADS"
        assert decision.direction == "SUBJECT_TO_OBJECT"
        assert decision.negated is False
        assert decision.epistemic_status == "ASSERTED"
        assert "EVIDENCE_LITERAL_VERIFIED" in codes(decision)

        # Plan: aprobado, con las operaciones que de verdad tocarian el grafo.
        assert run.plan is not None and run.plan.approved is True
        tipos = [op["operation_type"] for op in run.plan.mutation_operations]
        assert "CREATE_ASSERTION" in tipos, tipos

        # Ledger y writer.
        assert len(run.ledger_entries) == 1
        assert_dry_run_simulado(run)

    def test_las_entidades_del_plan_son_las_del_catalogo_real(self, gold, entities):
        """El plan apunta a los IDs del mundo, no a provisionales inventadas."""
        _, run = run_text(gold, entities, "e2e-01-ids", T_HECHO)
        payload = run.plan.mutation_operations[0]["payload"]
        assert payload["subject_entity_id"] == "entity:leyenda:ilaria"
        assert payload["object_entity_id"] == "entity:leyenda:casa-ciervo"


# ===========================================================================
# E2E-02  HECHO SEMANTICO (proveedor guionizado)
# ===========================================================================
class TestE2E02HechoSemantico:
    """El mismo hecho, propuesto ademas por el carril de proveedor.

    CARRIL REAL: este escenario mide el CABLEADO, no la calidad del modelo. La
    corrida contra Ollama/NVIDIA de verdad la ejecuta el coordinador en la
    puerta 5; aqui el proveedor es un puerto guionizado y la unica afirmacion
    posible es que su propuesta ENTRA, se marca como externa y no manda.
    """

    def test_la_propuesta_externa_recorre_la_cadena_sin_ganar_autoridad(
        self, gold, entities
    ):
        quote = T_HECHO.rstrip(".")
        port = ScriptedExternalPort(
            semantic_payload(quote, [{"predicate": "LEADS", "confidence": 0.9}])
        )
        _, run = run_text(
            gold,
            entities,
            "e2e-02",
            T_HECHO,
            external_port=port,
            providers="local_plus_external",
        )

        assert_llego_al_final(run)
        assert port.requests, "el puerto externo no llego a ser invocado"

        # DOS claims: el determinista y el semantico. La cadena no los funde.
        assert len(run.decisions) == 2, [d.decision for d in run.decisions]
        externa = [d for d in run.decisions if "EXTERNAL_PROPOSAL" in codes(d)]
        local = [d for d in run.decisions if "EXTERNAL_PROPOSAL" not in codes(d)]
        assert len(externa) == 1 and len(local) == 1

        # La propuesta externa NO aprueba por si sola: tope de confianza 0.6 y
        # revision pedida. Quien aprueba es el carril local.
        assert externa[0].decision == "REVIEW"
        assert externa[0].confidence == pytest.approx(0.6)
        assert local[0].decision == "ACCEPT"

        # El plan lo firma el motor local y sale simulado.
        assert run.plan.approved is True
        assert_dry_run_simulado(run)

    def test_el_proveedor_externo_no_es_ollama_ni_la_red(self, gold, entities):
        """Guardia del encargo: el puerto guionizado no abre ninguna conexion."""
        quote = T_HECHO.rstrip(".")
        port = ScriptedExternalPort(
            semantic_payload(quote, [{"predicate": "LEADS", "confidence": 0.9}])
        )
        run_text(
            gold,
            entities,
            "e2e-02-red",
            T_HECHO,
            external_port=port,
            providers="local_plus_external",
        )
        # Todo lo que el puerto vio son objetos de dominio, no sockets.
        assert all(hasattr(r, "prompt") for r in port.requests)


# ===========================================================================
# E2E-03  NEGACION SIMPLE
# ===========================================================================
class TestE2E03NegacionSimple:
    """`no lidera`: informacion negativa. Ni se afirma ni se tira: se revisa."""

    def test_la_negacion_simple_llega_marcada_y_no_aprueba(self, gold, entities):
        _, run = run_text(gold, entities, "e2e-03", T_NEGACION)

        assert_llego_al_final(run)
        decision = only_decision(run)

        assert decision.decision == "REVIEW"
        assert decision.negated is True
        assert decision.negation_kind == "SIMPLE"
        assert "NEGATED_CLAIM" in codes(decision)

        # El predicado NO se pierde: una negacion sin predicado no es
        # informacion, es ruido.
        assert decision.predicate == "LEADS"

        # No hay plan de escritura, y el de revision no lleva operaciones: un
        # REVIEW no muta el grafo por definicion.
        assert run.plan is None
        assert run.review_plan is not None
        assert run.review_plan.approved is False
        assert run.review_plan.mutation_operations == []
        assert_no_hubo_escritura(run)


# ===========================================================================
# E2E-04  CESACION
# ===========================================================================
class TestE2E04Cesacion:
    """`ya no lidera`: hubo relacion y termina. No es lo mismo que `no lidera`."""

    def test_la_cesacion_se_distingue_de_la_negacion_simple(self, gold, entities):
        _, run = run_text(gold, entities, "e2e-04", T_CESACION)

        assert_llego_al_final(run)
        decision = only_decision(run)

        assert decision.decision == "REVIEW"
        assert decision.negated is True
        assert decision.negation_kind == "CESSATION"

        # Sin nada vigente que cerrar, el motor lo dice en vez de inventarse
        # una vigencia que cerrar.
        assert "CESSATION_WITHOUT_ACTIVE_ASSERTION" in codes(decision)
        assert run.plan is None
        assert_no_hubo_escritura(run)

    def test_negacion_simple_y_cesacion_no_producen_el_mismo_veredicto(
        self, gold, entities
    ):
        """La distincion importa: si colapsaran, el eje no existiria."""
        _, simple = run_text(gold, entities, "e2e-04-a", T_NEGACION)
        _, cese = run_text(gold, entities, "e2e-04-b", T_CESACION)
        assert only_decision(simple).negation_kind == "SIMPLE"
        assert only_decision(cese).negation_kind == "CESSATION"
        assert codes(only_decision(simple)) != codes(only_decision(cese))


# ===========================================================================
# E2E-05  NEGACION DE CESACION
# ===========================================================================
class TestE2E05NegacionDeCesacion:
    """`no dimitio ... y lidera`: la cesacion esta NEGADA. Cerrar seria mentir.

    LIMITE MEDIDO Y DECLARADO: no existe ningun texto que el extractor
    determinista acepte en el que convivan una frase de cesacion negada y una
    de sus frases de relacion literales — sus frases de cesacion piden
    infinitivo (`dejo de liderar`) y sus frases de relacion son formas
    conjugadas (`lidera`). Lo que SI es alcanzable, y es lo que este escenario
    demuestra, es que la cadena lo detecta como alcance ambiguo y se abstiene
    en lugar de leerlo como una cesacion.
    """

    def test_una_cesacion_negada_no_se_lee_como_cesacion(self, gold, entities):
        # Primero, en el clasificador: la lectura correcta existe.
        verdict = _cues.analyze_raw_text(T_NEG_CESACION)
        assert verdict.negation_kind == "SCOPE_AMBIGUOUS"
        assert "REVIEW_NEGATION_SCOPE" in verdict.reason_codes

        # Y despues, por la ruta completa: se abstiene, no cierra nada.
        _, run = run_text(gold, entities, "e2e-05", T_NEG_CESACION)
        assert_llego_al_final(run)
        decision = only_decision(run)

        assert decision.decision == "ABSTAIN"
        assert decision.negation_kind != "CESSATION"
        assert "CLAIM_ABSTAINED_UPSTREAM" in codes(decision)
        assert "CESSATION_WITHOUT_ACTIVE_ASSERTION" not in codes(decision)

        assert run.plan is not None and run.plan.approved is False
        assert run.plan.mutation_operations == []
        assert_no_hubo_escritura(run)


# ===========================================================================
# E2E-06  PREGUNTA
# ===========================================================================
class TestE2E06Pregunta:
    """Una pregunta no afirma nada. No debe producir NI UN claim."""

    def test_la_pregunta_no_genera_ninguna_propuesta(self, gold, entities):
        _, run = run_text(gold, entities, "e2e-06", T_PREGUNTA)

        # El normalizador y el extractor de menciones SI trabajan: las
        # entidades se mencionan de verdad aunque nada se afirme de ellas.
        assert_normalizador_hizo_su_trabajo(run)
        assert len(run.mentions) == 2

        # Pero no hay claim, y la razon queda escrita.
        assert run.claims == []
        assert "INTERROGATIVE_CONTEXT" in {d["code"] for d in run.diagnostics}

        # La cadena se detiene en el motor, declarandolo.
        assert run.stopped_at == "engine"
        assert run.decisions == ()
        assert run.plan is None
        assert_no_hubo_escritura(run)


# ===========================================================================
# E2E-07  CONTRAFACTUAL
# ===========================================================================
class TestE2E07Contrafactual:
    """`De haber ...`: mundo alternativo NO realizado. Nada que materializar."""

    def test_el_contrafactual_no_produce_ningun_claim(self, gold, entities):
        _, run = run_text(gold, entities, "e2e-07", T_CONTRAFACTUAL)

        assert_normalizador_hizo_su_trabajo(run)
        assert run.claims == []
        assert "COUNTERFACTUAL_CONTEXT" in {d["code"] for d in run.diagnostics}
        assert run.stopped_at == "engine"
        assert run.plan is None
        assert_no_hubo_escritura(run)

    def test_el_mismo_hecho_sin_el_marco_si_se_afirma(self, gold, entities):
        """Control: lo que bloquea es el MARCO, no la frase de relacion."""
        _, run = run_text(gold, entities, "e2e-07-ctl", T_HECHO)
        assert only_decision(run).decision == "ACCEPT"


# ===========================================================================
# E2E-08  PROVEEDOR CAIDO
# ===========================================================================
class TestE2E08ProveedorCaido:
    """El externo estalla. La cadena no solo sobrevive: TERMINA su trabajo.

    `test_knowledge_v3_e2e.py::TestConjunta08` ya prueba que un externo caido se
    anota y no tumba la cadena. Lo que aqui se anade es el otro extremo: que el
    carril LOCAL llega hasta el dry-run igualmente. Sobrevivir sin producir nada
    tambien seria "no tumbarse", y no seria suficiente.
    """

    def test_con_el_proveedor_caido_el_carril_local_llega_al_writer(
        self, gold, entities
    ):
        _, run = run_text(
            gold,
            entities,
            "e2e-08",
            T_HECHO,
            external_port=ExplodingExternalPort(),
            providers="local_plus_external",
        )

        assert_llego_al_final(run)

        # La caida se ANOTA, no se traga.
        assert "PROVIDER_UNAVAILABLE" in {d["code"] for d in run.diagnostics}

        # Y el carril local aprueba y simula igual.
        aceptadas = [d for d in run.decisions if d.decision == "ACCEPT"]
        assert len(aceptadas) == 1
        assert aceptadas[0].predicate == "LEADS"
        assert "EXTERNAL_PROPOSAL" not in codes(aceptadas[0])

        assert run.plan is not None and run.plan.approved is True
        assert_dry_run_simulado(run)

    def test_el_proveedor_caido_no_aporta_ni_una_mencion(self, gold, entities):
        """Nada de lo que el externo iba a decir se cuela por otra puerta.

        OBSERVADO, y merece explicacion: con el puerto caido el extractor
        semantico SI deja un claim con `provider="external"` en su traza. No es
        contenido del modelo —el modelo no contesto nunca—: es el REGISTRO del
        intento, y ese claim sale ABSTAIN con `PREDICATE_ABSENT`. Lo que se
        afirma aqui es lo que de verdad importa: ninguna MENCION viene del
        externo, y nada suyo entra en el plan aprobado.
        """
        _, run = run_text(
            gold,
            entities,
            "e2e-08-b",
            T_HECHO,
            external_port=ExplodingExternalPort(),
            providers="local_plus_external",
        )

        # Ni una mencion del carril externo.
        for mention in run.mentions:
            for paso in mention.provider_trace:
                assert paso.get("provider") != "external", paso

        # El claim con sello externo existe, pero esta VACIO de contenido: se
        # abstiene por falta de predicado.
        externos = [
            d for d in run.decisions if "EXTERNAL_PROPOSAL" in codes(d)
        ]
        assert len(externos) == 1
        assert externos[0].decision == "ABSTAIN"
        assert externos[0].predicate is None
        assert "PREDICATE_ABSENT" in codes(externos[0])

        # Y el plan aprobado es enteramente del carril local.
        for op in run.plan.mutation_operations:
            assert "external" not in json.dumps(op), op


# ===========================================================================
# E2E-09  PREDICADOS RIVALES
# ===========================================================================
class TestE2E09PredicadosRivales:
    """Dos predicados con confianza casi igual: la ambiguedad es del MOTOR.

    El extractor no debe elegir. Lo que se comprueba es que los dos candidatos
    viajan hasta el motor y que el motor lo llama por su nombre en vez de
    quedarse con el primero.
    """

    def test_dos_candidatos_reñidos_acaban_en_revision_por_ambiguedad(
        self, gold, entities
    ):
        quote = T_HECHO.rstrip(".")
        port = ScriptedExternalPort(
            semantic_payload(
                quote,
                [
                    {"predicate": "LEADS", "confidence": 0.55},
                    {"predicate": "MEMBER_OF", "confidence": 0.52},
                ],
            )
        )
        _, run = run_text(
            gold,
            entities,
            "e2e-09",
            T_HECHO,
            external_port=port,
            providers="local_plus_external",
        )

        assert_llego_al_final(run)
        rival = [d for d in run.decisions if "EXTERNAL_PROPOSAL" in codes(d)]
        assert len(rival) == 1
        decision = rival[0]

        assert decision.decision == "REVIEW"
        assert "PREDICATE_AMBIGUOUS" in codes(decision)
        assert "PREDICATE_LOW_CONFIDENCE" in codes(decision)

        # Y no entra en el plan aprobado por la puerta de atras.
        aprobados = [
            op["payload"].get("predicate")
            for op in run.plan.mutation_operations
            if op["operation_type"] == "CREATE_ASSERTION"
        ]
        assert "MEMBER_OF" not in aprobados, aprobados

    def test_sin_rival_el_mismo_carril_no_marca_ambiguedad(self, gold, entities):
        """Control: la marca la pone la RIVALIDAD, no el carril externo."""
        quote = T_HECHO.rstrip(".")
        port = ScriptedExternalPort(
            semantic_payload(quote, [{"predicate": "LEADS", "confidence": 0.9}])
        )
        _, run = run_text(
            gold,
            entities,
            "e2e-09-ctl",
            T_HECHO,
            external_port=port,
            providers="local_plus_external",
        )
        externa = [d for d in run.decisions if "EXTERNAL_PROPOSAL" in codes(d)][0]
        assert "PREDICATE_AMBIGUOUS" not in codes(externa)


# ===========================================================================
# E2E-10  IDENTIDAD NO RESUELTA
# ===========================================================================
class TestE2E10IdentidadNoResuelta:
    """Un nombre que no esta en el catalogo. No se inventa: se marca provisional."""

    def test_una_entidad_desconocida_no_llega_al_grafo(self, gold, entities):
        quote = T_DESCONOCIDA.rstrip(".")
        port = ScriptedExternalPort(
            semantic_payload(
                quote,
                [{"predicate": "LEADS", "confidence": 0.9}],
                subject="Kestrel Umbrio",
            )
        )
        _, run = run_text(
            gold,
            entities,
            "e2e-10",
            T_DESCONOCIDA,
            external_port=port,
            providers="local_plus_external",
        )

        assert_llego_al_final(run)

        # Resolutor: crea una PROVISIONAL en vez de enlazar a lo que se le
        # parezca o de tirar la mencion.
        provisionales = [r for r in run.resolutions if r.action == "CREATE_PROVISIONAL"]
        assert len(provisionales) == 1
        assert provisionales[0].assigned_entity_id.startswith("entity:prov:")

        # Motor: lo ve y lo dice.
        decision = only_decision(run)
        assert decision.decision == "REVIEW"
        assert "ENTITY_PROVISIONAL" in codes(decision)

        # Y nada se escribe.
        assert run.plan is None
        assert_no_hubo_escritura(run)


# ===========================================================================
# E2E-11  REVISION HUMANA
# ===========================================================================
class TestE2E11RevisionHumana:
    """Lo que el motor manda a revisar tiene que LLEGAR al humano.

    El canal es `review_export`: el paquete inmutable que consume `/v3/review`.
    Un REVIEW que no produce documento de revision es una decision perdida.
    """

    def test_la_decision_de_revision_produce_su_documento(self, gold, entities):
        p = KnowledgePipeline(base_config(gold, writer_driver=ExplodingDriver()))
        result = p.run(
            [raw_case("e2e-11", T_NEGACION)], catalog_entities=entities
        )
        assert only_decision(result.runs[0]).decision == "REVIEW"

        docs = review_documents(result, workspace=WORKSPACE)
        assert len(docs) == 1, docs
        doc = docs[0]

        # La evidencia que ve el humano es el texto LITERAL del episodio.
        assert doc["evidence"]["literal_text"] == T_NEGACION
        assert doc["episode_text"] == T_NEGACION

        # La decision y su porque viajan enteras.
        assert doc["engine_decision"]["decision"] == "REVIEW"
        assert "NEGATED_CLAIM" in doc["engine_decision"]["reason_codes"]
        assert doc["proposal"]["predicate"] == "LEADS"
        assert doc["proposal"]["negated"] is True

        # Y el paquete es direccionable e integro.
        assert doc["proposal_id"].startswith("review:")
        assert len(doc["proposal_hash"]) == 64

    def test_lo_aceptado_no_va_a_revision(self, gold, entities):
        """Control: el canal humano no se inunda con lo que ya se decidio."""
        p = KnowledgePipeline(base_config(gold, writer_driver=ExplodingDriver()))
        result = p.run([raw_case("e2e-11-ctl", T_HECHO)], catalog_entities=entities)
        assert only_decision(result.runs[0]).decision == "ACCEPT"
        assert review_documents(result, workspace=WORKSPACE) == []


# ===========================================================================
# E2E-12  CORRECCION HUMANA
# ===========================================================================
class TestE2E12CorreccionHumana:
    """El operador corrige un hecho ya asentado, y la correccion SURTE EFECTO.

    La palanca real es el ledger: `retract` con un motivo canonico. Lo que hace
    que esto sea un escenario de ruta completa y no una prueba de unidad del
    ledger es la ultima comprobacion: el snapshot que veria la SIGUIENTE fuente
    ya no contiene el hecho retirado.
    """

    def test_la_retractacion_del_operador_desaparece_del_snapshot(
        self, gold, entities
    ):
        p, run = run_text(gold, entities, "e2e-12", T_HECHO)
        assert only_decision(run).decision == "ACCEPT"
        assert len(run.ledger_entries) == 1

        led = p.ledger
        assertion_id = run.assertions[0].assertion_id
        assert led.current(assertion_id)["status"] == "ASSERTED"
        antes = bridge.engine_snapshot(led, entities=entities)
        assert len(antes.assertions) == 1

        # La correccion humana. El motivo es obligatorio y canonico.
        led.retract(
            assertion_id,
            recorded_at="2026-07-27T13:00:00Z",
            reason_code="OPERATOR_RETRACTION",
        )

        assert led.current(assertion_id)["status"] == "RETRACTED"
        assert led.live() == []

        # Lo que veria la siguiente fuente ya no lo incluye.
        despues = bridge.engine_snapshot(led, entities=entities)
        assert despues.assertions == () or len(despues.assertions) == 0

    def test_la_correccion_no_borra_la_historia(self, gold, entities):
        """Retractar no es borrar: la auditoria conserva las dos versiones."""
        p, run = run_text(gold, entities, "e2e-12-b", T_HECHO)
        led = p.ledger
        assertion_id = run.assertions[0].assertion_id
        led.retract(
            assertion_id,
            recorded_at="2026-07-27T13:00:00Z",
            reason_code="OPERATOR_RETRACTION",
        )
        historia = led.history(assertion_id)
        assert [v.status for v in historia] == ["ASSERTED", "RETRACTED"]

    def test_un_motivo_no_canonico_no_corrige_nada(self, gold, entities):
        """El operador tampoco puede escribir prosa libre en la auditoria."""
        p, run = run_text(gold, entities, "e2e-12-c", T_HECHO)
        with pytest.raises(Exception):
            p.ledger.retract(
                run.assertions[0].assertion_id,
                recorded_at="2026-07-27T13:00:00Z",
                reason_code="ME_LO_HA_DICHO_UN_AMIGO",
            )


# ===========================================================================
# E2E-13  ALIAS CANDIDATO
# ===========================================================================
class TestE2E13AliasCandidato:
    """`Vandreth` es alias de `Ilaria Vandreth`. Enlaza, pero con menos confianza."""

    def test_el_alias_enlaza_a_la_entidad_canonica(self, gold, entities):
        _, run = run_text(gold, entities, "e2e-13", T_ALIAS)

        assert_llego_al_final(run)
        decision = only_decision(run)
        assert decision.decision == "ACCEPT"
        assert (
            run.plan.mutation_operations[0]["payload"]["subject_entity_id"]
            == "entity:leyenda:ilaria"
        )
        assert_dry_run_simulado(run)

    def test_el_alias_cuesta_confianza_frente_al_nombre_canonico(
        self, gold, entities
    ):
        """Si costara lo mismo, el eje de identidad no estaria midiendo nada."""
        _, canonico = run_text(gold, entities, "e2e-13-a", T_HECHO)
        _, alias = run_text(gold, entities, "e2e-13-b", T_ALIAS)
        assert only_decision(alias).confidence < only_decision(canonico).confidence


# ===========================================================================
# E2E-14  ERROR DE OCR
# ===========================================================================
class TestE2E14ErrorOCR:
    """`Casa de1 Ciervo`: la variante degradada esta declarada en el perfil.

    El sistema la reconoce (para eso esta declarada) pero NO la trata como si
    fuera el nombre limpio: la confianza baja y queda constancia.
    """

    def test_la_superficie_degradada_enlaza_a_la_entidad_correcta(
        self, gold, entities
    ):
        _, run = run_text(gold, entities, "e2e-14", T_OCR)

        assert_llego_al_final(run)
        decision = only_decision(run)
        assert decision.decision == "ACCEPT"
        assert (
            run.plan.mutation_operations[0]["payload"]["object_entity_id"]
            == "entity:leyenda:casa-ciervo"
        )
        assert_dry_run_simulado(run)

    def test_el_ocr_degradado_no_vale_lo_mismo_que_el_texto_limpio(
        self, gold, entities
    ):
        _, limpio = run_text(gold, entities, "e2e-14-a", T_HECHO)
        _, sucio = run_text(gold, entities, "e2e-14-b", T_OCR)
        assert only_decision(sucio).confidence < only_decision(limpio).confidence

    def test_una_degradacion_NO_declarada_no_se_adivina(self, gold, entities):
        """El reconocimiento viene del glosario, no de una correccion magica."""
        _, run = run_text(
            gold, entities, "e2e-14-c", "Ilaria Vandreth lidera la Kasa del Zierbo."
        )
        assert run.claims == []


# ===========================================================================
# TRANSVERSAL: el dry-run no toca Neo4j en NINGUN escenario
# ===========================================================================
@pytest.mark.parametrize(
    "source_id,text",
    [
        ("t-01", T_HECHO),
        ("t-03", T_NEGACION),
        ("t-04", T_CESACION),
        ("t-05", T_NEG_CESACION),
        ("t-06", T_PREGUNTA),
        ("t-07", T_CONTRAFACTUAL),
        ("t-09", T_MIEMBRO),
        ("t-13", T_ALIAS),
        ("t-14", T_OCR),
    ],
)
def test_ningun_escenario_toca_el_driver_de_neo4j(gold, entities, source_id, text):
    """`ExplodingDriver` estalla en cuanto alguien lo mira. Ninguno lo mira."""
    _, run = run_text(gold, entities, source_id, text)
    if run.write_result is not None:
        assert run.write_result.outcome != "APPLIED"


# ===========================================================================
# DIFERIDOS A LA PUERTA 7 (Neo4j efimero, los ejecuta el coordinador en VM105)
# ===========================================================================
@pytest.mark.skip(
    reason="puerta 7 / Neo4j efimero: confirmar que el plan de E2E-01, ya "
    "simulado aqui, se APLICA de verdad contra un Neo4j efimero y que la "
    "idempotency_key impide la segunda escritura. Requiere Docker + Neo4j "
    "(S9K_WRITER_NEO4J_REAL=1); lo ejecuta el coordinador en VM105."
)
def test_e2e_01_aplicado_contra_neo4j_efimero():  # pragma: no cover
    raise AssertionError("no debe ejecutarse en este arbol")


@pytest.mark.skip(
    reason="puerta 7 / Neo4j efimero: confirmar que la retractacion del "
    "operador de E2E-12 se propaga al GRAFO y no solo al ledger en memoria. "
    "Requiere Docker + Neo4j (S9K_WRITER_NEO4J_REAL=1); lo ejecuta el "
    "coordinador en VM105."
)
def test_e2e_12_correccion_propagada_al_grafo_real():  # pragma: no cover
    raise AssertionError("no debe ejecutarse en este arbol")


# ===========================================================================
# DEFECTOS ENCONTRADOS. No se arreglan aqui: se dejan fallando en rojo-declarado.
# ===========================================================================
class TestDefectosDeProduccion:
    """Dos defectos REALES hallados recorriendo la ruta completa.

    Van con `xfail(strict=True)`: si alguien los arregla, el test PASA de forma
    inesperada y la suite avisa. Un `skip` los habria escondido.
    """

    # HALLAZGO D-G1 corregido: el marco explicito de rumor ya frena la escritura.
    def test_DG1_un_rumor_explicito_no_deberia_aprobarse(self, gold, entities):
        _, run = run_text(
            gold,
            entities,
            "def-g1",
            "Corre el rumor de que Daiki Oharu lidera la Casa del Ciervo.",
        )
        decision = only_decision(run)
        assert decision.decision != "ACCEPT", (
            f"un rumor salio {decision.decision} con plan "
            f"aprobado={run.plan.approved if run.plan else None}"
        )

    def test_DG1_control_la_marca_reconocida_si_frena(self, gold, entities):
        """El control que demuestra que D-G1 es una LAGUNA de vocabulario."""
        _, run = run_text(
            gold,
            entities,
            "def-g1-ctl",
            "Se dice que Daiki Oharu lidera la Casa del Ciervo.",
        )
        decision = only_decision(run)
        assert decision.decision == "REVIEW"
        assert decision.epistemic_status == "RUMORED"
        assert "EPISTEMIC_NOT_ASSERTED" in codes(decision)

    # HALLAZGO D-G2 corregido: export usa las listas de menciones de los contratos.
    def test_DG2_el_documento_de_revision_deberia_decir_de_quien_habla(
        self, gold, entities
    ):
        p = KnowledgePipeline(base_config(gold, writer_driver=ExplodingDriver()))
        result = p.run([raw_case("def-g2", T_NEGACION)], catalog_entities=entities)
        doc = review_documents(result, workspace=WORKSPACE)[0]
        assert doc["proposal"]["subject"] != "UNKNOWN", doc["proposal"]
        assert doc["proposal"]["object"] != "UNKNOWN", doc["proposal"]
        assert doc["resolution"]["subject"] is not None, doc["resolution"]

    def test_DG2_las_claves_que_review_export_busca_no_existen(self):
        """La causa raiz, aislada del resto de la cadena."""
        import dataclasses

        from knowledge_v3.contracts.claim import ClaimProposal
        from knowledge_v3.contracts.resolution import EntityResolution

        claim_fields = {f.name for f in dataclasses.fields(ClaimProposal)}
        resolution_fields = {f.name for f in dataclasses.fields(EntityResolution)}

        assert "subject_mention_id" not in claim_fields
        assert "object_mention_id" not in claim_fields
        assert "subject_mentions" in claim_fields
        assert "mention_id" not in resolution_fields
        assert "mention_ids" in resolution_fields


# ===========================================================================
# REPRODUCIBILIDAD DE LA RUTA COMPLETA
# ===========================================================================
#: Semillas del encargo.
SEEDS = ("1", "7", "42", "123")

#: Sonda de la CADENA ENTERA. Mismo patron que
#: `tests/reconcile_hashseed_probe.py` y `tests/planner_hashseed_probe.py`: se
#: ejecuta en un proceso NUEVO por semilla e imprime un unico sha256.
#:
#: Aquellas dos sondas cubren una etapa cada una (reconciliador y planner). Esta
#: cubre la costura completa —normalizador, extractor, reconciliador, resolutor,
#: motor, planner, ledger y writer en dry-run—, que es donde un orden de
#: iteracion inestable tiene mas sitio donde esconderse.
_CHAIN_PROBE = '''
import hashlib, json, sys
APP = {app!r}
sys.path.insert(0, APP)
sys.path.insert(0, APP + "/tests")
from test_knowledge_v3_e2e_fixtures import (
    NOW, WORKSPACE, base_config, gold_dev, snapshot_entities,
)
from knowledge_v3.multimodal.base import IngestOptions, SourceInput
from knowledge_v3.pipeline import KnowledgePipeline
from knowledge_v3.pipeline.pipeline import SourceCase

TEXTS = {texts!r}
gold = gold_dev()
entities = snapshot_entities(gold)
cases = [
    SourceCase(
        source_id="repro-%d" % i,
        source=SourceInput(
            data=t.encode("utf-8"), original_name="r%d.md" % i,
            original_location="mem://r%d" % i, mime_type="text/markdown",
            source_kind="MARKDOWN",
        ),
        ingest_options=IngestOptions(
            workspace=WORKSPACE, collection_id="collection:pruebas",
            ingested_at=NOW, created_at=NOW, game_profile="generic",
            language_hint="es",
        ),
    )
    for i, t in enumerate(TEXTS)
]
result = KnowledgePipeline(base_config(gold)).run(cases, catalog_entities=entities)
payload = []
for run in result.runs:
    summary = run.summary()
    # La latencia es un reloj, no un resultado: se cae fuera del hash a
    # proposito. Todo lo demas entra.
    summary.pop("reconciliation", None)
    payload.append({{
        "source_id": run.source_id,
        "summary": summary,
        "decisions": [
            {{
                "decision": d.decision, "predicate": d.predicate,
                "direction": d.direction, "negated": d.negated,
                "negation_kind": d.negation_kind,
                "findings": sorted(f.code for f in d.findings),
            }}
            for d in run.decisions
        ],
        "plan": run.plan.to_dict() if run.plan else None,
        "assertions": [a.to_dict() for a in run.assertions],
        "write": run.write_result.to_dict() if run.write_result else None,
    }})
blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
print(hashlib.sha256(blob.encode("utf-8")).hexdigest())
'''


def test_la_ruta_completa_es_identica_con_cualquier_pythonhashseed(tmp_path):
    """Cuatro semillas, cuatro procesos nuevos, un unico hash de la cadena.

    Se ejecuta en SUBPROCESOS a proposito: `PYTHONHASHSEED` se fija al arrancar
    el interprete, asi que cambiarlo dentro del proceso en curso daria un verde
    vacio.

    Lo que se firma incluye el `GraphMutationPlan` completo y el resultado del
    writer en dry-run, es decir `plan_hash` e `idempotency_key`. Si el orden de
    iteracion de un `set` se colase ahi, dos procesos firmarian el mismo plan
    con hashes distintos y la confirmacion manual del operador dejaria de
    significar nada.
    """
    probe = tmp_path / "e2e_global_hashseed_probe.py"
    probe.write_text(
        _CHAIN_PROBE.format(
            app=str(_APP_DIR),
            texts=(T_HECHO, T_NEGACION, T_CESACION, T_MIEMBRO),
        ),
        encoding="utf-8",
    )

    hashes: dict[str, str] = {}
    for seed in SEEDS:
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        env["PYTHONPATH"] = os.pathsep.join(
            part for part in (str(_APP_DIR), env.get("PYTHONPATH", "")) if part
        )
        completed = subprocess.run(
            [sys.executable, str(probe)],
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=600,
        )
        hashes[seed] = completed.stdout.strip()

    assert len(set(hashes.values())) == 1, f"la cadena cambia con la semilla: {hashes}"
    # Que sea un sha256 de verdad: sin esto, una sonda muda pasaria el assert
    # anterior con cuatro cadenas vacias.
    assert len(next(iter(hashes.values()))) == 64, hashes


def test_las_sondas_de_semilla_ya_existentes_siguen_verdes():
    """Las dos sondas por etapa se ejecutan aqui tambien, con las 4 semillas.

    No duplica `test_knowledge_v3_planner_reproducibility.py` (que corre solo la
    del planner): lo que se comprueba es que las TRES sondas —reconciliador,
    planner y cadena completa— pertenecen al mismo regimen y se pueden auditar
    juntas desde un unico sitio.
    """
    resultados: dict[str, set[str]] = {}
    for nombre in ("reconcile_hashseed_probe.py", "planner_hashseed_probe.py"):
        probe = _TESTS_DIR / nombre
        assert probe.exists(), probe
        vistos: set[str] = set()
        for seed in SEEDS:
            env = os.environ.copy()
            env["PYTHONHASHSEED"] = seed
            env["PYTHONPATH"] = os.pathsep.join(
                part for part in (str(_APP_DIR), env.get("PYTHONPATH", "")) if part
            )
            completed = subprocess.run(
                [sys.executable, str(probe)],
                env=env,
                check=True,
                capture_output=True,
                text=True,
                timeout=600,
            )
            vistos.add(completed.stdout.strip())
        resultados[nombre] = vistos

    for nombre, vistos in resultados.items():
        assert len(vistos) == 1, f"{nombre} cambia con la semilla: {vistos}"
        assert len(next(iter(vistos))) == 64, (nombre, vistos)
