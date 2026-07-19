# Informe de validación — Bloque 1: Ollama real en modo sombra

**Fecha:** 2026-07-19
**Probe:** `ollama-shadow-probe-1.0.0` (`relations.calibration.ollama_shadow_probe`)
**Evaluador bajo prueba:** `relations.local_llm_shadow.evaluate_relation_local`
**Endpoint:** `http://<host>/v1` (localhost, OpenAI-compatible; endpoint **explícito**, sin default)
**Modelo:** `qwen2.5:7b`
**Corpus:** 3 casos **sintéticos** (personajes/facciones inventados) · repeticiones: 2
**Artefacto crudo:** [`artifacts/block-1-ollama-probe.json`](artifacts/block-1-ollama-probe.json)

## 1. Veredicto

La validación real **CONFIRMA** que el evaluador local se mantiene en modo sombra contra
Ollama real y que su validación estricta rechaza salidas defectuosas del modelo.

- **Invariantes de sombra (globales):** `all_shadow = true`, `no_approvals = true` en **todas**
  las repeticiones de **todos** los casos. El evaluador nunca decidió, nunca aprobó, nunca
  escribió (ni Neo4j, ni ficheros, ni caché).
- **Endpoint explícito / fallo cerrado:** confirmado por test (`test_probe_fails_closed_without_endpoint`)
  y por diseño del evaluador (`ConfigError` sin abrir socket si falta endpoint).
- **Repetibilidad:** los 3 casos fueron **deterministas** (salida decisiva idéntica entre las
  2 repeticiones; `distinct_outputs = 1`).

## 2. Resultados por caso

| Caso | Estado | Recomendación | Validación | Determinista | Latencia p50 / máx (ms) | Hallazgo |
|---|---|---|---|---|---|---|
| `membership_affirmative` | `INVALID_RESPONSES` | `recommend_human_review` | INVALID | sí | 64 831 / 79 538 | `offsets_do_not_match_evidence` |
| `alliance_negated` | `HUMAN_REQUIRED` | `recommend_human_review` | VALID | sí | 10 677 / 19 651 | `no_relation_extracted` (no afirmó la negación como hecho) |
| `alliance_rumored` | `INVALID_RESPONSES` | `recommend_human_review` | INVALID | sí | 59 470 / 68 034 | `offsets_do_not_match_evidence` |

Hashes de entrada/prompt registrados por caso en el artefacto JSON (trazabilidad y repetibilidad).

## 3. Hallazgos de calibración (insumo para bloques 3–6)

1. **Fidelidad de offsets (débil):** `qwen2.5:7b` cita evidencia textual plausible pero devuelve
   offsets de carácter que **no coinciden** con la evidencia citada. El evaluador lo detecta
   (`offsets_do_not_match_evidence`) y **rechaza cerrado** — comportamiento seguro. Es la
   limitación dominante del modelo local en esta tarea.
2. **Negación (segura):** ante una relación explícitamente **negada**, el modelo no propuso una
   relación afirmativa; el evaluador la enrutó a revisión humana (`HUMAN_REQUIRED`), sin
   convertir la negación en hecho. Coherente con el objetivo del futuro Bloque 5.
3. **Rumor / estado epistémico:** el caso de rumor también cayó por offsets antes de poder
   evaluar el estado epistémico; la validación epistémica fina queda para el Bloque 5.
4. **Coste / latencia:** p50 entre ~10 s y ~65 s por evaluación en caliente (cold start previo
   ~140 s). El LLM local es **caro**; refuerza su uso como señal en *ensemble*, no como camino
   único.

## 4. Garantías de seguridad verificadas

- **Sin escritura:** el probe y el evaluador no escriben en Neo4j ni tocan producción. El único
  fichero escrito es el artefacto de calibración (`--out`), explícito.
- **Sin corpus privado:** solo datos sintéticos inventados.
- **Secretos redactados:** el informe/artefacto ofusca el host (`http://<host>/v1`); el evaluador
  local no usa API key (Ollama local) y el subsistema redacta cualquier secreto por diseño.
- **Aislamiento en CI:** los tests unitarios del probe usan transportes inyectados (sin red). El
  test live (`tests/wave2b/test_local_llm_ollama_live.py`) se **salta** salvo `S9K_OLLAMA_LIVE=1`
  con endpoint alcanzable, de modo que CI permanece verde y no depende de Ollama.

## 5. Reproducción

```bash
export PYTHONPATH="$PWD/data-engine/app"
python -m relations.calibration.cli \
    --endpoint http://localhost:11434/v1 \
    --model qwen2.5:7b \
    --repetitions 2 \
    --out informe.json
```

## 6. Estado de producción

Intacta. No se tocó VM105, Neo4j (199/140), `auth.db`, `jobs.db`, timers ni servicios.
`S9K_ALLOW_REAL_INGEST = off`. `release/rc6-candidate = 15ae1d4` (inmutable).
