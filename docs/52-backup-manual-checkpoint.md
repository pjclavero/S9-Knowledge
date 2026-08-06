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

## Limitaciones — leer antes de confiar en esta copia

1. **BACKUP LOCAL SIN COPIA OFF-HOST.** La máquina tiene un único disco
   (`/dev/sda1`, 9,8 GiB libres) y el destino está en ese mismo disco. Protege
   frente a error lógico, borrado accidental o migración fallida; **no** protege
   frente a pérdida del host o del almacenamiento. La replicación fuera del host
   es una etapa posterior e independiente.
2. **Neo4j es una exportación lógica, no un dump físico.** Restaurarla implica
   recrear nodos y relaciones, no reponer el almacén. Es suficiente para este
   volumen (199/140) pero no equivale a una restauración binaria. Un dump físico
   consistente exige detener la base: requiere autorización específica para esa
   ventana de parada.
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

- Automatización: propuesta en `deploy/propuestas/backup-automatico/`, **sin
  activar**. Su activación está gateada a la revisión de esta copia manual.
- Replicación fuera del host.
- Dump físico de Neo4j, si se autoriza una ventana de parada.
