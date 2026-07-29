# -*- coding: utf-8 -*-
"""Verificacion independiente del ProposalReconciler.

Estos tests NO los escribio quien implemento el reconciliador: se derivan de los
diez criterios de revision de `docs/v3/22-encargo-equipo-externo-reconciliador.md`
y se ejecutaron contra la entrega antes de aceptarla.

El criterio que manda es el test de aceptacion (`test_aceptacion_*`): la union de
extractores no puede destruir los claims que el semantico consigue en solitario.
Todo lo demas existe para que ese resultado sea reproducible y no una casualidad.
"""
from __future__ import annotations

import copy
import json
import random

import pytest

from knowledge_v3.benchmarks.loader import load_gold
from knowledge_v3.contracts import parse_document
from knowledge_v3.extraction.base import ExtractionOutput
from knowledge_v3.reconcile import (
    DEFAULT_INDEPENDENCE_REGISTRY,
    ProposalReconciler,
)

_STEPS = {
    "det": ("extract.deterministic", "local"),
    "sem": ("extract.semantic", "ollama"),
    "sem2": ("extract.semantic", "external"),
}


@pytest.fixture(scope="module")
def gold():
    return load_gold("dev")


@pytest.fixture()
def reconciler():
    return ProposalReconciler()


def _reatribuir(doc: dict, origen: str) -> dict:
    """Reescribe la procedencia como si el documento viniera de otro extractor."""
    step, provider = _STEPS[origen]
    trace = [dict(p) for p in (doc.get("provider_trace") or [])]
    if trace:
        trace[0]["step"] = step
        trace[0]["provider"] = provider
    doc["provider_trace"] = trace
    doc["produced_by_step"] = step
    return doc


def _mencion(base: dict, mention_id: str, origen: str):
    doc = _reatribuir(copy.deepcopy(base), origen)
    doc["mention_id"] = mention_id
    return parse_document(doc)


def _claim(base: dict, claim_id: str, origen: str, **campos):
    doc = _reatribuir(copy.deepcopy(base), origen)
    doc["claim_id"] = claim_id
    doc.update(campos)
    return parse_document(doc)


def _serializar(salida: ExtractionOutput) -> str:
    def volcar(documentos):
        return [
            json.dumps(d if isinstance(d, dict) else d.to_dict(), sort_keys=True)
            for d in documentos
        ]

    return json.dumps(
        {"m": volcar(salida.mentions), "c": volcar(salida.claims)}, sort_keys=True
    )


def _soporte(claim) -> dict:
    doc = claim if isinstance(claim, dict) else claim.to_dict()
    return ((doc.get("metadata") or {}).get("reconciliation") or {}).get("support", {})


# --------------------------------------------------------------------------
# Fusion de lo equivalente
# --------------------------------------------------------------------------
def test_dos_extractores_sobre_el_mismo_span_se_fusionan(gold, reconciler):
    """El caso que motiva el componente: mismo tramo, ids distintos."""
    base = list(gold.mentions)[:6]
    entrada = ExtractionOutput(
        mentions=tuple(
            _mencion(m, f"{origen}-m-{i}", origen)
            for i, m in enumerate(base)
            for origen in ("det", "sem")
        )
    )
    assert len(entrada.mentions) == 12

    salida = reconciler.reconcile(entrada)

    assert len(salida.mentions) == 6, "los duplicados exactos deben colapsar"


# --------------------------------------------------------------------------
# Lo que NO debe fusionarse
# --------------------------------------------------------------------------
def test_la_polaridad_distinta_no_se_fusiona(gold, reconciler):
    """"A pertenece a B" y "A no pertenece a B" no son el mismo hecho."""
    base = next(c for c in gold.claims if not c.get("abstained"))
    entrada = ExtractionOutput(
        claims=(
            _claim(base, "afirmado", "det", negated=False),
            _claim(base, "negado", "sem", negated=True),
        )
    )

    salida = reconciler.reconcile(entrada)

    assert len(salida.claims) == 2


def test_los_predicados_rivales_sobreviven_como_candidatos(gold, reconciler):
    """No vota: si un extractor discrepa, su lectura llega al motor."""
    base = next(c for c in gold.claims if not c.get("abstained"))
    propio = base["predicate_candidates"][0]["predicate"]
    rival = "MEMBER_OF" if propio != "MEMBER_OF" else "LEADS"
    entrada = ExtractionOutput(
        claims=(
            _claim(base, "a", "det"),
            _claim(base, "b", "sem"),
            _claim(
                base,
                "c",
                "sem2",
                predicate_candidates=[{"predicate": rival, "confidence": 0.5}],
            ),
        )
    )

    salida = reconciler.reconcile(entrada)
    doc = salida.claims[0]
    doc = doc if isinstance(doc, dict) else doc.to_dict()
    predicados = {p["predicate"] for p in doc["predicate_candidates"]}

    assert {propio, rival} <= predicados, "se perdio la lectura de un extractor"


# --------------------------------------------------------------------------
# Independencia: dos modelos con el mismo prompt no son dos pruebas
# --------------------------------------------------------------------------
def test_dos_semanticos_del_mismo_prompt_son_una_sola_familia(gold, reconciler):
    base = next(c for c in gold.claims if not c.get("abstained"))
    entrada = ExtractionOutput(
        claims=(_claim(base, "qwen", "sem"), _claim(base, "llama", "sem2"))
    )

    soporte = _soporte(reconciler.reconcile(entrada).claims[0])

    assert soporte["providers"] == 2
    assert soporte["independent_families"] == 1


def test_determinista_y_semantico_son_familias_independientes(gold, reconciler):
    base = next(c for c in gold.claims if not c.get("abstained"))
    entrada = ExtractionOutput(
        claims=(_claim(base, "det", "det"), _claim(base, "sem", "sem"))
    )

    soporte = _soporte(reconciler.reconcile(entrada).claims[0])

    assert soporte["providers"] == 2
    assert soporte["independent_families"] == 2


def test_el_registro_de_familias_esta_versionado():
    assert DEFAULT_INDEPENDENCE_REGISTRY.version


# --------------------------------------------------------------------------
# Determinismo: es contrato, no detalle
# --------------------------------------------------------------------------
def test_el_orden_de_llegada_no_altera_la_salida(gold, reconciler):
    base = list(gold.mentions)[:6]
    documentos = [
        _mencion(m, f"{origen}-m-{i}", origen)
        for i, m in enumerate(base)
        for origen in ("det", "sem")
    ]
    esperado = _serializar(reconciler.reconcile(ExtractionOutput(mentions=tuple(documentos))))

    for semilla in range(30):
        barajado = list(documentos)
        random.Random(semilla).shuffle(barajado)
        obtenido = _serializar(
            reconciler.reconcile(ExtractionOutput(mentions=tuple(barajado)))
        )
        assert obtenido == esperado, f"la permutacion {semilla} cambia la salida"


def test_reconciliar_dos_veces_no_cambia_nada(gold, reconciler):
    base = list(gold.mentions)[:6]
    entrada = ExtractionOutput(
        mentions=tuple(
            _mencion(m, f"{origen}-m-{i}", origen)
            for i, m in enumerate(base)
            for origen in ("det", "sem")
        )
    )

    una = reconciler.reconcile(entrada)
    dos = reconciler.reconcile(una)

    assert _serializar(una) == _serializar(dos)


def test_con_un_solo_extractor_la_salida_es_la_entrada(gold, reconciler):
    """Protege la ruta determinista de los gates, la unica reproducible bit a bit."""
    base = list(gold.mentions)[:6]
    entrada = ExtractionOutput(
        mentions=tuple(_mencion(m, f"det-m-{i}", "det") for i, m in enumerate(base))
    )

    salida = reconciler.reconcile(entrada)

    assert _serializar(salida) == _serializar(entrada)


# --------------------------------------------------------------------------
# ACEPTACION: la razon de ser del componente
# --------------------------------------------------------------------------
def test_aceptacion_la_union_no_puede_destruir_los_claims_del_semantico(gold, reconciler):
    """Sin reconciliador, unir extractores lleva los claims correctos a cero.

    Se reproduce con documentos gold: dos extractores proponen las mismas
    menciones con ids distintos y un claim que las referencia. Si el
    reconciliador no alinea las menciones, el claim se queda sin argumentos.
    """
    menciones = list(gold.mentions)[:4]
    claim = next(c for c in gold.claims if not c.get("abstained"))

    union = ExtractionOutput(
        mentions=tuple(
            _mencion(m, f"{origen}-m-{i}", origen)
            for i, m in enumerate(menciones)
            for origen in ("det", "sem")
        ),
        claims=(_claim(claim, "sem-c", "sem"),),
    )

    salida = reconciler.reconcile(union)

    assert len(salida.mentions) == 4, "las menciones duplicadas deben alinearse"
    assert len(salida.claims) == 1, "el claim del semantico no puede perderse"
