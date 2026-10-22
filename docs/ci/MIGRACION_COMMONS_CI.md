# Migración de la CI de S9-Knowledge a COMMONS-CI (VM115)

> Carril **MIGRACION-CI-S9K**. Rama `ci/migracion-commons-ci` desde `origin/main` `284758c`, con
> `origin/main` `4eb442a` (fix de pip-audit, #276) integrado por `git merge`.
> Documento canónico de la infraestructura: `s9-server/infraestructura/commons-ci.md` (fuera de este repo).
> Estado de este documento: **preparación**. El runner `commons-ci-s9k-01` **no está registrado**:
> el registro (repo público, `--allow-public`) lo hace el operador en persona. Hasta entonces, nada de
> esta rama se empuja: con `runs-on` self-hosted y 0 runners el run se quedaría en cola sin fin.

## 1. Objetivo y límites

Recuperar CI operativa ejecutando los jobs en un runner self-hosted de VM115 **sin debilitar ningún gate
ni cambiar la semántica de ningún check**. Lo único que cambia en los workflows es:

- `runs-on: [self-hosted, linux, x64, commons, ci, s9-knowledge]` en cada job migrado;
- `timeout-minutes` donde falte (regla: 2 × la duración medida en GitHub, mínimo 30; calibraciones 360);
- pasos de instalación que en `ubuntu-latest` dependían de `sudo` (§6), en forma compatible con ambos runners.

**No cambia:** `name:` de ningún job (los 17 contextos requeridos se llaman igual), `on:`, `permissions`,
tests, asserts, excepciones de pip-audit, ni la protección de rama. Prohibidos `pull_request_target`,
`workflow_run` y `continue-on-error`.

## 2. Decisión: NO se añade la condición `if:` de eventos (§18.1 de commons-ci.md)

La condición recomendada como «defensa en profundidad»

```yaml
if: github.event_name == 'push' || github.event_name == 'workflow_dispatch' || (github.event_name == 'pull_request' && github.event.pull_request.head.repo.full_name == github.repository)
```

**no se aplica**, por dos razones medidas:

1. **SKIPPED ≠ GREEN.** Un job saltado por `if:` informa `success` y **no bloquea** un check requerido
   (documentación de GitHub Actions: «A job that is skipped will report its status as "Success". It will
   not prevent a pull request from merging, even if it is a required check»). En un PR desde fork los 17
   requeridos quedarían «verdes» sin ejecutar nada. Sin el `if:`, ese PR va al runner self-hosted y el
   **guard del hook de inicio lo rechaza en rojo** (salida 21, ningún paso), que es lo seguro.
2. **Rompe un gate requerido.** `check_ci_config.py` solo admite `if: always()` (`CONDICIONES_PERMITIDAS`).
   Prueba local (2026-10-22, sobre `284758c`):

   | `ci.yml` | `python3 .github/scripts/check_ci_config.py` |
   |---|---|
   | sin cambios | OK (rc=0) |
   | `check-unicode` con `runs-on` self-hosted **y** el `if:` de §18.1 | `FALLO: 1 problema(s) de integridad de gates` — «el job `check-unicode` declara `if: …`. Una condicion solo puede hacer que se ejecute MENOS…» |
   | `check-unicode` con `runs-on` self-hosted **sin** `if:` | OK |

   Re-anclar el gate para admitirla sería relajar un gate, que está prohibido.

**Frontera frente a forks que queda:** (1) aprobación obligatoria de **todos** los contribuidores externos
(`all_external_contributors`, verificado por GET el 2026-10-22) y (2) guard de eventos en el hook de inicio
de VM115 (root, fuera del alcance del PR). Flujo para PR externos: §18.4 de commons-ci.md (los forks no
reciben CI self-hosted; el mantenedor lleva el cambio a una rama interna).

## 3. Runner `commons-ci-s9k-01`

| Campo | Valor |
|---|---|
| Nombre en GitHub | `commons-ci-s9k-01` |
| Labels | `self-hosted`, `linux`, `x64` (automáticas) + `commons`, `ci`, `s9-knowledge` |
| Nombre local / usuario | `runner-02` / `runner02` (uid 1002, grupo `docker`, **sin sudo**) |
| HOME | `/home/runner02` (0700) |
| Directorio del runner | `/opt/github-actions/runners/runner-02` (runner02 0750), runner 2.338.0, SHA-256 `af4b794c…` verificado |
| Workdir / caché / estado | `/var/lib/github-actions/{work,cache}/runner-02` (0700), `state/runner-02` (0750) |
| Log de hooks | `/var/log/commons-ci/runner-02-hooks.log` (root:runner02 0660) + entrada en `/etc/logrotate.d/commons-ci` |
| `.env` | idéntico al de runner-01 (`LANG` + `ACTIONS_RUNNER_HOOK_JOB_STARTED/COMPLETED`), root:runner02 0640 |
| Servicio | `github-actions-runner-02.service` (lo crea `runner-admin add` desde la plantilla; `User=runner02`) |
| Hooks / guard | los mismos ficheros de `/opt/github-actions/tools/hooks/` (el hook deriva rutas del usuario `runnerNN`); golden y estado CLEAN/DIRTY propios |
| Concurrencia | 1 job a la vez. `runner-01` (`commons-ci-01`, repo de pruebas) **no se toca** |

### 3.1 Parche de `runner-admin` (nombre y labels)

`runner-admin add` fijaba el nombre en GitHub como `commons-ci-<NN>` y las labels como `commons,ci`.
Para obtener el nombre pedido sin editar a mano ficheros de credenciales se añadieron dos opciones
**opcionales** (sin ellas el comportamiento es el de antes):

- `--name <commons-ci-…>` — nombre en GitHub (validado: `^commons-ci-[a-z0-9-]{1,40}$`);
- `--extra-labels <a,b>` — labels que se **añaden** a `commons,ci` (nunca las sustituyen).

Instalado el 2026-10-22: `/usr/local/bin/runner-admin` sha256 `d335b38e…`; copia previa en
`/opt/github-actions/config/backup/runner-admin.pre-MIGRACION-CI-S9K-20261022153449` (sha256 `cb72c080…`).
El token sigue yendo por stdin → variable de entorno efímera de `config.sh`; nunca por argv ni a disco.

### 3.2 Registro (lo ejecuta el operador)

```bash
gh api -X POST repos/pjclavero/S9-Knowledge/actions/runners/registration-token --jq .token \
  | ssh ciadmin@192.168.1.215 sudo runner-admin add pjclavero/S9-Knowledge runner-02 \
      --allow-public --name commons-ci-s9k-01 --extra-labels s9-knowledge
ssh ciadmin@192.168.1.215 'sudo runner-admin golden runner-02 && sudo runner-admin reconcile runner-02 --apply --confirm runner-02 && sudo runner-admin doctor'
gh api repos/pjclavero/S9-Knowledge/actions/runners --jq '.runners[]|{name,status,labels:[.labels[].name]}'
```

**Orden importante:** el golden se genera con el HOME de runner02 limpio. Las precargas de §5 viven en
`_work/_tool` (entrada de infraestructura que el hook conserva), no en HOME ni en la caché propia.

Retirada: `remove-token` por stdin → `runner-admin remove pjclavero/S9-Knowledge runner-02`.

## 4. Inventario de jobs (17 requeridos)

Duraciones del último run verde de `main` (`284758c`, run CI 39651557176, `ubuntu-24.04`, 4 vCPU/16 GB).
pip-audit: run 38258343199 (último verde; el de `284758c` falla por CVE nuevas que corrige otro carril).
Todos los contextos son requeridos (strict=true, app_id 15368) y hoy todos usan `ubuntu-latest`.

| # orden | job id | `name` (= contexto requerido) | Duración GitHub | Dependencias | Riesgo en VM115 | timeout propuesto |
|---|---|---|---|---|---|---|
| 1 | `check-unicode` | No dangerous Unicode (Trojan Source) | 0,1 min | setup-python 3.13 | bajo (depende de §5.1) | 30 |
| 1 | `check-imports` | No hardcoded absolute paths in sys.path | 0,1 min | solo `grep` | nulo | 30 |
| 2 | `check-ci-config` | Integridad de gates (cobertura de ramas, 0 tests, skips criticos) | 0,2 min | Python + PyYAML | bajo | 30 |
| 2 | `review-ingest-contracts` | Contratos review/ingest v1 (JSON Schema) | 0,2 min | Python, jsonschema | bajo | 30 |
| 2 | `knowledge-v3-contracts` | Contratos internos V3 (v3-internal-v1) | 0,2 min | Python, jsonschema, `git status` | bajo | 30 |
| 3 | `test-data-engine` | Data Engine Tests | 10,8 min | Python, lock data-engine, **Docker** (Neo4j efímero por `docker run --publish 127.0.0.1:…`), `fetch-depth: 0` | medio: RAM (Neo4j heap 256 MB) | 30 |
| 3 | `test-viewer` | Viewer Tests | 5,3 min | Python, viewer, **Docker** (Neo4j efímero) | medio | 30 |
| 3 | `deployment-validation` | Deployment scripts validation | 0,7 min | **shellcheck 0.9.0** (era `sudo apt-get`), yamllint, ansible (pip) | medio: paso con `sudo` (§6) | 15 (ya existe) |
| 3 | `route-map-gate` | Censo de rutas (configuracion canonica en codigo) | 4,2 min | Python, viewer, `git fetch origin main` | bajo | 30 |
| 3 | `metodos-de-escritura` | Metodos de escritura (especificacion independiente del montaje) | 7,8 min | Python, viewer | bajo | 30 |
| 3 | `check-env-reproducibility` | Reproducibilidad de entorno (declarado == instalado) | 0,9 min | Python, lock + viewer | bajo | 30 |
| 4 | `test-graph-js` | Especificacion JS del grafo (Node obligatorio) | 0,4 min | Python, **Node 20** (setup-node, 20.20.2) | bajo | 30 |
| 5 | `test-neo4j-authz` | Authz integration (Neo4j efímero) | 3,9 min | `services: neo4j:5.26.0` (pagecache 128M, puerto 7687 → loopback por `daemon.json`) | medio: RAM | 30 |
| 6 | `test-login-browser` | Login browser contract (Playwright) | 4,8 min | Playwright 1.64.0 + Chromium 156; deps de sistema (era `--with-deps` con `sudo`) | **alto**: RAM 4 GB | 30 |
| 7 | `pip-audit` (supply-chain.yml) | pip-audit (data-engine + viewer) | 0,5 min | Python, pip-audit, red a PyPI/OSV | bajo | 30 |
| 8 | `test-combined` | Combined Test Suite (no collection errors) | 10,4 min | Python, lock + viewer, `fetch-depth: 0`, bootstrap de certificación | medio | 30 |
| 9 | `calibracion-de-gates` | Calibracion de gates (cada violacion tiene que ponerse ROJA) | **150,1 min** | Python, lock + viewer, Node 20, `fetch-depth: 0`; muta y restaura el árbol | alto: duración en 2 vCPU | **360** |

Suma en serie (un solo runner): ≈ 201 min en GitHub; en VM115 (2 vCPU) previsiblemente más. Se mide
por fases; las calibraciones van las últimas y **sin optimizar**.

Orden de migración (un commit por grupo, verificando cada uno antes del siguiente): 1 canario →
2 estáticos/auditoría → 3 Python simple → 4 Node → 5 Neo4j efímero → 6 Playwright (con muestreo de
RAM/CPU; OOM demostrado = STOP, no se sube RAM) → 7 pip-audit → 8 combinada/integridad → 9 calibraciones.

## 5. Preparación de VM115 (2026-10-22)

### 5.1 Python 3.13 para `setup-python` — **BLOQUEADO, pendiente de decisión**

GitHub usó CPython **3.13.16** (`Successfully set up CPython (3.13.16)` en los logs de 39651557176).
`setup-python` no tiene builds para Debian 13 (las de `actions/python-versions` son de Ubuntu), así que el
plan era precargar la build oficial en el toolcache de runner-02
(`/var/lib/github-actions/work/runner-02/_tool/Python/3.13.16/x64` + `x64.complete`), ejecutando su
`setup.sh` como runner02 con `RUNNER_TOOL_CACHE` apuntando ahí.

Resultado medido:

| Build oficial | SHA-256 (digest de la release, verificado) | `import ctypes` como runner02 |
|---|---|---|
| `python-3.13.16-linux-24.04-x64.tar.gz` (release `3.13.16-36805956071`) | `d6f5f504…c872` OK | **SIGSEGV** (`ctypes/__init__.py` l.159); `setup.sh` muere en `ensurepip` |
| `python-3.13.16-linux-22.04-x64.tar.gz` | `1b505e67…91b0` OK | **SIGSEGV** igual |
| Python del sistema Debian 13 (3.13.5) | — | OK |

`ssl`, `sqlite3`, `lzma`, `bz2`, `readline`, `zlib`, `hashlib` importan bien; solo `_ctypes` (enlazado a
`libffi.so.8` del sistema, Debian `libffi8 3.4.8-2`) revienta. La precarga se **retiró** (sin
`x64.complete` no la usaría `setup-python`, pero no se deja residuo): `_work/runner-02` vuelve a estar vacío.

Opciones (decide el organizador; ninguna aplicada):
- (a) compilar CPython 3.13.16 desde el tarball de python.org (SHA verificado) en VM115 con las opciones
  de `actions/python-versions`, e instalarlo en el toolcache con la misma estructura;
- (b) build de `python-build-standalone` 3.13.16 (libffi estático) con SHA verificado;
- (c) diagnosticar el choque con libffi 3.4.8 (p. ej. probar con la libffi de Ubuntu en `LD_LIBRARY_PATH`).

**Consecuencia:** 15 de los 17 jobs usan `setup-python`. Sin esta decisión, el canario solo puede dar verde
en `check-imports`; `check-unicode` fallaría en `Set up Python`.

### 5.2 shellcheck 0.9.0 (versión de `ubuntu-latest`)

`ubuntu-24.04` trae `shellcheck 0.9.0-1` (log del job 119400915508: «shellcheck is already the newest
version (0.9.0-1)»); Debian 13 ofrece 0.10.0-1. La release de koalaman/shellcheck v0.9.0 **no publica
checksums**, así que se usó el **mismo paquete fuente 0.9.0-1** de Debian bookworm, verificado por la
cadena firmada de Debian:

1. `dists/bookworm/InRelease` — `gpgv` contra `/usr/share/keyrings/debian-archive-keyring.gpg`:
   «Good signature from Debian Stable Release Key (12/bookworm)», rc=0;
2. `main/binary-amd64/Packages.xz` — SHA-256 `9e0b5aab…88c5` del InRelease: OK;
3. `shellcheck_0.9.0-1_amd64.deb` — SHA-256 `8c40f8a4…fa4f` del Packages: OK.

Se extrajo solo el binario (sin instalar el .deb de otra versión de Debian) a `/usr/local/bin/shellcheck`
(root 0755, sha256 `59d20b9f…43ce`). Dependencias (`libc6`, `libffi8`, `libgmp10`) presentes; `ldd` sin
ausencias; `shellcheck --version` = 0.9.0 como runner02.

### 5.3 Dependencias de sistema de Playwright 1.64.0

GitHub usó Playwright 1.64.0 (Chrome for Testing 156.0.8078.4). Se instalaron con
`playwright install-deps chromium` (Playwright 1.64.0 en un venv temporal de ciadmin, como root):
**91 paquetes** apt, lista exacta abajo (rc=0, disco 3,7 G → 4,1 G).
Comprobación: Chromium 156.0.8078.4 descargado a un directorio temporal de ciadmin arranca headless y
renderiza una página (`LAUNCH_OK`). Venv y navegador de prueba borrados después.
El navegador del job se sigue descargando en cada ejecución a `~/.cache/ms-playwright` de runner02
(el hook lo borra al terminar: no hay cachés de HOME autorizadas).

<details><summary>91 paquetes instalados</summary>

`at-spi2-common` `fontconfig` `fontconfig-config` `fonts-freefont-ttf` `fonts-ipafont-gothic` `fonts-liberation` `fonts-noto-color-emoji` `fonts-tlwg-loma-otf` `fonts-unifont` `fonts-wqy-zenhei` `libasound2-data` `libasound2t64` `libatk-bridge2.0-0t64` `libatk1.0-0t64` `libatspi2.0-0t64` `libavahi-client3` `libavahi-common-data` `libavahi-common3` `libcairo2` `libcups2t64` `libdatrie1` `libdrm-amdgpu1` `libdrm-common` `libdrm-intel1` `libdrm2` `libfontconfig1` `libfontenc1` `libfribidi0` `libgbm1` `libgl1` `libgl1-mesa-dri` `libglvnd0` `libglx-mesa0` `libglx0` `libgraphite2-3` `libharfbuzz0b` `libice6` `libllvm19` `libnspr4` `libnss3` `libpango-1.0-0` `libpciaccess0` `libpixman-1-0` `libsensors-config` `libsensors5` `libsm6` `libthai-data` `libthai0` `libunwind8` `libvulkan1` `libwayland-server0` `libx11-6` `libx11-data` `libx11-xcb1` `libxau6` `libxaw7` `libxcb-dri3-0` `libxcb-glx0` `libxcb-present0` `libxcb-randr0` `libxcb-render0` `libxcb-shm0` `libxcb-sync1` `libxcb-xfixes0` `libxcb1` `libxcomposite1` `libxdamage1` `libxdmcp6` `libxext6` `libxfixes3` `libxfont2` `libxi6` `libxkbcommon0` `libxkbfile1` `libxmu6` `libxpm4` `libxrandr2` `libxrender1` `libxshmfence1` `libxt6t64` `libxxf86vm1` `libz3-4` `mesa-libgallium` `x11-common` `x11-xkb-utils` `xfonts-encodings` `xfonts-scalable` `xfonts-utils` `xkb-data` `xserver-common` `xvfb`

</details>

### 5.4 Node

`setup-node@v4` descarga `node-20.20.2-linux-x64.tar.gz` de `actions/node-versions` (binario genérico de
Linux, sin filtro de distribución): no necesita precarga. Queda en `_work/_tool`, que el hook conserva.

## 6. Pasos con `sudo` (fase 2, no incluidos en el canario)

`runner02` no tiene sudo y la unidad lleva `NoNewPrivileges=yes`. Cambios previstos, compatibles con
ambos runners:

- `deployment-validation`: `sudo apt-get update -qq; sudo apt-get install -y shellcheck` →
  `command -v shellcheck >/dev/null || { sudo apt-get update -qq && sudo apt-get install -y shellcheck; }`
  (en VM115 encuentra el 0.9.0 de §5.2; en GitHub instala como hoy).
- `test-login-browser`: `python -m playwright install --with-deps chromium` → `python -m playwright install chromium`
  (deps ya en VM115, §5.3). El ancla `playwright install` de `check_ci_config.py`/`check_env_reproducibility.py`
  se conserva.

Resultado PRE-PUSH de estos dos cambios: §7.

## 7. PRE-PUSH (calibradores que vigilan `ci.yml`)

Calibradores localizados por `grep` (leen `ci.yml`/`supply-chain.yml`): `.github/scripts/check_ci_config.py`,
`check_suite_inventory.py` (+ `bootstrap_certificacion.py`), `check_env_reproducibility*.py`,
`calibra_*.py`, `check_ejecucion_real.py`, `registro_xfail.py`, `normaliza_shell.py`, `estado_de_fabrica.py`,
`scripts/calibracion/mutaciones_calidad_datos.py`, `scripts/check_docs_consistency.py`.
Ejecutados en ia-server con un venv Python 3.13.5 (lock de data-engine + viewer + PyYAML + jsonschema),
**después de commitear** (los arneses mutan y restauran el árbol). En todas las filas el árbol quedó limpio
(`git status --porcelain` = 0) y el HEAD intacto.

### 7.1 Canario (`9024e98`: `check-unicode` y `check-imports` → self-hosted + `timeout-minutes: 30`)

| Calibrador | rc | Duración |
|---|---|---|
| `check_ci_config.py` | 0 | 2 s |
| `check_env_reproducibility_calibration.py` | 0 | 40 s |
| `scripts/check_docs_consistency.py` | 0 | 4 s |
| `calibra_gate_integrity.py` | 0 | 59 s |
| `check_suite_inventory.py` vía bootstrap desde el objeto Git (como en `test-combined`) | 0 | 53 s |
| `check_suite_inventory.py --escribir-inventario` + `git diff --quiet` del inventario | 0 | 35 s |
| `calibra_suite_inventory.py` | 0 | 37 min |
| `calibra_desarme.py` | **1** (ver abajo) | 9 min |
| `calibra_registro_xfail.py` | 0 | 10 min |
| `calibra_ejecucion_real.py` | 0 | 52 min |
| `calibra_a2_linaje.py` | 0 | 6 min |
| `calibra_base_materializada.py` | 0 | 3 min |
| `scripts/calibracion/mutaciones_calidad_datos.py` | 0 | 49 s |

**`calibra_desarme.py` rc=1 es del entorno local, no del cambio.** Control A/B: el mismo arnés sobre la
base intacta `284758c` da también rc=1 con **las mismas 7 desviaciones**, fila por fila (`diff` vacío). Todas
son de la familia «`usercustomize` EXTERNO» y `-s`, que en un venv no se pueden ejercer (el venv desactiva el
*user site*). La fila que compara la construcción de `ci.yml` (`M0 el arnes mide la MISMA construccion que
ci.yml`) sale **OK**. En CI corre con el Python de `setup-python`, no en un venv.

Tras integrar `origin/main` (`4eb442a`, fix de pip-audit, merge `02c3f3b`, sin conflictos; solo cambia
`data-engine/requirements.lock`) se repitieron los rápidos sobre el HEAD final: ver §7.3.

### 7.2 Pasos sin `sudo` de §6 (rama local temporal, **no** incluidos en el canario)

| Calibrador | rc |
|---|---|
| `check_ci_config.py` | 0 |
| `check_env_reproducibility_calibration.py` | 0 |
| `scripts/check_docs_consistency.py` | 0 |
| `calibra_gate_integrity.py` | 0 |
| `check_suite_inventory.py` vía bootstrap | 0 |
| `check_suite_inventory.py --escribir-inventario` + diff | 0 |
| `check_env_reproducibility.py runtimes --require chromium` | 1 — esperado: en ia-server no hay Playwright instalado; es el gate de tiempo de ejecución funcionando, no un ancla sobre `ci.yml` |

Ningún calibrador exige la línea literal `--with-deps` ni `sudo apt-get`: el ancla de
`check_ci_config.py` / `check_env_reproducibility.py` es la subcadena `playwright install`, y la única aparición
literal de `--with-deps chromium` está en el `ci.yml` **sintético** de `check_env_reproducibility_calibration.py`.

### 7.3 HEAD final de la rama

Medido sobre `4e85451` (canario + merge de `4eb442a` + este documento); el commit siguiente solo
rellena esta tabla.

| Calibrador | rc |
|---|---|
| `check_ci_config.py` | 0 |
| `check_unicode.py` | 0 |
| `scripts/check_docs_consistency.py` | 0 |
| `check_env_reproducibility_calibration.py` | 0 |
| `calibra_gate_integrity.py` | 0 |
| `check_suite_inventory.py` vía bootstrap | 0 |
| `check_suite_inventory.py --escribir-inventario` + diff | 0 |

Los arneses largos (§7.1) no se repitieron tras el merge: `4eb442a` solo toca `data-engine/requirements.lock`.

## 8. Anti-fork: guard del hook ejecutado como `runner02`

14 payloads fabricados (sin atacante real, sin ejecutar código externo: el modo `guard` solo parsea JSON),
en `/var/tmp/mig-ci-guard/` de VM115 (root 0644), evaluados con
`sudo -u runner02 env -i … python3 -I /opt/github-actions/tools/hooks/commons_ci_hook.py guard EVENTO PAYLOAD pjclavero/S9-Knowledge`
(repo esperado por argv porque el runner aún no está registrado). Resultado: **14/14 con la decisión
esperada, FALLOS=0, rc=0**.

| Caso | Evento | Decisión (rc) |
|---|---|---|
| 01 push a rama propia | push | PERMITIDO (0) |
| 02 push de tag | push | RECHAZADO (21) |
| 03 dispatch de rama | workflow_dispatch | PERMITIDO (0) |
| 04 schedule | schedule | PERMITIDO (0) |
| 05 PR de rama interna | pull_request | PERMITIDO (0) |
| 06 PR desde fork | pull_request | RECHAZADO (21) |
| 07 PR con `head.repo.fork=true` | pull_request | RECHAZADO (21) |
| 08 PR con `head.repo` nulo | pull_request | RECHAZADO (21) |
| 09 `pull_request_target` desde fork | pull_request_target | RECHAZADO (21) |
| 10 `workflow_run` | workflow_run | RECHAZADO (21) |
| 11 `issue_comment` | issue_comment | RECHAZADO (21) |
| 12 push de otro repo | push | RECHAZADO (21) |
| 13 push con `pull_request` falsificado | push | RECHAZADO (21) |
| 14 `merge_group` | merge_group | RECHAZADO (21) |

Tras el registro se repite **sin** el repo en argv (el hook lo lee del `.runner` de runner-02):
`bash /var/tmp/mig-ci-guard/run_guard.sh registrado`, y se comprueba con un `push` real de la rama
(permitido, pre y post CLEAN en el log del job).

## 9. Pendiente / techo

- Registro del runner (operador), golden + reconcile de runner-02.
- Decisión sobre Python (§5.1): bloquea 15 jobs.
- Fases 1-9 sin ejecutar: sin duraciones, RAM ni residuos medidos en VM115.
- Anti-fork con `.runner` real y con eventos reales del repo: pendiente del registro.
- PR desde un fork **real**: no probado (necesitaría otra cuenta de GitHub), igual que en commons-ci.md §18.2.
