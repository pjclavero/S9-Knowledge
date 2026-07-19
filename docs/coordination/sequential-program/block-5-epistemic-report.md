# Informe de validación — Bloque 5: Rumores y estado epistémico

**Fecha:** 2026-07-20
**Rama:** `feat/relation-epistemic-calibration-v1`
**Clasificador:** `relation-epistemic-1.0.0` (`relations.epistemic`)
**Corpus:** `relation-benchmark v1` (sintético; 16 fuentes + fixtures)
**Baseline evaluada:** `baseline1` (pipeline offline determinista)
**Gate:** `rumors` (umbral **0.60**)

## 1. Objetivo

Mejorar la **clasificación epistémica** de las relaciones para que el estado de un
enunciado (hecho / rumor / hipótesis / intención) se derive de forma explícita y
trazable, en lugar de caer por defecto a `ASSERTED`. El gate `rumors` estaba en
**PARTIAL** con valor **0.5** (1/2 casos `RUMORED` correctos): frágil, con solo
dos casos, y sostenido por una única heurística de rumor.

La **regla bloqueante** que gobierna todo el bloque: un **rumor NUNCA se convierte
en hecho**. El estado epistémico no puede perderse. La subida del gate se hace sin
tocar el contrato de datos, el enum, las plantillas de prompt ni el corpus.

## 2. Diagnóstico raíz

El fallo era de **cobertura epistémica**, no de emparejamiento:

1. **Solo dos reglas heurísticas.** `signals.signal_rumor` y
   `signals.signal_modality` reconocían un puñado de marcadores de rumor/modalidad.
   Cualquier enunciado sin esas marcas exactas **caía a `ASSERTED`** por defecto,
   aunque llevara atribución indirecta («según…»), creencia («cree que…»), duda
   («quizá…»), posibilidad («podría…»), condicional («si…»), contradicción
   («fuentes discrepan») o intención («planea…»). El estado epistémico se perdía
   sistemáticamente.
2. **Gate frágil con 2 casos.** Con solo dos casos `RUMORED` en el subgrupo, un
   único acierto/fallo movía la métrica medio punto. La señal no distinguía los
   matices epistémicos, así que la mitad de los enunciados no-asertivos se colaban
   como hechos.

El resultado: un pipeline que, ante la ausencia de una marca reconocida, **afirmaba
de más** — exactamente lo que la regla bloqueante prohíbe.

## 3. Diseño

### 3.1 Módulo `epistemic.py` (nuevo)

`EPISTEMIC_VERSION = "relation-epistemic-1.0.0"`, **independiente** de
`SCHEMA_VERSION`: ampliar los léxicos NO cambia el contrato de datos, solo esta capa
de clasificación. El módulo es **DETERMINISTA y puro** (sin red, disco, estado
mutable ni azar), en la misma línea que `temporality.py` (B4) y `vocabulary.py`
(B3).

### 3.2 Reutiliza el enum del contrato (SIN añadir valores)

`classify_epistemic` reutiliza el enum `EpistemicStatus` de `relations.contracts`
**sin definir uno nuevo ni añadir valores**. Los cuatro valores canónicos son los
del contrato: **ASSERTED · RUMORED · HYPOTHETICAL · INTENDED**. No se toca el enum
ni `SCHEMA_VERSION`: no hay cambio de contrato.

### 3.3 Mapeo de 9 matices a los 4 valores del enum

El clasificador distingue **9 matices finos** (`nuance`) y los **mapea** a los 4
valores existentes. El `nuance` es **metadato de trazabilidad**, NO se persiste como
campo del contrato:

| nuance | status del enum |
|---|---|
| `rumor` | RUMORED |
| `indirect` (atribución de segunda mano) | RUMORED |
| `belief` (creencia/opinión de un sujeto) | RUMORED |
| `contradiction` (versiones en disputa) | HYPOTHETICAL |
| `doubt` (incertidumbre explícita) | HYPOTHETICAL |
| `possibility` (modalidad potencial) | HYPOTHETICAL |
| `hypothesis` (condicional/supuesto) | HYPOTHETICAL |
| `intention` (plan/propósito no realizado) | INTENDED |
| `assertion` (sin marca) | ASSERTED |

### 3.4 Precedencia documentada y estable

`classify_epistemic(text)` aplica una prioridad **documentada y estable**. El primer
grupo con match fija `status` + `nuance`:

```text
RUMOR / INDIRECTO / CREENCIA            -> RUMORED       (mayor prioridad)
CONTRADICCION / DUDA / POSIBILIDAD / HIPOTESIS -> HYPOTHETICAL
INTENCION / PLAN                        -> INTENDED
(ninguna marca)                         -> ASSERTED       (menor prioridad)
```

El rumor pesa **más** que la hipótesis: si algo es a la vez rumor y dudoso, se marca
`RUMORED`. La contradicción se **degrada** a `HYPOTHETICAL` (nunca se afirma algo en
disputa). El matching es por **frontera de palabra** sobre texto aplanado (sin
tildes, minúsculas), evitando falsos positivos por subcadena (`si` casa «si cae»
pero no «situado»).

### 3.5 Invariante de seguridad

**INVARIANTE DURO:** si el texto contiene CUALQUIER cue epistémico no-asertivo, el
`status` resultante **NUNCA** es `ASSERTED`; se degrada a RUMORED/HYPOTHETICAL/
INTENDED según la precedencia. `ASSERTED` se reserva EXCLUSIVAMENTE para textos sin
ninguna marca epistémica.

`is_epistemically_safe(status, has_epistemic_cue)` es la **guardia explícita y
verificable** de ese invariante: devuelve `False` (inseguro) si hay un cue
no-asertivo y aun así el status es `ASSERTED` — es decir, un rumor convertido en
hecho. `classify_epistemic` nunca debe producir un estado inseguro; los consumidores
pueden aseverarlo para blindar el pipeline.

`EpistemicClassification` (frozen) traza la decisión: `status`, `nuance`, `cues`
(literales que dispararon la clase) y `epistemic_version`, con las propiedades
`is_asserted` y `has_epistemic_cue`.

### 3.6 Señal explicable e integración sin tocar el contrato

`signals.signal_epistemic` (nueva) delega en `classify_epistemic` sobre la ventana
de la frase del par y expone la decisión de forma **explicable** (status, nuance,
cues), manteniendo `signal_rumor`/`signal_modality` por compatibilidad.
`pipeline._epistemic_status` delega en la señal (y por tanto en
`classify_epistemic`): **nunca** devuelve `ASSERTED` si hay un cue no-asertivo. No se
tocó `contracts.py`, `SCHEMA_VERSION`, corpus ni schema.

## 4. Resultados: ANTES / DESPUÉS

Benchmark `baseline1` sobre `relation-benchmark v1`, gate `rumors` (medido y
reconfirmado por el Organizador):

| Métrica | ANTES | DESPUÉS | Δ |
|---|---|---|---|
| Estado del gate | **PARTIAL** | **PASS** | — |
| Valor (umbral 0.60) | 0.5 | **1.0** | +0.5 |
| `RUMORED` correctos | 1/2 | **2/2** | **+1** |
| Existencia — Precision | sin regresión | sin regresión | 0 |
| Existencia — Recall | sin regresión | sin regresión | 0 |
| Existencia — F1 | sin regresión | sin regresión | 0 |

El gate pasa de **PARTIAL 0.5 → PASS 1.0** (umbral 0.60) y **no hay regresión en las
métricas globales de existencia**: la mejora es de **clasificación epistémica**, no
altera qué pares se emparejan.

## 5. Análisis de seguridad

- **`is_affirmative()` intacto.** La salvaguarda dura sigue siendo
  `is_affirmative() = (not negated) and status == ASSERTED`, **sin modificar** en
  `contracts.py`. Una relación solo se considera afirmación de hecho si no está
  negada y su estado es `ASSERTED`. Cualquier cue epistémico degrada el status, así
  que un rumor jamás satisface `is_affirmative()`.
- **Chequeos de mutación bloqueantes.** El invariante «cue no-asertivo ⇒ no
  `ASSERTED`» es verificable vía `is_epistemically_safe`: un cambio que permitiera
  que un rumor se afirme como hecho rompería esa guardia. El estado epistémico no se
  pierde en ningún punto del recorrido señal → pipeline → contrato.
- **Conservador al degradar.** Una aserción llana del narrador **sin marcas** se
  clasifica `ASSERTED` (no se degrada de más, para no falsear la métrica). Solo
  degrada cuando hay atribución o cue epistémico real. Es una decisión **honesta**:
  ni se afirma de más, ni se degrada de más.

## 6. Garantías (qué NO se ha tocado)

- **Enum y contrato de datos:** intactos. No se añaden valores a `EpistemicStatus`;
  `SCHEMA_VERSION` no cambia. `EPISTEMIC_VERSION` es una capa aparte. El `nuance` es
  metadato de trazabilidad, **no** un campo del contrato.
- **Corpus / schema del benchmark y plantillas de prompt:** no se modifican.
- **Áreas compartidas:** no se tocan. La semántica epistémica vive en `epistemic.py`;
  nada externo depende de su forma interna.
- **Alcance del cambio de código (por otros agentes):** `epistemic.py` (nuevo),
  `signals.py` (nueva `signal_epistemic` explicable; se mantienen
  `signal_rumor`/`signal_modality`) y `pipeline.py` (`_epistemic_status` delega en
  `classify_epistemic`, nunca `ASSERTED` con cue no-asertivo).

## 7. Estado de producción

Intacta. No se tocó VM105, Neo4j, `auth.db`, `jobs.db`, timers ni servicios.
`S9K_ALLOW_REAL_INGEST = off`. `release/rc6-candidate = 15ae1d4` (inmutable).

## Limitaciones conocidas (aceptadas, no bloqueantes)

Detectadas por el Supervisor y el especialista de integridad; todas en **dirección segura**
(degradan hacia no-asertivo, nunca convierten un rumor en hecho) y con **F1 global sin cambios**.
No afectan al gate ni al corpus del benchmark, por lo que se documentan como deuda de léxico en
lugar de reabrir el clasificador tras la revisión:

- **`sí` vs `si`**: al normalizar acentos, la afirmación "sí" colapsa con el condicional "si", de
  modo que "respondió que sí" se clasifica HYPOTHETICAL en vez de ASSERTED. Sesgo conservador; no
  aparece en el ground_truth.
- **Futuro simple `hará`**: "hará la guerra" se marca INTENDED (intención) aunque pueda ser un
  futuro asertivo. Conservador; fuera del corpus.
- **Conocimiento indirecto `según`/`de acuerdo con`**: se mapea a RUMORED(indirect) por diseño
  (información de segunda mano), consistente con la especificación.
- **Texto vacío / no-str**: por defecto ASSERTED (sin cue). El pipeline nunca alcanza esta rama
  con un cue presente.

Candidatas a un léxico epistémico v1.1 con desambiguación de acentos previa al `strip`.
