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
   por los `import` del módulo, así que `Annotated`, los alias y las anotaciones
   como cadena entran. Casos `ADV-annotated`, `ADV-alias`, `ADV-clasico`.
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

Cifra de la base (`aaf9695` + este carril): **70 rutas montadas, 13 de escritura,
57 de lectura, 22 contratos de cliente (13 de escritura)**, especificación
**VERDE** (`rc=0`, cero hallazgos).

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
`os.chmod`, `open(..., "w")`, SQL de escritura, `commit`. Un salto de
profundidad, y **sólo dentro de código del proyecto**: seguir a `pathlib` o a la
biblioteca estándar declaraba «mutador» cualquier cosa —medido: 12 rutas de
lectura marcadas por error antes de acotarlo—.

**Consecuencia, y es un ROJO REAL sobre esta base:** `GET /admin/health` y
`GET /api/admin/health` llaman a `app.health.storage.save_report` dentro del
propio `GET` (`viewer/app/routers/health_admin.py:28,40`), que hace `mkdir` +
`write_text` + `os.replace` + `chmod 0600`. Salen como **`lectura-que-escribe`**
—un motivo propio, para no confundirlos con «una escritura mal montada»— y la
especificación termina con `rc=1`. **El job nace ROJO por ellos, a propósito.**
Sacar el `save_report` del GET cambia el comportamiento del panel de operaciones
(que lee el último informe guardado), y esa decisión es del operador, no de este
carril. Registrado con evidencia y fecha en
`viewer/tests/test_metodos_escritura_http.py` (2026-08-18), donde impide que un
check **exigido** se ponga rojo por un defecto que este carril no puede
arreglar, pero **no** lo silencia: cualquier lectura-que-escribe NUEVA rompe esa
suite.

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

Corrida completa: **44 casos, veredicto OK, 0 en fallo**, hash del árbol
idéntico antes y después (`65f6b300…3d7a`), **8 ablaciones cobradas**.

| familia | mutación | n | resultado |
|---|---|---|---|
| **W0** | árbol limpio | 1 | **ROJO, y correctamente**: 2 `lectura-que-escribe` (los GET de health). Ningún otro hallazgo |
| **MET-\<endpoint\>** | `@router.post` → `@router.get` | **13/13** | **ROJO** por `metodo-seguro-en-endpoint-de-escritura` nombrando al endpoint. Corroborado por ejecución en 9/13 y por contrato de cliente en **13/13** |
| **ALI-\<endpoint\>** | se **añade** `@router.get(<misma ruta>)` | **13/13** | **ROJO**, mismo motivo. Corroborado por ejecución en 9/13 |
| **PUT-\<endpoint\>** | `@router.post` → `@router.put` | **13/13** | **detectados por C3**, incluido `admin_users_new_submit`, que antes se escapaba (ver abajo) |
| **ADV-annotated / -alias / -clasico** | endpoint de escritura **NUEVO** con `Annotated[str, Form()]` / alias de `Form` / `Form` clásico, montado con `@router.get` | 3/3 | **ROJO** por `metodo-seguro-en-endpoint-de-escritura` |
| **ADV-mudo** | `POST` nuevo **sin ninguna evidencia** clasificable | 1/1 | **ROJO** por `metodo-de-escritura-sin-evidencia` (la red que no depende de F1) |

Los 15 endpoints de escritura, nombre a nombre: `login_submit`, `logout`,
`change_password_submit`, `admin_users_new_submit`, `admin_user_update`,
`admin_user_unlock`, `admin_revoke_sessions`, `admin_partidas_grant`,
`admin_partidas_revoke`, `select_partida`, `reviews_console.decide`,
`v3_review.decide`, `v3_review.undo` —los 13 con método de escritura, mutados
uno a uno— más `admin_health_panel` y `api_admin_health`, que **no tienen ningún
`post` que cambiar** (son los GET que escriben) y por eso no generan casos
MET/ALI/PUT: su ausencia consta en el artefacto
(`endpoints_sin_metodo_de_escritura`), no se calla.

Los 4 casos en que la ejecución no corrobora (`login_submit`,
`change_password_submit`, `admin_users_new_submit`, `admin_user_update`) son
**exactamente** los endpoints cuyo path comparte una pantalla `GET`: al mutar, la
petición la sigue atendiendo el manejador de lectura y C2 no puede pronunciarse.
El rojo lo da C1. **Se registra, no se disimula.**

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
**sólo ese control** ve. (Ya no puede cobrarse por «rc=0»: el árbol limpio sale
rojo por los GET de health.)

| ablación | caso que deja de detectarse | qué se quita |
|---|---|---|
| `AB-C1C2` | `ALI-auth.change_password_submit` | método seguro + exigencia de método de escritura + atribución del sondeo |
| `AB-C1bis` | `ADV-mudo` | la red «método de escritura sin evidencia» |
| `AB-C3` | `PUT-auth.change_password_submit` | el contrato de cliente |
| `AB-C3-especificidad` | `PUT-admin.admin_users_new_submit` | la regla de «la ruta que manda» |
| `AB-F1` | `ALI-auth.change_password_submit` | las señales de clasificación + el suelo `espec-vacia` |
| `AB-F1-annotated` | `ADV-annotated` | el recorrido de la **anotación** (vuelve el superviviente) |
| `AB-F1-alias` | `ADV-alias` | la resolución de **alias de importación** |
| `AB-durabilidad` | los 2 `lectura-que-escribe` de la base | la derivación de durabilidad por el código del invocable |

Las tres últimas son la prueba de que las correcciones de esta ronda son
**cargantes**: al quitarlas, el defecto vuelve a ser invisible.

**Lo que NO se puede cobrar, y consta:** C1 y C2 no son individualmente
necesarios —quitar uno deja el caso rojo por el otro—. Es redundancia
deliberada (enumeración + ejecución), y decirlo es más honesto que fabricar un
caso artificial que sólo uno pudiera ver.

## 5. Lo que NO se midió, y en qué estado queda el job

- **No se ejecutó nada contra producción, VM105, Neo4j ni ningún despliegue.**
  Todo corre sobre `app.main.app` con proveedor `mock` y una auth DB **vacía y
  efímera** en un temporal.
- **El job `metodos-de-escritura` nace ROJO**, y es un rojo REAL: las dos
  `lectura-que-escribe` de `health_admin.py`. Arreglarlo —sacar `save_report`
  del GET— cambia el comportamiento del panel de operaciones, que lee el último
  informe guardado; es decisión del operador y no de este carril.
- **Por eso NO se propone todavía como check exigido.** Un check obligatorio
  que nace rojo enseña a la gente a no mirarlo. La promoción va en el mismo
  commit que cierre el punto anterior, y ese commit debe dejar
  `ci_running_but_not_required` con **una sola entrada** y `ci_checks_required`
  en **16**.
- **Profundidad de la derivación de durabilidad: un salto**, y sólo dentro de
  `app.*`. Una escritura escondida a dos saltos, o a través de un objeto
  guardado en un atributo, no se ve. No hay caso que lo mida: es una frontera
  declarada, no una medida.
- **Verbos exóticos** (`TRACE`, `PROPFIND`…) sobre estos endpoints: no se
  sondean aquí.
- **Cobertura de la clasificación**: los casos `ADV` prueban tres estilos de
  declarar cuerpo y uno sin evidencia. No prueban todas las formas imaginables
  de escribir un endpoint; lo que sí cubre a todas es la red C1bis, que no
  depende del estilo.
