# Puerta 6 — Hallazgos (re-medida tras el ciclo de corrección)

Fichero **aparte** de `gate6-factivity-matrix.md` a propósito: aquél lo genera
`gate6_report.py` y se sobrescribe en cada análisis; éste se escribe a mano y
sobrevive a las regeneraciones.

Estado: **re-medido después** de la corrección de D-G1/F6-2 (ampliación del
vocabulario de `cues.py`).

---

## Resumen de la re-medida

| | Fase 2 (antes) | Fase 3 (después) |
|---|---|---|
| Violaciones NVIDIA (familias ABSTAIN que materializan hecho) | **4** | **2** |
| Carril NVIDIA vacuo (0 hechos en controles) | **sí** | **no** (6 hechos) |
| Acuerdo de acción entre carriles | no medible | **79,17 %** (5 discrepancias / 24) |
| Puerta 4 | 0,875 / 0,10 | **idéntica** |

Mejora real y comprobada. Pero **el veredicto de la puerta no puede leerse sin
las dos secciones siguientes**, que es donde está lo importante.

---

## F6-5 — El arreglo NO generaliza: es una tabla de frases

**Éste es el hallazgo central de la fase 3.**

El parche añadió al vocabulario, entre otras, dos frases **literales del corpus**
(«cabe suponer que», «barajan la posibilidad de que»). Volver a medir el mismo
corpus contesta a la pregunta equivocada: dice si el parche tapa los casos que lo
motivaron, no si el sistema entiende la no-factividad. Es el error que este
proyecto ya pagó con el motor v2 (0,81 con dev==test → 0,24 en real).

Para separarlo se construyó un **conjunto de control**
(`factivity_generalization_probe.py`): 30 frases con marcadores no-factivos
**ausentes de `cues.py` y de `cases.json`**. La ausencia se comprueba
automáticamente — 0 frases contaminadas.

| Medida | Resultado |
|---|---|
| No-factivas leídas como **hecho del mundo** | **20 / 26** |
| Acierto en no-factividad | **0,231** |
| Controles positivos acertados | 4 / 4 (**1,000**) |

Fugan **familias enteras**: los 4 rumores, los 4 de hipótesis, las 3 órdenes, las
2 falsedades atribuidas y las 2 de ficción interna. Las 6 que sí se frenan las
frena un mecanismo **estructural** (`si`, `¿?`), **no** el vocabulario nuevo.

La evidencia más limpia está en la propia re-medida: de las 4 violaciones,
**desaparecieron exactamente las 2 cuyas frases literales se añadieron**. Las
otras dos siguen ahí, incluida la que el nuevo patrón productivo de rumor
(`dicen <fuente> que`) estaba pensado para cazar:

| Caso | Familia | Sigue | Texto |
|---|---|---|---|
| `fact:orden:01` | ORDEN | `CREATE_NEGATIVE` | «Custodia el Sello de Lava…, y **no se lo entregues** a nadie de la Casa Verrant.» |
| `fact:rumor:02` | RUMOR | `CREATE_NEGATIVE` | «**Dicen los arrieros, aunque nadie lo firma,** que Runa Belisa dejó de servir al gremio…» |

> La política de factualidad es correcta en su lógica de precedencia, pero
> **depende por completo de que la marca esté enumerada**. Añadir frases arregla
> exactamente esas frases.

---

## F6-6 — El carril de proveedor no es determinista: 5 de 7 cambios son ruido

Entre la corrida de fase 2 y la de fase 3, **con el mismo corpus, el mismo
prompt y el mismo modelo**, cambiaron **7 de 24** casos del carril NVIDIA. Solo
**2** los explica el parche:

| Caso | Cambio | ¿Lo explica el arreglo? |
|---|---|---|
| `fact:hipotesis:01` | CREATE_POSITIVE → NO_FACT | **sí** (frase añadida) |
| `fact:hipotesis:02` | CREATE_POSITIVE → NO_FACT | **sí** (frase añadida) |
| `fact:hecho-afirmado:01` | NO_FACT → CREATE_POSITIVE | no |
| `fact:hecho-afirmado:02` | NO_FACT → CREATE_POSITIVE | no |
| `fact:negacion-factual:02` | NO_FACT → CREATE_NEGATIVE | no |
| `fact:falsedad-atribuida:02` | NO_FACT → CREATE_NEGATIVE | no |
| `fact:alcance-complejo:02` | CREATE_NEGATIVE → NO_FACT | no |

**Suelo de ruido: 5/24 = 20,8 %.** Efecto atribuible al arreglo: 2/24 = 8,3 %.
**El ruido es mayor que el efecto que se pretende medir.**

Consecuencia metodológica, y es seria: **una comparación antes/después de una
sola corrida por carril no puede separar el arreglo del muestreo del modelo.**
Lo único atribuible con confianza son los cambios que explica la capa
determinista (la política de cues); todo lo demás necesitaría corridas repetidas
que esta campaña no ha pagado.

En particular, que el carril **deje de ser vacuo** (0 → 6 hechos en controles) es
una mejora que **ningún cue añadido explica**: es, muy probablemente, muestreo.
No debe apuntarse como logro del ciclo de corrección.

---

## F6-4 — Ollama, segunda corrida: sigue sin ser utilizable, pero ya no revienta

4 frases, `qwen2.5:7b`, 1 716 s de pared, **0 errores de transporte**. Latencia
mediana **588 879 ms** — de nuevo pegada al *timeout* de cliente de 600 s.

| Caso | Diagnósticos | Hechos |
|---|---|---|
| `fact:alcance-complejo:01` | `PREDICATE_NOT_IN_PROFILE` | 0 |
| `fact:condicional:01` | `CONDITIONAL_CONTEXT`, `PREDICATE_NOT_IN_PROFILE` | 0 |
| `fact:contrafactual:01` | `CONDITIONAL_CONTEXT`, `PREDICATE_NOT_IN_PROFILE`, `UNKNOWN_ENTITY_TYPE` | 0 |
| `fact:deseo:01` | `DESIRE_CONTEXT` | 0 |

Diferencia con la corrida anterior: entonces 2 de 4 episodios murieron con
`PROVIDER_UNAVAILABLE`; ahora los 4 respondieron. Lo que aparece en su lugar es
`PREDICATE_NOT_IN_PROFILE` en 3 de 4: el modelo **sí** propone relaciones, pero
inventa predicados fuera de la ontología y el sistema los rechaza —que es
exactamente lo que debe hacer, y lo que la puerta 5 exige.

Sigue siendo un carril **vacuo** (0 hechos, 0 controles medidos) y sigue sin ser
utilizable para ingesta en esta máquina.

---

## F6-1 — El carril determinista sigue sin extraer nada (ahora sobre las 100)

`det` y `combined`, **corpus completo de 100 frases**: 0 hechos positivos, 1
negativo, y **0 hechos en los 20 controles positivos**.

> **Corrección a mi propio informe de fase 2.** Allí declaré estos carriles
> «100 frases». Era falso: el fichero crudo que dejé cubría **12** casos — era la
> corrida de humo y nunca la repetí a tamaño completo. La conclusión no cambia
> (ahora verificada sobre las 100), pero la cobertura declarada estaba mal y el
> artefacto se ha regenerado.

No es un defecto del extractor: `RELATION_RULES` es una lista curada y literal
por diseño. La consecuencia sí importa: cualquier gate de seguridad sobre este
carril pasa **por inanición**.

---

## F6-7 — La política, medida de verdad, acierta 79/100 (no 100/100)

Segunda corrección a la fase 2: allí escribí que «el carril `policy` clasifica
las 100 frases bien». Sólo había mirado las 12 primeras. Medido sobre las 100:

**79/100 correctas, 21 discrepancias**, de las cuales **12 son frases no-factivas
que la política lee como hecho del mundo** (3 condicionales, 4 contrafactuales,
2 deseos, 3 órdenes), más 4 de alcance complejo, 3 negaciones factuales no
detectadas y 2 falsedades atribuidas donde política y corpus discrepan de forma
defendible.

El parche **no movió ni un solo caso** de este carril (0 cambios de clase entre
antes y después), lo que confirma que las violaciones de NVIDIA venían del camino
de claim (`analyze_context` con `focus_char`), no de `analyze_raw_text`.

---

## F6-3 — El acuerdo entre carriles ya es medible, y es 79,17 %

Con el carril NVIDIA no vacuo, el gate por fin se puede calcular sobre un
conjunto con contenido:

| Carriles comparados | Frases comunes | Con algún hecho | Acuerdo | Estado |
|---|---|---|---|---|
| `det` + `combined` + `nvidia` | 24 | 6 | **79,17 %** (5 discrepancias) | **NO CONFORME** |
| … + `ollama` | **4** | **0** | 100,00 % | **NO EVALUABLE** |

**La cifra vinculante es 79,17 %.** El 100 % de la segunda fila es un espejismo y
merece explicación, porque estuvo a punto de colarse como verde:

> Al añadir Ollama —que sólo midió 4 frases— la **intersección** de los cuatro
> carriles se encoge a esas 4, y en ninguna de ellas produce un hecho **ningún**
> carril. Coincidir en no hacer nada no es coincidir. Es la misma inanición que
> el analizador ya vigilaba en los gates por carril, disfrazada de acuerdo.

El analizador se corrigió para exigir que en el conjunto común haya **al menos un
hecho sobre el que discrepar**; si no lo hay, el gate sale **NO EVALUABLE** en vez
de CONFORME. Sin esa corrección, este informe habría publicado un 100 % de
acuerdo perfectamente falso.

---

## Veredicto de la puerta 6

**NO CONFORME.**

Mejoró de forma real (4 → 2 violaciones, carril interpretable, gate de acuerdo
medible), pero:

- persisten 2 violaciones, una de ellas la que el patrón productivo debía cazar;
- el acierto en no-factividad **fuera del corpus es 0,231**;
- el suelo de ruido del proveedor (20,8 %) supera al efecto medido (8,3 %).

**Recomendación:** no dar por cerrada la no-factividad ampliando más el
vocabulario. Cada frase nueva compra exactamente esa frase. La sonda de
generalización debería ser el criterio de aceptación de cualquier intento
futuro, y debería ejecutarse **antes** de tocar `cues.py`.
