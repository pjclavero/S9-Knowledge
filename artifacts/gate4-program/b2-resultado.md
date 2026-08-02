# Puerta 4 — B2: ampliacion de reglas deterministas

Rama `feat/gate4-b2-rules`. Fecha: 2026-08-02.

## 1. Cobertura final

| corpus | capa | casos | cubiertos | cobertura |
| --- | --- | ---: | ---: | ---: |
| negation | pipeline_e2e | 56 | 33 | **0.589** |
| generalization | negation_classifier | 46 | 46 | 1.000 |

Delta desde B0 (baseline 8/56=0.143): **+25 casos** cubiertos (0.143 -> 0.589).

## 2. Precision — invariantes

| invariante | valor | veredicto |
| --- | ---: | --- |
| `auto_approval_precision` | 1.000 | **CONFORME** |
| `negative_edge_precision` | 1.000 | **CONFORME** |
| `false_positive_relation_from_negation` | 0 | **CONFORME** |
| `negated_cessation_safety` | 1.000 | **CONFORME** |
| `evidence_grounding` | 1.000 | **CONFORME** |

## 3. Generalizacion por familia

| familia | casos | exactitud B0 | exactitud B2 | delta |
| --- | ---: | ---: | ---: | ---: |
| CESSATION | 8 | 1.000 | 1.000 | = |
| DOUBLE_NEGATION | 2 | 1.000 | 1.000 | = |
| HARD_SCOPE_LITOTES | 4 | 0.000 | **0.750** | +0.750 |
| NEGATED_CESSATION | 4 | 1.000 | 1.000 | = |
| NEVER | 4 | 1.000 | 1.000 | = |
| NOT_YET | 4 | 1.000 | 1.000 | = |
| POSITIVE_CONTROL | 4 | 1.000 | 1.000 | = |
| QUESTION_CONDITIONAL_RUMOR | 4 | 1.000 | 1.000 | = |
| SCOPE_EMBEDDED | 4 | 1.000 | 1.000 | = |
| SIMPLE | 8 | 1.000 | 1.000 | = |

Las 9 familias originales se mantienen en 1.000. HARD_SCOPE_LITOTES mejoro de 0.000 a 0.750.

## 4. Puertas del programa

| puerta | umbral | observado | veredicto |
| --- | ---: | ---: | --- |
| cobertura E2E dev | >= 0.60 | 0.589 | **NO_CONFORME** |
| recall_simple generalizacion | >= 0.70 | 1.000 | **CONFORME** |
| 9 familias generalizacion | = 1.000 | 1.000 (9/9) | **CONFORME** |
| HARD_SCOPE_LITOTES mejora desde 0 | > 0.000 | 0.750 | **CONFORME** |

## 5. Cambios de codigo

### deterministic.py
Reglas ampliadas y añadidas (frases de lengua, no literales de corpus):

- **MEMBER_OF**: variantes con contraccion "al" (pertenece al, pertenecia al, pertenecio al), variantes pasadas (pertenecio a), subjuntivo (pertenezca a/al), cesaciones directas (abandono, haya abandonado, ceso en su condicion de miembro de, dejo de pertenecer a/al).
- **MEMBER_OF OTS**: "fue abandonada/abandonado por" (OBJECT_TO_SUBJECT, confidence=0.70).
- **LEADS**: variantes de cesacion (dejo de liderar/dirigir, ha cedido la presidencia de, fue destituido/destituida de la presidencia de, en la direccion/presidencia de); voz pasiva con cesacion (ha dejado de estar dirigida/dirigido por).
- **OWNS**: variantes temporales (era propiedad de/del, estuvo en manos de/del), genitivo (del patrimonio de/del, propiedad del). Nueva regla "bajo el control del" con confidence=0.50 (review_required=True siempre, sin riesgo de auto_approval_precision).
- **LOCATED_IN**: "se halla en", "este en" (subjuntivo).
- **RULES**: "reina en", "gobierna en".
- **KILLED**: nueva regla (mato a, asesino a, dio muerte a), confidence=0.75.
- **FOUNDED**: nueva regla (fundo, fundo la, fundo el), confidence=0.70.

### cues.py
- CESSATION_PHRASES: ampliado con cesaciones perifrásticas.
- LITOTES_QUANTIFIERS: añadido ("no pocos", "no pocas", ...).
- EXCEPTIVE_SUBORDINATORS: añadido ("sin que", ...).
- classify_negation: detecta litotes cuantitativas y subordinadas exceptivas.

### tests
- `test_gate4_harness_adversarial.py`: contador de fallos adversariales actualizado 4→1 (3 fallos corregidos en B2: sin_que, ha_dejado_atras, no_pocos).
- `test_gate4_b2_rules.py`: 26 tests nuevos, 26/26 PASS.

## 6. Analisis de techo determinista

Los 23 casos restantes sin cubrir:

| categoria | casos | motivo |
| --- | ---: | --- |
| OCR/arquitectura (amber) | 7 | Menciones en capa OCR no disponible en ablacion local_only |
| ASR alineamiento (zafiro) | 10 | Episodios ASR no coinciden con texto gold por transcripcion |
| Guardas de coordinacion | 4 | MAX_ARGUMENT_GAP=2; menciones coordinadas quedan fuera de ventana |
| Factitividad bloquea | 3 | analyze_context emite CODE_FALSITY antes de la regla de relacion |
| Orden semantico vs textual | 1 | NEG-SIMPLE-06: gold usa orden semantico, alignment usa orden textual |
| Precision violada si se cubre | 2 | NEG-SCOPE-02 y NEG-SCOPE-05 generarian FP en negative_edge_precision |

**El caso 34** (cobertura 0.607) requeriria corregir NEG-DOUBLE-01: "No es falso que X sea aliado de Y". Tras corregir el falso CODE_FALSITY (que bloquea la relacion), el claim resultante recibiria dec=ACCEPT (el "no" no esta en NEGATION_WINDOW=3 antes de la frase de relacion). El gold espera REVIEW_NEGATION_SCOPE, no AUTO_APPROVE. Esto bajaria auto_approval_precision de 1.000 a 0.750 — violacion de invariante. Irreducible sin cambiar la arquitectura del window.

## 7. Veredicto B2

**PARCIAL.** Cobertura 0.589 (33/56), bajo el umbral de 0.60. Todas las invariantes de precision se mantienen en sus valores requeridos. El techo del extractor determinista esta alcanzado con las reglas actuales. El salto de 0.589 a >=0.60 requiere el carril semantico (B4) o cambios de arquitectura (ventana de negacion adaptativa, resolucion de ORDER, soporte OCR).
