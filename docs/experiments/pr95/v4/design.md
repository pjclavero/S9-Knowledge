# PR#95 V4 — Diseño (arquitectura por etapas)

SHA base: `92583f4`.

## Hipotesis

Separar el pipeline monolitico de relaciones en etapas desactivables e
independientes permite: (a) **medir** la contribucion de cada etapa (ablation),
(b) **endurecer** la etapa sensible (temporal/epistemica) sin tocar el resto, y
(c) evolucionar sin **romper** a los consumidores del contrato de 20 campos.
Todo ello debe ser posible SIN regresion cuando los flags estan en su default.

## Abstracciones puras (`relations/hybrid/models.py`)

Tres dataclasses inmutables, INTERNAS (no forman parte del contrato publico):

- **`SegmentReference`** — referencia REDACTADA a segmento: procedencia + offsets +
  `text_len` (longitud, no el texto en claro). No filtra contenido.
- **`RelationHypothesis`** — hipotesis estructural: par + predicado + direccion +
  `score` (senal ordinal en [0,1]) + `reasoning` (el "por que"). NUNCA contiene la
  cita literal.
- **`EvidenceBundle`** — evidencia LITERAL (`evidence_text` verbatim) + offsets +
  `verified`/`covers_*` + `reasoning`. **El razonamiento va SEPARADO de la cita
  literal**: quien audite la evidencia recibe solo el span, no la explicacion.

## Flujo por etapas (`relations/hybrid/stages.py`)

Cada etapa es una funcion PURA (sin red, sin estado compartido) y **desactivable
por flag**; el default de cada flag reproduce EXACTAMENTE la base.

| # | Etapa | Flag | Default | OFF (ablation) |
|---|-------|------|---------|----------------|
| 1 | Ranking de menciones / top-k | `hybrid_top_k` | 0 = sin acotar (base) | `>0` acota candidatos por segmento |
| 2 | Hipotesis estructural | `structural_hypothesis` | True | score neutro (solo afecta al ranking) |
| 3 | Predicado / direccion | `predicate_direction` | True | predicado generico `RELATED_TO`, `UNDIRECTED` |
| 4 | Evidencia (span literal) | `evidence` | True | span degradado (solo sujeto) |
| 5 | Verificacion | `verification` | True | acepta sin verificar cobertura |
| 6 | Temporal / epistemica | `temporal_epistemic` | True | `temporal=None`, `epistemic=ASSERTED` |
| 7 | Consenso | `consensus` | True | registro sin consenso (`None`) |

La etapa inter-frase se gobierna con `hybrid_cross_sentence` (False = intra-frase
base; True = emparejamiento a nivel de segmento).

## Orquestador (`relations/hybrid/engine.py`)

- `resolve_stages(dict)` — normaliza flags a booleanos con defaults base; **fail-closed**
  ante nombres desconocidos o valores no-bool.
- `StageDeps` — **inyeccion** de las piezas de la base (`_choose_predicate`,
  `_confidence`, `_temporal_scope`, `_epistemic_status`, `compute_all_signals`,
  proveedores en sombra, consenso, `RelationCandidate`, `_candidate_key`, ...). Asi
  se **reutiliza** el codigo existente sin reimplantarlo y SIN import circular
  (`engine.py` NO importa `pipeline.py`).
- `build_candidate_records_staged(...)` — sustituye SOLO el bucle interno
  `for pair in pairs: _process_pair(...)` cuando el modo hibrido esta activo.

## Enhebrado en el pipeline (`relations/pipeline.py`)

- `PipelineConfig` gana `hybrid_stages`, `hybrid_top_k`, `hybrid_cross_sentence`.
  `to_dict()` OMITE estas claves en su valor por defecto (config canonica base
  intacta -> hash base intacto).
- `run_pipeline` valida la config hibrida temprano (fail-closed).
- `_process_segment` bifurca: `hybrid_stages is None` -> camino clasico literal;
  en otro caso -> motor por etapas. El top-k acota **candidatos**, nunca las
  senales ni los pares (la salida de senales del segmento no cambia).

## Adaptador de compatibilidad

`build_candidate_records_staged` con todas las etapas en default construye un
`RelationCandidate` **campo a campo identico** al de `_build_candidate` (mismo
predicado, direccion, confianza, span, negacion, temporal, epistemico,
`validation_flags=["dry_run","heuristic"]`) y ensambla el mismo registro
(candidate/consensus/local/external). El contrato de 20 campos no se toca.

## Parser fuerte opcional / fallback stdlib

El analisis sintactico sigue usando el proveedor `heuristic` (stdlib) por
defecto (`get_analyzer("heuristic")`). No se añade dependencia de spaCy/stanza; si
no estan, el pipeline funciona igual. El diseño deja la puerta abierta a inyectar
un parser fuerte como proveedor de sintaxis, pero **nunca como requisito**.
