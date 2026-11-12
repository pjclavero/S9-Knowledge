# deploy/ — instalación y despliegue reproducible de S9 Knowledge

Herramientas para instalar, actualizar, verificar y revertir sin comandos
memorizados. Nada se despliega automáticamente: el operador revisa primero los
dry-runs y ejecuta después.

## Despliegue genérico con Ansible

`ansible/inventory.example`, `site.yml` y los roles
`common/data_engine/viewer/auth/systemd/tls/healthchecks` no dependen del nombre de
VM105. El inventario de ejemplo usa `192.0.2.10` (RFC 5737, no una IP real)
como *default* ilustrativo, usuario `root` y las rutas de esa máquina, pero host, usuario,
grupo, rutas, repositorio y rama se cambian exclusivamente en el inventario:

```bash
cp deploy/ansible/inventory.example deploy/ansible/inventory.ini
# editar ansible_host, ansible_user y las variables s9k_*
ansible-playbook -i deploy/ansible/inventory.ini deploy/ansible/site.yml --check --diff
ansible-playbook -i deploy/ansible/inventory.ini deploy/ansible/site.yml
```

`deployments/local-vm105/` se conserva como referencia histórica no ejecutada;
no es el procedimiento vigente.

## Primera release: de máquina limpia a `INSTALLATION_COMPLETE` (B2 · USABLE-V1)

### ESTADO DE ESTA SECCIÓN (leer antes de seguir)

```
CODE         PASS      camino implementado; pasos 3-4, 6 y 16b-17 de deploy.sh ejecutados en arnés
CALIBRATION  PASS      scripts/calibracion/mutaciones_b2_fresh_install.py (job «Calibracion de gates»)
RC-E2E       PENDING   sin nginx, sin systemd, sin VM limpia, sin navegador, sin CA real
```

Antes de B2 una máquina nueva **no podía instalarse** por ningún camino
documentado (H-01): Ansible no crea `releases/<id>` ni `current`, y
`deploy.sh --mode fresh` daba `PROCEED` en el paso 3 y moría en el 4 por
`EMPTY_STATE`. Y un host sano con `jobs.db` ausente o vacía tampoco podía
actualizarse (H-43).

### El camino elegido: `deploy.sh --mode fresh` (uno solo)

La primera release la crea **`deploy.sh --mode fresh`**, no Ansible. Razón:
`deploy.sh` ya es la autoridad que construye una release (clon, venv,
manifiesto, checksum, unidad, `current` atómico, identidad del proceso vivo,
healthcheck, rollback). Hacer que Ansible creara otra sería una **segunda**
forma de construir releases que podría divergir de la primera. Ansible
prepara la máquina y **dice** que la primera release no es suya: el rol
`viewer` avisa «`current` no existe … `deploy.sh --mode fresh`».

```bash
# 1. Preparar la máquina (directorios, .repo-cache, nginx/TLS si se provisiona)
ansible-playbook -i deploy/ansible/inventory.ini deploy/ansible/site.yml
# 2. Configuración del visor: la plantilla TAL CUAL, cambiando SOLO la URL pública
install -m 0600 deploy/config/viewer.env.example /etc/s9-knowledge/viewer.env
#    editar S9K_PUBLIC_BASE_URL (y S9K_TLS_CA_FILE si la CA es propia)
# 3. Configuración del WORKER (B3 · H-02: obligatoria, el paso 6 bloquea sin ella).
#    La plantilla TAL CUAL: cola, propuestas y decisiones iguales a viewer.env.
install -m 0600 deploy/config/worker.env.example /etc/s9-knowledge/worker.env
#    y el secreto de la cuenta de SÓLO LECTURA del grafo, 0600, en ESA ruta
#    (es el origen que copia la unidad del worker). Sin el valor en argv:
install -d -m 0700 /etc/s9-knowledge/secrets
install -m 0600 /dev/null /etc/s9-knowledge/secrets/neo4j_worker_password
#    ESCRIBIR LA CONTRASEÑA en el fichero ANTES de desplegar (vacío BLOQUEA el
#    paso 6), sin ponerla en argv: con un editor, o desde stdin:
cat > /etc/s9-knowledge/secrets/neo4j_worker_password   # pegar, Enter, Ctrl-D
# 4. Primera release (instala, habilita y arranca visor y worker)
deploy/scripts/deploy.sh --environment production --release-ref <tag|sha> \
    --mode fresh --confirm-production
```

- **Origen del código**: sin `current`, `deploy.sh` clona de `S9K_REPO_URL`
  (`/etc/s9-knowledge/deploy.env`, opcional) o de `${S9K_ROOT}/.repo-cache`,
  que deja el rol `data_engine`.
- **No hace falta fijar `S9K_CSRF_SECRET`**: el visor lo genera 0600 junto a
  la auth DB (#248) y `validate_deploy.sh` lo acepta si `S9K_AUTH_DB_PATH` es
  absoluta, está **bajo el state root** (ruta normalizada: un `..` no cuela)
  y su directorio se puede crear y escribir (comprobado por efecto). Un valor
  explícito débil sigue bloqueando. Desde H-06/H-08 el paso 5b deja el state
  root a nombre de `s9knowledge` y verifica POR EFECTO, con `runuser`, que ese
  usuario escribe allí (ver «Usuario de servicio dedicado y estado privado»).
- **Proveedor de fábrica `not_configured`** (#264): vacío honesto, nunca `mock`.
- **Estado de revisión fuera de la release**: `S9K_V3_REVIEW_DATABASE_PATH` y
  `S9K_V3_REVIEW_PROPOSALS_DIR` son críticas y el paso 6 ejecuta
  `preflight_ensayo_rc.py --grupo despliegue` (declaradas, absolutas, bajo el
  state root, escribibles y resueltas igual por visor y motor).
- **En `fresh` la unidad se habilita** (`systemctl enable`) además de
  arrancarse.
- **El visor y el worker corren como `s9knowledge`** (H-08 cerrado): la unidad
  que instala `deploy.sh` y la que copia Ansible son el MISMO fichero
  (`viewer/systemd/…`, `User=s9knowledge`). El usuario de sistema lo crea el
  paso 3b (y el rol `common`).
- **`auth.db` y todo su entorno nacen `0600`** en un state root `0700` (H-06
  cerrado en código; fresh/upgrade reales en laboratorio: VM112 PENDING).

### Quién decide si se puede seguir: `decision`, y por estado del producto

`detect_state.py` clasifica auth y jobs y devuelve **`decision`**, la única
respuesta a «¿se puede seguir?» (el paso 4 la aplica en
`lib.sh::paso4_migrar_o_validar_estado`). `global_state` queda **informativo**.

| Estado del producto | `--mode upgrade` | `--mode fresh` |
|---|---|---|
| sin `auth.db`, o `auth.db` sin usuarios y **sin sello** | BLOCK (no hay admin) | **PROCEED** → `FIRST_ADMIN_PENDING` |
| `auth.db` sin usuarios pero **sellada** (`install_state`) | BLOCK | BLOCK: no es fábrica y `/setup/admin` no se reabre |
| `auth.db` con usuarios y ≥1 admin | PROCEED | **BLOCK**: fresh nunca sobrescribe |
| `auth.db` corrupta / legacy y nueva divergentes | BLOCK | BLOCK |
| `jobs.db` ausente o **vacía** | no bloquea (H-43) | no bloquea |

### Los estados de la instalación, y cómo se mide cada uno

«`deploy.sh` terminó» **no** es «instalación completa». La autoridad única de
la cadena es `deploy/scripts/estado_instalacion.py`; la evidencia se anota en
`${S9K_STATE_ROOT}/deploy/instalacion.json` (sin secretos) y cada estado
exige la de **todos** los anteriores.

| Estado | Evidencia | La observa |
|---|---|---|
| `DEPLOY_OK` | pasos 1–16 en verde (release activa, proceso vivo verificado, healthcheck) | `deploy.sh` |
| `HTTPS_BOOTSTRAP_PATH_VERIFIED` | vía HTTPS por efecto **y** GATE A | `deploy.sh` 16b + 16c |
| `FIRST_ADMIN_PENDING` | sin usuarios y sin sello, y `GET /setup/admin` 200 | `detect_state` + GATE A |
| `FIRST_ADMIN_VERIFIED` | GATE B `--modo bootstrap` | el operador |
| `INSTALLATION_COMPLETE` | GATE B `--modo persistencia` **después** de reiniciar | el operador |

`deploy.sh` imprime **dos líneas** al terminar, que responden a dos preguntas:

- `ESTADO_OBSERVADO=<estado>`: lo que vio **esta** ejecución, según la cadena
  de arriba. `deploy.sh` nunca **anota** evidencia de gates que no observó y
  no crea administradores, así que por sí solo no pasa de
  `FIRST_ADMIN_PENDING`.
- `ESTADO_DEL_PRODUCTO=<estado>`: lo que la auth DB dice de sí misma, leída
  como la lee `detect_state` (sello `install_state` y administradores
  activos), **nunca** del registro. Valores: `FRESH` (no hay auth DB),
  `FIRST_ADMIN_PENDING` (sin usuarios ni sello), `BOOTSTRAP_SELLADO` (sellada
  y sin admin activo), `INSTALLATION_COMPLETE_SEGUN_PRODUCTO` (sellada, o con
  usuarios —el producto infiere el sello—, y con ≥1 admin activo) e
  `INDETERMINADO` (la base no es legible).

**El registro se reinicia en CADA despliegue**, también en `upgrade`: la
evidencia de un gate pertenece a la release que lo observó. Un `upgrade`
sobre una instalación ya completa imprime `ESTADO_OBSERVADO=DEPLOY_OK` (lo
observado en esa ejecución), **no** `INSTALLATION_COMPLETE` heredado; para
volver a afirmarlo sobre la release nueva hay que repetir el GATE B
`--modo persistencia`… y aun así la cadena exige `gate_a`, que en una
instalación sellada no se puede observar. Es deliberado: en `upgrade` la
cadena de primera instalación no se re-declara. Lo que el operador lee para
saber que la instalación sigue completa es `ESTADO_DEL_PRODUCTO=
INSTALLATION_COMPLETE_SEGUN_PRODUCTO`.

**Límite conocido (O1):** `detect_state` cuenta como `EMPTY_STATE` cualquier
SQLite íntegro **sin tabla `users`** (por ejemplo, un fichero ajeno en
`S9K_AUTH_DB_PATH`); en `fresh` eso procede. Qué hace después el visor con
esa base (migrarla o negarse a arrancar) **no se ha medido** en B2: es deuda
de rango 4.

### GATE A — el CSRF funciona sobre la vía HTTPS (lo ejecuta `deploy.sh`)

Paso 16c, solo con el primer administrador pendiente. `GET /setup/admin`
(cookie `Secure` observada y token) y un `POST` **deliberadamente inválido**
(usuario vacío) **con el CSRF correcto**. PASS **solo** si la respuesta es la
validación EXACTA: `400` con la plantilla, el mensaje
«El nombre de usuario no puede estar vacio.» y un token nuevo. No escribe nada.

| Respuesta | Causa |
|---|---|
| `400` + mensaje exacto | PASS: el CSRF pasó y la validación corrió detrás |
| URL `http://` con `Secure=true` | `ESQUEMA_NO_HTTPS` + `COOKIE_SECURE_SOBRE_HTTP` (no se sondea: D3) |
| `403` por HTTP plano (arnés) | `COOKIE_SECURE_SOBRE_HTTP`: la cookie no vuelve, **no** es un CSRF roto |
| `403` por HTTPS y el producto dice «el formulario ha caducado…» | `CSRF_RECHAZADO_CON_COOKIE`: la cookie llegó y el token no validó (secreto distinto entre procesos…) |
| `403` por HTTPS y el producto dice «no ha devuelto la cookie…» | `COOKIE_NO_VUELVE_POR_HTTPS`: algo entre cliente y visor descarta la cookie (proxy) |
| `403` por HTTPS sin ninguno de los dos mensajes | `CSRF_403_SIN_DIAGNOSTICO`: quien responde puede no ser el visor |
| `5xx` | `ERROR_DE_SERVIDOR` / `ALMACEN_DE_AUTH_NO_DISPONIBLE`: **nunca** PASS |
| `200`, `400` sin el mensaje | `VALIDACION_INESPERADA` |
| `303` | `ALTA_INVALIDA_ACEPTADA` |

```bash
python3 deploy/scripts/preflight_setup_admin.py --env-file /etc/s9-knowledge/viewer.env \
    --modo gate-a --registro /var/lib/s9-knowledge/deploy/instalacion.json
```

### GATE B — el primer administrador se crea, entra y persiste (lo ejecuta el operador)

Es el recorrido de #267 (`--modo bootstrap`, luego reiniciar el servicio y
`--modo persistencia`). La contraseña la **aporta el operador** por fichero
`0600` o `stdin`; **nunca** por `argv` y nunca la inventa el instalador.

```bash
python3 deploy/scripts/preflight_setup_admin.py --env-file /etc/s9-knowledge/viewer.env \
    --modo bootstrap --credenciales-desde cred.json --registro /var/lib/s9-knowledge/deploy/instalacion.json
systemctl restart s9-knowledge-viewer.service
python3 deploy/scripts/preflight_setup_admin.py --env-file /etc/s9-knowledge/viewer.env \
    --modo persistencia --credenciales-desde cred.json --registro /var/lib/s9-knowledge/deploy/instalacion.json
# -> ESTADO_OBSERVADO=INSTALLATION_COMPLETE
```

Si el administrador se crea en el navegador, basta `--modo persistencia` tras
el reinicio con esas credenciales; la cadena se queda entonces en
`FIRST_ADMIN_PENDING` (falta la evidencia del bootstrap), que es lo honesto.

### Qué se midió de verdad, y qué no

Medido (`deploy/tests/test_b2_primera_release.py`): plantilla productiva
literal (solo cambian el prefijo del state root y la URL) → pasos 3–4 reales
en `fresh` → paso 6 real → `current` por `atomic_symlink` → visor real desde
`current/viewer` por TLS autofirmado → auth.db vacía y `.csrf_secret` 0600 →
pasos 16b–17 reales (`FIRST_ADMIN_PENDING`, GATE A sin escribir) → GATE B
bootstrap (`FIRST_ADMIN_VERIFIED`) → `upgrade` ya procede y `fresh` bloquea →
**proceso nuevo** → GATE B persistencia (`INSTALLATION_COMPLETE`). Y el
negativo: la misma plantilla por HTTP plano reproduce el 403, el GATE A lo
nombra `COOKIE_SECURE_SOBRE_HTTP` y `deploy.sh` muere en 16b sin línea de
estado.

No medido: clon de la release y su venv (red/pip), pasos 7–13 (systemd),
nginx, CA real, navegador, VM limpia, reinicio de **máquina**. El venv del
**motor** lo crea `deploy.sh` desde B3 (paso 2), junto a la unidad del worker
(ver «Worker de jobs como servicio»). **H-08** se cerró en H-06/H-08: ya no hay
dos unidades del visor (el rol `systemd` copia la de la release, como el
worker) y las dos declaran `User=s9knowledge`.

## Usuario de servicio dedicado y estado privado (H-06 + H-08 · USABLE-V1 · Fase C)

### ESTADO DE ESTA SECCIÓN (leer antes de seguir)

```
CODE         PASS      autoridad service_state.py, unidades, Ansible, migrar_estado.py, arranque fail-closed (arnés local)
CALIBRATION  PASS      scripts/calibracion/mutaciones_h06_h08_servicio_y_estado.py (M1–M12)
LAB (VM112)  PENDING   fresh y upgrade reales con root, useradd, systemd y OTRO usuario local: deploy/tests/lab/
RC-E2E       PENDING   no se ha tocado ninguna máquina de producción
```

**Contrato (una frase por línea).** Root instala y actualiza. nginx hace de
proxy con su propio usuario. **`s9knowledge` es el visor, el worker, el
healthcheck y el dueño exclusivo del estado privado.** La release es código.
El state root es `0700`; los ficheros privados, `0600`. Un usuario local ajeno
no lee `auth.db` ni `review.sqlite3`; ningún proceso normal necesita root; un
upgrade migra de forma segura **o PARA**.

### UNA autoridad (§22)

`data-engine/app/knowledge_v3/service_state.py` fija, y **solo ella**, las
cuatro cifras: usuario/grupo (`s9knowledge`), state root
(`/var/lib/s9-knowledge`, la que ya existía), modo de fichero (`0600`) y modo
de directorio (`0700`). De ahí beben por CLI (`service_state.py get …`) o por
import: `deploy.sh`, `lib.sh`, `validate_deploy.sh`, `review_store.py`,
`migrar_estado.py`, el arranque del visor y del worker. Las unidades systemd y
`group_vars/all.yml` son ficheros estáticos (no pueden importarla): un test
estructural los compara con ella (gate **M12**, `test_h06_h08_servicio_y_estado.py`).
La identidad **ya no se escribe** en los guiones de despliegue (otro test lo
exige) y desaparecieron las cuatro copias de `s9k_service_user` de Ansible
(defaults de `common`, `systemd`, `viewer` e `inventory.example`): queda UNA, en
`group_vars/all.yml`.

### Unidades (§11): una sola política

| Unidad | `User=` | `UMask=` | Notas |
|---|---|---|---|
| `viewer/systemd/s9-knowledge-viewer.service` | `s9knowledge` | `0077` | **única** unidad del visor: Ansible la **copia** de la release (se eliminó la plantilla Jinja que decía `www-data` mientras `deploy.sh` instalaba otra sin `User=`, es decir root: H-08) |
| `data-engine/systemd/s9-knowledge-worker.service` | `s9knowledge` | `0077` | antes `www-data` |
| `viewer/systemd/s9-knowledge-healthcheck.service` | `s9knowledge` | `0077` | antes root; `CapabilityBoundingSet=` vacío, `NoNewPrivileges=true`; HTTP local + bases `mode=ro` + `systemctl is-active` (consulta, sin privilegios); no se elevó ningún permiso |
| `s9-knowledge-neo4j-restore-test.service.j2` | `root` | — | operación de Neo4j (restore de prueba); **no toca el state root**; un test lo vigila |

Las unidades NO controlan la validación de arranque (es obligatoria, ver abajo) y
**ya no copian el secreto** de Neo4j a `/run`: lo leen directamente de
`/etc/s9-knowledge/secrets` (política SECRET, abajo). `validate_viewer_unit` /
`validate_worker_unit` rechazan una unidad que declare `S9K_STATE_VALIDATION` o
`S9K_STATE_ENFORCE`, o que reintroduzca `ExecStartPre`/`RuntimeDirectory`.

El usuario se crea **idempotente** en `deploy.sh` (paso 3b,
`lib.sh::asegurar_identidad_de_servicio`) y en el rol `common` de Ansible:
usuario y grupo **de sistema**, shell `nologin`, sin home de login, sin
pertenencia a `sudo`/`wheel`/`adm`/`docker`; se **comprueba el resultado**, no
que `useradd` “dijera sí”.

### Estado privado (§3–§5)

Todo el estado mutable vive bajo el state root; `<state>` es `0700`,
`s9knowledge:s9knowledge`; todo fichero, `0600`, **con independencia de la
umask del proceso** (el código crea con `os.open(…, 0o600)` vía la autoridad:
`auth.db`, su `.lock`, las copias `.bak.vN`, `jobs.db`, `decisions.jsonl`,
`audit.jsonl`, candidatos de glosario, `health.json`; `review.sqlite3` pasa de
`0660` a `0600`). Los `-wal`/`-shm` heredan el modo de su base. Excepción
declarada: `<state>/deploy/` (registros del instalador) es de `root` y el
servicio no lo lee.

**State root efectivo y canónico (fase 2, §6).** `S9K_STATE_ROOT` ya NO es obligatoria
(ZERO-TERMINAL: nadie edita `.env` para esto): la raíz efectiva es la declarada si existe
y, si no, el default del producto `/var/lib/s9-knowledge`
(`service_state.effective_state_root`, UNA función para visor, worker y despliegue).
Una raíz de despliegue NO canónica exige el override declarado y coincidente; si no se
determina de forma inequívoca, el despliegue PARA (2b).

`decisions.jsonl`, `audit.jsonl` y `glossary-candidates/` **ya no caen por
defecto en la release**: `viewer.env.example` los declara y, si faltan, el visor
los deriva junto a `review.sqlite3` (misma función que usa el despliegue).

### Arranque fail-closed (§13) y qué NO afirma (§14)

**La validación es OBLIGATORIA** (fase 2, §12): no depende de que la unidad ponga nada y
la ausencia de configuración NO es «modo test». Solo una **excepción explícita**,
`S9K_STATE_VALIDATION=disabled-explicit-for-tests` (valor exacto; la fija el `conftest.py`
raíz de la suite y los guiones de laboratorio que lo declaren), la omite, y la omisión se
anuncia en el log; en un `viewer.env`/`worker.env`/unidad operativa esa variable PARA el
despliegue. Antes de abrir una sola base, visor (`main.py::_startup_auth`) y worker
(`worker.py::main`) llaman a **la misma** `service_state.enforce`: el proceso
corre como `s9knowledge` (root → se niega, “viewer root por ruta alternativa”),
toda ruta de estado está declarada y cuelga del
state root (no de la release, sin symlinks), y todo el árbol cumple propietario,
modo, tipo y acceso efectivo. Ejemplo de diagnóstico, no un “Permission denied”:

```
STATE_CONTRACT_VIOLATION (estado/identidad del servicio, H-06/H-08):
  - /var/lib/s9-knowledge/auth/auth.db [OWNER]: tiene owner root:root; esperado s9knowledge:s9knowledge
  - /var/lib/s9-knowledge/auth/auth.db [MODE]: tiene modo 0644; maximo permitido 0600 (fichero privado)
```

**Techo declarado.** 0600 es el objetivo, no una prueba de aislamiento: se
detecta la *presencia* de ACL POSIX extendidas (xattr) y se falla cerrado, pero
no se interpretan; no se auditan capacidades, SELinux/AppArmor ni montajes. En
desarrollo y CI el servicio arranca con los defectos de desarrollo **solo si se
declara la excepción explícita** (`S9K_STATE_VALIDATION`, arriba).

### Migración AUTOMÁTICA en `deploy.sh` (§8, §9)

| Contrato | Dónde | Qué |
|---|---|---|
| 1–2 estado real y precondiciones | **2b** (puras: `viewer.env`/`worker.env` con rutas de estado válidas, ANTES de parar nada) y 5b | state root real (no symlink), rw, con espacio |
| 3–5 parar y comprobar | **3b**, `parar_y_verificar_servicios` | para timer de salud, healthcheck, worker y visor y **verifica** (estado + sin PID) antes de tocar nada |
| 6 inspeccionar | **5b**, `migrar_estado.py` | STOP ante symlink, tipo raro, ilegible, `-journal` pendiente o **fichero abierto por un proceso** |
| 7 mover estado legacy fuera de la release | 5b | copia a temporal `0600`, `fsync`, **hash SHA-256**, publica sin pisar y **solo entonces** renombra el original a `<nombre>.migrado-<release>` (no se borra) |
| 8–9 propietario y modos | 5b | `lchown` y `chmod` de todo el árbol (sidecars, lock, bak, `.csrf_secret`, jobs, review, health, propuestas) |
| 10 verificar | 5b | la **misma** `inspect_state` que usa el arranque, más `runuser -u s9knowledge` (lectura/escritura real) |
| 11 otros usuarios no acceden | 5b | `runuser -u nobody` no lee ni lista nada |
| 12–13 arrancar y salud | 13, 14a, 16 | además, los **procesos vivos** (`/proc/<PID>`) corren como `s9knowledge`; si no, rollback |
| 14 funcionalidad mínima | 16, 16c | `verify-deployment.sh`, GATE A |

Una precondición pura que falla (2b) no deja nada parado. Cualquier fallo posterior → `die` con el diagnóstico concreto, **la release no se activa,
no se declara éxito y el estado original se conserva** (los servicios quedan
parados: no se relanzan a ciegas). Casos que paran: fichero ilegible, directorio
inaccesible, sistema de ficheros de solo lectura, owner/modo inesperados,
symlink, ruta incorrecta o en la release, base abierta, servicio que no para,
movimiento parcial, espacio insuficiente, sidecar de tipo inesperado, conflicto
(origen y destino existen y difieren: se conservan los dos). **Idempotente**: un
segundo despliegue no cambia nada. El arbol legacy
(`/opt/knowledge-services/s9-knowledge-repo`) solo se **copia**, nunca se retira.

Esto resuelve la incoherencia anterior (el paso 6 se paraba con
`[SIN_PERMISOS]` ante un `review.sqlite3` `root:root` antes de que el paso 13
pudiera corregirlo, y esta documentación decía que el guion no hacía `chown`):
**una sola política**, y el cambio de dueño/modo ocurre ANTES de cualquier
verificación como usuario de servicio. Ya no hay receta manual de
`chown`/`chmod` (la de la sección de C1 queda como historia).

**Receta de upgrade (automática).**

```bash
deploy/scripts/deploy.sh --environment production --release-ref <tag|sha> \
    --mode upgrade --confirm-production
# No hay que editar nada para el state root (default canónico). Los secretos se
# dejan root:s9knowledge 0640 solos (paso 5b); S9K_BACKUP_DIR, si se declara, tiene
# que estar FUERA del state root.
```

### CLI de auth (§12): `runuser -u s9knowledge --`

La CLI abre `auth.db` en WAL: root crearía `-wal`/`-shm` como `root:root`. Por
eso **rechaza a root** (rc 4, mostrando el comando) incluso para comandos de
lectura. Elección: *rechazo claro*, no delegación automática (la CLI es
interactiva y su configuración está en `/etc`, ilegible para el usuario de
servicio; delegar en silencio esconde la identidad con la que se escribe).

```bash
sudo deploy/scripts/auth-cli.sh status            # forma canónica (helper de deploy)
sudo deploy/scripts/auth-cli.sh create-admin
# equivalente directo, con el entorno ya exportado:
runuser -u s9knowledge -- /opt/s9-knowledge/current/viewer/.venv/bin/python -m app.cli.auth status
```

El helper analiza `viewer.env` como root y **exporta** las variables (nunca en
argv: los secretos no viajan por la línea de comandos). El rol Ansible `auth`
ejecuta `status` con `become_user: s9k_service_user`.

### Secretos (SECRET), backups (BACKUP) y clasificación (fase 2, §7, §9, §10)

Cinco categorías, y todo lo persistente pertenece a UNA:

| Clase | Qué | Dónde y política |
|---|---|---|
| **STATE** | `auth.db`(-wal,-shm), `review.sqlite3`(-wal,-shm), `jobs.db`, `decisions.jsonl`, `audit.jsonl`, `glossary-candidates`, `glossary.db`, cache de IA externa (`S9K_EXTERNAL_AI_CACHE_DIR`), `.csrf_secret` | bajo el state root, `s9knowledge:s9knowledge`, dirs `0700`, ficheros `0600` |
| **SECRET** | password Neo4j (`/etc/s9-knowledge/secrets/*`), `viewer.env`/`worker.env` | NO se mueven al state root. `/etc/s9-knowledge` `root:s9knowledge 0710` (el grupo atraviesa, no lista), `secrets/` `0750`, ficheros `root:s9knowledge 0640` o más restrictivo: **el servicio lee y NO escribe** (lo fija `preparar_secretos_del_servicio` y lo verifica POR EFECTO `secret-probe` con `runuser`). `viewer.env`/`worker.env` siguen `root 0600` (los lee systemd) |
| **RELEASE** | releases (código, venvs, templates) | `root`, inmutable para el servicio |
| **EXTERNAL OPERATOR CONTENT** | `S9K_VAULT_ROOT`, `perfil-operador.json`, contenido del operador | fuera del state root; escribe solo si el FS ya concede permiso; sin `chown`/`chmod`, sin fallback ni copia bajo STATE |
| **BACKUP** | copias operativas | raíz SEPARADA (`/var/backups/s9-knowledge`, `root:s9knowledge 0750`; `S9K_BACKUP_DIR`), **nunca dentro del state root**: `validate-env` y `preparar_raiz_de_backups` lo rechazan; un `<state>/backups` con contenido PARA la migración (`BACKUP_EN_STATE`). Un restore vuelve a estado canónico re-ejecutando `migrar_estado.py` (owner/modos); no se rediseña el backup |

Se **eliminó** la copia del secreto a `/run` (unidades más simples, una pieza menos).

**Quinta categoría: EXTERNAL OPERATOR CONTENT (fase 2b).** `S9K_VAULT_ROOT` y
`perfil-operador.json` son contenido del operador y NO forman parte del state root; no se fuerzan
dentro de STATE/SECRET/RELEASE/BACKUP. Decisión del operador (TD-H06-02 cerrada): el perfil
sigue en la bóveda; no se mueve a `/var/lib/s9-knowledge`, no se desactiva la funcionalidad.
`vault_writer` escribe SOLO si el sistema de ficheros ya concede permiso efectivo al usuario de
servicio. La aplicación NO hace `chown`/`chmod` de la bóveda (un test por AST lo vigila), no corre
como root para escribirla, no guarda el perfil en otro sitio ni cae a STATE. Antes de escribir
comprueba el destino (directorio y fichero escribibles) y la escritura es atómica; si no puede,
responde **409** con «perfil-operador.json no es escribible por el usuario s9knowledge: …», sin
cambios parciales (mismo contenido, inodo, modo y propietario). Una bóveda opcional no escribible
NO impide arrancar (la validación de arranque solo mira el estado interno).

### Rollback: qué pasa con la unidad y el dueño

La **identidad no se revierte jamás**. `lib.sh::revertir_worker` solo restaura
una unidad respaldada si declara la identidad vigente (si es anterior a H-06 —
root o `www-data`— no la restaura: no podría leer el estado `0700`);
`rollback-release.sh` no acepta como destino una release cuya unidad del visor
no declare `s9knowledge`. El estado migrado se queda migrado: los originales
retirados siguen en la release como `*.migrado-<release>` (renombrar de vuelta
es manual y solo tiene sentido con la identidad anterior). Volver a un código
anterior a H-06 requiere restaurar copia, no un rollback de `current`.

### Inventario de escrituras persistentes (§3)

Derivado del código por AST y **vigilado**: `deploy/tests/test_h06_h08_inventario_escrituras.py`
cuenta los sitios de escritura de `viewer/app` y del cierre estático de
`worker.py` y falla si aparece uno nuevo (o uno supera su techo) sin declarar.
Techo declarado: cuenta *sitios de llamada*, no flujo de datos; no ve
reflexión, `subprocess` ni terceros.

| Módulo | Escribe | Gobierna | Clase |
|---|---|---|---|
| `viewer/app/auth/db.py` | `auth.db`, `-wal`, `-shm`, `.lock`, `.bak.vN` | `S9K_AUTH_DB_PATH` | STATE |
| `viewer/app/auth/csrf_bootstrap.py` | `.csrf_secret` | junto a `S9K_AUTH_DB_PATH` | STATE |
| `viewer/app/auth/bootstrap.py`, `routers/admin.py`, `main.py` | sello / `mkdir` del directorio de `auth.db` | `S9K_AUTH_DB_PATH` | STATE |
| `viewer/app/services/v3_review.py` | `decisions.jsonl`, `audit.jsonl` | `S9K_V3_REVIEW_DECISIONS_PATH` (o junto a `review.sqlite3`) | STATE |
| `viewer/app/services/v3_glossary_candidates.py` | candidatos de glosario | `S9K_V3_GLOSSARY_CANDIDATES_DIR` | STATE |
| `viewer/app/services/v3_review_store.py` | `review.sqlite3` (la **crea el despliegue**) | `S9K_V3_REVIEW_DATABASE_PATH` | STATE |
| `viewer/app/health/storage.py` | `health.json` | `S9K_HEALTH_REPORT_PATH` | STATE |
| `data-engine/app/jobs/job_store.py` | `jobs.db`, `-wal`, `-shm` | `S9K_JOBS_DB` | STATE |
| `data-engine/app/knowledge_v3/review_export.py`, `pipeline/*`, `ledger/store.py`, `writer/*` | propuestas, informes, ledger, auditoría del escritor | `S9K_V3_REVIEW_PROPOSALS_DIR` y rutas que se le pasan | STATE |
| `viewer/app/services/review_console.py` | almacén de laboratorio | `S9K_REVIEW_LAB_DIR` / tempdir; consola apagada por defecto | TMP |
| `viewer/app/vault_writer.py` | `perfil-operador.json` en la bóveda del operador | `S9K_VAULT_ROOT` (fuera del state root, opt-in) | EXTERNAL OPERATOR CONTENT |
| `data-engine/app/external_ai/cache.py`, `glossary/glossary_store.py` | caché NVIDIA, `glossary.db` | `S9K_EXTERNAL_AI_CACHE_DIR`, `S9K_GLOSSARY_DB`; por defecto bajo el state root | STATE |
| `viewer/app/main.py::_reviews_dir` | solo **lectura** de `output/reviews` | — | — |

### Deudas e hipótesis de esta entrega

- **TD-H06-01** (reducida) `deploy/propuestas/backup-automatico/` (NO instalada) ya apunta a
  la raíz de backups separada (`/var/backups/s9-knowledge`); le queda ejecutar `sqlite3 .backup`
  como `s9knowledge` (como root puede crear `-wal`/`-shm` `root:root` junto a una base viva) antes
  de adoptarla.
- **TD-H06-02** (cerrada) `vault_writer` = EXTERNAL OPERATOR CONTENT (ver «Quinta categoría»).
- **TD-H06-03** (cerrada) la caché de IA externa y `glossary.db` ya no tienen default dentro de
  la release: `<state root>/external_ai_cache` y `<state root>/glossary`.
- **TD-H06-04** El reparto de ACL, capacidades y SELinux no se audita (techo).
- No medido aquí (necesita laboratorio): `useradd`, `chown` a `s9knowledge`,
  `runuser` real, `systemd-analyze` con la unidad desplegada, `nobody` leyendo,
  `become_user` de Ansible (puede exigir el paquete `acl`), reinicio de máquina.

## Vía HTTPS: sin ella la instalación NO está completa

### ESTADO DE ESTA SECCIÓN (leer antes de seguir)

```
CODE         PASS     mecanismo implementado (preflight, gates, rol, plantillas)
CALIBRATION  PASS     scripts/calibracion/mutaciones_pr3_instalacion_https.py
RC-E2E       PENDING  no ejecutado: aquí no hay TLS, ni navegador, ni VMs
```

Lo que sigue describe el mecanismo en presente («detecta», «reutiliza»,
«verifica por efecto») porque así está implementado y calibrado. **Eso no es
lo mismo que ejercido en una máquina real**: léase todo lo de abajo con
`RC-E2E PENDING` en mente, no al revés.

### El defecto medido

Con la plantilla literal, `S9K_SESSION_SECURE=true` hace que la cookie CSRF de
`/setup/admin` salga con atributo `Secure`. Sobre `http://` ningún cliente la
devuelve y el `POST` entra en **bucle de 403**. Medido con doble control
positivo: reinyectando la cookie a mano → 303 correcto; con
`SESSION_SECURE=false` → bootstrap completo. Consecuencia: **una instalación de
fábrica sobre HTTP plano no puede crear su primer administrador**, y la única
salida era editar `.env` a mano — un terminal, justo en el paso que existe para
evitarlo.

### La decisión (D3) y lo que NO se hizo

- `S9K_SESSION_SECURE=true` **permanece** como default seguro. No se degrada
  automáticamente.
- **No** se usa el esquema de la petición (`request.scheme == "http"` ni
  equivalente) como razón para degradar la cookie, y **no** hay ningún fallback
  a HTTP para «hacer pasar» la instalación. Resolver esto debilitando la
  garantía se consideró y se **descartó**.
- `S9K_SESSION_SECURE=false` queda **únicamente** como opt-out explícito de
  laboratorio/desarrollo.
- **TLS es responsabilidad del proceso de instalación.** Una instalación
  productiva **no se considera completada** hasta que entrega una URL HTTPS
  funcional.

### Contrato de la vía HTTPS soportada

1. La instalación **declara** su URL pública en `S9K_PUBLIC_BASE_URL`
   (`/etc/s9-knowledge/viewer.env`). Ausencia **no** es «no aplica»: es fallo.
2. El esquema es `https`.
3. El certificado presentado **verifica contra un almacén de confianza
   declarado**: el del sistema, o el de `S9K_TLS_CA_FILE`. Un autofirmado o una
   CA propia se aceptan **declarándolos**; el **preflight en sí** (el guion
   `deploy/scripts/preflight_https.py`) no expone ninguna bandera para
   desactivar esa verificación — eso es lo que «nunca se desactiva».
4. El **nombre** de la URL pública coincide con el certificado (SNI + hostname
   check).
5. El endpoint **responde**: `GET /api/status` sobre esa conexión TLS devuelve
   200 (auth off) o 401 (auth on) — el mismo criterio que
   `viewer/app/health/checks.py::check_viewer`. Un 502 es el terminador TLS sin
   backend, y **no** cuenta. **Esto es «contesta con uno de esos códigos», no
   «el visor está detrás»**: el cuerpo de la respuesta no se lee ni se
   descarta por contenido, así que cualquier proceso que devuelva 200/401 en
   esa ruta —incluido un terminador de pruebas enlatado— satisface este punto
   igual que el visor real. El negativo N4 del guion RC (abajo) se apoya en
   esto: lo que discrimina «terminador sin backend» no es que el 200 venga
   del visor, es que nginx devuelva 502 cuando no hay nada detrás.
6. **HTTP plano con cookie `Secure` es una instalación no válida.**
7. **Fallo de HTTPS ⇒ instalación NO completa** (código de salida ≠ 0).

### Quién comprueba cada mitad

| Mitad | Autoridad | Qué hace |
|---|---|---|
| Estática | `deploy/scripts/validate_deploy.sh::validate_https_contract` | presencia de `S9K_PUBLIC_BASE_URL`, esquema, y la **coherencia** con `S9K_SESSION_SECURE`. Bloquea en `production`, avisa en `lab` (ver «H-05 corte B» abajo: el visor, en cambio, NO arranca sin URL válida en ningún ambiente). |
| **Por efecto** | `deploy/scripts/preflight_https.py` | abre el socket TLS, verifica **cadena**, verifica **nombre**, y exige que el endpoint **conteste**. |

Las dos se invocan desde `deploy.sh` (pasos 6 y **16b**) y la segunda también
desde el rol `tls`. Una sola implementación por mitad, dos invocantes.

### H-05 corte B: URL pública obligatoria y Host aceptados

`S9K_PUBLIC_BASE_URL` es la ÚNICA autoridad del host público. El visor acepta
sólo `Host` = su hostname + `localhost`, `127.0.0.1`, `::1` (cualquier puerto);
el resto recibe **400** antes de la sesión o de cualquier ruta. **El visor no
arranca** sin URL válida —ausente, placeholder `cambiar.por.el.nombre.real`
(también como subdominio), comodín, sin hostname, malformada, `0.0.0.0` o con
caracteres no ASCII (IDN en punycode)— **ni siquiera en `lab`**.

Receta del operador (instalación existente o upgrade), ANTES de desplegar:

1. Inspecciona el `viewer.env` real (`/etc/s9-knowledge/viewer.env`): ¿tiene
   `S9K_PUBLIC_BASE_URL=` con el nombre real? Una plantilla copiada sin editar
   conserva el placeholder; instalaciones anteriores al PR-3 pueden no tenerla.
2. Decláralo con el hostname por el que se llega desde fuera, p. ej.
   `S9K_PUBLIC_BASE_URL=https://knowledge.seccionnueve.duckdns.org`.
3. El proxy (VM104) debe reenviar `Host` = ese nombre (el vhost de este repo
   usa `proxy_set_header Host $host`). Si reenvía otro nombre (IP interna, otro
   alias), esas peticiones reciben 400: no se añade el nombre a la lista, se
   corrige el proxy.
4. Si falla: el servicio muere en el arranque y `journalctl -u
   s9-knowledge-viewer` muestra `PublicEndpointError: PUBLIC_URL_...` con el
   código (`MISSING`, `PLACEHOLDER`, `WILDCARD`, `NO_HOSTNAME`, `MALFORMED`,
   `SCHEME`, `INVALID_HOSTNAME`). Un 400 `Invalid host header` en uso normal
   indica un `Host` no declarado; un 503 `Public endpoint misconfigured`, una
   configuración que dejó de ser válida con el proceso vivo.

Deuda declarada: en `lab`, `validate_https_contract` solo AVISA mientras el
visor luego se niega a arrancar (incoherencia consciente; endurecerla excede
este corte). `verify-deployment.sh` clasifica el 400 de la frontera como
«degraded» sin nombrar el `Host` (observación O5).

Las causas que nombra el preflight son discriminantes, no un error genérico:
`URL_PUBLICA_NO_DECLARADA`, `ESQUEMA_NO_HTTPS`, `COOKIE_SECURE_SOBRE_HTTP`,
`CERTIFICADO_NO_VERIFICABLE`, `NOMBRE_NO_COINCIDE`, `ENDPOINT_NO_RESPONDE`,
`ENDPOINT_RESPUESTA_INESPERADA`, `ALMACEN_DECLARADO_ILEGIBLE` (un `--ca-file`
vacío, con basura, con un PEM corrupto o con una ruta inexistente; observación
O4 del PR #266 — antes de esta causa, esos cuatro casos escapaban como
traceback de `ssl.SSLError`/`FileNotFoundError` en vez de como un `Hallazgo`).

```bash
# Sobre un viewer.env del host:
python3 deploy/scripts/preflight_https.py --env-file /etc/s9-knowledge/viewer.env
# Contra una URL concreta, con CA propia declarada:
python3 deploy/scripts/preflight_https.py --url https://knowledge.example.net \
    --session-secure true --ca-file /etc/s9-knowledge/tls/ca.pem
```

### El rol `tls`: detectar y reutilizar, o provisionar

`deploy/ansible/roles/tls` **detecta** un terminador ya escuchando en 443 y,
si lo hay, lo **reutiliza sin tocarlo** (reescribir la configuración de otro
para que «pase» no es instalar: es romper lo que funcionaba). Si no lo hay y
`s9k_tls_provision=true`, **provisiona** la vía soportada: nginx terminando TLS
delante del visor en loopback, con el `80` limitado a redirigir — si el 80
sirviera la aplicación, alguien llegaría a `/setup/admin` por ahí y se
encontraría otra vez el bucle de 403.

El rol **no genera certificados**. `s9k_tls_cert_file` y `s9k_tls_key_file` son
obligatorios para provisionar: un autofirmado creado en silencio por el
instalador produce una vía HTTPS que se ve verde y que ningún cliente acepta.

Al final, el rol **verifica por efecto** con el mismo preflight, invocándolo
sólo cuando `s9k_tls_verify: true` (default de fábrica). Esta variable es un
**interruptor maestro de la invocación desde Ansible**, distinto de lo que
dice el párrafo anterior: con `s9k_tls_verify: false` las dos tareas de
verificación (la que falla en `production`/cualquier ámbito distinto de
`lab`, y la que sólo avisa en `lab`) **no se ejecutan en absoluto**, y el rol
no dice nada al respecto — ni un aviso. Apagarlo es, en la práctica, instalar
sin comprobar por efecto que la vía HTTPS funciona, así que con
`s9k_tls_verify: false` la instalación **no debe declararse completa**: existe
para calibración y para ensayos locales sin red, no para uso en `production`.
`s9k_environment` sigue sin tener valor por defecto (observación O1 del PR
#266): hay que declararlo explícitamente en `inventory.ini` como `lab` o
`production`, y el rol falla con un `assert` si no está o si no es uno de los
dos.

### Recordatorio: `RC-E2E PENDING`

Ver el bloque de estado justo después del `##` de esta sección. Lo medido es
que **el preflight distingue** una vía HTTPS que verifica y
contesta de las formas en que no lo hace, contra endpoints TLS locales con
certificado autofirmado generado en el momento
(`deploy/tests/test_preflight_https.py`). Eso **no** demuestra que la
instalación entregue HTTPS en una máquina real: no se ha ejercido nginx, ni
systemd, ni una VM limpia, ni un navegador, ni DNS, ni una CA real.
VM110/VM111 están apagadas y no se encienden. Lo que falta es el ensayo de
abajo.

**Corrección de alcance (PR-4).** Esta frase decía además que no se había
ejercido «el recorrido de crear el primer administrador, ni un reinicio». Eso
ya no es exacto: el PR-4 lo ejerce contra el **visor real** por TLS local y
reiniciando su **proceso** (ver la sección siguiente). Lo que sigue sin
ejercerse es ese recorrido **sobre una máquina real con un navegador**, que es
lo que el ensayo RC mide. El techo se movió un poco; no se cerró.

## Instalación COMPLETA tras el bootstrap: el primer administrador se crea, entra y persiste

### ESTADO DE ESTA SECCIÓN (leer antes de seguir)

```
CODE         PASS     mecanismo implementado (preflight hermano del de HTTPS)
CALIBRATION  PASS     scripts/calibracion/mutaciones_pr4_instalacion_completa.py (10/10)
RC-E2E       PENDING  no ejecutado: aquí no hay nginx, ni systemd, ni VM, ni navegador
```

Como en la sección anterior, lo que sigue describe el mecanismo en presente
porque así está implementado y calibrado. **Eso no es lo mismo que ejercido en
una máquina real**: léase con `RC-E2E PENDING` en mente, no al revés.

### Lo que la sección anterior NO demuestra

`preflight_https.py` demuestra que el endpoint **contesta**: handshake que
verifica, nombre que coincide, y un `GET` con código de estado. Es necesario y
**no es suficiente**.

Un `200` dice que algo respondió. El defecto de rango 1 era otro: el **`POST`**
de `/setup/admin` entraba en bucle de 403 porque la cookie CSRF sale con
atributo `Secure` y sobre `http://` ningún cliente la devuelve. Una instalación
puede tener un `GET /setup/admin` que responde `200` impecablemente y seguir
siendo una instalación **en la que el primer administrador no se puede crear**.

### El criterio, y quién lo guarda

| Exigencia | Quién la comprueba |
|---|---|
| `/setup/admin` completa el flujo con cookie `Secure` | `comprobar_get_del_formulario` + `comprobar_post_crea_el_administrador` |
| **No basta `GET 200`** | `comprobar_recorrido_completo`: las fases **no observadas** no cuentan a favor (`RECORRIDO_INCOMPLETO`) |
| POST, CSRF, sesión y creación del administrador | el `303` a `/login?message=bootstrap_ok`, que es como el producto confirma el alta |
| Tras el setup, el login funciona | `comprobar_login_funciona`, con un cliente **limpio** y exigiendo cookie de sesión |
| El estado persiste tras reinicio | `--modo persistencia`: sello en `404` **y** login que sigue funcionando |

El guardián de «no basta `GET 200`» **no es una frase de la documentación**: es
una función, y tiene su mutación obligatoria (M1) en el arnés.

### Autoridades reutilizadas, no duplicadas

- **`preflight_https.py`** (PR-3) se **importa**: `Hallazgo`, el lector de
  `EnvironmentFile`, la lista cerrada de valores verdaderos, el contexto TLS
  que nunca apaga la verificación y las **dos puertas estáticas**
  (`ESQUEMA_NO_HTTPS`, `COOKIE_SECURE_SOBRE_HTTP`). No hay un segundo criterio
  de HTTPS en el repositorio.
- **El sello irreversible** de `viewer/app/auth/bootstrap.py`
  (`install_state['bootstrap_completed']`) se lee **por donde el producto lo
  publica**: el `404` que decide `routers/setup.py::_guarda`. El preflight **no
  abre la base SQLite** y no inventa su propia idea de «el setup está hecho»;
  sobre una instalación remota, además, no podría.
- **El fail-closed** del almacén de autenticación (`503`) se reconoce como lo
  que el producto dice que es: **no se sabe**. Nunca como «instalación nueva».

### D3 sigue gobernando

`S9K_SESSION_SECURE=true` permanece. Este preflight **no escribe
configuración**, **no habla `http://` nunca** —la puerta estática lo rechaza
antes de abrir socket, y hay una prueba que comprueba que **no se hizo ni una
petición**— y trata una cookie de setup **sin `Secure`** como un **fallo**
(`COOKIE_SETUP_SIN_SECURE`), porque ésa es la forma que tendría la degradación
que D3 consideró y descartó. `S9K_SESSION_SECURE=false` sigue siendo **sólo
opt-out de laboratorio**.

### Uso

Las credenciales **no se pasan por `argv`**: entran por un fichero `0600` o por
`stdin`, y no se imprimen.

```bash
# Recorrido completo (ESCRIBE: crea el primer administrador)
python3 deploy/scripts/preflight_setup_admin.py \
    --env-file /etc/s9-knowledge/viewer.env --modo bootstrap < cred.json

# Después del reinicio (SÓLO LECTURA)
python3 deploy/scripts/preflight_setup_admin.py \
    --env-file /etc/s9-knowledge/viewer.env --modo persistencia < cred.json
```

### POR QUÉ ESTO **NO** ES UN PASO DE `deploy.sh`

`deploy.sh` insertó el paso 16b para la vía HTTPS porque aquello se puede
verificar sin intervención. Esto **no**: crear el primer administrador exige
**una contraseña que elige una persona**. Un paso de despliegue que la generase
dejaría una credencial fabricada por el instalador en una instalación
productiva, que es peor que el defecto que se está cerrando. Por eso este
preflight es **herramienta del operador y del ensayo RC**, y el orden numerado
de `deploy.sh` **no se toca** en este corte. Queda declarado como frontera, no
como olvido.

**Actualización B2.** La frontera se mantiene para el **alta** (GATE B), pero
`deploy.sh` sí ejecuta ahora el **GATE A** (paso 16c, `--modo gate-a`): no
crea nada ni necesita credenciales, y es lo que le permite declarar
`HTTPS_BOOTSTRAP_PATH_VERIFIED` / `FIRST_ADMIN_PENDING`. Ver «Primera release».

### Qué se midió de verdad, y qué no

Medido: contra el **visor real** (`app.main:app`) arrancado como **proceso
separado** por `uvicorn` con TLS autofirmado y `S9K_SESSION_SECURE=true`, el
recorrido entero sale —`GET 200`, cookie `Secure` **observada**, `POST 303`,
sello en `404`, login `302` con sesión— y **sobrevive a matar el proceso y
arrancar otro** sobre la misma base. Y con un **control positivo de resultado
conocido**: el mismo visor por HTTP plano **reproduce el 403**, de modo que
consta que el instrumento ve el defecto cuando el defecto está.

No medido: nginx, systemd, una VM limpia, un navegador, DNS, una CA real.
VM110/VM111 están apagadas y no se encienden. Lo que falta es el ensayo de
abajo, al que este corte **añade filas**.

## Guion del ensayo RC de la instalación (PENDIENTE de ejecutar)

Este guion queda escrito aquí, en la autoridad de despliegue, para que el
ensayo no se improvise. **A fecha de hoy no se ha ejecutado ni una sola de sus
líneas.**

### Recorrido principal

```
VM limpia -> instalar -> HTTPS disponible -> abrir /setup/admin -> crear primer admin
-> cookie Secure efectiva -> CSRF válido -> setup sellado -> login
-> reinicio de servicios/VM -> login sigue funcionando
-> NINGUNA edición manual de .env -> NINGÚN cambio por terminal después de «instalado»
```

Las dos últimas líneas son condiciones de validez del ensayo, no pasos: si en
cualquier momento hay que editar `.env` o abrir un terminal después de que la
instalación se declare terminada, **el ensayo ha fallado**, por mucho que el
recorrido acabe.

**Instrumentación del recorrido** (añadido por el PR-4). Cada tramo tiene quién
lo mide, para que el ensayo no se juzgue a ojo:

| Tramo del recorrido | Se comprueba con |
|---|---|
| `VM limpia -> primera release -> current activo` (B2) | `deploy.sh --mode fresh`, pasos 3–4 (`decision`) y 12 |
| `instalar -> HTTPS disponible` | `deploy.sh` paso 16b → `preflight_https.py` |
| `/setup/admin -> cookie Secure -> CSRF funcional` (B2, sin escribir) | `deploy.sh` paso 16c → GATE A (`--modo gate-a`) |
| `/setup/admin -> cookie Secure -> CSRF -> admin creado -> sellado -> login` | `preflight_setup_admin.py --modo bootstrap` |
| `reinicio -> login sigue funcionando` | `preflight_setup_admin.py --modo persistencia`, **después** de reiniciar |

El recorrido **también se hace en el navegador**, que es lo que el preflight no
es. El preflight no sustituye al navegador: le quita la ambigüedad. Si los dos
discrepan, **manda el navegador** y eso es un hallazgo del ensayo.

### Negativos obligatorios

Un recorrido que sólo sale verde no mide nada. Cada fila tiene que salir en
rojo, y **por su causa**:

| # | Se rompe | Resultado exigido |
|---|---|---|
| N1 | Instalar sin HTTPS (ningún terminador, `S9K_PUBLIC_BASE_URL` ausente o `http://`) | **Instalación incompleta**: `deploy.sh` muere en el paso 16b con `URL_PUBLICA_NO_DECLARADA` / `ESQUEMA_NO_HTTPS`, y no imprime «DEPLOY completado». |
| N2 | Certificado no declarado (autofirmado contra el almacén del sistema) | fallo **explícito** `CERTIFICADO_NO_VERIFICABLE`, no un aviso. |
| N3 | Nombre incorrecto (certificado de otro `CN`/SAN) | fallo **explícito** `NOMBRE_NO_COINCIDE`. |
| N4 | Terminador TLS levantado sin backend | `ENDPOINT_NO_RESPONDE` o `ENDPOINT_RESPUESTA_INESPERADA` (502): que la configuración esté escrita no cuenta. |
| N5 | HTTP plano con `S9K_SESSION_SECURE=true` | `COOKIE_SECURE_SOBRE_HTTP` y **no se acepta como instalación correcta**; en el navegador, el bucle de 403 reproducido. |
| N6 | Setup corrupto o parcial (admin a medio crear, auth.db truncada) | **fail-closed**: no se sirve la aplicación como si estuviera instalada, ni se vuelve a ofrecer `/setup/admin` sobre un estado a medias. |
| N7 | Reinicio de servicios y de la VM | **no pierde** el administrador ni la configuración: el login posterior funciona sin tocar nada. |
| N8 | `GET /setup/admin` responde `200` pero el `POST` se rechaza (terminador que no reenvía la cookie, proxy que la descarta) | `BUCLE_403_CSRF` **y** `RECORRIDO_INCOMPLETO`: un `GET` que responde **no** cuenta como instalación completa. Es la fila que distingue este corte del PR-3. |
| N9 | Tras crear el administrador, `/setup/admin` **sigue sirviéndose** | `SELLO_NO_CIERRA_SETUP`: una instalación que sigue ofreciendo crear el primer administrador permite que un desconocido cree otro. |
| N10 | Base de autenticación **no durable** (ruta en tmpfs, volumen sin montar, contenedor que recrea su almacén) y reinicio | `ESTADO_NO_PERSISTE`, con los dos desenlaces distinguidos: la pantalla de alta **reabierta** (`200`), o el sello puesto y el **login ya inservible**. |
| N11 | El setup se sirve con cookie **sin `Secure`** (alguien «arregló» el bucle degradando la cookie) | `COOKIE_SETUP_SIN_SECURE`: la degradación que D3 descartó **no** se acepta como instalación correcta, ni siquiera sobre HTTPS. |
| N12 | Login que redirige pero **no emite sesión** | `SESION_NO_EMITIDA`: en el navegador eso se ve como un login que vuelve al login. |
| N13 | (B2) `deploy.sh --mode fresh` sobre un host con usuarios en `auth.db` | **BLOCK** en el paso 4 (`auth: NEW_STATE bloquea en fresh`), `auth.db` intacta. |
| N14 | (B2) `auth.db` truncada/corrupta en `fresh` y en `upgrade` | **BLOCK** con `CORRUPT_STATE`; nunca «instalación nueva». |
| N15 | (B2) `viewer.env` sin `S9K_V3_REVIEW_DATABASE_PATH` o `…_PROPOSALS_DIR` | **BLOCK** en el paso 6 nombrando la variable. |
| N16 | (B2) `upgrade` con `jobs.db` ausente o vacía | **sigue** (H-43): una cola vacía no bloquea. |
| N17 | (B2) `deploy.sh` en `fresh` termina | imprime `ESTADO_OBSERVADO=FIRST_ADMIN_PENDING` y `ESTADO_DEL_PRODUCTO=FIRST_ADMIN_PENDING`, **no** `INSTALLATION_COMPLETE`; éste solo tras GATE B `--modo persistencia` después de reiniciar. |

### Qué se registra

Para cada fila: la causa que imprimió el preflight (verbatim), el código de
salida, y si hubo que tocar un terminal. Un ensayo sin esa tabla rellenada no
cierra el `RC-E2E PENDING` de **ninguna** de las dos secciones anteriores.

Y, para las filas del recorrido principal (añadido por el PR-4): **las fases
que el preflight declaró OBSERVADAS**. El preflight las nombra una por una, y
un recorrido que acaba en verde con fases sin observar no es un recorrido
completo, es un `RECORRIDO_INCOMPLETO` que alguien leyó deprisa.

Las credenciales del ensayo **no se transcriben** en esa tabla ni en ningún
registro: se anota el nombre de usuario y nada más.

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
   corren sobre el mismo árbol — es decir, en **desarrollo**. En un
   **despliegue** no se admite (B2 · H-04, lado deploy): las dos rutas están
   en `CRITICAL_ENV_VARS` y en la plantilla productiva, y el paso 6 de
   `deploy.sh` ejecuta `preflight_ensayo_rc.py --grupo despliegue`.
3. Declararla **en uno solo** es el peor caso: el defecto del otro lado es una
   ruta válida, así que todo parece funcionar.

Es la misma exigencia que el Corte 2 ya impuso a `review.sqlite3`
(`S9K_V3_REVIEW_DATABASE_PATH`): visor y motor tienen que compartir volumen o
la autoridad de decisión se parte en dos.

La *resolución* de la ruta, en cambio, ya no puede divergir dentro del código:
existe **un solo resolvedor** (`data-engine/app/knowledge_v3/review_paths.py`)
y el visor lo importa en vez de derivar la suya. Un caso lo comprueba por
enumeración del árbol.

## Las decisiones humanas persisten: `review.sqlite3` lo crea el DESPLIEGUE (C1 · USABLE-V1 · H-04 + H-18)

### ESTADO DE ESTA SECCIÓN (leer antes de seguir)

```
CODE         PASS      deploy/scripts/review_store.py + pasos 6 y 13 reales de deploy.sh en arnés; E2E local fresh -> decisión -> upgrade
CALIBRATION  PASS      scripts/calibracion/mutaciones_c1_persistencia_revision.py (job «Calibracion de gates»)
RC-E2E       PENDING   sin systemd, sin usuario de servicio real (s9knowledge), sin VM limpia
```

Antes de C1 el estado de revisión vivía **por defecto dentro de la release** y,
si faltaba, nadie lo decía: el motor leía `{}` («nadie ha decidido nada») y el
visor **creaba una base vacía**. Un `deploy.sh` con una ruta nueva bajo el
state root daba «APTO: el estado sobrevive» mientras las decisiones humanas
quedaban huérfanas.

**Contrato.** *Deploy* es la autoridad que decide y prepara el almacén; el
*runtime* (visor y motor) lo **consume y verifica** y, con la ruta declarada,
**nunca lo crea** ni lo sustituye por `{}`.

| Situación | Qué hace el despliegue (paso 6 de `deploy.sh`, `review_store.py`) |
|---|---|
| `--mode fresh`, ruta libre | **crea** `review.sqlite3` con el schema del producto (`0600` en directorio `0700`, dueño = `s9knowledge`; H-06/H-08, antes `0660`) y lo **verifica por efecto**: existe, abre, tiene `human_decisions`, lo escribe el usuario del servicio |
| `--mode fresh`, ya hay un almacén **con decisiones** | **BLOQUEA**: con estado existente se usa `--mode upgrade` |
| `--mode upgrade`, almacén válido (aunque vacío: *vacío ≠ ausente*) | lo **preserva**; no crea ni toca nada |
| `--mode upgrade`, **sin almacén** | **STOP** por defecto: o la ruta cambió, o el estado se perdió |
| `--mode upgrade --autorizar-creacion-review-db`, sin almacén ni candidata legacy con decisiones | crea y **anota** la excepción en el log del despliegue |
| cualquier modo, almacén corrupto / directorio / schema ajeno / sin permisos | **STOP** con la causa real. La autorización **no es un `--force`**: nunca sobrescribe, repara ni adopta |
| ruta ausente pero hay una candidata legacy con decisiones (`${release previa}/viewer/output/reviews-v3/`, `/opt/knowledge-services/s9-knowledge-repo/…`) | **STOP aunque esté autorizado**: migrar es una decisión del operador |

**Primer upgrade tras C1 en una instalación que nunca abrió la revisión.** No
existe `review.sqlite3` en la ruta declarada y tampoco hay candidata con
decisiones: el despliegue se detendrá con «UPGRADE sin almacen…». Repetir con
`deploy.sh --mode upgrade --autorizar-creacion-review-db …`. Si en cambio
**había** decisiones en la release anterior, el STOP es correcto: hay que
migrarlas antes (no lo hace este guion).

**Primer upgrade tras C1 donde el visor (root) creó `review.sqlite3`.** *(Superado
por H-06/H-08: `deploy.sh` lo migra AUTOMÁTICAMENTE en el paso 5b —propietario
`s9knowledge`, modo `0600`, directorio `0700`—, antes de que el paso 6 lo mire
como usuario de servicio; ver «Usuario de servicio dedicado y estado privado».
La receta manual de abajo queda como historia y con los modos nuevos.)* Era el
caso habitual: el visor de `deploy.sh` corría como root y dejó
`review.sqlite3` como `root:root 0644`. El paso 6 se detenía con
`STOP … [SIN_PERMISOS]`, porque el usuario del servicio no puede escribirlo.
Receta histórica (se ejecutaba a mano, en el host, sabiendo lo que se toca):

1. **Inspeccionar** sin modificar nada. `<dir>` es el directorio de
   `S9K_V3_REVIEW_DATABASE_PATH` en `viewer.env`:
   `ls -ld <dir>` · `ls -l <dir>/review.sqlite3*` ·
   `stat -c '%U:%G %a %n' <dir> <dir>/review.sqlite3*`.
2. **Propietario esperado**: `s9knowledge:s9knowledge`, el que fija la autoridad
   (`service_state.py get service_user`); es lo que `deploy.sh` usa para el
   paso 6 (`REVIEW_USER`/`REVIEW_GROUP`) y el 13.
3. **Modo esperado** (autoridad `service_state.py`, usada por `review_store.py`
   y `preparar_estado_del_worker`): fichero `review.sqlite3` **`0600`** y
   directorio que lo contiene **`0700`**, ambos a nombre del usuario del
   servicio (SQLite crea ahí los `-wal`/`-shm`, que heredan el modo).
4. **Corregir**: `chown s9knowledge:s9knowledge <dir> <dir>/review.sqlite3*` ·
   `chmod 0700 <dir>` · `chmod 0600 <dir>/review.sqlite3*`.
5. **Repetir** el despliegue (`deploy.sh --mode upgrade …`); el paso 6 vuelve
   a verificarlo por efecto (existe, abre, `human_decisions`, escribible por el
   servicio). Ni el `chown` ni el `chmod` lo hace el guion por su cuenta sobre
   una base existente: la autorización no es un `--force`.

**La variable declarada tiene que significar algo.** `S9K_V3_REVIEW_DATABASE_PATH`
vacía, de solo espacios, relativa, apuntando a un directorio o con un carácter
que SQLite interpreta en una URI (`#`, `?`, `%`) o de control se rechaza en
`validate_viewer_env` (paso 6) y también en el runtime, con un diagnóstico que
nombra la causa (*no existe* ≠ *no es escribible* ≠ *no es un fichero* ≠
*schema inválido* ≠ *carácter no permitido en la ruta del almacén*, N19). Con
`#` o `?` en la ruta, una URI `file:` sin escapar se cortaba y SQLite abría
—creándolo— **otro** fichero; por eso, además del rechazo, toda URI del
almacén sale de una sola función (`review_paths.sqlite_uri`) que escapa la ruta.

**Una sola resolución de la ruta** (`review_paths.default_review_db()`),
compartida por visor, motor y preflight; `ReviewService(database_path=…)` es la
única costura de test. Sin la variable declarada (desarrollo) se conserva el
defecto del repositorio como **techo declarado**: ahí el visor puede crear el
fichero y el motor lee `{}` si no existe. Una instalación productiva no puede
estar en ese caso: la variable está en `CRITICAL_ENV_VARS`.

**Worker.** `ingest_v3` con la ruta declarada ausente termina `FAILED` con
`REVIEW_STORE_UNAVAILABLE` (o `REVIEW_STORE_PERMISSIONS` si es de permisos), sin
gastar la corrida y **sin publicar paquete**. El paso 13 deja el directorio del
almacén y sus `-wal`/`-shm` a nombre del usuario del worker
(`preparar_estado_del_worker`) y vuelve a **verificarlo por efecto**.

`preflight_ensayo_rc.py --grupo despliegue` acepta `--modo upgrade` (defecto,
estricto: el almacén tiene que existir) o `--modo fresh` (puede no existir aún) y
`--usuario-servicio` (evalúa los permisos del almacén para ese usuario, por bits
de modo, no para quien ejecuta).

**Medido** (CI required): `deploy/tests/test_c1_revision_deploy.py` (P1–P3,
N1, N4–N16, paso 6 y 13 reales, E2E local con dos releases exportadas) y
`viewer/tests/test_c1_revision_runtime.py` (N2, N3, N7–N10, N13, N17, N18, P1,
P2, techo). **No medido** (RC-E2E PENDING): `chown` a `s9knowledge` de verdad,
el reparto de propietarios de `-wal`/`-shm` entre visor y worker (ambos
`s9knowledge` desde H-06/H-08; laboratorio VM112), `systemctl` y el reinicio de
máquina.

### Deuda documentada C1 (sin carril abierto)

- **D1** El censo AST de N18 solo ve el literal `S9K_V3_REVIEW_DATABASE_PATH` y solo en `viewer/app` + `data-engine/app`: un alias o una concatenación no se detectan (techo declarado).
- **D2** No hay testigo de que `export_review_package` no se trague un `ReviewDecisionsError`.
- **D3** Un symlink colgante en la ruta declarada: fresh/autorizado crea en el destino, posiblemente fuera del state root (el juicio de ubicación es léxico).
- **D4** Inspeccionar una candidata legacy en WAL crea su `-shm`, también en dry-run.
- ~~**D5**~~ **CERRADA (P1-2, #279):** las URIs del almacén de revisión salen solo de `review_paths.sqlite_uri` (escapada; modos `ro`/`rw`) y una declaración con `#`, `?`, `%` o caracteres de control se rechaza (N19). Censo: fuera del almacén de revisión siguen URIs construidas a mano para otros almacenes (auth.db, jobs.db, backups) en `viewer/app/health/checks.py`, `viewer/app/auth/db.py`, `viewer/app/auth/schema_compat.py`, `deploy/scripts/detect_state.py` y `deploy/scripts/migrate_sqlite.py`; otro contrato, sin carril.
- **D6** Directorio no escribible: `OperationalError` crudo en el visor y `REVIEW_STORE_UNAVAILABLE` (no PERMISSIONS) en el worker.
- **D7** Quitar `--usuario-servicio` del preflight del paso 6 (o la exigencia de escritura) no pone nada rojo hasta el paso 13, ya con la release activada.
- **D8** Orden: en el paso 6 `review_store preparar` crea antes de `preflight` y `validate_worker_env`; si estos mueren, queda la BD creada.

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

### Quién provisiona esto: el operador deposita el secreto; el despliegue, el resto

Hasta B3 no lo provisionaba **nadie**: no había unidad systemd del worker en
ningún ref, el único lanzador (`scripts/run-jobs-worker.sh`, ya retirado)
apuntaba al layout *legacy* y buscaba un venv que nadie creaba, y un
`worker.env` ausente solo avisaba. Desde B3 (USABLE-V1 · H-02) el reparto es:

| Paso | Quién | Detalle |
|---|---|---|
| 1. Directorio | Ansible (`roles/common`) | `/etc/s9-knowledge`, `root:root`, `0700` |
| 2. Subdirectorio | **el operador, a mano** | `/etc/s9-knowledge/secrets`, `root:root`, `0700` |
| 3. Fichero del secreto | **el operador, a mano** | `/etc/s9-knowledge/secrets/neo4j_worker_password`, `root:root`, **`0600`**, fuera de la release (nunca bajo `/opt/s9-knowledge/current`, que `validate_deploy.sh` rechaza). **Tiene que ser esa ruta**: es el origen que copia la unidad |
| 4. Entorno del worker | **el operador, a mano** | `/etc/s9-knowledge/worker.env`, `root:root`, `0600`, desde `deploy/config/worker.env.example`: `S9K_NEO4J_URI`, `S9K_NEO4J_USER`, `S9K_NEO4J_PASSWORD_FILE`, `S9K_JOBS_DB`, `S9K_V3_REVIEW_PROPOSALS_DIR` y `S9K_V3_REVIEW_DATABASE_PATH` (las tres últimas, **iguales** a las de `viewer.env`) — **y sin `S9K_NEO4J_PASSWORD`** |
| 5. Venv del motor | `deploy.sh` (paso 2) | `<release>/data-engine/.venv` con `data-engine/requirements.lock` |
| 6. Unidad del worker | `deploy.sh` (pasos 7–13) y el rol `systemd` | la MISMA `data-engine/systemd/s9-knowledge-worker.service`; ver «Worker de jobs como servicio» |

No hay `ansible-vault` en este repositorio: el secreto lo deposita una persona
en el host y ninguna herramienta lo genera.

**La puerta:** `deploy/scripts/validate_deploy.sh::validate_worker_env`
—invocada desde el paso 6 de `deploy.sh`— **bloquea** si `worker.env` no existe
(desde B3: es el `EnvironmentFile` de un servicio que el despliegue instala y
arranca), si le falta cualquiera de las seis variables, si `S9K_JOBS_DB`,
`S9K_V3_REVIEW_PROPOSALS_DIR` o `S9K_V3_REVIEW_DATABASE_PATH` difieren de las
de `viewer.env`, si el fichero
del secreto no es `0600` o no existe, o si alguien ha puesto
`S9K_NEO4J_PASSWORD`. Su tabla de calibración está en
`deploy/tests/test_worker_env_validacion.py`: cada fila rompe una cosa y exige
rojo.

No se ha añadido `S9K_NEO4J_PASSWORD_FILE` a `CRITICAL_ENV_VARS`, y es
deliberado: esa lista gobierna `viewer.env`, y el **visor** admite a propósito
las dos formas (`viewer/app/config.py`). Hacerla crítica allí rompería una
configuración soportada del visor por un requisito que es del **motor**.

## Worker de jobs como servicio (B3 · USABLE-V1 · H-02)

### ESTADO DE ESTA SECCIÓN (leer antes de seguir)

```
CODE         PASS      worker real en subproceso; pasos 2/7/13 reales de deploy.sh
CALIBRATION  PASS      scripts/calibracion/mutaciones_b3_worker.py (job «Calibracion de gates»)
RC-E2E       PENDING   systemd real, reinicio de máquina (ensayo RC)
```

Una ingesta pedida desde `/panel/operations` la procesa el worker **sin ningún
comando**: el despliegue lo instala como servicio, se reinicia solo y se
recupera de un proceso muerto a mitad de un trabajo.

### La unidad canónica

`data-engine/systemd/s9-knowledge-worker.service` es la **única** plantilla.
`deploy.sh` la valida (paso 7), la instala (pasos 8–9), la verifica con
`systemd-analyze verify` (paso 10), la **habilita y la arranca** antes de
reiniciar el visor (paso 13, en `fresh` y en `upgrade`: hasta B3 no existía,
así que todo upgrade es también su primera instalación) y exige que esté
`active` en tres lecturas (paso 14b; si no, rollback). El rol Ansible `systemd`
**copia ese mismo fichero** desde la release activa y comprueba que su `User=`
es `s9k_service_user` (y desde H-06/H-08 el visor sigue el mismo patrón: ya no hay
una segunda versión en Jinja de ninguna de las dos unidades).

| Directiva | Valor | Por qué |
|---|---|---|
| `User=`/`Group=` | `s9knowledge` (la autoridad `service_state.py`) | no corre como root ni como `www-data`; un test cruza esta unidad con la autoridad (gate M12) y `deploy.sh` pide la identidad a la autoridad, no a esta unidad |
| `UMask=` | `0077` | lo que escribe (propuestas, `jobs.db` si la crea él) nace `0600` |
| `EnvironmentFile=` | `/etc/s9-knowledge/worker.env` | su configuración; obligatoria |
| `ExecStartPre=+-` | copia el secreto `0600` a `/run/s9-knowledge-worker/` | el usuario del servicio no atraviesa `/etc/s9-knowledge` (`0700`); con `-`, si falta, la ingesta falla **cerrado** y visible (`GRAPH_OBSERVATION_UNCONFIGURED`) en vez de una unidad muerta |
| `ExecStart=` | `…/data-engine/.venv/bin/python …/worker.py --loop --sleep-seconds 5 --release-stale-seconds 600 --retry-backoff-seconds 30` | daemon (sin `--limit`); huérfanos liberados gastando un intento; reintentos con retroceso |
| `Restart=` | `always` | vuelve si muere |
| `TimeoutStopSec=` | `120` | al parar, termina el trabajo en curso; si no le da tiempo, el huérfano lo libera el siguiente arranque |

### Qué hace el worker

* `--loop` es un **daemon**: una cola vacía no lo termina (antes salía con
  `rc=0` al instante: `if once or limit` con `--limit` = 1 por defecto).
  `--once` sigue existiendo para uso manual.
* **Latido**: mientras corre un trabajo refresca `locked_at`; un trabajo vivo y
  largo no se confunde con un huérfano.
* **Huérfanos** (`--release-stale-seconds`): en cada vuelta, un `running` sin
  latido vuelve a `pending` **gastando un intento**; al agotar `max_attempts`
  queda `failed`. Antes no gastaba intentos: un trabajo que matara al proceso
  se reintentaba para siempre.
* **Reintentos**: un fallo reintentable vuelve a `pending` con `next_retry_at`
  (`30 s × 2^intento`, techo 1 h) y no se reclama antes. Un fallo permanente
  (lo declara el handler) va directo a `failed`.
* **Cancelación cooperativa, solo del ESTADO**: un trabajo cancelado (o
  liberado y reclamado por otro) mientras corría **no** se sobrescribe al
  terminar; el handler no se interrumpe. **Los efectos NO se deshacen**: el
  paquete de propuestas que el handler ya escribió sigue en el almacén y
  visible en `/panel/review` (F4 de la revisión; deuda declarada).
* **Cola inutilizable = worker caído, no verde**: al arrancar se hace una
  escritura de prueba sobre `jobs.db` (`BEGIN IMMEDIATE` + `CREATE TABLE` +
  `ROLLBACK`); si falla (solo lectura, corrupta) el worker sale con `rc=3`. En
  `--loop`, `--max-vueltas-fallidas` (5) vueltas fallidas **seguidas** también
  lo terminan con `rc=3`, para que `Restart=always`, `systemctl is-active` y
  `deploy.sh::worker_activo` lo vean. Una vuelta fallida suelta no lo mata.
* **Rollback** (pasos 14/14b/16): si la release previa no trae
  `data-engine/.venv` (toda release anterior a B3), el worker se **deshabilita**
  (`disable --now`) y se restaura la unidad respaldada o se quita la nueva; si
  la trae, se restaura la unidad y se reinicia (`lib.sh::revertir_worker`).
* SIGTERM: termina el trabajo en curso y sale con `rc=0`. **Techo:** con
  `TimeoutStopSec=120`, un trabajo más largo que eso lo mata systemd al parar;
  queda huérfano y el siguiente arranque lo libera gastando un intento.
* **Techo: no hay tiempo máximo por trabajo.** Un handler colgado sigue
  latiendo y bloquea la cola (un solo worker) hasta que alguien lo pare (F6).

### Estado compartido con el visor, y permisos

`jobs.db`, el almacén de propuestas y la base de decisiones humanas
(`S9K_V3_REVIEW_DATABASE_PATH`, sin la cual el motor del worker contaría como
pendientes propuestas ya resueltas) son de los dos. Sus rutas salen de
**una** autoridad cada una: `job_store.ruta_de_despliegue` para la cola (H-37;
`deploy.sh` se la pide, las plantillas la declaran y un testigo exige que
coincidan) y `knowledge_v3.review_paths` para las propuestas (visor y worker
idénticos). `validate_worker_env` exige que `worker.env` y `viewer.env` digan
lo mismo en las tres.

Visor y worker corren los dos como `s9knowledge` (H-06/H-08). El paso 5b
migra y deja el estado compartido (cola, propuestas, decisiones) a su nombre
con modos `0700`/`0600`, y el paso 13 lo **re-comprueba** de forma idempotente
antes de arrancar (`lib.sh::preparar_estado_del_worker`): un `jobs.db` creado
por otro usuario `0644` dejaría al worker en «attempt to write a readonly
database». El caso antiguo (SQLite corriendo como root creando `-wal`/`-shm`
con el dueño de la base) ya no puede darse: root no ejecuta el servicio, y la
CLI de auth rechaza a root.

### Qué se midió de verdad, y qué no

Medido (CI required): el recorrido web → servicio → web en
`viewer/tests/test_b3_worker_desatendido_e2e.py` (visor real, worker real en su
propio proceso arrancado con los flags de `ExecStart`, el entorno de
`worker.env.example` y el directorio de `WorkingDirectory`; reinicio por
SIGTERM y segundo trabajo), los negativos en
`data-engine/app/tests/test_b3_worker_desatendido.py` (worker parado, error
del handler, worker matado a mitad, `max_attempts` agotado, cola vacía) y la
unidad por efecto en `deploy/tests/test_b3_worker_unidad.py`.

**No medido** (RC-E2E PENDING): `systemctl enable/restart` de verdad, el
`Restart=always` del gestor, el usuario del servicio sobre el state root real,
la copia del secreto por `ExecStartPre=+` en una máquina, el reinicio de **máquina** y
Neo4j/apply.

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
- `preflight_https.py`: vía HTTPS verificada **por efecto** (certificado,
  nombre y que el endpoint conteste). rc≠0 = instalación NO completa.
- `preflight_setup_admin.py`: el **recorrido del primer administrador**
  verificado por efecto (GET, cookie `Secure`, POST con CSRF, alta, sello,
  login y persistencia tras reinicio). Hermano del anterior: lo importa y no lo
  duplica. Credenciales por fichero `0600` o `stdin`, **nunca por `argv`**.
  rc≠0 = instalación NO completa. El alta (GATE B) **no** es un paso de
  `deploy.sh`; el GATE A (`--modo gate-a`, no escribe) **sí** (paso 16c).
- `estado_instalacion.py`: la cadena `DEPLOY_OK` → `INSTALLATION_COMPLETE`
  sobre la evidencia anotada; ningún estado sin todos los anteriores.
- `preflight_ensayo_rc.py --grupo despliegue --env-file … --state-root …`:
  el subconjunto del ensayo RC que `deploy.sh` exige en el paso 6.
- `validate_deploy.sh https <viewer.env> [lab|production]`: mitad estática del
  contrato HTTPS.
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
