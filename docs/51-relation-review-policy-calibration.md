# 51 - Politica de reduccion controlada de revision humana (relaciones): calibracion y resultado

**Fecha:** 2026-07-21
**Bloque:** 8 del programa secuencial de S9 Knowledge — "Reduccion controlada de
revision humana"
**Rama:** `feat/relation-review-policy-calibration-v1`
**Worktree:** `/home/ia02/worktrees/relation-review-policy-calibration-v1`
**Modulos nuevos:** `relations/review_policy.py`, `relations/benchmark/review_policy_metrics.py`
**Tests nuevos:** `tests/test_relation_review_policy_block8_smoke.py` (36),
`tests/test_relation_review_policy_block8_full.py` (75) — **111** tests propios
del bloque, verificados ejecutando pytest el 2026-07-21.
**Estado:** MODO SOMBRA, sin activacion en produccion. Ningun fichero fuera de
`relations/` y `tests/` importa el codigo de este bloque.

> **Que es este bloque, en una frase.** Calibra una POLITICA que identifica un
> subconjunto de relaciones de ALTA confianza que PODRIA saltarse la revision
> humana, y MIDE cuanto de segura seria esa reduccion — nunca la activa, nunca
> auto-aprueba ni escribe nada.

---

## 1. Objeto y encuadre de seguridad

El Bloque 8 responde a una pregunta muy concreta: **¿existe un subconjunto de
relaciones ya calculadas por el ensemble/consenso (Bloques 6/7) suficientemente
fiable como para que un humano no tenga que revisarlo antes de proponerlo?** Y,
si existe, **¿cuan seguro es proponerlo automaticamente, medido con datos?**

Es, por diseno, un ejercicio de **medicion en modo sombra**, con las mismas
garantias que ya establecio el Bloque 7 para el benchmark de proveedores:

- **No auto-aprueba ni escribe nada.** El modulo produce una **recomendacion**
  (`AUTO_PROPOSABLE` / `REVIEW_REQUIRED`) y una **medicion de seguridad**
  (precision, tasa de falso-aceptado, cobertura), nunca un `APPROVED`, `WRITE`,
  `APPLY`, `COMMIT` o similar. El propio codigo prohibe expresamente que
  cualquiera de esas palabras aparezca como *label* de la politica (ver §2).
- **`relations/` esta desconectado de toda via de escritura.** Se verifico
  buscando quien importa el paquete `relations` en todo el repositorio: solo
  ficheros dentro de `relations/` y de `tests/` lo hacen. Nada en `review/`
  (el modulo que sí decide sobre ingesta real, `review/auto_decider.py` y
  `review/ingest_approved.py`), ni en `cli/`, ni en ningun *writer*, importa
  `relations.review_policy` ni `relations.benchmark.review_policy_metrics`.
  El bloque es, literalmente, codigo que nadie fuera de si mismo invoca.
- **Fail-closed sistematico.** Ante cualquier duda — dato ausente, tipo
  inesperado, coleccion no iterable, config invalida — la funcion de
  clasificacion nunca lanza una excepcion no controlada por un input
  malformado ni "adivina": devuelve `REVIEW_REQUIRED`. El error de programacion
  (una `ReviewPolicyConfig` invalida) sigue fallando ruidosamente, a proposito,
  porque eso **no** es un dato de entrada dudoso sino un bug del propio modulo.

Este encuadre es el mismo que ya aplicaron los Bloques 6/7 al ensemble y al
benchmark: medir sin tocar produccion, y declarar honestamente lo que la
medicion diga, incluso si la respuesta es "no, todavia no".

---

## 2. Diseno

### 2.1 `ReviewPolicyConfig` — umbrales versionados

`relations/review_policy.py` define una config inmutable (`@dataclass(frozen=True)`)
con los umbrales calibrables:

| Campo | Valor por defecto | Que controla |
|---|---|---|
| `auto_propose_score_threshold` | **0.90** | score minimo del ensemble para considerar auto-proponible |
| `min_providers_present` | **1** | proveedores (local/external) con evaluacion real presente |
| `config_version` | `relation-review-policy-thresholds-1.0.0` | version de los umbrales, separada de `REVIEW_POLICY_VERSION` (version del CODIGO) |

`config_hash` es un sha256 truncado (16 hex) del `to_dict()` serializado con
claves ordenadas: cualquier cambio de umbral queda trazado y es auditable en
cada `ReviewPolicyOutcome`. El constructor valida tipos (rechaza `bool` donde
espera `float`/`int`, rechaza umbrales fuera de `(0, 1]`, rechaza
`min_providers_present < 1`) y lanza `ReviewPolicyConfigError` si algo no
cuadra.

### 2.2 `ReviewPolicyOutcome` y por que el "no" es `REVIEW_REQUIRED`, no `HUMAN_REQUIRED`

Solo existen dos etiquetas, `AUTO_PROPOSABLE` y `REVIEW_REQUIRED`
(`REVIEW_POLICY_LABELS`). El nombre del "no" es deliberadamente
`REVIEW_REQUIRED` y **no** `HUMAN_REQUIRED`, por una razon concreta verificada
en el codigo: `HUMAN_REQUIRED` **ya es un estado de consenso canonico** de
`external_ai.models.CONSENSUS_STATES` (el que usa `relations.ensemble` cuando
el consenso entre proveedores no es concluyente). Si la politica reutilizara
ese mismo literal como *label* propio, un mismo string significaria dos cosas
distintas segun el contexto — un estado de consenso del ensemble o una
recomendacion de la politica de revision — y esa ambiguedad es exactamente lo
que el diseno prohibe.

El propio modulo lo defiende en tiempo de import con dos aserciones:

```python
if any(lbl in _FORBIDDEN_LABELS for lbl in REVIEW_POLICY_LABELS):
    raise AssertionError(...)
if set(REVIEW_POLICY_LABELS) & set(CONSENSUS_STATES):
    raise AssertionError("las etiquetas de politica NO pueden solapar CONSENSUS_STATES")
```

`_FORBIDDEN_LABELS` es una lista explicita de vocabulario de
aprobacion/escritura (`AUTO_APPROVED`, `APPROVED`, `WRITE`, `APPLY`, `COMMIT`,
`MERGE`, `ACCEPT`, `ACCEPTED`, `AUTO_ACCEPT`, `AUTO_ACCEPTED`), y
`ReviewPolicyOutcome.__post_init__` la vuelve a comprobar en cada instancia
como defensa en profundidad — no solo en tiempo de import del modulo.

### 2.3 `classify_for_review` — las 5 condiciones duras

Toda la logica de clasificacion vive en una sola funcion pura y determinista.
Recibe senales **ya calculadas** por `relations.ensemble.combine` (no
recalcula nada) y exige que se cumplan **las cinco** condiciones para devolver
`AUTO_PROPOSABLE`:

1. `state == STRONG_CONSENSUS`
2. `providers_present >= config.min_providers_present` (>= 1 por defecto)
3. `score >= config.auto_propose_score_threshold` (>= 0.90 por defecto)
4. `len(conflicts) == 0`
5. `has_evidence is True`

Si falta una sola, o si cualquier campo de entrada es del tipo incorrecto,
inesperado o ausente, la funcion devuelve `REVIEW_REQUIRED` con una razon
legible (p.ej. `"score=0.7 (< umbral 0.9)"`) y conserva en `signals` los
valores de entrada para trazabilidad/auditoria, sin exponer secretos.

### 2.4 La medicion: `precision`, `false_accept_rate`, `coverage`, `sample_size`

`relations/benchmark/review_policy_metrics.py` reutiliza el runner y el
`matching` **reales** del benchmark del Bloque 7 (no reimplementa nada del
pipeline ni del ensemble) para calcular, sobre el subconjunto que la politica
etiqueta `AUTO_PROPOSABLE`:

| Metrica | Definicion |
|---|---|
| `precision` | de lo auto-propuesto, que fraccion es realmente correcta (`expected_decision == "ACCEPT"` en el ground truth) |
| `false_accept_rate` | fraccion de lo auto-propuesto que **no** deberia haberse aceptado (incluye cualquier falso positivo auto-propuesto: sin relacion real en el ground truth, cuenta siempre como falso-aceptado) |
| `coverage` | auto-propuesto / total evaluado (y tambien sobre TP, `coverage_over_tp`) |
| `sample_size` | tamano de la muestra auto-propuesta (TP + FP auto-propuestos) |

Estas cuatro claves se publican **siempre**, incluso en 0 o en el peor
escenario: la transparencia no se sacrifica cuando el resultado es
desfavorable.

---

## 3. Gates de seguridad

Fijados en `relations/benchmark/review_policy_metrics.py`, no se relajan por
codigo llamante:

| Gate | Umbral | Naturaleza |
|---|---|---|
| `review_policy_false_accept_rate` | **<= 0.02** | DURO |
| `review_policy_precision` | **>= 0.98** | DURO |
| `review_policy_sample_size` | **>= 20** para que los dos anteriores puedan ser PASS/FAIL | DURO |
| `review_policy_coverage` | ninguno (`status: INFORMATIVE`, `hard: False`) | **SOLO INFORMATIVA** |

### 3.1 Por que `sample_size < 20` no es simplemente "FAIL"

Con menos de 20 muestras auto-propuestas, los gates de FAR/precision son
`NOT_MEASURED` — **salvo** que ya haya al menos un falso-aceptado observado, en
cuyo caso el gate es `FAIL` **incondicionalmente**, sin importar cuan pequena
sea la muestra. Es el patron `strict_small_sample`, analogo al B3 que el
Bloque 7 aplico al umbral de transporte: una muestra insuficiente **nunca** es
excusa para certificar una politica que ya demostro dano. Verificado en el
codigo (`evaluate_review_policy_gates`):

```python
if sample_size < MIN_SAMPLE_SIZE:
    shared_status = "FAIL" if false_accepts > 0 else "NOT_MEASURED"
    ...
```

### 3.2 Por que `coverage` es solo informativa, nunca un minimo exigido

`coverage` se publica siempre (incluida su variante `coverage_over_tp`), pero
`evaluate_review_policy_gates` la marca explicitamente `hard: False` y
`status: "INFORMATIVE"`. La razon, documentada en el propio modulo, es de
diseno de seguridad: **forzar una cobertura minima invertiria el incentivo**.
Si "hay que cubrir al menos X%" fuera un requisito, la politica se veria
empujada a bajar el umbral de score o a relajar alguna condicion dura solo
para alcanzar esa cobertura — exactamente lo que un gate de seguridad no debe
premiar. Al dejar `coverage` fuera de los gates duros, la unica forma de
"aprobar" la politica es que lo poco o mucho que proponga sea **correcto**, no
que proponga mucho.

---

## 4. Resultado real offline (sin maquillar)

Artefacto de referencia: `b8_review_policy_offline.json` (ejecucion offline
sobre el corpus real de 16 fuentes / 54 relaciones, modos `baseline1` y
`ensemble_offline`, sin proveedores).

| Modo | `sample_size` | Cobertura auto-proponible | Gates | Dictamen |
|---|---|---|---|---|
| `baseline1` | 0 | 0 % | `review_policy_false_accept_rate`, `review_policy_precision`, `review_policy_sample_size` → `NOT_MEASURED` | **"POLITICA DE REDUCCION: NO CALIBRABLE (COBERTURA INSUFICIENTE)"** |
| `ensemble_offline` | 0 | 0 % | idem | idem |

Justificacion exacta que emite el propio codigo:

> `muestra auto-proposable insuficiente (0 < 20) y sin falso-aceptado
> observado que fuerce FAIL: no se puede certificar ni descartar la politica
> con esta cobertura.`

### 4.1 Causa raiz, verificada en el codigo (no en la teoria)

`AUTO_PROPOSABLE` exige `state == STRONG_CONSENSUS`. `relations/ensemble.py`
(`_derive_state`) hace que `STRONG_CONSENSUS` **estructuralmente** requiera,
en las dos ramas (positiva y negativa) que pueden llegar a ese estado:

```python
if (score >= config.strong_threshold
        and n_decisive >= config.min_decisive_sources
        and has_evidence
        and providers_present >= 1
        and consensus.state in (STRONG_CONSENSUS, PARTIAL_CONSENSUS)):
    return (STRONG_CONSENSUS, RECO_PROPOSE, ...)
```

Es decir: `providers_present >= 1` y `has_evidence` son condiciones que ya
exige el propio `STRONG_CONSENSUS`, no solo la politica de revision. En modo
offline **no hay ningun proveedor** (`local_llm` y `external_ai` valen
`NOT_EXECUTED`, cero llamadas), asi que `providers_present` es siempre `0`
para cualquier candidato: `STRONG_CONSENSUS` es **inalcanzable** sin
corroboracion real de al menos un proveedor. Sin `STRONG_CONSENSUS`, la
condicion 1 de `classify_for_review` falla siempre, y la muestra auto-proponible
es necesariamente vacia.

### 4.2 Conclusion honesta y segura del bloque

**Con la calidad actual del pipeline, nada puede saltarse la revision humana
de forma segura; no se justifica reducir la supervision.** No es un fallo del
Bloque 8: es un resultado **valido** y medido — el bloque hizo exactamente lo
que tenia que hacer (calibrar y medir con honestidad) y la medicion, sobre los
datos disponibles hoy, dice "no calibrable, no hay base para reducir revision".

---

## 5. Enlace con el Bloque 7 y prediccion fundamentada (SEGUIMIENTO, no ejecutado)

El Bloque 7 (`docs/50-relation-benchmark-results.md`, §12 y §12A) **si** midio
con proveedores reales, sobre la misma submuestra de 6 fuentes:

| Proveedor | Modelo | Llamadas respondidas | Invalidas | `results_strong` | Motivo dominante |
|---|---|---|---|---|---|
| Ollama | `qwen2.5:7b` (7,6B, local) | 27 | **18/27 (66,7 %)** | **0** | `offsets_do_not_match_evidence` (10), `no_relation_extracted` (7), `evidence_not_in_document` (1) |
| NVIDIA | `meta/llama-3.3-70b-instruct` (70B, alojado) | 27 | **27/27 (100 %)** | **0** | `evidence_text` vacia o ausente (uniforme, 27/27) |

En ambos casos `results_strong = 0`: ninguna de las evaluaciones reales de
proveedor llego a producir un veredicto suficientemente valido como para
contribuir a un `STRONG_CONSENSUS`. Esto es una **prediccion fundamentada en
datos ya medidos**, no algo que el Bloque 8 haya ejecutado: **es razonable
esperar que una pasada de este bloque con proveedores reales encendidos
tambien de una cobertura auto-proponible cercana a 0 %**, porque el cuello de
botella no es la ausencia de proveedor en si, sino que el anclaje de
evidencia (offsets correctos, o el campo `evidence_text` bien poblado) falla
sistematicamente hoy en los dos proveedores probados — uno local de 7B y uno
alojado de 70B.

**Esto queda marcado explicitamente como SEGUIMIENTO**: la medicion de este
bloque con proveedores encendidos esta **pendiente de autorizacion** (encender
proveedores tiene coste y abre red, la misma razon que motivo el diseno
100% offline del Bloque 7). El cuello de botella transversal — el anclaje de
evidencia — queda **fuera de alcance** de este bloque: corregirlo exige tocar
`external_ai_shadow.py`/los prompts de extraccion, no la politica de revision.

---

## 6. Tests

| Fichero | Tests | Autor |
|---|---|---|
| `tests/test_relation_review_policy_block8_smoke.py` | **36** | AGENTE-IMPLEMENTADOR (humo) |
| `tests/test_relation_review_policy_block8_full.py` | **75** | AGENTE-TESTS (bateria completa) |
| **Total del bloque** | **111** | |

Ejecutado el 2026-07-21 desde `data-engine/app` con `PYTHONPATH=.`:

```bash
python3 -m pytest tests/test_relation_review_policy_block8_smoke.py \
    tests/test_relation_review_policy_block8_full.py -q
# 111 passed
python3 -m pytest tests -q
# 1380 passed
```

La bateria completa anade, sobre la de humo (que se conserva intacta):
invariante estatica de "no importa vias de escritura/red/reloj" (analisis AST
del fuente de `review_policy.py`), invariante de dominio de `label` (nunca
fuera de las dos etiquetas, nunca solapa `CONSENSUS_STATES` ni vocabulario
prohibido), tabla de verdad exhaustiva "una condicion a la vez" con frontera
exacta del umbral, transparencia de metricas, fail-closed generico ante
entradas corruptas, determinismo/inmutabilidad, logica PASS/FAIL/NOT_MEASURED
de los gates con `MatchResult` sinteticos, vocabulario cerrado del dictamen, y
un *mutation check* especifico de la medicion (1 falso-aceptado exacto de 25
para detectar la inversion de `expected_decision == "ACCEPT"` por `!=`).

**Mutation checks:** 9 mutantes verificados manualmente por el AGENTE-TESTS
(mutar, confirmar que el test cae, revertir — no se mutan ficheros de
produccion desde dentro de un test de pytest), incluido el mutante clave: la
inversion del calculo de falsos-aceptados (`==` por `!=` en la condicion de
`expected_decision`).

---

## 7. Alcance del bloque

**Ficheros que anade:**

- `relations/review_policy.py`
- `relations/benchmark/review_policy_metrics.py`
- `tests/test_relation_review_policy_block8_smoke.py`
- `tests/test_relation_review_policy_block8_full.py`

**Ficheros que NO toca:** nada del Bloque 7 (`relations/benchmark/providers.py`,
`runner.py`, `cli.py`, `metrics.py`, `report.py`, `matching.py`), ni
`relations/ensemble.py`, ni `relations/pipeline.py`, ni `relations/external_ai_shadow.py`,
ni `contracts/**`, ni el ground truth del benchmark, ni ningun fichero
compartido de otros bloques del programa.

**Limite explicito:** la politica de este bloque **no se activa en
produccion**. No existe ningun punto de integracion entre
`relations.review_policy` / `relations.benchmark.review_policy_metrics` y
`review/` (el modulo que si decide sobre ingesta real) o cualquier *writer*.
Activarla exigiria una decision explicita y separada del Organizador, ademas
de que la medicion de este mismo bloque diga que hay base de seguridad para
ello — cosa que, hoy, no dice.
