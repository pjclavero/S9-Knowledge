# Bucle de revisión humana y Teacher Lab — S9-Knowledge V3

Fecha: 2026-07-30 · Estado: **registro V3 implementado; aprendizaje pendiente**

> **El activo principal no será GPT, Claude ni Qwen. Será el historial estructurado
> de decisiones humanas correctas.** Contiene el dominio real, la ontología propia,
> los errores reales, los criterios de aprobación y los casos que de verdad aparecen
> en los documentos. Los modelos grandes deben ayudar a multiplicar, auditar y
> explotar ese conocimiento, no sustituirlo ni inventarlo desde cero.

Todo lo demás de este documento se deriva de esa frase.

---

## 1. Punto de partida verificado (2026-07-29)

Dos comprobaciones en el código, no supuestos:

- **El glosario no crece.** `resolution/glossary.py` define `GlossarySource` con un
  único método, `lookup()`. No hay `add`, `insert`, `upsert` ni `save`. La
  implementación real sobre SQLite es un enganche declarado y **sin conectar**.
- **Ya existe una cola de revisión V3.** El pipeline exporta paquetes inmutables a
  `proposals/`, `/v3/review` los sirve y registra las decisiones humanas en una
  cadena append-only. Las correcciones humanas explícitas generan candidatos de
  glosario deduplicados, siempre `PROPOSED`, sin mutar el glosario efectivo.
- **El aprendizaje estructurado sigue pendiente.** El historial ya no se pierde,
  pero todavía no existe el proceso que lo convierta, con aprobación humana, en
  reglas, cambios de perfil, casos de regresión o datasets del Teacher Lab.

**Estado actual:** el primer tramo urgente ya está cubierto: las decisiones se
registran y los candidatos de glosario se conservan sin aplicación automática.
La prioridad pasa a explotar ese historial de forma versionada, reversible y
medible, sin confundir «candidato generado» con «conocimiento aplicado».

## 2. Human Review Learning Loop

Cada decisión humana sobre una propuesta se registra como dato de primera clase:
qué se propuso, qué decidió el humano, por qué, sobre qué evidencia y con qué
ontología vigente. De ahí salen candidatos —nunca cambios automáticos— para:

- entradas de glosario y alias;
- predicados o ajustes de dominio/rango del `GameProfile`;
- entidades canónicas y fusiones;
- casos de regresión.

Todo candidato entra en estado `PROPOSED` y requiere aprobación explícita. El
glosario y el perfil son **datos editables, versionados y reversibles**: ahí es
donde el sistema acumula conocimiento sin volverse opaco.

## 3. Teacher Lab V1 — cuatro funciones, ninguna entrena nada

### A · Auditor de gold

Recibe texto + gold + ontología. Devuelve `AGREE | DISPUTE | UNCERTAIN` con la
incidencia, la etiqueta sugerida, el razonamiento y la evidencia. **No modifica el
gold**: un `DISPUTE` abre una incidencia que resuelve un segundo revisor o el humano.

Detecta sistemáticamente lo que hoy encontramos por casualidad: menciones sin
anotar, predicado equivocado, dirección invertida, evidencia incompleta, negaciones
mal tipadas, claims no factuales y relaciones que faltan. (Ya nos pasó dos veces:
la mención de "Umbra" y el `MEMBER_OF` que debía ser `LEADS`.)

> **Añadido imprescindible: medir al auditor antes de creerle.** Un auditor solo
> detecta lo que sabe detectar, y un `AGREE` no significa nada hasta demostrar que
> sabría decir `DISPUTE`. Antes de usarlo, **sembrar errores conocidos** en una
> muestra del gold (mutación deliberada: cambiar un predicado, invertir una
> dirección, desplazar una evidencia) y medir cuántos caza. Es la misma disciplina
> de mutación que ya aplicamos a los tests: una prueba en verde solo cuenta si la
> mutación correspondiente la pone en rojo.

**Separación por split, no negociable:**

- `dev-real`: el Teacher Lab puede auditarlo libremente.
- `validation-real`: la auditoría produce **solo incidencias de calidad**, separadas
  del desarrollo. Si una corrección se usa para cambiar el sistema, esa versión de
  validación deja de ser independiente.
- `heldout-real`: **no se enseña a los profesores antes de la evaluación final**. Se
  audita antes de sellarlo por otra vía, o después de obtener la puntuación.

### B · Generador adversarial

Partiendo de una regla, generar las construcciones difíciles: *"dejó de liderar"*,
*"no dejó de liderar"*, *"no es cierto que dejara de liderar"*, *"negó haber dejado
de liderar"*, *"¿no dejó de liderar?"*, *"si hubiera dejado de liderar…"*, *"afirmó
falsamente que había dejado de liderar"*, *"en la obra representada, dejó de
liderar"*.

Todo va a `dev-synthetic/adversarial`. **Nunca a métricas de generalización real.**
Cada caso se valida antes de recibir etiqueta definitiva.

> **Complemento necesario:** los casos generados desde una regla atacan las reglas
> que ya conocemos, y los fallos reales suelen estar en construcciones que nadie
> anticipó. La fuente adversarial más valiosa es **el corpus real**: las frases donde
> el sistema se abstuvo, donde los revisores discreparon, o donde el motor y el
> extractor no coincidieron. Esas vienen gratis del bucle humano y son adversariales
> de verdad, no imaginadas.

### C · Analista de errores

Compara resultado de S9 contra gold humano y propone causa probable, etapa
responsable, regla candidata, test de regresión y casos similares. Es la función
que más tiempo de diagnóstico ahorra.

### D · Generador de tests

De una corrección validada produce test unitario, test E2E, variaciones
lingüísticas, contraejemplos y prueba negativa. **El resultado esperado se deriva
del gold humano, nunca de la respuesta del profesor.**

## 4. Procedencia obligatoria

```yaml
teacher:
  provider:
  model:
  model_version:
  prompt_version:
  prompt_hash:      # añadido: los prompts se editan sin cambiar de versión
  temperature:
  timestamp:
  tokens:           # añadido: para saber si el laboratorio es sostenible
  cost:

source:
  document_hash:
  fragment_hash:
  ontology_version:

output:
  status: PROPOSED
  destination: dev-synthetic
```

GPT y Claude cambian: una versión nueva puede juzgar de otro modo los mismos
ejemplos. La procedencia permite responder qué profesor generó cada caso, con qué
prompt, quién confirmó la etiqueta y si influyó en alguna regla.

## 5. Entrenamiento, hardware y privacidad

La VM disponible **no puede entrenar**: sirve para inferencia lenta, evaluación,
preparación de dataset, validación e informes. Ni fine-tuning completo, ni LoRA a
escala útil, ni experimentos múltiples. La destilación exigiría GPU alquilada,
hardware externo o servicio gestionado, con política explícita: qué documentos
pueden salir, anonimización, retención del proveedor, cifrado, workspaces
`LOCAL_ONLY`, sintético frente a real, borrado tras el entrenamiento, custodia de
checkpoints y licencias de los modelos.

> **La opción de entrenar con reglas + ontología + ejemplos abstractos + fragmentos
> anonimizados + correcciones humanas estructuradas no es solo la más segura:
> probablemente sea la mejor.** Lo que hay que enseñar no es el contenido de los
> documentos, es el **criterio de decisión**. Dos mil decisiones estructuradas con
> su justificación enseñan más sobre esta ontología que dos mil documentos crudos.

## 6. Orden

```
1. Terminar SemanticEpisodeExtractor E2E          ← hecho (PR #107)
2. Corregir negaciones                            ← hecho
3. Mover política de aprobación al motor
4. Implementar ProposalReconciler
5. Ampliar corpus real dev/validation
6. Human Review Learning Loop                 ← registro implementado; aprendizaje pendiente
7. Correcciones humanas → tests y candidatos  ← candidatos de glosario PROPOSED implementados
8. Teacher Lab V1 (auditor · adversarial · analista · generador de tests)
9. Medir impacto real
10. ¿Hay dataset suficiente para destilar?
11. Evaluar GPU externa y privacidad
12. Teacher Lab V2 / modelo especializado
```

**Dos matices al orden:**

- **El registro del paso 6 debería empezar ya**, en paralelo con 3 y 4. No el bucle
  completo: solo guardar las decisiones humanas en formato aprovechable. Lo que no
  se registre desde hoy no existirá cuando llegue el paso 8.
- **Medir el efecto del paso 3 exige el paso 4.** Está medido que la unión de
  extractores destruye 8 claims correctos; activar autoaprobación sobre un conjunto
  de propuestas que el propio sistema está estropeando daría una medida sin
  significado. La política puede implementarse antes; su evaluación honesta, no.

**Y falta un paso entre 9 y 10:** decidir **cuáles** de las cuatro funciones del
Teacher Lab merecen la pena. Puede que el analista de errores sea rentable y el
generador adversarial no, o al revés. Hay que medir cada una por separado antes de
mantenerlas todas.
