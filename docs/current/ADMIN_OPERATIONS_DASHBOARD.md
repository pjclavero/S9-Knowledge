# Centro de Estado (Admin Operations Dashboard) — Carril B

Rama: `feat/admin-operations-dashboard`. Solo observación, nunca control.

## Problema

El estado real de S9 Knowledge está repartido: un informe de health en disco,
una cola de jobs en SQLite, una bandeja de revisión en JSONL, la base de auth,
y unas copias de seguridad de las que el visor no sabe nada. Cuando algo se
tuerce, nadie tiene una pantalla que diga a la vez qué se sabe y —sobre todo—
**qué no se sabe**. El repetido error histórico del proyecto ha sido tratar
"no tengo el dato" como "está bien".

## Solución

Un panel de admin de **solo lectura** que agrega seis secciones y las traduce a
cuatro estados: `OK`, `WARNING`, `CRITICAL`, `UNKNOWN`.

`UNKNOWN` tiene severidad **1**, estrictamente mayor que `OK` (0). Una sección
sin fuente de datos nunca puede pintar verde ni desaparecer del estado global
(`app/ops/models.py::SEVERITY`).

| Sección | Fuente reutilizada | UNKNOWN cuando |
|---|---|---|
| Aplicación | `app.health.storage.load_last()` + `S9K_APP_VERSION`/`S9K_GIT_COMMIT` (o `S9K_OPS_RELEASE_PATH`) | no hay informe, JSON corrupto, timestamp inválido, versión/commit no declarados |
| Datos | `app.deps.get_provider()` (`is_connected`, `counts`) + componente `neo4j` del informe de health | proveedor no consultable, conteos no fiables, sin fecha de último chequeo |
| Procesado | `app.jobs_client` (`jobs_db_status`, `get_counts_by_status`, `list_jobs`) | base de jobs ausente/ilegible, marcas de tiempo inválidas |
| Revisión | `app.services.review_console` (`list_source_summaries`, `read_decisions`) | resúmenes o decisiones ilegibles, sin fuentes visibles |
| Backups | fichero de estado de un **watchdog externo** | fichero ausente, JSON corrupto, fechas inválidas, estado no declarado |
| Seguridad | base de auth en **modo lectura** (`file:...?mode=ro`): sesiones, usuarios bloqueados, recuentos de auditoría | auth desactivada, base ausente, base no consultable |

### Backups: el panel NO habla con Proxmox

Sin token PVE, sin SSH, sin `vzdump`, sin leer el almacenamiento de copias.
El panel sólo lee un JSON ya saneado que deja un watchdog externo en
`S9K_OPS_BACKUP_STATE_PATH` (por defecto `viewer/state/ops/backup_watchdog.json`,
directorio ignorado por git). Contrato (ver `viewer/examples/ops_backup_watchdog.example.json`):

```json
{"vmid":105,"last_backup":"...","age_hours":12,"status":"ok",
 "last_restore_verified":"...","restore_status":"ok","generated_at":"..."}
```

Si el fichero no existe todavía —hoy no existe— la sección vale `UNKNOWN`, y lo
dice. El propio watchdog se vigila: si `generated_at` supera
`S9K_OPS_BACKUP_WATCHDOG_STALE_HOURS` (25 h), la sección pasa a `WARNING`
porque el dato ya no es de fiar. **El watchdog no forma parte de esta entrega.**

## Decisiones

1. **UNKNOWN por encima de OK en la agregación.** Es el corazón del diseño y
   está cubierto por control positivo.
2. **`age_hours` calculada, no creída.** Si la fuente trae `last_backup`
   parseable, manda esa fecha; el `age_hours` declarado sólo se usa como
   respaldo cuando la fecha falta o es inválida. Un timestamp basura nunca se
   interpreta como "ahora".
3. **Errores saneados.** Se publica el *tipo* de excepción, jamás el mensaje,
   la traza o la ruta. Hay tests que buscan literalmente rutas y URIs con
   credenciales en el JSON de salida y exigen que no aparezcan.
4. **Nada de escritura.** Ni siquiera se guarda el informe generado (a
   diferencia de `/admin/health`, que persiste su último informe). El router
   sólo expone GET; hay un test que lo comprueba enumerando `route.methods`.
5. **Seguridad sin secretos.** Sólo agregados numéricos y recuentos por tipo de
   evento. Ni tokens, ni hashes de sesión, ni IPs, ni rutas de la base.
6. **Router propio, no `main.py`.** Ver "Dependencias".

## Ficheros

- `viewer/app/ops/__init__.py`, `models.py` (estados y agregación), `collector.py`
  (seis recolectores + informe).
- `viewer/app/routers/ops.py` — `GET /api/admin/ops` (JSON) y `GET /admin/ops` (HTML).
- `viewer/app/templates/auth/admin/ops.html`.
- `viewer/examples/ops_backup_watchdog.example.json` — contrato del watchdog.
- `viewer/tests/test_ops_dashboard.py` — 65 tests.

## UX

Una página por secciones. Cada sección muestra su estado con color, un mensaje,
la tabla de métricas y las notas. Toda métrica desconocida se pinta como una
etiqueta `UNKNOWN` gris, nunca como un hueco vacío ni como un cero: el hueco se
lee como "bien" y el cero como "medido". La cabecera repite la regla en texto:
«UNKNOWN significa "no lo sé", no "está bien"».

## Tests

`cd viewer && python3 -m pytest -q tests/test_ops_dashboard.py` → **65 pasados,
0 fallos, exit 0** (~2 s).

Cubren: estado sano, warning, critical, fuente ausente, JSON corrupto,
timestamps inválidos, datos stale (health rancio, watchdog rancio, cola parada),
Neo4j no disponible, base de jobs ausente, usuario no admin (401 anónimo, 403
viewer, 403 reviewer, 302 a login en HTML), no filtración de secretos y ausencia
de rutas de escritura.

**Control positivo** (`test_control_positivo_*`): se muta el panel para que
devuelva siempre `OK` y para que `UNKNOWN` tenga severidad 0, y se comprueba que
los tests reales revientan. Además se verificó a mano, editando
`collect_backups` para devolver `OK` incondicionalmente: **11 fallos, 54
pasados**; revertido, **65 pasados**.

## Limitaciones

- Sin watchdog de backups desplegado, la sección Backups será `UNKNOWN` en
  producción desde el primer día. Es correcto y deliberado.
- La sección Revisión lee los *fixtures* de contrato del panel de revisión (lo
  que hay hoy en el repo), no una cola de revisión productiva.
- Versión y commit sólo se conocen si el despliegue los declara; si no,
  `UNKNOWN`.
- Los recuentos de Procesado y Revisión no se filtran por ámbito de partida: la
  ruta es exclusivamente de admin. No exponen contenido, sólo cifras.
- La sección Datos usa el proveedor ya configurado del visor; no abre conexiones
  propias ni fuerza reconexión.

## Dependencias

- **`viewer/app/main.py` pertenece a otro equipo de este programa y NO se ha
  tocado.** El router no está montado. Para activarlo hace falta exactamente
  esto en `main.py`:

  ```python
  from app.routers import ops as ops_router
  app.include_router(ops_router.router)
  ```

  No existe en el repo un mecanismo de auto-descubrimiento de routers, así que
  no hay forma de montarlo sin editar ese fichero. Los tests montan el router en
  una app mínima con `AuthMiddleware` para poder probar las rutas de verdad.
- Un enlace en `templates/base.html` a `/admin/ops` también requeriría tocar una
  plantilla compartida; queda igualmente pendiente.
- **M5b (PR #152/#153): sin dependencias.** No se ha tocado
  `app/policies/**`, `app/authz/**`, `app/providers/neo4j_provider.py`,
  `app/routers/admin.py` ni `app/main.py`, ni se ha introducido vocabulario de
  autorización paralelo (`visibility`, `known_by`, `scope`, `deny`…). El control
  de acceso reutiliza tal cual `require_admin` / `require_api_role("admin")`.

## Pendientes

1. Montar el router en `main.py` (dueño: equipo de `main.py`).
2. Escribir y desplegar el watchdog externo de backups que produzca el JSON del
   contrato (fuera de este carril: toca producción).
3. Declarar `S9K_APP_VERSION` / `S9K_GIT_COMMIT` en el despliegue.
4. Enlace de navegación al panel en `base.html`.
