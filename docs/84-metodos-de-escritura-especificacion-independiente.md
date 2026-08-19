# 84 — Los métodos de los endpoints de ESCRITURA, contra una especificación independiente del montaje

**Qué se cablea:** el job `metodos-de-escritura` de `ci.yml` («Metodos de
escritura (especificacion independiente del montaje)») y la suite
`viewer/tests/test_metodos_escritura_http.py`, que corre dentro de los tests del
visor y por tanto ya entra en un check exigido.
**Qué lo sostiene:** `scripts/route_map/write_spec.py` (la especificación) y
`scripts/route_map/calibrate_write_spec.py` (su control negativo).
**Qué NO hace este carril:** añadir el job nuevo a la protección de rama (lo
decide el operador), ni tocar el contrato del censo (`docs/83`), que queda
intacto.

---

## 1. La garantía que no estaba donde creíamos

El censo de rutas es el check exigido nº 16 y su contrato incluye, textualmente,
**«método cambiado → ROJO»**. Sobre el SHA congelado `aaf9695` se comprobó que
no lo cumple para las rutas de escritura:

- `viewer/app/routers/admin.py:263`, `POST /admin/users/{user_id}/unlock` —una
  ruta **de escritura**— pasa a `GET`: **ningún instrumento se pone rojo**.
- se le **añade un alias `GET`** a esa misma ruta: **tampoco**.

La causa no es un descuido, es la construcción del control. `gate.py` compara
los métodos **declarados por el router** con los métodos **montados en la app**:

```python
# scripts/route_map/gate.py:513-520
montados = sorted({m for f in filas for m in f["metodos"]})
if montados != d["metodos_declarados"]:
    hallazgos["metodo-declarado-no-coincide"].append(...)
```

y `metodos_declarados` sale de `route.methods` del propio `APIRouter`
(`gate.py:324-331`), o sea, **del mismo decorador que se pretende vigilar**. Si
alguien escribe `@router.get`, las dos mitades de la comparación cambian a la vez
y la igualdad se mantiene. El único control de método que sí es independiente
—`metodo-cambiado`, `gate.py:609-614`— sólo mira los **nombres de ruta que
`NAV` exige**, es decir, pantallas de navegación (`GET`); ninguna ruta de
escritura está en `NAV`.

Y `POST /admin/users/{user_id}/unlock` **no tenía ninguna prueba HTTP**.

## 2. De dónde sale ahora la referencia (y por qué no es una lista)

La condición del operador es la misma que rige el censo: la fuente de referencia
vive **en código o en una fuente canónica ejecutable**, nunca en una lista
documental que haya que acordarse de actualizar. Aquí son **tres fuentes, todas
ejecutadas, ninguna derivada del decorador**:

| id | fuente | qué aporta | qué la mantiene al día |
|---|---|---|---|
| **F1** | firma y cuerpo del manejador (AST) | **capacidad de escritura**: parámetros de cuerpo en CUALQUIER estilo —`x: str = Form(...)`, `x: Annotated[str, Form()]`, `UploadFile`, modelos de pydantic— y con alias de importación resueltos; `request.form()/json()/body()`; **verificación** de CSRF; y llamadas que **escriben estado durable**, derivadas leyendo el código del invocable | es el código que el manejador ejecuta; escribir el handler lo declara |
| **F2** | plantillas y JS que **la propia app sirve** (`viewer/app/templates`, `viewer/app/static`) | contrato de cliente `MÉTODO + URL`: `<form method="post" action="/x">`, `fetch(url, {method})` | si la pantalla cambia, el contrato cambia con ella |
| **F3** | la app REAL (`fastapi.testclient` contra `app.main.app`) | toda afirmación termina en una petición y en **quién la atendió** | es la app que se despliega |

Ninguna enumera endpoints. Pero **la primera versión de este documento afirmaba
de más**, y un revisor lo tumbó por ejecución: decía «un endpoint de escritura
nuevo queda cubierto solo» cuando eso dependía de que F1 lo reconociera, y F1
era **muda** ante `x: Annotated[str, Form()]` —la forma que la documentación de
FastAPI recomienda hoy— y ante un alias de importación (`from fastapi import
Form as _F`). Medido entonces: un `@router.get` con `Annotated[..., Form()]` que
escribía un fichero salía **`rc=0`, VERDE**; el mismo con `Form(...)` clásico
salía rojo. **La única diferencia era el estilo del parámetro.** La regla de
«modelo de cuerpo» estaba además **muerta en toda la app**, porque los routers
usan `from __future__ import annotations` y `inspect.signature` devuelve
cadenas.

Corregido, y **con la afirmación rebajada a lo que se puede sostener**:

1. F1 recorre el **árbol de la anotación** (no su texto) y resuelve cada nombre
   por los `import` del módulo, así que entran `Annotated[str, Form()]` y los
   **alias de importación** (`Form as _F`). Casos `ADV-annotated`, `ADV-alias`,
   `ADV-clasico`.

   **Lo que NO entra, y la versión anterior de este documento decía lo
   contrario:** la anotación escrita **como cadena** (`x: "Annotated[str,
   Form()]"`) sale `[]`, porque `_evidencia_en_anotacion` trata
   `Call`/`Name`/`Attribute` y no `ast.Constant`. Mudos por la misma razón el
   **alias de tipo reutilizado** —`Formulario = Annotated[str, Form()]` y luego
   `x: Formulario`, patrón que la propia documentación de FastAPI recomienda— y
   las anotaciones de `*args`/`**kwargs`. Los tres son **irrelevantes hoy
   mientras el endpoint vaya montado con `POST/PUT/PATCH/DELETE`, porque
   entonces los coge la red (2)**; lo que no cubre nadie es esa forma sobre un
   `GET`.
2. Y sobre todo: **hay una red que NO depende de que F1 acierte**. Toda ruta
   montada con `POST/PUT/PATCH/DELETE` cuya clasificación no encontró **ni una**
   evidencia sale `metodo-de-escritura-sin-evidencia`. Hoy ese conjunto está
   **vacío** sobre las 70 rutas, así que entra en verde y **cubre a todo
   endpoint de escritura montado, acierte o no la clasificación**. Caso
   `ADV-mudo`.

Lo que no se pueda clasificar por falta de fuente sale ROJO
(`endpoint-sin-fuente`); lo que se clasifique **sin evidencia** cae en
«lectura», y es la red (2) —no la clasificación— la que impide que eso pase
mudo.

Cifra de la base, **tras arreglar los dos GET que escribían** (§«el defecto
estaba en las rutas»): **71 rutas montadas, 14 de escritura, 57 de lectura, 23
contratos de cliente (14 de escritura)**, especificación **VERDE** (`rc=0`,
**cero hallazgos**).

Las cifras han cambiado tres veces en este carril, y las tres constan porque
cada cambio dice algo: «13 de escritura / 57 de lectura / VERDE» era la primera
medida, con la clasificación aún ciega a `app.health`; «15 / 55 / ROJA con 2
`lectura-que-escribe`» fue la medida honesta del defecto; **«14 / 57 / VERDE» es
la de ahora**, con los dos GET de salud convertidos en lectura pura y la
escritura movida a un `POST`. Una cifra que sobrevive al cambio de la cosa que
mide es el error que este carril persigue.

### La atribución se hace por EJECUCIÓN, no por path

`GET /login` y `POST /login` comparten path: que la app sirva `GET` ahí es
legítimo porque lo atiende **otro** manejador (el que pinta el formulario). Por
eso el sondeo instrumenta cada objeto `Route` y registra **qué manejador
atendió** la petición (`write_spec._instalar_resolutor`). El rojo salta cuando el
`GET` lo atiende un manejador **clasificado como de escritura**, no cuando la
URL responde. Sin esto, cuatro rutas legítimas salían rojas —`/login`,
`/account/change-password`, `/admin/users/new`, `/admin/users/{user_id}`—: un
rojo por el motivo equivocado es peor que un verde.

### Un detalle que costó dos endpoints: las comillas del `action`

La primera versión leía los atributos HTML con `["']([^"']*)["']` y perdía **en
silencio** el formulario cuyo `action` lleva Jinja con comillas simples dentro
(`{% if mode == 'new' %}…`), que es justamente el de `POST /admin/users/new` y
`POST /admin/users/{user_id}`. Contratos de cliente: 16 → **22**. Un contrato que
se pierde sin ruido es un endpoint sin vigilar.

### La lista de módulos que había aquí era el mismo antipatrón, un nivel más arriba

La versión anterior decidía qué es «estado durable» con
`MODULOS_DE_ESTADO_DURABLE = ("app.auth", "app.services", …)`: **una tupla de
prefijos mantenida a mano**. Bastaba que una escritura viviera en un módulo no
listado para que el endpoint saliera verde — y eso es exactamente lo que pasaba
con `app.health`. Un carril cuyo titular es «un GET que escribe es lo que
existimos para detectar» no puede cerrar dejando verdes los dos únicos GET que
escriben en el repositorio.

Sustituida por `_escribe_de_verdad()`, que **lee el código del invocable**
(resuelto por `sys.modules` a partir de los `import` del módulo) y busca
primitivas de escritura: `write_text`/`write_bytes`, `mkdir`, `os.replace`,
`os.chmod`, `open(..., "w")`, SQL de escritura, `commit`.

**La cota, enunciada como es y no como suena mejor: se sigue UN SALTO A
SÍMBOLOS IMPORTADOS de `app.*`.** Medido, función a función: `write_text`
directo → detectado; helper **importado** → detectado; **helper del MISMO
módulo → MUDO**; dos helpers encadenados → mudo; objeto instanciado en tiempo
de ejecución → mudo. La causa es concreta: `_escribe_de_verdad` resuelve el
invocable con `_importaciones_del_modulo`, y un nombre local no lleva punto, así
que sale por `"." not in canon`. Decir «un salto» a secas prometía más de lo que
da: los helpers locales tienen **cero**.

**Y no se arregla a la ligera, también medido:** seguir helpers locales sin más
criterio convierte media docena de GET de administración en
`lectura-que-escribe` por el `mkdir` de `admin._get_db_path`. Un rojo por el
motivo equivocado es peor que un verde, así que la cota se declara en vez de
ensancharse a ciegas.

**La restricción a `app.*` sí está medida y gana precisión**: quitándola, la
base pasa de 15 a 20 endpoints de escritura y de 2 a 7 `lectura-que-escribe`, y
los **5 nuevos son el mismo falso positivo** —`Path(indirecto)`: se desciende a
`pathlib` y allí escribe cualquier cosa—. Antes de acotarlo eran 12 rutas de
lectura marcadas por error.

**Consecuencia inmediata, que fue un ROJO REAL:** `GET /admin/health` y
`GET /api/admin/health` llamaban a `app.health.storage.save_report` dentro del
propio `GET` —`mkdir` + `write_text` + `os.replace` + `chmod 0600`—, y salieron
como **`lectura-que-escribe`**, con la especificación en `rc=1`.

### El defecto estaba en las rutas, y se arregló ahí

Decisión del operador (2026-08-19), textual: *«si esos dos GET provocan
escritura, el defecto está en las rutas, no en la puerta»*. Y explícitamente: no
se acepta un `GET` que escribe por ser «sólo administración», «sólo health» o
«ya estaba así», ni una whitelist tipo `health_admin.py permitido`, porque eso
**destruiría la independencia del censo**. Se arreglaron las rutas
(`viewer/app/routers/health_admin.py`), endpoint por endpoint y por semántica:

| endpoint | qué pretende hacer | qué era la escritura | resolución |
|---|---|---|---|
| `GET /api/admin/health` | **consultar** salud y devolver JSON | **incidental**: una caché para que el panel B tuviera algo que enseñar | **se elimina**; queda de lectura pura |
| `GET /admin/health` | **consultar** salud y pintarla | **incidental**, misma caché | **se elimina**; queda de lectura pura |
| `POST /admin/health/snapshot` *(nuevo)* | **guardar** la instantánea | **es la operación** | verbo mutador, `require_admin` + **CSRF**, con su formulario en la plantilla |

Ejecutar comprobaciones **no** es escribir: `runner.run_report()` no deja estado
durable propio. Lo que lo dejaba era `save_report`, y ahora vive donde la
semántica lo pedía.

**Quién consume el informe guardado, comprobado ANTES de romper nada:**
`app.health.storage.load_last` lo leen `app/routers/chassis_operations.py`
(panel B) y `app/cli/health.py`. El CLI **también lo escribe**, y es el camino
previsto en producción (el timer horario), así que quitar la escritura del `GET`
no deja al panel sin fuente; y la capacidad de refrescarlo desde la interfaz no
se pierde: cambia de verbo. Comprobado por HTTP en
`viewer/tests/test_health_admin_get_sin_escritura.py` (7 casos: los dos GET no
crean el fichero, el POST sí lo crea y redirige, sin CSRF da 403 sin escribir,
el anónimo no escribe, y ningún verbo de escritura se cuela por los GET).

**Efecto sobre este carril:** la base vuelve a `rc=0`, el job **deja de nacer
rojo — porque el defecto ya no existe, no porque se haya eximido**, y el
contrato `rc == 0` vuelve a vivir en un check EXIGIDO (la suite del visor), que
es donde debe estar. El registro fechado de excepciones que hubo entre el 18 y
el 19 de agosto **queda vacío**, y la constante se conserva sólo para que
cualquier lectura-que-escriba futura rompa esa suite.

**Higiene que descubrió el propio arreglo:** `storage.default_report_path()`
devuelve una ruta **relativa**, así que una sonda que consiguiera escribir
—contra el endpoint sin guardián que inyecta la calibración, por ejemplo—
dejaba el fichero en el árbol REAL aunque el auditado fuese una copia. Medido y
corregido: `write_spec.bootstrap` apunta `S9K_HEALTH_REPORT_PATH` a un temporal.
Un instrumento que escribe en lo que mide invalida su propia medida.

## 3. El contrato, punto por punto

| control | afirma | hallazgo |
|---|---|---|
| **C1** (enumeración) | ningún endpoint con capacidad de escritura está montado con `GET`/`HEAD`; y tiene al menos un método de escritura | `metodo-seguro-en-endpoint-de-escritura`, `escritura-sin-metodo` |
| **C2** (ejecución) | un `GET` a la URL de una escritura **no lo atiende el manejador de escritura** | `escritura-servida-por-get` |
| **C1bis** (red independiente de F1) | ninguna ruta montada con `POST/PUT/PATCH/DELETE` se queda sin explicación | `metodo-de-escritura-sin-evidencia` |
| **C1ter** | ningún método seguro escribe estado durable | `lectura-que-escribe` |
| **C3** (contrato de cliente) | todo formulario/`fetch` que la app sirve se puede ejecutar **y lo atiende la ruta que manda** (la más específica que casa con la URL) | `contrato-de-cliente-roto` |
| **C4** (suelos) | hay endpoints de escritura y contratos de escritura; hubo sondeo y alguna petición atravesó un manejador | `espec-vacia`, `espec-no-inspecciono-la-app-real` |
| **C5** (clasificación) | todo endpoint montado se pudo clasificar | `endpoint-sin-fuente` |

C1 y C2 son **redundantes a propósito**: uno lee el enrutador, el otro ejecuta.
C3 cubre lo que ninguno de los dos ve: un cambio de método que **sigue siendo
inseguro** (`POST → PUT`), donde «no hay método seguro» sigue siendo cierto.

## 4. Controles negativos: medidos endpoint a endpoint

`python3 scripts/route_map/calibrate_write_spec.py`. **Una mutación por vez, un
subproceso por mutación, sobre copias del árbol**, con `__pycache__` purgado y
`PYTHONDONTWRITEBYTECODE=1`; al terminar se comprueba por **SHA-256 del
contenido** de `viewer/`, `scripts/route_map/` y `contracts/` que el árbol real
no cambió ni un byte.

Los casos **no están escritos a mano**: el arnés ejecuta la especificación sobre
el árbol limpio, toma de ahí los endpoints de escritura y muta **cada uno**. Si
mañana aparece uno nuevo, se muta también sin que nadie lo añada aquí.

Corrida completa: **49 casos, veredicto OK, 0 en fallo**, hash del árbol
idéntico antes y después (`32d820e4…36f8`), **8 ablaciones cobradas**.

| familia | mutación | n | resultado |
|---|---|---|---|
| **W0** | árbol limpio | 1 | **VERDE** (`rc=0`, cero hallazgos). Lo era también antes del 18/8; entre medias salió ROJO por un defecto real, y ahora vuelve a serlo **porque el defecto se arregló**, no porque se eximiera |
| **MET-\<endpoint\>** | `@router.post` → `@router.get` | **14/14** | **ROJO** por `metodo-seguro-en-endpoint-de-escritura` nombrando al endpoint. Corroborado por ejecución en 10/14 y por contrato de cliente en **14/14** |
| **ALI-\<endpoint\>** | se **añade** `@router.get(<misma ruta>)` | **14/14** | **ROJO**, mismo motivo. Corroborado por ejecución en 10/14 |
| **PUT-\<endpoint\>** | `@router.post` → `@router.put` | **14/14** | **detectados por C3** (`put_no_detectados: []`) |
| **ADV-annotated / -alias / -clasico** | endpoint de escritura **NUEVO** con `Annotated[str, Form()]` / alias de `Form` / `Form` clásico, montado con `@router.get` | 3/3 | **ROJO** por `metodo-seguro-en-endpoint-de-escritura` |
| **ADV-mudo** | `POST` nuevo **sin ninguna evidencia** clasificable | 1/1 | **ROJO** por `metodo-de-escritura-sin-evidencia` |
| **ADV-lectura-que-escribe** | `GET` nuevo que llama a `storage.save_report` | 1/1 | **ROJO** por `lectura-que-escribe` — el defecto que el operador se negó a eximir, ahora reproducido a voluntad |
| **FP-lectura-genuina** | `GET` nuevo que **sólo lee** | 1/1 | **VERDE**, cero hallazgos |

Los tres casos que el operador exigió medir tras el arreglo están ahí, y salen
como debían: **`POST → GET` = ROJO** (familia MET), **alias `GET` mutador =
ROJO** (familia ALI y `ADV-*`), **`GET` genuino de lectura = VERDE**
(`FP-lectura-genuina`). El tercero no es adorno: sin él, «se pone rojo con todo»
pasaría por buena señal, y el modo de fallo por exceso —volverse estricto de
más— no se ve mirando sólo los rojos.

Los 14 endpoints de escritura, nombre a nombre: `login_submit`, `logout`,
`change_password_submit`, `admin_users_new_submit`, `admin_user_update`,
`admin_user_unlock`, `admin_revoke_sessions`, `admin_partidas_grant`,
`admin_partidas_revoke`, `select_partida`, `reviews_console.decide`,
`v3_review.decide`, `v3_review.undo` y **`admin_health_snapshot`** —el nuevo, que
el arnés muta como a cualquier otro **sin que nadie lo haya escrito en ninguna
lista**: apareció y quedó cubierto—. Y `endpoints_sin_metodo_de_escritura` está
**vacío**: ya no hay ningún endpoint de escritura sin verbo mutador.

Los 4 casos en que la ejecución no corrobora son **exactamente** los endpoints
cuyo path comparte una pantalla `GET`: al mutar, la petición la sigue atendiendo
el manejador de lectura y C2 no puede pronunciarse. El rojo lo da C1. **Se
registra, no se disimula.**

### `POST → PUT` en `/admin/users/new`: cerrado sin escribir ningún nombre

Era el único `NO-DETECTADO` de la ronda anterior, y no era un agujero de diseño
sino de atribución: `/admin/users/new` se declara antes que
`/admin/users/{user_id}`, así que al mutar el primero la petición cae en el
segundo (`user_id="new"`) y responde 422 — nunca 405, que era lo único que C3
miraba. Ahora C3 exige además que **la atienda la ruta que manda**: la más
específica de las que casan con la URL (menos parámetros gana; a igualdad, más
literal). Es una derivación del enrutador, no una lista. Cobrado por la ablación
`AB-C3-especificidad`, que devuelve ese caso a NO-DETECTADO al quitarla.

### Que ningún rojo sea prestado

Dos comprobaciones, porque «se puso rojo» no es «se puso rojo por esto»:

1. **Ancla única por construcción.** Cada mutación se localiza por los
   **offsets del nodo decorador en el AST** del fichero, no por búsqueda de
   texto. Dos endpoints distintos tienen offsets distintos: no hay forma de que
   una mutación caiga sobre el ancla de otra. Si el decorador no aparece donde el
   AST dice, el arnés **levanta** en vez de dar el caso por bueno.
2. **Atribución de cada hallazgo.** En cada caso se comprueba que **todos** los
   hallazgos emitidos nombran al endpoint mutado (su path, su URL concreta o su
   clave `módulo.función`). Un solo hallazgo ajeno marca el caso como
   `ancla_unica: false` y lo pone en FALLO.

Medido: **0 casos con hallazgos ajenos** en los 40. Ningún rojo es prestado.

### Ablaciones (necesidad): 8 cobradas

Se cobra una ablación sólo si **el caso deja de detectarse**, y sobre el caso que
**sólo ese control** ve.

| ablación | caso que deja de detectarse | qué se quita |
|---|---|---|
| `AB-C1C2` | `ALI-auth.change_password_submit` | método seguro + exigencia de método de escritura + atribución del sondeo |
| `AB-C1bis` | `ADV-mudo` | la red «método de escritura sin evidencia» |
| `AB-C3` | `PUT-auth.change_password_submit` | el contrato de cliente |
| `AB-C3-especificidad` | `PUT-admin.admin_users_new_submit` | la regla de «la ruta que manda» |
| `AB-F1` | `ALI-auth.change_password_submit` | las señales de clasificación + el suelo `espec-vacia` |
| `AB-F1-annotated` | `ADV-annotated` | el recorrido de la **anotación** |
| `AB-F1-alias` | `ADV-alias` | la resolución de **alias de importación** |
| `AB-durabilidad` | `ADV-lectura-que-escribe` | la derivación de durabilidad por el código del invocable |

`AB-durabilidad` se cobraba antes sobre los dos GET de health de la línea base;
al arreglarse el producto ya no hay ninguno, así que **pasa a cobrarse sobre el
GET inyectado**. Es mejor control: no depende de que exista un defecto en el
árbol.

**Lo que NO se puede cobrar, y consta:** C1 y C2 no son individualmente
necesarios —quitar uno deja el caso rojo por el otro—. Es redundancia
deliberada (enumeración + ejecución).

## 5. Lo que NO se midió, y en qué estado queda el job

- **No se ejecutó nada contra producción, VM105, Neo4j ni ningún despliegue.**
  Todo corre sobre `app.main.app` con proveedor `mock`, una auth DB **vacía y
  efímera** y `S9K_HEALTH_REPORT_PATH` en un temporal.
- **El job `metodos-de-escritura` ya NO nace rojo**, y la diferencia importa:
  no se ha eximido nada, se arreglaron las dos rutas. Con la base en `rc=0`, el
  contrato completo vuelve a estar bajo un check EXIGIDO (la suite del visor
  comprueba también el código de salida). **Promoverlo a check exigido nº 17 es
  decisión del operador**, y con ella el número final de puertas.
- **Profundidad de la derivación de durabilidad: un salto A SÍMBOLOS IMPORTADOS
  de `app.*`.** Los **helpers del mismo módulo tienen cero saltos y son mudos**
  (`"." not in canon`), igual que dos helpers encadenados y los objetos
  instanciados en ejecución. Un `GET` que escribiera a través de un
  `_persistir()` local **sería invisible**, y C1bis no puede rescatarlo por ser
  un `GET`. Frontera declarada, no medida — y no se ensancha porque hacerlo
  enrojecería media docena de GET de administración por el `mkdir` de
  `admin._get_db_path`.
- **La primitiva que se reporta es la PRIMERA encontrada, no la más grave**
  (`mkdir` antes que `write_text` + `os.replace`). Sirve para atribuir, no para
  calificar el daño.
- **Formas de declarar cuerpo que la clasificación NO ve**: anotación como
  cadena, alias de tipo reutilizado, `*args`/`**kwargs`. Quedan cubiertas por
  C1bis **en cuanto el endpoint va montado con método de escritura**; sobre un
  `GET`, no las ve nadie.
- **Verbos exóticos** (`TRACE`, `PROPFIND`…) sobre estos endpoints: no se
  sondean aquí.
- **Documentación de otros carriles que este arreglo deja obsoleta, declarada y
  NO tocada**: `viewer/app/routers/chassis_operations.py:9-17`, `docs/80` y el
  docstring de `test_el_panel_no_ejecuta_healthchecks_ni_escribe_el_informe`
  describen que `/admin/health` escribe dentro del `GET`. Ya no es cierto. Sus
  aserciones siguen siendo válidas (hablan del panel B), pero el texto miente y
  **corregirlo es de ese carril**, no de éste.
