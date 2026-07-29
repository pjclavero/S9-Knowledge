# Encargo a equipo externo — Interfaz de revisión, multimodalidad y writer real

Fecha: 2026-07-29 · Repositorio: `pjclavero/S9-Knowledge` · Rama base:
`feat/knowledge-v3-redesign`

Documento **autocontenido**: contiene todo lo necesario para trabajar sin haber
participado en el proyecto. Léelo entero antes de tocar nada.

**Reparto:** vosotros implementáis y entregáis en ramas separadas. Nosotros
revisamos, ejecutamos las pruebas y decidimos la integración. **No mergeéis nada, no
abráis PR.**

Son **tres encargos independientes** (A, B y C). Pueden hacerse en paralelo por
personas distintas: no comparten ficheros ni se estorban.

---

## PARTE 0 · Contexto común

### Qué es este sistema

S9-Knowledge convierte documentos (texto, PDF, tablas, transcripciones) en un grafo
de conocimiento en Neo4j:

```
fuente → normalización → episodios y fragmentos → extracción → resolución de
identidad → motor local → ledger temporal → GraphMutationPlan → writer → Neo4j
```

**El principio que gobierna todo el diseño:** los extractores y los modelos de
lenguaje **proponen**; solo el **motor local** valida y aprueba; solo el **writer**
escribe, y únicamente planes firmados por el motor. Ningún proveedor externo puede
aprobar ni escribir. Hay tests de mutación que lo comprueban: romperlo invalida la
entrega entera.

### Estado actual

La cadena funciona de punta a punta y tiene 4.539 tests en verde. El extractor
semántico está conectado, el reconciliador integrado, el motor decide y el writer
tiene su puerta de operador. **Pero el sistema todavía no es usable ni está
verificado donde importa**, y eso es exactamente lo que cubren estos tres encargos:

1. El motor manda a revisión humana la mayor parte de lo que extrae, y **no existe
   ninguna interfaz para revisarlo**. Hoy la cola de revisión es un concepto, no un
   sitio. (Parte A)
2. La multimodalidad —PDF escaneado, fotos, manuscritos, audio, vídeo— **está
   construida como interfaces y stubs**, y nunca se ha recorrido con material real.
   (Parte B)
3. El writer, la única puerta de escritura al grafo, **nunca ha hablado con un Neo4j
   de verdad**: sus 129 tests corren contra un driver simulado. (Parte C)

### Reglas duras (romper una invalida la entrega)

1. **Contratos congelados.** `contracts/knowledge-v3/v1/` y
   `data-engine/app/knowledge_v3/contracts/` no se tocan. Lo que no quepa va en
   `metadata`. Si creéis que falta un campo, **paradlo y reportadlo**.
2. **No toquéis `ci.yml` ni `pytest.ini`.**
3. **No toquéis el corpus gold** (`benchmarks/datasets/`). Ni para arreglar un caso
   que os parezca mal etiquetado: reportadlo.
4. **No uséis los splits `heldout` ni `negation`.** Existen en el repo y son
   activos de un solo uso; mirarlos los inutiliza.
5. **Nada escribe en el Neo4j de producción, nunca.** La parte C escribe, pero
   exclusivamente contra una instancia efímera que levantáis y destruís vosotros.
   En A y B el writer se usa en dry-run con driver simulado.
6. **No modifiquéis otros subsistemas.** Si encontráis un defecto en `engine/`,
   `resolution/`, `extraction/`, `reconcile/` o `writer/`, **no lo parcheéis**:
   documentadlo con fichero y línea. Esos módulos han pasado revisiones
   adversariales y un cambio lateral rompe garantías que no se ven desde fuera.
7. **Sin `git commit --amend` ni `push --force`.** Commits nuevos encima, siempre.
8. **Sin cifras inventadas.** Lo que no se ejecutó, se dice que no se ejecutó.

### Condición de entrega (esto cambió respecto al encargo anterior)

> **Una entrega sin tests escritos Y EJECUTADOS no se acepta, y no se revisa.**

En el encargo anterior llegó código sin un solo test, sin `pytest` ejecutado y sin
verificar el criterio de aceptación. El código resultó estar bien, pero eso no se
sabía: era código plausible. Se aceptó porque lo verificamos nosotros, y esa parte
no se va a repetir. Si vuestra entrega no incluye la salida real de `pytest`, se
devuelve sin leer.

### Entorno

- **Python 3.13** (es la versión de CI).
- Dependencias en `data-engine/requirements.lock` y `viewer/requirements.txt`. El
  proyecto **evita dependencias nuevas por política**: si necesitáis una,
  justificadla y elegid la más pequeña y pura-Python posible.
- Tests **desde la raíz del repositorio**:

```bash
python -m pytest data-engine/app/tests/ -q     # subsistema de datos
python -m pytest viewer/tests/ -q              # visor
python -m pytest -q                            # todo (usa pytest.ini)
```

- Para ejecutar código del data-engine: `PYTHONPATH=data-engine/app`.
- Estado que debéis mantener: **4.539 pasados, 9 saltados**, más vuestros tests, sin
  regresiones.

### Glosario mínimo

| Término | Qué es |
|---|---|
| **Episodio** | Unidad de contenido con procedencia (párrafo, turno de habla, fila) |
| **Fragmento** | Tramo de evidencia dentro de un episodio, con offsets |
| **Mención** | Aparición textual de una entidad, anclada a un fragmento |
| **Claim** | Propuesta de relación: sujeto, predicado, objeto, evidencia, polaridad |
| **Assertion** | Hecho registrado en el ledger, con vigencia temporal |
| **GraphMutationPlan** | Plan firmado por el motor; lo único que el writer acepta |
| **Workspace** | Aislamiento duro entre corpus; nada cruza de uno a otro |
| **GameProfile** | Ontología: predicados, dominios, rangos, simetrías, inversas |
| **reason_code** | Código que explica por qué el motor decidió lo que decidió |

---

## PARTE A · Interfaz de revisión

### El problema

El motor produce decisiones: `ACCEPT`, `REVIEW`, `ABSTAIN`, `REJECT_INVALID`. En la
última medición sobre el corpus de desarrollo, de 18 claims propuestos: **0
aceptados, 7 a revisión, 10 abstenciones, 1 rechazo**. Es decir, **prácticamente
todo el conocimiento que el sistema extrae necesita que una persona lo mire** — y
ahora mismo no hay dónde mirarlo.

Sin esta interfaz, S9-Knowledge no se puede usar. Con ella, se puede empezar a
alimentar el grafo aunque el extractor todavía sea mediocre.

### Lo que hay que construir

Una aplicación web mínima pero **usable de verdad** para revisar propuestas.

**Base de partida:** existe `viewer/` — un visor de solo lectura en FastAPI
(`viewer/app/main.py`, con rutas `/`, `/graph`, `/status`, plantillas HTML y sus
tests en `viewer/tests/`). Decidid vosotros si lo extendéis o creáis una aplicación
hermana; justificadlo en el informe. Reutilizar su autenticación y su estilo es
preferible a inventar otro.

### Qué tiene que poder hacer una persona

1. **Ver la cola**: qué hay pendiente de revisar, con filtros por workspace, fuente
   y tipo de decisión, y ordenación estable.
2. **Entender la propuesta sin salir de la pantalla**:
   - el **texto del episodio completo**, con la **evidencia literal resaltada** en
     su posición exacta (los offsets están en el fragmento);
   - sujeto, predicado, objeto y dirección propuestos;
   - los **candidatos alternativos** de predicado y de dirección, con su confianza y
     **qué extractor propuso cada uno** (está en `provider_trace` y en
     `metadata.reconciliation.support`);
   - si viene negado, de qué tipo;
   - **por qué el motor no lo aprobó**: los `reason_code` traducidos a lenguaje
     humano, no el código en crudo;
   - la ontología aplicable: qué predicados permite el perfil entre esos tipos.
3. **Decidir**: aprobar, rechazar, o corregir (elegir otro predicado de entre los
   candidatos, invertir la dirección, marcar la negación, ajustar el alcance).
4. **Registrar la decisión** — y esto es lo más importante del encargo.

### El registro de decisiones es el entregable de verdad

La interfaz es el medio; **el activo es el historial estructurado de decisiones
humanas**. Ese historial es lo que después permitirá que el glosario crezca, que se
generen tests de regresión y que se pueda entrenar o auditar cualquier cosa. Hoy no
existe, y cada revisión que se hace sin registrar es material perdido para siempre.

Cada decisión debe guardarse con, al menos:

```yaml
decision_id:
timestamp:
reviewer:              # quién
workspace:
source_id:
episode_id:
proposal:              # la propuesta íntegra que se revisó
engine_decision:       # qué había decidido el motor, con sus reason_codes
human_decision:        # APPROVE | REJECT | CORRECT
correction:            # qué cambió exactamente, si corrigió
rationale:             # texto libre opcional del revisor
ontology_version:
engine_version:
```

Almacenamiento **append-only** (JSONL sirve), sin borrados ni ediciones en sitio.
Una corrección posterior es una entrada nueva que supersede a la anterior, no una
sobrescritura. Es el mismo principio que el ledger del sistema.

### Lo que la interfaz NO puede hacer

- **No aprueba nada por su cuenta ni escribe en Neo4j.** Una decisión humana de
  aprobar produce un registro; la escritura sigue siendo del writer, con su gate de
  operador, y eso queda fuera de este encargo.
- **No modifica el motor ni sus umbrales.**
- **No inventa datos**: si un campo no está en la propuesta, la pantalla lo dice, no
  lo rellena.
- **No cruza workspaces**: un revisor ve un workspace cada vez. Es un invariante de
  seguridad del sistema entero, no una preferencia.

### Usabilidad: qué significa aquí

No hace falta que sea bonito. Hace falta que **una persona pueda revisar cincuenta
propuestas seguidas sin agotarse**:

- atajos de teclado para aprobar, rechazar y pasar a la siguiente;
- que el foco vaya solo al siguiente ítem tras decidir;
- que no haya que hacer scroll para ver la evidencia;
- que se pueda deshacer la última decisión;
- que el estado sobreviva a recargar la página;
- que diga cuántas quedan.

Si la pantalla obliga a abrir otra ventana para entender la propuesta, el encargo no
está cumplido.

### Tests mínimos exigidos (escritos y ejecutados)

| Qué | Esperado |
|---|---|
| La cola lista solo el workspace pedido | Ningún ítem de otro workspace, nunca |
| Cada decisión escribe exactamente una entrada | Append-only verificado |
| Una corrección no borra la decisión anterior | Dos entradas, la segunda supersede |
| La interfaz no escribe en Neo4j | Driver que estalla si se le llama |
| La interfaz no aprueba sola | Aprobar humano ≠ plan aprobado |
| Evidencia resaltada en la posición correcta | El tramo marcado coincide con los offsets |
| `reason_code` desconocido | Se muestra el código, no se rompe la página |
| Recarga a media revisión | No se pierde ni se duplica ninguna decisión |

### Entrega A

- Rama `feat/v3-review-ui`, empujada. Sin merge, sin PR.
- Informe en `docs/v3/25-interfaz-de-revision.md`: diseño, decisión sobre extender o
  no el visor, esquema del registro de decisiones, capturas o descripción del flujo,
  **salida real de `pytest`**, y limitaciones conocidas.

---

## PARTE B · Multimodalidad real

### El problema

V3 promete ingerir PDF nativo y escaneado, fotos, manuscritos, dibujos, mapas,
diagramas, tablas, audio y vídeo. Lo construido hoy:

- **Reales**: texto, Markdown, tabla (CSV y Markdown), PDF nativo (extracción por
  página), y envoltorios de las transcripciones existentes.
- **Stubs honestos**: imagen, manuscrito y dibujo. Existe el puerto
  `VisualProvider` (`multimodal/adapters/visual.py`) y, sin proveedor conectado, se
  emite `UNPROCESSED_PENDING_PROVIDER` con `score 0.0`, sin texto y sin evidencia.

Es decir: la arquitectura está, el enganche está, y **no hay nadie al otro lado**.
Además, **nunca se ha recorrido la cadena completa con una fuente real no textual**.

### Lo que hay que construir

**B.1 — Un proveedor de OCR real conectado al puerto existente.**

Requisitos:

- **Local por defecto.** El contenido no debe salir de la máquina salvo decisión
  explícita: el sistema tiene una política de proveedores con
  `PRIVATE_CONTENT_STAYS_LOCAL` y hay que respetarla. Tesseract u otro motor local
  es preferible a una API de nube; si proponéis nube, que sea opcional y desactivada
  por defecto.
- Debe devolver **texto con posición** (bounding boxes), porque el contrato de
  evidencia lo exige para `media_type: OCR_TEXT`. Un OCR que solo devuelva texto
  suelto no sirve: la evidencia quedaría sin anclar.
- **OCR literal y descripción visual son cosas distintas** y el sistema ya lo
  distingue: un proveedor que devuelva las dos a la vez se rechaza. Respetadlo.
- Confianza fuera de `[0,1]` → se rechaza el resultado, **no se recorta**.

**B.2 — El recorrido completo con material real.**

Coger una fuente de verdad y llevarla de punta a punta:

```
PDF escaneado (o foto de una página)
  → normalización → episodios y fragmentos con bbox
  → extracción → resolución → motor → GraphMutationPlan (dry-run)
```

Y documentar **dónde se pierde información**: cuántos caracteres recupera el OCR,
cuántos episodios salen, cuántas menciones sobreviven al anclaje, cuántos claims
llegan al motor. El sistema ya tiene un arnés de métricas (`knowledge_v3/benchmarks/`)
que calcula CER, WER y cobertura: usadlo, no inventéis otro.

**B.3 — Gold multimodal: el mismo contenido, varias modalidades.**

Preparad **un fragmento corto de contenido** (dos o tres párrafos inventados, mundo
nuevo, nada de los corpus existentes) y producidlo en:

- texto plano;
- PDF nativo;
- PDF escaneado o foto (podéis imprimir a imagen y degradarla);
- audio leído (o su transcripción simulada con errores realistas de ASR).

**Con el mismo gold semántico para las cuatro.** Eso permite responder la pregunta
que hoy no se puede: si el texto produce una relación y el audio no, ¿falla el ASR o
falla el motor? Va a `benchmarks/datasets/multimodal/`, split propio, y **no se
conecta a ningún flujo automático**.

### Lo que NO hay que hacer en este encargo

- No implementar HTR (manuscrito) ni interpretación visual de dibujos y mapas: el
  puerto queda como está, con su stub.
- No tocar el pipeline de audio y vídeo existente: se envuelve, no se reescribe.
- No añadir proveedores de nube activados por defecto.

### Tests mínimos exigidos (escritos y ejecutados)

| Qué | Esperado |
|---|---|
| OCR real sobre una imagen fixture | Texto con bbox, evidencia anclada, contrato válido |
| Imagen ilegible o vacía | Diagnóstico, sin inventar texto, sin romper el lote |
| Proveedor que devuelve texto y descripción a la vez | Rechazado |
| Confianza fuera de rango | Rechazado, no recortado |
| Bbox fuera de los límites de la imagen | Rechazado |
| Sin proveedor conectado | Sigue emitiendo el stub actual, sin regresión |
| Recorrido completo con la fixture real | Llega al plan en dry-run, sin escribir |
| Las cuatro modalidades del gold | Las cuatro validan contra los contratos |

### Entrega B

- Rama `feat/v3-multimodal-real`, empujada. Sin merge, sin PR.
- Informe en `docs/v3/26-multimodalidad-real.md`: qué proveedor de OCR y por qué,
  cómo se instala, medición del recorrido completo con las cifras reales de pérdida
  por etapa, composición del gold multimodal, **salida real de `pytest`**, y qué
  queda sin cubrir.

---

## PARTE C · El writer contra un Neo4j real

### El problema, y por qué es el más grave de los tres

El writer es la única puerta física al grafo. Está construido, revisado
adversarialmente y tiene 129 tests: admisión de planes firmados, gate de operador de
nueve condiciones, transacción única, concurrencia optimista, idempotencia,
rollback, auditoría append-only.

**Y nunca ha hablado con un Neo4j de verdad.** Todo está probado con un driver
simulado. Las consultas Cypher se construyen y se verifican contra un mock que
responde lo que el test espera. Nadie ha comprobado que **en una base real hagan lo
que dicen hacer**.

Esto no es un detalle: es la diferencia entre "el writer se comporta bien" y "el
writer escribe bien". Un error de sintaxis Cypher, un `MERGE` que se comporta
distinto de lo previsto, una transacción que no aísla como se cree, o una
comparación de versión que la base evalúa de otro modo — nada de eso lo puede
detectar un mock, porque el mock está de acuerdo con quien lo escribió.

### Regla absoluta

> **Contra un Neo4j efímero y aislado. NUNCA contra producción.**

En la infraestructura del proyecto hay un Neo4j en uso con datos reales. **Está
prohibido tocarlo**: ni escribir, ni leer, ni "solo para comprobar". Levantad una
instancia propia en contenedor, con datos que creéis vosotros, y destruidla al
terminar. Si vuestro entorno no permite levantar Neo4j, **paradlo y decidlo** — es
mejor no entregar esta parte que hacerla contra algo que no debe tocarse.

### Lo que hay que verificar (cada punto, contra la base real)

1. **Las consultas son Cypher válido.** Suena obvio; es la mitad del valor de este
   encargo.
2. **CREATE-only de verdad**: el writer no debe poder sobrescribir un nodo o una
   relación existente. Preparad el estado, aplicad un plan que lo intente y
   comprobad en la base que no se pisó nada.
3. **Concurrencia optimista real**: un plan trae `expected_version` y
   `expected_hash` de cada objetivo. Modificad el nodo por fuera entre la lectura y
   la aplicación, y comprobad que el plan **aborta entero** en vez de escribir con
   el estado desfasado. Es la prueba que un mock no puede dar.
4. **Transaccionalidad**: forzad un fallo en la operación N de M (una restricción
   violada, por ejemplo) y comprobad **en la base** que no quedó ni una escritura de
   las anteriores.
5. **Idempotencia**: aplicar el mismo plan dos veces deja el grafo idéntico y la
   segunda vez cuenta como no-op. Verificad contando nodos y relaciones, no fiándoos
   del informe del writer.
6. **Cierre de vigencia y supersesión**: un plan de cesación cierra el hecho
   anterior **sin borrarlo** y crea la supersesión. Comprobad que la historia sigue
   ahí y es consultable.
7. **Dry-run no toca nada**: ejecutad el mismo plan en dry-run contra la base real y
   comprobad que el grafo queda **byte a byte** como estaba.
8. **El gate sigue mandando**: sin `S9K_ALLOW_REAL_INGEST`, sin confirmación del
   hash del plan, o con el workspace mal declarado, no se escribe nada aunque la
   base esté disponible y accesible.
9. **Aislamiento de workspace en la base**: un writer construido para un workspace
   no puede tocar nodos de otro, y hay que comprobarlo consultando la base después.

### Lo que NO hay que hacer

- **No modifiquéis el writer** salvo que encontréis un defecto real; en ese caso,
  documentadlo y proponed el arreglo por separado, sin mezclarlo con las pruebas.
- No cambiéis el gate ni sus condiciones.
- No añadáis dependencias pesadas: si usáis `testcontainers` o similar,
  justificadlo; un `docker run` desde un script de prueba marcado para no correr en
  CI por defecto también vale.
- Estas pruebas **no deben ejecutarse en CI por defecto** (CI no tiene Neo4j):
  marcadlas para que se salten salvo que se active explícitamente, como ya hace el
  proyecto con las pruebas contra Ollama y NVIDIA.

### Entrega C

- Rama `test/v3-writer-neo4j-real`, empujada. Sin merge, sin PR.
- Informe en `docs/v3/27-writer-contra-neo4j-real.md`: cómo se levanta la instancia
  efímera, qué se verificó punto por punto **con la evidencia de la base** (conteos,
  estados antes y después), qué falló si algo falló, **salida real de `pytest`**, y
  qué queda sin cubrir.
- Si algo del writer resulta estar mal, ese hallazgo es el entregable más valioso de
  los tres encargos. Reportadlo con claridad y sin arreglarlo por vuestra cuenta.

---

## PARTE D · Cómo se os va a revisar

Un revisor independiente **ejecuta, no lee**. Sin sorpresas: estos son los criterios.

**Comunes a los tres encargos:**

1. La suite completa sigue en verde, sin regresiones (4.539 + vuestros tests).
2. Vuestros tests **se ponen rojos** si se rompe la regla que dicen proteger. Se
   aplicarán mutaciones propias del revisor: un test que sigue verde tras romper su
   invariante no cuenta como cobertura.
3. Ningún camino escribe en Neo4j ni aprueba nada por su cuenta.
4. Aislamiento de workspace intacto.
5. Contratos, gold, `heldout`, `negation`, `ci.yml` y `pytest.ini` sin tocar
   (`git diff` restringido a esas rutas debe estar vacío).
6. Lo declarado en el informe coincide con lo que se puede reproducir.

**Específicos de A:** que una persona pueda revisar cincuenta ítems seguidos; que el
registro sea append-only de verdad (se intentará corromperlo); que la evidencia
resaltada corresponda exactamente a los offsets; que un `reason_code` desconocido no
rompa la pantalla.

**Específicos de C:** que las pruebas corran contra una base real y efímera, nunca
contra la de producción; que cada verificación traiga evidencia consultada en la
base (conteos, estado antes y después), no el informe del propio writer.

**Específicos de B:** que el OCR devuelva posiciones utilizables; que la evidencia
quede anclada; que una imagen basura no produzca texto inventado; que las cuatro
modalidades del gold compartan gold semántico de verdad.

---

## PARTE E · Historia del proyecto que os ahorra errores

Tres fallos que han costado caro aquí, porque el diseño está construido contra
ellos:

**`dev == test`.** Una versión anterior obtenía 0.81 de precisión midiendo contra el
mismo corpus con el que se había afinado, y **0.24 sobre material real**. De ahí la
separación estricta de splits y la prohibición de tocar el gold.

**Aprobar de más.** Ese mismo motor generaba unos 170 falsos positivos por acierto.
Por eso el sistema prefiere abstenerse y por eso nada aprueba automáticamente.

**Lo que parece medido y no lo está.** Un bloque declaró cerrado un fallo que seguía
abierto porque su test usaba un doble que no se comportaba como el objeto real; se
descubrió reproduciéndolo con un servidor de verdad. Escribid tests que ejerciten el
comportamiento, no dobles complacientes. Y en la parte B esto es especialmente fácil
de hacer mal: un OCR simulado que siempre devuelve el texto correcto no prueba nada.

## PARTE F · Dudas

Si algo es ambiguo, **preguntad antes de decidir en silencio**, sobre todo en: qué
se considera "usable" en la parte A, el formato exacto del registro de decisiones, y
qué motor de OCR elegir en la parte B. Una decisión silenciosa en cualquiera de esos
tres puntos cuesta una ronda entera de correcciones.
