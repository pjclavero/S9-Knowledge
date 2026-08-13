# 72 — Una sola autoridad sobre `admin_full` (carril P0-AUTH)

**Rama:** `feat/p0-admin-full-declarado` · **Base:** `main = e0305cc`

Bloqueo de seguridad previo a construir más producto encima de esta
autorización. El hallazgo no se redescubre aquí: lo demostraron dos agentes
independientes y está en `docs/66-calidad-de-datos-v2.md §1-3`. Este documento
cuenta qué se ha **cerrado**, con qué evidencia y con qué límites.

Principio que gobierna el resto: *una afirmación no es evidencia porque haya un
test verde*. Todo lo que se afirma aquí tiene una mutación que lo pone rojo en
`scripts/calibracion/mutaciones_p0_auth.py`, y además una **ablación** que
comprueba que el control es necesario: si quitarlo no cambia ningún resultado,
no puede cobrarse como defensa.

---

## 1. Lo que había: una potestad total, tres autoridades, cero declaraciones

`admin_full` **no es una dimensión más**: es el bypass TOTAL. Se salta
workspace, aislamiento entre partidas, nivel de visibilidad, `known_by` y el
tope de sesión, y en `filtered_provider._scope_workspaces()` devuelve `None`, es
decir **quita también el acotado en el propio Cypher**, no sólo el filtro
posterior. Lo único que no salta es una `visibility` inválida y `deny`.

Llegaba por **tres caminos** y ninguno estaba declarado en el registro M5b:

| vía | dónde | qué era |
|---|---|---|
| el campo | `ctx.admin_full` | la dimensión, sin cadena declarada |
| el rol, otra vez | `authz/scope.py` → `bool(ctx.admin_full) or ctx.role == "admin"` | una **segunda** potestad, evaluada fuera del constructor |
| un flag de despliegue | `authz/context.py` → `admin_full=True` si `S9K_AUTH_ENABLED` es falso | una variable de entorno como autoridad de facto |

Y una **cuarta**, que apareció al mirar: `UNRESTRICTED = VisibilityScope(
ViewerContext(role="admin", admin_full=True))` en `authz/scope.py` — un contexto
de potestad total **fabricado a mano**, invisible para quien fuera a buscar
"quién concede `admin_full`" al sitio donde se concede.

`can_view_reference` (única llave del nivel `reference`) y `character_knowledge`
(concede saltándose `known_by`) tampoco estaban declaradas.

---

## 2. Lo que hay: una sola cadena

```
principal autenticado → build_viewer_context() → admin_full → consumidores
```

- **`role == "admin"` es ENTRADA del constructor, nunca un bypass lateral.**
  `scope.py` deja de reevaluar el rol. Que el rol conceda es correcto; que lo
  conceda *dos veces, en dos sitios*, no: el día que se revoque el bypass en el
  constructor, la línea de `scope.py` lo seguiría concediendo y la revocación
  quedaría incompleta sin que nada se pusiera rojo.
- **`AUTH_ENABLED=false ⇒ admin_full=True` eliminado semánticamente.** Sin
  autenticación no hay principal, luego no hay autoridad: **mínimo privilegio**.
- **No se ha inventado un modo dev.** Un interruptor nuevo sería la misma
  autoridad lateral con otro nombre. Si algún día hace falta, tendrá que
  declararse en el registro como una dimensión más.
- **`UNRESTRICTED` pasa por el productor** (`build_internal_context(motivo=…)`).
  El motivo es obligatorio: no hace la llamada más segura, hace que quede
  escrito por qué un camino sin usuario recibe la potestad máxima.
- **`deny` sigue siendo terminal**: la regla 0 del motor va deliberadamente
  ANTES del bypass. `deny + admin_full ⇒ DENY`. Un bypass puede saltarse reglas
  de permiso; no puede convertir un estado terminal en permiso ni un dato
  inválido en válido.
- **Revocación real**: el rol se relee de `auth.db` en cada petición. Retirar
  admin ⇒ la **siguiente** petición pierde `admin_full`, sobre la sesión ya
  abierta, sin nuevo login.

---

## 3. AVISO PARA QUIEN ESCRIBA UN TEST O UN BANCO DE MEDIDA

**`S9K_AUTH_ENABLED` vale `False` por defecto** (`viewer/app/auth/config.py`).
Antes de este carril, eso significaba que **todo proceso que no fijara la
variable corría con el bypass total puesto**: un test, un script, un banco de
medida o un despliegue recién montado medían el sistema *sin ninguna barrera
activa* creyendo que medían el sistema. No es hipotético: el carril de
saturación encontró **dos de sus bancos** en esa situación.

Qué obtiene **hoy** quien no fije la variable:

| | antes | ahora |
|---|---|---|
| `role` | `"public"` | `"anonymous"` |
| `admin_full` | **`True`** | `False` |
| `can_view_secret` / `can_view_reference` | irrelevante (bypass) | `False` |
| `allowed_partida_ids` | irrelevante (bypass) | vacío |
| `max_visible_session` | irrelevante (bypass) | `0` |
| qué ve | **todo** | sólo `player` de la capa juego de su workspace |

Es decir: **mínimo privilegio**. Si un banco necesita ver contenido elevado,
tiene que autenticarse de verdad, no dejarse la variable sin fijar. Fijado en
`viewer/tests/test_p0_autoridad_admin_full.py::
test_el_valor_POR_DEFECTO_de_S9K_AUTH_ENABLED_no_concede_nada`.

Efecto colateral medido y aceptado: el visor abierto deja de servir material
`visibility=reference`. Un solo test lo notó
(`test_api.py::test_api_search_finds_tamori`), y ese test sólo pasaba porque el
bypass estaba puesto; ahora afirma lo contrario y es un testigo del cierre.

---

## 4. La cuarentena se ha ELIMINADO, no congelado

El carril J dejó la cuarentena "congelada": una lista de tres nombres exentos de
la red inversa, comparada contra una copia congelada y contra un tamaño escrito
aparte. Eso frenaba el crecimiento accidental, pero seguía siendo **un sitio
donde escribir un nombre para que la red deje de mirarlo** — y ese sitio se
usó: un revisor añadió un bypass nuevo *y su nombre a la cuarentena en el mismo
commit* y la suite pasó verde, 92 passed.

Las tres dimensiones están ahora declaradas en `app/policies/registry.py` con su
cadena completa (autoridad, productor, almacenamiento, consumidores, semántica
de ausencia y de valor inválido, **revocación**, prueba negativa y prueba E2E
HTTP), así que la lista de exentas es vacía **y ya no existe como constante**.
Sin lista de exentas, la única salida de una dimensión nueva es declararla.

Hay además un test que impide que la salida de emergencia se reabra en
silencio: si vuelve a aparecer en ese fichero una constante con forma de lista
de exentas, se pone rojo. Ningún test puede impedir que un humano borre un test;
lo que sí puede es que reabrir la puerta deje de ser un efecto colateral y pase
a ser un cambio explícito y visible en el diff.

---

## 5. La red inversa pasa de `grep` a AST

La red anterior era sintáctica y buscaba dos formas literales: `node.get("x")` y
`(?:ctx|self)\.x`. Está **medido** que esto pasaba VERDE con la suite entera:

```python
_c = ctx
if _c.puerta_trasera:
    return _ALLOW
```

Un alias local de una línea desactivaba la red. Y no hace falta mala intención:
renombrar `ctx` a `contexto`, o extraer una regla a una función cuyo parámetro
se llame distinto, produce el mismo agujero.

Ahora se lee el **árbol** (`viewer/tests/authz_lecturas.py`). La regla está
deliberadamente **sobre-aproximada**: cuenta como consumo cualquier acceso a un
atributo cuyo nombre sea un campo de `ViewerContext`, venga del objeto que
venga. Sobre-contar sólo obliga a declarar de más; sub-contar deja una dimensión
decidiendo sin cadena.

### Lo que este instrumento NO ve (límite declarado, no cobertura fingida)

1. acceso **dinámico** con nombre calculado: `getattr(ctx, "admin" + "_full")`
   (se detecta `getattr(x, "literal")`, no una expresión);
2. consumo **indirecto**: pasar el contexto entero a una función de otro módulo
   que decida allí — el barrido cubre `policies/engine.py` y `policies/models.py`
   y nada más;
3. recorrido por diccionario: `dataclasses.asdict(ctx)["admin_full"]`.

Las tres son **evasiones deliberadas**: hay que escribirlas a propósito. El
alias local, que es el caso accidental, sí queda cerrado. Esa es toda la mejora
reclamada, ni una línea más.

---

## 6. Calibración: 11 mutaciones, dos fases cada una

`python3 scripts/calibracion/mutaciones_p0_auth.py`

Cada mutación reintroduce un defecto real y se mide dos veces:

- **ablación (necesidad)** — la suite *sin* los controles de este carril. Se
  espera VERDE: ése es el falso negativo, la prueba de que nadie más veía el
  defecto. Si sale ROJO, el control no es la única defensa y el arnés lo dice
  con esas palabras en vez de callarlo.
- **completo (suficiencia)** — la suite entera. Se espera ROJO, con el nombre de
  los tests que se ponen rojos.

Y después se revierte siempre —también si pytest revienta— y se comprueba que el
árbol vuelve a verde.

Un arnés que pasa con 0 casos está roto: aquí se exige que pytest haya recogido
tests en las dos fases, y una fase que no recoja nada se declara ERROR. Una
mutación cuyo patrón no aparezca en el fichero también es ERROR: *"no se pudo
mutar" no es "no hay defecto"*.

### Resultado medido (suite del visor: 1220 tests al medirlas, verde de partida y tras revertir; hoy 1222 con los casos de S1)

| # | mutación | ablación | completo | test(s) rojo(s) |
|---|---|---|---|---|
| M1 | borrar `admin_full` del registro | VERDE (1069) | **ROJO** (5) | red AST + productor + prueba de ausencia + monotonía |
| M2 | reintroducir `role == "admin"` en `scope.py` | VERDE (1204) | **ROJO** (1) | `test_la_segunda_via_al_bypass_total_tiene_testigo` |
| M3 | reintroducir `AUTH_ENABLED=false ⇒ admin_full` | VERDE (1182) | **ROJO** (4) | `test_api_search_…`, `test_desactivar_la_autenticacion_no_concede_potestad`, `test_el_valor_POR_DEFECTO_…`, `test_con_la_autenticacion_desactivada_…` |
| M4 | quitar la revocación (rol congelado en la sesión, caché por token) | VERDE (1189) | **ROJO** (1) | `test_retirar_el_rol_admin_retira_admin_full_en_la_siguiente_peticion` |
| M5 | `admin_full` supera un `deny` | **ROJO** (1) | **ROJO** (3) | ver nota abajo |
| M6 | dimensión nueva + su nombre en la cuarentena, mismo commit | VERDE (1069) | **ROJO** (2) | red AST + `test_no_reaparece_ninguna_lista_de_EXENTAS_en_esta_red` |
| M7 | `ViewerContext` a mano esquivando el productor | VERDE (1190) | **ROJO** (1) | `test_el_constructor_de_contexto_es_el_unico_productor` |
| M8 | **`_scope_workspaces()` abierto** (superviviente del carril J) | VERDE (1204) | **ROJO** (1) | `test_el_acotado_por_workspace_…_solo_se_levanta_para_admin_full` |
| M9 | **bypass por alias local** | VERDE (1069) | **ROJO** (1) | red AST del contexto |
| M10 | **(R8) `models.ViewerContext(...)`, import calificado** | VERDE | **ROJO** (1) | `test_el_constructor_…_unico_productor` |
| M11 | **(R7) `dataclasses.replace(ctx, admin_full=True)`** | VERDE | **ROJO** (1) | `test_el_constructor_…_unico_productor` |

Además, **M10 (R8)** y **M11 (R7)**: las dos evasiones que la revisión
independiente encontró contra M7, ambas medidas en VERDE (1211 passed) antes del
arreglo y ROJAS después. Ver §6bis.

**M5 no puede cobrarse como defensa exclusiva de este carril**, y el arnés lo
dice solo: la ablación ya sale roja por
`test_m5b2_cierre_defecto_permisivo.py::test_deny_es_terminal_tambien_para_administrador`,
que es **preexistente**. La terminalidad de `deny` ya estaba defendida; lo que
aporta este carril es el testigo **por HTTP** y la declaración en el registro.

**M4 sí es exclusiva, y mi renuncia anterior era EXCESIVA.** Este documento
declaraba que la revocación no se podía medir en aislamiento porque la mutación
tumbaba 5 pruebas ajenas. El defecto estaba en **mi mutación**, no en la
cobertura: cacheaba el rol por `user.id`, y los ids **se repiten entre tests**
(cada uno estrena su `auth.db` y crea el usuario 1), así que el caché saltaba de
un test a otro. Cacheando por **token de cookie** —aleatorio en cada login,
nunca compartido— la mutación reproduce exactamente el defecto buscado y nada
más. Medido: **1 solo rojo** (1219 passed + 1 failed), **ablación VERDE** (1189).
Es decir, `test_retirar_el_rol_admin_retira_admin_full_en_la_siguiente_peticion`
**es la defensa exclusiva de la revocación**. Lo señaló la revisión
independiente; renunciar a medir algo medible es tan poco honesto como afirmarlo
sin medirlo.

## 6bis. La cuarta autoridad se reabría escribiendo la llamada de otra forma

La revisión independiente atacó M7 —"el constructor de contexto es el único
productor"— y la abrió **por dos sitios**, las dos con la suite **VERDE (1211
passed)** y la potestad total realmente concedida (lo comprobó con control
positivo, no por lectura):

| | evasión | por qué pasaba |
|---|---|---|
| **R8** | `models.ViewerContext(role="admin", admin_full=True)` | el detector contaba `ast.Name`; calificar el import lo convierte en `ast.Attribute` |
| **R7** | `dataclasses.replace(ctx_de_viewer, admin_full=True)` | no es una llamada a `ViewerContext` en absoluto: parte de un contexto legítimo de `viewer` y le pone la potestad encima. `replace()` es la vía soportada para sortear `frozen=True` |

Es **la lección de este carril aplicada contra el propio carril**: *un nombre no
puede conceder nada*, y el detector estaba concediendo "no hay otro productor" a
cambio de que la llamada se escribiera de **una** forma concreta. Exactamente el
mismo error que la red inversa que sólo veía `ctx.foo` y no `_c.foo`.

Y una **tercera**, encontrada en la segunda ronda de revisión al pedir
expresamente más evasiones:

| | evasión | medido |
|---|---|---|
| **S1** | `replace(ctx_de_viewer, **{"admin_full": True})` | **VERDE (1220)**, `admin_full is True` |

S1 era **un descuido de una línea en mi propio arreglo**: `any(k.arg in campos
for k in nodo.keywords if k.arg)` descarta el keyword del desempaquetado, cuyo
`arg` es `None`. Desempaquetar un diccionario apagaba el detector entero.
Cerrado contando **cualquier** `replace(...)` que traiga `**`: no se puede saber
qué hay dentro, y sobre-contar sólo obliga a declarar de más — la misma
asimetría deliberada de `authz_lecturas.py`. Coste real medido: **cero falsos
positivos**, porque los 13 `replace(` de `viewer/app` son `str`/`datetime`/`os`
con argumentos posicionales o kwargs que no son campos del contexto.

Arreglado en `_fabrica_un_contexto()`: cuenta `ast.Name`, `ast.Attribute`,
`replace(campo=...)` y `replace(**desempaquetado)` — **cuatro formas**, no tres
como decía este documento y el propio docstring. Calibrado en las dos
direcciones: **siete** formas que deben detectarse y cuatro que **no** deben
producir falso positivo, porque un detector que marcase cualquier `.replace()`
del repositorio sería imposible de satisfacer y acabaría desactivado.

El detector es `ast.walk` sobre `APP.rglob("*.py")`, así que es **independiente
del fichero por construcción**; la revisión lo confirmó además **por medida**,
reproduciendo R8 y R7 en `filtered_provider.py` —otro fichero— y obteniendo rojo
**del detector**, no de un testigo de comportamiento.

### Defectos del propio arnés, encontrados calibrándolo

1. informaba `0 rojos` en **todas** las mutaciones: comparaba
   `ln.startswith("FAILED")` contra líneas **coloreadas** por pytest. Daba el
   semáforo correcto y **ninguna evidencia**;
2. los `--deselect` se ignoraban **en silencio**, porque el nodeid va relativo al
   *rootdir* y se le pasaba relativo al *cwd*. La ablación de M2, M3 y M8 corría
   con el control puesto, salía roja, y yo lo estaba leyendo como *"el defecto lo
   ve también otro control"*. Es la misma familia que el hallazgo de
   `get_visibility_context`: **un instrumento desconectado que no se queja**,
   cometido por el arnés que persigue exactamente eso;
3. corregido con una comprobación mecánica: si la ablación no recoge **menos**
   tests que la corrida completa, no ha ablacionado nada y se declara ERROR.
4. **un rojo por la razón equivocada, que casi cierra un hallazgo en falso.** Al
   reproducir R7 lo coloqué primero en `sees_operational_detail` en vez de en
   `UNRESTRICTED`. Salió **ROJO** — y por un momento pareció que el hallazgo del
   revisor ya estaba cubierto. No lo estaba: lo que se puso rojo fue el
   **testigo de comportamiento** (`test_la_segunda_via_al_bypass_total_tiene_testigo`),
   porque esa colocación sí cambia lo que ve un usuario; el **detector** seguía
   sin ver nada. Al moverlo a `UNRESTRICTED`, donde la fabricación del contexto
   no altera ningún comportamiento observado, reapareció el VERDE.

   Es la misma familia que todo lo demás de este carril: **un rojo no es
   evidencia de que la barrera que crees estar probando funcione**, igual que un
   verde no es evidencia de que no haya defecto. Hay que mirar *cuál* se pone
   rojo. Un rojo por el motivo equivocado es más peligroso que un verde, porque
   el verde invita a seguir buscando y el rojo invita a parar.

---

## 7. Lo que este carril NO cierra

- **`character_knowledge` es una vía LATENTE, no inocua.** La cadena de petición
  (`authz/dependencies.py`) no la puebla: hoy llega siempre vacía, y el único
  productor que la rellena (`context_for_simulated_character`) no lo invoca
  ninguna ruta. Es la forma de H-A. Pero conviene ser preciso sobre **cuánto**
  concede si alguien la puebla: concede por `id` **saltándose `known_by` y la
  regla de nivel**, y su otra condición —`active_character` legible— **sí la
  puebla la cadena** desde la concesión de partida. Es decir, **basta con que un
  productor la rellene para que la vía se estrene entera**; no hace falta nada
  más. Se declara así —con su prueba HTTP midiendo justo esa inercia— en vez de
  retirarla, porque el modo "ver como personaje" la necesita. El día que se
  conecte un productor, esa prueba se pone roja y obliga a declarar autoridad y
  revocación **antes** de estrenarla.

## 8. Observaciones de la revisión independiente (declaradas, no cerradas)

Ninguna bloquea; todas son ciertas y quedan escritas para que nadie las
redescubra creyendo que eran desconocidas.

- **EL DETECTOR NO SIGUE ALIAS DEL CONSTRUCTOR** (S2/S5, segunda ronda). Esto
  pasa en **VERDE**, con `UNRESTRICTED.ctx.admin_full is True` comprobado por
  control positivo:

  ```python
  _VC = ViewerContext
  UNRESTRICTED = VisibilityScope(_VC(role="admin", admin_full=True))
  ```

  **Medido: 1222 passed**, en `authz/scope.py` (S2) y también en
  `filtered_provider.py` (S5) — es independiente del fichero, como el propio
  detector. `from app.policies.models import ViewerContext as VC` tiene el mismo
  efecto. Es decir: **renombrar el constructor reabre la cuarta autoridad
  lateral en cualquier fichero.**

  Y conviene decir lo incómodo con todas las letras: el alias local es
  exactamente la forma que este carril declaró *"el caso accidental, y es el que
  se cierra"* al endurecer la **otra** red AST (`authz_lecturas.py`, M9). Allí se
  cerró; **aquí no**. Cerrarlo exigiría seguir asignaciones dentro del módulo, y
  se ha decidido dejarlo: es un límite real de un detector sintáctico. Dejarlo
  abierto es legítimo, callarlo no lo sería. Está anclado en
  `test_el_LIMITE_del_detector_esta_donde_se_declara_que_esta`, que se pondrá
  rojo el día que se cierre, para que esta declaración no sobreviva al hecho que
  describe.
- **El campo `prueba_http` concede por el nombre.** Sólo se comprueba que la
  función **exista** y que el fichero **mencione** `TestClient`. Repuntarla a un
  test irrelevante deja todo verde. En un carril cuyo lema es *un nombre no puede
  conceder nada*, ese campo concede "está probada por HTTP" a cambio de un
  nombre. Mismo diagnóstico que H6-1 (mencionar no es probar), un nivel más
  arriba.
- **`consumer`, `storage` y `revocation` no se validan en absoluto.** Son prosa.
  `authority` se comprueba con `"servidor" in campo.authority` —un **substring**,
  no un vocabulario cerrado— y la prueba de ausencia/invalidez sigue siendo
  `campo.name in corpus`, es decir un `grep`. El registro es más fuerte que
  antes, pero **no todos sus campos son ejecutables**; los que no lo son están
  aquí nombrados uno a uno.
- **`test_no_reaparece_ninguna_lista_de_EXENTAS` es un guardián por NOMBRE.**
  Usa una expresión regular sobre nombres de constante: llamar a la lista
  `_SALTAR` la evade. Es **defensa en profundidad, no barrera** —su valor es que
  reabrir la puerta salga en el diff—, y así hay que leerlo.
- **`simulated` esquiva la degradación por autenticación desactivada.** Con
  `simulated=True` el rol de la petición se toma por bueno sin autenticar: no
  concede `admin_full`, pero sí `can_view_reference` y `can_view_future`. Hoy es
  **inalcanzable** —ninguna ruta invoca `context_for_simulated_character`, que
  además fija `auth_enabled=True`—, pero es **una excepción escrita dentro del
  propio cierre y no declarada en el registro**. Queda declarada aquí.
- **Los tres límites de la red AST son ciertos y explotables** (R1/R2/R3 del
  revisor: bypass total con la suite verde). Están bien declarados y **no
  cerrados**, que es distinto. Un matiz suyo que corrige mi redacción: **R2 no es
  una "evasión deliberada"** —mover una decisión a `filtered_provider.py` es
  refactor normal, y `MODULOS_DE_POLITICA` no tiene descubrimiento automático—,
  así que el riesgo real es el **descuido**, no la mala fe.
- **Dos averías menores del arnés, no corregidas**: `recogidos = passed+failed`
  **no cuenta `error`**, así que una mutación que rompa la colección puede
  degradar a "0 recogidos" y parecer arnés roto en vez de mutación inválida; y la
  reversión **no se verifica por hash**, sólo se reescribe el texto original.
- **El caso de ausencia de `admin_full` en la red de monotonía es débil** y está
  dicho en el propio código: es una concesión booleana cuya ausencia es `False`,
  así que "quitarla no enseña más" se cumple por construcción. Lo que sostiene
  esa dimensión no es esa línea, sino la cadena HTTP completa (concesión, uso y
  revocación) y las mutaciones que la reintroducen por cada una de sus vías.
- **Que la consulta salga sin acotar no demuestra que se filtren datos.** El
  testigo de `_scope_workspaces()` fija el ACOTADO, no la ausencia de fuga: el
  filtrado posterior por política podría taparla, y eso no se comprueba.
- **`get_filtered_provider` llama a `get_visibility_context(request)` como
  función normal, NO vía `Depends`** (`viewer/app/authz/dependencies.py:168`).
  Consecuencia, medida en el carril de saturación: sobrescribir
  `get_visibility_context` con `app.dependency_overrides` **no surte ningún
  efecto** sobre `/api/graph` y las demás rutas de datos — el control no colapsa
  y el banco certifica en falso que la política se ejercía. Las pruebas de este
  carril **no** usan ese punto de inyección (sustituyen el proveedor base y
  atraviesan la cadena real con cookie de sesión), y eso está **demostrado**, no
  afirmado, en `test_el_control_de_autorizacion_COLAPSA_en_api_graph`. **No se ha
  cambiado el punto de inyección**: hacerlo toca cómo se construye el proveedor y
  el operador quiere decidirlo antes. Queda como propuesta con su evidencia. La
  revisión independiente lo reprodujo por su cuenta —sobrescribió
  `get_visibility_context` y `/api/graph` siguió devolviendo nodos— y dictamina
  que dejarlo sin tocar es correcto: **deuda declarada, no bloqueante**. A raíz de
  su única pega, la prueba de colapso ya **no acepta `404`** como rama
  alternativa: exige **200 con cero nodos**, porque un 404 puede venir de una ruta
  mal escrita y dejaría pasar el test sin que la política hubiera intervenido.
- **`S9K_AUTH_ENABLED` sigue valiendo `False` por defecto.** Que la barrera esté
  apagada por defecto es una decisión de despliegue discutible y no se ha
  tocado; lo que se ha cerrado es que apagarla **conceda la potestad máxima**.
