# 31 — Test Remediation and CI Report

**Fecha**: 2026-07-13  
**Rama**: `fix/tests-imports-cache-and-ci`  
**Objetivo**: Hacer la suite de tests reproducible en clones limpios y añadir CI.

---

## Situación inicial

| Métrica | Valor |
|---------|-------|
| Tests (suites separadas) | 184 data-engine + 36 viewer = 220 pasados |
| Errores de colección (corrida combinada) | 5 en viewer/tests |
| Causa | Colisión del paquete Python `app` en corrida combinada |

### Descripción del problema (CR-1)

En corrida combinada, pytest importa los tests de `data-engine/app/tests/` primero.  
Como `data-engine/app/` tenía un `__init__.py` vacío, Python registraba ese directorio  
en `sys.modules['app']`. Cuando llegaba a colectar `viewer/tests/`, el import  
`from app.config import Settings` fallaba porque `sys.modules['app']` apuntaba a  
`data-engine/app` (que no tiene `config.py`).

Adicionalmente, `data-engine/app/tests/__init__.py` y `viewer/tests/__init__.py`  
(ambos vacíos) causaban `ImportPathMismatchError` en corrida combinada al registrarse  
ambos como el paquete `tests`.

---

## Causas raíz y soluciones

| ID | Causa | Tests afectados | Solución aplicada |
|----|-------|----------------|-------------------|
| CR-1a | `data-engine/app/__init__.py` vacío → paquete `app` colisiona con `viewer/app` | 5 errores de colección viewer | Eliminar `__init__.py` vacío |
| CR-1b | `data-engine/app/tests/__init__.py` + `viewer/tests/__init__.py` → `ImportPathMismatchError` | 5 errores de colección | Eliminar ambos `__init__.py` vacíos |
| CR-1c | `conftest.py` raíz no insertaba `viewer/` en sys.path | viewer no importable en combinada | Reescribir conftest raíz con ambos paths |
| CR-2 | `create_job()` firma (jobs, worker) | Ya pasaban; código alineado | Sin cambios necesarios |
| CR-3 | `VALID_SOURCE_KINDS` | Ya pasaban | Sin cambios necesarios |
| CR-4 | `HAS_FOUGHT→FOUGHT_AT` | Ya pasaban | Sin cambios necesarios |

---

## Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `data-engine/app/__init__.py` | Eliminado (estaba vacío; causaba registro de paquete `app`) |
| `data-engine/app/tests/__init__.py` | Eliminado (estaba vacío; causaba ImportPathMismatchError) |
| `viewer/tests/__init__.py` | Eliminado (estaba vacío; idem) |
| `conftest.py` | Reescrito: inserta `data-engine/app` y `viewer/` en sys.path con documentación clara |
| `pytest.ini` | Sin cambios funcionales (se eliminó `pythonpath` redundante) |
| `.github/workflows/ci.yml` | Creado: 4 jobs (data-engine, viewer, combined, check-imports) |

---

## Resultado final

| Métrica | Antes | Después |
|---------|-------|---------|
| Errores de colección (combinada) | 5 | 0 |
| Tests pasados (combinada) | N/A (colección fallaba) | 220 |
| Tests fallidos | 0 (suites separadas) | 0 |
| Duración | — | 6.45s |

---

## CI añadido

Workflow: `.github/workflows/ci.yml`

**Jobs**:
- `test-data-engine`: instala `data-engine/requirements.lock`, corre `data-engine/app/tests/`
- `test-viewer`: instala `viewer/requirements.txt`, corre `viewer/tests/`
- `test-combined`: instala ambos, corre corrida combinada completa (valida CR-1 en CI)
- `check-imports`: grep de rutas `/opt/` hardcodeadas en archivos `.py`

**Triggers**: push a `main`, `fix/**`, `feat/**`, `audit/**`, `docs/**`, `chore/**`; PR a `main`.

---

## Producción

- Neo4j: no modificado
- `S9K_ALLOW_REAL_INGEST`: no activado
- Servicios VM105: no reiniciados
- Datos: ningún cambio
- Árbol `/opt/knowledge-services/s9-knowledge-repo`: no modificado
