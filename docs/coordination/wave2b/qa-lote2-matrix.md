# QA Lote 2 — Matriz de mutaciones (OLA 2B, Agente P8)

Suite `tests/wave2b`: QA transversal que **importa los modulos REALES** ya
integrados en `main` (Lotes 1+2) y comprueba sus invariantes de seguridad. Q no
reimplementa nada ni copia logica: solo ejercita el producto real y **bloquea**
si detecta un defecto (no lo arregla).

## Modulos reales importados

| Modulo (`data-engine/app/relations/`) | Fichero de test |
| --- | --- |
| `syntax` | `tests/wave2b/test_syntax_real.py` |
| `local_llm_shadow` | `tests/wave2b/test_local_llm_real.py` |
| `external_ai_shadow` | `tests/wave2b/test_external_ai_real.py` |
| `consensus_adapter` | `tests/wave2b/test_consensus_real.py` |
| `observability` | `tests/wave2b/test_observability_real.py` |

Import via `data-engine/app` en `sys.path` (patron de `tests/wave2/conftest.py`).
El **cortafuegos de produccion** se hereda de `tests/conftest.py` (no se duplica).

## Matriz 12/12 (cada fila = un `@pytest.mark.mutation`)

| # | Violacion (mutacion) | Modulo real | Como se captura | Test |
| --- | --- | --- | --- | --- |
| 1 | proveedor sintactico descarga modelo | `syntax` | el proveedor por defecto (`heuristic`) analiza 100% offline (socket minado); pedir spaCy/Stanza **falla cerrado** (`SyntaxProviderUnavailable`), nunca descarga | `test_mutation_default_syntax_never_opens_socket_or_downloads` |
| 2 | endpoint local usa default real | `local_llm_shadow` | sin endpoint ni transporte -> `ConfigError` **antes** de abrir socket (socket minado); con transporte inyectado si evalua | `test_mutation_no_endpoint_fails_closed_without_socket` |
| 3 | secreto aparece en logs | `external_ai_shadow` | `assert_no_secrets` bloquea el payload con API key (`SecretLeakError`); `config.to_dict`/`repr` y el resultado no contienen la key | `test_mutation_secret_never_leaks_to_provider_or_logs` |
| 4 | JSON invalido aceptado | `local_llm_shadow` + `external_ai_shadow` | ambos evaluadores marcan `INVALID_RESPONSES` ante texto no-JSON; con JSON valido no | `test_mutation_invalid_json_rejected_by_local_and_external` |
| 5 | evidencia inexistente aceptada | `external_ai_shadow` | verdicto con `evidence_text` no literal en el segmento -> `INVALID_RESPONSES`; evidencia literal si se acepta | `test_mutation_invented_evidence_is_rejected` |
| 6 | workspace mezclado aceptado | `consensus_adapter` | proveedor de otro workspace -> `INVALID_RESPONSES/workspace_mismatch`; mismo workspace no | `test_mutation_workspace_mismatch_is_invalidated` |
| 7 | negacion se pierde | `consensus_adapter` | `negated` del candidato se preserva en el consenso (True y False) | `test_mutation_negation_is_preserved` |
| 8 | temporalidad se pierde | `consensus_adapter` | `temporal_scope` se preserva intacto (dict y None) | `test_mutation_temporal_scope_is_preserved` |
| 9 | consenso depende del orden | `consensus_adapter` | dos permutaciones (con duplicados) dan `to_dict` identico | `test_mutation_consensus_is_order_independent` |
| 10 | proveedor ausente = rechazo | `consensus_adapter` | un proveedor que propone con el otro **ausente** -> `PARTIAL/propose`; con el otro **presente y reject** -> `MODEL_CONFLICT` | `test_mutation_absent_provider_is_not_a_reject` |
| 11 | aparece autoaprobacion | `consensus_adapter` + `external_ai_shadow` + `local_llm_shadow` | los `__post_init__` reales rechazan `approve`/`AUTO_APPROVED`; un consenso calculado nunca contiene `APPROVED` | `test_mutation_no_auto_approval_across_modules` |
| 12 | dry-run genera escritura | `observability` + `local_llm_shadow` + `syntax` | `builtins.open` en modo escritura esta minado; las capas disponibles no escriben | `test_mutation_layers_perform_zero_writes` |

Cada mutation check demuestra que la regla es **load-bearing**: incluye el
**rechazo real** de la violacion y un **control positivo** que si pasa (la logica
no rechaza indiscriminadamente).

## Defectos detectados

**Ninguno.** Las 12 invariantes se cumplen contra el producto real integrado en
`main` (`b01b6022`). No se ha modificado ningun producto.

## Notas de alcance (para el Organizador)

- **testpath pendiente**: `pytest.ini` es area compartida y **no** se edita en
  esta rama. `testpaths` incluye `tests/wave2` pero **no** `tests/wave2b`. El
  Organizador debe anadir `tests/wave2b` al `testpath` de `pytest.ini` en el PR de
  integracion. Mientras tanto la suite se ejecuta por ruta explicita:
  `python3 -m pytest tests/wave2b -q`.
- **Punto 12 / R8**: la comprobacion de "cero escritura" cubre las capas hoy
  disponibles (observability, LLM local sombra, sintaxis). Cuando se integre R8
  (pipeline de escritura en Neo4j), esta comprobacion debe **extenderse** a esa
  capa para cerrar el punto 12 de extremo a extremo.

## Ejecucion

```
S9K_ALLOW_REAL_INGEST="" python3 -m pytest tests/wave2b -q     # 21 passed (12 mutation)
python3 -m pytest tests -q                                     # 148 passed (no rompe OLA 2A/D)
python3 .github/scripts/check_unicode.py                       # OK
python3 scripts/check_docs_consistency.py                      # coherente
```
