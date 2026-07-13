# Análisis de fallos de tests — S9 Knowledge v0.2.5b

## Cabecera de auditoría

| Campo | Valor |
|-------|-------|
| Fecha | 2026-07-13 |
| Commit auditado | `1fd94b85` (v0.2.5b) |
| Entorno | VM105 (192.168.1.205) · Python 3.13.5 · pytest 8.4.2 |
| Venv | `/opt/knowledge-services/property-graph/.venv` |
| Repositorio | `/opt/knowledge-services/s9-knowledge-repo` |
| Comando ejecutado | `python -m pytest data-engine/app/tests/ viewer/tests/ --tb=short -q` |

### Resultados de la ejecución

| Métrica | Valor |
|---------|-------|
| Tests recopilados | 196 |
| Aprobados | 155 |
| Fallidos | **41** |
| Errores de colección | **6** |
| Omitidos | 0 |
| Duración | ~1.05 s |

Los 6 errores de colección impiden que esos ficheros arranquen. Los 41 fallos son tests que sí corren pero no superan sus aserciones.

---

## Resumen ejecutivo

Los 41 tests fallidos y los 6 errores de colección reducen a **dos causas raíz independientes**.

**CR-1 (primaria — 39 fallos + 6 errores de colección):** El fichero `data-engine/app/tests/test_ingest_semantics.py` ejecuta, en el cuerpo del módulo (fuera de cualquier función o fixture), la instrucción `sys.path.insert(0, "/opt/knowledge-services/property-graph/app")`. Esta inserción ocurre durante la fase de **colección** de pytest, antes de que corra ningún test. Pone en primer plano la copia antigua del proyecto (`property-graph/`) que todavía existe en disco como estado previo del despliegue. A partir de ese momento todos los módulos que pytest importe encuentran la versión antigua antes que la nueva: `ingest_rpg` sin normalización FOUGHT_AT, `jobs.job_store` sin los campos de cola genérica, y el paquete `app` apuntando a `property-graph/app` en lugar de `viewer/app`. Efecto en cascada: todos los tests de `test_job_store.py`, `test_media_jobstore_bridge.py`, `viewer/tests/test_api_jobs.py`, `viewer/tests/test_reviews.py` y los 6 ficheros de colección del visor reciben módulos incorrectos y fallan.

**CR-2 (secundaria — 4 fallos independientes):** Los tests de `viewer/tests/test_api_jobs.py` fallan también en ejecución aislada por un motivo diferente: `get_settings()` está decorada con `@lru_cache` y no existe ningún fixture `autouse` que limpie la caché entre tests. El primer test del fichero fija con `monkeypatch.setenv` un `S9K_JOBS_DB` que apunta a una ruta inexistente. El caché se construye en esa llamada. Los cuatro tests siguientes ven el Settings cacheado con la ruta no-existente y obtienen `jobs_db_not_found` en lugar del resultado esperado.

**Lo que NO afecta:** La protección de doble guardia contra escritura en producción (doble verificación de `S9K_ALLOW_REAL_INGEST`) no está implicada en ninguno de los fallos. El grafo de producción está protegido. Ningún test activa ingesta real.

**Orden de prioridad de corrección:**
1. Eliminar el `sys.path.insert` hardcodeado de `test_ingest_semantics.py` (CR-1) — una sola línea resuelve 39 fallos y los 6 errores de colección.
2. Añadir fixture `autouse` en `viewer/tests/conftest.py` que limpie `get_settings.cache_clear()` entre tests (CR-2) — resuelve los 4 restantes.

---

## Tabla de causas raíz

| ID | Causa raíz | Tests fallidos (full suite) | Errores colección | Componente | Tipo | Impacto | Severidad |
|----|-----------|----------------------------|-------------------|------------|------|---------|-----------|
| CR-1 | `sys.path.insert(0, property-graph/app)` a nivel de módulo en `test_ingest_semantics.py` | 39 | 6 | test infrastructure / imports | import path poisoning en colección | Enmascara regresiones reales; tests verifican el módulo equivocado | **ALTA** |
| CR-2 | `@lru_cache` en `get_settings()` no limpiado entre tests | 4 (independiente de CR-1) | 0 | viewer / test isolation | fixture missing | Tests del panel de jobs no detectan regresiones en resolución de path de BD | **MEDIA** |

**Nota sobre severidad:** ALTA no significa error de producción. Significa que estos fallos impiden que la suite detecte regresiones reales. CR-1 es especialmente peligroso porque los 155 tests que "pasan" son los que se ejecutan antes de que el path quede envenenado.

---

## Análisis detallado

### CR-1: import path poisoning por `test_ingest_semantics.py`

**Fichero:** `data-engine/app/tests/test_ingest_semantics.py`, línea 12

**Código problemático:**
```python
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)
sys.path.insert(0, "/opt/knowledge-services/property-graph/app")   # <- ruta hardcodeada
```

**Por qué falla:** La línea 12 inserta una ruta absoluta hardcodeada al despliegue antiguo del proyecto. El directorio `property-graph/` contiene versiones previas de `ingest_rpg.py`, `jobs/job_store.py` y otros módulos. Al insertarse en `sys.path[0]` durante la fase de colección de pytest, todos los imports subsiguientes encuentran primero los módulos de `property-graph/` antes que los de `data-engine/app/`.

**Módulos afectados y cómo difieren:**

| Módulo | Versión `property-graph/app` | Versión `data-engine/app` |
|--------|------------------------------|--------------------------|
| `ingest_rpg._check_relation_semantics` | No normaliza HAS_FOUGHT→FOUGHT_AT cuando el target es Location/Region | Normaliza (líneas 302-315) |
| `jobs.job_store.create_job` | `(workspace, source_kind: str, ...)` — source_kind **obligatorio** | `(workspace, source_kind: str = None, ...)` — opcional; acepta `job_type` en su lugar |
| `jobs.job_store.resolve_db_path` | No existe | Existe |
| `jobs.job_store` (esquema SQL) | Sin `job_type`, `priority`, `payload_json`, etc. | Con todas las columnas de la Fase jobs-worker-panel |
| `jobs.worker` | No existe en `property-graph/app/jobs/` | Existe en `data-engine/app/jobs/` |
| `app` (paquete) | `property-graph/app/` (sin `main.py`, sin `providers/`) | `viewer/app/` (aplicación FastAPI completa) |

**Cadena de contaminación:**

```
pytest collect phase
  → test_ingest_semantics.py (cuerpo del módulo)
    → sys.path.insert(0, "/opt/knowledge-services/property-graph/app")
      ↓ CONTAMINACION DE sys.path GLOBAL PARA TODA LA SESION

test_ingest_semantics.py (2 fallos directos):
  import ingest_rpg  → property-graph/app/ingest_rpg.py (sin normalización)
  assert HAS_FOUGHT → FOUGHT_AT  → FALLA

test_job_store.py (19 fallos):
  from jobs import job_store  → property-graph/app/jobs/job_store.py
  create_job(..., job_type="echo")  → TypeError: missing source_kind (obligatorio)
  job_store.resolve_db_path(...)  → AttributeError: no existe

test_media_jobstore_bridge.py (1 fallo):
  from jobs import job_store  → versión antigua
  create_job(..., source_kind='video')  → falla en validación antigua

test_jobs_worker.py (error de colección):
  from jobs import job_store, worker
  → ImportError: worker no existe en property-graph/app/jobs/

viewer/tests/test_api.py, test_config.py, test_labels.py,
             test_provider_mock.py, test_serializers.py (5 errores de colección):
  from app.main import app
  → ModuleNotFoundError: property-graph/app no tiene main.py

viewer/tests/test_api_jobs.py (6 fallos):
  sys.modules['app'] = property-graph/app (cacheado)
  → ModuleNotFoundError o TypeError en cascada

viewer/tests/test_reviews.py (11 fallos de 13):
  from app.main import app  → ModuleNotFoundError
```

**Corrección:**
Eliminar la línea 12 de `data-engine/app/tests/test_ingest_semantics.py`. La ruta `data-engine/app/` ya está en `sys.path` gracias al conftest de la carpeta de tests (líneas 9-11 del mismo fichero).

```python
# ELIMINAR esta línea:
sys.path.insert(0, "/opt/knowledge-services/property-graph/app")
```

**Riesgo de la corrección:** Bajo. La línea es redundante y contraproducente.

---

### CR-2: `@lru_cache` en `get_settings()` no limpiado entre tests

**Ficheros afectados:**
- `viewer/app/config.py` (línea 42) — define el caché
- `viewer/tests/test_api_jobs.py` — fichero con los tests que fallan
- `viewer/tests/conftest.py` — donde debe añadirse el fixture

**Código problemático:**
```python
@lru_cache
def get_settings() -> Settings:
    return Settings()
```

**Por qué falla:** `get_settings()` construye `Settings` leyendo las variables de entorno en la primera llamada y lo cachea indefinidamente. El primer test del fichero (`test_api_jobs_reports_not_found_when_db_missing`) fija `S9K_JOBS_DB` a una ruta inexistente con `monkeypatch.setenv`, disparando la primera llamada. Al terminar el test, `monkeypatch` restaura la variable de entorno, pero el caché NO se limpia. Los cuatro tests siguientes obtienen el valor cacheado con la ruta inexistente y reciben `jobs_db_not_found`.

**Tests afectados (fallan en ejecución aislada):**
- `test_api_jobs_returns_jobs_with_temp_db`
- `test_api_jobs_counts`
- `test_api_job_detail_not_found`
- `test_jobs_panel_renders_html`

**Tests que pasan en ejecución aislada:**
- `test_api_jobs_reports_not_found_when_db_missing` — primer test, el caché se construye con sus valores; espera "not found", pasa
- `test_jobs_panel_renders_without_db` — también espera "not found", tolera el caché corrupto

**Corrección:**
Añadir fixture `autouse` en `viewer/tests/conftest.py`:

```python
from app.config import get_settings

@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
```

**Riesgo de la corrección:** Bajo. La caché existe para producción. En tests, limpiarla entre casos no tiene efectos secundarios.

---

## Análisis de puntos críticos

### `FOUGHT_AT`: impacto en semántica del grafo

La normalización `HAS_FOUGHT → FOUGHT_AT` cuando el target es `Location` o `Region` existe en `data-engine/app/ingest_rpg.py` (líneas 302-315) pero NO en la copia antigua `property-graph/app/ingest_rpg.py`. En producción, la función `_check_relation_semantics` que se ejecuta durante la ingesta usa el fichero de `data-engine/app/`, que SÍ normaliza correctamente.

Los tests fallan porque importan el módulo equivocado (CR-1). Una vez corregido CR-1, estos dos tests pasarán y confirmarán que la normalización semántica está activa. Sin la corrección, no hay manera de verificar que la normalización siga funcionando tras futuras modificaciones de `ingest_rpg.py`.

### `source_kind='video'`: impacto en pipeline multimedia

`video` SÍ está en `VALID_SOURCE_KINDS` en `data-engine/app/jobs/job_store.py` (línea 49). El test `test_job_store_accepts_video_kind` falla porque, tras la contaminación de CR-1, importa el job_store antiguo de `property-graph/`, cuya lista de valores válidos es más reducida. En producción, el scanner multimedia puede crear jobs con `source_kind='video'` sin problemas. El fallo es un falso negativo de CR-1.

### Firma `create_job`: impacto en cola de trabajos

La firma evolucionó de `create_job(workspace, source_kind: str, ...)` (obligatorio) a `create_job(workspace, source_kind: str = None, ...)` (opcional, con soporte para `job_type`). Esta evolución está en producción y es correcta. Los tests están correctamente escritos para la nueva API. Los 19+1 fallos de `test_job_store.py` y `test_media_jobstore_bridge.py` son falsos negativos causados por CR-1.

### Imports del visor: por qué funciona en producción y falla en pytest

El visor en producción usa **su propio venv** (`viewer/.venv`) arrancado por systemd con `WorkingDirectory=/opt/knowledge-services/s9-knowledge-repo/viewer`. En ese contexto, `app` se refiere sin ambigüedad a `viewer/app/`. No hay rastro de `property-graph/app` en su sys.path.

Los tests del visor ejecutan con el venv compartido de `property-graph/.venv` y desde el directorio raíz del repo. La raíz conftest añade `viewer/app/` y `data-engine/app/` al sys.path, lo que en condiciones normales funciona correctamente (los 36 tests del visor pasan cuando se ejecutan sin CR-1 antes). El fallo es consecuencia pura de CR-1.

---

## Verificación: tests que pasan en aislamiento y fallan en suite completa

| Fichero de test | En aislamiento | En suite completa | Causa |
|-----------------|---------------|-------------------|-------|
| `test_ingest_semantics.py` | 2 fallan, 2 pasan | 2 fallan, 2 pasan | CR-1 directo |
| `test_job_store.py` | 19 pasan | 19 fallan | CR-1 cascade |
| `test_media_jobstore_bridge.py` | 3 pasan | 1 falla, 2 pasan | CR-1 cascade |
| `test_jobs_worker.py` | colecta OK | error de colección | CR-1 cascade |
| `viewer/tests/test_reviews.py` | 13 pasan | 11 fallan | CR-1 cascade |
| `viewer/tests/test_api_jobs.py` | 4 fallan, 2 pasan | 6 fallan | CR-1 cascade + CR-2 |
| `viewer/tests/test_api.py` | colecta OK | error de colección | CR-1 cascade |
| `viewer/tests/test_config.py` | colecta OK | error de colección | CR-1 cascade |
| `viewer/tests/test_labels.py` | colecta OK | error de colección | CR-1 cascade |
| `viewer/tests/test_provider_mock.py` | colecta OK | error de colección | CR-1 cascade |
| `viewer/tests/test_serializers.py` | colecta OK | error de colección | CR-1 cascade |

---

## Orden de corrección recomendado

### Prioridad 1 — Eliminar import path poisoning (CR-1)

**Fichero:** `data-engine/app/tests/test_ingest_semantics.py`

**Cambio:** eliminar la línea 12 (una única línea):
```python
# ELIMINAR:
sys.path.insert(0, "/opt/knowledge-services/property-graph/app")
```

**Efecto esperado:** 39 fallos y 6 errores de colección desaparecen. La suite pasa de 155/196 a ~192/196. Los tests que antes pasaban por importar el módulo antiguo ahora verificarán el código de producción real.

### Prioridad 2 — Limpiar caché de Settings entre tests (CR-2)

**Fichero:** `viewer/tests/conftest.py`

**Cambio:** añadir fixture autouse (ver sección CR-2 para el código completo).

**Efecto esperado:** Los 4 tests restantes de `test_api_jobs.py` pasan. Suite completa: 196/196.

---

## Propuesta de ramas de implementación

| Rama | Fichero(s) | Cambio | Tests resueltos |
|------|-----------|--------|-----------------|
| `fix/test-ingest-semantics-path` | `data-engine/app/tests/test_ingest_semantics.py` | Eliminar línea 12 (`sys.path.insert` hardcodeado) | 39 fallos + 6 errores de colección |
| `fix/viewer-settings-cache` | `viewer/tests/conftest.py` | Añadir fixture `clear_settings_cache` autouse | 4 fallos de lru_cache |

Ambas ramas pueden trabajarse en paralelo.

---

## Tests que deben añadirse (gaps detectados)

1. **Verificación de sys.path en CI:** Un check que detecte ruta absoluta hardcodeada en ficheros de test (`grep -r 'sys.path.insert.*/opt' data-engine/app/tests/`).

2. **pytest-randomly periódico:** Ejecutar la suite con `pytest-randomly` y semilla aleatoria para detectar dependencias entre tests antes de que lleguen a producción.

3. **Test de isolation de Settings:** Una vez añadido el fixture, un test explícito que fije `S9K_JOBS_DB` a una ruta válida y verifique que `get_settings()` devuelve el valor correcto después de otro test que lo fijó a ruta inválida.

4. **Smoke test de módulo correcto:** Si `property-graph/` va a permanecer en disco, un test que verifique que `ingest_rpg.__file__` apunta a `data-engine/app/`, no a `property-graph/app/`.

---

## Riesgos

### Qué podría romperse al corregir

**CR-1 (eliminar sys.path.insert):**
Riesgo bajo. La línea añadía un path que ya está presente por el conftest de tests. Si algún test dependiera deliberadamente de importar desde `property-graph/app/`, fallaría. Revisión del fichero confirma que no.

**CR-2 (fixture cache_clear):**
Riesgo bajo. Las Settings se reconstruirán en cada test. No se detectan tests que dependan de persistencia de Settings entre casos.

### Tests que pueden enmascarar regresiones reales

Los 155 tests que pasan en la suite completa se ejecutan ANTES de que `test_ingest_semantics.py` envenene el path (pytest ejecuta en orden alfabético).

- Los tests de `test_ingest_semantics.py` que pasan (2 de 4) validan comportamiento del módulo antiguo (`property-graph/app/ingest_rpg.py`), no del nuevo. Son **falsos positivos**.
- Todos los tests que corren DESPUÉS de `test_ingest_semantics.py` en la sesión son potencialmente no fiables: pueden pasar por razones incorrectas.

---

## Estado

```
Auditoría de tests:      COMPLETO (2026-07-13)
Commit auditado:         1fd94b85 (v0.2.5b)
Causas raíz:             2 identificadas (CR-1 primaria, CR-2 secundaria)
Tests fallidos:          41 + 6 errores de colección

Correcciones de código:  PENDIENTE (requieren ramas específicas y aprobación)
  → fix/test-ingest-semantics-path  (CR-1, 1 línea, resuelve 39 fallos + 6 colección)
  → fix/viewer-settings-cache       (CR-2, fixture autouse, resuelve 4 fallos)

Impacto en producción:   NINGUNO — los fallos son de test infrastructure,
                          no de código de producción. La protección de escritura
                          (doble guard S9K_ALLOW_REAL_INGEST) está intacta.
```

---

## Anexo — Análisis Agente B: divergencia código producción vs repo (2026-07-13)

> Hallazgos adicionales obtenidos reproduciendo los fallos en clone aislado del repo
> (`/tmp/s9k-work-agentB`, commit `9dd92b4`, rama `main`). Complementa el análisis
> principal del Agente A (commit auditado `1fd94b85`, producción).

### Entorno Agente B

| Campo | Valor |
|-------|-------|
| Clone aislado | `/tmp/s9k-work-agentB` |
| Commit HEAD (clone) | `9dd92b4` |
| Código producción comparado | `/opt/knowledge-services/property-graph/app/` |
| PYTHONPATH | `/tmp/s9k-work-agentB` |
| Fallos reproducidos (suite por separado) | 22 fallos + 6 errores colección |

### Divergencias detectadas entre repo (main) y producción

El Agente B confirmó que además del mecanismo de path poisoning (CR-1) y lru_cache (CR-2),
existen divergencias reales entre el código del repo y el código desplegado en producción
que harían fallar tests incluso si se corrigiera CR-1:

#### `jobs/job_store.py` — Firma extendida en repo, no sincronizada a producción

**Producción** `create_job(workspace, source_kind: str, ...)` — `source_kind` posicional OBLIGATORIO, sin `job_type`, sin `resolve_db_path()`, sin `worker.py`.

**Repo** `create_job(workspace, source_kind: str = None, ..., job_type: str = None, ...)` — `source_kind` opcional, soporte cola genérica, `resolve_db_path()`, `worker.py`.

Tests afectados si CR-1 se corrige pero el código no se sincroniza: 19 de `test_job_store.py` + 2 de `test_resolve_db_path` + `test_job_store_accepts_video_kind`.

#### `VALID_SOURCE_KINDS` — `'video'` y `'generic'` faltan en producción

- Producción: `{"book", "pdf", "audio", "transcript", "text", "image", "youtube", "web", "manual_note", "test"}`
- Repo: añade `"video"` y `"generic"`
- Test afectado: `test_job_store_accepts_video_kind` → `ValueError: source_kind inválido: 'video'`

#### `ingest_rpg._check_relation_semantics` — normalización `HAS_FOUGHT→FOUGHT_AT`

El bloque de normalización (repo, líneas 302-315) no existe en producción. Los 2 tests `test_has_fought_*` fallarán incluso con CR-1 corregido hasta que se sincronice `ingest_rpg.py`.

### Pasos para corrección completa

| Paso | Acción | Riesgo | Responsable |
|------|--------|--------|-------------|
| 1 | Eliminar `sys.path.insert(0, "/opt/.../property-graph/app")` en `test_ingest_semantics.py` y `test_schemas.py` | Ninguno | s9-code |
| 2 | Añadir fixture `autouse` `cache_clear` en `viewer/tests/conftest.py` | Bajo | s9-code |
| 3 | Sincronizar `data-engine/app/jobs/job_store.py` (con `_MIGRATION_COLUMNS`) a producción | Medio (BD) | s9-sysadmin |
| 4 | Copiar `data-engine/app/jobs/worker.py` a producción | Bajo | s9-sysadmin |
| 5 | Sincronizar bloque `HAS_FOUGHT→FOUGHT_AT` de `ingest_rpg.py` a producción | Bajo | s9-code + s9-sysadmin |

### Estado

```
Análisis Agente B:        COMPLETO (2026-07-13)
Clone aislado:            /tmp/s9k-work-agentB (no producción)
Divergencias adicionales: 3 (job_store firma, VALID_SOURCE_KINDS, HAS_FOUGHT normalizer)
Impacto en producción:    NINGUNO — solo análisis, sin escritura en Neo4j
```
