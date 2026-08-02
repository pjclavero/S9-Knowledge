# Clasificación de SKIPS — suite completa

**Rama:** `integration/v3-final-core-validation`

Comandos ejecutados (suite completa, `-rs`, sin filtros):

```
cd data-engine/app && python3 -m pytest -q -rs -p no:randomly
  -> 4648 passed, 26 skipped, 495 warnings in 97.51s   (exit 0)

cd viewer && python3 -m pytest -q -rs
  ->  381 passed,  1 skipped,  13 warnings in 14.88s   (exit 0)
```

**Total: 5029 passed, 27 skipped.** Coincide exactamente con la base declarada de 5029.
(Medición tomada **antes** de añadir `test_knowledge_v3_e2e_global.py`, para que sea comparable con
la base. Con el fichero nuevo: 4648+39 = 4687 passed, 26+2 = 28 skipped, 2 xfailed en el árbol
`data-engine`.)

Categorías: **(a)** deliberado por diseño · **(b)** integración externa · **(c)** Docker ·
**(d)** credencial ausente · **(e)** ACCIDENTAL.

---

## 1. Tabla completa

| # | fichero::test | motivo literal | cat. | comentario |
|---|---|---|---|---|
| 1 | `test_knowledge_v3_extraction_ollama.py:242` | `humo real contra Ollama: se activa con S9K_LIVE_OLLAMA=1` | **b** | Humo contra Ollama real. Puerta explícita por variable de entorno; el resto del fichero prueba el extractor con transporte doble y sí corre. |
| 2 | `test_knowledge_v3_extraction_ollama.py:248` | ídem | **b** | ídem |
| 3 | `test_knowledge_v3_multimodal_real.py:118` | `Tesseract no está instalado; configura S9K_TESSERACT_CMD` | **b** | Binario OCR del sistema ausente. Detectado en runtime (`pytest.skip` en fixture, línea 103), no por variable. |
| 4 | `test_knowledge_v3_multimodal_real.py:146` | ídem | **b** | ídem |
| 5 | `test_knowledge_v3_multimodal_real.py:161` | ídem | **b** | ídem |
| 6 | `test_knowledge_v3_multimodal_real.py:311` | ídem | **b** | ídem |
| 7 | `test_knowledge_v3_multimodal_real.py:423` | ídem | **b** | ídem |
| 8 | `test_knowledge_v3_multimodal_real.py:462` | ídem | **b** | ídem |
| 9 | `test_knowledge_v3_providers_nvidia.py:339` | `humo real de pago: activar con S9K_LIVE_NVIDIA=1 y S9K_NVIDIA_API_KEY` | **d** | Requiere API key **de pago**. Doble puerta (flag + credencial). |
| 10 | `test_knowledge_v3_providers_nvidia.py:347` | ídem | **d** | ídem |
| 11 | `test_knowledge_v3_providers_ollama.py:303` | `humo real: activar con S9K_LIVE_OLLAMA=1` | **b** | ídem que 1–2, en el módulo de proveedores. |
| 12 | `test_knowledge_v3_providers_ollama.py:312` | ídem | **b** | ídem |
| 13 | `test_knowledge_v3_providers_ollama.py:333` | ídem | **b** | ídem |
| 14 | `test_knowledge_v3_writer_neo4j_real.py:464` | `Neo4j real efimero: activar con S9K_WRITER_NEO4J_REAL=1` | **c** | `pytestmark` de módulo (línea 45) + arranque de contenedor Neo4j efímero (líneas 86–109: `pytest.skip("Docker no esta disponible…")`). |
| 15 | `…:486` | ídem | **c** | ídem |
| 16 | `…:499` | ídem | **c** | ídem |
| 17 | `…:522` | ídem | **c** | ídem |
| 18 | `…:537` | ídem | **c** | ídem |
| 19 | `…:553` | ídem | **c** | ídem |
| 20 | `…:574` | ídem | **c** | ídem |
| 21–23 | `…:585` **(×3)** | ídem | **c** | Test parametrizado, 3 casos. |
| 24 | `…:614` | ídem | **c** | ídem |
| 25 | `test_relation_v2_b5_parser.py:286` | `spaCy no instalado: comparacion diferida` | **b** | Dependencia opcional de análisis sintáctico. Ver §3. |
| 26 | `test_relation_v2_b5_parser.py:298` | `Stanza no instalado: comparacion diferida` | **b** | ídem. Ver §3. |
| 27 | `viewer/tests/browser/test_login_browser.py:22` | `Playwright no instalado: SKIP, no PASS` | **b** | `importorskip` de módulo. El motivo declara explícitamente la intención de no fingir verde. |

---

## 2. Recuento por categoría

| categoría | nº | % |
|---|---|---|
| (a) deliberado por diseño | **0** | 0 % |
| (b) integración externa | **14** | 51,9 % |
| (c) Docker | **11** | 40,7 % |
| (d) credencial ausente | **2** | 7,4 % |
| **(e) ACCIDENTAL** | **0** | **0 %** |
| **total** | **27** | 100 % |

Desglose de (b): Ollama real 5, Tesseract 6, spaCy 1, Stanza 1, Playwright 1.

---

## 3. Sección destacada: ACCIDENTALES

> **No se ha encontrado ni un solo skip accidental.**

Ese resultado no se afirma por lectura de los 27 motivos: un skip accidental casi nunca se declara
como skip. Se han auditado **cuatro** vías por las que se pierde cobertura sin que aparezca una `s`
en la salida de pytest.

### 3.1 Ficheros de test no recogidos por el colector

```
data-engine/app:  118 ficheros recogidos / 122 ficheros test_*.py en disco
```

Los **4 no recogidos** son módulos de **fixtures**, no de pruebas. Verificado contando funciones de
test en cada uno:

| fichero | funciones `test_` |
|---|---|
| `tests/test_knowledge_v3_e2e_fixtures.py` | **0** |
| `tests/test_knowledge_v3_multimodal_fixtures.py` | **0** |
| `tests/test_knowledge_v3_providers_support.py` | **0** |
| `tests/test_knowledge_v3_resolution_fixtures.py` | **0** |

Los cuatro se importan desde otros ficheros y su docstring lo declara
(*"Modulo de fixtures: NO contiene pruebas"*). **Cero cobertura perdida.**

En `viewer`: 25 ficheros recogidos; el único ausente es
`tests/browser/test_login_browser.py`, que está en la tabla como skip nº 27 (`importorskip` de
módulo — sí se recoge, se salta). **Cero cobertura perdida.**

### 3.2 Clases `Test*` con `__init__` (pytest las ignora en silencio)

Búsqueda sobre todo el árbol de tests: **0 coincidencias**. Es la trampa clásica —una clase de test
con constructor no se recoge y pytest **no avisa**— y aquí no se da.

### 3.3 Cuadratura de la aritmética de colección

```
data-engine/app:  4674 tests recogidos  ==  4648 passed + 26 skipped
```

Cuadra exactamente. No hay tests recogidos que desaparezcan de la ejecución (deseleccionados por un
filtro, abortados por un error de colección silencioso, etc.).

### 3.4 Pares `skipif` mutuamente excluyentes

`test_relation_v2_b5_parser.py` define **dos parejas invertidas**:

| líneas | condición | estado hoy |
|---|---|---|
| 92, 102 | `skipif(HAS_SPACY)` — "spaCy instalado: la ruta de ausencia no aplica" | **se ejecutan** (spaCy ausente) |
| 109 | `skipif(HAS_STANZA)` — "Stanza instalado" | **se ejecuta** (Stanza ausente) |
| 286 | `skipif(not HAS_SPACY)` — "comparacion diferida" | **se salta** (nº 25) |
| 298 | `skipif(not HAS_STANZA)` — "comparacion diferida" | **se salta** (nº 26) |

Es un diseño **deliberado**: sea cual sea el entorno, una de las dos ramas corre siempre y la ruta
de ausencia de dependencia queda cubierta. No es un skip accidental; es la mitad complementaria de
un par. (Se clasifica en (b) porque la causa material es una dependencia externa ausente.)

---

## 4. Riesgos que los skips dejan al descubierto

Ningún skip es accidental, pero **11 de 27 (40,7 %) son la escritura real contra Neo4j**. La
consecuencia honesta: en este árbol **el writer sólo está probado en dry-run**. El camino
`apply=True` —transacciones, `idempotency_key`, rollback— no se ejecuta aquí. Es exactamente lo que
la **puerta 7** debe cubrir en VM105 con Docker, y coincide con los dos escenarios que este bloque
marca como `DIFERIDO-puerta7` en `e2e-results.md`.

Los otros dos bloques (Ollama real 5, NVIDIA 2) están **deliberadamente** cerrados en esta corrida:
otro agente tiene los proveedores reservados y Ollama sólo admite una inferencia concurrente.
