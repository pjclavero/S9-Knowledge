# Medicion en sombra: precision del subconjunto-acuerdo determinista ∧ NVIDIA

> **Revision (ronda acotada tras dictamen CONFORME CON OBSERVACIONES).** La
> primera version de este documento definia el acuerdo exigiendo `ACCEPT`
> real del motor en AMBOS carriles. El revisor senalo que ese criterio hace
> el resultado (`n=0`) **tautologico**: multiplica dos eventos ya raros del
> motor (la puerta 4 mide un recall de autoaprobacion bajo, ver docs/v3/46
> 1.4), asi que la interseccion se vacia por construccion del filtro, no por
> la hipotesis medida. Este documento redefine el acuerdo a **nivel de
> CONTENIDO** (mismo claim + predicado compatible + misma polaridad, SIN
> exigir `ACCEPT`) como vista PRINCIPAL, y conserva el criterio original como
> vista secundaria `acuerdo_con_accept`, documentado como tautologico. El
> revisor tambien detecto una purga de cache incompleta (2 entradas `"model":
> "mock"` sobrevivieron en la cache compartida con B3): se corrigio separando
> la cache de este bloque en `artifacts/agreement/cache/` (nunca compartida
> con `artifacts/gate4-program/b3-cache/`) y repitiendo la medicion. Los
> resultados de este documento son de esa version corregida.

## Objetivo del bloque

Hipotesis del operador: si el subconjunto donde el carril DETERMINISTA
(`local_only`, la cadena E2E real que mide el 0.607 de B2) y el carril NVIDIA
(`external_only`, en SOMBRA) llegan INDEPENDIENTEMENTE al MISMO claim tiene
precision alta, se podria proponer una politica de tipo "acuerdo → ACCEPT,
discrepancia o carril unico → REVIEW" con muestreo de auditoria como red. Este
bloque **mide, no decide**: no cambia ninguna politica, no escribe en Neo4j
(el writer de `pipeline.runner.run_one` va SIEMPRE en DRY-RUN, sin bandera que
lo cambie) y no toca produccion ni el gold congelado.

## Diseno del criterio de acuerdo

### Vista PRINCIPAL: `acuerdo_contenido`

Un claim entra en `acuerdo_contenido` si, sobre el MISMO `claim_id` del gold
(sujeto/objeto alineados):

1. ambos carriles proponen algo emparejable (`covered=True` en ambos);
2. el predicado top-1 coincide, o esta ausente en alguno de los dos carriles
   (compatible-por-omision, declarado como limitacion mas abajo);
3. la polaridad (`negated`) coincide entre carriles.

**No se exige ningun veredicto concreto del motor.** El par de decisiones de
cada caso (`ACCEPT/ACCEPT`, `REVIEW/REVIEW`, `ACCEPT/REVIEW`, `ABSTAIN/x`,
...) se publica como ATRIBUTO (`decision_pair`) de cada caso y se desglosa
por celda: esa tabla es la que responde la pregunta del operador, no un
agregado que la esconde. En particular, el subconjunto `REVIEW/REVIEW` (ambos
motores marcan el claim para revision, pero de forma INDEPENDIENTE y con la
MISMA polaridad) es el que mas directamente informa la hipotesis: si ambos
carriles ya coinciden en que un claim necesita ojos humanos Y en cual seria
su polaridad si se aceptara, ¿acierta ese acuerdo?

Caveat declarado sobre `ABSTAIN`: `build_rows` (runner congelado) da
`negated=False` por CONVENCION cuando el motor abstiene -- no porque el
carril haya comprobado una polaridad. Un par `ABSTAIN/ABSTAIN` cae en
`acuerdo_contenido` (misma polaridad por defecto en ambos lados), pero cada
caso lleva el atributo `ambos_abstienen=True` para que no se lea como una
coincidencia de asercion activa.

### Vista SECUNDARIA (tautologica, conservada por trazabilidad): `acuerdo_con_accept`

El criterio ORIGINAL de este bloque: subconjunto de `acuerdo_contenido` donde
AMBOS carriles reciben `predicted_decision == "ACCEPT"` real del motor
(`engine/decision.py`), que ya incorpora la puerta 6 (`review_required` +
`epistemic_status_hint` degradado nunca `ACCEPT`, ver docs/v3/46 P0) y la
verificacion de evidencia literal. Se conserva como vista secundaria, pero
**declarada tautologica**: no usar `n=0` en esta vista para concluir "el
acuerdo no sirve" -- para eso esta `acuerdo_contenido`.

### Los conjuntos que produce el script

| conjunto | definicion |
| --- | --- |
| `acuerdo_contenido` | **vista principal**: mismo claim, predicado compatible, misma polaridad -- sin exigir ACCEPT; desglosado por `decision_pair` |
| `acuerdo_con_accept` | **vista secundaria, tautologica**: subconjunto de arriba con ACCEPT/ACCEPT |
| `solo_det` | solo el carril determinista cubre el claim (nota: `is_abstain` marca si esa cobertura es una abstencion) |
| `solo_nvidia` | solo el carril NVIDIA cubre el claim (misma nota) |
| `discrepancia.polaridades_opuestas_activas` | ambos carriles predicen algo ACTIVO (ninguno abstiene) y la polaridad difiere -- la discrepancia semantica "dura" |
| `discrepancia.abstain_vs_afirma` | un carril abstiene (`negated=False` por convencion) y el otro predice algo activo con polaridad distinta -- discrepancia parcialmente artefactual |
| `discrepancia.predicado_incompatible` | mismo claim, pero el predicado top-1 de cada carril difiere (ambos lo declaran) |
| `sin_cubrir` | ningun carril propone nada emparejable |

**Precision** de `acuerdo_contenido` (global y por `decision_pair`) y de
`solo_det`/`solo_nvidia` = fraccion de casos donde la polaridad coincide con
el gold. **Recall de `acuerdo_contenido`** = `n / evaluable_total` (56, la
misma convencion de "casos evaluables" que usan B0-B3: se excluye el unico
ABSTAIN puro del gold, sin `subject_mentions` ni `object_mentions`). Este
recall es la respuesta a "¿cuanta revision libera la politica?": una
precision de 1.000 sobre un acuerdo que cubre poco del gold no libera casi
nada de revision humana aunque sea perfecta.

## Hallazgo de diseno: por que este script NO usa `benchmarks.harness`

La primera version de este bloque emparejo los claims predichos contra el
gold con `benchmarks.harness.score_extractor` (via `pipeline.bundle.to_bundle`),
igual que hace `measure_b3.py`. Con la cadena E2E real (`local_only`,
`entry="raw"`) esa via da **cobertura estructuralmente cero**: el normalizador
acuna sus propios `episode_id` (`ep-<hash>`) a partir de los BYTES de
entrada, y `score_extractor` exige coincidencia EXACTA de `episode_id` para
emparejar menciones. El runner E2E CONGELADO que mide el 0.607 real de B2
(`artifacts/v3-final-validation/gate4_negation_measure.py`) no tropieza con
esto porque implementa su PROPIO alineamiento de tres fases
(`episode_alignment` por texto literal, `mention_alignment` por span +
fallback de superficie normalizada, `claim_alignment` por menciones-gold
traducidas) mas `build_rows` (una fila por claim gold evaluable, con la
decision REAL del motor).

Este bloque **reutiliza esas cuatro funciones tal cual**, cargando el runner
congelado por ruta via `knowledge_v3.eval._frozen_runner.load()` -- el MISMO
cargador que ya usan `dev_corpus.py` y `harness.py` para no fijar el nombre
del split a mano y para no copiar codigo. Nunca se modifica ni se importa
como paquete: es lectura por ruta, igual que el resto del repo ya hace.

## Que se reutiliza (nada de esto es nuevo)

| pieza | ruta | por que |
| --- | --- | --- |
| Gold congelado (57 claims, hash verificado) | `knowledge_v3.eval.dev_corpus.load_dev_gold` | el MISMO split `negation` que miden B0-B3 |
| `pipeline.runner.run_one` | `knowledge_v3/pipeline/runner.py` | via DESIGNADA en B3-gate4 (docs/v3/40) para correr la cadena completa con un proveedor externo sobre el mismo split; demostrada por `test_gate4_b3_adversarial.py` |
| Alineamiento de 3 fases + filas del motor | `artifacts/v3-final-validation/gate4_negation_measure.py` (via `_frozen_runner.load()`) | resuelve el desajuste de `episode_id`; produce `predicted_decision` REAL (ACCEPT/REVIEW/ABSTAIN/REJECT) |
| Retry/metering/cache NVIDIA | `scripts.gate4.measure_b3.make_b3_port` | backoff exponencial, timeout duro, cache en disco -- reutilizado tal cual |

## Cache: por que es propia del bloque (causa estructural de la contaminacion)

`CachingPort` (reutilizado de `measure_b3.py`) guarda `respuesta -> hash de
`system+prompt+purpose`, sin distinguir de que bloque vino la peticion. Un
directorio de cache compartido entre `measure_b3.py` y este script mezcla sus
respuestas si algun prompt coincide -- y, mas grave, una corrida `--mock` que
por descuido apunte a la ruta compartida escribe respuestas VACIAS (`{"model":
"mock", "claims": [], ...}`) que un `--mock` posterior sirve como si fueran
reales. Eso fue exactamente lo que ocurrio dos veces durante el desarrollo de
este bloque (ver seccion siguiente). La correccion estructural: este script
usa `artifacts/agreement/cache/` por defecto, un directorio PROPIO, nunca
`artifacts/gate4-program/b3-cache/` de B3. Los tests de este bloque
(`test_agreement_shadow.py`) SIEMPRE apuntan `--cache` a un directorio
temporal propio en cualquier subproceso que invoquen, incluidos los que
prueban la garantia de "no carga el driver neo4j" -- ese era el vector que
faltaba corregir en la primera version de la suite.

## Incidencias de proceso, declaradas (dos rondas de contaminacion detectadas y corregidas)

1. **Primera contaminacion** (antes de la primera medicion real): una prueba
   de humo con `--mock` sin `--cache` explicito escribio 42 respuestas vacias
   en la ruta compartida `artifacts/gate4-program/b3-cache/`. Se detecto por
   `tokens.total_tokens=0` junto con `cache.calls_served_from_cache=42` en
   una corrida que no debia tener cache previa; se corrigio purgando el
   directorio y repitiendo la pasada real completa.
2. **Segunda contaminacion** (detectada por el revisor, no por este agente):
   dos subprocesos de test que invocaban `--mock` sin fijar `--cache`
   siguieron usando la ruta compartida por defecto de esa version del
   script, y las dos corridas de la suite completa (ejecutada dos veces
   sobre esa cache) dejaron 2 entradas `"model": "mock"` en
   `artifacts/gate4-program/b3-cache/responses.json` -- verificable porque
   `CachingPort` nunca escribe en excepcion, asi que esas 2 entradas SOLO
   pudieron venir de una pasada `--mock`, no de las 2 llamadas reales
   fallidas de la medicion real (esas nunca se cachearon). Esto NO cambiaba
   las cifras del artefacto ya publicado (una respuesta mock vacia equivale
   a un episodio sin cobertura, que es como ya se contabilizaba), pero
   invalidaba la narrativa de incidencias ("2 fallidas `ProviderUnavailable`")
   frente al fichero de cache real, que ya no las respaldaba con ese
   contenido.

Correccion aplicada: (a) purga de las 2 entradas mock de la cache heredada de
B3 (identificadas por `"model": "mock"`), (b) separacion de la cache de este
bloque en `artifacts/agreement/cache/` (nunca compartida), (c) todos los
subprocesos de test fijan `--cache` a un directorio temporal propio, (d)
regeneracion de artefactos a partir de la cache real (40 entradas reales
conservadas) mas 2 llamadas nuevas contra la API (una de las 2 que habian
fallado en la medicion original se resolvio; la otra volvio a fallar).

## Limitaciones declaradas

* **Techo del acuerdo acotado por la cobertura determinista.** El carril
  determinista solo cubre 0.607 del gold (B2, cadena congelada completa); en
  este arnes (`local_only` + alineamiento del runner congelado) su cobertura
  medida es menor aun (ver `alineamiento.covered_rows` en el JSON). El
  acuerdo, por construccion, no puede superar el minimo de cobertura de los
  dos carriles.
* **n=56 evaluables.** El mismo techo pequeno que ya declaro el programa de
  la puerta 4 (dev==test): una precision de un subconjunto de este tamano
  tiene un intervalo ancho y no se trata como una cifra poblacional. Los
  desgloses por `decision_pair` son sobre subconjuntos AUN mas pequenos
  (4-6 casos por celda): leerlos como tendencia poblacional seria un error
  mayor todavia.
* **Predicado compatible-por-omision.** Cuando un carril no resuelve
  predicado (`predicted_predicate=None`), el par se declara compatible sin
  comprobacion real: es una limitacion explicita del criterio, no un acierto
  fabricado.
* **`ABSTAIN` no es una polaridad comprobada.** `negated=False` en una fila
  `ABSTAIN` es una convencion de `build_rows` (el runner congelado), no una
  afirmacion del carril. Se declara en cada caso (`is_abstain`,
  `ambos_abstienen`) y en las notas de `solo_det`/`solo_nvidia` para que no
  se lea como precision de aserciones activas.
* **Inestabilidad de la API NVIDIA (heredada de B3).** Latencias de decenas
  de segundos por llamada y una fraccion de episodios perdidos tras agotar
  reintentos; una sola pasada de este bloque no distingue un pico puntual del
  comportamiento habitual del proveedor. Cifras reales de incidencias, cache
  y coste de la pasada final en `artifacts/agreement/agreement-shadow.{json,md}`.

## Reproduccion

```bash
export S9K_NVIDIA_ENABLED=true
export S9K_NVIDIA_API_KEY=...   # nunca en la linea de comandos ni commiteada
cd /ruta/al/repo
PYTHONPATH=data-engine/app python3 scripts/agreement/measure_agreement.py \
    --out-dir artifacts/agreement --out-name agreement-shadow \
    --cache artifacts/agreement/cache --concurrency 2
```

`--mock` sustituye NVIDIA por un puerto guionizado (sin red, sin key): sirve
para probar el script y es lo que usan los tests unitarios
(`data-engine/app/tests/test_agreement_shadow.py`), SIEMPRE con `--cache`
apuntando a un directorio temporal propio.

La cache de respuestas es PROPIA de este bloque (`artifacts/agreement/cache/`,
gitignored) para no refacturar en repeticiones; el resultado agregado
versionado es `artifacts/agreement/agreement-shadow.{json,md}`.

## Resultados (medicion final, corregida)

Cifras completas en `artifacts/agreement/agreement-shadow.{json,md}`,
generadas de punta a punta por el script (nada transcrito a mano),
`mock: false` verificado en el JSON.

### Vista PRINCIPAL: `acuerdo_contenido`, desglosado por par de decisiones

**n=15, precision global=0.8667, recall sobre el gold=0.2679 (15/56).**

| par de decisiones (det/nvidia) | n | tp | fp | precision |
| --- | ---: | ---: | ---: | ---: |
| ABSTAIN/ABSTAIN | 6 | 4 | 2 | 0.6667 |
| ABSTAIN/REVIEW | 3 | 3 | 0 | 1.0000 |
| ACCEPT/REVIEW | 2 | 2 | 0 | 1.0000 |
| **REVIEW/REVIEW** | **4** | **4** | **0** | **1.0000** |

El subconjunto `REVIEW/REVIEW` -- ambos motores marcan el claim para revision,
de forma INDEPENDIENTE, con la MISMA polaridad -- es el que responde la
pregunta del operador de forma mas directa: 4/4 aciertos en esta medicion. Es
un n muy pequeno (4 casos): no se trata como una cifra poblacional, pero es
un dato real, no una tautologia del criterio.

Los pares `ABSTAIN/ABSTAIN` (6 casos, precision 0.6667) son el grupo mas
grande pero el mas debil evidencialmente: coinciden en polaridad por
CONVENCION (`negated=False` por defecto en ambos lados cuando ambos motores
abstienen), no porque ninguno de los dos haya comprobado nada. Sus 2 falsos
positivos son casos donde el gold SI declara negacion pero ninguno de los dos
carriles produjo evidencia para afirmarla.

### Vista SECUNDARIA (tautologica): `acuerdo_con_accept`

**n=0, precision=None, recall=0.0.** Confirma la prediccion del revisor: con
el criterio original (ACCEPT real en ambos carriles), el conjunto sigue vacio
en esta corrida -- pero ahora se sabe que es un artefacto del filtro
(`ACCEPT` en ambos motores es un evento raro multiplicado dos veces), no una
propiedad del sistema medido. La vista principal (`acuerdo_contenido`) es la
que aporta senal real.

### Otros conjuntos

| conjunto | n | tp | fp | precision |
| --- | ---: | ---: | ---: | ---: |
| solo-det | 14 | 6 | 8 | 0.4286 |
| solo-nvidia | 10 | 5 | 5 | 0.5000 |
| discrepancia: polaridades opuestas ACTIVAS | 0 | 0 | 0 | -- (conjunto vacio) |
| discrepancia: abstain vs afirma | 5 | -- | -- | -- |
| discrepancia: predicado incompatible | 0 | -- | -- | -- |
| sin_cubrir | 12 | -- | -- | -- |

**Discrepancias activas reales (dos predicciones activas, polaridad
opuesta): 0.** Con la separacion de ABSTAIN, no hay ningun caso en este gold
donde ambos carriles afirmen algo activo y se contradigan en polaridad. Los 5
casos de "discrepancia" que existen son todos `abstain_vs_afirma` (un carril
abstiene, negated=False por convencion; el otro predice algo activo con
polaridad distinta) -- listados en el `.md` con su `gold_negated`.

### Coste / latencia / incidencias de la API (pasada final, desde cache real + 2 llamadas nuevas)

* Cache real conservada de la medicion original: 40 entradas (0 mock).
* 2 llamadas nuevas necesarias (los 2 episodios que habian fallado sin
  cachearse la primera vez): **1 exito, 1 fallo** tras agotar reintentos.
* 5 reintentos de transporte, 4 timeouts duros de 60s en esta pasada final.
* Latencia media 34.3 s/llamada, p95 54.2 s (sobre las llamadas reales
  medidas) -- mismo orden que B3 y que la medicion original.
* 206,483 tokens totales en la tanda (cache + llamadas nuevas).
* Unico error de transporte observado: `ProviderUnavailable`.
* Cache: 40 servidas / 2 miss -- consistente con partir de la cache real
  purgada de mocks.

### Lectura para la decision del operador (sin recomendacion de politica)

* precision del acuerdo de CONTENIDO (vista principal): **0.8667** (n=15,
  desglosado por par de decisiones arriba).
* recall del acuerdo de contenido sobre el gold: **0.2679** (15/56).
* precision del acuerdo_con_accept (vista secundaria, tautologica): **None**
  (n=0) -- no usar esta cifra para concluir que el acuerdo no sirve.
* precision solo-det: 0.4286 (n=14); precision solo-nvidia: 0.5000 (n=10).
* discrepancias activas reales (polaridad opuesta, ambos carriles con
  prediccion activa): **0**.
* discrepancias abstain-vs-afirma: 5; predicado incompatible: 0; sin cubrir:
  12.
* El subconjunto `REVIEW/REVIEW` (4 casos, 4/4 aciertos) es el material mas
  directo para evaluar si "acuerdo de contenido, incluso cuando ambos
  motores piden revision" podria autoaprobarse con muestreo de auditoria --
  la decision de politica, con su intervalo de confianza sobre un n de 4,
  es del operador.
