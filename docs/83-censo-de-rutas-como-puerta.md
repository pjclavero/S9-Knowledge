# 83 — El censo de rutas como PUERTA: la configuración canónica vive en código

**Qué se cablea:** el job `route-map-gate` de `ci.yml` («Censo de rutas
(configuracion canonica en codigo)»).
**Qué lo sostiene:** `scripts/route_map/gate.py` (la puerta) y
`scripts/route_map/calibrate_gate.py` (su control negativo).
**Qué NO hace este carril:** añadirlo a la protección de rama. Sería el check
exigido nº 16 y lo decide el operador.

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

Calibración: `python3 scripts/route_map/calibrate_gate.py`. **26 casos y 12
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
control que al quitarlo no cambia ningún resultado no se cobra. **12 cobradas**:
`AB-C2`(G5), `AB-C3`(G4), `AB-C4`(G6), `AB-C5-existe`(G2), `AB-C5-metodo`(G3),
`AB-C6`(G7), `AB-C7`(G8), `AB-C8`(G10), `AB-C9-head`(A2),
`AB-C9-cobertura`(A3), `AB-C9-conjunto`(A6), `AB-C10`(A8).

**Superviviente declarado:** el control de nivel *router* (C1) **no se cobra**.
Al quitarlo, G1 sigue rojo por C2 y C5: es un refinamiento de diagnóstico —dice
«nadie incluyó este router» en vez de listar sus rutas una a una—, no el control
que sostiene el rojo. Se deja porque el mensaje vale, y se declara que no es
carga probatoria.

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
| calibración (`calibrate_gate.py`, 26 casos + 12 ablaciones, un subproceso cada uno) | **47 s** |
| **total del job** | **≈ 110 s** más la instalación de dependencias |

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
