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
| **F1** | firma y cuerpo del manejador (`inspect.signature` + AST) | **capacidad de escritura**: parámetros `Form(...)`/`Body(...)`/`File(...)`/`UploadFile`, modelos de cuerpo, `request.form()/json()/body()`, **verificación** de CSRF, y mutadores de estado durable (`app.auth`, `app.services`, `app.providers`, `app.policies`, `app.authz`) | es el código que el manejador ejecuta; escribir el handler lo declara |
| **F2** | plantillas y JS que **la propia app sirve** (`viewer/app/templates`, `viewer/app/static`) | contrato de cliente `MÉTODO + URL`: `<form method="post" action="/x">`, `fetch(url, {method})` | si la pantalla cambia, el contrato cambia con ella |
| **F3** | la app REAL (`fastapi.testclient` contra `app.main.app`) | toda afirmación termina en una petición y en **quién la atendió** | es la app que se despliega |

Ninguna enumera endpoints. **Un endpoint de escritura nuevo queda cubierto
solo**: en cuanto declara un cuerpo, valida CSRF o llama a un mutador, F1 lo
clasifica y F3 lo sondea. Y lo que no se pueda clasificar **no se calla**:
`endpoint-sin-fuente` es ROJO.

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

### Un coste declarado, a propósito

`GET /admin/health` y `GET /api/admin/health` llaman a `storage.save_report(...)`
dentro del propio `GET` (lo admite el docstring de
`viewer/app/routers/chassis_operations.py:9-17`). F1 **no** los clasifica como
escritura porque su mutador vive en `app.health`, fuera de los módulos de estado
durable vigilados. Es una **frontera declarada**, no un olvido: incluirlos
pondría roja la base por una escritura ya conocida y documentada, que no es lo
que este carril viene a arreglar. Queda anotado como deuda para quien decida
tratar «un GET que escribe» como defecto del producto.

## 3. El contrato, punto por punto

| control | afirma | hallazgo |
|---|---|---|
| **C1** (enumeración) | ningún endpoint con capacidad de escritura está montado con `GET`/`HEAD`; y tiene al menos un método de escritura | `metodo-seguro-en-endpoint-de-escritura`, `escritura-sin-metodo` |
| **C2** (ejecución) | un `GET` a la URL de una escritura **no lo atiende el manejador de escritura** | `escritura-servida-por-get` |
| **C3** (contrato de cliente) | todo formulario/`fetch` que la app sirve se puede ejecutar (ni 404 ni 405) | `contrato-de-cliente-roto` |
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

Corrida completa: **40 casos, veredicto OK**, hash del árbol idéntico antes y
después (`70ff4020…d049`).

| familia | mutación | n | resultado |
|---|---|---|---|
| **W0** | árbol limpio | 1 | VERDE |
| **MET-\<endpoint\>** | `@router.post` → `@router.get` | **13/13** | **ROJO** por `metodo-seguro-en-endpoint-de-escritura` nombrando al endpoint. Corroborado por C2 en 9/13 y por C3 en 12/13 |
| **ALI-\<endpoint\>** | se **añade** `@router.get(<misma ruta>)` | **13/13** | **ROJO** por `metodo-seguro-en-endpoint-de-escritura`. Corroborado por C2 en 9/13 |
| **PUT-\<endpoint\>** | `@router.post` → `@router.put` | 13 | 12 detectados por C3; **1 NO-DETECTADO**, ver §5 |

Los 13, nombre a nombre: `login_submit`, `logout`, `change_password_submit`,
`admin_users_new_submit`, `admin_user_update`, `admin_user_unlock`,
`admin_revoke_sessions`, `admin_partidas_grant`, `admin_partidas_revoke`,
`select_partida`, `reviews_console.decide`, `v3_review.decide`, `v3_review.undo`.

Los 4 casos en que C2 no corrobora (`login_submit`, `change_password_submit`,
`admin_users_new_submit`, `admin_user_update`) son **exactamente** los endpoints
cuyo path comparte una pantalla `GET`: al mutar, la petición la sigue atendiendo
el manejador de lectura y C2 no puede pronunciarse. El rojo lo da C1, que no
depende del enrutado. **Se registra, no se disimula.**

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

### Ablaciones (necesidad)

Se cobra una ablación sólo si **vuelve VERDE un caso que estaba ROJO**, y sobre
el caso que **sólo ese control** detecta —medir necesidad desde un caso que otros
controles también cubren es lo que ya costó una ronda en `docs/83`:

| ablación | caso | qué se quita | resultado |
|---|---|---|---|
| `AB-C1C2` | `ALI-change_password_submit` | el filtro de método seguro, la exigencia de método de escritura y la atribución del sondeo | **COBRADA** (`rc=0` con un alias `GET` sobre una escritura en el árbol) |
| `AB-C3` | `PUT-change_password_submit` | el contrato de cliente | **COBRADA** (`rc=0` con el formulario roto) |
| `AB-F1` | `ALI-change_password_submit` | las tres señales de clasificación (cuerpo, CSRF, mutador) y el suelo `espec-vacia` | **COBRADA** (`rc=0`: sin clasificación no hay nada que vigilar) |

El caso `ALI` es el que aísla a C1/C2: el `post` original sigue ahí, así que el
formulario de la plantilla sigue funcionando y C3 calla. El caso `PUT` aísla a
C3: el método sigue siendo inseguro, así que C1/C2 callan.

**Lo que NO se puede cobrar, y consta:** C1 y C2 no son individualmente
necesarios —quitar uno deja el caso rojo por el otro—. Es redundancia
deliberada (enumeración + ejecución), y decirlo es más honesto que fabricar un
caso artificial que sólo uno pudiera ver.

## 5. Lo que NO se midió

- **No se ejecutó nada contra producción, VM105, Neo4j ni ningún despliegue.**
  Todo corre sobre `app.main.app` con proveedor `mock` y una auth DB **vacía y
  efímera** en un temporal.
- **Rutas ensombrecidas.** `PUT-admin_users_new_submit` sale `NO-DETECTADO`: el
  `POST /admin/users/new` del formulario lo captura `POST
  /admin/users/{user_id}` (`user_id="new"`), así que no hay 405 que ver y C3 no
  puede actuar. Consta con nombre y apellidos en el artefacto
  (`put_no_detectados`). La mutación equivalente hacia `GET` **sí** se detecta
  (caso `MET-admin_users_new_submit`, por C1).
- **Un `GET` que escribe fuera de los módulos de estado durable vigilados** (§2):
  declarado, no cubierto.
- **Verbos exóticos** (`TRACE`, `PROPFIND`…) sobre rutas de escritura: no se
  sondean aquí; el censo ya afirma conjunto cerrado sobre los montajes estáticos,
  no sobre estos endpoints.
- **La protección de rama.** Este carril deja el job creado y verde; convertirlo
  en check exigido nº 17 es decisión del operador. Mientras tanto, la suite
  `viewer/tests/test_metodos_escritura_http.py` ya entra por los tests del visor.
