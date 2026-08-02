# Reproducibilidad — `PYTHONHASHSEED` ∈ {1, 7, 42, 123}

**Rama:** `integration/v3-final-core-validation`
**Semillas:** `1`, `7`, `42`, `123`
**Veredicto: REPRODUCIBLE.** Ninguna de las tres sondas de hash ni ninguna de las suites
deterministas cambia con la semilla.

---

## 1. Por qué esto se prueba con sondas y no sólo corriendo la suite

`PYTHONHASHSEED` se fija **al arrancar el intérprete**: cambiarlo dentro del proceso en curso no
cambia nada y un test que lo intentase daría un verde vacío. Por eso el patrón que ya existe en el
repo —y que aquí se **reutiliza sin reimplementar**— es una **sonda**: un script que se ejecuta en
un **proceso nuevo** por semilla e imprime **un único sha256** de la serialización canónica de su
artefacto. El test compara las cuatro salidas.

Sondas preexistentes reutilizadas:

- `data-engine/app/tests/reconcile_hashseed_probe.py` — salida del reconciliador
- `data-engine/app/tests/planner_hashseed_probe.py` — `GraphMutationPlan` sellado (4 ramas)

Sonda **añadida** por este bloque (embebida en el test, escrita a `tmp_path` en tiempo de ejecución
para no crear ficheros nuevos en `tests/`):

- **cadena completa** — normalizador → extractor → reconciliador → resolutor → motor → planner →
  ledger → writer en dry-run

La razón de añadir la tercera: las dos existentes cubren **una etapa cada una**. Un orden de
iteración inestable tiene mucho más sitio donde esconderse en la **costura** entre etapas que dentro
de una sola.

---

## 2. Hashes medidos (valores reales, cuatro procesos independientes por sonda)

### 2.1 Reconciliador — `reconcile_hashseed_probe.py`

| semilla | sha256 |
|---|---|
| 1 | `8325f19204fc7eb9836cab6b3f560bf4912ffff3b1a5c97effb2cef56137f3d2` |
| 7 | `8325f19204fc7eb9836cab6b3f560bf4912ffff3b1a5c97effb2cef56137f3d2` |
| 42 | `8325f19204fc7eb9836cab6b3f560bf4912ffff3b1a5c97effb2cef56137f3d2` |
| 123 | `8325f19204fc7eb9836cab6b3f560bf4912ffff3b1a5c97effb2cef56137f3d2` |

**1 hash distinto de 4 ejecuciones.**

### 2.2 Planner (plan sellado) — `planner_hashseed_probe.py`

| semilla | sha256 |
|---|---|
| 1 | `eaff0ac66dbc4cbd31a0224274b365bae0a7edbe11ee052ff7738ff083f98815` |
| 7 | `eaff0ac66dbc4cbd31a0224274b365bae0a7edbe11ee052ff7738ff083f98815` |
| 42 | `eaff0ac66dbc4cbd31a0224274b365bae0a7edbe11ee052ff7738ff083f98815` |
| 123 | `eaff0ac66dbc4cbd31a0224274b365bae0a7edbe11ee052ff7738ff083f98815` |

**1 hash distinto de 4 ejecuciones.**

### 2.3 Cadena completa — sonda nueva (4 textos por la ruta desde bytes)

Entrada: los textos de E2E-01, E2E-03, E2E-04 y `es miembro de`, corridos como cuatro fuentes en la
**misma** corrida (ledger compartido, snapshot reconstruido entre fuentes).
Contenido firmado: `summary` de cada fuente, decisiones con sus `findings` ordenados,
`GraphMutationPlan` completo (**incluye `plan_hash`, `decision_hash` e `idempotency_key`**),
afirmaciones y resultado del writer en dry-run.

| semilla | sha256 |
|---|---|
| 1 | `31621226538dcedfe8b9594b403484d10cadb3f43b290d656c9a0c1d12c0a199` |
| 7 | `31621226538dcedfe8b9594b403484d10cadb3f43b290d656c9a0c1d12c0a199` |
| 42 | `31621226538dcedfe8b9594b403484d10cadb3f43b290d656c9a0c1d12c0a199` |
| 123 | `31621226538dcedfe8b9594b403484d10cadb3f43b290d656c9a0c1d12c0a199` |

**1 hash distinto de 4 ejecuciones.**

**Por qué importa que el plan entre en el hash:** el plan se **sella**. El operador confirma el
`plan_hash` **a mano** antes de un `apply`, y la `idempotency_key` es lo que impide que un plan
reaplicado escriba dos veces. Si el orden de iteración de un `set` se colase en esa serialización,
dos procesos con distinta semilla firmarían el **mismo** plan con hashes distintos: la confirmación
del operador dejaría de significar nada y la idempotencia se rompería entre reinicios del writer.

---

## 3. Suites ejecutadas con las cuatro semillas

### 3.1 Subconjunto fijado (evidencia principal)

16 ficheros del núcleo V3, **lista explícita y cerrada** — inmune a que otros agentes añadan
ficheros al árbol mientras se mide:

```
test_knowledge_v3_contracts.py        test_knowledge_v3_ledger.py
test_knowledge_v3_extraction.py       test_knowledge_v3_writer.py
test_knowledge_v3_semantic.py         test_knowledge_v3_e2e.py
test_knowledge_v3_reconcile.py        test_knowledge_v3_e2e_global.py
test_knowledge_v3_reconcile_validation.py   test_knowledge_v3_multimodal_core.py
test_knowledge_v3_resolution.py       test_knowledge_v3_review_export.py
test_knowledge_v3_engine.py           test_knowledge_v3_negation.py
test_knowledge_v3_engine_gold.py      test_knowledge_v3_planner_hardening.py
```

| semilla | resultado |
|---|---|
| 1 | `1303 passed, 2 skipped, 2 xfailed in 57.90s` |
| 7 | `1303 passed, 2 skipped, 2 xfailed in 57.93s` |
| 42 | `1303 passed, 2 skipped, 2 xfailed in 58.59s` |
| 123 | `1303 passed, 2 skipped, 2 xfailed in 58.58s` |

**Idéntico en las cuatro**, incluidos los recuentos de skip y de xfail.

### 3.2 Árbol `data-engine/app` completo

| semilla | resultado |
|---|---|
| 1 | `4729 passed, 28 skipped, 3 xfailed in 105.98s` |
| 7 | `4754 passed, 28 skipped, 6 xfailed in 103.75s` |
| 42 | `4754 passed, 28 skipped, 6 xfailed in 103.08s` |
| 123 | `4754 passed, 28 skipped, 6 xfailed in 104.86s` |

**La diferencia de `seed=1` NO es un fallo de reproducibilidad.** Es rotación del árbol: la corrida
con semilla 1 arrancó mientras otros agentes de la validación seguían añadiendo ficheros de test a
`tests/`, y las tres siguientes vieron ya el árbol con 25 tests y 3 xfail más. Evidencias de que la
causa es esa y no la semilla:

1. las tres corridas **posteriores** (7, 42, 123) son **exactamente iguales** entre sí;
2. el **número de skips es 28 en las cuatro**, sin una sola diferencia;
3. el subconjunto **fijado** de §3.1, que no puede crecer, es idéntico en las cuatro.

Lo honesto es decir que el árbol completo se midió sobre una base en movimiento y que la afirmación
de reproducibilidad se apoya en §2 y §3.1.

---

## 4. Qué queda FUERA y por qué

| fuera del alcance | motivo |
|---|---|
| `stage_latency_ms`, `latency_ms`, `duration_ms` del informe de reconciliación | Son medidas de **reloj** (`time.perf_counter`), no resultados. Varían entre ejecuciones por definición, con o sin semilla. Excluidos explícitamente del hash de la sonda de cadena. |
| Los 11 tests de `test_knowledge_v3_writer_neo4j_real.py` | Requieren Docker + Neo4j efímero. No se ejecutan en este árbol (ver `skips-classification.md`). La reproducibilidad de la escritura **real** es materia de la **puerta 7**. |
| Los 5 tests de humo contra Ollama real y los 2 contra NVIDIA | Salida de un **modelo generativo remoto**: no determinista por naturaleza, y además los proveedores están reservados por otro agente. El carril real lo mide el coordinador en la **puerta 5**. |
| Los 6 tests de `test_knowledge_v3_multimodal_real.py` | Dependen del binario **Tesseract** del sistema, cuya versión y modelos condicionan la salida. No instalado aquí. |
| `test_relation_v2_b5_parser.py:286,298` | Dependen de spaCy / Stanza, cuyos modelos estadísticos no forman parte del núcleo determinista. |
| `viewer/tests/browser/test_login_browser.py` | Navegador real (Playwright): temporización y renderizado fuera de control del hash. |

Un apunte relevante: **`pytest-randomly` NO está instalado** (comprobado con `importlib.util`). El
orden de ejecución de la suite es, por tanto, estable de por sí; el flag `-p no:randomly` usado en
algunas corridas fue un no-op. La reproducibilidad medida aquí es la del **contenido** de los
artefactos, no la del orden de los tests.

---

## 5. Veredicto

**REPRODUCIBLE.**

- 3 sondas × 4 semillas × proceso nuevo = **12 ejecuciones**, **3 hashes distintos en total**
  (uno por sonda), es decir cero variación intra-sonda.
- El artefacto que el operador firma a mano (`plan_hash`) y el que garantiza la no-duplicación
  (`idempotency_key`) están **dentro** del hash verificado.
- El subconjunto determinista fijado de 1303 tests da resultado idéntico con las cuatro semillas.
- No se ha encontrado ninguna dependencia del orden de iteración de `set`/`dict` en ninguna etapa de
  la cadena.

Cobertura de la verificación en la suite: los tests
`test_la_ruta_completa_es_identica_con_cualquier_pythonhashseed` y
`test_las_sondas_de_semilla_ya_existentes_siguen_verdes`, en
`data-engine/app/tests/test_knowledge_v3_e2e_global.py`.
