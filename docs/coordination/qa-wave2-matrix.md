# Matriz de QA transversal — OLA 2A (Agente Q)

Rama: `test/wave2-crosscutting-security-v1` · base `main@15ae1d4`.

El Agente Q **no corrige producto**: reproduce, asigna severidad e identifica al
equipo propietario, bloquea el gate y propone un PR correctivo separado. Esta ola
cubre los tres contratos internos de OLA 2A y la supply chain.

## FASE 2 (integrada): tests contra el PRODUCTO REAL

Tras fusionar A1 (relaciones), B2 (export/import), B3 (multimedia) y B-SEC-1
(supply chain), esta suite se reescribió para **importar y ejercitar las
implementaciones reales** ya en `main`, no validadores de referencia duplicados:

- `relations.contracts` (RelationCandidate) — `data-engine/app/relations`.
- `export_import.contract` (validate_safe_path/validate_sha256/validate_manifest/
  validate_zip_metadata/dry_run_import/DryRunReport) — `data-engine/app/export_import`.
- `media.multimedia_contract` (BoundingBox/MediaType) — `data-engine/app/media`.
- `.github/dependabot.yml` real (política de supply chain).

`tests/wave2/conftest.py` pone `data-engine/app` en `sys.path` (mismo patrón que
`data-engine/app/tests/conftest.py`), exponiendo `relations`/`export_import`/`media`
sin colisionar con el paquete `app` del viewer. Q **sigue sin modificar producto**:
solo lo importa y comprueba sus invariantes. Los 6 MUTATION checks ejercitan el
comportamiento REAL importado (una regla relajada dejaría pasar lo que el validador
real rechaza). Resultado: 42 tests, 6/6 mutaciones.

## Cobertura por contrato

| Contrato | Fichero de test | Invariantes verificadas |
|----------|-----------------|-------------------------|
| Relaciones (§1, Equipo A) | `test_relation_contract_rules.py` | schema inválido, offsets `start>end`/negativos, evidencia ausente, workspace vacío, confidence fuera de `[0,1]`, negación no explícita, epistemic inválido, dirección inválida, campos obligatorios |
| Export/Import (§2, Equipo B) | `test_export_import_security.py` | path traversal (`../`, absoluta, drive Windows), hash sha256 incorrecto/ausente, manifest ausente, versión desconocida, formato desconocido, IDs duplicados, workspace ajeno, tamaño excesivo, **import dry-run por defecto (0 escrituras, APPLY nunca por defecto)** |
| Multimedia (§3, Equipo B) | `test_multimedia_contract_rules.py` | bbox fuera de `[0,1]`/fuera de página, bbox degenerado, tipos desconocidos, confianza fuera de rango, orientación inválida, página inválida, procedencia ausente (file/hash/model), solapamiento = **warning** (no error) |
| Supply chain (Dependabot, Equipo B) | `test_supply_chain_config.py` | `version==2`, ecosistemas requeridos (pip, github-actions) presentes, ecosistema desconocido rechazado, **sin auto-merge** (ni general ni de major), Actions pinneables por SHA de 40 hex |

## Pruebas de mutación (cada una: RELAJAR la regla la deja pasar -> regla load-bearing)

| # | Mutación | Test que la captura | Contrato | Confirmado |
|---|----------|---------------------|----------|------------|
| 1 | Aceptar workspace vacío | `test_mutation_accepting_empty_workspace_breaks` | Relaciones | Sí |
| 2 | Ignorar el hash sha256 | `test_mutation_ignoring_hash_breaks` | Export/Import | Sí |
| 3 | Aceptar path traversal | `test_mutation_accepting_path_traversal_breaks` | Export/Import | Sí |
| 4 | Import con APPLY por defecto | `test_mutation_apply_by_default_breaks` | Export/Import | Sí |
| 5 | Aceptar bbox fuera de rango | `test_mutation_accepting_out_of_range_bbox_breaks` | Multimedia | Sí |
| 6 | Auto-merge de major | `test_mutation_enabling_major_automerge_breaks` | Supply chain | Sí |

Cada test de mutación afirma dos cosas: (a) el validador **estricto** captura la
violación y (b) el validador **relajado** (mutante) la deja pasar. Es decir, la
mutación cambia el resultado y rompería la garantía de seguridad.

**Totales:** 66 tests, 6 mutation checks. `pytest tests/wave2 -q` -> 66 passed.

## Invariante de seguridad heredada

El cortafuegos de producción (`tests/support/prod_block.py`, instalado por
`tests/conftest.py`) cubre también `tests/wave2/` por herencia de conftest: ningún
test Q puede conectar a `knowledge.seccionnueve.duckdns.org`, `192.168.1.205` ni
`100.103.100.105`. `tests/wave2/conftest.py` **no** lo duplica; solo registra el
marker `mutation` y expone la fixture `prod_firewall_active`.

## Nota de integración — pytest.ini testpath

`pytest.ini` es **área compartida** (propiedad del Organizador) y **no** incluye
`tests/wave2` en `testpaths`. Q **no** lo edita. Mientras tanto, la suite se ejecuta
por ruta explícita:

```
S9K_ALLOW_REAL_INGEST="" python3 -m pytest tests/wave2 -q
```

**Acción para el Organizador:** añadir `tests/wave2` a `testpaths` de `pytest.ini`
vía PR de integración para que CI la recoja automáticamente.

## Defectos detectados

**Ninguno de producto.** Los contratos reales de A1/B2/B3 no están fusionados, por
lo que Q no ha ejecutado producto: esta ola fija las invariantes de referencia. El
único hallazgo transversal es de **utillaje** (no de producto):

| Hallazgo | Severidad | Propietario | Estado |
|----------|-----------|-------------|--------|
| `tests/wave2` no está en `testpaths` de `pytest.ini` | Baja (utillaje) | Organizador | Documentado; requiere PR de integración |

Cuando A1/B2/B3 se fusionen, Q re-apuntará estos validadores de referencia contra
el contrato real; cualquier divergencia se reportará aquí con severidad y propietario
y **bloqueará el gate** sin que Q modifique producto.
