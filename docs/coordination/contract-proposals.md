# Contratos internos propuestos (OLA 1)

Propuestas **internas y versionadas**. No modifican el contrato público v1. Su
promoción a v2 requiere aprobación del Supervisor.

## §1 — Contrato interno de relaciones (Equipo A, A-REL-1)

`relation-candidate/internal-v1` — una relación propuesta por el pipeline nuevo
`data-engine/app/relations/`. Campos obligatorios:

```json
{
  "schema_version": "internal-1.0.0",
  "document_type": "relation-candidate",
  "relation_id": "<stable_id>",
  "subject_id": "<entity_id>",
  "predicate": "<PREDICATE_ENUM>",
  "object_id": "<entity_id>",
  "direction": "SUBJECT_TO_OBJECT | OBJECT_TO_SUBJECT | UNDIRECTED",
  "confidence": 0.0,
  "evidence_text": "<cita literal mínima>",
  "evidence_span": {"start": 0, "end": 0},
  "source_id": "<sanitized>",
  "source_page": null,
  "source_segment": "<segment_id>",
  "extraction_method": "HEURISTIC | LLM_LOCAL | NVIDIA | ONTOLOGY",
  "model": "<model@version | null>",
  "negated": false,
  "temporal_scope": "<null | {before|after|during: evento/fecha}>",
  "epistemic_status": "ASSERTED | RUMORED | HYPOTHETICAL | INTENDED",
  "workspace": "<workspace>",
  "validation_flags": ["<flag>", "..."]
}
```

Reglas: `evidence_text` obligatorio y literal; sin evidencia → no autoaprobable.
`negated=true` invalida la afirmación positiva. `epistemic_status != ASSERTED` no es
hecho confirmado. `predicate` restringido a la ontología por workspace.

Estados de consenso del ensemble (reusa los existentes): `STRONG · PARTIAL ·
CONFLICT · INVALID · HUMAN`. Vetos: schema inválido, tipos incompatibles, evidencia
ausente, negación ignorada, workspace incorrecto, procedencia incompleta,
contradicción grave.

Casos obligatorios de A-REL-3 (sintaxis): `Akodo no pertenece al Clan Grulla` →
sin `MEMBER_OF` afirmativa; `Se dice que Bayushi traicionó…` → `RUMORED`;
`Fue vasallo de Hantei antes de la guerra` → `temporal_scope.before`.

## §2 — Contrato interno export/import (Equipo B, B-EXP-1c)

`s9-knowledge-export/internal-v1`. Extiende `test_review_export_import` (ya redacta
IPs/rutas). Paquete = ZIP manifestado:

```json
{
  "manifest_version": "internal-1.0.0",
  "workspace": "<workspace>",
  "filters": {"entity_types": [], "since": null},
  "created_at": "<iso8601Z>",
  "formats": ["jsonl", "json", "csv", "graphml", "markdown"],
  "counts": {"entities": 0, "relations": 0, "aliases": 0},
  "schemas": {"entity": "v1", "relation": "internal-v1"},
  "hashes": {"<file>": "sha256:..."},
  "compatibility": {"min_reader": "internal-1.0.0"}
}
```

**No exporta**: contraseñas, sesiones, secretos, rutas internas, tokens, config
sensible. Export según permisos de workspace.

Import: `VALID · INVALID · WOULD_CREATE · WOULD_UPDATE · WOULD_LINK · CONFLICT ·
DUPLICATE · DEFERRED`. **Dry-run por defecto; APPLY nunca por defecto.** No importa
dumps internos de Neo4j como contrato de usuario. Suite hostil obligatoria (RK-03).

## §3 — Contrato interno multimedia (Equipo B, B-IMG-1)

`multimedia-artifact/internal-v1`. Toda salida incluye: `file, page, region,
bounding_box, method, model, confidence, language, orientation, visual_evidence,
hash`. Tipos separados (OCR ≠ comprensión visual):

`OCR_TEXT · IMAGE_DESCRIPTION · TABLE · MAP · DIAGRAM · CHARACTER_SHEET ·
UNKNOWN_VISUAL`.

Pipeline: archivo → clasificación → metadata → texto embebido → detección de
necesidad OCR → layout → OCR → comprensión visual → fusión → dedupe → procedencia →
candidatos → revisión. Corpus visual **sanitizado**; sin producción.

## Promoción a v2

Ninguno de estos contratos se promueve a `contracts/**` v2 sin: (1) benchmark que
demuestre valor, (2) Supervisor CONFORME, (3) PR de integración del Organizador.
