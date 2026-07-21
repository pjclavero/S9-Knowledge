# PR#95 V4 — Seguridad

SHA base: `92583f4`.

## Invariantes preservados de la base

- **DRY-RUN estructural**: sin modo write/apply/persist, sin drivers Neo4j, sin
  autoaprobacion. El motor hibrido NO añade ninguna via de escritura; reutiliza el
  mismo constructor de candidato y el mismo consenso.
- **Sin red por defecto**: proveedores en sombra deshabilitados; el motor hibrido
  llama a los MISMOS `_run_local`/`_run_external` inyectados, que fallan cerrado
  sin transporte. Ninguna etapa abre un socket.
- **Fail-closed de configuracion**: `resolve_stages` rechaza etapas desconocidas y
  valores no-bool; `run_pipeline` valida la config hibrida ANTES de procesar. Los
  flags de escritura prohibidos (`write`/`apply`/...) siguen abortando.
- **Sin dependencia obligatoria nueva**: parser fuerte SOLO opcional; fallback a
  analizador heuristico stdlib. `spacy`/`stanza` no se importan.
- **Contrato de 20 campos intacto**; abstracciones nuevas son internas.
- **Redaccion**: `SegmentReference` guarda `text_len`, no el texto en claro.
- **Razonamiento separado de la evidencia**: la cita literal (`evidence_text`)
  nunca se mezcla con el "por que" (`reasoning`). Un auditor de la cita no recibe
  explicaciones inyectadas en el texto de evidencia.

## La etapa sensible: temporal/epistemica (etapa 6)

La garantia dura de la base es **"un rumor NUNCA se convierte en hecho"**
(`_epistemic_status`, `RelationCandidate.is_affirmative`). En V4 esa logica vive
en la etapa 6, **activada por defecto**, que delega en las funciones canonicas.

- Con la etapa ON (default): RUMORED/HYPOTHETICAL/INTENDED se conservan; ASSERTED
  solo sin cue no-asertivo. Reproduce la base.
- Con la etapa OFF (**regresion de seguridad detectable**): `epistemic=ASSERTED`
  para todo. En el corpus B1 esto baja `epistemic_correct` 0.8605 -> 0.8140, y en
  el test unitario un rumor explicito ("Se dice que ...") pasa de RUMORED a
  ASSERTED. Por eso la etapa 6 se documenta como **sensible**: desactivarla es
  degradar la seguridad, no solo la calidad, y el test
  `test_ablation_temporal_epistemic_off_is_security_regression` lo fija como
  comportamiento observado, no como recomendacion.

## Anti-gaming

Dos invariantes mutados y confirmados por fallo de test, revertidos sin residuo:
(1) el acotado top-k, (2) la compatibilidad por defecto. Sin `skip`/`xfail`, sin
bajar umbrales. Detalle en `test-plan.md`.

## Superficie de riesgo introducida

- Nuevo codigo en `relations/hybrid/` ejecutado SOLO cuando `hybrid_stages` no es
  `None`. Con el default (`None`), el camino es el clasico literal: **cero cambio
  de comportamiento y cero superficie nueva**.
- La activacion del motor hibrido es una eleccion explicita de configuracion; no
  hay activacion implicita ni por entorno.
