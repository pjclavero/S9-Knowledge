# Encargo a equipo externo — `ProposalReconciler`

Fecha: 2026-07-29 · Repositorio: `pjclavero/S9-Knowledge` · Rama base:
`feat/knowledge-v3-redesign`

Este documento es **autocontenido**: contiene todo lo necesario para escribir el
código sin haber participado en el proyecto. Léelo entero antes de tocar nada.

**Reparto de trabajo.** Vosotros implementáis y entregáis en una rama. Nosotros
revisamos, ejecutamos las pruebas y decidimos la integración. No mergeéis nada.

---

## 1. Qué es este sistema, en un párrafo

S9-Knowledge convierte documentos (texto, PDF, tablas, transcripciones de audio) en
un grafo de conocimiento en Neo4j. La cadena es:

```
fuente → normalización → episodios y fragmentos → extracción → resolución de
identidad → motor local → ledger temporal → GraphMutationPlan → writer → Neo4j
```

**El principio que gobierna todo el diseño:** los extractores y los modelos de
lenguaje **proponen**; solo el **motor local** valida y aprueba; solo el **writer**
escribe, y únicamente planes firmados por el motor. Ningún proveedor externo
—Ollama, NVIDIA, cualquier LLM— puede aprobar ni escribir nada. Esto no es una
recomendación: hay tests de mutación que lo comprueban, y romperlo invalida el
bloque entero.

## 2. Por qué existe este encargo (el problema, medido)

Hoy conviven dos extractores: uno **determinista** (reglas léxicas, alta precisión,
cobertura baja) y uno **semántico** (un LLM guiado por la ontología). Cuando se usan
por separado funcionan. Cuando se usan juntos, el resultado **empeora
catastróficamente**:

| Configuración | Claims correctos | F1 |
|---|--:|--:|
| Determinista solo | 0 | — |
| Semántico solo | **8** | 0.421 |
| **Los dos juntos** | **0** | **0.000** |

Son **los mismos 18 claims** en los dos últimos casos. Lo único que cambia es que
se unen las propuestas de ambos extractores, y al hacerlo se destruyen los ocho
aciertos.

**Causa raíz identificada:** los dos extractores proponen la misma mención (mismo
tramo de texto) con identificadores distintos. El emparejamiento con el gold es uno
a uno, así que adjudica la mención a un solo extractor y los claims del otro se
quedan sin argumentos alineados: `claim_key` devuelve `None` y cuentan como falsos
positivos. De los 43 falsos positivos de menciones, unos 24 los añade la unión y 15
son errores genuinos del modelo — **no es una sola causa**, y conviene no
simplificarlo.

**Vuestro encargo es el componente que arregla esto**: un reconciliador que agrupe
las propuestas equivalentes **antes** de que lleguen al resolutor y al motor.

## 3. La especificación

Está completa en **`docs/v3/21-proposal-reconciler.md`**. Es el documento normativo:
si algo de aquí contradice aquello, manda aquel. Resumen de sus puntos duros:

- **Frontera estricta:** el reconciliador alinea propuestas que señalan **el mismo
  tramo textual** con identificadores distintos. **No** resuelve alias, ni
  pronombres, ni fusiona entidades — eso es del resolutor, que ya existe.
- **Nunca vota.** Si un extractor dice `LEADS` y otro `MEMBER_OF`, se conservan
  ambos como candidatos con su procedencia. Decide el motor.
- **Independencia declarada por familia**, no deducida del modelo: dos LLM distintos
  con el mismo prompt son **una sola familia de evidencia**, porque comparten los
  modos de fallo (está medido: pisaban las mismas 3 de 4 trampas del corpus).
- **Ante la duda, no fusionar.** Un falso negativo cuesta trabajo extra al motor y
  se recupera; un falso positivo mezcla dos hechos distintos y esa información no
  vuelve.
- **Salida canónica y determinista**, con identificadores derivados de hash de
  contenido, nunca de contadores dependientes del orden de ejecución.

### Test de aceptación

```
Con el reconciliador, la unión determinista + semántico debe conservar
al menos los 8 claims correctos que el semántico produce en solitario.
```

Escribidlo **antes** que el código. Si no se cumple, la entrega no vale, por
elegante que sea la implementación.

## 4. Reglas duras (romper una invalida la entrega)

1. **Contratos congelados.** `contracts/knowledge-v3/v1/` y
   `data-engine/app/knowledge_v3/contracts/` **no se tocan**. Ni un campo, ni un
   schema. Lo que no quepa va en `metadata` (única excepción documentada a
   `additionalProperties: false`). Si creéis que hace falta un campo nuevo,
   **paradlo y reportadlo** — no lo añadáis.
2. **No toquéis `ci.yml` ni `pytest.ini`.**
3. **No toquéis el corpus gold** (`benchmarks/datasets/`). Ni para "arreglar" un
   caso que os parezca mal etiquetado: reportadlo.
4. **No uséis el split `heldout`**. Existe, está en el repo, y es un activo de un
   solo uso: mirarlo lo inutiliza. Tampoco el split `negation`, que es la vara de
   otro bloque.
5. **Nada escribe en Neo4j.** El writer se usa siempre en dry-run con driver
   simulado. No añadáis credenciales, URIs ni dependencias de red.
6. **No modifiquéis otros subsistemas.** Si encontráis un defecto en `resolution/`,
   `engine/`, `extraction/` o `writer/`, **no lo parcheéis**: documentadlo con
   fichero y línea en vuestro informe. Varios de esos módulos han pasado revisiones
   adversariales y un cambio lateral rompe garantías que no se ven desde fuera.
7. **Sin `git commit --amend` ni `push --force`.** Commits nuevos encima, siempre.
8. **Sin cifras inventadas.** Si una medición no se ejecutó, se dice que no se
   ejecutó. Un resultado negativo bien medido vale más que un número adornado.

## 5. Alcance de ficheros

**Vuestro, en exclusiva:**

```
data-engine/app/knowledge_v3/reconcile/          (nuevo, todo el paquete)
data-engine/app/tests/test_knowledge_v3_reconcile*.py
docs/v3/23-reconciliador-implementacion.md       (vuestro informe)
```

**Podéis modificar, mínimamente y justificándolo:**

```
data-engine/app/knowledge_v3/pipeline/pipeline.py   (para insertar la etapa)
data-engine/app/knowledge_v3/pipeline/config.py     (para activarla)
```

**Solo lectura:** todo lo demás.

## 6. Entorno y comandos

- **Python 3.13** (es la versión de CI).
- Dependencias: `data-engine/requirements.lock` (fijadas; no añadáis paquetes sin
  justificarlo — el proyecto evita dependencias nuevas por política).
- Los tests se ejecutan **desde la raíz del repositorio**:

```bash
python -m pytest data-engine/app/tests/ -q          # subsistema
python -m pytest -q                                  # todo (usa pytest.ini)
```

- Para ejecutar código del data-engine directamente: `PYTHONPATH=data-engine/app`.
- CI relevante: los jobs `test-data-engine`, `test-combined` y `check-imports`.
  **Deben quedar en verde.** La suite completa está hoy en **4.529 pasados, 9
  saltados**; vuestra entrega debe mantener ese número más vuestros tests, sin
  regresiones.

### Por dónde empezar a leer el código

| Qué | Dónde |
|---|---|
| Contratos (entrada y salida vuestra) | `contracts/knowledge-v3/v1/*.schema.json` y `knowledge_v3/contracts/` |
| Qué produce el extractor | `knowledge_v3/extraction/base.py`, `pipeline.py` |
| Quién consume vuestra salida | `knowledge_v3/resolution/`, `knowledge_v3/engine/` |
| Clave canónica ya existente (reutilizad el criterio, **no lo dupliquéis**) | `knowledge_v3/engine/contradiction.py` |
| Orquestador donde se inserta la etapa | `knowledge_v3/pipeline/pipeline.py` |
| Arnés de medición | `knowledge_v3/benchmarks/harness.py`, `cli.py` |

## 7. Cómo se os va a revisar

Un revisor independiente ejecutará, no leerá. Estos son los criterios exactos, sin
sorpresas:

1. **El test de aceptación**: ¿sobreviven los ocho claims?
2. **Frontera**: ¿el reconciliador consulta alias, entidades canónicas, Neo4j,
   memoria de workspace o correferencias entre tramos? Debe ser imposible.
3. **No vota**: se le darán dos proveedores de acuerdo y uno en desacuerdo, y se
   comprobará que conserva los candidatos rivales en vez de elegir.
4. **Independencia**: dos LLM con el mismo prompt deben dar `providers: 2` e
   `independent_families: 1`.
5. **Determinismo**: 100 permutaciones de la misma entrada → salida idéntica byte a
   byte. Idempotencia. Reproducibilidad entre procesos con `PYTHONHASHSEED`
   distintos.
6. **Conservador**: `lideraba` / `ya no lidera`, `pertenece` / `no pertenece`,
   `dejó de liderar` / `no dejó de liderar` → **nunca** se fusionan.
7. **Identidad con un solo extractor**: sin nada que reconciliar, la salida es la
   entrada. Esto protege la ruta determinista de los gates, que es la única
   reproducible bit a bit.
8. **Aguas abajo**: dos menciones solapadas conservadas sin fusionar no pueden
   acabar produciendo dos entidades ni dos claims duplicados.
9. **Rendimiento**: no puede ser la etapa dominante. Se medirá también **sin LLM**,
   donde una implementación cuadrática sería el nuevo cuello de botella. Nada de
   comparaciones todos contra todos: agrupad primero por claves baratas.
10. **Mutación**: cada regla estructural debe tener un test que se ponga **rojo** al
    relajarla. Un test verde que sigue verde tras romper la regla que dice proteger
    no cuenta como cobertura. Se aplicarán mutaciones propias del revisor.

## 8. Qué entregar

- Rama `feat/v3-proposal-reconciler` desde `feat/knowledge-v3-redesign`, empujada al
  repositorio. **Sin merge y sin PR** (lo abrimos nosotros).
- Informe en `docs/v3/23-reconciliador-implementacion.md` con: diseño y por qué,
  ficheros tocados, número de tests, resultado del test de aceptación, medición
  antes/después sobre el split `dev` (menciones y claims con P/R/F1, predicado top-1
  y top-2, dirección, tiempo de la etapa), defectos encontrados en otros subsistemas
  **sin parchear**, y limitaciones conocidas.
- La tabla de familias de independencia, versionada junto a la configuración, con
  su justificación escrita.

## 9. Historia del proyecto que os ahorra errores

Vale la pena conocer los tres fallos que más han costado aquí, porque el diseño está
construido contra ellos:

**El pecado original: `dev == test`.** La versión anterior del motor obtenía 0.81 de
precisión de predicado midiendo contra el mismo corpus con el que se había afinado,
y **0.24 sobre material real**. De ahí vienen la separación estricta de splits y la
prohibición de tocar el gold o el held-out.

**Aprobar de más.** Ese mismo motor generaba unos 170 falsos positivos por cada
acierto. Por eso todo el diseño actual prefiere abstenerse, y por eso el
reconciliador **no puede votar**: convertir dos propuestas débiles en una fuerte es
exactamente cómo se llega ahí.

**Lo que parece medido y no lo está.** Un bloque anterior declaró cerrado un fallo
de temporización que seguía abierto porque su test usaba un doble que no se
comportaba como el objeto real; el revisor lo cazó reproduciendo el caso con un
servidor de verdad. Escribid tests que ejerciten el comportamiento, no dobles
complacientes.

Y uno reciente, por si os toca leer código de negaciones: el sistema clasificaba
*"no dejó de liderar"* exactamente igual que *"dejó de liderar"* — habría cerrado la
vigencia de una relación que el texto afirma que sigue viva. Está corregido. Es el
tipo de error que un test escrito mirando la implementación jamás encuentra.

## 10. Glosario mínimo

| Término | Qué es |
|---|---|
| **Episodio** | Unidad de contenido con procedencia (un párrafo, un turno de habla, una fila) |
| **Fragmento** | Tramo de evidencia dentro de un episodio, con offsets |
| **Mención** | Aparición textual de una entidad, anclada a un fragmento |
| **Claim** | Propuesta de relación: sujeto, predicado, objeto, evidencia, polaridad |
| **Resolución** | Decisión de a qué entidad canónica corresponde una mención |
| **Assertion** | Hecho registrado en el ledger, con vigencia temporal |
| **GraphMutationPlan** | Plan firmado por el motor; lo único que el writer acepta |
| **Workspace** | Aislamiento duro entre corpus; nada cruza de uno a otro |
| **GameProfile** | Ontología del dominio: predicados, dominios, rangos, simetrías, inversas |
| **Split** | Partición del corpus: `dev` (libre), `negation` (batería), `heldout` (sellado) |

## 11. Contacto y dudas

Si algo de la especificación es ambiguo o contradictorio, **preguntad antes de
decidir por vuestra cuenta**, especialmente en: la frontera con el resolutor, qué
cuenta como "evidencia equivalente" para fusionar, y el formato de la tabla de
independencia. Una decisión silenciosa en cualquiera de esos tres puntos cuesta una
ronda entera de correcciones.
