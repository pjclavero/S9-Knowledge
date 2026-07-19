# Puertas de calidad obligatorias (A–H)

Cada bloque debe superar **todas** las puertas, en orden. Ninguna mayoría de condiciones es
suficiente: todas son obligatorias.

## GATE A — Auditoría

Informe con: estado actual · rutas reales · interfaces · riesgos · dependencias · alcance ·
fuera de alcance · tests · mutaciones · puntos de parada · impacto esperado.
Sin auditoría aprobada, no comienza la implementación.

## GATE B — Implementación

Diff dentro del alcance · contratos reutilizados · sin duplicación · sin efectos laterales ·
**sin defaults productivos** · **sin secretos** · sin escrituras no autorizadas · sin cambios
incidentales.

## GATE C — Tests

Unitarios · integración · negativos · hostiles · determinismo · límites · errores · seguridad ·
aislamiento · mutation checks cuando proceda.

No se acepta: tests que copien el producto · stubs como validación final · `skip`/`xfail`
injustificados · mocks que eviten la ruta real · `|| true` · errores silenciados.

## GATE D — Supervisor

Dictamen posible: `CONFORME` · `CONFORME CON OBSERVACIONES` · `NO CONFORME` · `BLOQUEADO`.
**Solo `CONFORME` permite pasar al merge.** `CONFORME CON OBSERVACIONES` no autoriza el merge
automáticamente: el Organizador clasifica las observaciones y exige corrección si afectan a
seguridad, datos, contratos, determinismo, calidad, producción, workspaces, evidencia,
negación, temporalidad, secretos, red o escritura.

## GATE E — CI de PR

Todos los checks requeridos verdes. Checks requeridos actuales del workflow `CI`:

```text
Data Engine Tests
Viewer Tests
Login browser contract (Playwright)
Combined Test Suite (no collection errors)
No dangerous Unicode (Trojan Source)
```

Más el workflow `Supply Chain Security`. No fusionar con checks pendientes, cancelados,
ignorados, tests rojos, auditorías rojas o allowlists improvisadas.

## GATE F — Merge

Fusionar únicamente la PR del bloque actual. Registrar: PR · head · merge commit · fecha ·
agente · Supervisor · tests · mutaciones · CI.

## GATE G — CI post-merge de main

Tras el merge: actualizar `origin/main` → worktree limpio `--detach` sobre `origin/main` →
ejecutar/esperar CI → suite específica del bloque → suite de regresión → comprobar producción →
comprobar `release/rc6-candidate == 15ae1d4`. El bloque **no se cierra** solo por fusionar la PR.

## GATE H — Checkpoint

Publicar el checkpoint formal (ver `checkpoint-template.md`). Solo después se autoriza el
siguiente bloque. La última línea debe ser exactamente una de:
`SIGUIENTE BLOQUE AUTORIZADO` · `SIGUIENTE BLOQUE NO AUTORIZADO` · `PROGRAMA BLOQUEADO`.

## Decisión lógica de autorización (todas obligatorias)

```text
if Supervisor != CONFORME:            no autorizar
if PR_CI != GREEN:                    no autorizar
if Merge != CONFIRMED:                no autorizar
if Main_Post_Merge_CI != GREEN:       no autorizar
if Production != INTACT:              bloquear programa
if RC6_Candidate != 15ae1d4:          bloquear programa
if all_checks_pass:                   autorizar siguiente bloque
```
