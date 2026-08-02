# Notas de rendimiento — validación final V3

**Informativo. Ninguna cifra de este documento condiciona ningún gate.** Se
registra porque un número medido hoy es la única defensa contra una estimación
inventada mañana.

## Entorno de medida

Todas las cifras se tomaron en `yggdrasil`, en el worktree
`.claude/worktrees/integration`, el 2026-07-30, **con la máquina muy cargada**:
tres agentes ejecutando suites de pytest en paralelo más los carriles de
proveedor. `load average` observado entre **9,0 y 11,5** durante toda la
campaña.

Esto no es una anécdota: el carril Ollama es CPU-bound y sus latencias de esta
tabla están infladas por la contención. Se dejan tal cual —medidas reales en
condiciones reales— en vez de repetirlas en una máquina ociosa para que salgan
más bonitas.

## Proveedores: verificación de que están vivos

Llamada mínima (`{"ok": true}`, 64 tokens), a través de los puertos reales de
`knowledge_v3/extraction/provider_port.py`:

| Proveedor | Puerto | Modelo devuelto | Latencia | JSON válido |
|---|---|---|---|---|
| Ollama local | `OllamaProviderPort` | `qwen2.5:7b` | 87 844 ms (**arranque en frío**) | sí |
| Ollama local | `OllamaProviderPort` | `qwen2.5:7b` | 2 354 / 2 032 / 2 527 ms (**en caliente**) | sí |
| NVIDIA NIM | `NvidiaProviderPort` | `meta/llama-3.3-70b-instruct` | 6 213 ms | sí |

Lectura honesta de estas cifras:

- **Los 88 s de Ollama son carga del modelo**, no inferencia. Una vez residente
  (`/api/ps` lo confirma), el mismo prompt baja a ~2,3 s. Cualquier medida que
  incluya la primera llamada de la sesión está midiendo el arranque.
- **NVIDIA es estable en ~6 s** y, al ser remoto, apenas le afecta la carga
  local de la máquina.
- El prompt real de extracción NO es este prompt mínimo: lleva la ontología
  completa más el episodio. El coste de *prefill* de ese prompt sobre un 7B en
  CPU cargada domina la latencia por episodio y es la razón de que el carril
  Ollama se muestreara en vez de recorrer las 100 frases.

## Coste real de los carriles de extracción semántica

Éstas son las cifras que importan, y son **mucho** peores que las del prompt
mínimo: el prompt de extracción lleva la ontología completa más el episodio, y
el extractor hace **dos llamadas por episodio** (extracción + segunda pasada
temporal).

| Carril | Frases | Llamadas | Latencia mediana / frase | Pared total | Errores |
|---|---|---|---|---|---|
| `nvidia` (`meta/llama-3.3-70b-instruct`) | 24 | 48 | **50 107 ms** (min 1 336 / max 180 296) | **1 372 s** (22,9 min) | 0 |
| `ollama` (`qwen2.5:7b`, CPU) | 4 | 8 | > 5 min/frase (no completó en 15 min la primera vez) | ver abajo | — |

Dos lecturas honestas:

1. **El salto de 6 s a 50 s en NVIDIA no es del proveedor, es del prompt.** La
   misma API respondía en 6,2 s a un prompt de dos líneas. Cualquier
   planificación de ingesta que use los 6 s como referencia se equivocará por un
   factor de 8.
2. **Ollama con el prompt real es inviable a este tamaño en esta máquina.** Un
   primer intento de 3 frases fue **abortado por su propio timeout de 15 min**
   sin escribir nada. Por eso el carril se redujo a 4 frases y se relanzó cuando
   la carga bajó.

### Fallo de diseño del propio utillaje (anotado para no repetirlo)

`gate6_factivity_runner.py` escribe el JSON **sólo al final**. Cuando el primer
intento de Ollama agotó su timeout, se perdió el trabajo de 15 minutos y no
quedó ni una fila. Un runner de medidas caras debe volcar resultados
incrementalmente. No se ha cambiado ahora para no alterar el utillaje a mitad de
campaña, pero es lo primero que hay que corregir antes de la siguiente.

## Coste por etapa

| Etapa | Coste observado | Nota |
|---|---|---|
| Suite completa `data-engine/app` (base) | 93–97 s | 4 610 → 5 029 → … según fase |
| Suite completa `viewer` | ~30 s | 418 passed, 1 skipped |
| Sonda de reproducibilidad del planner (4 semillas, 4 subprocesos) | ~3 s | subprocesos, no hilos |
| Carril `policy` (100 frases, sin red) | < 1 s | `cues.analyze_raw_text` |
| Carril `det` (100 frases) | < 5 s | sin red |

## Decisión de muestreo y por qué

El corpus de factividad tiene 100 frases. Recorrerlo entero por los dos
carriles de proveedor, con la máquina en este estado, no cabía en la ventana de
la campaña. En vez de recortar el corpus o de fingir una cobertura que no hubo:

- `policy` y `det` se ejecutan sobre **las 100** frases;
- los carriles de proveedor se ejecutan sobre una **muestra estratificada por
  familia** (un caso de cada familia antes de repetir ninguna), de forma que
  ninguna familia se quede sin representar;
- el gate de acuerdo entre carriles se calcula **sobre la intersección**, que es
  el único conjunto donde la comparación es legítima.

El tamaño real de la muestra y el número de llamadas efectivas quedan escritos
en `gate5-authority.json` y `gate6-factivity-matrix.json`. Si un carril no
llegó a ejecutarse, su gate se reporta **BLOQUEADO**, nunca CONFORME.

## RAM

`max_rss` del proceso de medida se registra en `gate5-authority.json`
(`max_rss_mb`). El modelo de Ollama reside en el servidor de Ollama, no en el
proceso de medida: su huella (≈5,06 GB para `qwen2.5:7b`, según `/api/ps`) no
aparece en esa cifra y se anota aquí para que nadie la busque donde no está.
