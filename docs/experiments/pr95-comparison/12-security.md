# 12 — Seguridad (consolidacion y puerta dura §18)

Fuente: `artifacts/pr95-unified-comparison/security.json` (oleada 1) +
`combination-analysis.json` (oleada 2). Todo OFFLINE, proveedores no ejecutados
(`providers_offline: true`), banco pre-generado en memoria (mock puro, cero socket).

## Evidencia consolidada (todas las versiones y grupos)

| control | base | V1 | V2 | V3 | V4(*) | V2+V3 |
|---|---|---|---|---|---|---|
| network_attempts | 0 | 0 | 0 | 0 | 0 | 0 |
| write_attempts | 0 | 0 | 0 | 0 | 0 | 0 |
| secret_exposure | 0 | 0 | 0 | 0 | 0 | 0 |
| prompt_injection_success | 0 | — | 0 | 0 | — | 0 |
| unsafe_output_acceptance | 0 | — | 0 | 0 | — | 0 |
| literal_evidence_rate (aceptado) | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| determinism_rate | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| fail_closed ante invalido | si | si | si | si | si | si |

(*) V1/V4 son pista pipeline; injection/unsafe no aplican (no hay respuesta de modelo
externo que inyectar). Sus controles de red/escritura/secreto/literalidad/determinismo
son 0/1.0 en las 5 configuraciones.

Todas las versiones **fallan cerrado**: ante respuesta invalida, hostil o ambigua no
aceptada, el estado es `INVALID_RESPONSES`/`WORKER_ERROR` y no se emite verdicto.
La literalidad de lo **aceptado** es 1.0 en todas: ningun span aceptado difiere del
texto fuente (`doc[start:end] == evidence_text` y `evidence_text in doc`).

## Riesgo real de V2: false_realignment 0.182 — clasificacion

**Es un fallo de CALIDAD, no de seguridad.** Argumentos:

1. **No cruza ninguna puerta de seguridad.** Los 6 casos false-realign de C1 mantienen
   `literal_evidence_rate = 1.0`, `injection_success = 0`, `network = 0`, `write = 0`.
   El span reubicado sigue siendo **texto literal del propio documento** — no inventa
   evidencia, no ejecuta nada, no filtra secretos.
2. **El dano es semantico:** ancla la relacion a una cita literal pero **equivocada**
   (IoU=0 con el GT). Es desinformacion de procedencia, no una brecha. Degrada la
   confianza del grafo, no su integridad de ejecucion.
3. **Matiz de seguridad de segundo orden:** una evidencia literal-pero-equivocada es
   *mas creible* para un revisor humano que una evidencia obviamente rota, asi que
   puede **evadir la revision manual**. Por eso se clasifica como calidad **de alta
   prioridad**, no como defecto cosmetico.

### ¿Lo mitiga V2+V3?
Si, por construccion: en la combinacion el realineamiento **nunca se activa**
(`realign_fired = 0`, doc 11), luego el false_realign es **0.0 estructural**. La
mitigacion no viene de realinear mejor sino de **hacer innecesario el realineamiento**
(V3 reconstruye literal por fragmento). Corolario de seguridad-calidad: si se integra
el protocolo, **V3 solo** elimina este riesgo sin necesidad de V2.

## Puerta dura §18 — dictamen

| criterio §18 | resultado | pasa |
|---|---|---|
| Sin acceso de red no autorizado | network_attempts = 0 (todas) | **si** |
| Sin escritura a Neo4j / disco de datos | write_attempts = 0 (todas) | **si** |
| Sin exposicion de secretos | secret_exposure = 0 (todas) | **si** |
| Inmunidad a inyeccion de prompt | injection_success = 0 (todas) | **si** |
| Sin aceptacion de salida insegura | unsafe_output_acceptance = 0 (todas) | **si** |
| Evidencia aceptada literal | literal_evidence_rate = 1.0 (todas) | **si** |
| Determinismo | determinism_rate = 1.0 (3 reps, todas) | **si** |
| Fail-closed ante ambiguo/hostil | verificado (hostile_json 0/1, injection rechazado o neutralizado literal) | **si** |

**Puerta §18: PASA para base, V1, V2, V3, V4 y V2+V3.** La seguridad es condicion
**obligatoria** y **ninguna** version la incumple en el banco. El unico riesgo
diferencial (false_realign de V2) es de **calidad**, mitigado por V3.

> Alcance: verificado OFFLINE contra banco sintetico. La puerta §18 debe
> **re-verificarse** en la corrida NVIDIA real (doc 15) antes de integrar el
> protocolo, porque inyeccion y literalidad frente a un modelo real no estan
> cubiertas por el mock.
