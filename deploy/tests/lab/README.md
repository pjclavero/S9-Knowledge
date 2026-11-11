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
| 4 | `40_escenario_C_negativo.sh` | **C · NEGATIVO** (chown/chmod, movimiento, retiro, conflicto forzados): STOP, sin éxito falso, estado preservado, convergencia | N11, N12, N5, N6 |

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

Estado: **escritos y revisados con `bash -n` y `shellcheck`; NO EJECUTADOS** (VM112
apagada en la fecha de esta entrega).
