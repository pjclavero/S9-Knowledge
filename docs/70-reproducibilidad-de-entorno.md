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

Depende de **PyYAML** allí donde lee `ci.yml` (ver «Lo que leía el gate»
abajo). Dos modos:

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

  6. **Este gate no se puede apagar en silencio.** El job
     `check-env-reproducibility` tiene que existir, ejecutar `all` y ejecutar
     su calibración, y ninguna invocación del gate puede llevar la salida
     neutralizada (`|| true`, `|| :`, `|| exit 0`). Ver «Los seis
     supervivientes» abajo: la comprobación de fidelidad de fragmentos **no**
     cubría esto, porque un apagado aplicado a la vez en `ci.yml` y en el
     fragmento deja los dos idénticos.

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

  Y la comprobación **no puede apagarse sola**. Cuando la declaración existía
  pero no era legible —`node-version: ${{ env.NODE_V }}`, que es idioma normal
  de Actions— o cuando había **dos** `node-version` distintos, el gate dejaba
  de comparar versiones y seguía en verde con un `node` v18: la ausencia de una
  *declaración legible* degradaba la comprobación en silencio, que es
  exactamente lo que este carril persigue en los demás. Ahora cada caso es
  **rojo con su mensaje propio** —«no declara», «declara de forma no literal»,
  «declara varias distintas»—; antes el mensaje además **mentía**, decía «no
  declara version» cuando declaraba dos. La única salida verde es escribir la
  versión literal en el workflow.

La raíz del repositorio es inyectable con `S9K_ENV_REPRO_ROOT`, para poder
calibrar el gate contra repositorios sintéticos sin romper el real.

## Los seis supervivientes (revisión independiente de este PR)

Un revisor dictaminó **CONFORME CON OBSERVACIONES** y demostró seis mutaciones
que el carril **no** detectaba. Se reprodujeron una a una en verde antes de
tocar nada, y cada arreglo se comprobó rojo con la mutación y verde sin ella.
Los dos primeros son los graves, porque incumplían **dentro de este mismo PR**
la doctrina que el PR enuncia: *nada se apaga en silencio*.

| # | Mutación | Antes | Ahora | Dónde se cierra |
|---|---|---|---|---|
| 1 | `\|\| true` tras la invocación del gate, **a la vez** en `ci.yml` y en el fragmento | **VERDE**: el gate corre, falla, el paso pasa | ROJO por **dos** instrumentos independientes | `check_ci_config.py` (regla genérica) + `check_gate_no_apagado` (regla propia) |
| 2 | Quitar el paso de calibración, **a la vez** en ambos | **VERDE**: el gate corre sin instrumento calibrado | ROJO | `check_gate_no_apagado` |
| 3 | `# node-version: 18` dentro de un **comentario** YAML | ROJO falso (`('varias', ['18','20'])`) | VERDE limpio | lectura por `yaml.safe_load`, no por regex |
| 4 | `node-version: '20.x'`, idioma legítimo de `actions/setup-node` | ROJO falso (`ilegible`) | VERDE: se normaliza a major `20` | `RE_VERSION_LITERAL` |
| 5 | Stub de Chromium (0 bytes, `chmod 000`) en la ruta de Playwright | **VERDE**: `(True, ...)` | ROJO | `presente_chromium` exige `X_OK` **y** lanza `--version` |
| 6 | `zope.interface` satisfecho por `zope-interface` (el `.` era comodín) | **VERDE**: huella `resolved:pip-freeze` mintiendo | ROJO (`unresolved`) | `lib.sh` escapa el nombre antes de interpolarlo |

Las seis, **más cinco controles añadidos**, están ahora en el arnés de
calibración: no pueden volver sin ponerse rojas. Los controles extra existen
porque una mutación que sólo prueba el rojo no distingue un instrumento fino de
uno que se pone rojo ante todo:

- el job del gate **borrado** entero de `ci.yml` (la forma extrema de 1 y 2);
- Chromium ejecutable **que no dice su versión** → rojo;
- Chromium que arranca y **sí** la dice → verde (control positivo);
- `zope.interface` satisfecho por `zope.interface` → sigue resolviendo
  (control positivo del escape: romper todos los nombres con punto habría
  pasado por «arreglo»);
- `node-version: '20.x'` declarado con un `node` v18 en el `PATH` → **rojo**
  (control negativo: aceptar `20.x` no puede significar dejar de comparar).

### Lo que leía el gate, y por qué ahora parsea

Los supervivientes 3 y 4 tenían la misma causa: `ci.yml` se leía con una
**regex de texto**, teniendo el parseo YAML del carril L al lado. Un comentario
no es una declaración, y `'20.x'` es lo que documenta `actions/setup-node`.
Ninguno de los dos era un agujero —los dos fallaban **cerrados**, en rojo—,
pero un instrumento que no distingue un comentario de una declaración no está
midiendo lo que dice medir, y un falso positivo es un gate que alguien acabará
queriendo apagar. Ahora se leen las **claves del `with:`** del YAML parseado.

Si falta PyYAML, el gate **no** vuelve al texto: se pone rojo pidiendo que se
instale. Por eso `test-graph-js` hace `pip install pyyaml` antes de invocar
`runtimes --require node`. `runtimes --require chromium` no lo necesita:
Chromium no declara versión en el workflow, así que ese camino no llega a
parsear nada.

### Coordinación con el carril L

La prohibición **genérica** de `|| true` vive en
`.github/scripts/check_ci_config.py`, que es de otro carril, porque es su sitio
natural: allí ya se parsea YAML de verdad y ya se prohíbe `continue-on-error`,
que es exactamente el mismo apagado una capa más arriba. Prohibir el campo YAML
y dejar libre su equivalente en el shell era vigilar la puerta y no la ventana.
Se añadieron allí dos reglas y **tres casos a su propia calibración**
(`calibra_gate_integrity.py`), que pasa **23/23** — incluidos su `estado
correcto` y su `restaurado` en verde, que es la prueba de que no se rompió nada
suyo. Nótese que el `ci.yml` real contiene comentarios que dicen «Sin
`|| true`: …»: la regla mira **código**, no texto, y ese caso verde lo
demuestra.

`check_gate_no_apagado` **duplica** a propósito la parte que afecta a este
carril. El solape es el mismo criterio que ya se aplicó con Node: dos gates que
fallan por el mismo motivo es mejor que cero, y éste sobrevive aunque alguien
afloje el otro.

### Ablación: qué control es realmente el que sostiene cada rojo

Cada control nuevo se retiró de una copia del árbol para comprobar que **algún
resultado cambia**. Uno de los cinco **no** pasó la prueba, y conviene dejarlo
escrito en vez de presentarlo como si hubiera pasado:

| Control retirado | ¿Cambia algo? |
|---|---|
| `check_gate_no_apagado` | Sí: 1, 2 y el job borrado dejan de detectarse |
| `comprueba_neutralizacion` (L) | Sí: los casos `\|\| true` y `\|\| :` de la calibración de L se desvían |
| `comprueba_jobs_exigidos` (L) | Sí: el caso «job exigido que desaparece» se desvía |
| `os.access(X_OK)` en `presente_chromium` | **No**: nada cambia |
| `presente_chromium` entero (vuelta a `os.path.exists`) | Sí: los dos casos de 5 dejan de detectarse |
| lectura semántica de `ci.yml` (vuelta a regex) | Sí — **pero sólo tras corregir la calibración**, ver abajo |

Es decir: en el superviviente 5 **lo que sostiene el rojo es lanzar el binario**,
no el `os.access`. El `X_OK` es redundante y se conserva sólo porque convierte
un `OSError` opaco en un mensaje que dice qué pasa («existe pero no es
ejecutable»). No se presenta como una barrera: no lo es.

**Y la ablación encontró una calibración decorativa, que es el hallazgo más
incómodo de esta ronda.** Los casos de 3 y 4 se escribieron primero en modo
`all`, y `version_declarada` **sólo se ejecuta en modo `runtimes`**: el código
bajo prueba ni siquiera corría, así que esos dos casos habrían salido verdes
pasara lo que pasara. Al revertir por ablación la lectura a regex seguían en
verde, y eso los delató. Ahora viven en `calibra_declaracion_node`, que corre
el modo correcto con un `node` falso al frente del `PATH`, y llevan además un
**control negativo** (`20.x` declarado con un `node` v18 presente → sigue
siendo ROJO). Sin ese control, «aceptar `20.x`» sería indistinguible de «dejar
de comprobar la versión», que es exactamente el defecto que este carril cerró
en la ronda anterior.

La lección se aplica a cualquier arnés: un caso de calibración que no ejercita
el código que dice medir es un verde tan vacío como el que persigue el gate.
La prueba de ablación es lo único que lo distingue.

### `.github/scripts/check_env_reproducibility_calibration.py`

La calibración, ejecutada **en cada corrida de CI**. Construye un repositorio
sintético que sale verde, y para cada una de las **35 reglas** (incluidos los
ocho caminos del `dependency_fingerprint`, los seis supervivientes de la
revisión con sus controles positivos, y el `node` de versión equivocada,
inyectado como ejecutable falso al frente del `PATH`): introduce la
violación, exige rojo (o el aviso, para las señaladas) con el mensaje
correcto, revierte y exige verde. Un gate cuyo mecanismo de medida no se
prueba puede llevar meses sin poder ponerse rojo.

Esta calibración ya encontró un defecto real en la primera versión del propio
comprobador: daba por cubierto cualquier test cuya carpeta se llamara `tests`,
porque comparaba nombres sueltos en el texto de `ci.yml` en vez de prefijos de
ruta dentro del job que aprovisiona el runtime.

Y volvió a encontrar otro al añadir los supervivientes: la mutación
`paso runtimes --require retirado` quitaba el comando pero **no su sangría**,
dejando un `ci.yml` que ni siquiera era YAML válido. Salía roja, sí, pero por
el motivo equivocado; una mutación que produce un workflow imposible no prueba
lo que dice probar. Se corrigió, y de paso el gate dejó de reventar con una
traza ante un `ci.yml` ilegible: ahora es un rojo con mensaje.

### CI

| Sitio | Qué añade |
|---|---|
| job `check-env-reproducibility` | instala lo declarado (lock + requirements, mismo orden que el job combinado), corre la calibración y después `all --strict-missing` |
| paso en `test-graph-js` | `pip install pyyaml` y `runtimes --require node` |
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

**Por qué el verde de CI no dice nada sobre esto.** El job
`check-env-reproducibility` empieza instalando lo declarado
(`requirements.lock` + `requirements.txt`), así que cuando el gate compara
«declarado contra instalado» las dos cosas coinciden **por construcción**: el
runner acaba de fabricar esa coincidencia. El gate es honesto —mide lo que
dice medir— pero su verde certifica **el entorno de CI**, no el de nadie más.
Las 7 divergencias son reales y sólo se ven donde el entorno no lo fabrica el
runner: en local, y en cualquier despliegue.

Estas 7 divergencias **no se cierran desde este carril**. Actualizar los
paquetes cambia el entorno de todo el mundo y es decisión del operador; y
generar aquí un lock desde este `pip freeze` **congelaría** la divergencia en
vez de cerrarla (ver D1). El gate debe seguir señalándolas en rojo: son un
hallazgo, no un fallo del instrumento.

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
| D2 | **CERRADA** | `dependency_fingerprint` se calcula ahora sobre `pip freeze --all` del venv de la release (versiones **resueltas**), **y sólo si esa salida no está vacía y contiene los paquetes declarados**. Un `pip` que sale 0 sin decir nada producía el sha256 de la cadena vacía etiquetado como resuelto —el mismo defecto que D2 venía a cerrar, y peor: dos despliegues rotos compartirían huella y se leerían como «mismas dependencias»—; ahora eso es `dependency_fingerprint_source: unresolved` con valor `unknown`. La comprobación de «contiene los paquetes declarados» compara el nombre **completo**: incluir `-` en la clase del separador hacía que `fastapi-extra==1.0` satisficiera el requisito de `fastapi`, y un venv sin `fastapi` se etiquetaba como resuelto. Los seis caminos (`none`, `declared-ranges`, `unresolved` ×3 —vacío, sin lo declarado, colisión de prefijo—, `resolved:pip-freeze`) están calibrados en CI. |
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
- **`set +e` sin comprobar el código de retorno.** La regla nueva caza
  `|| true`, `|| :` y `|| exit 0`. No caza un `set +e` que luego **no** mire
  `$rc`: en `ci.yml` los `set +e` que hay sí capturan el código y deciden con
  él (es el idioma que permite imprimir la salida de pytest antes de fallar),
  así que prohibirlos rompería jobs correctos. Un `set +e` descuidado sigue
  siendo un apagado posible y **no está cerrado**.
- **Neutralización repartida entre líneas.** Se mira línea a línea; un apagado
  escrito en varias (`cmd \` + continuación, o una función de shell que
  siempre devuelve 0) no se detecta.
- **El gate se juzga a sí mismo.** `check_gate_no_apagado` sólo puede hablar si
  el gate se ejecuta. Que el job desaparezca lo cubre el carril L
  (`JOBS_EXIGIDOS`), que es un job distinto; pero si alguien apagara **los
  dos** a la vez, no queda tercer instrumento.
