"""data-engine/app/review — Pipeline de revisión S9 Knowledge.

Módulos:
  models          — Dataclasses del pipeline (Segment, Candidate, …)
  segmenter       — Segmenta transcripciones en bloques de 3-5 min
  classifier      — Clasifica segmentos y decide should_extract
  extractor       — Extrae candidatos de entidades/relaciones/eventos
  validator       — Valida candidatos contra el schema RPG
  resolver        — Busca coincidencias en Neo4j (solo lectura)
  auto_decider    — Decide auto_approve / needs_review / auto_reject
  review_store    — Persiste estados en JSON y SQLite
  approved_writer — Genera los JSON y review.md finales
  ingest_approved — Escribe en Neo4j desde approved_payload.json (--dry-run obligatorio en esta fase)
  pipeline        — Orquesta todos los pasos
"""
