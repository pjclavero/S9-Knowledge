# Dosier de análisis externo — Motor de relaciones S9-Knowledge

**Propósito:** entregar a un revisor externo, de forma autocontenida, **el problema, los
datos de prueba y dónde está cada evidencia**, para que pueda analizarlo y **buscar
alternativas**. No propone una solución cerrada: mapea el estado real y señala los frentes
abiertos.

**Estado honesto de una frase:** el trabajo reciente (programa PR#95) mejoró —de forma
*potencial, aún sin fusionar*— la **capa de corroboración externa** (que la IA externa vea
el texto real y su cita se acepte). **El motor de extracción PROPIO no ha mejorado en las
pruebas**: los dos intentos que lo tocaron salieron **negativo (V1)** y **neutro (V4)**. El
limitante de fondo para poder ingerir —el **predicado** y la **estructura semántica**—
sigue **sin abordarse**.

> Repo: `pjclavero/S9-Knowledge`. Todo lo de este dosier es OFFLINE/dry-run/modo sombra:
> nada escribe en Neo4j, nada se ha desplegado, la ingesta real sigue bloqueada.

---

## 1. El problema, en dos capas

El pipeline propone relaciones `(sujeto, predicado, objeto)` con evidencia textual, en
modo sombra. Fallaba en dos sitios independientes:

### Capa A — Corroboración externa (IA externa en sombra)
- **P0 (bug de contrato, CORREGIDO en la base experimental):** el evaluador externo recibía
  el **ID del segmento** como "documento" en vez del **texto real** → rechazaba toda la
  evidencia. Corregido pasando `document_text` real.
- **Offsets del modelo (ABIERTO):** aun con el texto real, el LLM devuelve la cita bien pero
  con **offsets mal contados**. Es lo que atacan V2 (recomputar offsets) y V3 (protocolo por
  fragmentos, sin offsets). Medición real en curso (§6).

### Capa B — Motor de extracción PROPIO (heurístico) — el limitante real
Independiente de la IA externa. Es lo que decide si algún día se puede **ingerir sin
revisión humana total**. Sus métricas en el benchmark (§3) muestran que **el cuello no es
la evidencia** (IoU 0.907) **sino el PREDICADO (0.256), la DIRECCIÓN (0.628), la
TEMPORALIDAD (0.442) y la DECISIÓN (0.302)**. Ninguna de las 4 versiones del programa mejoró
esto. Este es el frente donde buscar alternativas.

---

## 2. Qué se probó y qué salió (resumen)

| Cambio | Capa | Resultado en pruebas (honesto) | ¿Mejora el motor propio? |
|---|---|---|---|
| **P0** contrato documento/ID | A | Necesario; el modelo ya ve el texto real | No (es la capa externa) |
| **V1** anclaje conservador | B | **Negativo**: evidence 0.907→0.837 (0 mejoras, 3 regresiones) | **No, empeora** |
| **V2** realineamiento determinista | A | Sintético: aceptación 0.185→0.796, pero **false_realign 0.182** | No (capa externa) |
| **V3** selección por fragmentos | A | Sintético: aceptación 0.185→**0.963**, inmune a inyección | No (capa externa) |
| **V4** híbrido por etapas | B | **Neutro**: default == base; cross_sentence sube recall pero F1 0.525 | No, ±0 |

**Conclusión:** mejora *potencial* solo en la **capa A** (externa), y solo **medida en banco
sintético** salvo la corrida NVIDIA real (§6). **La capa B (motor propio) = 0 de mejora.**

---

## 3. Datos de prueba (benchmark) y su evidencia

### Corpus B1 (congelado, versionado)
- Ruta: `data-engine/app/tests/data/relation_benchmark/`
- Tamaño: **16 fuentes, 54 relaciones de ground truth**; el pipeline genera **52 candidatos**.
- Hashes (integridad): `manifest.json` sha256 `a2cc506f…d2631`; `ground_truth/relations.json`
  sha256 `15973d18…cc5c`.
- **No se adaptó el corpus a ninguna versión** (regla de la evaluación).

### Métricas del MOTOR PROPIO — línea base (corpus C1 real, misma vara)
Fuente: `artifacts/pr95-unified-comparison/comparison-table.md` (rama `audit/pr95-unified-comparison-v1`).

| Métrica | base | V1 | V4_default | interpretación |
|---|---|---|---|---|
| pair_F1 | 0.811 | 0.811 | 0.811 | emparejamiento de pares: aceptable |
| pair_recall | 0.796 | 0.796 | 0.796 | — |
| **strict_F1** (todos los campos) | **0.208** | 0.208 | 0.208 | **muy bajo**: casi nada sale perfecto |
| evidence_correct (IoU≥.5) | 0.907 | 0.837↓ | 0.907 | evidencia por solape: buena |
| evidence_exact | 0.395 | 0.000 | 0.395 | exactitud literal de la evidencia: floja |
| offsets_overlap | 0.930 | 0.930 | 0.930 | (solape, NO exactitud) |
| boundary_mae | 7.29 | 9.50 | 7.29 | error medio de límites (chars) |
| **predicate_exact** | **0.256** | 0.256 | 0.256 | **el cuello de botella** |
| **direction_exact** | **0.628** | 0.628 | 0.628 | flojo |
| negation | 0.907 | 0.907 | 0.907 | bien |
| **temporal** | **0.442** | 0.442 | 0.442 | flojo |
| epistemic | 0.860 | 0.860 | 0.860 | bien |
| **decision** | **0.302** | 0.302 | 0.302 | **bajo** (deriva del predicado débil) |

**Dictamen del benchmark:** *"APTO CON REVISIÓN HUMANA TOTAL — evidencia/offsets fiables pero
el predicado heurístico es débil"* → **ingesta real bloqueada**. La expresión "APTO PARA
INGESTA" no existe en el vocabulario de dictamen (el motor es propositor en sombra).

> **Lectura para el análisis externo:** los targets de mejora del motor propio, por impacto,
> son **predicado (0.256)**, **decisión (0.302)**, **strict (0.208)**, **temporalidad
> (0.442)** y **dirección (0.628)**. La evidencia (IoU 0.907) NO es el problema del motor
> propio; su exactitud literal (0.395) sí es mejorable pero secundaria.

---

## 4. Ficheros implicados (dónde vive el motor)

Import root: `data-engine/app`. Paquete: `data-engine/app/relations/`.

| Fichero | Rol | Relevancia para mejorar el motor propio |
|---|---|---|
| `relations/pipeline.py` | Orquestador end-to-end (dry-run) | Alta: ensambla el candidato, elige predicado/dirección/confianza |
| `relations/pairs.py` | Generación determinista de pares candidatos | Media: recall de pares, ventana de contexto (interfrase) |
| `relations/signals.py` | Señales heurísticas (misma frase, SVO, distancia, tipos, negación, modalidad, rumor) | **Alta**: base del predicado y la dirección |
| `relations/syntax.py` | Analizador sintáctico heurístico (stdlib, sin parser fuerte) | **Alta**: estructura SVO → dirección/predicado |
| `relations/vocabulary.py` | Vocabulario canónico de predicados (alias, simetría) | **Alta**: normalización/mapeo de predicados |
| `relations/temporality.py` | Clasificación temporal (pasado/futuro/en curso/terminado) | Media: métrica temporal 0.442 |
| `relations/epistemic.py` | Estado epistémico (afirmado/rumor/hipótesis/intención) | Baja (0.860 ya bien) |
| `relations/consensus_adapter.py`, `ensemble.py` | Consenso/ensemble → estado canónico y decisión | Media: decisión 0.302 |
| `relations/contracts.py` | Contrato `RelationCandidate` (20 campos) | Baja (no cambiar sin adaptador) |
| `relations/external_ai_shadow.py` | Evaluador IA externa en sombra (capa A) | Alta para capa A (P0/V2/V3) |
| `relations/benchmark/{runner,matching,metrics,report}.py` | Arnés de medición (NO es el motor) | Alta para AUDITAR la medición; umbrales en `report.py` |

### Tests (dónde comprobar y no romper)
- `data-engine/app/tests/test_relation_*.py` (pares, señales, sintaxis, vocabulario,
  temporalidad, epistémico, pipeline, consenso, ensemble, benchmark…).
- Invariantes transversales de seguridad: `tests/test_relation_calibration_final_quality_block9.py`
  (48 tests: sombra, fail-closed, umbrales, doble llave, literalidad…). **No bajar umbrales.**

---

## 5. Documentación implicada

- `docs/41-relation-benchmark-plan.md` — plan y criterio de emparejamiento del benchmark.
- `docs/50-relation-benchmark-results.md` — resultados del benchmark (rama del programa).
- `docs/51-relation-pipeline-runtime.md` — runtime del pipeline.
- `docs/52-motor-extraccion-auditoria-externa.md` — auditoría previa del motor (PR #95, origen).
- `docs/experiments/pr95/{v1,v2,v3,v4}/{README,design,test-plan,results,security,limitations}.md`
  — diseño y resultados por versión (en sus ramas respectivas).
- `docs/experiments/pr95-comparison/00..16-*.md` — **comparación unificada** (problema,
  metodología, resultados por versión, head-to-head, combinaciones, estadística, seguridad,
  integración, plan proveedor real, veredicto). En rama `audit/pr95-unified-comparison-v1`.

---

## 6. Dónde está la evidencia (ramas, PRs, artefactos, SHAs)

`origin/main` = `dcded31` (intacto). Todo lo experimental vive en ramas draft (DO NOT MERGE):

| Contenido | Rama | PR | SHA cabeza |
|---|---|---|---|
| Base (fix P0) | `exp/pr95-compare-base-contract-v1` | #97 | `92583f4` |
| V1 anclaje conservador | `exp/pr95-v1-conservative-anchor` | #98 | `46998e0` |
| V2 realineamiento | `exp/pr95-v2-deterministic-realignment` | #99 | `b47497f` |
| V3 fragmentos | `exp/pr95-v3-fragment-selection` | #100 | `28ce8a1` |
| V4 híbrido | `exp/pr95-v4-hybrid-staged-engine` | #101 | `4ded509` |
| **Comparación unificada + evidencia** | `audit/pr95-unified-comparison-v1` | #102 | ver rama |

**Artefactos de evidencia** (en la rama `audit/pr95-unified-comparison-v1`,
`artifacts/pr95-unified-comparison/`):
- `comparison-table.md` — tabla homogénea (dos pistas, misma vara).
- `metrics.json` / `metrics.csv` — todas las métricas por config.
- `confidence-intervals.json` — bootstrap (incertidumbre; muestras pequeñas marcadas).
- `decision-matrix.json` — matriz de decisión ponderada.
- `corpus-manifest.yaml`, `ground-truth.jsonl`, `ground-truth-hash.txt`, `synthetic-bank.json`.
- `normalized-results/`, `raw-redacted-results/` — resultados por candidato (redactados).
- `harness/` — scripts reproducibles (`run_comparison.py`, `build_bank.py`,
  `run_combinations.py`, `confidence_intervals.py`, `decision_matrix.py`,
  `real_provider_plan.sh`).
- `real-provider/` — corridas NVIDIA reales (payloads crudos + json redactado).

---

## 7. Corrida real NVIDIA (efecto aislado de P0 y de V2/V3)

Modelo `meta/llama-3.3-70b-instruct` (el `3.1` del EnvironmentFile está retirado). Doble
llave, key sourceada sin imprimir, logs redactados, sin escritura.

**Submuestra mínima (n=4, `src-09`+`src-13`), BASE post-P0:** NVIDIA respondió 4/4, 0
errores de transporte; **0/4 aceptados**, todos por `offsets_invalidos` (antes de P0 era
`evidencia_inexistente`). → **P0 elimina el primer muro pero destapa el de los offsets.**
Evidencia: `real-provider/base_p0_payloads.jsonl`, doc `15b-real-provider-min-result.md`.

**Datos fiables (corpus completo, mismos 52 candidatos, NVIDIA real `meta/llama-3.3-70b-instruct`):**

| Config | Verdictos VÁLIDOS | Rechazos | Motivo del rechazo |
|---|---|---|---|
| **BASE** (solo P0) | **0/52** | 52 | `offsets_invalidos` (50 no casan, 2 fuera de rango) |
| **V2** realineamiento | **52/52** | 0 | — |
| **V3** fragmentos | **49/52** | 3 | 2 fragmentos vacíos del modelo, 1 timeout transporte |

Artefactos: `real-provider/{base_classic_real,v2_full_real,v3_full_real}.jsonl`.

**Conclusión firme (ya con datos reales, no sintéticos):**
- **P0 es necesario pero NO suficiente:** solo con P0, NVIDIA da **0/52** (el 100% cae por
  `offsets_invalidos`). El modelo ve el texto real pero **cuenta mal los offsets**.
- **P0 + V2 o V3 desatasca la capa externa:** de 0/52 a **52/52 (V2)** / **49/52 (V3)**.

**Matiz de seguridad (crítico):** "válido" = cita **literal con offsets coherentes**, NO que
la evidencia sea la **correcta**. El banco sintético mostró que V2 ancla en el **span
equivocado ~18%** de las veces (literal pero erróneo) — riesgo que este recuento NO detecta.
V3 no tiene ese riesgo (reconstruye desde los fragmentos que el modelo eligió). Por tanto:
**aceptación bruta V2 (100%) ≥ V3 (94%); seguridad de la evidencia aceptada V3 ≥ V2.** La
elección V2/V3 es un trade-off, no "gana el número más alto". Falta un experimento que
compare la evidencia ACEPTADA contra el ground truth (cuántas son la cita correcta).

> **Y no olvidar la Capa B:** aunque V2/V3 arreglen la corroboración externa, el **motor
> propio sigue con el predicado débil (0.256)** → el dictamen sigue siendo "revisión humana
> total" y la **ingesta sigue bloqueada**. La capa externa desatascada no basta por sí sola.

---

## 8. Frentes abiertos para el análisis externo (alternativas a explorar)

Ninguno abordado por el programa PR#95. Se listan como **preguntas**, no como solución:

1. **Predicado (0.256) — el de mayor impacto.** ¿Mejora un clasificador de predicado
   (reglas + léxico de `vocabulary.py`/`signals.py`, o un modelo ligero) frente al mapeo
   heurístico actual? ¿Cuánta de la pérdida es normalización de alias vs elección de familia?
2. **Dirección (0.628).** Depende de la estructura SVO de `syntax.py` (parser heurístico
   stdlib). ¿Un parser fuerte OPCIONAL (spaCy/stanza) tras el mismo interfaz sube dirección
   y predicado sin romper el fallback stdlib? (V4 dejó el enganche, sin explotar.)
3. **Decisión (0.302).** Deriva del predicado débil; ¿mejora al calibrar el consenso o al
   separar "predicado incierto" de "relación incierta"?
4. **Temporalidad (0.442).** ¿Cobertura léxica/estructural insuficiente en `temporality.py`?
5. **Evidencia exacta (0.395 vs IoU 0.907).** El anclaje mecánico (span entre menciones)
   solapa pero no acierta el borde. V1 (cláusula) lo empeoró; ¿un objetivo distinto (recorte
   al predicado/verbo, o aprender el borde del GT) lo mejora? Caracterizar el GT primero.
6. **Interfrase (recall).** V4 `cross_sentence` sube recall a 0.963 pero hunde precisión;
   ¿un filtro de precisión (top-k, tipos) recupera F1?

**Cómo medirlo (reproducible, offline):**
```bash
cd data-engine/app
python3 -m pytest tests/ -k relation -q            # suite del motor
# tabla homogénea y métricas: rama audit/pr95-unified-comparison-v1
python3 artifacts/pr95-unified-comparison/harness/run_comparison.py
```

---

## 9. Garantías y restricciones (contexto para el analista)
- Offline/dry-run/modo sombra; sin red por defecto; sin escritura en Neo4j; ingesta bloqueada.
- Umbrales del benchmark **intactos** (`report.py` sin cambios); corpus **congelado con hash**;
  mediciones verificadas por mutación y por revisores independientes (no amañadas a la prueba).
- `main` y las ramas del programa **no se fusionan**; el motor productivo es el mismo de antes.
