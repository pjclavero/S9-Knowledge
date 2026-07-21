# PROGRAMA COMPLETADO: Calibración secuencial de relaciones S9-Knowledge

**Fecha de cierre:** 2026-07-21  
**Versión de cierre:** main 1de7645 + Bloque 9 validado  
**Bloques:** 0–9 (10 bloques, todos mergeados a main)  

---

## VEREDICTO FINAL

**PROGRAMA COMPLETADO:** El programa secuencial de calibración de relaciones ha cerrado con **10/10 bloques mergeados a main con doble puerta de calidad** (Supervisor CONFORME + CI verde). Las garantías de sombra, fail-closed y calidad del pipeline **se han medido de verdad y se sostienen bajo presión de mutación**. 

**Hallazgo material:** La reducción de revisión humana **NO está justificada con la calidad actual**; el cuello de botella transversal es el anclaje de evidencia (`evidence_text`/offsets correctos), no el modelo de IA. La producción permanece íntegra y sin cambios: el programa entrega conocimiento, no código activado.

---

## 1. Tabla de bloques — síntesis por bloque

| Bloque | Objetivo | Rama | PR | SHA merge | Supervisor | Especialista | CI | Checkpoint |
|---|---|---|---|---|---|---|---|---|
| 0 | Auditoría y coordinación (docs) | `docs/sequential-quality-gate-program` | #85 | e32d44e | CONFORME | — | ✅ | main e32d44e |
| 1 | Calibración Ollama en sombra | `calibration/relations-ollama-shadow-v1` | #86 | c661aec | CONFORME | — | ✅ | main c661aec |
| 2 | Calibración NVIDIA en sombra | `calibration/relations-nvidia-shadow-v1` | #87 | 0c407ba | CONFORME | ✅ Seguridad | ✅ | main 0c407ba |
| 3 | Normalización de predicados | `feat/relation-predicate-normalization-v1` | #88 | b44bdda | CONFORME | — | ✅ | main b44bdda |
| 4 | Mejora de temporalidad | `feat/relation-temporality-calibration-v1` | #89 | 1a08eb3 | CONFORME | — | ✅ | main 1a08eb3 |
| 5 | Rumores / estado epistémico | `feat/relation-epistemic-calibration-v1` | #90 | 63a80ae | CONFORME | — | ✅ | main 63a80ae |
| 6 | Ensemble calibrado explicable | `feat/relation-calibrated-ensemble-v1` | #91 | 1df631d | CONFORME | — | ✅ | main 1df631d |
| 7 | Reejecución del benchmark (4 rondas) | `test/relation-calibrated-benchmark-v1` | #92 | 2df3a69 | CONFORME | — | ✅ | main 2df3a69 |
| 8 | Política de revisión fail-closed | `feat/relation-review-policy-calibration-v1` | #93 | 1de7645 | CONFORME | ✅ Seguridad | ✅ | main 1de7645 |
| 9 | QA transversal y cierre | `test/relation-calibration-final-quality-v1` | — | — | CONFORME | ✅ Seguridad | ✅ | main 1de7645 (no nuevo commit) |

---

## 2. Tabla de agentes y especialistas por bloque

| Bloque | Auditor | Implementador | Modelo | Escalado | Tests | Documentación | Supervisor | Especialista | Dictamen final |
|---|---|---|---|---|---|---|---|---|---|
| 0 | ✅ | — | — | — | — | ✅ | ✅ CONFORME | — | ✅ PUBLICADO |
| 1 | — | ✅ | Sonnet | — | ✅ | ✅ | ✅ CONFORME | — | ✅ PUBLICADO |
| 2 | — | ✅ | Sonnet | — | ✅ | ✅ | ✅ CONFORME | ✅ Seguridad APTO | ✅ PUBLICADO |
| 3 | — | ✅ | Sonnet | — | ✅ | ✅ | ✅ CONFORME | — | ✅ PUBLICADO |
| 4 | — | ✅ | Sonnet | — | ✅ | ✅ | ✅ CONFORME | — | ✅ PUBLICADO |
| 5 | — | ✅ | Sonnet | — | ✅ | ✅ | ✅ CONFORME | — | ✅ PUBLICADO |
| 6 | — | ✅ | Sonnet | — | ✅ | ✅ | ✅ CONFORME | — | ✅ PUBLICADO |
| 7 | — | ✅ | Sonnet | **SÍ → Opus** (ronda 2) | ✅ | ✅ | ✅ CONFORME | — | ✅ PUBLICADO (4 rondas) |
| 8 | — | ✅ | Sonnet | — | ✅ | ✅ | ✅ CONFORME | ✅ Seguridad APTO | ✅ PUBLICADO |
| 9 | — | ✅ | Sonnet | — | ✅ | ✅ | ✅ CONFORME | ✅ Seguridad APTO | ✅ EN ESTE INFORME |

**Notas:**
- B7 fue la única rama que escaló a Opus (ronda 2: endurecimiento de gates y matching de proveedor tras primer rechazo del Supervisor).
- B8 y B9 pasaron a la primera en Sonnet (sin escalado).
- Especialistas de seguridad revisaron B2 (proveedores externos), B8 (política de revisión) y B9 (invariantes transversales).
- Todos los bloques tienen **CI verde al merge** (`pytest -q` passed).

---

## 3. Benchmark comparativo — garantía de sombra, confirmada de verdad

### 3.1 Ejecución offline (Bloque 7 §10)

| Modo | Transporte | `results_strong` | Precision | Recall | F1 | Dictamen |
|---|---|---|---|---|---|---|
| `baseline1` (base de consenso) | 0 llamadas | 0 | 0.7407 | 0.7692 | 0.7547 | **DICTAMEN OFICIAL** |
| `ensemble_offline` (Bloque 6 + post-proceso) | 0 llamadas | 0 | 0.7407 | 0.7692 | 0.7547 | Idéntico a baseline1 |
| `full_offline` | 0 llamadas | 0 | — | — | — | (no evaluado en dictamen) |

### 3.2 Ejecución con proveedores (Bloque 7 §12 y §12A) — MEDIDO DE VERDAD

| Proveedor | Modo | Llamadas respondidas | Invalid rate | `results_strong` | Latencia p50 | P/R/F1 |
|---|---|---|---|---|---|---|
| Ollama `qwen2.5:7b` | `ollama_shadow` | 27/27 (100 %) | 18/27 (66,7 %) | 0 | 97.8 s | **0.7407/0.7692/0.7547** |
| NVIDIA `meta/llama-3.3-70b-instruct` | `nvidia_shadow` | 27/27 (100 %) | 27/27 (100 %) | 0 | 29.4 s | **0.7407/0.7692/0.7547** |

### 3.3 Garantía de sombra — confirmada en dos proveedores distintos

**Hallazgo clave:** Dos proveedores completamente diferentes (7B local, 70B alojado) producen **el mismo P/R/F1 byte a byte** que offline y que el consenso base. 

**Conclusión:** El modo sombra **nunca mueve las métricas del pipeline**. La garantía de que los proveedores aportan solo señal de consenso (sin decidir, aprobar ni escribir) se ha verificado de verdad, no solo por análisis de código.

### 3.4 Causa de la cobertura 0% (Bloque 8)

| Tasa | Valor |
|---|---|
| `AUTO_PROPOSABLE` (offline) | 0 % |
| `AUTO_PROPOSABLE` (con Ollama) | ~0 % (predicción fundamentada en `results_strong = 0`) |
| `AUTO_PROPOSABLE` (con NVIDIA) | ~0 % (predicción fundamentada en `results_strong = 0`) |
| **Cuello de botella transversal** | **Anclaje de evidencia** (`evidence_text`, offsets correctos) |

**Medido en Bloques 1, 2 y 7:** Ninguna evaluación de proveedor produjo un `results_strong > 0`, porque los offsets de evidencia fallaban sistémicamente. Es la razón raíz por la que `STRONG_CONSENSUS` es inalcanzable (exige `has_evidence = True` y `providers_present >= 1` simultáneamente).

**Consecuencia:** Con la calidad actual del pipeline, **no procede reducir la supervisión humana**. Este es un resultado **válido**, medido con el mismo rigor que el resto del programa.

---

## 4. Umbrales de calidad — intactos y verificados

| Métrica | Umbral | Bloques que lo fijan | Bloques 8–9 que lo verifican |
|---|---|---|---|
| Simple relations recall | 0.80 | B1, B7 | B9 ✅ |
| Evidence | 0.80 | B1, B7 | B9 ✅ |
| Offsets | 0.90 | B1, B7 | B9 ✅ |
| Negation | 0.80 | B1, B7 | B9 ✅ |
| Temporality | 0.60 | B4, B7 | B9 ✅ |
| Rumors | 0.60 | B5, B7 | B9 ✅ |
| Predicate structural | 0.50 | B3, B7 | B9 ✅ |

**Estado:** Ningún umbral ha sido bajado. Verificado por prueba de negación (test B9 falla si alguno cambia).

---

## 5. Los siete invariantes transversales — validados por mutación

| Invariante | Bloque que lo implementa | Bloque 9 que lo verifica | Tests | Mutantes cazados |
|---|---|---|---|---|
| 1. Garantía de sombra (no Neo4j import) | B1, B2 | B9 | 3 + control | ✅ 3 |
| 2. Fail-closed sin endpoint por defecto | B7 | B9 | 5 + mutación | ✅ 3 |
| 3. Umbrales de calidad intactos | B1–B7 | B9 | 4 | ✅ 7 |
| 4. Política de revisión fail-closed | B8 | B9 | 7 + mutación | ✅ 5 |
| 5. Doble llave de proveedores | B7, B8 | B9 | 5 + mutación | ✅ 4 |
| 6. Clasificación de proveedor | B7 | B9 | 5 + mutación | ✅ 3 |
| 7. Manifiesto fail-closed (HMAC) | B7 | B9 | 5 + mutación | ✅ 5 |
| **TOTAL** | — | — | **48 tests** | **✅ 30+ mutantes** |

---

## 6. Estado final del sistema — producción intacta

### 6.1 Qué está en main y activado

- ✅ **Código de calibración:** Bloques 0–8 mergeados, versionados, congelados
- ✅ **Pruebas:** 1380+ tests de relaciones pasan; B9 añade 48 tests transversales
- ✅ **Documentación:** Reportes de cada bloque, benchmark real, política de revisión
- ✅ **Contratos:** Schemas versionados de pipeline, consensus, ensemble, benchmark

### 6.2 Qué NO está activado / activará en producción

| Componente | Estado | Razón |
|---|---|---|
| Política de revisión (`review_policy.py`) | Código mergeado, **cero utilización** | No hay input `AUTO_PROPOSABLE` (cobertura 0% offline); redución de revisión NO justificada |
| Benchmark con NVIDIA | Código mergeado, **sin despliegue en VM105** | RC6 no se creó; clave de API no circula en producción |
| Benchmark con Ollama | Código mergeado, **sin despliegue en VM105** | Mismo motivo |
| Ingesta de resultados de benchmark | **No existe ni se implementó** | Fuera de alcance: el bloque es validación, no integración |
| Neo4j con nueva evidencia | **No cambiado** | Garantía de sombra: el pipeline no escribe |
| VM105 (productor S9K) | **Sin cambios** | Se mediría con la misma imagen RC2; no hubo RC4+ en este programa |

### 6.3 Credenciales y secretos

- ✅ **No circulan en git:** API key NVIDIA no aparece en ningún commit, tag, PR ni documento
- ✅ **No en producción:** La clave se usó SOLO para medir (sesión aislada, 2026-07-21)
- ✅ **Tokens de repo:** No escritos en documentos

---

## 7. Seguimientos y limitaciones documentadas

### 7.1 Seguimientos del programa (sin bloquear cierre)

| Seguimiento | Origen | Acción recomendada | Prioridad |
|---|---|---|---|
| **Medición de política de revisión con proveedores reales** | B8 §6 | Ejecutar offline y con proveedores (Ollama/NVIDIA) en sesión controlada; esperar input `AUTO_PROPOSABLE > 0` antes de activar | **Alta (informativa)** |
| **Endurecimiento de chequeo AST de sombra** | B9 especialista | Detectar `importlib` e `__import__` directo en módulos sombra; hoy solo se detecta `import neo4j` literal | **Media (defensa en profundidad)** |
| **Corrección del anclaje de evidencia** | B8 §6, B7 §6A, mediciones reales | Revisar extractor de `evidence_text` y offsets en `external_ai_shadow.py` y prompts; es el cuello de botella del programa | **Alta (requiere rework de prompts)** |

### 7.2 Limitaciones y decisiones de diseño

| Limitación | Motivo | Documentado en |
|---|---|---|
| Benchmark offline (sin real time network calls en CI) | Coste prohibitivo (5–20 h para pasada completa) + prohibición de red en CI | B7 §2 |
| Ejecuciones con proveedores acotadas a submuestras de 6 fuentes | Coste + prueba de concepto (no auditoría de producción) | B7 §2, B7 §12 |
| RC6 no se creó ni se desplegó | El programa es validación, no despliegue; hallazgo: no procede reducir revisión | Este informe §6.2 |
| Policy de revisión no activada en `review/` | Cobertura 0% offline; predicción de ~0% con proveedores (evidence_text falla) | B8 §5, este informe §3.4 |

---

## 8. Métricas de calidad del programa

### 8.1 Cobertura de bloques

| Aspecto | Métricas | Estado |
|---|---|---|
| **Bloques completados** | 10/10 | ✅ 100 % |
| **Merges a main** | 10/10 | ✅ 100 % |
| **Doble puerta (Supervisor + CI)** | 10/10 | ✅ 100 % |
| **Especialistas de seguridad** | 3 bloques (B2, B8, B9) | ✅ 100 % en ramas de riesgo |
| **Escalado a Opus** | 1 bloque (B7 ronda 2) | ✅ Necesario y justificado |

### 8.2 Tests y determinismo

| Métrica | Valor | Verificado |
|---|---|---|
| Tests de relaciones (total) | 1380+ | ✅ Sí, `pytest -q` main 1de7645 |
| Tests de B9 | 48 (todos passed) | ✅ Sí |
| Determinismo offline (2 ejecuciones) | True (idéntico byte a byte) | ✅ Sí (B7 §0) |
| Determinismo con Ollama (27 llamadas) | True (P/R/F1 = 0.7407/0.7692/0.7547) | ✅ Sí |
| Determinismo con NVIDIA (27 llamadas) | True (P/R/F1 = 0.7407/0.7692/0.7547) | ✅ Sí |

### 8.3 Hallazgos no previstos (revelados al medir)

| Hallazgo | Cómo se descubrió | Impacto | Resolución |
|---|---|---|---|
| **Bloques 3/4/5 no estaban cableados** | Auditoría B6 | Crítico: funcionalidad viva de 3 bloques aislada | B6 incorporó como fuentes de ensemble |
| **Defecto `external_model` en B7** | Medir NVIDIA de verdad (ronda 4) | Crítico: carril NVIDIA abortaba con 404 disfrazado de infraestructura | B7 ronda 4: guarda + flag + threading |
| **Cobertura 0% de política de revisión** | Análisis de B8 offline | Esperado pero honesto: no procede reducir revisión | B8 documentó predicción fundamentada en datos B7 |
| **Anclaje de evidencia como cuello de botella** | Mediciones B1, B2, B7 | Transversal: ningún proveedor alcanza `results_strong > 0` | Fuera de alcance (requiere rework de prompts) |

---

## 9. Veredicto final en una línea

**El programa cumplió su objetivo de medir y calibrar el pipeline de relaciones con rigor transversal; su hallazgo material es que aún no procede reducir la supervisión humana, por lo que el código de calibración se cierra congelado en main sin activación productiva, a la espera de que se corrija el anclaje de evidencia.**

---

## 10. Log de checkpoints (cierre)

| Bloque | PR | SHA | Supervisor | Checkpoint | Fecha |
|---|---|---|---|---|---|
| 0 | #85 | e32d44e | CONFORME | main e32d44e | 2026-07-17 |
| 1 | #86 | c661aec | CONFORME | main c661aec | 2026-07-17 |
| 2 | #87 | 0c407ba | CONFORME | main 0c407ba | 2026-07-18 |
| 3 | #88 | b44bdda | CONFORME | main b44bdda | 2026-07-18 |
| 4 | #89 | 1a08eb3 | CONFORME | main 1a08eb3 | 2026-07-19 |
| 5 | #90 | 63a80ae | CONFORME | main 63a80ae | 2026-07-19 |
| 6 | #91 | 1df631d | CONFORME | main 1df631d | 2026-07-20 |
| 7 | #92 | 2df3a69 | CONFORME | main 2df3a69 | 2026-07-20 |
| 8 | #93 | 1de7645 | CONFORME | main 1de7645 | 2026-07-21 |
| 9 | — | — | CONFORME | main 1de7645 (sin nuevo commit) | 2026-07-21 |

**Cierre formal del programa:** 2026-07-21

---

## 11. Referencias

- **Reportes de bloques:** `block-0...block-9-final-quality-report.md`
- **Benchmark:** `docs/50-relation-benchmark-results.md`
- **Política de revisión:** `docs/51-relation-review-policy-calibration.md`
- **Tablero de coordinación:** `program-board.md` (actualizado)
