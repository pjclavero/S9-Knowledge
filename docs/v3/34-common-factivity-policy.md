# Política común de factualidad

Fecha: 2026-07-30

`extraction/factivity.py` recibe señales tipadas ya detectadas por `cues.py`.
No comprende ni vuelve a leer el texto. Aplica una precedencia conservadora:
la ambigüedad y los marcos no factuales ganan a una negación gramatical interna.

## Tabla normativa

| Clase | Ejemplo | Acción de política |
|---|---|---|
| `ASSERTED_FACT` | «Ilaria lidera la Casa.» | `EMIT_WORLD_CLAIM` |
| `NEGATED_FACT` | «Ilaria no lidera la Casa.» | `EMIT_NEGATED_WORLD_CLAIM` |
| `QUESTION` | «¿Ilaria lidera la Casa?» | `EMIT_DIAGNOSTIC` |
| `CONDITIONAL` | «Si Ilaria liderara la Casa…» | `EMIT_DIAGNOSTIC` |
| `COUNTERFACTUAL` | «De haber sobrevivido, la lideraría.» | `EMIT_DIAGNOSTIC` |
| `HYPOTHETICAL` | «Cabe suponer que la lidera.» | `EMIT_DIAGNOSTIC` |
| `DESIRE` | «Desea que Ilaria lidere la Casa.» | `EMIT_DIAGNOSTIC` |
| `COMMAND` | «Custodia el sello.» | `EMIT_DIAGNOSTIC` |
| `REPORTED_FALSEHOOD` | «Es falso que Ilaria lidere la Casa.» | `EMIT_DIAGNOSTIC` |
| `FICTION_WITHIN_FICTION` | «En la obra, Ilaria lideraba la Casa.» | `EMIT_DIAGNOSTIC` |
| `RUMOR` | «Se rumorea que Ilaria lidera la Casa.» | `EMIT_EPISTEMIC_PROPOSAL` |
| `UNKNOWN` o alcance ambiguo | «No todos los capitanes…» | `REVIEW_SCOPE` |

Hasta que exista un contrato epistémico separado y seguro, una hipótesis
conserva su evidencia como diagnóstico y **nunca** se materializa como relación
del mundo.

## Negación factual frente a falsedad atribuida

«Ilaria no lidera la Casa» afirma directamente un hecho negativo sobre el
mundo y puede emitir un claim negado. «El heraldo afirmó falsamente que Ilaria
lidera la Casa» describe un acto de habla y niega su veracidad: no autoriza a
materializar ni la relación positiva ni su inversión automática. Del mismo
modo, «es falso que no X» no se transforma mediante doble negación en `X`; el
marco `REPORTED_FALSEHOOD` tiene precedencia.

## Limitaciones

La sonda fuera de corpus contiene 30 frases cuyos marcadores no aparecen en
`cues.py` ni en `cases.json`. En las 26 no factivas, **20/26 se leyeron como
hecho del mundo**: el acierto fue **0.231**. Los 4 controles positivos acertaron
4/4. La política léxica es, en la práctica, una tabla de frases, no comprensión
composicional.

El intento de arreglo por vocabulario se rechazó por sobreajuste: desaparecieron
exactamente las dos violaciones cuyas frases literales se añadieron, mientras
persistieron otras dos. La recomendación vigente es ejecutar la sonda de
generalización como **criterio de aceptación antes de tocar `cues.py`**; añadir
vocabulario no demuestra generalización.

El extractor determinista produjo **0 hechos** en las 100 frases del corpus de
factualidad, incluidos 0 en los 20 controles positivos. `RELATION_RULES` es
literal por diseño. Por ello los gates de seguridad de `det` y `combined`
pasan por **inanición**, no por comprensión o acierto, y no son interpretables
como validación positiva.

Fuentes: `artifacts/v3-final-validation/gate6-factivity-matrix.*`,
`gate6-findings.md`, `factivity-generalization-probe.json`,
`knowledge_v3/extraction/factivity.py` y `deterministic.py`.
