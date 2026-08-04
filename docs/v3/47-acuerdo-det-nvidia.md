# Medicion en sombra: precision del subconjunto-acuerdo determinista ∧ NVIDIA

## Objetivo del bloque

Hipotesis del operador: si el subconjunto donde el carril DETERMINISTA
(`local_only`, la cadena E2E real que mide el 0.607 de B2) y el carril NVIDIA
(`external_only`, en SOMBRA) llegan INDEPENDIENTEMENTE al MISMO claim tiene
precision ≈ 1.000, se podria proponer la politica "acuerdo → ACCEPT,
discrepancia o carril unico → REVIEW" con muestreo de auditoria como red. Este
bloque **mide, no decide**: no cambia ninguna politica, no escribe en Neo4j
(el writer de `pipeline.runner.run_one` va SIEMPRE en DRY-RUN, sin bandera que
lo cambie) y no toca produccion ni el gold congelado.

## Diseno del criterio de acuerdo

Un claim entra en **acuerdo** si, sobre el MISMO `claim_id` del gold
(sujeto/objeto alineados):

1. ambos carriles proponen algo emparejable (`covered=True` en ambos);
2. la polaridad (`negated`) coincide entre carriles;
3. el predicado top-1 coincide, o esta ausente en alguno de los dos carriles
   (compatible-por-omision, declarado como limitacion mas abajo);
4. **ambos carriles reciben `ACCEPT` del motor real** (`engine/decision.py`),
   no `REVIEW` ni `REJECT`.

El punto 4 es la conexion con la puerta 6: `ACCEPT` ya exige evidencia
literal verificada Y que `epistemic_status_hint` no este degradado
(`review_required` depende de `hint != ASSERTED`, conectado de verdad al
extractor determinista desde el rework de gate6-B2, ver docs/v3/46 P0). Un
claim con hint degradado (RUMORED, HYPOTHETICAL, INTENDED, VISUAL_INFERRED)
en cualquiera de los dos carriles **nunca** entra en acuerdo, aunque ambos
coincidan en polaridad: va al conjunto de diagnostico
`degradado_no_acuerdo`, no a `acuerdo`. Es la MISMA puerta que ya usa
produccion, no una reimplementacion paralela de la regla.

Los 4 (+1 diagnostico) conjuntos que produce el script:

| conjunto | definicion |
| --- | --- |
| `acuerdo` | ambos carriles cubren el claim, coinciden en polaridad/predicado, y ambos `ACCEPT` |
| `solo_det` | solo el carril determinista cubre el claim |
| `solo_nvidia` | solo el carril NVIDIA cubre el claim |
| `discrepancia` | ambos cubren, pero polaridad o predicado NO coinciden |
| `degradado_no_acuerdo` | ambos cubren y coinciden en polaridad/predicado, pero al menos uno NO recibe `ACCEPT` (factividad degradada o evidencia no verificada) |
| `sin_cubrir` | ningun carril propone nada emparejable |

**Precision** de cada conjunto (salvo `discrepancia`, donde no hay un unico
veredicto compartido) = fraccion de casos donde la polaridad acordada/propia
coincide con el gold. **Recall del acuerdo** = `|acuerdo| / evaluable_total`
(56, la misma convencion de "casos evaluables" que usan B0-B3: se excluye el
unico ABSTAIN puro del gold, sin `subject_mentions` ni `object_mentions`).
Este recall es la respuesta a "¿cuanta revision libera la politica?": una
precision de 1.000 sobre un acuerdo que cubre el 5 % del gold no libera casi
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
| Alineamiento de 3 fases + filas del motor | `artifacts/v3-final-validation/gate4_negation_measure.py` (via `_frozen_runner.load()`) | resuelve el desajuste de `episode_id`; produce `predicted_decision` REAL (ACCEPT/REVIEW/REJECT) |
| Retry/metering/cache NVIDIA | `scripts.gate4.measure_b3.make_b3_port` | backoff exponencial, timeout duro, cache en disco -- reutilizado tal cual |

## Reproduccion

```bash
export S9K_NVIDIA_ENABLED=true
export S9K_NVIDIA_API_KEY=...   # nunca en la linea de comandos ni commiteada
cd /ruta/al/repo
PYTHONPATH=data-engine/app python3 scripts/agreement/measure_agreement.py \
    --out-dir artifacts/agreement --out-name agreement-shadow \
    --cache artifacts/gate4-program/b3-cache --concurrency 2
```

`--mock` sustituye NVIDIA por un puerto guionizado (sin red, sin key): sirve
para probar el script y es lo que usan los tests unitarios
(`data-engine/app/tests/test_agreement_shadow.py`).

La cache de respuestas se comparte con B3 (`artifacts/gate4-program/b3-cache/`,
gitignored) para maximizar aciertos y no refacturar; el resultado agregado
versionado es `artifacts/agreement/agreement-shadow.{json,md}`.

## Limitaciones declaradas

* **Techo del acuerdo acotado por la cobertura determinista.** El carril
  determinista solo cubre 0.607 del gold (B2); el acuerdo, por construccion,
  no puede superar ese techo -- como maximo el acuerdo cubre lo que el
  determinista YA cubre. Si NVIDIA cubre menos aun, el techo real es el
  minimo de los dos.
* **n=56 evaluables.** El mismo techo pequeno que ya declaro el programa de
  la puerta 4 (dev==test): una precision de un subconjunto de este tamano
  tiene un intervalo ancho y no se trata como una cifra poblacional.
* **Predicado compatible-por-omision.** Cuando un carril no resuelve
  predicado (`predicted_predicate=None`), el par se declara compatible sin
  comprobacion real: es una limitacion explicita del criterio, no un acierto
  fabricado.
* **Inestabilidad de la API NVIDIA (heredada de B3).** La corrida original de
  B3 tuvo 3.3 % de episodios perdidos tras agotar reintentos y latencias de
  decenas de segundos por llamada; una sola pasada de este bloque no
  distingue un pico puntual del comportamiento habitual del proveedor. Cifras
  reales de incidencias, cache y coste de ESTA pasada en
  `artifacts/agreement/agreement-shadow.{json,md}`.

## Resultados (corrida real del 2026-08-04/05, sin cache preexistente)

Cifras completas en `artifacts/agreement/agreement-shadow.{json,md}`,
generadas de punta a punta por el script (nada transcrito a mano). La cache
de B3 (`artifacts/gate4-program/b3-cache/`) no existia en este checkout --
se perdio con su worktree por ser gitignored, confirmado por el orquestador
-- asi que esta pasada parte de cache vacia: **0 aciertos preexistentes**,
declarados sin maquillaje.

> **Incidencia de proceso, declarada.** La primera ejecucion de este script
> (sin `--mock` explicito en la primera prueba de humo) escribio, por
> accidente, respuestas MOCK (claims vacios) en la ruta de cache POR DEFECTO
> (`artifacts/gate4-program/b3-cache/`) al probar `--mock` sin apuntar
> `--cache` a un directorio temporal. La corrida "real" siguiente sirvio esas
> 42 respuestas vacias desde cache (0 llamadas reales, 0 tokens) y hubiera
> publicado un `acuerdo`/`solo_nvidia` en cero por un artefacto del proceso,
> no por el sistema medido. Se detecto por el campo `tokens.total_tokens=0`
> junto con `cache.calls_served_from_cache=42` en un run que no debia tener
> cache -- una senal que no cuadraba -- y se corrigio purgando el directorio
> de cache contaminado y repitiendo la pasada completa contra la API real
> antes de aceptar ningun numero. Los resultados de abajo son de esa segunda
> pasada, verificada `mock: false` en el JSON.

### Los 4 (+1 diagnostico) conjuntos

| conjunto | n | tp | fp | precision |
| --- | ---: | ---: | ---: | ---: |
| **acuerdo** | **0** | 0 | 0 | **None (conjunto vacio)** |
| solo-det | 16 | 8 | 8 | 0.5000 |
| solo-nvidia | 9 | 4 | 5 | 0.4444 |
| discrepancia | 3 | -- | -- | ver casos abajo |
| degradado_no_acuerdo | 15 | -- | -- | -- |
| sin_cubrir | 13 | -- | -- | -- |

**Recall del acuerdo sobre el gold: 0.0 (0/56).**

### Lectura honesta

El subconjunto de acuerdo **esta vacio** en esta medicion: ningun claim del
gold recibe, simultaneamente, `ACCEPT` real del motor en AMBOS carriles con
la misma polaridad. La hipotesis del operador ("si el acuerdo tiene
precision ≈1.000, se puede proponer acuerdo→ACCEPT con muestreo de
auditoria") **no se puede evaluar sobre este gold con esta version del
carril NVIDIA**: no hay division por cero disimulada -- el reporte devuelve
`precision: None` explicitamente porque `n=0`, no un `1.000` vacio de
contenido. La razon se ve en el desglose:

* **15 casos** (el grupo mas grande) coinciden en sujeto/objeto/polaridad
  entre carriles pero el motor no los aceptaria en al menos uno (mayoria
  `ABSTAIN`/`REVIEW` reales, ver la tabla de casos en el `.md`): la puerta 6
  ya los manda a revision, con o sin acuerdo de polaridad.
* **13 casos** no los cubre ningun carril.
* **9 casos** los cubre solo NVIDIA (precision 0.4444 en solitario) y **16**
  solo el determinista (precision 0.5000 en solitario) -- las dos cabezas de
  cobertura se solapan poco en este split.
* **3 discrepancias** reales de polaridad (los 3 casos listados en el `.md`,
  con el `gold_negated` de cada uno): material de diagnostico directo para
  quien trabaje el clasificador de negacion o el prompt de NVIDIA.

Cuando SI cubren el mismo claim con la misma polaridad (aritmetica:
16+9+3+15 = 43 casos con algun tipo de superposicion o cobertura unilateral,
de 56 evaluables), el motor casi nunca acepta ambos a la vez -- la
factividad conectada en gate6-B2 y la verificacion de evidencia literal son,
en este split, un filtro mucho mas estricto que "misma polaridad". Ese es el
hallazgo cuantitativo central del bloque: **el cuello de botella del acuerdo
no es el desacuerdo de polaridad (solo 3 casos), es que ambos carriles rara
vez llegan a `ACCEPT` a la vez** (0 casos de 56).

### Coste / latencia / incidencias de la API (pasada real, sin cache previa)

* 42 llamadas intentadas, 40 reales OK, **2 fallidas** tras agotar
  reintentos (4.8 %) -- comparable al 3.3 % de B3.
* 31 reintentos de transporte, 26 timeouts duros de 60s.
* Latencia media 33.7 s/llamada, p95 53.7 s -- mismo orden que B3.
* 201,222 tokens totales en la tanda.
* Unico error de transporte observado: `ProviderUnavailable` (429/5xx/timeout
  ya mapeados por el puerto).
* Cache: 0 servidas / 42 miss -- consistente con partir de cache vacia
  (declarado arriba).

### Lectura para la decision del operador (sin recomendacion de politica)

* precision del acuerdo: **indefinida (n=0)** -- el conjunto que la politica
  propuesta autoaprobaria esta vacio en este gold.
* recall del acuerdo sobre el gold: **0.0** (0/56).
* precision solo-det: 0.5000 (n=16); precision solo-nvidia: 0.4444 (n=9).
* 3 discrepancias de polaridad reales, 15 casos perdidos por factividad/
  evidencia pese a coincidir en polaridad, 13 sin cobertura de ningun
  carril.
* La politica "acuerdo→ACCEPT" tal como esta definida (exigiendo `ACCEPT`
  real de ambos carriles) no tiene, hoy, sobre este gold y este carril
  NVIDIA, ningun caso sobre el que aplicarse. Cualquier decision sobre
  relajar el criterio (por ejemplo, aceptar acuerdo de polaridad sin exigir
  `ACCEPT` de ambos motores) es del operador, y el conjunto
  `degradado_no_acuerdo` (15 casos) es exactamente el material para
  evaluarla.
