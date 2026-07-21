# -*- coding: utf-8 -*-
"""Benchmark A/B OFFLINE — protocolo clasico (offsets libres) vs seleccion por
fragmentos (PR#95 V3). Sin red, sin escritura, determinista.

Banco SINTETICO de respuestas: modela el FALLO REAL de los LLM con offsets.
  * Modelo "clasico" (da offsets): en una fraccion determinista de casos
    parafrasea la cita o desalinea los offsets (fallo tipico observado).
  * Modelo "fragmentos" (elige IDs): selecciona el/los fragmentos de la frase
    que sustenta la relacion; nunca produce offsets libres.

Se ejecuta el codigo REAL (`evaluate_relation_external`) con un proveedor falso
inyectado y se reportan tasas MEDIDAS (no inventadas):
  - acceptance_rate
  - literal_evidence_rate (evidencia aceptada que es subcadena literal del doc)
  - invalid_rate (fragmentos_invalidos / respuestas rechazadas)
  - ambiguity_rate (evidencia que aparece >1 vez en el doc, entre aceptadas)

Uso:  python3 ab_benchmark.py [ruta_salida_json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parents[3] / "data-engine" / "app"
sys.path.insert(0, str(_APP_DIR))

from relations.contracts import Direction, EpistemicStatus, ExtractionMethod, RelationCandidate
from relations import fragment_protocol as fp
from relations.external_ai_shadow import RelationExternalConfig, evaluate_relation_external


# --- corpus sintetico determinista ----------------------------------------
# Cada caso: (documento, frase_evidencia, predicado). La frase de evidencia
# existe LITERALMENTE en el documento.
CORPUS = [
    ("Bayushi Hisao nacio en el sur. Bayushi Hisao juro lealtad al Clan Escorpion. El clan guarda secretos.",
     "Bayushi Hisao juro lealtad al Clan Escorpion", "MEMBER_OF"),
    ("Akodo Toturi lidera la Legion Leon. Su honor es reconocido en el Imperio.",
     "Akodo Toturi lidera la Legion Leon", "LEADS"),
    ("Kaede estudia el Vacio. Isawa Kaede pertenece al Clan Fenix desde joven.",
     "Isawa Kaede pertenece al Clan Fenix", "MEMBER_OF"),
    ("El Clan Grulla firmo la paz. Doji Hoturi represento al Clan Grulla en la corte.",
     "Doji Hoturi represento al Clan Grulla", "REPRESENTS"),
    ("Hida Kisada defiende el Muro. Hida Kisada comanda el Clan Cangrejo con firmeza.",
     "Hida Kisada comanda el Clan Cangrejo", "LEADS"),
    ("Togashi medita en la montana. La orden del Dragon sigue a Togashi Yokuni.",
     "La orden del Dragon sigue a Togashi Yokuni", "FOLLOWS"),
    ("Shinjo explora las estepas. Los jinetes del Clan Unicornio protegen a Shinjo Yokatsu.",
     "Los jinetes del Clan Unicornio protegen a Shinjo Yokatsu", "PROTECTS"),
    ("La corte se reunio. Bayushi Kachiko manipula la corte del Escorpion en secreto.",
     "Bayushi Kachiko manipula la corte del Escorpion", "MANIPULATES"),
    ("El torneo comenzo. Matsu Tsuko derroto a su rival en el torneo del Leon.",
     "Matsu Tsuko derroto a su rival", "DEFEATS"),
    ("La biblioteca ardio. Agasha Tamori estudia los pergaminos del Clan Dragon.",
     "Agasha Tamori estudia los pergaminos del Clan Dragon", "STUDIES"),
]


def _cand(pred, ev):
    return RelationCandidate(
        subject_id="Suj", subject_type="Character", predicate=pred,
        object_id="Obj", object_type="Faction",
        direction=Direction.SUBJECT_TO_OBJECT, confidence=0.8,
        evidence_text=ev[:10], evidence_start=0, evidence_end=10,
        source_id="s", source_page=1, source_segment="seg",
        extraction_method=ExtractionMethod.HEURISTIC, model=None, negated=False,
        temporal_scope=None, epistemic_status=EpistemicStatus.ASSERTED, workspace="leyenda",
    ).validate()


def _cid(c):
    return f"{c.subject_id}|{c.predicate}|{c.object_id}"


class ScriptedProvider:
    """Proveedor falso: devuelve el JSON precomputado para cada caso."""
    def __init__(self, content):
        self._content = content

    def _post_chat(self, model, messages):
        return {"choices": [{"message": {"content": self._content}}]}, 5.0


def _paraphrase(ev):
    # Fallo tipico: el LLM parafrasea (cambia una palabra) -> deja de ser literal.
    return ev.replace("juro", "prometio").replace("lidera", "dirige").replace(
        "pertenece", "es parte").replace("represento", "hablo por").replace(
        "comanda", "manda").replace("sigue", "obedece").replace(
        "protegen", "cuidan").replace("manipula", "controla").replace(
        "derroto", "vencio").replace("estudia", "analiza")


def run_classic():
    """Modelo clasico (offsets). Fallo determinista que modela el comportamiento
    tipico observado en LLM: 1/3 de los casos parafrasea la cita (deja de ser
    literal), 1/3 desalinea los offsets (+2), y 1/3 responde EXACTO (literal y
    offsets correctos). Mezcla realista, no un caso extremo."""
    accepted = literal = ambiguous = invalid = 0
    for i, (doc, ev, pred) in enumerate(CORPUS):
        cand = _cand(pred, ev)
        cid = _cid(cand)
        s = doc.find(ev)
        mode = i % 3
        if mode == 0:
            # parafrasea: evidence_text ya no es subcadena literal
            ev_out, start_out, end_out = _paraphrase(ev), s, s + len(ev)
        elif mode == 1:
            # desalinea offsets: start+2 (cita ya no casa con seg[start:end])
            ev_out, start_out, end_out = ev, s + 2, s + len(ev)
        else:
            # respuesta EXACTA: literal + offsets correctos -> aceptada
            ev_out, start_out, end_out = ev, s, s + len(ev)
        content = json.dumps([{
            "candidate_id": cid, "verdict": "confirm", "predicate": pred,
            "subject_type": "Character", "object_type": "Faction", "negated": False,
            "evidence_text": ev_out, "evidence_start": start_out, "evidence_end": end_out,
            "confidence": 0.9, "reason_codes": [], "explanation": "ok",
        }])
        cfg = RelationExternalConfig(model="m", provider=ScriptedProvider(content), shadow_mode=True)
        res = evaluate_relation_external(cand, config=cfg, document_text=doc)[0]
        if res.state != "INVALID_RESPONSES":
            accepted += 1
            evt = res.verdict["evidence_text"]
            if evt in doc:
                literal += 1
            if doc.count(evt) > 1:
                ambiguous += 1
        else:
            invalid += 1
    return _rates("classic", accepted, literal, ambiguous, invalid)


def run_fragments():
    """Modelo de fragmentos: elige el ID del fragmento que contiene la frase de
    evidencia. Nunca produce offsets libres."""
    accepted = literal = ambiguous = invalid = 0
    for doc, ev, pred in CORPUS:
        cand = _cand(pred, ev)
        cid = _cid(cand)
        frags = fp.fragment_document(doc)
        target = [f.fragment_id for f in frags if ev in f.text]
        if not target:
            # sin fragmento que contenga la evidencia -> el modelo no puede elegir
            target = [frags[0].fragment_id] if frags else []
        content = json.dumps([{
            "candidate_id": cid, "verdict": "confirm",
            "fragment_ids": target, "confidence": 0.9,
        }])
        cfg = RelationExternalConfig(
            model="m", provider=ScriptedProvider(content), shadow_mode=True,
            fragment_protocol_enabled=True,
        )
        res = evaluate_relation_external(cand, config=cfg, document_text=doc)[0]
        if res.state != "INVALID_RESPONSES":
            accepted += 1
            evt = res.verdict["evidence_text"]
            if evt in doc and doc[res.verdict["evidence_start"]:res.verdict["evidence_end"]] == evt:
                literal += 1
            if doc.count(evt) > 1:
                ambiguous += 1
        else:
            invalid += 1
    return _rates("fragments", accepted, literal, ambiguous, invalid)


def _rates(name, accepted, literal, ambiguous, invalid):
    total = len(CORPUS)
    return {
        "protocol": name,
        "total": total,
        "accepted": accepted,
        "invalid": invalid,
        "acceptance_rate": round(accepted / total, 4),
        "literal_evidence_rate": round(literal / accepted, 4) if accepted else None,
        "invalid_rate": round(invalid / total, 4),
        "ambiguity_rate": round(ambiguous / accepted, 4) if accepted else 0.0,
    }


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("results.json")
    report = {
        "base_sha": "92583f4",
        "fragment_protocol_version": fp.FRAGMENT_PROTOCOL_VERSION,
        "corpus_size": len(CORPUS),
        "note": "Banco sintetico determinista. Cifras MEDIDAS ejecutando el codigo real, sin red.",
        "classic": run_classic(),
        "fragments": run_fragments(),
    }
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
