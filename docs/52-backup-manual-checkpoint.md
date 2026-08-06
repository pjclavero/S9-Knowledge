# Checkpoint — backup manual de producción (2026-08-06)

Copia de emergencia creada tras detectar que producción llevaba ~3 semanas sin
copia fresca. El healthcheck horario lo venía señalando —`backups: backup
válido pero rancio`— con el servicio en `failed`, pero nadie observaba ese
estado.

Autorizado por el operador con alcance limitado: la copia solo puede escribir
en el destino de backups; sin reinicios, paradas, migraciones, compactaciones,
cambios de flags, limpiezas ni escrituras en Neo4j.

## Identificación

| Campo | Valor |
|---|---|
| `BACKUP_ID` | `manual-20260806-181324` |
| Inicio / fin (UTC) | 2026-08-06T18:13:24Z / 2026-08-06T18:13:47Z |
| Host | `common` (máquina de servicios comunes) |
| Usuario efectivo | `root` |
| Commit desplegado | `47bc3147fdab6b642ab72ffe0cf84133e3a57b2e` (RC5.1) |
| Release | `deploy--20260718-133409` |
| Neo4j | 5.26.0, edición **community** |
| SQLite | 3.46.1 |
| Destino | `/var/lib/s9-knowledge/backups/manual-20260806-181324` |
| Tamaño | 284 KiB (17 ficheros) |

## Método, y por qué

| Origen | Método | Motivo |
|---|---|---|
| `auth.db` | `sqlite3 .backup` | Copia consistente en caliente. Nunca `cp` de un fichero abierto: podría capturar una escritura a medias. |
| `jobs.db` | `sqlite3 .backup` | Igual. |
| Neo4j | **Exportación lógica** en solo lectura vía `cypher-shell` | El backup en caliente (`neo4j-admin database backup`) es exclusivo de la edición Enterprise; APOC no está instalado (0 procedimientos `apoc.export`); y `neo4j-admin database dump` **exige la base detenida**. Detener el servicio no estaba autorizado en este paso. |
| Configuración | Copia con **valores redactados** | Se conservan los nombres de clave para poder reconstruir la configuración, nunca los valores. |
| Unidades systemd | `systemctl cat` | Necesarias para restaurar el servicio. |

## Contenido

```
MANIFEST.sha256          17 entradas: hash, tamaño y fecha de cada fichero
sqlite/auth.db           usuarios, sesiones, auditoría
sqlite/jobs.db           cola de trabajos
neo4j/nodos.txt          199 nodos con etiquetas y propiedades
neo4j/relaciones.txt     140 relaciones con extremos, tipo y propiedades
neo4j/indexes.txt        índices declarados
neo4j/constraints.txt    vacío — verificado: la base no tiene ninguna restricción
neo4j/conteo-*.txt       conteos de control
meta/despliegue.txt      release, commit, versiones, host, kernel
meta/*-schema.sql        esquema de ambas bases SQLite
meta/auth-tablas.txt     tablas presentes (incluye schema_version)
meta/auth-user-version.txt  estado de migraciones (user_version = 0)
meta/viewer.service, healthcheck.{service,timer}
meta/viewer.env.claves   nombres de clave con valores redactados
```

## Validación

No basta con que el comando termine en cero. Se comprobó:

| Comprobación | Resultado |
|---|---|
| Manifiesto | **17/17 ficheros OK**, sin discrepancias, recuento coincidente |
| `PRAGMA integrity_check` en ambas copias | `ok` |
| `PRAGMA foreign_key_check` en `auth.db` | sin violaciones |
| Restauración de ensayo | En directorio **aislado**, nunca contra rutas productivas |
| Datos tras la restauración | 1 usuario, 21 sesiones, 65 eventos de auditoría |
| Contraste con producción | Cifras **idénticas** (lectura en modo solo lectura) |
| Neo4j | 199 nodos / 140 relaciones, coincide con producción |
| Ficheros vacíos | Solo `constraints.txt`, y se verificó que la base realmente no tiene restricciones |
| Secretos en el backup | Ninguno: búsqueda de patrones de contraseña, token y clave sin resultados |

## Dump físico — `manual-dump-20260806-190625`

Segundo `BACKUP_ID`, **enlazado** al lógico anterior en vez de modificar su
manifiesto ya verificado. Obtenido en una ventana de parada autorizada.

| Campo | Valor |
|---|---|
| Método | `neo4j-admin database dump`, binario de la misma versión desplegada |
| Bases volcadas | `neo4j` (36 ficheros, 1,700 MiB) y `system` (41 ficheros, 1,150 MiB) |
| Tamaño | `neo4j.dump` 134 448 B, `system.dump` 11 202 B |
| Herramienta | 5.26.0 |
| Ventana | 19:06:52 → 19:08:56 UTC (~2 min de los 10 autorizados) |
| Código de salida | 0 en ambos volcados |

Secuencia: preflight (sin trabajos en cola, sin worker activo, ambas bases
`online`) → parada limpia → confirmación de detención (`false exited`) → volcado
→ **arranque inmediato** → validación.

### Validación tras reanudar

| Comprobación | Resultado |
|---|---|
| Contenedor | `healthy` |
| Nodos / relaciones | **199 / 140**, idénticos a antes de la parada |
| Bases | `neo4j` y `system` `online` |
| Visor | `active`, PID 740, `NRestarts=0` (no se reinició) |
| Errores nuevos en registros | Ninguno |
| Healthcheck | **Recuperado**: `Result=success` con código 1 (degradado por Ollama y Nextcloud no configurados, que la unidad acepta), frente al código 2 anterior |

### Restauración de ensayo del dump

En contenedor aislado con nombre propio, datos propios y **sin publicar
puertos**; ninguna conexión a producción. Resultado: **199 nodos, 140
relaciones**, con etiquetas, tipos de relación, propiedades e índices correctos.
El contenedor se eliminó y el backup quedó intacto.

> **Detalle imprescindible del procedimiento de restauración.** El primer
> intento restauró una base **vacía**. Causa: al publicar, el backup recibe
> `chmod -R go-rwx`, y el usuario `neo4j` del contenedor (uid 7474) no puede
> leer los `.dump`; `neo4j-admin` respondía `Failed to list archive files` y aun
> así el contenedor arrancaba —vacío— sin error visible. **Quien restaure debe
> copiar antes los `.dump` a un área legible por ese usuario.** Este fallo es
> silencioso: sin comprobar los conteos, una restauración vacía parece
> correcta.

## Limitaciones — leer antes de confiar en esta copia

1. **BACKUP LOCAL SIN COPIA OFF-HOST.** La máquina tiene un único disco
   (`/dev/sda1`, 9,8 GiB libres) y el destino está en ese mismo disco. Protege
   frente a error lógico, borrado accidental o migración fallida; **no** protege
   frente a pérdida del host o del almacenamiento. La replicación fuera del host
   es una etapa posterior e independiente.
2. ~~Neo4j es solo exportación lógica.~~ **Resuelto**: existe además el dump
   físico `manual-dump-20260806-190625`, con restauración verificada. Se
   conservan **ambos**: la exportación lógica es legible e inspeccionable sin
   herramientas; el dump físico restaura con fidelidad y no depende de que el
   procedimiento de reconstrucción recuerde metadatos internos.
3. **RPO estimado**: el estado capturado es el del momento de la copia. Sin
   automatización, cualquier cambio posterior queda fuera. Antes de esta copia
   el RPO real era de ~20 días.
4. Las dos consultas de Neo4j (nodos y relaciones) se ejecutan por separado. Con
   el sistema en reposo y sin ingesta activa la instantánea es coherente, pero no
   es una transacción única.

## Estado del healthcheck

Con esta copia, el componente `backups` debería volver a OK en la siguiente
ejecución horaria, y con él el estado global. El resto de componentes ya estaba
correcto: visor, Neo4j, cola de trabajos, auth.db, sistema de ficheros (68,6 %
de uso) y unidades de systemd. Ollama y la sincronización de Nextcloud figuran
como «no configurado», que es lo esperado porque no se usan.

## Pendiente

- **P0 restante: replicar al menos una copia verificada a otro host o soporte
  físico independiente.** Mientras no exista, todo lo anterior sigue viviendo en
  el mismo disco que los datos.
- Automatización: propuesta en `deploy/propuestas/backup-automatico/`, **sin
  activar**. Su puerta exige, además de lo ya cumplido, ensayar en entorno
  aislado los fallos destructivos (espacio insuficiente, fallo parcial, lock,
  publicación interrumpida) y una segunda ejecución idempotente.
