# Batería de navegador contra una instalación real (RC-E2E, regresión 15)

Pruebas Playwright (Python, pytest, Chromium headless) que recorren la interfaz
web de una instalación **ya desplegada** del producto: nginx con TLS y CA
propia, visor, worker y —cuando lo haya— Neo4j. No arrancan el producto ni
importan su código.

No es la suite de `viewer/tests/browser`: aquélla corre en la CI contra la
aplicación arrancada **en el mismo proceso** con el proveedor de datos de
muestra, y prueba contratos de la interfaz. Ésta mide una instalación real y
sirve de evidencia de una RC-E2E.

## No corre en la CI, y por qué eso es correcto

- El directorio no está en los `testpaths` del `pytest.ini` de la raíz y
  ningún job de `.github/workflows/ci.yml` lo invoca. El inventario de suites
  (`.github/suite-inventario.json`) se deriva de esas dos fuentes, así que no
  lo contiene y `check_suite_inventory.py` no lo vigila.
- Tiene su propio `pytest.ini`: al apuntar pytest a este directorio, lo toma
  como raíz y no carga los `conftest.py` del producto.
- Playwright y Chromium son **obligatorios** aquí: si faltan, la batería falla
  al arrancar. No hay omisión por herramienta ausente (por eso los gates que
  buscan pruebas que se auto-omiten sin navegador no tienen nada que delegar).

## Qué necesita

En la máquina desde la que se lanza (la de la propia instalación sirve):

```
python3 -m venv <venv propio>
<venv>/bin/pip install playwright pytest
<venv>/bin/python -m playwright install --only-shell chromium
```

más las bibliotecas de sistema de Chromium (`playwright install-deps
chromium`, o el subconjunto que `ldd` del binario dé como ausente).

## Parametrización (todo por entorno; ningún secreto en el repo ni en argv)

| Variable | Obligatoria | Qué es |
|---|---|---|
| `S9K_RC_NAV_BASE_URL` | sí | URL pública `https://…` de la instalación |
| `S9K_RC_NAV_CA_FILE` | sí | CA (PEM) con la que se verifica la cadena TLS |
| `S9K_RC_NAV_CREDENCIALES` | sí | fichero JSON **0600 y fuera del repo** con las cuentas de prueba |
| `S9K_RC_NAV_SALIDA` | sí | directorio de evidencia, **fuera del repo** |
| `S9K_RC_NAV_CAPACIDADES` | no | lo que la instalación tiene (lista separada por comas; ver abajo) |
| `S9K_RC_NAV_IDLE_MINUTOS` | para inactividad | valor de `S9K_SESSION_IDLE_MINUTES` de la instalación |
| `S9K_RC_NAV_FASE_INACTIVIDAD` | para inactividad | `sembrar`, `tocar` o `comprobar` |
| `S9K_RC_NAV_FASE_PERSISTENCIA` | para 7.M3 / 14.M2a | `sembrar` antes del reinicio, `comprobar` después |
| `S9K_RC_NAV_MAX_INTENTOS` | no (5) | valor de `S9K_AUTH_MAX_FAILED_ATTEMPTS` |
| `S9K_RC_NAV_ESTADO_DIR` | no | dónde guardar el estado entre tandas (por defecto, junto a las credenciales) |
| `S9K_RC_NAV_WORKSPACE`, `S9K_RC_NAV_OTRO_WORKSPACE` | según prueba | workspace del ensayo y otro que no lo sea |
| `S9K_RC_NAV_FUENTE`, `S9K_RC_NAV_TERMINO` | no | fuente a ingerir y término de búsqueda del flujo |
| `S9K_RC_NAV_ESPERA_WORKER_S` | no (300) | espera máxima al worker |
| `S9K_RC_NAV_FLUJO_DESDE`, `S9K_RC_NAV_FLUJO_HASTA` | no | ventana del flujo completo |
| `S9K_RC_NAV_JOB_SELLADO`, `S9K_RC_NAV_JOB_CREDENCIAL` | según prueba | trabajos preparados de antemano |
| `S9K_RC_NAV_PARTIDA_A`, `S9K_RC_NAV_PARTIDA_B` | según prueba | las dos partidas del aislamiento entre lectores |
| `S9K_RC_NAV_PERFIL_BOVEDA` | no | ruta del perfil de la bóveda, para comprobar inodo, dueño y modo |

Sin las cuatro obligatorias la batería se niega a arrancar y dice cuál falta.

### Capacidades

Una prueba declara lo que necesita; lo que la instalación no declara **no se
ejecuta y no cuenta como verde**:

- `PENDING` — necesita Neo4j (marcador `necesita_grafo`) y no se declaró `grafo`.
- `BLOCKED` — necesita configuración del ensayo que no se declaró, o es una
  fase que esta tanda no pidió.

Capacidades: `grafo`, `panel_b`, `panel_c`, `panel_f`, `panel_g`, `resultado`,
`boveda`, `boveda_solo_lectura`, `boveda_inexistente`, `ingesta`, `apply`,
`aislamiento`, `job_credencial`, `partidas`, `setup_abierto` (su significado exacto está en
`soporte.py`). La declaración se contrasta con la instalación: hay pruebas que
fallan si un panel declarado no responde o si uno no declarado sí responde.

## Cuentas de prueba

`herramientas/usuarios_de_prueba.py crear` crea las cuentas por la CLI
canónica del producto (`s9k-cli.sh auth …`), genera sus contraseñas y las
guarda en el fichero 0600; las contraseñas viajan por la entrada estándar.
`retirar` las desactiva (la CLI no borra usuarios). **Hay que ejecutar `crear`
antes de cada tanda completa**: repone la obligación de cambiar la contraseña
de la cuenta `cambio` y desbloquea las demás.

Cada cuenta tiene un solo uso, porque el producto revoca las sesiones
anteriores de un usuario cada vez que entra.

## Ejecución

```
cd <clon>
export S9K_RC_NAV_BASE_URL=… S9K_RC_NAV_CA_FILE=… S9K_RC_NAV_CREDENCIALES=… S9K_RC_NAV_SALIDA=…
python -m pytest tests/rc_navegador -p no:randomly; echo PYTEST_RC=$?
```

Una sola instancia de Chromium y un solo proceso. La caducidad por inactividad
va en tres tandas cortas separadas en el tiempo (`test_nav_02_inactividad.py`
explica cuándo lanzar cada una).

## Enganche con el ejecutor de la RC-E2E

```
<python del venv> tests/rc_navegador/rc_paso.py --paso <id del contrato>
```

Ejecuta las pruebas cuyo `cubre(...)` nombra ese paso y sale con **0** (PASS),
**75** (BLOCKED: no cubierto, PENDING, falta configuración o no es su fase) u
otro valor (FAIL). Lee `RC_NAV_BASE_URL`, `RC_NAV_CA_FILE`, `RC_NAV_EVIDENCIA`,
`RC_NAV_WORKSPACE` y `RC_NAV_WORKSPACE_AJENO`; lo propio de la batería (cuentas,
capacidades, dónde está Chromium) lo toma de `tests/rc_navegador/.entorno-local`,
que no se versiona. Deja `<id>.resultado.json`, `<id>.png`, `<id>.txt` y las
capturas por prueba; en este modo no guarda trazas de Playwright. El detalle
está en la cabecera de `rc_paso.py`. También vale `pytest tests/rc_navegador
--paso <id>` a mano.

## Evidencia

Por prueba, en `S9K_RC_NAV_SALIDA/<módulo>/<prueba>/`: captura de pantalla y
HTML de cada paso, `pasos.json` y la traza de Playwright de cada contexto
(`traza-*.zip`, se abre con `playwright show-trace`). En la raíz de la salida:
`resultado.json` y `resultado.md` (estado declarado de cada prueba) y
`tls.json` (certificado servido y huellas).

Todo se guarda **sin secretos**: contraseñas, cookies y testigos CSRF se
sustituyen antes de escribir, y al terminar se recorre la salida entera
buscando los valores conocidos. Si aparece uno, la tanda termina en rojo.

## TLS

Antes de abrir el navegador se hace un handshake estricto con la CA declarada
(cadena y nombre). A Chromium se le pasa la huella de la clave pública de esa
cadena (`--ignore-certificate-errors-spki-list`), de modo que acepta ese
certificado y ningún otro; no se navega con los errores de certificado
desactivados.
