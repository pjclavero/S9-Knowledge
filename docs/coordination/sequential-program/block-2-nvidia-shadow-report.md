# Informe de validación — Bloque 2: NVIDIA NIM real en modo sombra

**Fecha:** 2026-07-19
**Probe:** `nvidia-shadow-probe-1.0.0` (`relations.calibration.nvidia_shadow_probe`)
**Evaluador bajo prueba:** `relations.external_ai_shadow.evaluate_relation_external`
**Endpoint:** `https://<host>/v1` (NVIDIA NIM alojado; base URL vía `S9K_NVIDIA_BASE_URL`)
**Modelo:** `meta/llama-3.1-70b-instruct`
**Corpus:** 3 candidatos **sintéticos** (relaciones ya propuestas por el pipeline, que el modelo debe *juzgar*) · repeticiones: 2
**Artefacto crudo:** [`artifacts/block-2-nvidia-probe.json`](artifacts/block-2-nvidia-probe.json)

## 1. Desbloqueo de la dependencia externa

La primera y segunda clave devolvían **403 Forbidden** en inferencia (`GET /v1/models` = 200,
pero `POST /chat/completions` = 403 en todos los modelos): la cuenta carecía de *entitlement* de
inferencia. Con una clave de cuenta con inferencia activa, `POST /chat/completions` pasó a **200**
y la validación real pudo ejecutarse. La API key nunca se imprimió ni se commiteó (se gestiona en
un EnvironmentFile privado `0600` y se lee vía `external_ai.registry`).

## 2. Veredicto

La validación real **CONFIRMA** que el evaluador externo se mantiene en modo sombra contra
NVIDIA real y que su validación estricta rechaza salidas defectuosas del modelo.

- **Invariantes de sombra (globales):** `all_shadow = true`, `no_approvals = true` en **todas**
  las repeticiones de **todos** los casos. `AUTO_APPROVED` nunca apareció; toda salida exige
  intervención humana.
- **Secreto seguro:** el informe reporta `api_key_present = true` sin revelar la clave; el host
  del endpoint está ofuscado. No hay `nvapi-...` en el artefacto.
- **Repetibilidad:** 3/3 casos **deterministas** (`distinct_outputs = 1`) entre las 2 repeticiones.

## 3. Resultados por caso

| Caso | Estado | Recom. sombra | Determinista | Latencia p50 / máx (ms) | Hallazgo |
|---|---|---|---|---|---|
| `alliance_affirmative` | `INVALID_RESPONSES` | `human` | sí | 13 860 / 21 470 | `offsets_invalidos` |
| `alliance_negated` | `INVALID_RESPONSES` | `human` | sí | 43 299 / 75 874 | `offsets_invalidos` |
| `membership_affirmative` | `INVALID_RESPONSES` | `human` | sí | 34 629 / 54 330 | `offsets_invalidos` |

## 4. Hallazgo de calibración clave (insumo para bloques 3–6)

**El fallo de offsets es transversal a ambos proveedores.** Igual que `qwen2.5:7b` local
(Bloque 1), `meta/llama-3.1-70b-instruct` vía NVIDIA cita evidencia textual plausible pero
devuelve **offsets de carácter que no coinciden** con la evidencia citada
(`offsets_invalidos: segmento[start:end] no coincide con evidence_text`). El validador estricto
lo **rechaza cerrado** en los 3 casos → todo cae a revisión humana (`human`).

Implicaciones:
1. El cuello de botella actual **no** es el criterio del modelo (confirmar/negar), sino la
   **fidelidad de offsets**. Ni un modelo local de 7B ni uno alojado de 70B los producen bien.
2. Refuerza el diseño de los bloques siguientes: la **normalización/anclaje de evidencia** (y una
   posible tolerancia de offsets o recomputación del span a partir del `evidence_text` literal)
   es candidata prioritaria antes que el *ensemble*.
3. La seguridad se mantiene: al no validar, **nada** se propone como hecho; el sistema falla hacia
   revisión humana, nunca hacia una aprobación indebida.

## 5. Coste / latencia

p50 entre ~14 s y ~43 s por candidato (máx ~76 s), con variabilidad de red del servicio alojado.
Coste real por llamada (facturable) → el proveedor externo debe usarse como **señal en ensemble**
y con lotes acotados, no como camino único.

## 6. Garantías de seguridad verificadas

- **Sin escritura:** el probe y el evaluador no escriben en Neo4j ni producción. El único fichero
  escrito es el artefacto (`--out`), explícito.
- **Sin corpus privado:** solo datos sintéticos inventados.
- **Secreto seguro:** API key por entorno (registry), nunca almacenada/impresa/serializada;
  `S9K_EXTERNAL_AI_ALLOW_PRIVATE_CONTENT` permanece en `false`.
- **Aislamiento en CI:** unitarios con proveedor inyectado (sin red); el test live
  (`tests/wave2b/test_external_nvidia_live.py`) se **salta** salvo `S9K_NVIDIA_LIVE=1`.

## 7. Reproducción

```bash
set -a; . ~/.config/s9k/nvidia.env; set +a     # S9K_NVIDIA_ENABLED=true + API key (0600)
export PYTHONPATH="$PWD/data-engine/app"
python -m relations.calibration.nvidia_cli \
    --model meta/llama-3.1-70b-instruct --repetitions 2 --out informe.json
```

## 8. Estado de producción

Intacta. No se tocó VM105, Neo4j (199/140), `auth.db`, `jobs.db`, timers ni servicios.
`S9K_ALLOW_REAL_INGEST = off`. `release/rc6-candidate = 15ae1d4` (inmutable).
