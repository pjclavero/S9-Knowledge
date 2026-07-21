# Plan de pruebas — PR#95 V1

Fichero: `data-engine/app/tests/test_pr95_v1_conservative_anchor.py` (14 tests, todos
verdes). Todas las aserciones fallan de verdad si el comportamiento se rompe (sin
`skip`/`xfail`, sin umbrales relajados). Verificado por mutación (ver `results.md`).

## Escenarios exigidos

| # | Test | Qué comprueba |
|---|------|---------------|
| 1 | `test_negacion_fuera_de_clausula_se_incluye` | Negación (`Nunca`) en cláusula previa a la de las menciones → se incluye en la envolvente. |
| 2 | `test_dos_clausulas_elige_la_segura` | Dos cláusulas; se elige la que contiene ambas menciones y se EXCLUYE la ajena. |
| 3 | `test_sujeto_repetido_offsets_correctos` | Sujeto repetido; la envolvente cubre la instancia elegida con offsets válidos y coherentes. |
| 4 | `test_temporalidad_final_se_incluye` | Marca temporal (`durante`) en cláusula posterior → se reincorpora. |
| 5 | `test_rumor_en_contexto_epistemico_preservado` | Atribución/rumor (`Segun rumores`) se incluye y `epistemic_status` sigue `RUMORED`. |
| 6 | `test_frase_sin_puntuacion_coherente` | Frase sin puntuación → envolvente coherente que no desborda. |
| 7 | `test_fallback_seguro_a_span` | Si `_conservative_anchor` devuelve `None` (monkeypatch), `_build_candidate` cae al span mecánico. |
| 8 | `test_metamorfico_estrechamiento_subset_frase` (5 casos) | Metamórfico: envolvente ⊆ frase, contiene ambas menciones, no vacía, coherente. |
| 9 | `test_no_regresion_default_es_span` | Default == `span`; salida byte-idéntica con `span` explícito; evidencia == span mecánico exacto. |

Extra: `test_conservative_difiere_del_span_en_esta_frase_no` — invariante de
coherencia del candidato en modo conservador end-to-end.

## Suites que deben seguir verdes (y siguen)

```
cd data-engine/app
python3 -m pytest tests/ -k relation -q                                  # 903 passed
python3 -m pytest tests/test_relation_calibration_final_quality_block9.py -q  # 48 passed
python3 -m pytest tests/test_relation_external_document_contract.py -q        # 13 passed
python3 -m pytest tests/test_pr95_v1_conservative_anchor.py -q                # 14 passed
```

## Medición A/B

`python3 -m tools.relation_anchor_ab` ejecuta el runner REAL (`baseline1`, offline)
sobre el corpus B1 comparando `span` vs `conservative` y guarda el JSON en
`artifacts/pr95-variants/v1/`. Ver `results.md`.
