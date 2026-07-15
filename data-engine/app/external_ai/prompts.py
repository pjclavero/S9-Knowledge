# -*- coding: utf-8 -*-
"""Construcción de prompts para la revisión de candidatos de entidades RPG.

Genera mensajes en formato OpenAI chat (lista de dicts con 'role'/'content')
para dos casos de uso:
  - build_review_prompt: revisión independiente de un lote de candidatos.
  - build_adjudication_prompt: arbitraje de desacuerdos entre dos revisores.

Modo sombra: ningún resultado escribe en Neo4j.
"""
from __future__ import annotations

import json

from external_ai.models import (
    ALLOWED_ENTITY_TYPES,
    VALID_DECISIONS,
    ReviewBatchRequest,
    ReviewItem,
)

PROMPT_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Prompt de sistema compartido (esquema JSON y reglas)
# ---------------------------------------------------------------------------

_SYSTEM_CORE = """\
Eres un revisor independiente de candidatos de entidades para un grafo de \
conocimiento de juego de rol (RPG). Tu función es exclusivamente analítica: \
NUNCA escribes en base de datos ni en Neo4j.

## Tarea
Devuelves ÚNICAMENTE JSON válido con la estructura:
{{"reviews": [ <objeto_review>, ... ]}}

Cada <objeto_review> tiene EXACTAMENTE estas claves (ni más, ni menos):
{{
  "candidate_id":   <string — ID del candidato, obligatorio>,
  "decision":       <string — una de: {valid_decisions}>,
  "canonical_name": <string o null — nombre canónico corregido, o null>,
  "entity_type":    <string o null — uno de: {allowed_types}, o null>,
  "matched_existing": <string o null — ID/nombre de entidad ya existente, o null>,
  "evidence":       <string — cita LITERAL extraída del texto del segmento, \
NUNCA inventada>,
  "confidence":     <número entre 0.0 y 1.0>,
  "reason_codes":   <lista de strings — códigos breves de motivo>,
  "explanation":    <string — explicación concisa en español>,
  "warnings":       <lista de strings — avisos opcionales>
}}

## Reglas estrictas
1. `decision` debe ser exactamente uno de: {valid_decisions}.
2. `entity_type` debe ser exactamente uno de: {allowed_types} — o null.
3. `evidence` DEBE ser una subcadena literal copiada del texto del segmento \
del candidato. Prohibido inventar o parafrasear.
4. `confidence` entre 0.0 y 1.0.
5. Usa `use_existing` solo si `matched_existing` está informado y es \
inequívoco.
6. Rechaza (`reject`) palabras comunes, verbos, stopwords, duplicados y \
candidatos sin evidencia en el texto.
7. Usa `edit` para corregir nombre canónico, tipo, capitalización o texto \
espurio.
8. No inventes claves adicionales.
9. La salida puede ir en un bloque ```json … ``` o como JSON puro, pero debe \
ser parseable.
""".format(
    valid_decisions=" | ".join(VALID_DECISIONS),
    allowed_types=" | ".join(ALLOWED_ENTITY_TYPES),
)


def _sanitize_text(text: str, max_chars: int = 600) -> str:
    """Trunca y limpia texto para incluirlo en el prompt sin exceso de tokens."""
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars] + " [...]"
    return text


def _format_neo4j_matches(matches: list) -> str:
    """Serializa coincidencias Neo4j de forma compacta."""
    if not matches:
        return "(ninguna)"
    parts = []
    for m in matches:
        if isinstance(m, dict):
            parts.append(json.dumps(m, ensure_ascii=False))
        else:
            parts.append(str(m))
    return "; ".join(parts)


def _format_glossary(glossary: list) -> str:
    """Une términos del glosario en una línea legible."""
    if not glossary:
        return "(vacío)"
    return ", ".join(str(g) for g in glossary)


def _format_item_block(idx: int, item: ReviewItem) -> str:
    """Genera el bloque de texto de un ReviewItem numerado para el prompt."""
    neo4j_str = _format_neo4j_matches(item.neo4j_matches)
    segment = _sanitize_text(item.segment_text)
    evidence = _sanitize_text(item.evidence, max_chars=300)
    return (
        f"--- Candidato {idx} ---\n"
        f"candidate_id: {item.candidate_id}\n"
        f"kind: {item.kind}\n"
        f"name: {item.name!r}\n"
        f"entity_type: {item.entity_type!r}\n"
        f"local_confidence: {item.local_confidence}\n"
        f"evidence (cita local): {evidence!r}\n"
        f"segment_text: {segment!r}\n"
        f"neo4j_matches: {neo4j_str}"
    )


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


def build_review_prompt(request: ReviewBatchRequest, model: str) -> list[dict]:
    """Construye los mensajes de revisión para un lote de candidatos.

    Parámetros
    ----------
    request:
        Lote de revisión ya sanitizado.
    model:
        Identificador del modelo destino (informativo, puede usarse para
        ajustar instrucciones en el futuro).

    Devuelve
    --------
    Lista de dicts con 'role' y 'content' compatible con la API OpenAI chat.
    """
    system_content = _SYSTEM_CORE

    item_blocks = "\n\n".join(
        _format_item_block(i + 1, item)
        for i, item in enumerate(request.items)
    )

    user_content = (
        f"## Contexto del lote\n"
        f"workspace: {request.workspace}\n"
        f"source_id (anonimizado): {request.source_id}\n"
        f"schema_version: {request.schema_version}\n"
        f"prompt_version: {request.prompt_version}\n"
        f"allowed_types: {', '.join(request.allowed_types)}\n"
        f"glosario canónico: {_format_glossary(request.glossary)}\n\n"
        f"## Candidatos a revisar ({len(request.items)} en total)\n\n"
        f"{item_blocks}\n\n"
        f"## Instrucción final\n"
        f"Devuelve un objeto JSON con la clave \"reviews\" conteniendo exactamente "
        f"{len(request.items)} objetos, uno por cada candidate_id listado arriba. "
        f"No omitas ninguno. No añadas candidatos inventados."
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def build_adjudication_prompt(
    item: dict,
    response_a: dict,
    response_b: dict,
    request: ReviewBatchRequest,
) -> list[dict]:
    """Construye el prompt de arbitraje para un candidato con revisores en desacuerdo.

    Parámetros
    ----------
    item:
        Dict del ReviewItem original (puede ser ReviewItem.to_dict() o dict crudo).
    response_a:
        Decisión del revisor A (dict con las claves del esquema de review).
    response_b:
        Decisión del revisor B.
    request:
        Lote de revisión original (para contexto: workspace, glosario, tipos).

    Devuelve
    --------
    Lista de mensajes OpenAI chat. La respuesta esperada es UN SOLO objeto review
    JSON (o {"reviews":[uno]}).
    """
    candidate_id = item.get("candidate_id", "desconocido")
    segment = _sanitize_text(str(item.get("segment_text", "")))
    evidence = _sanitize_text(str(item.get("evidence", "")), max_chars=300)
    neo4j_str = _format_neo4j_matches(item.get("neo4j_matches", []))

    system_content = (
        _SYSTEM_CORE
        + "\n## Rol especial: ÁRBITRO\n"
        "Eres el árbitro entre dos revisores que han discrepado. "
        "Debes devolver UN ÚNICO objeto review para el candidato indicado. "
        "Puedes devolver {\"reviews\":[<un_objeto>]} o directamente el objeto. "
        "Analiza ambas decisiones con imparcialidad y aplica las mismas reglas "
        "que un revisor ordinario. Si los dos están equivocados, decide tú."
    )

    user_content = (
        f"## Arbitraje de desacuerdo\n\n"
        f"### Candidato\n"
        f"candidate_id: {candidate_id}\n"
        f"kind: {item.get('kind', '?')}\n"
        f"name: {item.get('name', None)!r}\n"
        f"entity_type: {item.get('entity_type', None)!r}\n"
        f"local_confidence: {item.get('local_confidence', 0.0)}\n"
        f"evidence (cita local): {evidence!r}\n"
        f"segment_text: {segment!r}\n"
        f"neo4j_matches: {neo4j_str}\n\n"
        f"### Contexto del lote\n"
        f"workspace: {request.workspace}\n"
        f"allowed_types: {', '.join(request.allowed_types)}\n"
        f"glosario canónico: {_format_glossary(request.glossary)}\n\n"
        f"### Decisión del Revisor A\n"
        f"{json.dumps(response_a, ensure_ascii=False, indent=2)}\n\n"
        f"### Decisión del Revisor B\n"
        f"{json.dumps(response_b, ensure_ascii=False, indent=2)}\n\n"
        f"### Instrucción de arbitraje\n"
        f"Los revisores A y B han discrepado en su decisión para "
        f"candidate_id={candidate_id!r}. "
        f"Analiza sus argumentos, aplica las reglas del sistema y devuelve "
        f"TU decisión final como un único objeto JSON de review (o "
        f"{{\"reviews\":[<tu_decision>]}}). "
        f"No repitas el esquema de los revisores si contiene errores; "
        f"construye la respuesta correcta desde cero."
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]
