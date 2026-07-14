# Verificación Ollama — Prioridad 2 Benchmark

**Fecha:** 2026-07-14
**Ejecutado desde:** ia-server (192.168.1.157)
**Endpoint:** http://192.168.1.157:11434

## Modelo

| Campo | Valor |
|-------|-------|
| Modelo | qwen2.5:7b |
| Versión Ollama | 0.31.1 |
| Parámetros | 7.6B |
| Cuantización | Q4_K_M |
| Contexto (num_ctx) | 32768 tokens |
| Temperatura (settings.yaml) | 0 |
| Temperatura (llm_extractor.py) | 0.1 (override local) |
| Semilla soportada | sí |
| Parámetros modelfile | ninguno configurado (defaults de Ollama) |

## Conectividad

| Medición | Valor |
|----------|-------|
| Endpoint accesible | ✅ |
| Modelo cargado | ✅ |
| Duración run-1 (warm) | 33 856 ms |
| Duración run-2 (warm) | 29 699 ms |
| Duración run-3 (warm) | 30 407 ms |

Nota: las 3 runs se ejecutaron con el modelo ya cargado en memoria (warm). El cold start previamente medido es ~63 segundos.

## Reproducibilidad (temperatura=0)

| Run | Duración (ms) | Tokens prompt | Tokens eval | Respuesta idéntica |
|-----|--------------|---------------|-------------|-------------------|
| 1 | 33 856 | 124 | 183 | — |
| 2 | 29 699 | 124 | 183 | sí vs run-1 |
| 3 | 30 407 | 124 | 183 | sí vs run-1 |

**Varianza:** nula (respuestas bit-a-bit idénticas con temperatura=0)

**Semilla disponible:** sí (parámetro `seed` aceptado por la API; verificado con seed=42)

**Respuesta de referencia (run-1):**
```json
{"entities": [{"name": "Kakita Asuka", "type": "Character", "evidence": "Kakita Asuka llegó al Bosque del Norte."}, {"name": "Bosque del Norte", "type": "Location", "evidence": "Kakita Asuka llegó al Bosque del Norte."}, {"name": "Bayushi Hisao", "type": "Character", "evidence": "Bayushi Hisao la siguió."}, {"name": "Oni de las Sombras", "type": "Creature", "evidence": "El Oni de las Sombras los atacó cerca del Río Plateado."}, {"name": "Río Plateado", "type": "Location", "evidence": "El Oni de las Sombras los atacó cerca del Río Plateado."}]}
```

## Configuración en el código

| Campo | Valor |
|-------|-------|
| URL (settings.yaml) | http://192.168.1.157:11434 |
| URL (hardcoded llm_extractor.py) | http://192.168.1.157:11434/api/generate |
| Timeout (settings.yaml) | 900 s (request_timeout global) |
| Timeout (llm_extractor.py) | 120 s por segmento (OLLAMA_TIMEOUT, tiene precedencia) |
| Temperatura (settings.yaml) | 0 |
| Temperatura (llm_extractor.py) | 0.1 (override en `_call_ollama`, tiene precedencia) |
| Fallback en fallo | sí — degrada a lista vacía `[]` con warning; nunca crashea |

**Discrepancia detectada:** `llm_extractor.py` hardcodea `temperature=0.1` en lugar de 0, contradiciendo `settings.yaml`. Para el benchmark, esto significa que las runs LLM reales no son totalmente deterministas (temperatura no es 0).

## Estimación de tiempo para benchmark

Basado en tiempos medidos (warm ~30 s/segmento, cold ~63 s):

| Escenario | Tiempo estimado |
|-----------|----------------|
| 1 fuente en modo LLM (cold start) | ~63 s + tiempo inferencia |
| 1 fuente en modo LLM (warm, 1 segmento típico) | ~30-34 s |
| 1 fuente en modo hybrid (warm) | ~30-34 s (same LLM path) |
| 5 fuentes × 1 run LLM (warm, ~1-3 segmentos/fuente) | ~2.5-8.5 minutos |
| 5 fuentes × 3 runs LLM (warm) | ~7.5-25 minutos |
| 5 fuentes × 3 runs LLM + hybrid (warm) | ~15-50 minutos |

Nota: el tiempo real depende del número de segmentos con `should_extract=True` por fuente. Fuentes cortas (notas, fichas) producen 1-2 segmentos; transcripciones largas pueden producir 5-10 segmentos.

## Conclusión

- **Estado:** OPERATIVO
- **Reproducibilidad:** Alta con temperatura=0. Sin embargo, `llm_extractor.py` usa temperatura=0.1 (hardcoded), lo que introduce variabilidad real en el pipeline. Para el benchmark se recomienda parchar temporalmente a temperatura=0 o documentar esta discrepancia como variable en los resultados.
- **Seed:** Soportado — útil para forzar reproducibilidad completa si se añade al payload de `_call_ollama`.
- **Recomendación prioritaria:** Alinear la temperatura entre `settings.yaml` (0) y `llm_extractor.py` (0.1) antes de ejecutar el benchmark de reproducibilidad para obtener resultados comparables entre runs.
