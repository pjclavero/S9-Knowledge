# Guiones de laboratorio de H-06 + H-08 (VM112)

Estos guiones ejercen lo que **no puede** ejercer el arnés local: `useradd`, `chown`
a `s9knowledge`, `runuser`, systemd real y **otro usuario local** leyendo. Se
ejecutan **solo en el laboratorio** (VM112); la máquina de orquestación (`ia-server`)
y producción están prohibidas por `lib_lab.sh::lab_guard`, que además **PARA** si no
hay `sudo` sin contraseña, `systemd` o `runuser`, o si falta
`S9K_LAB_CONFIRMADO=VM112`.

Sin secretos ni IPs en el repositorio: los secretos de laboratorio se generan en la
VM (`/dev/urandom`), nunca en argv.

| Orden | Guion | Qué hace | P/N que cubre |
|---|---|---|---|
| 0 | `00_preparar.sh <origen>` | clon por SHA + venv de pruebas bajo `S9K_LAB_BASE` (no toca `~diana` ni otros carriles); toma `flock /srv/s9-test/heavy.lock` | — |
| 1 | `10_serie_pesada.sh` | tests específicos → calibrador H-06/H-08 → calibradores afectados → suites completas, **en serie y con `PYTEST_RC` real** | §23 |
| 2 | `20_escenario_A_fresh.sh` | **A · FRESH** (máquina limpia) | P1–P8, P11, N10, N15, N16 |
| 3 | `30_escenario_B_upgrade_legacy.sh` | **B · UPGRADE LEGACY** (root, 0644/0660, estado en la release, unidades antiguas reales) + idempotencia | P9, P10, P12, N5, N6 |
| 4 | `40_escenario_C_negativo.sh` | **C · NEGATIVO** (chown/chmod, movimiento, retiro, conflicto forzados): STOP, sin éxito falso, estado preservado, convergencia. Ronda 2: C5–C7 precondiciones del disco en 2b (backups en el state, `S9K_BACKUP_ROOT` dentro, entrada ajena: PARA sin llegar al paso 3b ni tocar el estado), C8 symlink legacy y C9 legacy duplicado (STOP en 5b sin mover nada), C10 rollback automático a una release con unidades anteriores a H-06 (NO se reactiva; servicios PARADOS). `S9K_LAB_C_SOLO_R2=1` corre solo los de la ronda 2 | N11, N12, N5, N6; C-1…C-5 |
| 5 | `50_escenario_H_boveda.sh` | **H · BÓVEDA**: caso 1 propio (conserva modo/grupo), caso 2 no escribible (409, intacto), caso 3 de OTRO dueño real `s9test:s9knowledge 0664` en carpeta `2775` (en el sitio: mismo inodo/dueño/grupo/modo), caso 3b sin respaldo posible (409, intacto) | fase 2b §12; H-2 |
| 6 | `60_escenario_DEF.sh` | **D** otro usuario real y `nobody` (R10 por efecto en una copia; R12 con `setfacl` o techo) · **E** healthcheck real (`state_validation`; drop-in con la excepción de tests → `verificar_entorno_efectivo` rc≠0 y UNHEALTHY, C-6) · **F** CLIs como ROOT REAL (auth, health, glossary, jobs: rc 4, nada de root en el estado) y por `s9k-cli.sh` (0700/0600 de `s9knowledge`) | N10, N15, N16; H-1, C-6, R10, R12 |

```bash
export S9K_LAB_CONFIRMADO=VM112 S9K_LAB_SHA=<sha-del-commit-a-probar>
deploy/tests/lab/00_preparar.sh <url-o-ruta-del-repo>
deploy/tests/lab/10_serie_pesada.sh            # horas: calibradores en serie
deploy/tests/lab/20_escenario_A_fresh.sh       # parte de una máquina limpia (snapshot)
deploy/tests/lab/30_escenario_B_upgrade_legacy.sh
deploy/tests/lab/40_escenario_C_negativo.sh
```

Reglas: un calibrador nunca corre a la vez que otro ni mientras se modifica el árbol;
el clon de laboratorio debe estar **limpio** (los calibradores restauran sobre el
fichero); **no se despliega en VM105 ni en producción**; el resultado se entrega con
el SHA, el `PYTEST_RC` y los logs de `S9K_LAB_BASE/logs`.

Estado: **ejecutados en VM112** (ronda 1: A, B, C1–C4, H; ronda 2: A, B, C completo con
C5–C10, D/E/F y H con el caso 3). El resultado de cada tanda (SHA, `PYTEST_RC`/rc real) queda
en `S9K_LAB_LOGS/rc.tsv`; lo que crean se registra en `CREADO.txt` y lo deshace `99_limpiar.sh`.
