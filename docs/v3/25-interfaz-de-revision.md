# Interfaz de revisión V3

Fecha de ejecución: 2026-07-29  
Rama: `feat/v3-review-ui`  
Base: `origin/feat/knowledge-v3-redesign` en `2d76f4b`

## Decisión de diseño

Se extendió `viewer/` porque ya aporta FastAPI, plantillas, estilo, sesiones,
identidad del revisor, CSRF y roles `reviewer`/`admin`. Se añadió una consola
independiente en `/v3/review`; no se reutilizó la semántica del panel
`review-ingest/v1`, ya que aquel revisa candidatos de entidad y este encargo
revisa claims y decisiones del motor Knowledge V3.

La consola nueva no importa el motor, el writer ni el proveedor Neo4j. Consume
paquetes JSON locales desde:

```text
S9K_V3_REVIEW_PROPOSALS_DIR
```

Si no se configura, usa `output/reviews-v3/proposals/`. Cada fichero puede
contener una propuesta, una lista, o `{"items": [...]}`. Los campos que la vista
necesita y no estén presentes se muestran como `No disponible`; no se
reconstruyen ni inventan.

El historial se escribe en:

```text
S9K_V3_REVIEW_DECISIONS_PATH
```

Si no se configura, usa `output/reviews-v3/decisions.jsonl`.

## Flujo de revisión

1. El revisor elige exactamente un workspace. La carga y todos los filtros se
   aplican después de aislarlo.
2. Puede filtrar por fuente y decisión del motor. El orden estable es
   `(source_id, episode_id, proposal_id)`.
3. La pantalla mantiene visible el episodio completo en un área acotada y centra
   la evidencia literal marcada según sus offsets.
4. Muestra sujeto, predicado, objeto, dirección, negación, alcance, razones del
   motor traducidas, ontología y candidatos alternativos. Los orígenes se leen
   tanto del paquete explícito como de
   `metadata.reconciliation.predicate_candidate_origins` y
   `direction_candidate_origins`.
5. `A`, `R`, `C` y `N` permiten aprobar, rechazar, corregir y pasar al siguiente.
   Tras registrar, la redirección carga el primer pendiente; el contador se
   obtiene del historial persistido.
6. `Deshacer última` agrega otra entrada `CORRECT` que supersede la decisión y
   devuelve la propuesta a pendiente. No borra ni edita la entrada anterior.

## Registro append-only

Cada línea JSON contiene, como mínimo:

```yaml
decision_id:
request_id:
timestamp:
reviewer:
workspace:
source_id:
episode_id:
proposal:
engine_decision:
human_decision:
correction:
rationale:
ontology_version:
engine_version:
supersedes_decision_id:
previous_hash:
record_hash:
```

`previous_hash` y `record_hash` forman una cadena SHA-256. Toda lectura valida la
cadena completa y se niega a continuar ante una edición, truncado intermedio,
reordenación o JSON inválido. La escritura abre el fichero únicamente en modo
append, hace `flush` y `fsync`.

`request_id` hace idempotente el reenvío del formulario tras una recarga. Repetir
la misma petición devuelve la entrada existente; reutilizar el identificador con
otra decisión o workspace se rechaza.

Una aprobación humana solo crea este registro. No contiene `plan_hash`,
`authorization` ni `mutation_operations`, y no llama al writer.

## Ficheros

- `viewer/app/services/v3_review.py`
- `viewer/app/routers/v3_review.py`
- `viewer/app/templates/v3_review.html`
- `viewer/app/static/css/v3-review.css`
- `viewer/app/static/js/v3-review.js`
- `viewer/app/main.py`
- `viewer/app/templates/base.html`
- `viewer/tests/test_v3_review.py`
- `docs/v3/25-interfaz-de-revision.md`

## Pruebas ejecutadas

Comando:

```text
python -m pytest viewer/tests/test_v3_review.py -q
```

Salida real:

```text
.............                                                            [100%]
13 passed, 1 warning in 0.82s
```

La advertencia es `StarletteDeprecationWarning` de `fastapi.testclient`.

También se ejecutó la nueva suite junto al panel previo:

```text
python -m pytest viewer/tests/test_v3_review.py viewer/tests/test_reviews_console.py -q
```

Resultado real:

```text
..........................FFFFFF                                         [100%]
6 failed, 26 passed, 1 warning in 1.33s
```

Los seis fallos ocurren al importar `viewer/app/auth/db.py:4`, antes de ejercer
las rutas del panel previo:

```text
ModuleNotFoundError: No module named 'fcntl'
```

Suite completa del visor:

```text
python -m pytest viewer/tests/ -q
```

Resultado real:

```text
ERROR viewer/tests/test_api.py
ERROR viewer/tests/test_health_backups.py
Interrupted: 2 errors during collection
1 skipped, 1 warning, 2 errors in 0.80s
```

Las causas son `viewer/app/auth/db.py:4` (`fcntl`, no disponible en Windows) y
`viewer/tests/test_health_backups.py:321` (`os.geteuid`, no disponible en
Windows).

Suite global:

```text
python -m pytest -q
```

Resultado real:

```text
ImportError while loading conftest 'deploy/tests/conftest.py'
deploy/scripts/retention.py:18: ModuleNotFoundError: No module named 'fcntl'
```

Esos defectos están fuera de A y no se modificaron, conforme a la prohibición de
parchear subsistemas laterales.

## Cobertura de los criterios

- Cola limitada a un workspace y ordenada de forma estable.
- Una petición produce exactamente una línea; un reintento no duplica.
- Corrección y deshacer conservan la entrada anterior y la superseden.
- Driver Neo4j que falla al tocarse permanece sin llamadas.
- Una aprobación humana no genera ni aprueba un plan.
- El texto marcado coincide exactamente con `episode_text[start:end]`.
- Un `reason_code` desconocido se muestra literalmente.
- Una instancia nueva del servicio recupera el estado y deduplica el reenvío.
- Una modificación manual del historial rompe la cadena y es detectada.

## Limitaciones conocidas

- No se obtuvo captura de navegador en esta máquina porque importar la aplicación
  completa está bloqueado por el uso POSIX de `fcntl` en autenticación. La
  plantilla y las rutas se ejercitaron con una aplicación FastAPI aislada.
- El servicio espera que el proceso que produce la cola materialice los paquetes
  JSON; integrar esa exportación dentro del pipeline habría requerido modificar
  subsistemas excluidos del encargo.
- El bloqueo concurrente es entre hilos del proceso. La cadena hash detecta
  corrupción externa, pero dos procesos distintos no coordinan un lock de
  escritura. El despliegue debe mantener un único worker escritor para esta
  versión.
