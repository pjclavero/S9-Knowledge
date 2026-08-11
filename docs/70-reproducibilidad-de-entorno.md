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

  5. **Fidelidad de los fragmentos**: todo job de `.github/ci-fragments/*.yml`
     que ya esté instalado en `ci.yml` debe coincidir con él (ignorando
     comentarios). Un fragmento existe para restituir un bloque que un
     conflicto se lleve por delante; si ha derivado, quien restituya desde él
     pierde pasos **en silencio**. Ya pasó: el fragmento se escribió antes de
     añadir el paso de calibración.

- `runtimes --require node,chromium` — comprobación **dinámica**, dentro del
  job: ¿está el runtime aquí y ahora, **y es el declarado**? Chromium se
  comprueba por el **binario que Playwright lanzaría**, no por que el paquete
  `playwright` esté instalado: esa diferencia es exactamente la que produjo el
  skip verde.

  Y no basta con que esté. Comprobar sólo la presencia era una **asimetría de
  fondo** —para los paquetes de Python se exigía versión y para los runtimes
  no— justo bajo la tesis «lo declarado tiene que ser lo ejecutado»: un `node`
  v18 al frente del `PATH` pasaba en verde con `node-version: '20'` declarado
  en el workflow, y la versión llegaba a imprimirse **sin compararla con
  nada**. La versión esperada se **deriva** de `ci.yml`, no se escribe en el
  comprobador: cambiar `node-version` cambia lo que el gate exige. Chromium no
  declara versión en el workflow (la fija Playwright), así que ahí sólo se
  exige presencia, y el gate lo dice en voz alta en vez de callarlo.

La raíz del repositorio es inyectable con `S9K_ENV_REPRO_ROOT`, para poder
calibrar el gate contra repositorios sintéticos sin romper el real.

### `.github/scripts/check_env_reproducibility_calibration.py`

La calibración, ejecutada **en cada corrida de CI**. Construye un repositorio
sintético que sale verde, y para cada una de las **21 reglas** (incluidos los
cinco caminos del `dependency_fingerprint` y el `node` de versión equivocada,
inyectado como ejecutable falso al frente del `PATH`): introduce la
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
repositorio declara: **7 errores sobre 6 paquetes** (`pytest` diverge de sus
**dos** declaraciones a la vez, la de `viewer/requirements.txt` y la del
`.lock` del motor, y cada una cuenta como un error):

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
| D1 | **ABIERTA, con motivo + procedimiento** | `viewer/` no tiene lock. No se genera aquí: el único `pip freeze` disponible es el de esta máquina, que diverge en 6 paquetes; un lock generado desde aquí **congelaría la divergencia** (`fastapi 0.139.0`, `argon2-cffi 23.1.0`) en vez de cerrarla — pondría el gate verde **bajando el listón** y convertiría un hallazgo de auditoría en hecho consagrado. El procedimiento para hacerlo bien está abajo. |
| D2 | **CERRADA** | `dependency_fingerprint` se calcula ahora sobre `pip freeze --all` del venv de la release (versiones **resueltas**), **y sólo si esa salida no está vacía y contiene los paquetes declarados**. Un `pip` que sale 0 sin decir nada producía el sha256 de la cadena vacía etiquetado como resuelto —el mismo defecto que D2 venía a cerrar, y peor: dos despliegues rotos compartirían huella y se leerían como «mismas dependencias»—; ahora eso es `dependency_fingerprint_source: unresolved` con valor `unknown`. Los cinco caminos (`none`, `declared-ranges`, `unresolved` ×2, `resolved:pip-freeze`) están calibrados en CI. |
| D3 | **ABIERTA, mitigada** | CI sigue instalando `viewer/requirements.txt` por rangos. Depende de D1. Mitigación: el job nuevo verifica que lo instalado cae dentro de lo declarado en cada corrida, así que un resolutor que se desvíe se ve; lo que no se garantiza es que dos corridas instalen lo mismo. |
| D4 | **CERRADA** | `python-multipart>=0.0.9,<0.1`. |
| D5 | **CERRADA, condicionada a instalación completa** | `pytest` y `pytest-asyncio` declarados en `data-engine/requirements.in`, y **check nuevo**: todo pin del `.lock` debe alcanzarse desde las raíces del `.in` por el grafo real de `Requires-Dist`. Ver el aviso de abajo sobre su precisión. |
| D6 | **SEÑALADA, no cerrada** | `preflight.sh` acepta 3.11+, CI sólo ejercita 3.13. El gate lo emite como `::warning::` derivado. No se cierra aquí porque el mínimo del preflight es una decisión del carril de despliegue: o se sube a 3.13, o CI añade una matriz de versiones. Tocarlo a ciegas podría bloquear un despliegue válido. |
| D7 | **SEÑALADA, con dueño y fecha** | `docs/v3/02-multimodal.md` fija `pypdf` en la versión 6.14.2 y el lock en la 6.15.0. El gate lo detecta comparando **toda** mención de versión exacta de `docs/**.md` contra el lock. No se corrige el fichero: este carril tiene prohibido tocar `docs/` salvo este documento. (Este documento evita escribir la cadena literal a propósito: la escribiría y su propio gate lo señalaría, con razón.) Ver el apartado de abajo. |

### D1 — cómo generar el lock del visor, bien

La capacidad **ya existe**: el job `check-env-reproducibility` instala en
limpio, en CI, desde los ficheros declarados. Falta ejecutar el procedimiento,
que es éste y **no se ejecuta aquí**:

1. En un job de CI (runner limpio, Python 3.13, sin caché de pip):
   `pip install -r viewer/requirements.txt`.
2. `pip freeze --all > viewer/requirements.lock` **en ese mismo job**. Nunca en
   una máquina de desarrollo: es lo que congelaría la divergencia.
3. Publicar el fichero como artefacto del job y abrirlo en un PR aparte, para
   que el lock quede revisable como cualquier otro cambio.
4. Cambiar los jobs de test a `pip install -r viewer/requirements.lock` y
   dejar `requirements.txt` como fichero de **entrada** (rangos), igual que
   `data-engine/requirements.in`.
5. El gate ya cubre lo demás: el check de fijación exigirá `==` en el nuevo
   `.lock`, y el de reconstruibilidad exigirá que todo pin se alcance desde
   `requirements.txt`.

Con eso D1 y D3 se cierran a la vez.

### D5 — precisión del check de reconstruibilidad

El argumento sobre los marcadores de entorno es correcto: ignorarlos
**sobre**-aproxima el cierre, así que un huérfano señalado lo es de verdad.
Pero hay una limitación en la otra dirección que conviene tener escrita: **el
grafo sale de las distribuciones instaladas en la máquina, no del `.lock`**. Si
un paquete no está instalado, sus aristas desaparecen y el cierre se
**sub**-aproxima, produciendo **falsos positivos** — un paquete legítimo,
alcanzable sólo a través del que falta, se declararía huérfano.

La guarda `if not requiere: continue` sólo cubre el caso de que no haya
**ningún** metadato; **no cubre la instalación parcial**. En CI es latente
porque el job instala ambos ficheros antes de ejecutar el check, así que el
grafo está completo. Fuera de CI, con un entorno a medias, este check puede dar
falsos positivos: **está condicionado a instalación completa.**

### D7 — dueño y fecha

Un `::warning::` sólo vale como transición **con dueño y fecha**; nadie está
obligado a mirar un aviso, y esta deriva es real y viva.

- **Qué queda abierto**: `docs/v3/02-multimodal.md` afirma una versión de
  `pypdf` que el `.lock` contradice. Cualquier lector que instale lo que dice
  la documentación se aparta del entorno declarado.
- **Falso positivo conocido del check**: `docs/65-preparacion-de-release.md`
  también se señala, pero allí la cadena aparece **citando** la deriva al
  documentar D7, no afirmándola. El check compara texto y no distingue una
  cita de una afirmación; por eso el aviso se lee, no se obedece a ciegas.
  Este mismo documento evita escribir la cadena literal justamente para no
  añadir un tercer falso positivo. Si D7 se promueve a error, hay que resolver
  antes esa distinción (por ejemplo, exceptuando los bloques de cita).
- **Dueño**: el carril propietario de `docs/v3/**` (documentación V3
  multimodal). Este carril no puede tocar `docs/` salvo este fichero.
- **Fecha**: en el siguiente cambio que toque `docs/v3/02-multimodal.md`, y en
  todo caso antes del próximo corte de release. Si al llegar ese corte el aviso
  sigue vivo, la reparación correcta no es silenciarlo sino **promoverlo a
  error** (`check_docs_versiones` ya produce la lista; basta moverla de
  `avisos` a `errores`).

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
