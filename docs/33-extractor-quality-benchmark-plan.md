# 33 · Plan de evaluación de calidad del extractor — Prioridad 2

**Fecha de redacción:** 2026-07-14  
**Prerequisitos:** Prioridad 1 completada (backup, restore, rollback)  
**Objetivo:** Definir criterios cuantitativos y reproducibles para aceptar el extractor en producción

---

## Contexto

El pipeline ya implementa tres modalidades de extracción:

| Modalidad | Descripción | Estado |
|-----------|-------------|--------|
| Heurístico | Reglas deterministas, stopwords, glosario | Implementado — falsos positivos conocidos |
| LLM | qwen2.5:7b vía Ollama (192.168.1.157:11434) | Implementado — calidad no evaluada |
| Híbrido | LLM + validación heurística | Implementado — calidad no evaluada |

El bloqueo actual no es la ausencia de LLM sino la ausencia de métricas sobre un corpus representativo. No se puede autorizar ingesta real sin saber qué porcentaje de candidatos autoaprobados son correctos.

---

## 1. Corpus de evaluación

### 1.1. Tipos de fuente a incluir

| Tipo | Prioridad | Motivo |
|------|-----------|--------|
| Transcripción de sesión RPG (audio/vídeo) | Alta | Fuente principal real del proyecto |
| PDF (manual, libro de campaña) | Alta | Segunda fuente más común |
| Notas de sesión (texto plano) | Media | Fuente frecuente, formato variable |
| Transcripción con errores ASR | Media | Caso real conocido — faster-whisper small |
| Notas en español con código-switching | Media | Específico de L5A |

### 1.2. Tamaño mínimo del corpus

- Mínimo 5 fuentes distintas
- Mínimo 3 tipos de fuente representados
- Mínimo 100 candidatos totales anotados (entidades + relaciones)
- Al menos un caso con entidades compartidas entre fuentes (para probar resolución)

### 1.3. Verdad esperada (ground truth)

Para cada fuente, anotar manualmente:

- Entidades correctas: nombre + tipo de nodo + workspace
- Relaciones correctas: origen → tipo → destino + evidencia mínima
- Entidades que **no** deben aparecer (falsos positivos esperados del modo heurístico)
- Relaciones que **no** deben aparecer

El ground truth debe almacenarse en `tests/fixtures/benchmark/` como JSON siguiendo el mismo esquema que `approved_payload`.

---

## 2. Métricas objetivo

### 2.1. Por modalidad y tipo de fuente

| Métrica | Definición | Umbral mínimo para producción |
|---------|------------|-------------------------------|
| Precisión entidades | TP / (TP + FP) | ≥ 0.85 |
| Recall entidades | TP / (TP + FN) | ≥ 0.70 |
| F1 entidades | 2 × P × R / (P + R) | ≥ 0.75 |
| Precisión relaciones | TP / (TP + FP) | ≥ 0.75 |
| Recall relaciones | TP / (TP + FN) | ≥ 0.60 |
| Tasa de duplicados | Entidades duplicadas / total candidatos | ≤ 0.10 |
| Tasa de relaciones inválidas | Relaciones semánticamente inválidas / total | ≤ 0.05 |

### 2.2. Métricas adicionales

- **Coste por fuente:** tiempo de ejecución × coste inferencia LLM (si aplica)
- **Reproducibilidad:** varianza entre dos ejecuciones sobre la misma fuente (LLM volátil)
- **Trazabilidad:** porcentaje de candidatos con evidencia de texto citada

---

## 3. Criterios de decisión por candidato

### 3.1. Autoaprobado automático

Un candidato puede autoaprobarse si:

- Confianza calculada ≥ umbral configurable (actualmente `decision_threshold`)
- No tiene conflicto semántico detectado
- No es duplicado de un nodo existente (o la resolución es unívoca)
- El tipo de nodo está en el esquema RPG v1.5.0
- La evidencia de texto es suficiente (longitud mínima, no vacía)

### 3.2. Envío a revisión humana

Un candidato va a revisión si:

- Confianza < umbral de autoaprobado
- Es potencial duplicado con similitud ambigua (delta < 0.10)
- El nombre tiene < 3 caracteres o es un término genérico en la stoplist
- El tipo de relación es semánticamente inusual para los tipos de los nodos involucrados
- El extractor LLM y el heurístico producen resultados contradictorios en modo híbrido

### 3.3. Rechazo automático

Un candidato se rechaza si:

- El nombre está en la stoplist global o de workspace
- El tipo de nodo no existe en el esquema
- La confianza es < umbral mínimo absoluto
- La relación conecta tipos de nodo incompatibles (e.g., HAS_FOUGHT con destino Location → degradar a FOUGHT_AT)

---

## 4. Comparativa de modalidades

### 4.1. Procedimiento

Para cada fuente del corpus, ejecutar el pipeline en los tres modos:

```bash
# Heurístico
python data_review.py --source <fuente> --mode heuristic --dry-run

# LLM
python data_review.py --source <fuente> --mode llm --dry-run

# Híbrido
python data_review.py --source <fuente> --mode hybrid --dry-run
```

Comparar el `approved_payload` resultante contra el ground truth.

### 4.2. Tabla de resultados esperada

| Fuente | Modo | Precisión | Recall | F1 | FP | FN | Duración | Coste |
|--------|------|-----------|--------|----|----|-----|----------|-------|
| fuente-1 | heurístico | | | | | | | |
| fuente-1 | llm | | | | | | | |
| fuente-1 | híbrido | | | | | | | |
| ... | | | | | | | | |

### 4.3. Decisión por tipo de fuente

Tras la comparativa, documentar qué modo se recomienda para cada tipo de fuente en `docs/20-data-review-and-approved-ingest.md`.

---

## 5. Reproducibilidad del LLM

El modo LLM puede ser volátil entre ejecuciones (qwen2.5:7b). Medir:

- Ejecutar la misma fuente 3 veces en modo LLM
- Calcular varianza de precisión, recall y número de candidatos
- Si la varianza es > 0.10 en F1: documentarlo y considerar temperatura = 0 o semilla fija

---

## 6. Casos de regresión

Definir un conjunto mínimo de casos que deben pasar siempre:

1. `Llevás` NO debe aparecer como Character en ningún modo
2. `Todo` NO debe aparecer como Character
3. `Como` NO debe aparecer como Character
4. Un personaje con nombre conocido del glosario debe aparecer con el nombre normalizado
5. Una relación HAS_FOUGHT con destino Location debe rechazarse o degradarse a FOUGHT_AT

Estos casos deben convertirse en tests de regresión en `data-engine/app/tests/`.

---

## 7. Condiciones para habilitar la primera ingesta real

La ingesta real en Neo4j puede habilitarse cuando se cumplan **todas**:

1. Al menos 2 modalidades alcanzan F1 ≥ 0.75 en entidades sobre el corpus completo
2. La tasa de duplicados es ≤ 0.10
3. La tasa de relaciones inválidas es ≤ 0.05
4. Los 5 casos de regresión pasan en el modo seleccionado
5. El backup de producción está al día (< 7 días)
6. Se ha acordado una ventana de rollback y se ha documentado el source_id de la fuente
7. Revisión humana del `review_queue` completada antes de ejecutar

---

## 8. Estimación de esfuerzo

| Tarea | Responsable | Estimación |
|-------|-------------|------------|
| Seleccionar y anotar corpus (5 fuentes, 100 candidatos) | Humano | 2-4 horas |
| Ejecutar pipeline en 3 modos × 5 fuentes | Agente | 1-2 horas |
| Calcular métricas y generar tabla comparativa | Agente | 1 hora |
| Revisar resultados y definir modo recomendado por fuente | Humano | 1 hora |
| Implementar casos de regresión como tests | Agente | 1 hora |
| Documentar criterios de producción | Agente | 30 min |

**Total estimado:** 6-9 horas (incluyendo revisión humana)

---

## 9. Documentos relacionados

- [docs/02-current-state.md](02-current-state.md) — estado actual del extractor
- [docs/05-data-engine.md](05-data-engine.md) — arquitectura del motor de datos
- [docs/20-data-review-and-approved-ingest.md](20-data-review-and-approved-ingest.md) — pipeline de revisión
- [docs/27-controlled-ingest-runbook.md](27-controlled-ingest-runbook.md) — runbook de ingesta controlada
- [docs/28-graph-migrations-and-rollback.md](28-graph-migrations-and-rollback.md) — rollback por source_id

---

## Siguiente acción

1. Seleccionar las 5 fuentes del corpus (responsabilidad humana — requiere acceso a Nextcloud)
2. Anotar el ground truth (1-2 horas de trabajo humano)
3. Lanzar la comparativa de modalidades (automatizable con agente)
