# -*- coding: utf-8 -*-
"""Helpers COMPARTIDOS de la QA final OLA 2B Lote 3 (`tests/wave2b`).

NO es un fichero de test (no coincide con `test_*.py`, no lo recoge pytest) y NO
reimplementa producto: solo construye PAYLOADS de entrada y dobles de transporte
inyectables para ejercitar los componentes REALES de `relations.*`.

Se importa por ruta absoluta del directorio para ser robusto frente al modo de
import de pytest (el conftest de `tests/wave2b` ya pone `data-engine/app` en el
path para que `relations`/`external_ai` sean importables como top-level).
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional


def ent(eid: str, text: str, etype: str, start: int) -> dict:
    """Entidad de entrada con offsets de caracter (forma consumida por generate_pairs)."""
    return {"id": eid, "text": text, "type": etype, "start": start, "end": start + len(text)}


def find_ent(eid: str, text: str, etype: str, whole: str) -> dict:
    """Como `ent` pero localiza el offset de `text` dentro de `whole`."""
    pos = whole.find(text)
    assert pos >= 0, f"mencion {text!r} no encontrada en el texto"
    return ent(eid, text, etype, pos)


def segment(text: str, entities: list, *, segment_id: str = "s1", workspace: str = "ws1",
            source_id: str = "d1") -> dict:
    return {
        "segment_id": segment_id,
        "text": text,
        "workspace": workspace,
        "source_id": source_id,
        "entities": entities,
    }


def payload(text: str, entities: list, *, workspace: str = "ws1", source_id: str = "d1",
            segment_id: str = "s1") -> dict:
    return {
        "source_id": source_id,
        "workspace": workspace,
        "segments": [segment(text, entities, segment_id=segment_id, workspace=workspace,
                             source_id=source_id)],
    }


# Texto de ejemplo con relacion simple de pertenencia (universo ficticio).
SIMPLE_TEXT = "Aria es miembro de la Orden del Alba."


def simple_payload(**over) -> dict:
    ents = [
        find_ent("e:aria", "Aria", "Character", SIMPLE_TEXT),
        find_ent("e:orden", "Orden del Alba", "Faction", SIMPLE_TEXT),
    ]
    return payload(SIMPLE_TEXT, ents, **over)


def relation_verdict_content(*, predicate: str = "MEMBER_OF",
                             evidence: str = SIMPLE_TEXT,
                             evidence_start: int = 0,
                             evidence_end: Optional[int] = None) -> str:
    """Contenido JSON valido para el transporte del LLM local (una relacion)."""
    if evidence_end is None:
        evidence_end = len(evidence)
    rel = {
        "predicate": predicate,
        "direction": "SUBJECT_TO_OBJECT",
        "confidence": 0.9,
        "evidence_text": evidence,
        "evidence_start": evidence_start,
        "evidence_end": evidence_end,
        "negated": False,
        "temporal_scope": None,
        "epistemic_status": "ASSERTED",
        "subject_type": "Character",
        "object_type": "Faction",
    }
    return json.dumps({"relations": [rel]})


def make_local_transport(content: str, latency: int = 5) -> Callable[[list], Any]:
    """Transporte LOCAL inyectable (duck-typed) que NO abre red."""
    def _transport(messages: list):
        assert isinstance(messages, list)
        return ({"choices": [{"message": {"content": content}}],
                 "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}},
                latency)
    return _transport


class FakeExternalProvider:
    """Proveedor EXTERNO inyectable (mismo contrato `_post_chat`), sin red."""

    provider_name = "nvidia"

    def __init__(self, content: str):
        self._content = content
        self.last_messages = None

    def _post_chat(self, model, messages):
        self.last_messages = messages
        return ({"choices": [{"message": {"content": self._content}}]}, 7)


def external_verdicts_content(*verdicts: dict) -> str:
    return json.dumps({"verdicts": list(verdicts)}, ensure_ascii=False)
