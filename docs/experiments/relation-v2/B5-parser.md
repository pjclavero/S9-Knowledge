# B5 — Parser sintáctico opcional (spaCy / Stanza) tras interfaz

**Rama:** `feat/relation-engine-v2-hybrid` · **Base del bloque:** `622fb8c` (B4) ·
**Ficheros:** `relations/syntax.py`, `relations/pipeline.py`,
`tests/test_relation_v2_b5_parser.py`

**Resultado del bloque: METRIC-NEUTRAL por diseño.** B5 no pretende mejorar ninguna
métrica: aporta la *infraestructura* para enchufar un analizador fuerte si algún día
está disponible, sin convertirlo en dependencia y sin cambiar el comportamiento por
defecto. **La comparación de calidad heurístico-vs-spaCy/Stanza queda HONESTAMENTE
DIFERIDA**: ninguna de las dos librerías está instalada en este entorno y el programa
prohíbe descargar nada, así que **no se afirma que spaCy mejore nada**. No hay número
que reportar porque no se ha podido medir.

---

## 1. Qué se ha construido

### 1.1. `LazyModelSyntaxAnalyzer` — proveedor fuerte, perezoso y sin descargas
Envuelve spaCy o Stanza detrás de la interfaz `SyntaxAnalyzer` ya existente.

- **Import perezoso real:** la librería pesada no se importa al cargar
  `relations.syntax`, ni al construir el analizador, ni siquiera al preguntar
  `available()` (usa `importlib.util.find_spec`, que no ejecuta el paquete).
- **Cero descargas:** si la librería falta, o el modelo no está en disco, se lanza
  `SyntaxProviderUnavailable` con un mensaje claro. Stanza se instancia con
  `download_method=None`, que desactiva su auto-descarga. No hay `spacy download`,
  ni `subprocess`, ni `pip`, ni `urllib`/`requests`/`socket` en el módulo.
- **Trazabilidad:** `provider` identifica el motor y `notes` registra versión de la
  librería y modelo concreto usado.
- **Modelos por defecto:** `es_core_news_sm` / `en_core_web_sm` (spaCy), `es`/`en`
  (Stanza). Configurables; nunca instalados automáticamente.

### 1.2. `FallbackSyntaxAnalyzer` — degradación segura
Intenta un primario y, si no está disponible **o revienta por cualquier motivo**, sirve
el heurístico. Nunca propaga la excepción y nunca descarga. La procedencia real queda
en `SyntaxAnalysis.provider` + una nota que dice qué primario se pidió y por qué se
degradó, de modo que siempre es auditable **quién sirvió de verdad el análisis**.

### 1.3. `CachingSyntaxAnalyzer` — un único análisis por segmento
Memoriza por clave `(texto, idioma)` con tope de entradas (`maxsize=512`). Como el
heurístico es una función pura y determinista, cachear **no puede alterar ninguna
métrica**: el resultado cacheado es idéntico al directo (verificado por test).

### 1.4. Fábrica
`get_analyzer(provider, *, fallback=False, cache=False, **kwargs)`.

- El **contrato histórico se conserva**: `get_analyzer("spacy")` sigue lanzando
  `SyntaxProviderUnavailable` cuando la librería no está (los tests previos de
  `test_relation_syntax.py` siguen verdes sin tocarlos).
- `fallback=True` → nunca lanza, degrada al heurístico.
- `cache=True` → envuelve en caché.
- `get_default_analyzer()` devuelve el analizador **compartido** del pipeline:
  heurístico + caché. Es lo único que cambia en `pipeline.py` (2 líneas): antes se
  construía un `HeuristicSyntaxAnalyzer` nuevo por segmento.

---

## 2. A/B — comprobación de neutralidad métrica

Corpus B1 congelado, arnés único `relations/benchmark/`, mismos umbrales.

| Métrica | selector v1 (base) | selector v2 (motor v2) |
|---|--:|--:|
| `predicate_correct` | 0.2093 | **0.8140** |
| `direction_correct` | 0.6279 | **0.9302** |
| `temporal_correct` | 0.4419 | **0.8837** |
| `strict_predicate.f1` | 0.1698 | **0.6604** |
| `evidence_correct` | 0.9070 | 0.9302 |
| `offsets_correct` | 0.9302 | 0.9535 |
| `decision_correct` | 0.3023 | 0.3023 |
| `global_existence.f1` (pair_F1) | 0.8113 | 0.8113 |

**Estas cifras son EXACTAMENTE las de B4.** B5 no mueve ni una décima, que es
justo lo que se buscaba: la infraestructura del parser entra sin efecto observable.
`deterministic=True`, `verdict = APTO PARA CONTINUAR EN MODO SOMBRA`,
`providers local=NOT_EXECUTED external=NOT_EXECUTED`, `llamadas=0`.

> **Caveat permanente del programa:** n=54 con dev==test. El 0.814 de predicado es un
> techo en-corpus; el rango honesto sigue siendo **[0.42, 0.81]** (ver B2). B5 no
> cambia nada de esto.

---

## 3. Pruebas — 23 tests (2 omitidos a propósito)

`tests/test_relation_v2_b5_parser.py`. Cubren: pereza real (spaCy/Stanza no aparecen
en `sys.modules`), errores claros de motor desconocido y de texto no-str, fallo
explícito sin dependencia, **auditoría estática sobre el AST** (ninguna llamada
`download/urlopen/check_call/run/system`, ningún import de `subprocess`/`pip`/`urllib`/
`requests`/`socket`, y `stanza.Pipeline` construido con `download_method=None`),
fallback que no propaga ni aunque el primario lance `RuntimeError`, caché (una sola
llamada por segmento, distinción por idioma, `maxsize`, `cache_clear`, resultado
idéntico al directo) y neutralidad del default.

Los **2 omitidos** son los que ejercitarían la conversión real de spaCy/Stanza a
`SyntaxAnalysis`: están marcados `skipif` y **se ejecutarán solo cuando la dependencia
exista**. Se declaran como omitidos, no como aprobados.

> Nota de honestidad: la primera versión del test de auditoría estática buscaba la
> cadena `"spacy download"` en el fichero y **fallaba contra su propio docstring**.
> Se rehízo sobre el AST, que ignora comentarios y prosa y comprueba el código real.

### Pruebas de mutación — 5 mutantes, 5 muertos
Cada mutante se aplicó **por separado** sobre el fichero limpio y se revirtió después
(hash de control verificado al final: el fichero vuelve byte a byte a su estado bueno).

| # | Mutación | Tests que caen |
|---|---|--:|
| M1 | `FallbackSyntaxAnalyzer` propaga en vez de degradar | 4 |
| M2 | `CachingSyntaxAnalyzer` no memoriza | 1 |
| M3 | Stanza con `download_method='download_resources'` (auto-descarga ON) | 1 |
| M4 | `import socket` a nivel de módulo | 1 |
| M5 | `pipeline.py` vuelve a construir un analizador por segmento | 1 |

Suite completa del repo: **1578 passed, 2 skipped**.

---

## 4. Comparación de calidad/RAM/CPU — DIFERIDA, no estimada

No se reporta ninguna cifra de calidad, memoria o latencia de spaCy/Stanza porque
**no se han ejecutado**: no están instalados y el programa prohíbe descargar modelos
y usar red. Inventar un "spaCy mejoraría un X%" sería exactamente el tipo de dato
fabricado que este programa prohíbe.

Para cerrar la comparación en el futuro haría falta, con autorización explícita:
instalar `spacy` + `es_core_news_sm` en un entorno aislado, correr el A/B con
`get_analyzer("spacy", fallback=True, cache=True)` inyectado en el pipeline, y medir
(a) las mismas métricas del arnés, (b) RSS máximo y (c) segundos por documento. Hasta
entonces el default es y sigue siendo el heurístico.

---

## 5. Seguridad y reversibilidad
Sin red, sin escritura en Neo4j, sin ingesta, sin secretos, sin descargas. Determinismo
intacto. El comportamiento por defecto es idéntico al de B4, así que revertir B5 es
quitar el fichero de tests y las tres clases: no hay estado ni migración que deshacer.

---

## 6. Auditoría independiente y corrección supervisada

El revisor independiente emitió **`DICTAMEN DEL REVISOR: CONFORME`** sobre `dcc9e1c`,
verificando por su cuenta las 10 afirmaciones del bloque. Lo más sólido de su
verificación (reproducido por él, no afirmado por mí):

- **Neutralidad métrica exacta**: diff estructural completo de los JSON del benchmark
  entre `622fb8c` y `dcc9e1c` → **0 diferencias** salvo `code_sha` y timings;
  `result_hashes` de las 16 fuentes **byte a byte iguales**.
- **Cero red demostrada en ejecución**: corrida completa del benchmark con
  `socket.socket` / `create_connection` / `getaddrinfo` parcheados a excepción →
  `exit 0` y hashes idénticos.
- **`**kwargs` no puede reactivar la descarga de Stanza**: probó el vector de
  sobrescritura (`get_analyzer("stanza", download_method="download_resources")`) →
  `TypeError`. El parámetro está fijado en el código, no difundido.

Pero **refutó parcialmente la afirmación 8**: de 8 mutantes nuevos que probó,
**4 sobrevivían** a los 1578 tests. Su conclusión, que acepto: la frase "garantías
verificadas por mutación" describía una red de seguridad más fuerte de la que existía.

### Correcciones aplicadas (commit de corrección supervisada)

| Defecto | Gravedad | Corrección |
|---|---|---|
| **D1** Fallback enmascaraba fallos: el resultado degradado traía `degraded=False` y era **indistinguible en campos estructurados** de una corrida sana; además capturaba `MemoryError` | MEDIA-ALTA | El fallback marca ahora `degraded=True` (señal legible por máquina, no una cadena en `notes`) y expone contadores `degradations` / `last_error`. `MemoryError`, `KeyboardInterrupt` y `SystemExit` **se propagan**: un OOM no es "proveedor roto" y degradar en silencio lo ocultaría documento tras documento |
| **D2** Caché de **solo inserción**: al llenarse dejaba de insertar y nunca desalojaba; en un proceso longevo se congelaba con los primeros 512 segmentos y la tasa de acierto tendía a 0, quedando solo el coste de memoria | MEDIA | Política **LRU real** sobre `OrderedDict`: un acierto renueva la entrada y al desbordar se desaloja la menos usada. Contador `evictions`. `maxsize < 1` es error |
| **D3 / M6** Los tests de pereza eran **vacuos**: afirmaban `"spacy" not in sys.modules` en un entorno donde spaCy no puede estar. El escenario que la invariante protege no se ejercitaba | MEDIA | Test que **fabrica un paquete `spacy` falso que explota al importarse**, lo pone en `sys.path` y comprueba que `available()` devuelve `True` sin importarlo |
| **M12** `FallbackSyntaxAnalyzer.available()` siempre `True` sobrevivía | — | Test con fallback no disponible |
| **M13** `cache=True` de la fábrica sin cobertura | BAJA | Test de envoltura + acierto efectivo |
| **M14 / D5** La auditoría "cero red" era una lista negra de nombres: bastaba partir el literal (`'url'+'open'`) para atravesarla | BAJA | La auditoría AST exige ahora que `import_module` reciba un **literal de una lista blanca** (`spacy`, `stanza`, `importlib.util`) y que `getattr` no use nombres calculados |

**Verificación de la corrección (hecha por mí, supervisor):** los 6 mutantes
correspondientes **mueren** (M6 → 2 fallos, M12 → 1, D1-degraded → 1, D1-MemoryError → 1,
D2-solo-inserción → 4, D2-LRU-sin-renovar → 1). Suite completa: **1588 passed, 2 skipped**.
Y lo esencial: los JSON del benchmark tras la corrección son **idénticos** a los de
`dcc9e1c` (v1 y v2, `result_hashes` incluidos) → **la corrección sigue siendo
metric-neutral**, no compra métricas.

**D4 (retención global de texto crudo, sin TTL ni API pública de reset) y D7
(el objeto cacheado se comparte por identidad) quedan ABIERTOS**, documentados aquí y
no corregidos: afectan al uso en un proceso de producción longevo, no al banco offline,
y tocarlos ahora saldría del alcance de B5. **Deben resolverse antes de que este código
pase de infraestructura en sombra a ruta de producción.**

## 7. Estado
**B5 CONFORME** como bloque de infraestructura: interfaz + fallback seguro + caché LRU +
fábrica, metric-neutral, con las garantías offline verificadas por mutación **y por una
auditoría independiente que encontró y forzó a corregir cuatro huecos reales**. La
comparación con parser fuerte queda abierta y explícitamente marcada como no medida.
Siguiente: **B6 — consenso y abstención** (`decision_correct` sigue en 0.3023, es la
métrica que menos se ha movido en todo el programa).
