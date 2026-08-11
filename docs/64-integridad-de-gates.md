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

## 3. Calibracion

`.github/scripts/calibra_gate_integrity.py` **introduce cada violacion de
verdad** (escribe el fichero, ejecuta el gate, lee el codigo de retorno,
restaura). No simula. Si el gate deja de detectar un caso, el harness sale en
rojo.

Salida real (14/14):

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
| job que puede ejecutar 0 tests | ROJO | 1 | ROJO |
| test que se auto-omite por falta de Chromium | ROJO | 1 | ROJO |
| restaurado | VERDE | 0 | VERDE |

Reproducir: `python3 .github/scripts/calibra_gate_integrity.py`

## 4. Supervivientes (declarados, no ocultos)

Cosas que este gate **no** cubre. Estan aqui porque ocultarlas seria el mismo
defecto que corrige.

1. **`concurrency: cancel-in-progress`.** Un `concurrency` mal puesto puede
   cancelar ejecuciones y dejar checks que nunca reportan. No se vigila. Un
   check que no aparece no es un check verde, pero eso se comprueba al contar
   conclusiones en el PR, no aqui.
2. **`if:` a nivel de job o de paso.** Un `if: false`, o una condicion sobre
   `github.event_name`, puede saltarse un job entero sin ponerse rojo. El gate
   no analiza condiciones. Es la siguiente familia natural de bypass.
3. **`continue-on-error: true`.** Convierte un job rojo en no bloqueante. No se
   vigila.
4. **Configuracion de rama protegida en GitHub.** Que un check exista y este en
   verde no significa que sea **requerido** para mergear. Eso vive en los
   ajustes del repositorio, fuera de todo fichero, y este gate no puede verlo.
5. **La guardia anti-cero se detecta por forma, no por semantica.** El gate
   comprueba que exista un `grep`/`if` sobre `passed`. Un `grep` escrito de
   otra manera, o uno que siempre case, pasaria. Es una mejora clara sobre no
   tener nada, no una prueba de que el job ejecuta tests.
6. **Herramientas fuera de la tabla `HERRAMIENTAS`.** Un test que se auto-omita
   por falta de Docker, de `psql` o de una GPU no se detecta hoy. Anadirlo es
   una fila de tabla.
7. **Workflows no vigilados.** Solo `ci.yml` y `supply-chain.yml`. Un workflow
   nuevo no entra en la lista solo. El gate falla si uno *desaparece*, no si
   uno *aparece* sin vigilar.
8. **`yaml.safe_load` no es el parser de GitHub.** Son compatibles en todo lo
   que aqui importa (y el diferencial lo comprueba caso a caso), pero no son el
   mismo programa. Diferencias de aliases o merge keys quedan sin explorar.
