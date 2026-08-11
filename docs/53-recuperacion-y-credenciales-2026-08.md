# 53 — Recuperación y credenciales de VM105 (2026-08-08)

Dos operaciones ejecutadas en producción el **2026-08-08** que hasta ahora no
tenían constancia escrita en el repositorio: la **rotación de la credencial de
Neo4j** y un **restore real de VM105 desde `vzdump`** en el hipervisor.

Este documento registra **lo que se hizo y lo que quedó demostrado**, y —con el
mismo cuidado— **lo que no**. Un ensayo de recuperación que se cuenta de más es
peor que no haberlo hecho: crea confianza sin respaldo.

> **Ningún valor de credencial aparece aquí, ni en ningún otro fichero del
> repositorio.** Se documenta el hecho y el procedimiento, nunca el secreto.

---

## 1. Rotación de la credencial de Neo4j

**Estado: VERIFICADO.**

### Qué se hizo

| Paso | Detalle |
|---|---|
| 1 | Cambio de contraseña **en la propia base** Neo4j. |
| 2 | Actualización del **fichero de secreto**, conservando dueño y permisos. |
| 3 | Sincronización de `NEO4J_AUTH` con el nuevo valor. |
| 4 | **Reinicio del visor** para que tomara la credencial nueva. |

### Qué quedó demostrado

- **La credencial nueva autentica.**
- **La credencial anterior NO autentica.** Éste es el punto que convierte la
  operación en una rotación y no en un simple cambio de fichero: se comprobaron
  ambos sentidos, no solo el feliz.
- **El grafo quedó intacto**: 199 nodos / 140 relaciones antes y después.

### Higiene aplicada

El valor de la credencial **nunca pasó por el contexto del agente**. No se
transcribió, no se imprimió y no se versiona. Conservar los permisos y el dueño
del fichero de secreto es parte del procedimiento, no un detalle: un secreto
legible por más usuarios de la cuenta es una rotación a medias.

### Qué NO cubre esta rotación

- No se rotaron otras credenciales del sistema (visor, `auth.db`, proveedores
  externos). El alcance fue **exclusivamente Neo4j**.
- No se comprobó que la credencial restaurada dentro de una copia de seguridad
  siga siendo funcional (ver §2, «lo no verificado»).

---

## 2. Restore real de VM105 desde `vzdump`

**Estado: VERIFICADO, con límites explícitos.**

Este ensayo es **distinto** del restore en contenedor aislado descrito en
[`docs/52-backup-manual-checkpoint.md`](52-backup-manual-checkpoint.md) §101-106.
Aquél restauraba **el dump de Neo4j** en un contenedor; éste restaura **la
máquina virtual completa** desde la copia `vzdump` del hipervisor.

### Condiciones del ensayo

| Parámetro | Valor | Por qué importa |
|---|---|---|
| Copia de origen | `vzdump` del **2026-08-02** | Fija la antigüedad real del punto de recuperación probado. |
| Destino | **VMID de prueba `900`** | Nunca se restauró sobre la VM productiva. |
| Red | **sin NIC** — dentro solo existe `lo` | Impide que la clonada hable con la red o se confunda con producción. |
| Arranque automático | `onboot=0` | No reaparece tras un reinicio del hipervisor. |
| Almacenamiento | destino **distinto de `local-lvm`** | No compite por el espacio de producción. |

### Resultados

| Comprobación | Resultado |
|---|---|
| Integridad del archivo `zstd` | **OK** |
| Restore completo (70 GiB) | **8,2 min** |
| `e2fsck` del sistema de ficheros | **limpio** |
| Arranque con guest agent | **23 s** |
| `auth.db` | `integrity_check = ok` |
| Store de Neo4j | **presente y completo** |

### Cierre

Entorno de prueba **destruido y verificado**, espacio liberado, **producción
intacta**.

### Lo que este ensayo NO verificó

Dos límites, y conviene que no se pierdan al citar el resultado:

1. **El contenido semántico del grafo.** Se comprobó que el store de Neo4j
   **está presente y es íntegro como fichero**. No se abrió la base ni se
   contaron nodos y relaciones dentro de la VM restaurada. «El store está» no
   es «los datos son correctos».
2. **La validez funcional de los secretos restaurados.** Que `auth.db` pase
   `integrity_check` dice que el fichero no está corrupto; no dice que sus
   credenciales sirvan para iniciar sesión. Y la copia es del **2026-08-02**,
   anterior a la rotación de §1: la credencial de Neo4j que contiene es, por
   construcción, **la antigua** — es decir, la que ya no autentica.

### 8,2 min es el RTO de la fase de restore, no el RTO hasta servicio

El número mide **copiar y desempaquetar 70 GiB**. No incluye decidir que hay que
recuperar, localizar la copia, reconfigurar red e identidad, arrancar los
servicios, comprobar que responden y devolver el tráfico. **El RTO hasta
servicio sigue SIN MEDIR.** Citar 8,2 min como «tiempo de recuperación» sería
exactamente el tipo de error que este ensayo sirve para evitar.

### La copia sigue viviendo en el mismo chasis

El `vzdump` restaurado reside en el **mismo servidor físico** que la VM que
protege. Protege frente a error lógico, borrado accidental o actualización
fallida. **No protege frente a la pérdida del chasis**, del almacenamiento o del
emplazamiento.

> **Una copia en el hipervisor que ejecuta la VM no es una copia off-host.**
> Es la misma caja. El P0 de replicación a un soporte independiente
> [sigue abierto](52-backup-manual-checkpoint.md) y este ensayo no lo cierra.

---

## 3. Qué cambia y qué no cambia en el estado de recuperación

| Antes de 2026-08-08 | Después |
|---|---|
| Restore de VM105 **nunca ejecutado** | Restore de VM **ejecutado y medido** sobre VMID de prueba |
| Tiempo de restore desconocido | Fase de restore medida: **8,2 min / 70 GiB** |
| Integridad de la copia sin comprobar | `zstd` OK, `e2fsck` limpio, `auth.db` íntegro |
| Sin copia off-host | **Sigue sin copia off-host** (P0 abierto, `RK-14`) |
| RTO hasta servicio sin medir | **Sigue sin medir** |
| Contenido del grafo restaurado sin validar | **Sigue sin validar** |
| Credencial de Neo4j sin rotar constancia | **Rotada y verificada en ambos sentidos** |

## 4. Vocabulario

Este documento usa el esquema de prioridades ya vigente en el repositorio
(**P0/P1** en `docs/52` y `RK-*` en
[`docs/coordination/risk-register.md`](coordination/risk-register.md)). No se
introduce ninguna nomenclatura nueva de identificadores de copia: si en alguna
conversación se han usado etiquetas del tipo `BKP-n`, **no pertenecen al
repositorio** y no deben citarse aquí como si fueran conocidas.

## 5. Pendiente

- **P0 (`RK-14`)**: replicar al menos una copia verificada **fuera del chasis**.
- **`RK-18`**: medir el **RTO hasta servicio**, no solo la fase de restore.
- Validar el **contenido** de un grafo restaurado (conteos y muestreo), no solo
  la presencia del store.
- Reverificar por SSH de solo lectura el estado del healthcheck de VM105, hoy
  marcado `PENDING_VERIFICATION` en
  [`docs/project-status.yaml`](project-status.yaml).
