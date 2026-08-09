# 61 — Manifiesto de release, comprobador de configuración y runbook de rollback

**Estado**: preparación del gate de despliegue. **No se ha desplegado nada.**
Todo lo de este documento se ha ejecutado en local; no se ha tocado VM105, ni
por SSH, ni contra su Neo4j, ni contra sus copias de seguridad.

**Rama**: `ops/v3-release-readiness` (desde `main` = `28320bd`).

Este documento responde a una pregunta que hasta ahora no tenía respuesta
escrita: **¿qué exactamente desplegaríamos?**

---

## 0. El kit, de un vistazo

| Fichero | Qué hace | Se ejecuta |
|---|---|---|
| `deploy/release/spec.py` | Fuente única de verdad: variables, ficheros, secretos, directorios, versiones, componentes, migraciones, métricas | (importado) |
| `deploy/release/generate_manifest.py` | Genera el manifiesto desde el repositorio | local / CI |
| `deploy/release/RELEASE_MANIFEST.json` | Manifiesto generado y versionado | artefacto |
| `deploy/release/config_check.py` | Comprueba un entorno contra la especificación | local o **host destino** |
| `deploy/release/calibrate_config_check.py` | Demuestra que el comprobador enrojece | local / CI |
| `deploy/release/smoke_lab.py` | Smoke suite in-process con auth activa | local / CI |
| `deploy/tests/test_release_readiness.py` | 37 tests que fijan todo lo anterior | CI |

---

## 1. El manifiesto: qué desplegaríamos

### Cómo se genera

```bash
python3 deploy/release/generate_manifest.py -o deploy/release/RELEASE_MANIFEST.json
python3 deploy/release/generate_manifest.py --format md   # versión legible
```

Nada se escribe a mano. Cada campo se **deriva**:

- commit, rama y `describe` — de `git`;
- versión de la aplicación — del literal `version=` del constructor `FastAPI`
  en `viewer/app/main.py` (leído, no importado: generar el manifiesto no debe
  arrancar la aplicación);
- versión de esquema de `auth.db` — de la constante `SCHEMA_VERSION` en
  `viewer/app/auth/db.py`, que es el mismo número que aplica la migración;
- Python — de las versiones declaradas en `.github/workflows/ci.yml`, porque lo
  único honesto es decir en qué Python se prueba de verdad;
- huellas de dependencias — sha256 de `viewer/requirements.txt` y
  `data-engine/requirements.lock`;
- componentes, migraciones, configuración, servicios y rollback — de `spec.py`.

Si algo no se puede derivar, el generador **falla con código 2**. No emite un
manifiesto parcial: un manifiesto incompleto que parece completo es peor que no
tenerlo.

### Distinción importante

Hay **dos** manifiestos y no son el mismo:

- el de **candidatura** (este): describe lo que un commit *sería* si se
  desplegara. Vive en el repositorio y se revisa antes de decidir.
- el de **release instalada**: lo escribe `create_manifest()` en
  `deploy/scripts/lib.sh` **en el host**, con el `release_id`, el checksum de
  ficheros y el `compatible_rollback_to` reales.

**Defecto corregido en esta rama**: el manifiesto de release instalada
declaraba `"schema_versions": {"auth_db": 1}` fijo, mientras el código va por la
**v3** desde T2. Es decir, toda release instalada mentía sobre su propio
esquema, y `compatible_rollback_to` no podía calcularse a partir de él. Ahora se
lee `SCHEMA_VERSION` del árbol de la release que se está instalando, y si no se
puede leer se declara `"unknown"` en lugar de inventar un número.

### Contenido, resumido

- **Versión**: `0.3.0`, commit `28320bd`, **sin tag de despliegue** — no existe
  ningún `deploy-v3-*` y cortarlo es requisito previo.
- **Componentes**: viewer, viewer-cli, data-engine (presente pero **no
  activado**), deploy-tools, contracts, docs.
- **Esquemas**: `auth.db` = **3**; `jobs.db` = 1; el grafo no lleva número de
  esquema en este proyecto.

### Migraciones NECESARIAS

**`auth_db.v3`** — `ALTER TABLE partida_access ADD COLUMN max_visible_session
INTEGER` y `ADD COLUMN character_id TEXT`. La aplica automáticamente
`app.auth.db.ensure_migrated()` al arrancar el visor, bajo `flock` exclusivo y
tras copiar `<db>.bak.v<versión anterior>`. **Irreversible**: no hay camino de
bajada en el código.

### Migraciones explícitamente NO necesarias

Esta es la mitad del manifiesto que suele faltar, y la que evita sorpresas.

- **`graph.legacy_visibility_m5b`** — **NO APPLY por decisión del operador.** El
  plan `12f7278f` se validó y se descartó: sin `known_by` en los datos legacy no
  hay migración semántica posible, solo una asignación arbitraria. El grafo de
  producción (199 nodos / 140 relaciones) se queda como está. **Consecuencia que
  el manifiesto asume**: el material legacy queda fuera del alcance de partida y
  se comporta según el cierre por defecto (fail-closed) — no como contenido de
  juego reetiquetado. Cualquier release que *exija* ámbito estampado en legacy
  contradice esta decisión y no debe desplegarse. Hay un test que lo impide
  (`test_ninguna_migracion_de_grafo_es_necesaria`).
- **`auth_db.v2`** — no como paso separado: `ensure_migrated()` encadena
  v1→v2→v3. Se declara para que nadie lea el manifiesto y crea que un `auth.db`
  en v1 salta a v3 sin pasar por v2.
- **`jobs_db.v1`** — el esquema no cambia; la base vive fuera del árbol de
  despliegue y se conserva intacta entre releases.

### Fuera de alcance, explícito

No se migra el grafo legacy. No se activa la ingesta real
(`S9K_ALLOW_REAL_INGEST` sin definir). No se reduce la revisión humana. No se
instala el backup automático de `deploy/propuestas/` — sigue siendo una
propuesta.

---

## 2. Comprobador de configuración

```bash
# En el host destino, que es donde tiene sentido completo:
python3 deploy/release/config_check.py \
    --env-file /etc/s9-knowledge/viewer.env \
    --production --check-filesystem --check-units --check-neo4j
```

Códigos de salida: **0** OK · **1** WARNING · **2** ERROR · **3** fallo interno
del propio comprobador.

### Qué comprueba

- **31 variables** de entorno: presencia, y además el *valor* — puerto en rango,
  ruta absoluta, URI bolt reconocible, booleano, valor dentro del conjunto
  permitido.
- **Reglas de producción**: `S9K_GRAPH_PROVIDER=mock` es ERROR (serviría el
  grafo de ejemplo); `S9K_AUTH_ENABLED` distinto de true es ERROR;
  `S9K_SESSION_SECURE`/`HTTPONLY` en false son ERROR.
- **Estado fuera de la release**: `S9K_AUTH_DB_PATH` o `S9K_JOBS_DB` bajo
  `/opt/s9-knowledge/releases/…` o bajo `current` es ERROR — es la lección de
  `docs/50-deploy-state-continuity.md`: ese estado se pierde en el siguiente
  despliegue.
- **Flags que deben estar apagadas**: `S9K_ALLOW_REAL_INGEST`,
  `S9K_ALLOW_RELATION_AUTOAPPROVAL`.
- **Secretos, por RUTA**: existencia y permisos de
  `/etc/s9-knowledge/viewer.env` (máx. 0600),
  `/etc/s9-knowledge/secrets/neo4j_password` (máx. 0640) y de cualquier ruta
  referenciada por una variable `*_FILE`. **El contenido no se lee, no se
  imprime, no se hashea.** De un secreto solo se comprueba, sin revelarlo, que
  no sea un marcador de posición conocido y que tenga al menos 32 caracteres.
- **Directorios y permisos**: los del state root, más el directorio de
  `auth.db` — que el visor **no crea** y sin el cual no arranca.
- **Versiones**: Python (>=3.13,<3.14) y Neo4j (>=5.26,<6.0).
- **Dependencias**: cada línea de `viewer/requirements.txt` instalada **y dentro
  del rango declarado**. Comprobar solo la presencia daba OK a versiones
  anteriores a la exigida.
- **Unidades systemd** declaradas.

### Qué NO puede comprobar sin acceso a la máquina destino

Esto se declara siempre como **WARNING explícito**, nunca como OK. Un
comprobador que calla lo que no sabe es peor que uno que no existe:

1. **Ficheros, secretos, directorios y permisos** — sin `--check-filesystem`
   comprueba cero de ellos, y lo dice en una línea propia.
2. **Versión real de Neo4j** — exige consultar el servidor
   (`CALL dbms.components()`) o la imagen del contenedor.
3. **Unidades systemd** — requiere `systemctl` en el destino.
4. **Que el secreto CSRF del host sea el correcto** — solo puede comprobar
   forma y longitud, nunca corrección.
5. **Propietario real de los ficheros** (`www-data` vs `root`) — se declara en
   la especificación pero no se verifica; requiere resolver uid/gid en el
   destino.
6. **Estado del proxy inverso, DNS, certificados y puertos publicados** — están
   fuera del alcance del repositorio por completo.
7. **Espacio en disco, memoria y frescura de las copias** — eso lo cubre
   `python -m app.cli.health check` en el host, no este comprobador.
8. **Que Neo4j contenga los datos esperados** — el comprobador no consulta
   datos, deliberadamente.

---

## 3. Smoke suite de laboratorio

```bash
python3 deploy/release/smoke_lab.py           # 12/12
python3 deploy/release/smoke_lab.py --json
```

Arranca la aplicación **real** en proceso (FastAPI + `TestClient`) con
autenticación **activa**, `auth.db` efímera migrada por el propio código, un
secreto CSRF generado al vuelo y la fixture multi-partida. Códigos: 0 pasa · 1
falla algún check · 3 no se pudo ni montar el arnés.

| Check | Qué afirma de verdad |
|---|---|
| `app_boots` | la app importa y un anónimo recibe **302 al login**, no 200 |
| `login` | credenciales correctas emiten sesión; **incorrectas no** |
| `viewer_home` | `/` y `/status` responden a un autenticado |
| `graph` | `/graph` y `/api/graph` responden |
| `entities` | `/api/entities` devuelve `items` y `/entities` renderiza |
| `sources` | reviewer 200 / **viewer 403** |
| `jobs` | `/jobs` y `/api/jobs` responden |
| `reviews` | `/review-console` reviewer 200 / **viewer 403**; `/reviews` 404 (ver hallazgo H1) |
| `admin` | admin 200 / **viewer 403** — es un check de denegación |
| `health` | el healthcheck emite un veredicto **explícito** con código en contrato |
| `neo4j_connectivity` | con `mock` se declara **NO VERIFICADO**; no se simula un OK |
| `unauthorized_data_invisible` | **el que importa**, ver abajo |

### El check que convierte esto en algo más que "responde 200"

`unauthorized_data_invisible` comprueba, sobre un grafo con capa juego +
`partida:uno` + `partida:dos` + un nodo legacy sin ámbito:

- un usuario **sin concesión** ve solo la capa juego (`lore_dios_sol`) — ninguna
  entidad de ninguna partida;
- el **material legacy sin ámbito no es visible** — que es exactamente la
  consecuencia esperada de la decisión NO APPLY: al no migrarse, queda mudo, no
  abierto;
- un usuario con acceso a `partida:uno` **no ve `partida:dos`**, y no solo en el
  listado: se comprueba también el **acceso directo por ficha**
  (`/api/entity/partida2_pc_bryn` → 404), porque un filtrado que solo se aplica
  al listado es una fuga con un rodeo de un clic.

### Qué NO es esta suite

No habla con VM105 ni con ningún host remoto. Un 200 aquí no prueba que
systemd, los permisos, el proxy o los datos reales estén bien allí. La
verificación en el destino es `deploy/scripts/verify-deployment.sh` más
`python -m app.cli.health check`.

---

## 4. Runbook de rollback (**escrito, no ejecutado**)

Escenario: se despliega la release **N**, falla, y hay que volver a **N-1**.

### Paso 0 — Decidir que se vuelve

Criterio explícito antes de tocar nada: ¿es un fallo de la release o del
entorno? Si `config_check.py` sale en ERROR en el host, el problema es de
configuración y **el rollback no lo arregla** — arregla la configuración.

### Paso 1 — Congelar

```bash
systemctl stop s9-knowledge-viewer.service
```

### Paso 2 — Copia previa, ANTES de tocar nada

```bash
sqlite3 /var/lib/s9-knowledge/auth/auth.db ".backup /var/lib/s9-knowledge/backups/prerollback-auth.db"
sqlite3 /var/lib/s9-knowledge/jobs/jobs.db ".backup /var/lib/s9-knowledge/backups/prerollback-jobs.db"
```

Un rollback destruye la evidencia de por qué N falló si no se hace esto
primero. También conserva el `auth.db` **ya migrado a v3**, que es el que hace
falta para el paso 5.

### Paso 3 — Restaurar el código

```bash
deploy/scripts/rollback-release.sh    # repunta el symlink `current` a N-1
```

N-1 sigue en disco: `S9K_RELEASES_TO_KEEP=3`. Es un cambio de symlink atómico,
la parte fácil y rápida.

### Paso 4 — Restaurar la configuración

`/etc/s9-knowledge/viewer.env` **no está versionado dentro de la release**. Si N
añadió, renombró o cambió variables, el rollback del código **no las revierte**.
Hay que revertirlas a mano y volver a pasar el comprobador:

```bash
python3 config_check.py --env-file /etc/s9-knowledge/viewer.env \
    --production --check-filesystem --check-units
```

### Paso 5 — La pregunta difícil: ¿y si N aplicó una migración de esquema?

**Si N aplicó `auth_db.v3`, volver a N-1 no devuelve la base a v2.**

Qué significa exactamente:

1. **La migración es de ida.** `ensure_migrated()` solo sube: mira si
   `versión < SCHEMA_VERSION` y aplica lo que falte. No hay `downgrade()`, no
   hay `DROP COLUMN`, y N-1 no sabe que v3 existe.
2. **Volver a N-1 deja una base v3 servida por código v2.** En este caso
   concreto la migración es **aditiva** (dos columnas nuevas en
   `partida_access`), así que el código N-1 sigue leyendo y escribiendo: ignora
   las columnas que no conoce. **Funciona, pero deja de aplicar los topes de
   sesión y el `character_id`**, es decir, se pierde silenciosamente una
   restricción de visibilidad. No es un fallo ruidoso: es una relajación
   silenciosa de permisos, que es peor.
3. **Por eso hay dos rollbacks distintos, y hay que elegir a conciencia:**

   - **Rollback de código, base en v3** (recomendado si la migración fue
     aditiva y sin pérdida): rápido, conserva usuarios, sesiones y concesiones
     creados bajo N. Coste: N-1 no aplica los topes de campaña. **Solo es
     aceptable si el fallo de N no está en la capa de autorización.**
   - **Rollback de código + restauración de `<db>.bak.v2`**: devuelve el
     esquema a v2 de verdad. Coste: **se pierde todo lo escrito en `auth.db`
     desde la migración** — usuarios creados, sesiones abiertas y concesiones
     de partida otorgadas bajo N. Es la única opción si la migración hubiera
     sido destructiva o si el fallo está en la autorización.

4. **Regla general que se deriva de esto**: una migración irreversible convierte
   el rollback en una decisión con pérdida de datos, no en un botón. La ventana
   entre "N arranca y migra" y "N se declara buena" es la ventana en la que esa
   pérdida crece. Cuanto antes se pase la smoke suite tras el arranque, menor es
   la pérdida si hay que volver.
5. **Copia de seguridad automática de la migración**: `migrate()` deja
   `<db>.bak.v<versión anterior>` junto a la base. Es el fichero del que depende
   la segunda opción. **Comprobar que existe antes de confiar en él** — es un
   efecto secundario de la migración, no un backup gestionado.

### Paso 6 — Arrancar y verificar

```bash
systemctl start s9-knowledge-viewer.service
deploy/scripts/verify-deployment.sh --expected-release <N-1>
python3 -m app.cli.health check
# y la smoke suite de laboratorio contra el código de N-1
```

El rollback **no está terminado cuando el servicio arranca**. Está terminado
cuando la verificación pasa. Un visor que arranca y sirve datos incorrectos es
un rollback fallido que parece exitoso.

### Métricas de recuperación — las tres, separadas

Mezclarlas es el error que hace creer que el servicio vuelve en ocho minutos.

| Métrica | Valor | ¿Medido? | Qué cubre |
|---|---|---|---|
| **RPO observado** | **sin garantía** | no | No hay backup automático instalado. La copia más reciente en VM105 es del 2026-07-17, más el checkpoint manual del 2026-08-06. El RPO real se mide hoy **en semanas**. |
| **RTO de restore** | **8,2 min** | **sí** | Duración de la **fase de restauración**. No incluye detección, ni decisión humana, ni arranque, ni verificación. |
| **RTO hasta servicio** | **sin medir** | no | Desde la detección del fallo hasta servir tráfico verificado. Incluye todo lo anterior más los pasos 0–6 de este runbook. **Nadie lo ha cronometrado.** No debe suponerse igual a 8,2 min. |

---

## 5. Calibración obligatoria del comprobador

Un comprobador que siempre sale OK es indistinguible de uno que funciona, salvo
rompiéndolo a propósito. En vez de hacerlo una vez a mano, está automatizado y
se ejecuta en CI:

```bash
python3 deploy/release/calibrate_config_check.py
```

Construye un entorno completo y válido, verifica que sale en **OK**, y luego
retira **cada** variable crítica de una en una comprobando que el veredicto pasa
a **ERROR**. Salida real:

```
== Línea base: entorno completo y válido ==
veredicto: OK

== Retirando cada variable crítica, de una en una ==
  sin S9K_VIEWER_HOST                    -> ERROR   [ROJO OK]
  sin S9K_VIEWER_PORT                    -> ERROR   [ROJO OK]
  sin S9K_GRAPH_PROVIDER                 -> ERROR   [ROJO OK]
  sin S9K_NEO4J_URI                      -> ERROR   [ROJO OK]
  sin S9K_NEO4J_USER                     -> ERROR   [ROJO OK]
  sin S9K_AUTH_DB_PATH                   -> ERROR   [ROJO OK]
  sin S9K_JOBS_DB                        -> ERROR   [ROJO OK]
  sin S9K_AUTH_ENABLED                   -> ERROR   [ROJO OK]
  sin S9K_CSRF_SECRET                    -> ERROR   [ROJO OK]
  sin S9K_SESSION_SECURE                 -> ERROR   [ROJO OK]
  sin S9K_SESSION_HTTPONLY               -> ERROR   [ROJO OK]

== Reglas duras ==
  OK: un solo hallazgo crítico en rojo basta para veredicto ERROR
  OK: un fichero de entorno ilegible sale con código 3 (no 0)
  OK: ningún valor secreto aparece en los mensajes del informe

CALIBRACIÓN CORRECTA: 11 variables críticas enrojecen al retirarlas; el entorno base queda restaurado.
```

Ejemplo concreto de una sola variable retirada y restaurada
(`S9K_CSRF_SECRET`, contra la plantilla versionada, que deliberadamente no trae
valor):

```
$ python3 deploy/release/config_check.py --env-file deploy/config/viewer.env.example --production --quiet
[ERROR  ] env   S9K_CSRF_SECRET   AUSENTE — secreto de firma CSRF; el código NO soporta
                                  S9K_CSRF_SECRET_FILE …; el código caería al valor por
                                  defecto '<redactado>'
…
OK=41  WARNING=4  ERROR=4
VEREDICTO GLOBAL: ERROR
El despliegue NO debe continuar.
$ echo $?
2
```

`S9K_NEO4J_PASSWORD` queda fuera de la calibración a propósito: tiene
alternativa por fichero (`S9K_NEO4J_PASSWORD_FILE`), así que su ausencia con el
fichero presente es una configuración **válida**, no una ausencia.

---

## 6. Huecos en la información disponible hoy

Encontrados al preparar el gate. Ninguno se ha "arreglado" inventando un valor.

**H1 — `/reviews` es inalcanzable con la convención de nombres multi-partida.**
`_reviews_dir()` (`viewer/app/main.py`) valida el workspace contra
`[A-Za-z0-9._-]{1,64}` porque lo usa como componente de ruta bajo
`output/reviews`. El carácter `:` no está permitido, así que con un workspace
`juego:<algo>` la cola de revisión devuelve **404 para todo el mundo**. Es
fail-closed (no hay fuga) y hoy no afecta a producción, cuyo workspace es
`leyenda`. Pero convierte "renombrar el workspace a `juego:*`" en un cambio que
rompe `/reviews` en silencio. La smoke suite fija este comportamiento por
escrito para que el día que cambie se note. *No se ha corregido: `main.py`
pertenece a otro carril.*

**H2 — El manifiesto de release instalada declaraba un esquema falso.**
`auth_db: 1` fijo frente a un código en v3. Corregido en `deploy/scripts/lib.sh`
en esta rama.

**H3 — El entorno de desarrollo no cumple `viewer/requirements.txt`.** El
comprobador, ya con verificación de rangos, detecta en esta máquina `fastapi
0.139.0` (exige `>=0.141.1`), `pytest 8.4.2` (exige `>=9.1.1`) y `argon2-cffi
23.1.0` (exige `>=25.1.0`). Los tests pasan igualmente, lo que significa que
**la suite no está validando las versiones que la release declara**. Merece
decidirse: o se relajan los pines, o se alinea el entorno.

**H4 — `compatible_rollback_to` está vacío en todas las releases instaladas.**
El campo existe en el manifiesto y `validate_manifest()` lo exige, pero
`create_manifest()` lo escribe siempre como `[]`. Nadie puede responder "¿a qué
release puedo volver?" leyendo el manifiesto. Ahora que el esquema se lee de
verdad (H2), el campo se puede calcular; no se ha hecho aquí para no cambiar el
comportamiento del desplegador en un carril de preparación.

**H5 — No hay endpoint `/health` sin autenticar.** La salud es un CLI más
`/admin/health` (rol admin). Cualquier sonda externa —proxy, monitor,
balanceador— que espere `/health` obtiene 404 o una redirección al login. No es
un defecto en sí, pero debe constar antes de que alguien configure una sonda.

**H6 — RTO hasta servicio sin medir.** Lo medido (8,2 min) es solo la fase de
restore. La única forma de saber el RTO real es cronometrar un ensayo completo
de rollback. El timer de prueba de restauración existe
(`s9-knowledge-neo4j-restore-test.timer`) pero está **desactivado**.

**H7 — RPO sin garantía.** El backup automático es una *propuesta* sin instalar
(`deploy/propuestas/backup-automatico/`), y el healthcheck de VM105 lleva desde
el 2026-07-17 avisándolo con un `failed`. Desplegar sin resolver esto significa
estrenar la release con el healthcheck ya en rojo, que es la mejor forma de
dejar de mirarlo.

**H8 — Propietario de ficheros no verificado.** La especificación declara
`www-data`/`root` según el fichero, pero el comprobador solo valida permisos, no
propietario. Requiere resolver uid/gid en el destino.

**H9 — `S9K_CSRF_SECRET` no admite fichero de secreto.** A diferencia de la
contraseña de Neo4j, el código no soporta `S9K_CSRF_SECRET_FILE`, así que el
secreto tiene que vivir en texto dentro de `/etc/s9-knowledge/viewer.env`. Es
una asimetría conocida; se mitiga con permisos 0600 y se declara aquí.

---

## 7. Lo que este trabajo NO hace

No despliega. No abre PR. No toca VM105 ni ninguna credencial de producción. No
migra el grafo legacy. No activa ninguna flag. No corta ningún tag. Deja
preparado el gate para que la decisión de desplegar pueda tomarse leyendo, y no
recordando.
