# 64 — Integridad de gates (carril L)

Rama: `ops/gate-integrity-v1`. Base canonica: `main = e9c66dc`.

Este documento explica **por que** el gate de configuracion de CI dejo de ser
una regex y **como se ha demostrado** que funciona. No se apoya en «hay un test
verde»: cada afirmacion tiene debajo una violacion introducida de verdad, un
ROJO real y una vuelta a VERDE.

---

## 1. La deuda que se cierra

`comprueba_silenciadores()` en `.github/scripts/check_ci_config.py` buscaba los
campos que pueden apagar CI (`paths`, `paths-ignore`, `branches-ignore`) con una
**regex de texto** anclada a una forma concreta de escribirlos:

```python
if re.search(rf"^    {re.escape(campo)}:", bloque, re.M):
```

Un revisor independiente encontro tres formas de escribir exactamente lo mismo
que la regex no veia. Las tres son YAML valido y **GitHub las interpreta igual
que la forma bloqueada**:

| Bypass | Escrito asi | Lo que GitHub lee |
|---|---|---|
| clave entrecomillada | `"paths-ignore": ['**']` | `paths-ignore` |
| espacio antes de los dos puntos | `paths-ignore : ['**']` | `paths-ignore` |
| campo bajo `pull_request` | `pull_request: { paths-ignore: ['**'] }` | `paths-ignore` (el gate ni miraba ese bloque) |

El tercero es el mas grave: apaga el CI de **todos los PR contra `main`**, que
es justo la barrera que protege la rama principal.

### Diferencial: gate viejo contra gate nuevo

Ejecutado sobre el mismo `ci.yml` mutado, con el gate de `e9c66dc` y con el
nuevo. La columna del medio es la prueba de que el bypass era real, no teorico:

```
| Bypass                          | claves reales que ve GitHub                 | gate VIEJO (regex) | gate NUEVO (yaml) |
|---------------------------------|---------------------------------------------|--------------------|-------------------|
| clave entrecomillada            | on.push -> ['branches', 'paths-ignore']     | RC=0 VERDE (BYPASS)| RC=1 ROJO         |
| espacio antes de los dos puntos | on.push -> ['branches', 'paths-ignore']     | RC=0 VERDE (BYPASS)| RC=1 ROJO         |
| bajo pull_request               | on.pull_request -> ['branches','paths-ignore']| RC=0 VERDE (BYPASS)| RC=1 ROJO       |
```

## 2. Que se ha cambiado

**Parseo YAML semantico en lugar de regex.** El workflow se lee con
`yaml.safe_load` y se comprueban las **claves del mapa**, normalizadas. La
comilla, el espacio, el orden y la forma de flujo dejan de existir como
concepto antes de que el gate mire nada: no se vigila *una* manera de
escribirlo, se cubre la familia entera por construccion. Es la misma idea que
`'**'` frente a la lista blanca de prefijos.

Detalle que cuesta un rato descubrir: en YAML 1.1 la clave `on:` se parsea como
el **booleano `True`**, no como la cadena `"on"`. El gate acepta ambas.

**Cobertura ampliada.** Los silenciadores se prohiben bajo `push`,
`pull_request` **y** `pull_request_target`, no solo bajo `push`.

**Propiedad de cobertura intacta.** `on.push.branches` debe cubrir cualquier
nombre de rama, probado contra `RAMAS_SONDA` (nombres inventados de familias
que no existen). Una lista blanca, aunque incluya **todas** las ramas reales de
`origin` de hoy, sigue en ROJO. Eso esta calibrado abajo.

**Workflows vigilados.** `ci.yml` y `supply-chain.yml`. Si uno desaparece, es
fallo: una barrera que puede dejar de existir sin ponerse roja no es barrera.

**Ejecucion condicional prohibida.** Ni `if:` (salvo `always()`) ni
`continue-on-error` truthy, ni a nivel de job ni de paso. Ver seccion 2 bis:
son dos supervivientes que un revisor demostro VIVOS, de una linea cada uno.

**La calibracion se ejecuta en CI** (`calibracion-de-gates`), para que no se
pudra.

**Meta-gate «0 tests».** Todo paso de un workflow vigilado que **invoque**
pytest (no que lo instale: `pip install "pytest>=8.2"` no ejecuta nada) tiene
que llevar guardia anti-cero sobre `N passed`. Un pytest que colecciona 0 tests
—directorio renombrado, filtro que no casa— saldria en verde sin comprobar
nada.

Al activarlo aparecieron **cuatro jobs reales sin guardia**:
`test-data-engine`, `test-viewer`, `test-combined` y `review-ingest-contracts`.
Se les ha anadido.

**Meta-gate «skip critico».** Todo test que se auto-omite por falta de una
herramienta externa exige un job que, **en el mismo job**: (a) instale la
herramienta, (b) lo ejecute nombrandolo, y (c) falle si la salida dice
`skipped`. Las herramientas estan en una tabla (`HERRAMIENTAS`): anadir una es
una fila, no un `if` nuevo. Hoy cubre Node y Chromium/Playwright.

Al activarlo aparecio un hallazgo real: `tests/e2e/conftest.py` tenia una
fixture `require_playwright` que se auto-omitia si Playwright faltaba, **ningun
test la usaba** y **ningun job instalaba Chromium para ese directorio**. Era una
guardia de omision que no guardaba nada y que, el dia que alguien la hubiera
usado, habria producido skips verdes. Se ha retirado en vez de dejarla de
adorno. Los tests de navegador de verdad viven en `viewer/tests/browser/`, que
si tienen job con `playwright install` y guardia anti-salto.

**Dependencia nueva: PyYAML.** Deliberada. La version anterior presumia de no
tener dependencias, y por eso parseaba con regex — que es exactamente el
defecto que aqui se corrige. El job `check-ci-config` instala PyYAML sin
`|| true`: si falta, el gate falla; **no se degrada a comprobacion textual**,
porque degradarse seria volver al agujero.

## 2 bis. Ejecucion condicional: apagar la barrera sin tocar la barrera

Un revisor independiente reprodujo el diferencial por su cuenta y ademas
encontro dos supervivientes **VIVOS**, cada uno de **una sola linea** en este
mismo `ci.yml`, que neutralizan un job de pruebas entero:

```
M12 if: false a nivel de JOB               RC=0  VERDE (SUPERVIVIENTE VIVO)
M11 continue-on-error a nivel de JOB       RC=0  VERDE (SUPERVIVIENTE VIVO)
```

No eran «la siguiente familia natural»: son exactamente la clase de defecto que
este fichero existe para impedir. Con `paths-ignore` la barrera deja de
evaluarse; con `if: false` la barrera **no llega a existir** y con
`continue-on-error` **existe pero no puede bloquear**. Los tres son el mismo
defecto.

Detalle que los hace peores que un fallo normal: un job saltado no reporta
`failure`, reporta **`skipped`**. No es rojo, es gris. Y una proteccion de rama
puede dar por satisfecho un check saltado.

**Decision, razonada y no escondida: se prohiben ambos, en los dos niveles (job
y paso), y la unica condicion admitida es `always()`.**

El argumento es asimetrico. El comportamiento por defecto —ejecutarse si lo
anterior fue bien— es el **maximo** de ejecucion posible. Cualquier `if:`
distinto de `always()` solo puede conseguir que se ejecute **menos**;
`always()` es la unica que va en direccion contraria, y por eso es la unica que
no puede apagar nada. No se hace una lista blanca de condiciones «legitimas»
porque seria el mismo error que la lista blanca de prefijos de rama: habria que
mantenerla a mano y el agujero volveria.

¿Y si algun dia hace falta una condicion de verdad? La reparacion no es
relajar `CONDICIONES_PERMITIDAS` en silencio: es meter la decision **dentro del
`run:`**, donde tiene que dejarla escrita y donde un fallo sale en rojo en vez
de en gris. Es la misma respuesta que ya se da para `paths`.

Coste comprobado: **cero**. El inventario de `ci.yml` y `supply-chain.yml` no
tiene hoy ni un solo `if:` ni un solo `continue-on-error`, asi que la
prohibicion no rompe nada existente. Se anade un control positivo a la
calibracion (`if: ${{ always() }}` debe quedar en VERDE) para que el gate no
pueda aprobarse simplemente rechazando cualquier `if:`.

## 3. Calibracion

`.github/scripts/calibra_gate_integrity.py` **introduce cada violacion de
verdad** (escribe el fichero, ejecuta el gate, lee el codigo de retorno,
restaura). No simula. Si el gate deja de detectar un caso, el harness sale en
rojo.

Y **se ejecuta en CI** (job `calibracion-de-gates`). Antes no: una calibracion
que no se ejecuta se pudre igual que cualquier otro codigo muerto, y el dia que
alguien aflojara `check_ci_config.py` no habria ningun aviso. Ese job es ahora
el aviso.

El calibrador tambien esta calibrado. Se le miente a proposito —desactivando
una mutacion e invirtiendo una expectativa— y tiene que cantarlo:

```
RC del calibrador con 2 mentiras: 1
  | `if: false` en un JOB de pruebas          | ROJO  | 0 | VERDE | **DESVIACION** |
  | `continue-on-error: true` a nivel de PASO | VERDE | 1 | ROJO  | **DESVIACION** |
  CALIBRACION FALLIDA: 2 caso(s) no dieron el veredicto esperado
```

Salida real (20/20):

| Caso | Esperado | RC | Obtenido |
|---|---|---|---|
| estado correcto | VERDE | 0 | VERDE |
| `paths-ignore` bajo `push` | ROJO | 1 | ROJO |
| `paths-ignore` bajo `pull_request` | ROJO | 1 | ROJO |
| `"paths-ignore"` entrecomillado | ROJO | 1 | ROJO |
| `paths-ignore :` con espacio antes de los dos puntos | ROJO | 1 | ROJO |
| `paths:` bajo `push` | ROJO | 1 | ROJO |
| `paths:` bajo `pull_request` | ROJO | 1 | ROJO |
| `branches-ignore` | ROJO | 1 | ROJO |
| politica reducida a `branches: [main]` | ROJO | 1 | ROJO |
| lista blanca EXHAUSTIVA con todas las ramas reales de `origin` | ROJO | 1 | ROJO |
| workflow vigilado borrado (`supply-chain.yml`) | ROJO | 1 | ROJO |
| `if: false` en un JOB de pruebas | ROJO | 1 | ROJO |
| `if: false` en un PASO de pruebas | ROJO | 1 | ROJO |
| `continue-on-error: true` a nivel de JOB | ROJO | 1 | ROJO |
| `continue-on-error: true` a nivel de PASO | ROJO | 1 | ROJO |
| `if:` con expresion que no es `always()` | ROJO | 1 | ROJO |
| control positivo: `if: ${{ always() }}` (unica permitida) | VERDE | 0 | VERDE |
| job que puede ejecutar 0 tests | ROJO | 1 | ROJO |
| test que se auto-omite por falta de Chromium | ROJO | 1 | ROJO |
| restaurado | VERDE | 0 | VERDE |

Reproducir: `python3 .github/scripts/calibra_gate_integrity.py`

## 4. EL HALLAZGO QUE MAS PESA: este gate no es un check requerido

El coordinador consulto los *required status checks* reales de `main`. **Son
once, y `Integridad de gates` no esta entre ellos.** Tampoco lo esta
`Especificacion JS del grafo (Node obligatorio)`.

Es decir: todo lo que hay en este documento **corre, pero no obliga**. El gate
puede ponerse rojo y el merge sigue permitido. Con el criterio de este mismo
fichero —«una barrera que puede dejar de evaluarse sin ponerse roja no es una
barrera»— hay que decirlo sin adornos: **un gate no exigido no es un gate; es
un informe**. Todo el trabajo de las secciones 1 a 3 sube el suelo de lo que se
detecta, y no cambia nada de lo que se puede fusionar.

La configuracion de rama protegida vive **fuera del repositorio** y no la puede
tocar ni este gate ni quien lo escribe: la cambia el operador. Mientras no se
anadan `Integridad de gates` y `Calibracion de gates` a los checks requeridos,
lo de arriba es una recomendacion muy bien medida.

Consecuencia menor y honesta: el renombrado del job (`Configuracion de CI` ->
`Integridad de gates`) no rompio ninguna proteccion, porque el nombre viejo
tampoco era exigido. Si algun dia se exige, hay que fijar el nombre.

## 5. Supervivientes (declarados, no ocultos)

Cosas que este gate **no** cubre. Estan aqui porque ocultarlas seria el mismo
defecto que corrige. Los antiguos 2 y 3 (`if:` y `continue-on-error`) ya **no
figuran: estan cerrados** en la seccion 2 bis.

1. **`concurrency: cancel-in-progress`.** Un `concurrency` mal puesto puede
   cancelar ejecuciones y dejar checks que nunca reportan. No se vigila. Un
   check que no aparece no es un check verde, pero eso se comprueba al contar
   conclusiones por identidad unica en el PR, no aqui.
2. **Proteccion de rama.** Ver seccion 4. Es el superviviente mas grave y el
   unico que no se puede cerrar desde el repositorio.
3. **N1 — pytest invocado INDIRECTAMENTE.** El meta-gate de «0 tests» detecta
   la invocacion en el texto del `run:`. Si las pruebas se lanzan desde un
   script, un `make`, un `tox` o un `nox`, la invocacion no esta en el YAML y
   el gate no ve nada. Comprobado VIVO:

   ```
   M8b real (invocacion 100% fuera del YAML): RC=0  VERDE (SUPERVIVIENTE VIVO)
   ```

   Y ya hay una instancia real hoy: `deployment-validation` ejecuta
   `bash deploy/tests/validate.sh` sin ninguna guardia anti-cero.

   **No se cierra aqui, a proposito.** Cualquier detector tendria que enumerar
   lanzadores (`make`, `tox`, `nox`, `npm test`, `*.sh`…) y ademas adivinar si
   el script ejecuta pruebas o lint: eso es una lista blanca que hay que
   mantener a mano, o sea vigilancia, que es justo lo que este carril rechaza.
   El arreglo por **construccion** es distinto y mas ambicioso: exigir que todo
   job de pruebas emita un **recuento de pruebas legible por maquina** (un
   fichero de resultados, un `--junitxml`) y comprobar ese recuento en vez de
   adivinar la invocacion. Eso cambia el contrato de varios jobs que no son de
   este carril, y por eso se declara en vez de improvisarse.

   Ojo a la diferencia con el superviviente 4: aquel habla de la **forma** de la
   guardia; este, de la **deteccion de la invocacion**. Son agujeros distintos.

4. **La guardia anti-cero se detecta por forma, no por semantica.** El gate
   comprueba que exista un `grep`/`if` sobre `passed`. Un `grep` escrito de
   otra manera, o uno que siempre case, pasaria. Es una mejora clara sobre no
   tener nada, no una prueba de que el job ejecuta tests.
5. **Herramientas fuera de la tabla `HERRAMIENTAS`.** Un test que se auto-omita
   por falta de Docker, de `psql` o de una GPU no se detecta hoy. Anadirlo es
   una fila de tabla.
6. **Workflows no vigilados.** Solo `ci.yml` y `supply-chain.yml`. Un workflow
   nuevo no entra en la lista solo. El gate falla si uno *desaparece*, no si
   uno *aparece* sin vigilar.
7. **`yaml.safe_load` no es el parser de GitHub.** Un revisor independiente
   probo aliases, merge keys, flow mapping y mayusculas, y el gate aguanto los
   cuatro. Aun asi no son el mismo programa: la equivalencia esta comprobada
   caso a caso, no demostrada.
8. **`RAMAS_REALES_CONOCIDAS` es una foto fija.** La calibracion de la «lista
   blanca exhaustiva» une las ramas vivas de `origin` con una lista capturada
   el dia que se escribio. La lista envejece; el caso no deja de probarse por
   ello (los nombres inventados de `RAMAS_SONDA` son los que deciden), pero es
   deuda declarada.
