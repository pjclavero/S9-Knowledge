# 70 — Reproducibilidad de entorno

Cierra la brecha entre lo que el repositorio **declara** que necesita y lo que
CI y el entorno real **ejecutan**.

## Por qué

Cuatro formas de verde que no comprobaba nada, todas vistas en este proyecto:

1. **Versión declarada ≠ instalada.** `viewer/requirements.txt` pide
   `fastapi>=0.141.1` y `pytest>=9.1.1`; un entorno con `fastapi 0.139.0` y
   `pytest 8.4.2` ejecutaba la suite igual y salía verde. Ese verde no dice
   nada sobre la versión que el repositorio declara necesitar.
2. **Declarado sin fijar.** Un `.lock` que no fija con `==` no es un lock.
   Un rango sin cota superior (`python-multipart>=0.0.9`) instala mañana una
   versión que nadie ha probado, sin que cambie una línea del repositorio.
3. **Usado y no declarado.** `viewer/app/auth/middleware.py` importa
   `starlette` directamente y `starlette` no estaba declarado: llegaba
   arrastrado por FastAPI. El día que FastAPI cambie de rango, el fallo
   aparece en ejecución, no al instalar.
4. **Runtime ausente leído como verde.** Dos veces una suite se auto-omitió
   por falta de Node o de Chromium y el job siguió en verde; las **171**
   pruebas de `viewer/tests/browser` se saltan enteras si el binario del
   navegador no está, porque el `importorskip` vive en el `conftest.py` del
   directorio. **La ausencia de un runtime es un FALLO RUIDOSO, jamás un
   skip.**

## Qué hay

### `.github/scripts/check_env_reproducibility.py`

Sin dependencias externas. Dos modos:

- `all [--strict-missing] [--strict-pinning]` — comprobación estática:
  1. **Versiones**: cada requisito declarado en `viewer/requirements.txt` y
     `data-engine/requirements.lock` se compara con la versión realmente
     instalada (`importlib.metadata`). Divergencia → **rojo**. Además detecta
     el conflicto entre ficheros: si el `.lock` fija una versión que el rango
     del otro fichero no admite, la versión realmente probada dependería del
     orden de instalación del job combinado.
  2. **Fijación**: en un `.lock`, cualquier entrada que no use `==` es
     **rojo**. En `requirements.txt`, la falta de cota superior o inferior se
     **señala** (aviso), y con `--strict-pinning` pasa a rojo.
  3. **Usadas y no declaradas**: los imports se **derivan** del árbol de
     fuentes con `ast` y se mapean a distribución instalada. No hay lista que
     mantener.
  4. **Puertas de runtime**: se **deriva** del árbol de tests qué ficheros se
     auto-omiten sin Node o sin Chromium (`shutil.which`, `importorskip`,
     `skip` con mensaje de runtime), distinguiendo si la omisión es a nivel de
     módulo —que arrastra el directorio entero, el caso de las 171— o dentro
     de una función. Para cada fichero se exige un job de `ci.yml` que, **en
     el mismo job**: aprovisione el runtime, ejecute ese fichero entre sus
     objetivos de pytest, lleve guardia antisalto (`skipped`) e invoque
     `runtimes --require`.

- `runtimes --require node,chromium` — comprobación **dinámica**, dentro del
  job: ¿está el runtime aquí y ahora? Chromium se comprueba por el **binario
  que Playwright lanzaría**, no por que el paquete `playwright` esté
  instalado: esa diferencia es exactamente la que produjo el skip verde.

La raíz del repositorio es inyectable con `S9K_ENV_REPRO_ROOT`, para poder
calibrar el gate contra repositorios sintéticos sin romper el real.

### `.github/scripts/check_env_reproducibility_calibration.py`

La calibración, ejecutada **en cada corrida de CI**. Construye un repositorio
sintético que sale verde, y para cada una de las **14 reglas**: introduce la
violación, exige rojo (o el aviso, para las señaladas) con el mensaje
correcto, revierte y exige verde. Un gate cuyo mecanismo de medida no se
prueba puede llevar meses sin poder ponerse rojo.

Esta calibración ya encontró un defecto real en la primera versión del propio
comprobador: daba por cubierto cualquier test cuya carpeta se llamara `tests`,
porque comparaba nombres sueltos en el texto de `ci.yml` en vez de prefijos de
ruta dentro del job que aprovisiona el runtime.

### CI

| Sitio | Qué añade |
|---|---|
| job `check-env-reproducibility` | instala lo declarado (lock + requirements, mismo orden que el job combinado), corre la calibración y después `all --strict-missing` |
| paso en `test-graph-js` | `runtimes --require node` |
| paso en `test-login-browser` | `runtimes --require chromium`, tras `playwright install` |

El bloque del job tiene copia canónica en
`.github/ci-fragments/check-env-reproducibility.yml`: varios carriles editan
`ci.yml` a la vez y una resolución de conflicto podría llevárselo por delante.
Si eso pasa, el propio gate señala la pérdida de los pasos `--require`.

## Limitación explícita: los resultados LOCALES de esta sesión no son de fiar

Esto es el hallazgo con más alcance del carril y no afecta sólo a este trabajo.

El entorno de desarrollo local **no** tiene instaladas las versiones que el
repositorio declara. Siete divergencias reales, medidas por el gate:

| Paquete | Declarado | Instalado en local |
|---|---|---|
| `fastapi` | `>=0.141.1,<1.0` | `0.139.0` |
| `pytest` | `>=9.1.1,<10.0` / `==9.1.1` | `8.4.2` |
| `argon2-cffi` | `>=25.1.0,<26.0` | `23.1.0` |
| `aiohttp` | `==3.14.3` | `3.14.1` |
| `packaging` | `==26.2` | `25.0` |
| `pypdf` | `==6.15.0` | `6.14.2` |

Consecuencia, dicha con todas las letras: **las suites que llevamos toda la
sesión ejecutando en local NO corrían con las versiones declaradas.** No es un
detalle de higiene:

- `argon2-cffi 23.1.0` frente a `>=25.1.0` está **en la cadena de
  autenticación**: el hashing de contraseñas que se probaba en local no es el
  que se declara para producción.
- `pytest 8.4.2` frente a `==9.1.1` cambia **cómo se recolecta y cómo se
  salta**, que es exactamente el mecanismo del que dependen los skips
  silenciosos que este carril persigue.

Por tanto: **en CI el gate sale verde; en local, rojo.** Todo resultado local
del proyecto —de cualquier carril, no sólo de éste— queda degradado en
confianza mientras el entorno local no se alinee. La evidencia que cuenta es
la de CI, y conviene reinstalar en local con `pip install -r
data-engine/requirements.lock -r viewer/requirements.txt` antes de dar peso a
una corrida local.

## Divergencias del carril I (D1–D7)

| # | Estado | Detalle |
|---|---|---|
| D1 | **ABIERTA, con motivo** | `viewer/` no tiene lock. No se genera aquí: el único `pip freeze` disponible es el de esta máquina, que diverge en 7 paquetes; un lock generado desde aquí **congelaría la divergencia** (`fastapi 0.139.0`, `argon2-cffi 23.1.0`) en vez de cerrarla. Hay que generarlo desde un entorno limpio, en CI. |
| D2 | **CERRADA** | `dependency_fingerprint` se calcula ahora sobre `pip freeze --all` del venv de la release (versiones **resueltas**). Cuando el venv no existe, el valor no se disfraza: lleva prefijo `ranges-sha256:` y se añade `dependency_fingerprint_source` (`resolved:pip-freeze` / `declared-ranges` / `none`) para que ningún consumidor lo confunda. |
| D3 | **ABIERTA, mitigada** | CI sigue instalando `viewer/requirements.txt` por rangos. Depende de D1. Mitigación: el job nuevo verifica que lo instalado cae dentro de lo declarado en cada corrida, así que un resolutor que se desvíe se ve; lo que no se garantiza es que dos corridas instalen lo mismo. |
| D4 | **CERRADA** | `python-multipart>=0.0.9,<0.1`. |
| D5 | **CERRADA** | `pytest` y `pytest-asyncio` declarados en `data-engine/requirements.in`, y **check nuevo**: todo pin del `.lock` debe alcanzarse desde las raíces del `.in` por el grafo real de `Requires-Dist`. Un huérfano futuro pone el gate en rojo. |
| D6 | **SEÑALADA, no cerrada** | `preflight.sh` acepta 3.11+, CI sólo ejercita 3.13. El gate lo emite como `::warning::` derivado. No se cierra aquí porque el mínimo del preflight es una decisión del carril de despliegue: o se sube a 3.13, o CI añade una matriz de versiones. Tocarlo a ciegas podría bloquear un despliegue válido. |
| D7 | **SEÑALADA, no cerrada** | `docs/v3/02-multimodal.md` fija `pypdf` en la versión 6.14.2 y el lock en la 6.15.0. El gate lo detecta comparando **toda** mención de versión exacta de `docs/**.md` contra el lock. No se corrige el fichero: este carril tiene prohibido tocar `docs/` salvo este documento. (Este documento evita escribir la cadena literal a propósito: la escribiría y su propio gate lo señalaría, con razón.) |

## Qué NO cubre

- **No fija el entorno**, lo audita: no genera locks ni construye imágenes.
  `viewer/requirements.txt` sigue siendo de rangos; el gate garantiza que lo
  instalado cae dentro del rango, no que dos máquinas instalen lo mismo. Un
  `viewer/requirements.lock` generado sería el siguiente paso.
- **Sólo Python y dos runtimes.** Node y Chromium están cubiertos porque son
  los que fallaron. Añadir otro (tesseract, ffmpeg…) es añadir una entrada en
  `RUNTIMES` y sus patrones; el resto se deriva solo.
- **No comprueba dependencias del sistema** (paquetes apt, versión del kernel)
  ni la coincidencia entre CI y producción.
