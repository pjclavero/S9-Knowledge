# Efecto del reconciliador — medición sobre `dev`

Fecha: 2026-07-29 · Sin inferencia nueva (caché de respuestas de qwen2.5:7b)

## Qué se midió

Las mismas propuestas (determinista + semántico) con y sin reconciliador, hasta el
final de la cadena: primero puntuadas por el arnés, después decididas por el motor.

## Resultado 1 — el arnés vuelve a poder medir

| | Menciones | Claims correctos | F1 |
|---|--:|--:|--:|
| Semántico solo | 40 | **3** | 0.421 |
| Unión **sin** reconciliador | 82 | **0** | 0.000 |
| Unión **con** reconciliador | **55** | **3** | **0.421** |

El reconciliador colapsa 27 menciones duplicadas y **recupera los claims que la
unión destruía**. Es el test de aceptación del componente y lo pasa.

## Resultado 2 — el motor decide exactamente igual

| | ACCEPT | REVIEW | ABSTAIN | Planes | Operaciones |
|---|--:|--:|--:|--:|--:|
| Sin reconciliador | **0** | 8 | 10 | 5 | **0** |
| Con reconciliador | **0** | 8 | 10 | 5 | **0** |

**Ni una sola decisión cambia.** El reconciliador no desbloquea ninguna aprobación.

## Lectura honesta

Esto no es un fallo del reconciliador: es la confirmación de dónde está el cuello
real. El componente arregla **la medición** —sin él, el emparejamiento uno a uno del
arnés dejaba los claims sin argumentos alineados y todo puntuaba a cero—, pero el
motor ya recibía los 18 claims antes y ya decidía sobre ellos. Alinear
identificadores de menciones no cambia si la evidencia está anclada, si el predicado
pertenece a la ontología, ni si la propuesta viene marcada para revisión.

Los 18 se reparten como ya sabíamos:

- **8 a revisión**: la política "origen no confiable ⇒ revisión humana". Es lo que
  levantaría el bloque de política de negaciones y aprobación local.
- **10 abstenciones**: calidad real del modelo — argumentos sin anclar, predicados
  fuera de ontología, citas alucinadas. A esos no les falta permiso, les falta ser
  correctos.

**Conclusión operativa:** el siguiente paso que mueve la aguja no es reconciliar
mejor, es (a) mover la política de aprobación del extractor al motor y (b) mejorar
la calidad del extractor semántico. El reconciliador era condición necesaria para
poder medir cualquiera de las dos, y ya está.

## Método

`ProposalReconciler` por defecto; motor con perfil genérico, snapshot vacío,
resoluciones gold (para aislar el efecto del reconciliador sobre el motor sin que la
resolución añada su propia varianza); lotes por asset, como exige el motor.
Reproducible desde la caché sin llamar al modelo.
