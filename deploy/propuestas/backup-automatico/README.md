# Propuesta: backup automático diario (NO ACTIVADA)

Propuesta de automatización de copias tras el backup manual de emergencia
(`docs/52-backup-manual-checkpoint.md`). **Nada de esto está instalado ni
activo en producción.** Su activación está gateada a la revisión de la copia
manual por el operador y a superar la puerta del final de este documento.

## Por qué existe

El healthcheck ya detectaba la ausencia de copias frescas y lo señalaba cada
hora, pero el servicio quedaba en `failed` sin que nadie observara ese estado.
Producción llegó a acumular ~3 semanas sin copia. La automatización cierra la
generación; la observación del fallo es un problema distinto y se aborda en la
sección de alertas.

## Piezas

| Fichero | Qué es |
|---|---|
| `s9-knowledge-backup.service` | Unidad de tipo `oneshot` que ejecuta el script |
| `s9-knowledge-backup.timer` | Disparo diario con `Persistent=true` |
| `backup.sh` | El script: preflight, copia, manifiesto, publicación atómica, retención |

## Decisiones de diseño

**Independiente de Nextcloud.** El backup automático nunca debe depender de que
la sincronización externa esté disponible: primero genera una copia local
consistente y la publica. La replicación fuera del host es una segunda etapa
independiente que puede fallar sin invalidar la copia local. Esto es
deliberado: ya hubo un acoplamiento parecido que arrastró un servicio a un
bucle de reintentos cuando el almacenamiento externo cayó.

**Publicación atómica.** Se construye en `.tmp-<id>` y se renombra al destino
final solo si todos los pasos terminan bien. Un fallo a medias no puede dejar
un directorio que *parezca* un backup válido — que es justo lo que engañaría al
chequeo de antigüedad.

**Lock anti-solapamiento.** `flock` sobre un fichero en el propio destino. Dos
copias simultáneas competirían por el mismo espacio y podrían publicar estados
inconsistentes.

**SQLite con `.backup`, nunca `cp`.** Copiar un fichero SQLite abierto puede
capturar una escritura a medias. Además, un `-shm`/`-wal` copiado junto al
fichero rejuvenece artificialmente un backup rancio: el error clásico que este
mismo proyecto ya documentó.

**Neo4j: exportación lógica mientras la edición sea community.** El backup en
caliente es de Enterprise. Si en el futuro se autoriza una ventana de parada, se
añade un modo de dump físico; hasta entonces, la exportación lógica es lo único
consistente que no requiere detener la base.

## Retención

Propuesta inicial: **7 diarias, 4 semanales, 3 mensuales**. La retención se
aplica *después* de publicar la copia nueva y verificar su manifiesto: nunca se
borra una copia antigua antes de tener una nueva válida.

## Alertas

Dos condiciones distintas, y conviene no confundirlas:

1. **Fallo de ejecución** — `OnFailure=` en la unidad, hacia un servicio de
   notificación.
2. **Backup demasiado antiguo** — ya lo cubre el healthcheck existente
   (`BACKUP_WARN_AGE_HOURS = 26`, `BACKUP_MAX_AGE_HOURS = 48`). Es la red que
   detecta que el timer dejó de funcionar en silencio.

La segunda es la importante: un timer que se desactiva no genera ningún fallo,
solo deja de haber copias. Por eso la alerta por antigüedad no debe depender
del propio timer de backup.

## Prueba periódica de restauración

Sin restauración probada, un backup es una suposición. Se propone una
verificación semanal que restaure la copia más reciente en un directorio
aislado y compruebe integridad y conteos, **nunca** contra rutas productivas.

## Puerta antes de activar en producción

La activación no se propone hasta que todo esto esté demostrado:

- [x] Backup manual correcto — `manual-20260806-181324`
- [x] Restauración aislada correcta — integridad `ok`, conteos idénticos a producción
- [ ] Segunda ejecución idempotente
- [~] Retención: **lógica probada en aislamiento** (`deploy/tests/test_backup_retencion_propuesta.py`,
      9 tests: conserva siempre la más reciente aunque las cuotas sean cero, ignora
      temporales y copias sin manifiesto, cuotas que se solapan sin duplicar, y nunca
      toca un directorio con nombre no reconocido). **Falta** probarla de extremo a
      extremo contra copias reales acumuladas.
- [ ] Fallo parcial probado (que no publica un backup incompleto)
- [ ] Espacio insuficiente probado (que falla limpio y alerta, sin dejar basura)
- [ ] Lock probado (dos ejecuciones simultáneas)
- [ ] Alerta probada (fallo y antigüedad)
- [ ] Supervisor: CONFORME

Los cinco puntos no marcados requieren un entorno de pruebas: **no deben
ensayarse contra producción**, porque probar «espacio insuficiente» y «fallo
parcial» implica provocar fallos en la máquina que guarda los datos.
