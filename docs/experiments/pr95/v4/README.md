# PR#95 V4 — Motor hibrido por etapas (hybrid staged engine)

- **SHA base**: `92583f4` (`exp(pr95-base): corrige contrato DOCUMENTO/ID del evaluador externo (P0)`)
- **Rama**: `exp/pr95-v4-hybrid-staged-engine`
- **Alcance**: la version mas ambiciosa de PR#95, priorizando **seguridad, ablation y compatibilidad** sobre cobertura.

## Que es

Descompone internamente el pipeline monolitico de relaciones
(`relations/pipeline.py`) en un flujo por **etapas desactivables** sobre tres
abstracciones puras, SIN cambiar el contrato publico de 20 campos de
`RelationCandidate` y SIN regresion por defecto.

- Modulo nuevo: `data-engine/app/relations/hybrid/`
  - `models.py` — `SegmentReference`, `RelationHypothesis`, `EvidenceBundle` (dataclasses puras).
  - `stages.py` — 7 etapas como funciones puras componibles.
  - `engine.py` — orquestador con flags + inyeccion de dependencias del pipeline.
- Flag maestro en `PipelineConfig`: `hybrid_stages: Optional[dict] = None`
  (`None` = pipeline clasico; `{}` = motor activo con todas las etapas en su
  default, que reproduce la base). Ademas `hybrid_top_k` y `hybrid_cross_sentence`.

## Garantia de compatibilidad (dura)

- `hybrid_stages=None` (default): **camino clasico intacto**, salida byte-identica
  a la base (`result_hash` identico). Las claves hibridas se OMITEN de la config
  canonica en su valor por defecto, asi que el hash de una run base no cambia.
- `hybrid_stages={}` (motor por etapas, todo en default): **contenido de
  candidatos identico** a la base (results/documents/summary iguales, verificado
  en tests y sobre el corpus B1). Solo difiere el bloque de config y por tanto el
  `execution_id`/`result_hash`, porque `hybrid_stages={}` es una eleccion explicita.

## Prohibiciones respetadas

Sin bajar thresholds, sin cambiar review policy, sin red por defecto, sin
escritura Neo4j, sin dependencia obligatoria nueva (parser fuerte SOLO opcional;
fallback stdlib por defecto), sin romper el contrato de 20 campos.

## Documentos

- [design.md](design.md) — arquitectura por etapas y decisiones.
- [test-plan.md](test-plan.md) — que se prueba y como falla de verdad.
- [results.md](results.md) — tabla de ablation REAL sobre corpus B1 + recuentos de suites.
- [security.md](security.md) — modelo de seguridad y la etapa sensible.
- [limitations.md](limitations.md) — etapas reales vs diseño, rollback, veredicto.

## Artefactos

`data-engine/app/artifacts/pr95-variants/v4/` — `ablation.json`, `ablation_table.md`.
