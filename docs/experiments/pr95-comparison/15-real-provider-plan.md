# 15 — Plan de corrida con proveedor REAL (NVIDIA) — GATEADO, NO EJECUTADO

Objetivo unico y medible:
> **¿Cuantos rechazos del evaluador externo desaparecen SOLO por corregir P0?**
> Reproducir el NVIDIA 27/27 previo y aislar el efecto del contrato DOCUMENTO/ID.

Esta fase esta **gateada a autorizacion humana explicita**. Aqui queda el plan
exacto y el driver listo (`harness/real_provider_plan.sh`), **sin ejecutarse**.
No red, no proveedores, no ingesta en esta auditoria.

## Parametros fijos (una sola vara, solo cambia el commit)

| parametro | valor |
|---|---|
| Modelo | `meta/llama-3.3-70b-instruct` |
| (retirado) | `meta/llama-3.1-70b-instruct` del EnvironmentFile **NO usar** (retirado por el proveedor) |
| Corpus | el MISMO C1 (`data-engine/app/tests/data/relation_benchmark`) o submuestra fija (misma semilla) |
| Prompt / suite | identica en todas las corridas (`prompt_suite` fijo) |
| Temperatura | identica y fija en las 4 corridas (p. ej. 0.0 determinista) |
| Reintentos / timeout | identicos (misma politica de `max_retries` y timeout por llamada) |
| Doble llave | `--enable-providers` **y** `S9K_BENCH_PROVIDERS=1` (ambas obligatorias) |
| API key | `S9K_NVIDIA_API_KEY` desde `/home/ia02/.config/s9k/nvidia.env`, **sourceada en el subproceso**, nunca impresa |
| Logs | redactados (sin key, sin texto crudo del documento; solo spans+longitud) |

## Matriz de corridas (aislar P0, luego +V2 y +V3)

Todo igual salvo el commit / flag:

1. **PRE-FIX** — commit `dcded31` (antes de P0): mide rechazos con el contrato roto.
2. **BASE (P0)** — commit `92583f4` (P0 aplicado): mide rechazos con el contrato
   corregido. **Delta (1)->(2) = rechazos que desaparecen SOLO por P0.** <- respuesta.
3. **+V2** — `92583f4` con `realignment_enabled=True`: efecto incremental del
   realineamiento (vigilar false_realign REAL, no el del banco).
4. **+V3** — `92583f4` con `fragment_protocol_enabled=True`: efecto incremental de
   fragmentos (vigilar recall y coste de prompt reales).

Comparaciones que produce:
- **P0 aislado:** (2) − (1) sobre el mismo corpus/modelo/prompt.
- **V2 vs V3 reales:** (3) vs (4) sobre (2) como base -> resuelve la parte
  PROVISIONAL del veredicto del protocolo (doc 16).

## Protocolo de ejecucion (cuando se autorice)

1. Congelar corpus y hash (ya existe `ground-truth-hash.txt`); registrar
   `run-manifest` con commit, modelo, temperatura, semilla, timeout, reintentos.
2. Usar **worktrees desechables** en cada commit (`dcded31`, `92583f4`) para no tocar
   ramas; +V2/+V3 via flag sobre `92583f4`.
3. 3 repeticiones por corrida para determinismo/estabilidad; reportar p50/p95 de
   latencia de **llamadas respondidas**.
4. Re-verificar la puerta §18 con el modelo real (inyeccion, literalidad, fail-closed).
5. Redactar todos los artefactos; **nunca** volcar la key ni el documento crudo.

## Driver

`harness/real_provider_plan.sh` deja el comando exacto parametrizado y **aborta con
mensaje** si no estan las dos llaves o la key; **no** llama al proveedor por si solo
(requiere descomentar la linea de ejecucion tras autorizacion). El script:

- Sourcea la key en el subproceso: `set +x; . /home/ia02/.config/s9k/nvidia.env; set -x`
  (con `set +x` alrededor para no ecoar la key).
- Exige `S9K_BENCH_PROVIDERS=1` y pasa `--enable-providers` + `--external-model
  meta/llama-3.3-70b-instruct`.
- Redirige a logs redactados.

## Salida esperada del experimento

- `p0-isolation.json`: rechazos PRE-FIX vs BASE, delta absoluto y % -> **"N rechazos
  desaparecen solo por P0"**.
- `provider-v2-v3.json`: recall/aceptacion/false_realign/literal REALES de V2 y V3.
- Actualizacion del veredicto del protocolo (doc 16) de PROVISIONAL a FIRME.

> Nada de lo anterior se ha ejecutado. La corrida consume cuota real de NVIDIA y toca
> red: requiere autorizacion humana previa (doble llave + revision de este plan).
