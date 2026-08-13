# CHANGELOG — S9 Knowledge

Formato basado en Keep a Changelog. Fechas en ISO-8601.

## [Unreleased]

### 2026-08-13 — El titular deja de mentir con la historia truncada, y el ultimo arreglo sin prueba pasa a tenerla

- **FUGA CERRADA: el titular no se calificaba con la historia truncada.** Era
  el defecto que este script ya habia corregido para `S9_DOCS_SKIP_GIT`
  reapareciendo **por otra puerta**. Escenario medido y reproducido: clon
  superficial + `--unshallow` imposible + `main_commit` = la punta ⇒ la
  existencia y la ancestria son triviales, la ventana de PR se saltaba en
  silencio, y un `latest_merged_pr: #4242` **INVENTADO pasaba en VERDE
  (`rc=0`)** bajo «DOCUMENTACION COHERENTE» a secas, con un `AVISO:` perdido
  media pagina mas arriba. Ahora: si hay un valor **declarado** que no se ha
  podido comprobar, es **ROJO**; y si no hay nada que comprobar, el titular
  dice **`COHERENTE (HISTORIA TRUNCADA)`**. Quien lee la ultima linea de un log
  ya no se lleva un verde que no ha comprobado lo que dice.
- **El «latente de regalo» pasa a tener falsador.** `_merged_prs(real_sha)` en
  vez de `_merged_prs(ref)` era un arreglo legitimo **pero sin prueba**:
  revertirlo dejaba 0 filas rojas, porque en el sandbox el nombre simbolico y
  el SHA nunca divergian. Era la misma familia que el orden de `_merged_prs` en
  la primera revision. **C18** los hace divergir por el mecanismo real —el
  `fetch --unshallow` del rescate moviendo `refs/remotes/origin/main` bajo los
  pies mientras el remoto avanza por otra linea—, y revertir el arreglo la pone
  roja. Un arreglo presentado como hallazgo tiene que poder ponerse rojo.
- **`latest_ci`: limitacion DECLARADA, no tapada.** Es el unico campo de
  `development` que **no valida nadie**: declararlo `green` sobre un commit con
  la CI en rojo pasa en verde. No se cubre porque el **oraculo esta fuera**
  (vive en GitHub; el gate corre sin red ni credenciales), y **no** se anade
  una comprobacion de vocabulario para aparentar cobertura: no podria fallar en
  el caso que importa. Queda dicho en el script y en la fila **C20**
  (`xfail(strict=True)`), que gritara por XPASS el dia que haya oraculo.
- **Calibracion:** 3 ablaciones dirigidas, **3 rojas** (fuga del #4242, titular
  sin calificar, `_merged_prs` por nombre simbolico), revertidas byte a byte.
  Suite del fichero: **66 passed, 6 xfailed**.

### 2026-08-12 (c) — El aviso programado se cumplio, y al cumplirse destapo un fallo real del gate

Al fusionar el #169, `main@0dfa788` se puso ROJO. Una de las dos causas era la
prevista y documentada; la otra era un **defecto del instrumento** que solo se
vio porque ocurrio la primera.

- **El desfase, refrescado REMIDIENDO.** `development.main_commit` paso a estar
  **8** commits por detras (ventana 3) y `Combined Test Suite` lo dijo. Se sube
  a `0dfa788` y `latest_merged_pr` a **#169**, con el README al dia. **No se ha
  tocado `max_lag_commits`**: subirlo es el antipatron que este mismo fichero
  dejo escrito. `latest_ci` se declara **`red`**, porque en `0dfa788` lo esta:
  escribir `green` seria justo la mentira coherente que el punto 0 existe para
  matar.
- **DEFECTO REAL: el rescate del clon superficial era CODIGO MUERTO en CI.**
  `Deployment scripts validation` (checkout por defecto, `fetch-depth: 1`)
  acusaba a `main_commit` de **«NO EXISTE en el repositorio»** siendo un
  ancestro perfectamente real, y de que el PR declarado «no aparece entre los
  **1** ultimos PR fusionados». Causa medida, reproducida paso a paso: con
  `fetch-depth: 1`, `actions/checkout` deja creados `main` **y** `origin/main`,
  asi que `_try_local_main` acierta a la primera y `_resolve_main` **vuelve
  antes de llegar al `--unshallow`**. El punto 0 se ejecutaba sobre UN commit
  de historia. **Y ahi estaba el aprobado facil de C15d/C15e/C15f:** las tres
  parten de que `main` NO es resoluble, que es exactamente lo que CI nunca
  cumple.
- **Arreglo:** la profundidad se asegura en `_deepen_if_shallow()`, en el unico
  sitio por el que pasan todas las comprobaciones, y no como efecto colateral
  de no encontrar una referencia. Resolver `main` no basta: el punto 0 necesita
  HISTORIA para responder a la ancestria y al desfase.
- **Y cuando no se puede completar, el gate dice la VERDAD.** «No lo veo» no es
  «no existe»: con la historia truncada un ancestro real es indistinguible de
  uno inventado. Sigue siendo ROJO —fail-closed—, pero con el diagnostico
  correcto en vez de acusar de mentir a un documento que no miente. La ventana
  de PR deja de opinar sobre una historia de un commit.
- **Ademas, un latente:** `_merged_prs` se leia del nombre simbolico `origin/main`,
  que el `fetch` del rescate puede MOVER bajo los pies; ahora se lee del SHA ya
  resuelto, para que existencia, ancestria y ventana hablen todas del mismo
  commit. Se vio en la reproduccion, no razonando.
- **Filas nuevas C17a/C17b** sobre un clon superficial CON `main` y
  `origin/main`, que es la forma de verdad. Calibracion: 3 ablaciones dirigidas
  a este arreglo, **3 rojas**; con `_deepen_if_shallow` neutralizado —el estado
  exacto de `main@0dfa788`— C17 da **2 rojas**.
- **Recuento de jobs: sigue siendo 14** (13 en `ci.yml` + 1 en
  `supply-chain.yml`), medido contra `main@0dfa788`; `main` **no** se quejaba
  de esta cifra. Se deja como LITERAL y no como cuenta derivada de los
  workflows: derivarla la haria siempre cierta y C13 dejaria de poder ponerse
  roja. Queda anotado que el PR #167 anade un job y habra que refrescarla a 15
  **cuando se fusione**, no antes.

### 2026-08-12 (b) — Cuatro huecos de cobertura cerrados, y la estrechez que queda queda DICHA

Revision independiente del PR #169. Ninguna cifra del PR resulto falsa; lo que
faltaba era **red debajo de cuatro afirmaciones**. Se cierran con el metodo de
siempre: falso negativo en verde primero, arreglo, **rojo**, reversion, verde.

- **R5 solo cazaba la redaccion historica literal.** El revisor metio seis
  frases falsas en `README.md` y **las seis pasaron en verde** contra el repo
  real (`rc=0`, medido): «siguen sin disparar CI», «CI no se dispara en ramas <!-- consistency:ignore -->
  `ops/**`», «el push a `test/**` no lanza CI», «CI unicamente corre en <!-- consistency:ignore -->
  `main`», «solo las ramas de la lista blanca disparan CI». `RX_NO_CI` pasa a <!-- consistency:ignore -->
  cubrir cuatro familias (negacion antes y despues de «CI», negacion por
  «sin …», y exclusividad «solo/unicamente …») y `RX_ALL_CI` cubre «cada /
  cualquier / todas las ramas» y «CI en todas las ramas». Las cinco frases
  negativas enrojecen ahora (**C4d**); la sexta, «cada rama dispara CI», es
  **cierta** hoy y su cobertura es la direccion simetrica (**C4c3**).
  **Estrechez que QUEDA, declarada con `xfail(strict=True)` y CUATRO frases
  concretas (C4e):** «el workflow ignora las ramas …» (no contiene siquiera el
  token «CI»), «arranca al abrir el PR, nunca en el push» (negacion desplazada
  al disparador), «es invisible para CI» (metafora) y «hay una lista blanca de
  prefijos» (describe un mecanismo sin negar nada). Esas cuatro no son
  enumerables y perseguirlas daria un gate ruidoso. **Las otras tres que se
  habian declarado incobrables SI lo eran** y se han cubierto en la segunda
  revision (familia (e) de `RX_NO_CI`): «CI queda excluido en …», «CI se limita
  a …» —que es la misma exclusividad que ya estaba implementada— y «fuera del
  alcance de CI». Declararlas incobrables era pereza, no honestidad.
- **«Ruido cero» estaba mal medido, y el gate mordia nuestro propio texto.**
  Comprobar que el texto de HOY sigue verde es **suficiencia**, no ausencia de
  falsos positivos. Medido sobre ocho frases legitimas, **cuatro enrojecian**:
  «CI se limita a informar: no bloquea el merge» —que es literalmente la tesis
  de **RK-20b** en prosa—, «el job de CI se limita a 20 minutos», «CI se limita
  a 14 jobs por PR» y «ese refactor queda fuera del alcance de este PR; CI no
  cambia», un descargo de alcance frecuentisimo en `CHANGELOG.md` y
  `ROADMAP.md`, que estan en `DOCS`. Causa: la familia (e) no exigia que el
  objeto fueran **ramas**. Se ancla a un token de rama (`_BRANCH`), como ya
  hacia `RX_ALL_CI`. Medido tras el arreglo: **8/8 legitimas en verde, 3/3
  falsas en rojo**, y las filas de C4d intactas. Nueva fila **C4f** para que
  los cuatro falsos positivos no puedan volver: quitando el ancla, C4f da
  exactamente **4 rojas**. Un gate que muerde el texto correcto se desactiva.
- **El sandbox daba un aprobado facil a `_merged_prs`.** Su historia sintetica
  era `#101 -> #102`, **monotona creciente**, asi que era incapaz de expresar
  el caso que la propia funcion declara load-bearing («en `main` real el #160
  se fusiono ANTES que el #158»): sustituir el orden cronologico por
  `sorted(reverse=True)` **no ponia roja ni una prueba**. La historia pasa a
  ser `#101 -> #105 -> #103`: el ultimo fusionado es el #103 y el mayor es el <!-- consistency:ignore -->
  #105. **C14a** (orden) y **C14b** (extremo a extremo con tolerancia 0)
  enrojecen con el orden numerico.
- **`_resolve_main` no tenia ni una prueba**: era la unica funcion del punto 0
  sin cobertura, y justo la que puso rojo el primer CI de este PR (rescate del
  clon superficial). C11 la monkeypatcheaba entera, asi que en CI solo
  enrojecia **por accidente del entorno**. Se anaden **C15a** (prefiere
  `origin/main` sobre un `main` local parado), **C15b** (cae al `main` local y
  lo dice en el `ref`) y **C15c** (sin ninguno de los dos y sin remoto:
  `(None, None)` y gate ROJO, ejecutando la funcion de verdad). **Y el rescate
  del clon superficial, que era el UNICO superviviente de la primera revision:**
  borrar entero el bloque `--unshallow` + `fetch` **no ponia roja ni una fila**
  (medido: la suite anterior seguia en verde con el bloque eliminado), asi que
  ese camino solo lo mitigaba un accidente del entorno —`Deployment scripts
  validation` hace checkout superficial—, no la tabla. **C15d** clona el
  sandbox con `--depth 1` sobre `file://`, le quita `origin/main` y `main`
  —exactamente lo que ve CI con `fetch-depth: 1`— y exige que `_resolve_main`
  lo recupere. Con el bloque eliminado, C15d enrojece. **Y una linea por fila,
  no el bloque como un todo:** cubrirlo entero enmascaraba su redundancia —el
  revisor midio que neutralizar `--unshallow`, o quitar el `fetch` normal, o
  quitar la salida por `FETCH_HEAD`, daba **0 rojas cada una**—. Ademas,
  recuperar el SHA **no exige `--unshallow`**: en un clon superficial el
  `fetch` normal ya trae `origin/main`, asi que C15d pasaba por un mecanismo
  distinto del que anunciaba (la misma forma del defecto de C9). `--unshallow`
  existe para poder calcular **ancestria y desfase**, asi que C15d lo comprueba
  ahora (`merge-base --is-ancestor`, `rev-list --count`, y que el clon deje de
  ser superficial); **C15e** ejerce la salida por `FETCH_HEAD` (refspec
  restringido, que es lo que configura `actions/checkout`) y **C15f** el
  `fetch` normal en un clon completo sin las dos referencias. Las tres lineas
  enrojecen ahora por separado.
- **Quitar la exigencia de SHA de 40 hex no ponia rojo nada.** Nueva fila
  **C16**: un `main_commit` abreviado enrojece, y se comprueba que la queja es
  la longitud y no otra (el commit existe y esta en `main`).
- **C4c acertaba por el motivo equivocado** (observacion menor del revisor):
  con la clave `on:` de YAML 1.1 rota, `_push_branches` devuelve `[]`,
  `universal` cae a `False` y la fila pasaba igual; solo C4b enrojecia. Ahora
  C4c **exige que el hallazgo cite la lista blanca leida**, y se anade
  **C4c2**, que comprueba el parser contra el `ci.yml` REAL.
- **Calibracion:** 13 ablaciones dirigidas, **13 rojas**, todas revertidas byte
  a byte; y con los patrones historicos restaurados enteros, **14 de las 15**
  filas de R5 caen (la superviviente es justo la redaccion que el patron viejo
  ya cubria). Suite del fichero: **61 passed, 5 xfailed**.
- **Pendientes cerrados sin trabajo pendiente:** las observaciones «O5» y «O6»
  que arrastraba la lista **no existen en este repositorio** — no aparecen en
  el arbol, ni en el cuerpo o los comentarios del #169, ni en los PR #160-#171;
  provienen de un encargo externo al repositorio. Se retiran en vez de dejarse
  abiertas para siempre.
- **`RK-20` pasa a CERRADO en cuanto a la cifra**, verificado contra GitHub y
  no contra un documento: la proteccion de `main` devuelve **11 contextos**, y
  los tres jobs ausentes son **exactamente** los tres de
  `ci_running_but_not_required`. El riesgo de fondo (esos tres corren pero no
  bloquean) se separa en **`RK-20b`, ABIERTO**, que depende del operador.
- **Aviso programado, medido y no estimado:** `development.main_commit` va **2**
  commits por detras de `origin/main` con la ventana en **3**. **El proximo
  merge a `main` pondra ese gate rojo**, y ese rojo es lo que el campo existe
  para decir, no una regresion. Anotado en `docs/project-status.yaml` junto a
  `max_lag_commits`, con el arreglo (remedir) y el antipatron (subir la
  ventana para apagar el aviso).

### 2026-08-12 — El punto 0 pasa a tener pruebas, y el gate deja de creerse a si mismo

- **Las ~300 lineas del punto 0 no tenian ni un test.** La tabla de calibracion
  vivia en la descripcion del PR, que no se ejecuta. Se lleva a
  `deploy/tests/test_docs_consistency.py` como **C0-C13** sobre un repositorio
  Git **sintetico** (historia propia, `origin/main` propio, workflows propios),
  asi que las filas que dependen de ancestria y desfase son deterministas en
  cualquier maquina. Calibrado por mutacion del validador: **8 mutaciones, 8
  rojos**; ninguna sobrevive en verde.
- **C9 estaba mal en la tabla original**: se ejecutaba tocando solo el YAML, de
  modo que el verde/rojo lo decidia la comparacion documento-YAML y no la
  ventana `max_lag_commits` que la fila decia medir. Ahora los documentos se
  mueven con el YAML (C9) y el otro mecanismo se prueba por separado (C9b).
- **`S9_DOCS_SKIP_GIT=1` ya no imprime «DOCUMENTACION COHERENTE» a secas.** El
  titular dice **«COHERENTE (SIN VERIFICAR CONTRA GIT)»**: quien lee la ultima
  linea de un log no puede llevarse un verde que no se ha comprobado. Y se
  anade una comprobacion de que esa variable **no aparece en ningun workflow**
  de `.github/workflows/`: en CI convertiria el gate en un verde ciego.
- **El validador ya lee `ci.yml`.** Una afirmacion falsa sobre los disparadores
  de CI —«`test/**` se queda sin CI», el defecto exacto que hizo NO CONFORME a
  `bf03ca7`— pasaba en verde porque el script no abria un solo workflow. Ahora
  se contrasta contra `on.push.branches`, en ambos sentidos (C4b y C4c).
- **Los numeros de RK-20 se verifican.**
  `ci_jobs_running`/`ci_checks_required`/`ci_running_but_not_required` se
  contrastan contra los jobs definidos en `.github/workflows/`; ponerlos a
  99/99 daba verde y ahora enrojece. **Limite declarado:** que un job sea
  *check requerido* vive en los ajustes de GitHub, no en el repositorio.
- **RK-19: retirada una fecha inventada.** Decia que `.env.example` se corrigio
  el 2026-08-09; `git log` demuestra que el primer commit que lo corrige es el
  de este mismo PR. Una fecha inventada dentro del PR cuya tesis es no fiarse
  de los documentos.

### 2026-08-11 — Revisión independiente de la auditoría documental (P0+P1)

- **El gate documental no comprobaba la fuente de verdad.** `check_docs_consistency.py`
  medía coherencia entre los documentos y `project-status.yaml`, pero **nunca
  contrastaba el YAML contra Git**. Calibrado con una contradicción inyectada:
  poniendo `main_commit: 1111111…` y `latest_merged_pr: 4242` y propagando la
  mentira a los cinco documentos, el gate contestaba *«DOCUMENTACION
  COHERENTE»* — describía con toda consistencia un repositorio inexistente.
  Se añade el **punto 0**: `main_commit` y `latest_merged_pr` se verifican
  contra `origin/main`. Si `main` no se puede resolver, el gate se pone **rojo**
  en vez de degradarse a verde en silencio (`S9_DOCS_SKIP_GIT=1` para asumirlo
  explícitamente).
- **El propio YAML entregado estaba desfasado y el gate lo daba por bueno:**
  declaraba `28320bd`/#157 con `origin/main` en `e9c66dc`/#158. Corregido, y
  ahora esa clase de desfase enrojece.
- `RK-16` pasa a **CERRADO**: `on.push.branches` es `['**']` desde el PR #160
  (`e21f766`). La documentación aún lo describía como abierto y «pendiente de
  merge en `chore/ci-test-branches-y-node`». Corregido en el registro de
  riesgos, en `docs/60` y en el README. Verificado leyendo `ci.yml`, no un documento.
- Se registran el **carril A** (Graph UX V2, PR #158) y el cambio de CI como
  programas cerrados. Los recuentos de casos de docs/61 (65/50/21) se
  **verificaron por colección real**, no por lectura de la prosa: `def test_`
  daba 27/20 porque no expande `parametrize`, y un grep de `test(` daba 55 en
  el fichero JS porque contaba llamadas a `.test()` de expresiones regulares.
- `RK-15` pasa a **CERRADO**: `Authz integration (Neo4j efímero)` **sí** es hoy
  check requerido. Leído de la protección de rama con `gh api`, no de un documento.
- **Nuevo `RK-20`**: se distingue por escrito entre *correr* y *exigirse*. En
  `main` corren **14** jobs pero solo **11** bloquean un merge; quedan fuera la
  especificación JS del grafo y los **dos meta-gates del carril L**. Un gate que
  no se exige no es un gate, es un informe — y resulta especialmente delicado
  cuando lo que ese gate vigila es, justamente, que los gates puedan ponerse rojos.
- El recuento de tests de `development` se marca `stale` + `remeasure_pending`
  en vez de sustituirse por una cifra nueva: la única medida disponible se
  tomó en un árbol de trabajo compartido y contaminado por ficheros sin
  versionar de otros carriles. Un número medido en un árbol sucio no es un dato.

### 2026-08-09 — Auditoría documental y sincronización de estado

- `docs/project-status.yaml`: `main_commit` y `latest_merged_pr` corregidos
  (`fb4a6fe`/#144 → `28320bd`/#157), que llevaban tres días desfasados y
  arrastraban al README y al ROADMAP.
- Se introduce una **convención de procedencia** en el bloque `production`:
  `VERIFIED` (leído en el destino, con fecha) frente a `PENDING_VERIFICATION`
  (conocido antes, no releído). El estado del healthcheck pasa a
  `PENDING_VERIFICATION`: la lectura del 2026-08-06 17:02Z (UNHEALTHY) y la de
  las 19:06Z (recuperado tras el backup manual) describían antes y después de
  la copia, no una contradicción — pero **nadie ha vuelto a mirarlo desde
  entonces**, y eso es lo que ahora consta.
- El recuento de tests de `main` deja de ser un número suelto: `7284` recogidos
  / `7061` passed / `219` skipped, **con commit, fecha y entorno**, y con la
  advertencia de que la cifra de CI difiere porque allí sí hay navegador y
  Neo4j.
- `ROADMAP.md`: **M5b dejaba de estar «sin trabajo iniciado»** — estaba cerrado
  desde hacía días (PRs #147, #150-#153). M6 se reetiqueta como lo que es:
  housekeeping **operativo** con aprobación explícita del operador.
- `viewer/README.md`: corregida una afirmación **invertida en materia de
  seguridad** — decía que la visibilidad por personaje «aún no se aplica en las
  consultas del visor» cuando se aplica desde M5b/M5c.
- **Nuevo** [`docs/53-recuperacion-y-credenciales-2026-08.md`](docs/53-recuperacion-y-credenciales-2026-08.md):
  rotación de la credencial de Neo4j y restore real de VM105 desde `vzdump`
  (ambos del 2026-08-08), con su alcance exacto y sus límites — y con la
  distinción explícita entre los **8,2 min de la fase de restore** y el **RTO
  hasta servicio, que sigue sin medir**.
- Corregido en seis documentos el error de llamar **off-host** a la copia en
  `yggdrasil`: `yggdrasil` es el hipervisor que ejecuta VM105, así que la copia
  vive en el mismo chasis. El P0 de replicación fuera del chasis sigue abierto
  (`RK-14`).
- Corregida la confusión entre **backup** y **restore verificado**: el «restore
  real» de julio era el del *dump de Neo4j* en instancia aislada, no la
  recuperación de la máquina.
- `docs/coordination/**` marcado **HISTÓRICO** (programa RC6+, ramas
  inexistentes, RC6 nunca creada), con aviso de que sus «Carriles A/B/R» no son
  los carriles A-E de agosto. `dependabot-analysis.md` marcado **SUPERSEDED**:
  su premisa («no existe `.github/dependabot.yml`») dejó de ser cierta.
- `risk-register.md`: RK-05 **cerrado** con evidencia (el default ya es
  `127.0.0.1`), y añadidos RK-14 a RK-18 para los riesgos abiertos que estaban
  descritos de varias formas en varios sitios o directamente sin registrar.
- `.env.example`: sustituidas las IP internas por marcadores. El repositorio es
  público y una IP privada publica gratis la topología de la red.
- `docs/archivados/02-current-state.md` deja de anunciarse como «documento
  canónico de estado» y de afirmar que el commit desplegado «= `main`».
- Enlaces internos rotos reparados en `viewer/README.md`,
  `docs/archivados/02-current-state.md` y `docs/archivados/INDEX.md`.
- `scripts/check_docs_consistency.py` ampliado: hasta ahora daba «COHERENTE»
  mientras el README anunciaba un `main` de tres días atrás. Ver la sección
  siguiente.

### 2026-08-06 — Sincronización de documentación de estado (desarrollo vs. producción)
- `docs/project-status.yaml` reestructurado en tres bloques explícitos:
  `development` (estado de `main`), `production` (último estado verificado
  por SSH en VM105) y `next_release` (candidato V3 y qué lo bloquea). El
  fichero anterior mezclaba ambos y describía una fotografía de RC5.1 ya
  desactualizada frente a `main`.
- README.md, ROADMAP.md y CHANGELOG.md actualizados para reflejar el cierre
  del programa multi-partida M0/M2/M3/M4/M5a (PRs #138, #140-#143; M1
  bloqueado por Nextcloud, M5b/M6 pendientes), <!-- consistency:ignore --> que no se había documentado
  fuera del README (PR #139 solo tocó README y la documentación consolidada).
- Corregido enlace roto en este CHANGELOG a `docs/02-current-state.md`
  (la ruta real es `docs/archivados/02-current-state.md`).
- Ningún dato de producción (contadores de Neo4j, fecha de despliegue) se
  ha vuelto a verificar por SSH en esta pasada; quedan marcados como
  pendientes de reconfirmar en `docs/project-status.yaml`.

### 2026-08-05 — Programa multi-partida: contratos, resolutor, writer y visor (PRs #138, #140–#143)
- **PR #138 — M0:** `partida_id` incorporado a los contratos de la tubería
  (`v3-contracts-frozen-1.0.0-m0`).
- **PR #140 — M2:** resolutor ciego entre partidas (Invariante 1):
  ninguna partida puede leer o inferir contenido de otra durante la
  resolución de entidades.
- **PR #141 — M3:** writer con ámbito estampado y error duro ante cruces
  de partida (Invariante 2).
- **PR #142 — M4:** divergencias locales del lore vía `local_override_of`,
  no destructivo sobre el lore común.
- **PR #143 (+ #144 fix):** M5a — selector de partida y aislamiento de
  acceso estampado por workspace efectivo en el visor. PR #144 corrige un
  fallo de CI introducido por #143 (import perezoso en `app.authz`).
- M1 (mapeo de ingesta Nextcloud→ámbito) sigue bloqueado a que Nextcloud
  vuelva a estar disponible. M5b y M6 pendientes. <!-- consistency:ignore -->

  Un CHANGELOG registra lo que era cierto en su fecha, así que estas líneas se
  conservan tal cual y quedan exentas del gate de coherencia (M5b se cerró
  después, el 2026-08-09). Lo que ya no es cierto se corrige en la entrada
  nueva, no reescribiendo el pasado.

### 2026-08-05 — Cierre de Puertas 4 y 6, medición del acuerdo determinista∧NVIDIA (PRs #124–#136)
- **Puerta 4 — cobertura del extractor (PRs #124-#130):** veredicto
  **PARCIAL**. Cobertura E2E de desarrollo 0.607 (umbral ≥0.60, conforme);
  recall de auto-aprobación SIMPLE 0.10 (umbral ≥0.70, no conforme); carril
  semántico NVIDIA en sombra insuficiente (0.357); invariantes de precisión
  intactos en todo el programa. Carril OCR validado con Tesseract 5.5.0 real
  en VM105. Ver `docs/v3/42-gate4-cierre-programa.md`.
- **Puerta 6 — factividad composicional (PRs #131-#133, #136):** veredicto
  **CONFORME CON RESERVAS**, ratificado por el operador el 2026-08-05.
  Generalización compositiva 0.381 (B0) → 0.811 (B2, corpus ampliado a 53
  casos); el rework de B2 reconectó el operador de discurso reportado al
  extractor real de producción, corrigiendo una desconexión detectada por
  revisión. Ver `docs/v3/46-gate6-cierre-programa.md`.
- **Medición del acuerdo determinista∧NVIDIA (PRs #134-#135):** acuerdo
  activo 27/27 y 1.000 sobre un corpus de evaluación ampliado. El operador
  ratificó un piloto controlado (auditoría humana 100%), sin reducir
  todavía la revisión; la reducción queda gateada al despliegue de V3 y a
  la primera ingesta autorizada. Ver `docs/v3/47-acuerdo-det-nvidia.md` y
  `docs/v3/48-acuerdo-eval2.md`.

### 2026-07-30 — Cierre de los lotes técnicos V3 (PRs #111–#114)
- **PR #111 — Lote 1:** endurecimiento del extractor y del motor sin cambio de
  política: ordenación estable de candidatos, frontera tipada de metadata,
  selección local explícita, caches acotadas y tratamiento fail-closed de
  negaciones desconocidas o con múltiples afirmaciones activas.
- **PR #112 — Lote 3:** validación del reconciliador con distintos
  `PYTHONHASHSEED`, prueba de escala y aceptación medida; D-R conserva los 8
  claims correctos de C1 que D reducía a 0.
- **PR #113 — Lotes 2 y 2b:** política graduada de negaciones y temporalidad
  implementada en el motor tras flags por defecto **OFF**, con métricas para su
  evaluación antes de activarla.
- **PR #114 — Lote 6:** replicabilidad reforzada para secretos, despliegue
  genérico, rollback conjunto de aplicación y datos, restore periódico y
  creación de workspaces.

### 2026-07-29 — Rediseño integral Knowledge V3 (PR #110)
- Merge de `knowledge_v3` en `main` con contratos congelados bajo
  `v3-contracts-frozen-1.0.0`, extractor determinista y semántico,
  reconciliador, motor local, ledger temporal y writer con gate de operador.
- Integradas la evidencia multimodal (`OCR_TEXT`, `TRANSCRIBED_TEXT`,
  `VISUAL_INFERRED`) y la transcripción manuscrita. V3 queda en el repositorio,
  no desplegada en producción.

### 2026-07-18 — Despliegue por candidatas RC1–RC5.1 y corrección de la regresión forward-ref
- **RC5.1** (`deploy-v0.3.0-rc5.1`, `47bc314`) — **DESPLEGADA y activa en producción.**
  Corrige la regresión de despliegue "forward-ref": desplegar hacia un tag/commit
  aún no materializado en el object store local fallaba porque
  `git rev-parse <ref>` imprime su argumento aunque falle y el fallback lo
  duplicaba (`invalid refspec`). Nueva función central `resolve_release_commit`
  (un único SHA a stdout, diagnósticos a stderr, rechazo de refs ambiguas /
  multilínea / con `-` inicial, fetch específico y seguro). Prueba E2E con
  repositorios git reales. Ver [docs/51](docs/archivados/51-deploy-forward-ref-regression.md).
- **RC5** (`deploy-v0.3.0-rc5`, `bcc3a59`) — candidata **NO desplegada**: el cutover
  se abortó antes de activarse; se conserva para auditoría.
- **RC4** (`deploy-v0.3.0-rc4`, `91bdc51`) — login con **submit explícito** (evita el
  autoenvío del navegador y el autofill del gestor) y garantía de **persistencia de
  la contraseña**. Fue producción hasta RC5.1; hoy es la release *previous*/rollback.
- **RC3** (`deploy-v0.3.0-rc3`, `3aae397`) — prevención de auto-submit del login y
  forzado de cambio de contraseña.
- **RC2** (`deploy-v0.3.0-rc2`, `f8b6153`) — continuidad de estado: preserva bases
  legacy y activa releases correctamente.
- **RC1** (`deploy-v0.3.0-rc1`, `d9af2d3`) — instalación/despliegue reproducible;
  candidata **rechazada** (la retención la eliminó; reconstruible desde su tag).
- **Retención fail-closed** y **verify-deployment fail-closed** (pass/fail/warn/skip;
  protege current/previous/tags/proceso vivo; sin falsos verdes).
- **Healthcheck** operativo (solo lectura) con **timer horario** (`OnCalendar=hourly`,
  `Persistent=true`, `RandomizedDelaySec=5m`); retirada del timer de 5 minutos.
- **Login único del visor**; **Basic Auth retirada** del proxy nginx (VM104).
- El estado real está en [docs/02-current-state.md](docs/archivados/02-current-state.md) y
  [docs/project-status.yaml](docs/project-status.yaml).

### 2026-07-15 — Autenticación del visor + endurecimiento de seguridad (docs/44)
- Autenticación opt-in por sesiones server-side con usuarios locales SQLite: login/logout/cuenta/cambio de contraseña, roles `admin`/`reviewer`/`viewer`, administración de usuarios, auditoría append-only, CLI y migraciones. Con `S9K_AUTH_ENABLED=false` el visor se comporta igual que antes.
- Hashing Argon2id (o bcrypt); cookies `HttpOnly`/`Secure`/`SameSite=Lax`; sesiones almacenadas solo como SHA-256; bloqueo por intentos fallidos.
- **Endurecimiento (Fase A4):**
  - Todas las APIs (`/api/status|workspaces|entity-types|search|entity|graph|jobs`) exigen sesión viewer+ → **401/403 JSON**; HTML anónimo → 302 /login. Dependencias centrales `get_current_api_user`/`require_api_authenticated_user`/`require_api_role`.
  - CSRF de login real: token firmado HMAC-SHA256, temporal y *double-submit* ligado al navegador.
  - Validación de arranque *fail-closed*: aborta si el secreto CSRF es vacío/por defecto/corto/baja entropía o si el backend de contraseñas no es Argon2id/bcrypt (PBKDF2-dev prohibido en producción).
  - Middleware fail-closed (sin `except: pass`): fallo de auth → usuario anónimo, acceso denegado, log sanitizado.
  - `/docs`, `/redoc`, `/openapi.json` no registrados por defecto; con `S9K_AUTH_EXPOSE_DOCS=true` solo admin.
  - Corregido el 500 en login con usuario inexistente (parámetro de auditoría inválido).
- **78 tests de auth** en 3 archivos (`test_auth_core` 18, `test_auth_routes` 22, `test_auth_hardening` 38). Suite viewer: 114 passed. Suite combinada: 438 passed. Sin escritura en Neo4j ni en el writer de ingesta.
- **Dictamen: Autenticación del visor PREPARADA (PR limpio, pendiente de merge).**

### 2026-07-15 — Fase B1: orquestador de procesamiento externo por rafaga (docs/45)
- Nuevo paquete `data-engine/app/external_processing/` (capabilities, errors, models, manifests, planner, chunking, provider, registry, cache, dispatcher, result_validator, result_merger) + providers/mock + providers/nvidia.
- `BurstPlanner`: seleccion automatica local/hybrid/burst por umbrales configurables con `reason_codes`.
- `BurstDispatcher`: concurrencia limitada (semaforo), reintentos con backoff exponencial, circuit breaker, cancelacion limpia, rate limiting.
- `MockExternalProcessingProvider`: 10 escenarios deterministicos (success, timeout, rate_limit, retry_once, auth_error, etc.) para todos los tipos de tarea.
- `NvidiaProcessingProvider`: capacidades verificadas declaradas (EXTRACT_TEXT_ENTITIES, GENERATE_EMBEDDINGS, RERANK, REVIEW_CANDIDATES); B2 pendiente para endpoints ASR/OCR/imagen.
- Validacion de respuestas externas: schema, hash, rangos, idioma, secretos, rutas privadas.
- Merger de resultados: audio por timestamps (elimina overlap, detecta gaps), OCR por paginas, texto por offsets.
- Cache idempotente SHA256 (`state/external_processing_cache/`).
- CLI `data-engine/app/cli/burst.py`: plan/dispatch/status/retry/cancel/validate/merge/report.
- Migracion SQLite idempotente: 11 columnas nuevas para jobs de procesamiento externo (batch_id, processing_mode, provider, model, task_type, chunk_json, progress, attempt_burst, next_retry_at, latency_ms, error_code).
- **88 tests** en `tests/test_external_processing/` en 10 archivos, cubriendo mas de 30 escenarios y requisitos de aceptacion (planner, chunking, cache, dispatcher, state machine, validacion, merger, seguridad, migracion, E2E mock, regresion de aislamiento).
- E2E mock (test_e2e_mock.py): 2 audios + 3 imagenes + 10 paginas PDF → plan→dispatch→validate→merge → READY_FOR_LOCAL_PIPELINE. Neo4j: 0 llamadas. writer: no invocado. ingest_approved: no importado por el pipeline. approved_payload: no generado.
- fix: test_e2e_flujo_completo usa snapshot de sys.modules anterior al pipeline para detectar solo contaminacion de Fase B1 (no contaminacion de orden de tests de la suite). Test de regresion test_e2e_ingest_approved_no_importado_por_pipeline anadido.
- **Dictamen Fase B1: LISTO. B2 (proveedores ASR/OCR/imagen reales) y B3 (produccion) pendientes.**

### 2026-07-15 — IA externa NVIDIA: revisión multi-modelo y calibración en modo sombra (docs/42)
- Nuevo paquete `data-engine/app/external_ai/` (base, models, errors, registry, openai_compatible, nvidia_nim, prompts, response_parser, consensus, calibration, cache, security) + CLI `cli/external_ai.py` (health/review/adjudicate/calibrate/report).
- Dos revisores independientes NVIDIA NIM + adjudicador → consenso (STRONG/PARTIAL/CONFLICT/INVALID/HUMAN). **shadow_mode=true** siempre; sin AUTO_APPROVED; nada escribe en Neo4j.
- Seguridad: API key solo por entorno/EnvironmentFile 0600, detector de secretos (incl. nvapi-) que bloquea el envío, sanitización reutilizada, caché idempotente (fuera de Git).
- **22 tests** (mock, sin llamadas reales) incl. test que falla si toca ingesta/Neo4j. E2E mockeado: 7 STRONG / 1 CONFLICT / 1 INVALID; Neo4j intacto 199/140.
- **Validación real ejecutada (§17, 2026-07-15):** 2 modelos de familias distintas (nvidia/nemotron-mini-4b + upstage/solar-10.7b) sobre 3 candidatos → consenso 2 STRONG/1 PARTIAL/0 conflictos, JSON válido (0 errores), caché confirmada, Neo4j intacto 199/140, sin secretos. Fase B (procesamiento externo por lotes) diseñada, no implementada.
- **Dictamen: Calibración multi-IA IMPLEMENTADA EN MODO SOMBRA; procesamiento externo de gran volumen DISEÑADO, NO IMPLEMENTADO.**

### 2026-07-15 — Benchmark de transcripción YouTube vs faster-whisper (docs/40)
- Comparación real por muestra (vídeo L5A QS2Rnw-dYlk, ventana 10 min): faster-whisper medium (RTF 0.56) vs YouTube auto-ASR.
- Acuerdo token-level 0.887; normalizador de glosario 0 sustituciones (whisper medium acierta nombres L5A). Sin subtítulos manuales ni referencia humana → WER verdadero no medible (comparación indirecta).
- Detector de segmentos conflictivos: 91% AUTO_ACCEPT / 7% REVIEW / 2% REJECT (cumple objetivo >90%/<10%). Los conflictos concentran errores de nombre propio (p. ej. Kakita Riko → "caquita rico").
- **Dictamen: Transcripción de vídeo APTA CON REVISIÓN DE SEGMENTOS CONFLICTIVOS.** Para la primera ingesta se recomienda NO usar una transcripción de vídeo nueva, sino una fuente pequeña ya validada. Sin ingesta. Detalle: docs/40.

### 2026-07-14 — Prioridad 2.1: revisión humana total + benchmark confirmatorio (7 fuentes)

#### Seguridad de ingesta (impuesta por código)
- **auto_decider**: `S9K_REVIEW_POLICY={normal,full_human_review}`. Bajo `full_human_review` TODO candidato → needs_review (`full_human_review_policy`); 0 autoaprobados; payload automático vacío. Política desconocida → error.
- **ingest_approved**: bajo `full_human_review`, rechaza (sin escribir) payloads sin procedencia de revisión humana (`review_status=approved`, `reviewed_by`, `reviewed_at`, `review_action`, `evidence`, `source_id`).
- **review_manual.py**: CLI mínima approve/reject/edit/use-existing con log append-only y `approved_payload.reviewed.json`; nunca toca Neo4j.
- 15 tests (`test_full_human_review.py`) + E2E: 17 candidatos → 0 autoaprobados; payload con auto_approved rechazado.

#### Benchmark confirmatorio (run `20260714-151119`, 7 fuentes, 49 OK / 0 INVALID / 0 FAIL)
- Hybrid entidades: **P 0.878 · R 0.823 · F1 0.846** (pasa los 3 umbrales); llm también los pasa. Relaciones F1 0.163 (<0.60).
- Fuentes nuevas: narrativo F1e 1.000, manual F1e 0.889. Reproducibilidad varianza 0.0. Neo4j intacto 199/140. 304 tests.
- **Dictamen: Prioridad 2.1 COMPLETADA — PREPARADA PARA INGESTA CONTROLADA CON REVISIÓN TOTAL. Primera ingesta: PREPARADA, NO EJECUTADA.** Detalle: docs/37.

### 2026-07-14 — Prioridad 2.1: Mejora de calidad del extractor

#### Mejoras (todas con tests; sin tocar ground truth ni umbrales)
- **auto_decider**: quality gate — relaciones **nunca autoaprobadas** (motivo `relation_autoapproval_disabled_quality_gate`) hasta abrir `S9K_ALLOW_RELATION_AUTOAPPROVAL`.
- **llm_extractor**: prompt de relaciones con taxonomía origen→destino, few-shot y regla apellido→clan.
- **relation_normalizer**: resuelve extremos por alias del source + glosario y corrige dirección.
- **workspace_aliases** + `config/aliases/leyenda.json`: glosario de alias por workspace (aislado, reviewed).
- **hybrid_filter**: filtro de unión (reglas A/B/C) que elimina FP solo-heurísticos y registra motivos.
- **corpus**: +2 fuentes (narrativo, manual), GT pase 3; `corpus-manifest-v2.json` (7 fuentes).

#### Resultados (run `20260714-121026`, mismas 5 fuentes que el baseline)
- Hybrid F1 entidades 0.728 → **0.806**; P 0.634 → **0.851**; R 0.856 → 0.775 → **pasa los 3 umbrales de entidad**.
- LLM F1 entidades 0.718 → 0.741; F1 relaciones 0.040 → 0.089.
- Relaciones aún < umbral (F1 0.089). Autoaprobación: **0 relaciones autoaprobadas** (gate E2E), entidades P 0.80.
- Reproducibilidad varianza F1 = 0.0. Neo4j intacto 199/140. Suite: 289 tests.
- **Dictamen: Prioridad 2.1 PARCIAL — MEJORA DEMOSTRADA. Primera ingesta: DESBLOQUEADA PARA ENTIDADES CON REVISIÓN HUMANA TOTAL.** Detalle: docs/36.

### 2026-07-14 — Prioridad 2: Benchmark real ejecutado en VM105 (métricas válidas)

#### Fallos demostrados por el benchmark y corregidos
- **`data_review.py` (`cmd_extract`)**: el subcomando aislado `extract` ignoraba `--extractor` y ejecutaba siempre el heurístico (el LLM nunca se invocaba). Ahora delega en `pipeline._run_extract_step` para llm/hybrid. Regresión: `test_extract_dispatch.py`.
- **`benchmark_comparator.py`**: leía `approved_payload.json` (nunca producido por el benchmark aislado) → métricas 0.0 en los tres modos. Ahora lee `candidates.json` vía `_load_candidates`. Regresión en `test_benchmark_runner.py`.

#### Resultados (run `20260714-094125`, 35 OK / 0 INVALID / 0 FAIL)
- Configuración final del benchmark: **temperature=0, seed=42, modelo=qwen2.5:7b**.
- F1 entidades agregado: heuristic 0.689 · llm 0.718 · hybrid 0.728. Precisión llm 0.810; recall hybrid 0.856.
- Relaciones F1 ≈ 0 (limitación de prompt/modelo). Autoaprobación P=0.85 (< 0.95).
- Reproducibilidad: varianza F1 entidades = 0.0 (temp=0, seed=42). Neo4j intacto (199 nodos / 140 rels).
- Suite verde en esa fecha. Detalle completo en `docs/34`. (El recuento vigente de la suite está en [docs/project-status.yaml](docs/project-status.yaml).)
- **Dictamen: Prioridad 2 PARCIAL — REQUIERE CORRECCIONES. Primera ingesta controlada: BLOQUEADA.**

### 2026-07-14 — Prioridad 2 FASE 2: Correcciones de benchmark + ground truth pase 2

#### Correcciones críticas del benchmark
- **`extractor_benchmark.py`**: modo aislado — usa `segments.classified.json` pre-clasificados, llama `extract` (no `run`), valida con `candidates.json` real, registra `source["file"]`, INVALID_RUN para runs vacíos, seed=42 para LLM
- **`llm_extractor.py`**: lee temperatura/URL/modelo de `settings.yaml`; temperatura=0 (antes 0.1 hardcoded); seed=42 vía `S9K_LLM_SEED`; **parsing de relaciones LLM implementado** (types permitidos + validación)
- **`pipeline.py`**: deduplicación hybrid corregida para relaciones — key `from|type|to` en lugar de `"|type"` incorrecto
- **Creados**: `tests/fixtures/benchmark/<source_id>/segments.classified.json` para las 5 fuentes (2+2+2+1+2 segmentos, todos `should_extract=true`)
- **Ground truth pase 2**: las 5 fuentes revisadas y congeladas (`annotation_pass=2`, `reviewed=true`)
- **docs/34**: actualizado con correcciones aplicadas, tabla de resultados pendiente de ejecución en VM105

### 2026-07-14 — Prioridad 2 PARCIAL: Benchmark del extractor (infraestructura + análisis)

#### Tests y calidad
- 15 tests de regresión del extractor añadidos en `test_extractor_regression.py`
- 8 tests del benchmark runner en `test_benchmark_runner.py`
- CI: 243 tests totales, 4 jobs verdes
- **Fix extractor:** `soy/eres/somos/sois` añadidos a STOPWORDS_ES; strip de prefijo verbal en nombres compuestos ("Soy X" → "X")

#### Benchmark
- Corpus de 5 fuentes anotado: 56 entidades esperadas, 23 negativas (ground truth pase 1)
- `extractor_benchmark.py`: runner reproducible, heuristic×1 + llm×3 + hybrid×3 por fuente
- `benchmark_comparator.py`: comparador Precisión/Recall/F1 contra ground truth
- 35/35 runs ejecutados en VM105 (clon temporal, producción intacta)
- **Hallazgo:** fixtures markdown no generan segmentos → métricas F1 pendientes (ver docs/34 §7.1)
- Bug corregido en comparador: `negative_entities` como lista de dicts soportada

#### Documentación
- docs/33: plan de evaluación del extractor (ya en main desde PR #10)
- docs/34: resultados del benchmark (dictamen: PARCIAL — REQUIERE CORRECCIONES)
- Ollama 0.31.1 verificado: qwen2.5:7b, seed soportado. **Hallazgo histórico:** el extractor usaba temperatura 0.1 hardcoded (discrepancia con settings.yaml=0); **corregido antes de la ejecución final** del benchmark (config final: temperature=0, seed=42, modelo=qwen2.5:7b)

### 2026-07-13 — Prioridad 1: Backup real, restore aislado, rollback laboratorio

#### Operaciones
- Primer backup real de Neo4j producción ejecutado (parada ~25 s, 132 KB, SHA256 c3179c01...)
- Restore en instancia aislada verificado: 199 nodos, 140 relaciones, 14 labels, 2 índices — idéntico a producción
- Rollback por `source_id` validado en laboratorio con datos sintéticos (patrón Cypher transaccional)
- Copia externa a yggdrasil completada y verificada: 2026-07-14 01:07 UTC, SHA256 coincide en destino

#### Limpieza de repositorio
- PRs obsoletos #4, #7, #8 cerrados con justificación documentada
- Ramas remotas huérfanas eliminadas: audit/test-failures-20260713, feat/neo4j-backup-restore-foundation, docs/session-final-report-20260713, docs/coordinator-final-report-20260713, docs/phase-0a-0b-baseline-20260713
- Repositorio: 0 PRs abiertos, ramas activas solo con trabajo en curso

#### Documentación
- docs/32: informe completo de validación de Prioridad 1
- docs/29, docs/26, docs/02, ROADMAP, CHANGELOG, INDEX, dossier: actualizados
- docs/33: plan de evaluación para Prioridad 2

### 2026-07-13 — Tests y CI (commit cef9233)

#### Fixed

- Eliminar `data-engine/app/__init__.py` vacío: registraba el directorio
  como paquete Python `app`, colisionando con `viewer/app` en corrida combinada y
  causando 5 errores de colección.
- Eliminar `data-engine/app/tests/__init__.py` y `viewer/tests/__init__.py` vacíos:
  causaban `ImportPathMismatchError` en corrida combinada.
- Reescribir `conftest.py` raíz con rutas relativas (Path(__file__).parent).
- Suite combinada: 220 passed, 0 errores de colección, 0 fallidos.
- `export_silverbullet.py`: ruta sys.path relativa (antes hardcoded /opt/).

#### Added

- `.github/workflows/ci.yml`: 4 jobs (data-engine, viewer, combined, check-imports), Python 3.13.
- `docs/31-test-remediation-and-ci-report.md`: informe de remediación y CI.

### 2026-07-13 — Auditoría inicial (historial)

#### Auditoría inicial de VM105 (estado antes de correcciones)
- Estado verificado en commit `1fd94b85` (v0.2.5b): 196 recopilados, 155 aprobados, 41 fallidos.
- Los 41 fallos eran deuda técnica funcional (semántica del grafo, jobs, multimedia, visor).
- Guard de ingesta 16/16 confirmado en estado histórico.
- Baseline: [`docs/24-vm105-baseline-and-verification.md`](docs/archivados/24-vm105-baseline-and-verification.md).
- Estado corregido posteriormente a 220/220 (commit cef9233).

### Fixed — 2026-07-13 (rama fix/tests-imports-cache-and-ci)

- Eliminar `data-engine/app/__init__.py` vacío: el archivo registraba el directorio
  como paquete Python `app`, colisionando con `viewer/app` en corrida combinada y
  causando 5 errores de colección.
- Eliminar `data-engine/app/tests/__init__.py` y `viewer/tests/__init__.py` vacíos:
  causaban `ImportPathMismatchError` en corrida combinada.
- Reescribir `conftest.py` raíz con documentación clara de por qué se insertan
  `data-engine/app` y `viewer/` en sys.path.
- Suite combinada: 220 passed, 0 errores de colección, 0 fallidos.

### Added — 2026-07-13 (rama fix/tests-imports-cache-and-ci)

- `.github/workflows/ci.yml`: 4 jobs (data-engine, viewer, combined, check-imports).
  Sin dependencias externas (no Neo4j real, no Ollama, no Nextcloud).
- `docs/31-test-remediation-and-ci-report.md`: informe de remediación y CI.

### Documentación — 2026-07-13

- Auditoría completa de VM105 y cierre documental de fases 0A y 0B.
- Commit auditado: `1fd94b85` (v0.2.5b). Estado verificado: Neo4j 199 nodos / 140 relaciones,
  visor HTTP 200 en todos los endpoints, 2 servicios systemd activos, guard de ingesta confirmado.
- Tests verificados: 196 recopilados, 155 aprobados, 41 fallidos (deuda técnica funcional — semántica del grafo, jobs, multimedia, visor; guard de ingesta 16/16 confirmado).
- Nuevo informe de baseline: [`docs/24-vm105-baseline-and-verification.md`](docs/archivados/24-vm105-baseline-and-verification.md).
- Corrección: `docs/06-viewer-panel.md` — visor marcado como en producción (no "no implementado").
- Corrección: `docs/05-data-engine.md` — cifra de tests actualizada (196/155 vs histórico 8/8).

### Added (inicial)
- Repositorio Git inicial con instantánea del proyecto (`data-engine/` + `docs/`).
- Documentación base: README, ROADMAP, `docs/00-vision` … `docs/10-clone-on-windows`.
- `.gitignore` y `.env.example` seguros.

## data-engine — 2026-07-10/11

### Added
- Schema RPG **1.5.0**: nuevos tipos de nodo (Creature, NonHuman, Spirit, Demon,
  Beast, Region, Group, Artifact, Encounter, Combat, Session, Transcript, Image);
  113 tipos de relación con etiquetas en español; vocabularios controlados
  (attitude, status, danger_level, visibility, knowledge_layer, review_status,
  known_by_scope, knowledge_quality); ~200 normalizadores ES/inglés.
- Campos opcionales de entidad/relación: metadatos temporales y de sesión,
  imágenes, estado de revisión y **capa de conocimiento por personaje**.
- Prompt RPG **1.4.0**: perfil transcript ampliado (criaturas/espíritus/combate),
  `SYSTEM_PROMPT_BOOK`, sección "CONOCIMIENTO DE PERSONAJES".
- Writer Neo4j: SET dinámico de campos opcionales, nodo `Session` + `APPEARS_IN`,
  sellado temporal, detección de imágenes locales, validación semántica
  (ok/dubious/invalid), `review_status`, auditoría `[AUDIT]` ampliada, nuevas CLI
  (`--source-kind`, `--session-*`, `--visibility`, `--knowledge-layer`, `--source-url/title/author`).
- Cola de trabajos `app/jobs/job_store.py` (SQLite `state/jobs.db`).
- Acceso `app/access/access_store.py` (usuario-personaje + permisos + audit log).
- Documentos de diseño: VISOR, EXTERNAL_SOURCES, KNOWLEDGE_VISIBILITY,
  USERS_CHARACTERS, RPG_GRAPH_MODEL_UPDATE, INFORME_ENTREGA.

### Verified
- `py_compile` OK en todos los módulos; `pytest` 8/8.
- Prueba end-to-end (source_id `test_creatures_locations_timeline`, perfil
  transcript, sesión 4): estado `complete`; Session + APPEARS_IN + relaciones de
  conocimiento (HAS_FOUGHT, HAS_TALKED_TO, HAS_HEARD_ABOUT, DISCOVERED) escritas
  con trazabilidad completa.

### Notes
- Recall de relaciones limitado por el modelo qwen2.5:7b (volátil entre
  ejecuciones); no es un fallo del pipeline.
- Nodos históricos (pp.1-40) sin source_id/kind previos a los fixes: no tocados.
