# Registro de riesgos

| ID | Riesgo | Prob. | Impacto | Mitigación | Estado |
|---|---|---|---|---|---|
| R-01 | NVIDIA sin API key en el entorno → Bloque 2 no ejecutable | Alta | Medio | Marcar Bloque 2 `BLOQUEADO` por causa externa; documentar en checkpoint; requiere aprobación explícita del Organizador para saltar con la validación marcada como no ejecutable | Abierto |
| R-02 | Uso accidental de endpoint productivo por defecto | Media | Alto | Endpoint explícito obligatorio; mutation check "endpoint por defecto"; sin defaults productivos | Mitigado por diseño |
| R-03 | Fuga de secretos en logs | Media | Alto | Logs redactados; scan de secretos en GATE E/G; mutation check "secreto en logs" | Mitigado por diseño |
| R-04 | Escritura no autorizada en modo sombra | Baja | Alto | Modo sombra estricto sin escritura; mutation check "escritura en sombra"; test no-write | Mitigado por diseño |
| R-05 | Rumor convertido en hecho (pérdida de estado epistémico) | Media | Alto | Bloque 5 bloqueante ante pérdida de estado epistémico; mutation check dedicado | Abierto (Bloque 5) |
| R-06 | Pérdida de evidencia/offsets/workspace | Media | Alto | Tests de evidencia/offsets/workspaces en GATE C y GATE G | Abierto |
| R-07 | Corpus del benchmark alterado sin versionar | Baja | Medio | B1 v1 inmutable; crear B1 v2 aparte; mutation check "benchmark con corpus alterado" | Mitigado por diseño |
| R-08 | Resultado no determinista aceptado | Media | Medio | Tests de determinismo; variabilidad LLM documentada y acotada | Abierto |
| R-09 | Autoaprobación productiva | Baja | Alto | Prohibida; en Bloque 8 solo simulación deshabilitada; mutation check "autoaprobación" | Mitigado por diseño |
| R-10 | Modificación de `release/rc6-candidate` | Baja | Crítico | Verificar `== 15ae1d4` en cada GATE G; bloquear programa si difiere | Vigilado |
| R-11 | Afectación de producción (VM105/Neo4j/auth.db/jobs.db/timer/deploy) | Baja | Crítico | Todo el programa es solo lectura sobre producción; `PROGRAMA BLOQUEADO` si se detecta | Vigilado |
| R-12 | CI post-merge de main rojo | Media | Alto | `HOTFIX_BLOCK_N` con ciclo completo antes de cerrar el bloque | Contingencia definida |
| R-13 | Deriva del alcance / cambios incidentales entre bloques | Media | Medio | Diff acotado por `ownership-map.md`; Supervisor rechaza cambios fuera de alcance | Vigilado |
| R-14 | Programa muy largo → fatiga de proceso, saltos de gate | Media | Alto | Máquina de estados estricta; ninguna transición prohibida; checkpoint por bloque | Vigilado |

## Disparadores de bloqueo inmediato del programa

- Escritura, conexión no autorizada, reinicio, cambio de datos o de configuración productiva.
- `release/rc6-candidate` distinto de `15ae1d4`.
- Hallazgo de seguridad sin corrección ni bloqueo documentado.
