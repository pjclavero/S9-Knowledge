# 18 — Mejora de transcripción L5A con glosario, normalización y corrección

Fecha: 2026-07-12
Rama: `feat/l5a-transcription-glossary`
VM105: 6 núcleos, 7.7 GB RAM

## Resumen ejecutivo

La transcripción de audio real de *La Leyenda de los Cinco Anillos* con faster-whisper
`small` es técnicamente funcional pero comete errores en nombres propios y términos de
dominio, lo que la hace poco fiable para ingesta directa al grafo. Se ha diseñado y
validado un pipeline de mejora con: (1) glosario automático en SQLite, (2) transcripción
asistida por `initial_prompt`/`hotwords`, (3) normalización determinista por `error_forms`,
y (4) corrección opcional con Ollama. **Conclusión: la vía fiable es `medium` + normalizador
determinista.** El `initial_prompt` sobre `small` degradó la salida y la corrección LLM de
bloque completo con qwen2.5:7b no preservó las marcas de tiempo (falló validación y se
descartó de forma segura). Nada se ha ingerido al grafo; `ready_for_ingestion=false` siempre.

## Fragmento de prueba

- Audio: `La Leyenda de los cinco Anillos - El Castillo Esmeralda (5⁄14)` (Nextcloud, `leyenda/videos/`)
- Offset: 00:02:00 · Duración: 3 min · WAV 16 kHz mono (5.5 MB)

## Benchmark de modelos (misma muestra de 3 min)

| Modelo | Tiempo | RAM pico | Segmentos | Errores L5A críticos |
|---|---|---|---|---|
| small  | 75 s  | 3.4 GB | 34 | 2 de 3 (67%) |
| medium | 148 s | 5.7 GB ⚠️ | 29 | 0 de 3 (0%) |

`medium` corrige el 100% de los nombres L5A críticos pero deja ~250 MB de RAM libre →
**nunca dos transcripciones `medium` simultáneas**.

### Errores L5A concretos (small)
- `Seijuro` → "Sei Yuro" (00:01:28 / 00:01:37 / 00:01:50)
- `Kitsugi Kaji` → "Kitsubikaji" (00:01:11)
- `medium` transcribe ambos correctamente.

## Glosario automático

Módulo `data-engine/app/glossary/` (SQLite `state/glossary.db`, workspace `leyenda`).

- Fuentes: semillas manuales L5A (17), entidades de Neo4j (199, solo lectura), términos de Markdown/docs (837).
- Total: 1044 términos. Búsqueda por exact / alias / error_form / fuzzy.
- `search "tosi rambo"` → `Toshi Ranbo` vía error_form (score 1.0).
- Exports para Whisper: `initial_prompt.txt`, `hotwords.txt`, `glossary.json` (250 términos).
- Discrepancia resuelta: el audio real dice **Seijuro** (no "Seiyuro"); "Seiyuro" queda como alias.

## Transcripción asistida por glosario (small + initial_prompt + hotwords)

Resultado **negativo**: con `small`, el `initial_prompt` colapsó la segmentación (9 segmentos)
y **perdió** el tramo central del audio (00:01:00–00:02:00 quedó casi vacío). No corrigió los
términos porque perdió el contenido que los contenía. **No recomendado con `small`.**

## Normalización determinista (recomendado)

Módulo `data-engine/app/glossary/transcript_normalizer.py`. Aplica `error_forms` del glosario
con límites de palabra (regex, no `str.replace` bruto), conserva timestamps y registra cada
sustitución. Umbrales: ≥0.95 auto_replace (solo error_forms exactos en esta fase).

Aplicado al baseline `small` real:

| Línea | Antes | Después | Confianza |
|---|---|---|---|
| 34 | Kitsubikaji | Kitsugi Kaji | 0.99 |
| 42 | Sei Yuro | Seijuro | 0.99 |
| 46 | Sei Yuro | Seijuro | 0.99 |
| 50 | Sei Yuro | Seijuro | 0.99 |

- **Timestamps: 34 → 34 (preservados).**
- Salidas: `*.normalized.md` + `*.review.json` (`ready_for_ingestion=false`).

Hallazgo: los `error_forms` semilla no coincidían con los errores reales del ASR
("Sei Yuro" vs "Se Yuro", "Kitsubikaji" vs "Kitsuji Kaji"). Se añadieron las formas
realmente observadas al glosario. Los `error_forms` deben alimentarse de errores reales.

## Corrección con Ollama (qwen2.5:7b) — opcional, falló validación

Módulo `data-engine/app/glossary/llm_corrector.py`. Corrige `normalized.md` con Ollama
(temperatura 0.1) y **valida** la salida. Resultado sobre esta muestra:

- timestamps: 34 → 17 ❌ (el modelo eliminó la mitad)
- length_ratio: 0.76 ❌ (acortó/resumió)
- sin meta-explicaciones ✅

Al fallar la validación, se marcó `llm_correction_failed` y se conservó `normalized.md`.
**La corrección LLM de bloque completo no es fiable para preservar timestamps.** Requiere
un enfoque por segmento (mantener el prefijo `[HH:MM:SS]` de forma programática) en fase futura.

## Recomendación de pipeline por defecto

1. Transcribir con **`medium`** (0% error en nombres L5A críticos) — una sola instancia a la vez.
2. Aplicar **normalizador determinista** (`error_forms` del glosario) — seguro, preserva timestamps.
3. Revisión humana antes de cualquier ingesta. `ready_for_ingestion` permanece `false`.
4. Corrección LLM: solo tras rediseñarla por segmentos con validación estricta.

## Limitaciones

- `medium` deja poca RAM (5.7/7.7 GB): no paralelizar transcripciones.
- `error_forms` requieren errores reales observados, no solo suposiciones.
- El glosario Markdown (837 términos) incluye ruido; conviene un ranking/filtrado más estricto.
- La corrección LLM directa rompe la estructura temporal.

## Siguiente fase

- Transcribir la muestra completa con `medium` + normalizador y revisar manualmente.
- Rediseñar `llm_corrector` por segmentos preservando timestamps.
- Depurar el glosario Markdown (reducir falsos términos).
- Solo entonces, diseñar la ingesta a Neo4j con metadatos de confianza y revisión humana.

## Confirmaciones de seguridad

- No se escribió en Neo4j (solo lectura). No se ejecutó ingesta al grafo.
- No se escribió en Nextcloud. No se borraron ni movieron audios.
- No se procesaron los 17 audios completos (solo fragmento de 3 min).
- No se tocó SilverBullet ni systemd. Ollama usado solo vía API normal.
- Outputs, `state/glossary.db` y WAV excluidos de git (.gitignore).
