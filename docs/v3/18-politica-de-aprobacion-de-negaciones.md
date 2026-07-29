# Política de aprobación de negaciones — bloque `feat/v3-negation-approval-policy`

Fecha: 2026-07-29 · Estado: **especificado, no implementado**

Objetivo: retirar la política universal que hoy vive en el extractor
(`deterministic.py:643`, `review = bool(negated or ...)`) y trasladar la decisión al
motor, con una política **graduada por tipo de negación**. Hoy toda negación acaba
en revisión humana con un plan de cero operaciones, así que el camino de escritura
de negaciones tiene **cobertura cero en producción**.

Este bloque **no mejora el extractor**. Solo mueve la decisión a donde corresponde y
activa la autoaprobación del caso más seguro.

---

## 1. El extractor emite datos, no decisiones

```yaml
negated: true
negation_kind: CESSATION
scope_confidence: 0.96
evidence_verified: true
origin: semantic_nvidia
requires_temporal_resolution: true
```

**Precisión obligatoria sobre `scope_confidence`:** debe calcularse **localmente**,
nunca aceptarse del modelo. Un número autorreportado por un LLM no está calibrado —
ya lo medimos: qwen copiaba la confianza del ejemplo del prompt, y no es
reproducible ni a temperatura cero. La confianza de alcance sale de señales
verificables: cuántas marcas de negación hay, si media un verbo de actitud entre la
marca y el foco, si están en la misma cláusula, si hay puntuación intermedia. Si se
acepta el número del modelo, estamos reconstruyendo el fallo de V2 con otro nombre.

## 2. Política por tipo, en el motor

### Negación simple — *"Toturi no pertenece al Clan del León"*

Acción: crear una afirmación negativa. **Autoaprobable** si y solo si:

1. la cita está anclada literalmente;
2. sujeto y objeto aparecen en el texto;
3. el predicado pertenece a la ontología;
4. el alcance es inequívoco;
5. no es pregunta, condicional, rumor ni orden;
6. no hay contradicción sin resolver;
7. las validaciones locales son conformes.

### Negación absoluta (NEVER) — *"Toturi nunca perteneció al Clan del León"*

Autoaprobable con requisitos reforzados, **sin interpretar que la negación cubre
toda la historia universal**: conserva el contexto temporal y la procedencia.

> Añadido: `NEVER` debe registrar explícitamente **hasta cuándo sabe la fuente**. Un
> "nunca" en un documento fechado en 1042 no dice nada sobre 1050. Sin ese anclaje,
> un `NEVER` se convierte en una afirmación sobre el futuro que la fuente no hizo.

### Cesación — *"Toturi ya no lidera"*, *"dejó de liderar"*

**`REVIEW_NEGATION_CESSATION`**, siempre, en esta fase. Puede cerrar una afirmación
existente, crear una supersesión y alterar la lectura temporal del grafo.

### Negación de una cesación — *"Toturi no dejó de liderar"*

**No es `CESSATION`.** Significa que la cesación no ocurrió y, según el contexto,
puede apoyar la continuidad. Va a **`REVIEW_NEGATION_SCOPE`**. Ninguna regla basada
solo en las palabras "dejó de" puede cerrar una relación.

### `NOT_YET` y alcance ambiguo

*"todavía no lidera"*, *"no cree que Akodo lidere"*, *"no es falso que lidere"*:
revisión o abstención hasta que la resolución de alcance sea fiable.

## 3. Batería mínima antes de soltar la protección

| Familia | Casos |
|---|--:|
| Negación simple | 10 |
| NEVER | 6 |
| CESSATION | 10 |
| Negación de cesación | 8 |
| NOT_YET | 5 |
| Alcance en subordinadas | 5 |
| Preguntas / condicionales / rumores | 4 |
| Doble negación | 2 |
| **Total** | **50** |

Los casos **no** pueden ser variaciones del mismo esqueleto: deben cambiar verbos,
predicados, orden de las frases, voz activa y pasiva, entidades, longitud,
puntuación, errores de transcripción y forma de la construcción negativa.

**Tres añadidos:**

1. **Controles positivos.** Afirmaciones normales sin negación, para detectar que la
   política de negación no contamina el camino positivo. Si al activar esto empiezan
   a fallar afirmaciones corrientes, hay que verlo.
2. **Casos cuya respuesta correcta es "no hay claim"**, no solo negaciones bien
   clasificadas.
3. **La batería se escribe sin mirar `cues.py`.** Ocho de los casos son de la
   familia que acabamos de arreglar; escritos leyendo la implementación, medirían el
   propio código y darían un verde vacío. Misma disciplina que con el held-out.

## 4. Condiciones para activar la autoaprobación de negaciones simples

```
false_positive_positive_edge            = 0
false_cessation_from_negated_cessation  = 0
evidence_grounding                      = 100 %
scope_accuracy                          suficientemente alta
```

Y por encima de todo: **"no dejó de X" nunca puede convertirse en "dejó de X"**.

> **Cuarta métrica, que falta y es imprescindible:** *recall de autoaprobación* —
> de las negaciones simples que **deberían** aprobarse, ¿cuántas se aprueban? Un
> sistema tan conservador que autoaprueba 0 de 10 cumple los cuatro criterios de
> arriba y no sirve para nada. Hay que medir las dos caras o el gate premia la
> parálisis.

## 5. Cesaciones: modo sombra antes que autoaprobación

Para cesaciones **no** se activa autoaprobación hasta tener corpus mayor y
resultados E2E reales. Propuesta intermedia que da datos sin riesgo:

**Modo sombra.** El motor calcula qué habría cerrado y lo registra, **sin cerrarlo**.
El ítem sigue yendo a revisión humana. Cuando el humano decide, se compara su
decisión con la que el motor habría tomado. Con unas decenas de casos reales se
sabe si el motor acierta, y con datos de producción en vez de sintéticos — usando
la cola de revisión que ya existe como fuente de verdad, gratis.

## 6. Secuencia

```
Bloque actual (cerrado, PR #107)
├── corregir clasificación
├── verificar negaciones
├── mantener freno universal
└── cerrar con seguridad

Bloque siguiente
├── batería de 50 casos (escrita a ciegas)
├── retirar la decisión del extractor
├── mover la política al motor
├── autoaprobar solo negaciones simples seguras
├── mantener cesaciones en revisión (modo sombra)
└── medir escritura E2E real
```

El principio que ordena todo esto: **no se retira el cinturón de seguridad el mismo
día en que se descubre que el sistema confundía "dejó de liderar" con "no dejó de
liderar"**. Primero se valida la comprensión; después se activa el motor real, y por
tramos.
