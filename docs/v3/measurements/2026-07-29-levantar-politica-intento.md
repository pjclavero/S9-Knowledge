# ¿Qué pasaría si se levanta la política de revisión? — intento fallido

Fecha: 2026-07-29 · **Resultado: el experimento no responde la pregunta.**
Se documenta porque lo que encontró importa más que lo que buscaba.

## Qué se intentó

Quitar la marca `review_required` de las propuestas (sin tocar código de
producción) y medir cuántas aprobaría el motor y cuántas de esas serían correctas.

## Qué salió

| | ACCEPT | REVIEW | ABSTAIN | Operaciones |
|---|--:|--:|--:|--:|
| Con la política | 0 | 8 | 10 | 0 |
| **Sin la política** | **0** | **8** | **10** | **0** |

Ni una diferencia. La primera lectura sería "la política no bloquea nada", pero los
códigos de razón dicen otra cosa:

```
REVIEW    REVIEW_ENTITY              x8
REVIEW    UNRESOLVED_MENTION         x8
ABSTAIN   CLAIM_ABSTAINED_UPSTREAM   x10
```

Y confirmado: `EXTRACTOR_REQUESTED_REVIEW` **ya no aparece**, así que el
desmarcado sí funcionó.

## Por qué no vale

**Los 8 no se paran por la política: se paran antes, por menciones sin resolver.**
El montaje usó las resoluciones *gold*, que corresponden a las menciones del gold y
no a las que produce el extractor —tienen identificadores distintos—, así que el
motor recibe claims cuyos argumentos no están resueltos y no puede llegar a evaluar
nada más. Es un artefacto del experimento, no del sistema.

**Y los 10 tampoco son del motor:** `CLAIM_ABSTAINED_UPSTREAM` significa que **el
extractor ya se había abstenido** de esos claims. El motor no los rechaza; los
recibe ya renunciados.

## Lo que sí queda demostrado

1. **Levantar la política no basta**, y probablemente no sea ni el primer paso: hay
   dos bloqueos por delante — la resolución de identidad y la abstención del propio
   extractor — que el motor nunca llega a superar.
2. **La medición honesta exige la cadena completa** con el resolutor real. Cualquier
   atajo con resoluciones gold mide el atajo, no el sistema.
3. El desglose que se venía repitiendo (7 por política, 10 por calidad) procede de
   una corrida por la cadena real y **no debe mezclarse** con estas cifras, que
   salen de otro montaje.

## Qué habría que hacer para responder de verdad

Ejecutar la cadena E2E completa —normalización, extracción, **resolución real**,
motor— con y sin la marca de revisión, sobre el mismo corpus. Eso cuesta una tanda
de inferencia (unos 50 minutos con el modelo local) y es el experimento que decide
si mover la política del extractor al motor cambia algo.

Mientras tanto, la pregunta abierta más interesante no es la política, sino:
**¿por qué el extractor se abstiene en 10 de 18?** Eso es techo de calidad, y ningún
cambio de política lo levanta.
