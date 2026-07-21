# Informe de validacion — Bloque 8: Calibracion de la politica de revision de relaciones

**Fecha:** 2026-07-21
**Rama:** `feat/relation-review-policy-calibration-v1`
**Worktree:** `/home/ia02/worktrees/relation-review-policy-calibration-v1`
**Base:** Bloque 7 integrado (benchmark de relaciones reejecutado, ronda 4)
**Modulos nuevos:** `relations/review_policy.py`, `relations/benchmark/review_policy_metrics.py`
**Estado:** MODO SOMBRA. Sin commit, sin push, sin PR desde este agente de
documentacion. Sin activacion en produccion.
**Tests propios del bloque:** **111** (36 de humo del AGENTE-IMPLEMENTADOR +
75 completos del AGENTE-TESTS)
**Resultados publicados en:** [`docs/51-relation-review-policy-calibration.md`](../../51-relation-review-policy-calibration.md)

---

## 1. Objetivo

Calibrar una **politica** que identifique, sobre resultados YA CALCULADOS por
el ensemble/consenso de los Bloques 6/7, un subconjunto de relaciones de ALTA
confianza que **podria** saltarse la revision humana, y **medir** con datos
reales cuan segura seria esa reduccion. El bloque **no** decide activar nada:
produce una recomendacion de clasificacion y una medicion de seguridad, en
modo sombra puro.

## 2. Encuadre de seguridad (verificado en el codigo, no asumido)

Tres garantias se verificaron directamente, no se dieron por buenas:

1. **Aislamiento de escritura.** Se busco en todo el repositorio quien importa
   el paquete `relations`; el resultado son unicamente ficheros dentro de
   `relations/` y de `tests/`. Ningun fichero de `review/` (que si controla la
   ingesta real, via `review/auto_decider.py` y `review/ingest_approved.py`),
   `cli/` ni ningun *writer* importa `relations.review_policy` o
   `relations.benchmark.review_policy_metrics`. El bloque queda, en la
   practica, desconectado de cualquier via de escritura.
2. **Vocabulario prohibido.** El propio modulo levanta `AssertionError` en
   tiempo de import si alguna de sus dos etiquetas (`AUTO_PROPOSABLE`,
   `REVIEW_REQUIRED`) coincidiera con vocabulario de aprobacion/escritura
   (`APPROVED`, `WRITE`, `APPLY`, `COMMIT`, `MERGE`, `ACCEPT`...) o con
   cualquier `CONSENSUS_STATES` canonico, y `ReviewPolicyOutcome.__post_init__`
   repite la comprobacion en cada instancia como defensa en profundidad.
3. **Fail-closed real.** `classify_for_review` valida cada campo de entrada
   uno a uno y devuelve `REVIEW_REQUIRED` — nunca lanza una excepcion no
   controlada — ante cualquier dato ausente, de tipo incorrecto o coleccion no
   iterable. Solo una `ReviewPolicyConfig` invalida (error de programacion,
   no un dato de entrada dudoso) falla ruidosamente, a proposito.

## 3. Diseno verificado

`ReviewPolicyConfig` (frozen, versionada: `auto_propose_score_threshold=0.90`,
`min_providers_present=1`, `config_hash` sha256 truncado del `to_dict()`)
alimenta `classify_for_review`, que exige **las cinco** condiciones a la vez
para etiquetar `AUTO_PROPOSABLE`: `state == STRONG_CONSENSUS`,
`providers_present >= min_providers_present`, `score >= umbral`,
`len(conflicts) == 0`, `has_evidence is True`. Cualquier condicion que falle
produce `REVIEW_REQUIRED` con la razon exacta y las senales de entrada
conservadas para auditoria.

**Por que "REVIEW_REQUIRED" y no "HUMAN_REQUIRED".** `HUMAN_REQUIRED` ya es un
estado de consenso canonico de `external_ai.models.CONSENSUS_STATES` que usa
`relations.ensemble`. Reutilizar ese mismo literal como *label* de politica
solaparia dos conceptos distintos (estado de consenso vs. recomendacion de
revision); el diseno del Bloque 8 lo prohibe explicitamente y usa un nombre
disjunto.

`relations/benchmark/review_policy_metrics.py` reutiliza el runner y el
matching **reales** del Bloque 7 (sin modificarlos) para calcular, sobre el
subconjunto `AUTO_PROPOSABLE`: `precision`, `false_accept_rate`, `coverage` y
`sample_size` — publicados siempre, incluso en 0 o en el peor caso.

## 4. Gates de seguridad (verificados en el codigo)

| Gate | Umbral | Tipo |
|---|---|---|
| `review_policy_false_accept_rate` | <= 0.02 | **DURO** |
| `review_policy_precision` | >= 0.98 | **DURO** |
| `review_policy_sample_size` | >= 20 para que los dos anteriores sean PASS/FAIL | **DURO** |
| `review_policy_coverage` | ninguno | **SOLO INFORMATIVA** (`hard: False`) |

Con `sample_size < 20`, los gates de FAR/precision son `NOT_MEASURED` —
**salvo** que ya haya algun falso-aceptado observado, en cuyo caso son `FAIL`
incondicional (`strict_small_sample`, el mismo patron que el B3 del Bloque 7
aplico al transporte de proveedor): una muestra insuficiente nunca disculpa un
dano ya medido.

`coverage` se deja fuera de los gates duros **a proposito**: forzar una
cobertura minima invertiria el incentivo de seguridad, empujando a bajar el
umbral de score o a relajar alguna condicion dura solo para "cubrir mas". La
unica forma de que la politica "apruebe" es que lo que proponga sea correcto,
no que proponga mucho.

## 5. Resultado real offline — medido, sin maquillar

Artefacto: `/home/ia02/.claude/jobs/d7a6832b/tmp/b8_review_policy_offline.json`
(corpus real, 16 fuentes / 54 relaciones, modos `baseline1` y
`ensemble_offline`, proveedores apagados).

| Modo | `sample_size` | Cobertura | Gates | Dictamen |
|---|---|---|---|---|
| `baseline1` | 0 | 0 % | `NOT_MEASURED` (los tres duros) | **"POLITICA DE REDUCCION: NO CALIBRABLE (COBERTURA INSUFICIENTE)"** |
| `ensemble_offline` | 0 | 0 % | idem | idem |

**Causa raiz, verificada en `relations/ensemble.py` (`_derive_state`), no
supuesta:** `STRONG_CONSENSUS` exige estructuralmente `providers_present >= 1`
y `has_evidence`, en las dos ramas (positiva y negativa) que pueden llegar a
ese estado. En modo offline no hay proveedor alguno (`local_llm` y
`external_ai` en `NOT_EXECUTED`, cero llamadas), asi que `providers_present`
es siempre 0: `STRONG_CONSENSUS` es **inalcanzable**, y por tanto tambien
`AUTO_PROPOSABLE`, sin corroboracion real de al menos un proveedor.

**Conclusion honesta y segura del bloque:** con la calidad actual del
pipeline, **nada puede saltarse la revision humana de forma segura; no se
justifica reducir la supervision.** Esto es un resultado **valido**, medido
con el mismo rigor que el resto del programa, no un fracaso del bloque.

## 6. Enlace con el Bloque 7 — prediccion fundamentada, SEGUIMIENTO

El Bloque 7 si midio con proveedores reales sobre la misma submuestra de 6
fuentes (`docs/50-relation-benchmark-results.md`, §12/§12A):

| Proveedor | Llamadas respondidas | Invalidas | `results_strong` |
|---|---|---|---|
| Ollama (`qwen2.5:7b`, local) | 27 | **18/27 (66,7 %)** | **0** |
| NVIDIA (`meta/llama-3.3-70b-instruct`, alojado) | 27 | **27/27 (100 %)** | **0** |

En ambos, `results_strong = 0`: ninguna evaluacion real de proveedor produjo
un veredicto lo bastante valido como para llegar a `STRONG_CONSENSUS`. Es
razonable esperar que una pasada de este bloque con proveedores encendidos
tambien de una cobertura auto-proponible cercana a 0 %, porque el cuello de
botella comun es el **anclaje de evidencia** (offsets correctos / campo
`evidence_text` bien poblado), que falla sistematicamente en los dos
proveedores probados hoy. **Esto es una prediccion basada en datos ya
medidos por el Bloque 7, no algo ejecutado por el Bloque 8**: la medicion con
proveedores reales queda marcada como **SEGUIMIENTO, pendiente de
autorizacion** (encender proveedores tiene coste medido y abre red — la misma
razon que motivo el diseno 100 % offline del Bloque 7). El anclaje de
evidencia en si queda **fuera de alcance** de este bloque.

## 7. Tests — verificados ejecutando pytest el 2026-07-21

```bash
cd data-engine/app
PYTHONPATH=. python3 -m pytest tests/test_relation_review_policy_block8_smoke.py -q
# 36 passed
PYTHONPATH=. python3 -m pytest tests/test_relation_review_policy_block8_full.py -q
# 75 passed
PYTHONPATH=. python3 -m pytest tests/test_relation_review_policy_block8_smoke.py \
    tests/test_relation_review_policy_block8_full.py -q
# 111 passed
PYTHONPATH=. python3 -m pytest tests -q
# 1380 passed
```

La bateria de 75 (AGENTE-TESTS) complementa, sin sustituir, la de 36 de humo
(AGENTE-IMPLEMENTADOR, que se conserva intacta) con: invariante estatica AST
de "no importa vias de escritura/red/reloj" en el fuente de
`review_policy.py`; invariante de dominio de `label`; tabla de verdad
exhaustiva "una condicion a la vez" con frontera exacta del umbral;
transparencia de metricas; fail-closed generico; determinismo/inmutabilidad;
logica PASS/FAIL/NOT_MEASURED de los gates; vocabulario cerrado del dictamen;
y un *mutation check* de la medicion con conteo exacto conocido (1
falso-aceptado de 25).

**9 mutantes** verificados manualmente (editar, confirmar fallo del test,
revertir — nunca dentro de la propia sesion de pytest), incluido el mutante
clave: invertir el calculo de falsos-aceptados (`==` por `!=` sobre
`expected_decision == "ACCEPT"`).

## 8. Alcance — verificado, no solo declarado

**Anade:** `relations/review_policy.py`,
`relations/benchmark/review_policy_metrics.py`,
`tests/test_relation_review_policy_block8_smoke.py`,
`tests/test_relation_review_policy_block8_full.py`.

**No toca:** ningun fichero del Bloque 7 (`providers.py`, `runner.py`,
`cli.py`, `metrics.py`, `report.py`, `matching.py` de
`relations/benchmark/`), ni `relations/ensemble.py`, ni
`relations/pipeline.py`, ni `relations/external_ai_shadow.py`, ni
`contracts/**`, ni el ground truth del benchmark, ni ningun fichero
compartido de otros bloques del programa. Verificado con `git status`/lectura
directa de los ficheros modificados en el worktree: solo los 4 listados
arriba, mas los 2 documentos de este informe.

**Limite:** la politica **no se activa en produccion**. No existe integracion
entre este bloque y `review/` (el modulo que si decide sobre ingesta real) ni
con ningun *writer*. Activarla requeriria decision explicita del Organizador
y, ademas, que una medicion futura (con proveedores reales) mostrara base de
seguridad para ello — cosa que la medicion actual, offline, no muestra.

## 9. Que verifico este agente de documentacion, y que queda como limitacion declarada

**Verificado directamente contra codigo y artefactos** (no aceptado de
segunda mano):

- Lectura completa de `relations/review_policy.py` y
  `relations/benchmark/review_policy_metrics.py`.
- Lectura de `_derive_state` en `relations/ensemble.py` para confirmar que
  `STRONG_CONSENSUS` exige `providers_present >= 1` y `has_evidence`
  estructuralmente.
- Busqueda de importadores de `relations` en todo el repositorio para
  confirmar el aislamiento de escritura.
- Lectura del artefacto `b8_review_policy_offline.json` completo (ambos
  modos).
- Ejecucion de la bateria de tests del bloque (111) y de la suite completa de
  `data-engine/app/tests` (1380 passed) el 2026-07-21.
- Lectura de `docs/50-relation-benchmark-results.md` §12/§12A para las cifras
  reales de Ollama (18/27 invalidas) y NVIDIA (27/27 invalidas) citadas como
  base de la prediccion del §6.

**Limitacion / seguimiento declarado, no ejecutado por este bloque:**

- La medicion de este bloque con proveedores reales encendidos esta
  **pendiente de autorizacion** — no se ha ejecutado; lo que se documenta en
  §6 es una prediccion fundamentada en datos ya medidos por el Bloque 7, no
  un resultado de este bloque.
- El anclaje de evidencia (offsets/`evidence_text`) que explica por que
  ningun proveedor probado hoy alcanza `results_strong > 0` es el cuello de
  botella transversal del programa y queda **fuera de alcance** de este
  bloque: corregirlo exigiria tocar `external_ai_shadow.py` o los prompts de
  extraccion, no la politica de revision.
