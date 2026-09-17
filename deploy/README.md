# deploy/ — instalación y despliegue reproducible de S9 Knowledge

Herramientas para instalar, actualizar, verificar y revertir sin comandos
memorizados. Nada se despliega automáticamente: el operador revisa primero los
dry-runs y ejecuta después.

## Despliegue genérico con Ansible

`ansible/inventory.example`, `site.yml` y los roles
`common/data_engine/viewer/auth/systemd/healthchecks` no dependen del nombre de
VM105. El inventario de ejemplo conserva como *defaults* históricos
`192.168.1.205`, usuario `root` y las rutas de esa máquina, pero host, usuario,
grupo, rutas, repositorio y rama se cambian exclusivamente en el inventario:

```bash
cp deploy/ansible/inventory.example deploy/ansible/inventory.ini
# editar ansible_host, ansible_user y las variables s9k_*
ansible-playbook -i deploy/ansible/inventory.ini deploy/ansible/site.yml --check --diff
ansible-playbook -i deploy/ansible/inventory.ini deploy/ansible/site.yml
```

`deployments/local-vm105/` se conserva como referencia histórica no ejecutada;
no es el procedimiento vigente.

## Secretos y proveedores

El rol `systemd` instala `/etc/s9-knowledge/providers.env` como `root:root`
`0600`, con valores vacíos y `force: false`: una ejecución posterior de Ansible
no sobrescribe credenciales rellenadas en el host. Antes de arrancar valida que
el fichero sea regular y exista. Las unidades pertinentes cargan
`EnvironmentFile=-/etc/s9-knowledge/providers.env`; el prefijo `-` mantiene la
unit tolerante para despliegues externos al rol, mientras `AssertPathExists` y
`ExecStartPre` dan un error explícito en instalaciones gestionadas.

Variables admitidas, según los adaptadores V3:

| Variable | Uso |
|---|---|
| `S9K_NVIDIA_API_KEY` | Credencial del proveedor NVIDIA NIM |
| `S9K_OLLAMA_URL`, `S9K_OLLAMA_MODEL` | Endpoint y modelo Ollama |
| `S9K_OLLAMA_TIMEOUT`, `S9K_OLLAMA_RETRIES` | Límites de transporte Ollama |
| `S9K_TESSERACT_CMD` | Ruta opcional al binario Tesseract |
| `S9K_V3_EXTERNAL_ENABLED` | Habilita la política de proveedor externo |
| `S9K_V3_EXTERNAL_CAPABILITIES` | Capacidades externas permitidas |
| `S9K_EXTERNAL_AI_ALLOW_PRIVATE_CONTENT` | Permiso explícito para contenido privado |
| `S9K_V3_EXTERNAL_MIN_UNITS` | Umbral mínimo de uso externo |
| `S9K_V3_EXTERNAL_MAX_CALLS` | Presupuesto máximo de llamadas |
| `S9K_V3_EXTERNAL_MAX_COST_UNITS` | Presupuesto máximo de coste |

No se versionan valores reales. `viewer.env` sigue conteniendo la configuración
del visor y sus propios secretos; `providers.env`, solo la configuración de
proveedores.

## Invariante: el almacén de revisión lo comparten escritor y lector

`S9K_V3_REVIEW_PROPOSALS_DIR` **no es configuración de un servicio: es un
acuerdo entre dos.**

| Lado | Quién | Qué hace |
|---|---|---|
| Escritor | el worker que corre `ingest_v3` (data-engine) | deja ahí la cola de revisión de cada ingesta |
| Lector | el visor, en `/panel/review` | la pinta |

Si cada lado la resuelve a un almacenamiento distinto **no hay ningún error**:
hay un trabajo `complete`, un informe que dice `REVIEW: 2` y una pantalla que
dice «Sin propuestas visibles». El operador concluye que no hay nada que
revisar y da por buena una ingesta cuyas ambigüedades no ha visto. Es el
defecto que cerró el Slice 2 · Corte 3 (`docs/88`), y la forma de reabrirlo es
desplegar los dos servicios con valores distintos —o con uno solo declarado.

**Reglas de despliegue:**

1. Si se declara, se declara **en los dos** entornos (el del visor y el del
   worker) **con el mismo valor**, y apuntando a un almacenamiento que ambos
   monten con permiso de lectura (visor) y de escritura (worker).
2. Si no se declara en ninguno, ambos caen al mismo defecto del repositorio
   (`viewer/output/reviews-v3/proposals`), que sólo es válido cuando los dos
   corren sobre el mismo árbol.
3. Declararla **en uno solo** es el peor caso: el defecto del otro lado es una
   ruta válida, así que todo parece funcionar.

Es la misma exigencia que el Corte 2 ya impuso a `review.sqlite3`
(`S9K_V3_REVIEW_DATABASE_PATH`): visor y motor tienen que compartir volumen o
la autoridad de decisión se parte en dos.

La *resolución* de la ruta, en cambio, ya no puede divergir dentro del código:
existe **un solo resolvedor** (`data-engine/app/knowledge_v3/review_paths.py`)
y el visor lo importa en vez de derivar la suya. Un caso lo comprueba por
enumeración del árbol.

## Invariante: el worker tiene que poder OBSERVAR el grafo

**Slice 2 · Corte 5.** Hasta este corte el worker no tenía ni una referencia a
Neo4j y el propio `worker.py` lo declaraba por escrito. Ya no es cierto: el
handler `ingest_v3` abre una conexión de **sólo lectura** al grafo.

**Por qué no es opcional.** El motor marca un ancla del plan como `observed`
en un único sitio (`pipeline/graph_catalog.snapshot_entities`), alcanzable sólo
con driver. Sin driver, las anclas salen con `observed: false` y el sellado
omite **toda** proyección con `PROJECTION_ANCHOR_NOT_OBSERVED`: el operador
aprueba una relación, el plan se sella, el apply se ejecuta y la arista no
aparece nunca.

Y no vale copiar el `state_hash` del catálogo en fichero: ese hash está
**derivado** de `{entity_id, entity_type, version}`, o sea, es reconstruible
sin haber mirado el grafo. Es un valor plausible y falso. La observación real
no se puede sustituir.

**Leer no es escribir.** La escritura la gobierna `apply`, por separado, y el
worker sigue corriendo con `apply=False`. El driver que abre el worker se usa
para una sola consulta: el catálogo de entidades del workspace.

### La cuenta del worker ES de sólo lectura. No es una recomendación.

**Requisito, no consejo:** el worker se conecta con una cuenta de Neo4j que
**no puede escribir**, y eso es una propiedad de la cuenta comprobada por una
prueba negativa calibrada
(`viewer/tests/test_corte5_credencial_solo_lectura_neo4j_real.py`): intenta
`CREATE`, `SET`, `DELETE` y `MERGE` con esa cuenta y exige
`Neo.ClientError.Security.Forbidden` **y** que el recuento de nodos no se
mueva; su gemela hace lo mismo con la cuenta administradora y comprueba que
**sí** escribe, que es lo que distingue «no tiene permiso» de «la sentencia no
escribía».

Cómo se crea el rol (una vez, con una cuenta administradora):

```cypher
CREATE ROLE s9k_observador;
GRANT ACCESS ON DATABASE neo4j TO s9k_observador;
GRANT MATCH {*} ON GRAPH neo4j NODES * TO s9k_observador;
GRANT MATCH {*} ON GRAPH neo4j RELATIONSHIPS * TO s9k_observador;
CREATE USER s9k_worker_lector SET PASSWORD '<secreto>' SET PASSWORD CHANGE NOT REQUIRED;
GRANT ROLE s9k_observador TO s9k_worker_lector;
```

No se concede `WRITE`, ni `CREATE`, ni `SET`, ni `DELETE`, ni `MERGE`. Las
cuatro formas se comprueban por separado: conceder `MATCH` y olvidar que
`MERGE` es otra capacidad sería justamente el hueco por el que se cuela una
escritura.

> ⚠️ **CONDICIÓN DE EDICIÓN — verificada, no supuesta.** Medido contra
> `neo4j:5.26-community`: `CREATE USER` funciona, pero `CREATE ROLE`,
> `SHOW ROLES` y `ALTER DATABASE … SET ACCESS READ ONLY` responden
> `UnsupportedAdministrationCommand`, y **un usuario creado en Community
> escribe sin restricción**. En Community una cuenta de sólo lectura **no se
> puede expresar**.
>
> Por tanto: **el rol de sólo lectura exige Neo4j Enterprise.** Si el
> despliegue corre Community, el worker se conectará necesariamente con una
> cuenta capaz de escribir, y esa exposición residual **tiene que aceptarse
> explícitamente por escrito** — no se puede dar por mitigada. Lo único que la
> contiene entonces es que ningún camino de código emita una escritura, que es
> una propiedad del código y no de la cuenta.

### Lo que el worker necesita, y sin lo cual falla cerrado

| Requisito | Variable | Si falta |
|---|---|---|
| Conectividad al servidor | `S9K_NEO4J_URI` (`bolt://…`), sin valor por defecto | `GRAPH_OBSERVATION_UNCONFIGURED` |
| Usuario **de sólo lectura** (ver arriba) | `S9K_NEO4J_USER` | `GRAPH_OBSERVATION_UNCONFIGURED` |
| Credencial: **el camino de un fichero `0600`**, nunca la contraseña en una variable ni en `argv` | `S9K_NEO4J_PASSWORD_FILE` | `GRAPH_OBSERVATION_UNCONFIGURED` |
| Base/contexto correcto, si el despliegue no usa la de por defecto | `S9K_NEO4J_DATABASE` | consulta contra la base equivocada: catálogo vacío y plan sin proyección |
| Workspace del perfil de la fuente coherente con el del grafo | perfil de ingesta | catálogo vacío; ninguna ancla observada |
| CA/TLS, si la URI es `bolt+s`/`neo4j+s` | truststore del sistema en la imagen del worker | `GRAPH_OBSERVATION_UNAVAILABLE` |

> ⚠️ **El entorno del worker NO debe llevar `S9K_NEO4J_PASSWORD`.** El motor
> (`knowledge_v3/driver_neo4j.py`) **sólo** lee `S9K_NEO4J_PASSWORD_FILE` y
> **ignora** la variable con el secreto dentro. Si se copia `viewer.env` tal
> cual —que sí admite las dos formas—, el secreto queda en una variable de
> entorno, el worker sigue funcionando porque coge el fichero, y **nada avisa
> de que el secreto está expuesto de más**. Copiar `viewer.env` al worker es
> precisamente el error fácil.

**Fail closed, y sin ruta de repuesto.** Si algo de lo anterior falta, el job
**no** se completa con una corrida sin observar: termina en ERROR con uno de
los dos códigos. Se distinguen por si tiene sentido reintentar:

* `GRAPH_OBSERVATION_UNCONFIGURED` — **permanente**. Cubre la conexión sin
  declarar, el fichero de credencial ausente/vacío/legible por el grupo, una
  URI con un esquema no soportado, y una credencial que el servidor rechaza
  (el grafo responde bien; lo que está mal es lo declarado).
* `GRAPH_OBSERVATION_UNAVAILABLE` — **reintentable**. El grafo no responde
  ahora y puede responder luego.

Degradar a `driver=None` sería una ruta de repuesto silenciosa: produciría una
ingesta que parece correcta y cuyo plan no puede proyectar nada.

### Quién provisiona esto hoy: NADIE. Es trabajo pendiente del operador.

Dicho sin rodeos, porque este corte **rompe a propósito** cualquier despliegue
que no lo haga: hoy, en este repositorio,

* **`deploy/ansible/` no define ninguna variable `S9K_NEO4J_*` para el motor.**
  El rol `data_engine` sólo clona el repositorio y su cabecera dice «No ejecuta
  ingesta. No toca Neo4j.»
* **No existe ninguna unidad systemd para el worker de jobs.** Las unidades que
  sí existen son el visor, la prueba de restore y el healthcheck.
* **`scripts/run-jobs-worker.sh`** —el único lanzador— exporta sólo
  `S9K_JOBS_DB` y apunta al layout *legacy*
  (`/opt/knowledge-services/s9-knowledge-repo`).
* `validate_deploy.sh` valida `viewer.env`, **no** un entorno de worker, y
  `S9K_NEO4J_PASSWORD_FILE` ni siquiera está en `CRITICAL_ENV_VARS`.

**El patrón a replicar es el que ya usa el visor**, y es enteramente manual:

| Paso | Quién | Detalle |
|---|---|---|
| 1. Directorio | Ansible (`roles/common`) | `/etc/s9-knowledge`, `root:root`, `0700` |
| 2. Subdirectorio | **el operador, a mano** | `/etc/s9-knowledge/secrets`, `root:root`, `0700` |
| 3. Fichero del secreto | **el operador, a mano** | `/etc/s9-knowledge/secrets/neo4j_worker_password`, `root:root`, **`0600`**, fuera de la release (nunca bajo `/opt/s9-knowledge/current`, que `validate_deploy.sh` rechaza) |
| 4. Entorno del worker | **el operador, a mano** | `/etc/s9-knowledge/worker.env`, `root:root`, `0600`, con `S9K_NEO4J_URI`, `S9K_NEO4J_USER` y `S9K_NEO4J_PASSWORD_FILE` — **y sin `S9K_NEO4J_PASSWORD`** |
| 5. Lanzador | ya lo hace | `scripts/run-jobs-worker.sh` carga `worker.env` si existe |

Hay una **plantilla literal** en `deploy/config/worker.env.example`, con las
tres variables obligatorias y la lista de lo que **no** debe ir ahí.

No hay `ansible-vault` en este repositorio: el secreto lo deposita una persona
en el host y ninguna herramienta lo genera.

**Y ahora hay una puerta, no sólo un párrafo.**
`deploy/scripts/validate_deploy.sh::validate_worker_env` —invocada desde
`deploy.sh`— bloquea el despliegue si `worker.env` existe y le falta cualquiera
de las tres variables, si el fichero del secreto no es `0600` o no existe, o si
alguien ha puesto `S9K_NEO4J_PASSWORD`. Si el fichero **no** existe no bloquea
—hoy no hay unidad de worker instalada y exigirlo rompería todos los
despliegues actuales— pero **avisa nombrando el código** con el que el operador
se lo encontraría. Su tabla de calibración está en
`deploy/tests/test_worker_env_validacion.py`: cada fila rompe una cosa y exige
rojo.

No se ha añadido `S9K_NEO4J_PASSWORD_FILE` a `CRITICAL_ENV_VARS`, y es
deliberado: esa lista gobierna `viewer.env`, y el **visor** admite a propósito
las dos formas (`viewer/app/config.py`). Hacerla crítica allí rompería una
configuración soportada del visor por un requisito que es del **motor**.

### CONDICIÓN PREVIA AL DESPLIEGUE: nodos sin `state_hash`

**Esto tiene que cerrarse antes de apuntar el worker a un grafo real.** No es
una nota al pie: el grafo legado es exactamente el caso que lo dispara.

Medido: con **todos** los nodos del workspace sin `state_hash` —el estado de un
grafo anterior al arreglo del writer, o sembrado a mano— la ingesta del panel
termina en `failed` con **`INGEST_FAILED` genérico** y **cero propuestas**. El
operador recibe el mensaje genérico en vez del diagnóstico y, como
`INGEST_FAILED` es reintentable, **gasta los tres intentos mientras la pantalla
dice «el trabajo sigue en la cola»**.

La causa está localizada: `graph_catalog.carencias` sabe emitir
`ENTIDAD_SIN_STATE_HASH`, pero **`run_ingest` nunca la llama** —sólo lo hace
`ingest_cli.main`—, así que por el camino del panel la carencia **ni se
calcula**. Es del motor y no se corrige en este corte.

Antes de apuntar el worker a un grafo preexistente, comprobar:

```cypher
MATCH (n:V3Entity {workspace: $ws}) WHERE n.state_hash IS NULL RETURN count(n);
```

Si devuelve algo distinto de `0`, **no desplegar**: o se repuebla el
`state_hash` de esos nodos, o se cierra antes la carencia en `run_ingest`.

### Consecuencia para el ensayo RC

El próximo ensayo ya **no puede validar sólo que el visor y el worker comparten
volúmenes**. Tiene que validar además la **capacidad real del worker de
observar el grafo**: desde el entorno del worker, con sus variables y su
credencial de sólo lectura, una ingesta desde el panel tiene que terminar
`complete`. Si termina con `GRAPH_OBSERVATION_*`, el despliegue está incompleto
aunque todos los volúmenes estén bien montados.

## Actualización V3

El flujo operativo es:

1. Ejecutar `deploy/scripts/preflight.sh` y resolver cualquier bloqueo.
2. Revisar `deploy/scripts/deploy.sh ... --dry-run` y aplicar con `--confirm`
   (o la confirmación de producción que indique su ayuda).
3. Ejecutar `deploy/scripts/verify-deployment.sh --expected-release <release>`.
4. Si falla, planificar el rollback completo:

   ```bash
   deploy/scripts/rollback-full.sh --to <release-anterior> \
     --neo4j-dump /ruta/al/neo4j.dump
   ```

   El comando anterior solo simula. Tras revisar ambos planes, repetir con
   `--apply`. Incluso en apply, el orquestador vuelve a ejecutar primero el
   dry-run de aplicación y el de datos; si cualquiera falla, no toca ninguna
   pata. Al terminar ejecuta `verify-deployment.sh`.

`rollback-release.sh` revierte solo la aplicación. `rollback-full.sh` coordina
esa operación con `scripts/backup/neo4j-restore.sh`; no restaura SQLite.

## Prueba periódica de restore

El rol instala `s9-knowledge-neo4j-restore-test.service` y su timer, pero el
timer queda **deshabilitado y parado por defecto**. El servicio localiza el
`neo4j.dump` más reciente bajo `s9k_neo4j_backup_root`, falla de forma visible
si supera `s9k_restore_max_age_days` (8 por defecto) y ejecuta
`neo4j-rollback-dryrun.sh --backup-file` dejando el resultado en journald.

Para habilitarlo manualmente, después de revisar rutas y credenciales:

```bash
sudo systemctl enable --now s9-knowledge-neo4j-restore-test.timer
systemctl list-timers s9-knowledge-neo4j-restore-test.timer
```

La periodicidad se configura con `s9k_restore_test_timer` (default `weekly`).
También se pueden sobrescribir en el host `S9K_NEO4J_BACKUP_ROOT` y
`S9K_RESTORE_MAX_AGE_DAYS`.

## Workspaces locales

La V3 exige que el mismo identificador aparezca en `PipelineConfig.workspace`,
`GameProfile.workspace` y `S9K_WRITER_WORKSPACE`. El siguiente comando crea
solo estructura local y un `workspace.json` que permite validar esa identidad:

```bash
python3 scripts/dev/create_workspace.py mi_campana --root /var/lib/s9-knowledge/workspaces
python3 scripts/dev/create_workspace.py mi_campana \
  --validate /var/lib/s9-knowledge/workspaces/mi_campana
```

No registra nada en Neo4j ni ofrece gestión web.

## Modos de almacenamiento

| Modo | Estado actual |
|---|---|
| Local | **Disponible hoy**: estado, workspaces y fuentes en rutas locales |
| Con Nextcloud | Fuera de alcance; existen piezas históricas de ingesta, no un modo desplegable |
| Híbrido | Fuera de alcance; no hay orquestación soportada local + Nextcloud |

El instalador wizard, la gestión web de workspaces y el modo Nextcloud siguen
fuera de alcance deliberadamente.

## Scripts y validación

- `preflight.sh`: requisitos, sin cambios.
- `deploy.sh`: dry-run por defecto.
- `verify-deployment.sh`: estado de la release activa.
- `rollback-release.sh`: rollback solo de aplicación.
- `rollback-full.sh`: rollback coordinado de aplicación y dump Neo4j.

Validación local:

```bash
deploy/tests/validate.sh
python3 -m pytest deploy/tests/ -q
python3 -m pytest data-engine/app/tests/ -q
```

## Límites

No incluye secretos reales, rotación de claves, despliegue automático,
activación automática del timer, wizard, gestión web ni operaciones de
producción.
