# 83 — El censo de rutas como PUERTA: la configuración canónica vive en código

**Qué se cablea:** el job `route-map-gate` de `ci.yml` («Censo de rutas
(configuracion canonica en codigo)»).
**Qué lo sostiene:** `scripts/route_map/gate.py` (la puerta) y
`scripts/route_map/calibrate_gate.py` (su control negativo).
**Qué NO hace este carril:** añadirlo a la protección de rama. Sería el check
exigido nº 16 y lo decide el operador.

> **Lo que la puerta afirma, exactamente: «lo declarado existe, y sólo lo
> clasificable está montado».** NO afirma «no hay rutas de más». Una ruta nueva,
> no declarada por nada pero **bien autenticada**, pasa en verde, y cubrirlo
> exigiría la lista que este carril tiene prohibida. Lo que sí se cierra: una
> ruta de más que además **se salte la autorización** —un alias de una `/api` que
> esquiva el `Depends` del `include_router`, por ejemplo— acaba en
> `rutas_sin_auth`, que la puerta trata como hallazgo DURO. Medido en modo
> completo con sonda.

---

## 1. La condición que había que cumplir

El censo (`docs/68`) ya daba `rc=0` legítimo, con `/static` **caracterizado** y
cero entradas opacas, así que no quedaba obstáculo técnico para hacerlo puerta.
La condición del operador era otra:

> La configuración que define qué rutas/router deben existir tiene que vivir en
> **código o en una fuente canónica ejecutable**, no en una lista documental
> mantenida aparte. No aceptaría como required un censo cuya lista de referencia
> haya que recordar actualizar manualmente. Eso recrearía exactamente el problema
> de las antiguas whitelist de ramas.

El precedente está en el repo dos veces:

1. la CI enumeraba prefijos de rama y pasó a `branches: ['**']` — *«ya no estamos
   intentando enumerar el futuro»*;
2. `viewer/tests/test_provider_authz_fields_contract.py:94-111` documenta la
   **cuarentena congelada** de dimensiones de autorización: un revisor añadió un
   bypass nuevo **y su nombre a la lista en el mismo commit**, y la suite pasó
   verde. No se reforzó la lista: **se eliminó**.

> **Una lista donde escribir un nombre para dejar de mirar es el antipatrón. Una
> aserción que se pone roja cuando el mundo cambia es la solución.**

## 2. Dónde vive la configuración canónica

En **cinco fuentes que ya existían en el código por otros motivos** y que el
proceso **ejecuta**. Ninguna es una copia de nada, y por eso ninguna puede
quedarse obsoleta en silencio.

| id | fuente | qué declara | qué la mantiene al día |
|---|---|---|---|
| **D1** | descubrimiento por AST de `viewer/app/**.py` | todo módulo que asigna `X = APIRouter(...)` **a nivel de módulo** es un router declarado | crear el fichero lo declara; borrarlo lo retira. **No hay lista** |
| **D2** | `import` de esos módulos y enumeración de `router.routes` | rutas y **métodos** que cada router declara | es el propio objeto que la app incluye |
| **D3** | `app.chassis.NAV` | **nombres de ruta** que el menú exige | el visor la recorre para pintar la barra: si apuntara a una ruta inexistente, `chassis.nav_for` levanta |
| **D4** | `app.chassis.FEATURE_SLOTS` | módulo, prefijo, nombre de ruta y rol de cada hueco | `main._mount_feature_slots()` la itera al arrancar: un hueco no importable impide arrancar |
| **D5** | `chassis.FLAG_ENV_TEMPLATE` / `FLAG_ON_VALUES` / `slot_enabled` | nombre de cada interruptor de panel y qué cuenta como «encendido» | si el chasis renombra sus banderas o cambia el criterio, la puerta cambia con él; un quinto hueco entra solo |

**Por qué no se puede quedar obsoleta:** D1 se descubre recorriendo el árbol, D2
se obtiene ejecutando el `import`, y D3/D4/D5 son objetos que la aplicación usa
en tiempo de arranque. Que la declaración se desactualizara exigiría que el
código que la app ejecuta divergiera del código que la app ejecuta.

**La correspondencia con la app real se hace por IDENTIDAD del objeto endpoint**
(`id(func)`), no por path ni por nombre, y eso no es un detalle: el path que
guarda un `APIRouter` es el **relativo**, sin el prefijo que aporta
`include_router`. Comparando por texto, el enumerador AST de `route_map` declara
MUERTAS tres rutas de este árbol —`GET /item/{entity_id}`,
`GET /item/{proposal_id}`, `GET /ficha/{handle}`— que están vivas y montadas bajo
el prefijo de su hueco. Un rojo por el motivo equivocado es más peligroso que un
verde.

### Lo inesperado se CARACTERIZA, no se exime

«Ruta inesperada debe clasificarse explícitamente» no es «debe estar en una lista
blanca». Se resolvió como se resolvió `/static`: cada ruta montada recibe una
**clase derivada** —endpoint de un router declarado (identidad), módulo del árbol
`viewer/app` (fichero fuente real, vía `inspect.getsourcefile`), montaje estático
caracterizado y verificado, o entrada opaca que el censo ya declara en rojo—. Lo
que no encaja en ninguna clase es `SIN-CLASIFICAR` y pone la puerta roja. Una
ruta inyectada por una librería o generada en ejecución no encaja, y nadie tiene
que mantener nada para que eso se detecte.

## 3. El contrato, punto por punto, con la evidencia de cada ROJO

Calibración: `python3 scripts/route_map/calibrate_gate.py`. **46 casos y 15
ablaciones cobradas**, un subproceso por mutación, sobre **copias** del árbol.

| punto del contrato | caso | mutación real | motivo que sale |
|---|---|---|---|
| router declarado → montado | **G1** | se borra `app.include_router(readonly_router.router)` de `main.py` | `router-declarado-no-montado` |
| ruta declarada → existe | **G5** | inclusión **parcial** del router de auth: declara `GET /account` y la app monta todo menos esa ruta | `ruta-declarada-no-montada` |
| método declarado → coincide | **G4** | el mismo endpoint montado además con `methods=["POST"]`, que su router no declara | `metodo-declarado-no-coincide` |
| ruta/método inesperado → clasificado | **G6** | endpoint definido **fuera** de `viewer/app` y montado con `add_api_route` | `ruta-sin-clasificar` |
| **router desmontado → ROJO** | **G1** | (el mismo) | tres motivos a la vez: router, rutas y nombres |
| **ruta eliminada → ROJO** | **G2** | se borra el decorador de `GET /entities`; su nombre `entities_page` sigue declarado en `NAV` | `nombre-canonico-no-resuelve` / `ruta-inexistente` |
| **método cambiado → ROJO** | **G3** | `@router.get("/entities"…)` → `@router.post(…)`: la pantalla sigue existiendo pero deja de servir navegación | `nombre-canonico-no-resuelve` / `metodo-cambiado` |
| **configuración vacía → ROJO** | **G7** | `NAV = ()` | `configuracion-vacia` |
| **configuración ausente → ROJO** | **G8** / **G9** | falta un elemento del chasis (`del FLAG_ON_VALUES`) / no hay `chassis.py` | `configuracion-ausente` |
| **censo que no inspeccionó la app real → ROJO** | **A1–A6** | sin artefacto · `head` de otro árbol · cobertura cero · `--skip-probe` · sin `--tested` · el artefacto describe otras rutas que las que sirve la app | `censo-no-inspecciono-la-app-real` |
| censo en rojo → ROJO | **A7–A9** | `rc=3` del censo · `censo_opaco` no vacío · `rutas_sin_auth` no vacío | `censo-en-rojo` |
| **un panel encendido cuando debía estar apagado** | **G10** / **G11** | `S9K_PANEL_C_ENABLED=true` · bandera de la familia que el chasis ya no declara | `panel-encendido` |
| router declarado y **no importable** | **G12** | módulo con `router = APIRouter()` y un `import` inexistente | `router-declarado-no-montado` / `modulo-no-importable` |
| el **enumerador degrada** al desaparecer una API privada | **G13** | desaparece `effective_route_contexts` | `ruta-declarada-no-montada` (en masa) |
| **hallazgo duro RENOMBRADO** en el artefacto | **A10** | `rutas_sin_auth` → `rutas_sin_auth_v2`, con la fuga dentro | `censo-en-rojo` / `hallazgo-desconocido` |
| el vocabulario de la puerta **es el que el censo emite** | **G14** + **G14-neg** | contraste contra las claves reales de `findings`; control negativo con un duro renombrado | desajuste nombrado en las dos direcciones |

**Falsos positivos vigilados (tienen que salir VERDES):** árbol limpio (**G0**);
bandera apagada explícitamente (**FP1**); bandera con valor ininteligible, que el
chasis apaga por fallo cerrado (**FP2**); variables *parecidas* que no son de la
familia, `S9K_PANELC_ENABLED` y `S9K_PANEL_C_ENABLE` (**FP3**); un router
declarado y **vacío**, que no aporta rutas y por tanto no permite exigir montaje
de nada (**FP4**); y artefacto íntegro (**AFP**).

**Atribución:** salvo G1, cada caso rojo lo está por **un solo motivo**. G1
dispara tres porque desmontar un router incumple tres declaraciones a la vez, y
se declara como tal en vez de fingir aislamiento.

### Ablaciones (necesidad)

Se cobra una ablación **sólo si vuelve VERDE un caso que estaba ROJO**. Un
control que al quitarlo no cambia ningún resultado no se cobra. **15 cobradas**:
`AB-C2`(G5), `AB-C3`(G4), `AB-C4`(G6), `AB-C5-existe`(G2), `AB-C5-metodo`(G3),
`AB-C6`(G7), `AB-C7`(G8), `AB-C8`(G10), `AB-C1`(G12),
`AB-C9-head`(A2), `AB-C9-cobertura`(A3), `AB-C9-conjunto`(A6),
`AB-C10`(AD-censo_opaco), `AB-C10-duros`(AD-rutas_sin_auth) y
`AB-C10-desconocido`(A10).

**Corrección: C1 SÍ es necesario, y la versión anterior de este documento se
equivocaba.** Se declaró «superviviente, diagnóstico y no carga probatoria»
porque en G1 (router desmontado) ablar C1 deja el caso rojo por C2 y C5 — cierto,
pero **G1 no era el caso que lo cobraba**. Lo es **G12**, un módulo de router
**no importable**: ahí D2 no llega a ver ni una ruta, así que C2 y C5 no tienen
nada que decir y **C1 es el único control que actúa**; con `AB-C1` el caso pasa a
**VERDE con un router roto en el árbol**. Es lo que se pagaba por juzgar la
necesidad de un control desde un solo caso: *no cobrado* no era *innecesario*,
era *no medido*.

### Dos casos que hubo que rehacer, y por qué constan

- **G5 salía VERDE** en su primera versión, que añadía una ruta al router
  *después* del `include_router`. En FastAPI 0.139 el `include_router` deja una
  referencia **viva** (`_IncludedRouter`), así que la ruta tardía se monta igual.
  Un caso que no puede ponerse rojo no calibra nada; se sustituyó por la
  inclusión parcial.
- **`AB-C6` no se cobraba** cuando la mutación vaciaba `NAV` **y**
  `FEATURE_SLOTS`: vaciar los huecos además desmonta los cuatro paneles, así que
  el rojo lo producía C1 y la ablación era inatribuible. Se dejó sólo `NAV = ()`.

Ambos son el mismo error de fondo —un rojo por el motivo equivocado— y el arnés
los cazó porque comprueba **la clave del hallazgo**, no el código de salida.

### Higiene del arnés

- **Un proceso por mutación.** `route_map`, `app.main` y `app.chassis` son
  singletons en `sys.modules`.
- **Nada se muta en el árbol real:** cada caso trabaja sobre una copia temporal, y
  al terminar se comprueba por **hash SHA-256 del contenido** de `viewer/`,
  `scripts/route_map/` y `contracts/` que no ha cambiado ni un byte. Reversión
  verificada por hash, no por presencia de cadenas: un guardián de presencia no
  distingue «el arreglo está» de «la palabra está».
- **`__pycache__` purgado** en cada copia y `PYTHONDONTWRITEBYTECODE=1` en cada
  subproceso. Un árbol Git limpio **no** demuestra que el proceso ejecute ese
  árbol: `shutil.copy2` preserva la mtime y CPython revalida el `.pyc`.
- **Mutaciones exigentes:** si el texto a sustituir no aparece el número de veces
  previsto, la calibración **levanta** en vez de pasar en verde sobre una
  mutación que no entró.
- **Suelos:** mínimo 16 casos ejecutados y 8 ablaciones cobradas. Un arnés que
  pasa con 0 casos está roto.

## 3.bis Lo que encontró la primera corrida en CI

La primera vez que el job corrió de verdad, **el censo murió antes de emitir una
fila**:

```
File "scripts/route_map/route_map.py", line 502, in collect_mounted
    from fastapi.dependencies.utils import get_flat_dependant
ImportError: cannot import name 'get_flat_dependant' from 'fastapi.dependencies.utils'
```

`get_flat_dependant` era **API privada del framework y ha desaparecido**.
`viewer/requirements.txt` declara `fastapi>=0.141.1,<1.0`; el entorno local donde
se venía ejecutando el censo tenía **0.139.0**, una versión que el repositorio ya
no declara. Es decir: **el instrumento llevaba tiempo sin poder correr contra las
dependencias reales del proyecto, y nadie se enteraba porque ningún job lo
ejecutaba**. Ése es, literalmente, el argumento de este carril.

Dos cosas que conviene subrayar:

- **La puerta se comportó bien.** No dio verde: el censo salió con rc distinto de
  0 y sin artefacto, y la puerta lo dijo — `censo-no-inspecciono-la-app-real`,
  motivo `artefacto-ausente`. El caso A1 de la calibración es exactamente ése.
- **El arreglo elimina la dependencia de API privada** en vez de fijarla a una
  versión: `_dependants_planos()` recorre el árbol de `Dependant` y deduplica por
  identidad del invocable, que es lo único que el censo consumía.

Re-medido con el FastAPI **declarado** (0.141.1): mismo resultado que con 0.139
—70 rutas montadas, 70 probadas, 68 denegaciones atribuibles, **0 SIN-AUTH, 0
opacas**—, puerta VERDE y calibración OK (26 casos, 12 ablaciones). La
calibración previa del censo (`calibrate_censo.py`, 17 casos y 12 ablaciones)
también sigue en OK con las dos versiones.

## 3.ter Un renombrado desarmaba el control de SIN-AUTH (cerrado)

Una revisión independiente midió el defecto más serio de la primera versión, y
merece constar entero porque es **el acoplamiento por nombre que este proyecto
lleva toda la ronda cazando**:

- con una ruta `/api` sin auth, el censo emite `rutas_sin_auth: ['GET /api/alias-fuga']`
  y la puerta da **rc=1 `censo-en-rojo`**;
- **renombrando esa clave a `rutas_sin_auth_v2` en el artefacto: rc=0, VERDE, con
  la fuga intacta.**

Y la calibración no lo veía, porque A8/A9 **inyectaban el nombre literal en un
artefacto sintético**: eso comprueba que la puerta reacciona a un nombre, no que
ese nombre siga siendo el que el censo produce.

**Arreglo, en dos capas, las dos calibradas:**

1. **En ejecución, se invierte el criterio.** La puerta ya no enumera los duros y
   se desentiende del resto: clasifica el **vocabulario entero** del censo en tres
   tuplas (`FINDINGS_CENSO_INCOMPLETO`, `FINDINGS_DUROS`, `FINDINGS_INFORMATIVOS`)
   y **lo que no esté clasificado es rojo** (`hallazgo-desconocido`). Un duro
   renombrado deja de casar con su clase y cae ahí. Caso **A10**, ablación
   `AB-C10-desconocido`.
2. **En el arnés, se contrasta contra el censo real.** El caso **G14** ejecuta
   `route_map --skip-probe` sobre el árbol, le pregunta al censo cuáles son sus
   claves de `findings`, y las compara con las que la puerta clasifica —leídas
   **de la puerta**, no copiadas— en las **dos direcciones**: un nombre que la
   puerta clasifica y el censo ya no emite (la clase apunta al vacío), y un nombre
   que el censo emite y la puerta no clasifica. **G14-neg** es su control
   negativo: con `rutas_sin_auth` renombrado, el contraste tiene que señalar las
   dos caras — si no puede ponerse rojo, no comprueba nada.

**Aviso de altura sobre las tres tuplas:** no son la lista blanca que este carril
prohíbe. Una lista blanca es aquella en la que **escribir un nombre quita
vigilancia**; escribir un nombre en `FINDINGS_DUROS` o en
`FINDINGS_CENSO_INCOMPLETO` **añade** una causa de rojo. La única que relaja es
`FINDINGS_INFORMATIVOS`, y va justificada elemento a elemento en el código (los 3
`rutas_muertas` son los falsos positivos conocidos del enumerador AST; los 39
`rutas_huerfanas`, APIs consumidas por `fetch`; etc.). De paso se **endurecieron**
tres hallazgos que estaban a 0 y no se exigían: `rutas_denegacion_404_ambigua`,
`rutas_denegacion_no_atribuible` y `sondas_inconcluyentes`.

**Dato que sube el valor de la puerta**, de la misma revisión: `route_map.py` sale
con **rc=0 aun con `rutas_sin_auth` no vacío**. Quien convierte una fuga en un
rojo de CI es `FINDINGS_DUROS`. La puerta no es un envoltorio del censo.

## 3.quater API privada que queda, y el detector de su degradación

`get_flat_dependant` ya desapareció y tumbó el censo (§3.bis). Lo que queda:

| interno | dónde | modo de fallo |
|---|---|---|
| `_IncludedRouter.effective_route_contexts()` · `.effective_low_priority_routes()` · `ctx.original_route` · `ctx.starlette_route` | `route_map._nodo` / `_nodo_ctx` | acceso con `getattr(..., None)`: **no revienta, DEGRADA** |
| `starlette.routing.compile_path` | `route_map` (2 usos) | no documentado, pero estable |
| `from fastapi.routing import _IncludedRouter` bajo `try/ImportError` con fallback `()` | `calibrate_censo.py:77` | si desaparece, **el control negativo se queda mudo en silencio** |

La primera fila es la peligrosa, y su peligro es concreto: degradaría **a la vez
el censo y la puerta**, así que `conjunto-de-rutas-distinto` (C9) **no lo vería**
— los dos mirarían lo mismo mal mirado.

**Detector, y sale gratis porque ya estaba.** D2 llega a las rutas por una vía que
**no usa ninguna API privada**: importa el módulo del router y lee
`router.routes`. Si el enumerador deja de descender por los `_IncludedRouter`,
los 53 endpoints declarados desaparecen del censo y **C2 se pone roja en masa**.
Hay **dos caminos independientes** hasta las mismas rutas y sólo uno depende de
los internos. Calibrado en **G13**, que hace desaparecer
`effective_route_contexts` a propósito: la puerta sale roja con
`ruta-declarada-no-montada`, `router-declarado-no-montado` y
`nombre-canonico-no-resuelve`.

Queda **declarado como riesgo del próximo bump de FastAPI**; el fallback mudo de
`calibrate_censo.py:77` no se toca en este carril (no es fichero de esta puerta),
pero queda escrito aquí.

## 3.quinquies La asignación duro/informativo, derivada de una medida (O4)

Con la puerta ya **requerida**, una revisión midió el hueco que quedaba (**M16**):
la asignación de cada hallazgo a *duro* o *informativo* estaba escrita a mano y
**sólo dos de los trece nombres duros tenían un caso que los cubriera**
(`censo_opaco` y `rutas_sin_auth`). Mover `rutas_denegacion_404_ambigua` o
`rutas_denegacion_no_atribuible` a `FINDINGS_INFORMATIVOS` **pasaba la
calibración**. Es decir: la inversión de O1 protegía el vocabulario contra
renombrados, pero no contra **degradaciones de la asignación**.

Cerrado en dos piezas que se necesitan mutuamente:

### 1) Los casos se GENERAN, uno por nombre duro

`casos_por_hallazgo_duro()` itera `gate.FINDINGS_DUROS` y
`gate.FINDINGS_CENSO_INCOMPLETO` —**leídos de `gate.py` en un subproceso**, no
copiados— y produce un caso sintético por nombre: **13 casos `AD-<nombre>`** que
antes eran dos escritos a mano. La protección **crece sola** al endurecer un
hallazgo nuevo, igual que D1 crece sola al aparecer un router.

**Lo que esto solo NO prueba, y hay que decirlo:** estos casos se derivan de la
misma lista que vigilan. Si alguien mueve un nombre a informativos, **su caso
desaparece con él** y ninguno se pone rojo. Es exactamente el suelo que se
autocumple contra el que este proyecto lleva toda la ronda avisando.

### 2) La pertenencia se DERIVA de dos medidas, no de una opinión

`G15` toma **dos medidas de referencia sobre el árbol limpio** —el censo con
sonda y el censo con `--skip-probe`— y exige que **todo hallazgo vacío en LAS DOS
sea duro**.

Por qué las dos y no una, que es donde está el criterio:

| medida | qué falsearía usarla sola |
|---|---|
| sólo **con sonda** | `rutas_no_probadas` sale vacío (70/70 ejercitadas) y el criterio exigiría endurecer la **cobertura de tests**, que es otra política y no la de esta puerta |
| sólo **`--skip-probe`** | `rutas_servidas_a_viewer` sale vacío porque **la medida no se ha hecho**, no porque no haya nada que contar |

> Un cubo que sigue vacío **tanto si debilitas la medida como si la refuerzas** no
> depende de la configuración: es un cubo que debería estar siempre vacío, y ése
> es el que tiene que ser duro. Uno que se llena en alguna de las dos está
> describiendo el estado del árbol, no una garantía rota, y queda libre.

El criterio es **de una sola dirección** (vacío ⇒ duro; no vacío ⇒ libre), así que
endurecer de más nunca lo viola: `caracterizacion_estatica_fallida` se llena con
`--skip-probe` y es duro igualmente, y está bien.

**Medido en este árbol:** la intersección son **12 nombres**, y los 12 están hoy
en las tuplas duras (la puerta declara 13: los 12 más
`caracterizacion_estatica_fallida`).

**Control negativo, nombre a nombre (`G15-neg`):** mover **cada uno** de los 12 a
`FINDINGS_INFORMATIVOS` tiene que detectarse, y se comprueban los 12, no el
conjunto en bloque — que era justo el defecto.

**Y verificado en vivo:** aplicada la mutación M16 sobre el árbol real (los dos
hallazgos movidos a informativos), la calibración sale **ROJA nombrando los dos**:

```
G15: `rutas_denegacion_404_ambigua` esta VACIO en las dos medidas de referencia,
     o sea que deberia estar siempre vacio, y sin embargo la puerta lo tiene en
     `FINDINGS_INFORMATIVOS`: si se llena, la puerta no se pondra roja
G15: `rutas_denegacion_no_atribuible` ...
```

Reversión **verificada por hash SHA-256** de `gate.py`
(`5e63bf25…` antes y después), no por presencia de cadenas.

**Total tras O4 y el cierre de S1/S2: 46 casos y 15 ablaciones cobradas.**

### `--mapa-completo` es un atajo de tiempo, NO una condición de validez

**Corrección de una afirmación falsa** que esta sección hizo antes («si falta
`--mapa-completo`, G15 es ROJO; no hay modo degradado»). Medido por una revisión:
**sin la bandera la calibración sale VERDE**, porque la rama `else` genera la
referencia con sonda por su cuenta. De fondo no degrada nada —sólo cuesta ~60 s
más—, pero la frase escrita era falsa y **quitar la bandera de `ci.yml` no lo
delataba**. Así que se escribe como es:

- **falta la bandera** ⇒ la referencia se genera aquí mismo; el arnés tarda más y
  mide lo mismo;
- **la bandera apunta a un artefacto INVÁLIDO** (tomado con `--skip-probe`, o sin
  `--tested`) ⇒ **ROJO**, porque derivar sobre una medida falseada es peor que no
  derivar.

## 3.septies Los dos supervivientes de O4, y por qué hacían falta dos controles más

Una revisión independiente andó dos huecos reales del cierre anterior. Los dos
tenían la misma forma: **el arnés protegía la asignación duro/informativo con
controles que se derivaban de la propia asignación**, así que el ataque que
borraba el rastro se llevaba también al vigilante.

### S1 — `caracterizacion_estatica_fallida` no tenía cobertura

Era el nombre que sobraba en el «13 contra 12» de G15. Movido a
`FINDINGS_INFORMATIVOS`, la calibración salía **VERDE**: G15 no lo exige (no está
vacío en las dos medidas, se llena con `--skip-probe`) y su caso `AD-`
**desaparecía con él**. Y el hueco era real en la puerta: con ese hallazgo lleno y
`--map-rc 0`, la puerta sana da rc=1 y la mutada da **rc=0**.

El atenuante que encontró la revisión resultó ser también la solución: en el
pipeline real el censo **ya sale con rc=3** si ese hallazgo no está vacío, y CI le
pasa el rc a la puerta. La garantía se sostenía **por otra capa**… que se podía
quitar en silencio. **`G16` convierte esa coincidencia en un acoplamiento
exigido:**

> Todo hallazgo por el que el censo sale con código distinto de 0 es **fatal para
> el censo**, y la puerta no puede tratarlo como informativo.

Y no se copia la lista: se **deriva del AST de `route_map.main()`**, leyendo qué
nombres aparecen en `findings.get(...)` dentro de las ramas que terminan en un
`return` distinto de 0. **Medido: 4 fatales** (`censo_opaco`, `censo_vacio`,
`caracterizacion_estatica_fallida`, `control_positivo_csrf_fallido`). Si mañana el
censo declara fatal un hallazgo nuevo, entra solo.

### S2 — un cubo que YA está lleno no lo protege ninguna regla local

Éste **no es un descuido: es un límite estructural de G15**, y conviene que quede
escrito porque es la clase de defecto que vuelve. Si el mismo commit
**introduce el defecto** (deja `contradiccion_deniega_y_sirve` no vacío) **y**
mueve ese nombre a informativos, entonces `duros_exigidos` ya no lo incluye,
`contraste_asignacion` no dice nada, el caso `AD-` desaparece con el nombre y el
suelo se cumple de sobra ⇒ **todo verde**. Sólo se salvaban `rutas_sin_auth` y
`censo_opaco`, y **por accidente**: estaban fijados a mano como objetivo de dos
ablaciones (y se «salvaban» con un `KeyError`, no con un diagnóstico).

**Ninguna regla que mire sólo el árbol actual puede cerrarlo**, porque en el árbol
actual el nombre ya no es duro y su cubo ya no está vacío: **el commit atacante ha
borrado su propio rastro**. Hace falta un punto de comparación que ese commit no
controle, y el único que hay es **el estado anterior del código**. De ahí `G17`:

> El conjunto duro de HEAD tiene que **contener** al conjunto duro de la base
> (merge-base con `origin/main`). Un nombre puede **añadirse** cuando se quiera;
> **quitarlo es ROJO**, da igual que su cubo esté lleno o vacío y que su caso
> generado haya desaparecido con él.

No es una lista que nadie mantiene: **es el commit de antes**, leído con
`git show <base>:scripts/route_map/gate.py` y parseado con AST — no con `grep`, y
no importando el fichero de otra rama, que es como una capacidad ajena se
convierte en verdad falsa del producto. En CI el job hace `fetch-depth: 0` y
comprueba que el merge-base existe **antes** de medir: sin base, G17 se pone rojo
en vez de callarse.

**Consecuencia deliberada:** aflojar una garantía deja de poder hacerse callando.
Si algún día hay que quitar un hallazgo de los duros con razón, el job se pone
rojo y hay que discutirlo. Eso es lo que se quiere de un check requerido.

### La cuenta honesta de quién protege a quién

`Gneg` muta **`gate.py` de verdad** —antes simulaba pasándole diccionarios
degradados a `contraste_asignacion`, que es calibrar la función y no el sistema— y
relee las constantes **en un subproceso**, uno por nombre. Y toma el veredicto en
el **peor caso de S2**: con `exigidos` **sin** ese nombre, que es lo que pasa
cuando el cubo se llena. Creditarle a G15 una protección que el ataque real le
quita sería contarse un control que no actúa.

| hallazgo | quién lo caza **bajo el ataque de dos pasos** |
|---|---|
| `caracterizacion_estatica_fallida` | **G16 · G17** |
| `censo_opaco`, `censo_vacio`, `control_positivo_csrf_fallido` | **G16 · G17** |
| los otros nueve | **G17** |

**Los 13, no 2.** G15 sigue apareciendo en el informe como
`G15-si-el-cubo-sigue-vacio`: es protección real mientras nadie llene el cubo, y
mentira contarla como protección frente a S2.

**Verificado en vivo sobre el árbol real**, con reversión comprobada por hash
SHA-256 de `gate.py` (`5e63bf25…` idéntico antes y después):

- **ataque S1** (mover `caracterizacion_estatica_fallida`) ⇒ ROJO por **G16 y G17**;
- **ataque S2** (mover `contradiccion_deniega_y_sirve`) ⇒ ROJO por **G15 y G17**.

### Lo que sigue sin tener detector (dicho, no disimulado)

- **G17 protege contra encoger, no contra no crecer.** Un hallazgo nuevo del censo
  que debiera ser duro y se clasifique como informativo **desde el primer
  commit** no lo ve G17 (nunca estuvo en la base). Lo ven G15 —si su cubo está
  vacío en las dos medidas— y G16 —si el censo lo declara fatal—. Fuera de esos
  dos casos, no hay detector.
- **La base es `origin/main`.** Si alguien relajase la asignación **en `main`**,
  las ramas siguientes heredarían la base ya relajada y G17 no diría nada. La
  protección es contra la deriva rama a rama, que es por donde entra.

## 3.octies El arnés ya no está desprotegido

**Nada guardaba a `calibrate_gate.py`**: borrar el bloque de G15 dejaba 42 casos
—por encima de `MINIMO_CASOS`— y todo verde. `calibra_gate_integrity.py` vigila
`check_ci_config.py`, no este arnés. Ahora hay una tupla `CONTROLES_OBLIGATORIOS`
(`G0`, `G13`, `G14`, `G14-neg`, `G15`, `G16`, `G17`, `Gneg`, `AFP`) y la
calibración falla si alguno no se ha ejecutado. Es de **exigencias**: escribir un
nombre ahí añade un control obligatorio.

Y dos diagnósticos que eran trazas:

- vaciar `FINDINGS_DUROS` o renombrar `rutas_sin_auth` daba `KeyError:
  'AD-rutas_sin_auth'`. Fallaba cerrado, pero el operador veía una traza. Ahora
  dice que el caso **ya no se genera** y remite a G14, G15, G16 y G17;
- `Gneg` con un conjunto vacío decía «OK» habiendo comprobado **0 nombres**. Un
  conjunto vacío ya no pasa.

## 3.sexies Dos cosas que hay que leer como coste, no como avería

**Un hallazgo nuevo del censo pone este job ROJO hasta que alguien lo clasifique.**
Medido (**M14**): una clave nueva **con lista vacía** ya lo enrojece, porque el
bucle de `hallazgo-desconocido` **no filtra por contenido**. Es **deliberado** y
es el precio de la inversión de O1: la alternativa —ignorar lo que no se conoce—
es precisamente el agujero por el que un hallazgo duro renombrado pasaba en
verde. Ahora que la puerta es un check **requerido**, conviene tenerlo escrito:
si estrenas un hallazgo en `route_map.py`, **clasifícalo en `FINDINGS_DUROS`,
`FINDINGS_CENSO_INCOMPLETO` o `FINDINGS_INFORMATIVOS` en el mismo commit**. Son
dos líneas, y el mensaje de error dice exactamente qué falta.

**`calibrate_gate` ejecutado desde una copia sin `.git` falla `A2` por
construcción.** `_head()` devuelve cadena vacía y la comparación de HEAD se salta,
así que el caso **no puede ponerse rojo**. Por eso los casos de artefacto apuntan
al repositorio real (`repo=REPO`) y no a la copia. En CI corre desde el repo real
y no afecta. Queda anotado porque **un A2 rojo desde una copia sin `.git` sería un
artefacto del arnés, no una detección de la puerta**, y ése es exactamente el
género de confusión que ya costó una ronda aquí.

## 4. La condición 2, implementada (no en prosa)

`docs/68 §5.quater` pedía que la puerta **comprobara** que los cuatro paneles
están apagados, y hasta hoy eso sólo existía escrito: `S9K_PANEL` aparecía una
sola vez en `scripts/` y `.github/`, y era un comentario. Si se cablea el job sin
implementarlo, la puerta nace con el defecto que dice cerrar —mediría una app y
certificaría otra—.

Implementación (`gate.py`, hallazgo `panel-encendido`):

1. El job **no exporta ninguna** `S9K_PANEL_*_ENABLED`, que es la configuración
   que se despliega (`chassis.py` falla cerrado ante la ausencia y declara que
   apagados es lo correcto para producción).
2. La puerta **no se fía de eso**: por cada `FeatureSlot` pregunta al chasis el
   nombre de su bandera (`slot_flag_env`) y si está encendida (`slot_enabled`).
   El criterio no se reimplementa: se **delega**, así que «encendido» significa
   exactamente lo que significa para la app.
3. Además barre el entorno buscando la **familia** `S9K_PANEL_*_ENABLED`: una
   bandera encendida que el chasis ya **no** reconoce también es roja — o sobra en
   el entorno o falta el hueco en el contrato.
4. `FP1`/`FP2`/`FP3` vigilan que apagar, escribir un valor ininteligible o usar
   un nombre parecido no produzcan rojos falsos.

## 5. Presupuesto medido

| paso | medido |
|---|---|
| suite del visor con la sonda (`-p route_map.pytest_route_probe`), genera `--tested` | **57 s** (1565 passed, 191 skipped) |
| censo (`route_map.py` con sonda) | **4,7 s** |
| puerta (`gate.py`) | **~2 s** |
| calibración (`calibrate_gate.py`, 46 casos + 15 ablaciones, un subproceso cada uno) | **~120 s** |
| **total del job** | **≈ 185 s** más la instalación de dependencias |

## 6. Recuento de jobs

Medido con `yaml.safe_load`, no con un grep: `ci.yml` pasa de 14 a **15** jobs y
`supply-chain.yml` aporta 1 ⇒ **16 corriendo**. `docs/project-status.yaml`
refrescado en el mismo commit:

- `ci_jobs_running: 15 → 16`;
- `ci_checks_required: 15` (**sin cambio**: añadirlo a la protección de rama es
  del operador);
- `ci_running_but_not_required: []` → `["Censo de rutas (configuracion canonica en codigo)"]`,
  que es lo que hace cuadrar `16 − 1 = 15`.

`check_ci_config.py` y `calibra_gate_integrity.py` corridos **antes y después**:
verdes las dos veces (30/30 casos de la calibración de gates).

## 7. Limitaciones (declaradas, no disimuladas)

- **Borrar una ruta a la que nada canónico apunta no pone la puerta roja.** No hay
  declaración que quede incumplida. Cubrirlo exigiría enumerar las rutas en una
  lista, que es exactamente lo prohibido. Las rutas afectadas se **nombran una a
  una** en el artefacto (`resumen.rutas_sin_declaracion_canonica`), no se resumen
  en un número. Los **14 nombres canónicos exigidos** están en
  `resumen.nombres_canonicos_exigidos`.
- **C4 sólo se pone roja para endpoints de FUERA de `viewer/app`.** Dos casos que
  suenan a «ruta inesperada» **pasan la clasificación**: un **alias** del mismo
  objeto endpoint montado en un segundo path (es el mismo endpoint de un router
  declarado) y una **función suelta** de un módulo de `viewer/app` montada con
  `add_api_route` (su fichero fuente está dentro del árbol). A los dos, cuando
  importan de verdad, los caza el **censo por falta de autorización**, no C4. Lo
  que C4 cierra es la **procedencia desconocida**: una ruta inyectada por una
  librería o generada en ejecución. Es menos de lo que el nombre sugiere.
- **La puerta hereda todas las limitaciones del censo** (§5.quater de `docs/68`):
  los tri-estados disparan ante la ausencia de dato, no ante su incorrección; un
  `Mount` opaco sigue siendo opaco; la superficie estática se comprueba sobre una
  muestra de verbos y dos URLs.
- **Mide una sola configuración: la de producción, con los cuatro paneles
  apagados.** El segundo job con los paneles encendidos sigue pendiente y sigue
  sin poder ser bloqueante: el instrumento no distingue «apagada por bandera» de
  «muerta».
- **`--solo-declaracion` es del arnés, no de la puerta.** Evalúa C1-C8 sin exigir
  artefacto de censo, para que cada control se pueda ablar por separado. La propia
  calibración comprueba que **ningún workflow** lo pasa.
