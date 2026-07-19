# Riesgos — OLA 2B

| ID | P | Riesgo | Mitigación |
|----|---|--------|------------|
| RK-2B-01 | P0 | Escritura en Neo4j desde el pipeline | dry-run estricto; cero writer; `S9K_ALLOW_REAL_INGEST` off; cortafuegos de red |
| RK-2B-02 | P0 | Conexión a producción (Ollama/NVIDIA/Neo4j) por default | endpoints solo por config explícita; tests sin red; prueba real NOT_EXECUTED sin autorización |
| RK-05 | P0 | Default viewer → Neo4j prod (192.168.1.205) | P7: fail-closed, config explícita, tests sin red (PR independiente) |
| RK-2B-03 | P1 | Explosión combinatoria de pares | R1: límites de ventana/distancia + máximo de pares + protección |
| RK-2B-04 | P1 | Prompt injection en prompts RPG | R4: JSON estricto, evidencia literal, saneo, tests de inyección |
| RK-2B-05 | P1 | Duplicar consenso/estados de external_ai | R7 reutiliza external_ai/consensus.py; Supervisor lo verifica |
| RK-2B-06 | P1 | No determinismo (LLM) | modo sombra, hashes de prompt/input, 3 ejecuciones, medir variabilidad |
| RK-2B-07 | P1 | Autoaprobación de relaciones | prohibido: consenso produce candidatos, nunca APPROVED; sin escritura |
| RK-2B-08 | P2 | Secretos en logs (IA externa) | redacción; security de external_ai; sin claves reales |
| RK-2B-09 | P2 | Corpus/imágenes privadas en Git | solo sintético sanitizado + hashes; secret scan |
| RK-2B-10 | P2 | Modificar contratos OLA 2A | congelados; cambio → punto de parada documentado |

## Estado final de los riesgos — cierre OLA 2B (2026-07-19)

Evaluados contra el pipeline real (R8 #80), corpus (B1 #79), benchmark (B2 #81) y
QA final (QF #83). Detalle en [`lote3-closeout.md`](lote3-closeout.md).

| ID | Estado final | Evidencia |
|----|-------------|-----------|
| RK-2B-01 | **MITIGADO** | dry-run estricto; QF: `builtins.open` de escritura minado, flags write/apply rechazadas; `S9K_ALLOW_REAL_INGEST` off; benchmark sin escritura |
| RK-2B-02 | **MITIGADO** | Ollama/NVIDIA `NOT_EXECUTED`; sockets minados; proveedor inválido → `FAILED_CLOSED` sin red |
| RK-05 | **CERRADO** | fail-closed viewer neo4j default (P7); QF verifica ausencia de driver neo4j en subproceso limpio |
| RK-2B-03 | **MITIGADO** | R8: cap de pares (`truncated=True`), M2/M11 y test E2E de explosión combinatoria |
| RK-2B-04 | **MITIGADO** | prompt injection tratado como dato (test hostil), JSON estricto, evidencia literal |
| RK-2B-05 | **MITIGADO** | R7 reutiliza `external_ai/consensus`; verificado por Supervisor sin duplicación |
| RK-2B-06 | **MITIGADO** | determinismo gate DURO PASS (2 ejecuciones: hashes/métricas/predicciones iguales) |
| RK-2B-07 | **MITIGADO** | recomendaciones ∈ {propose,reject,human}; nunca APPROVED (M8) |
| RK-2B-08 | **MITIGADO** | redacción de secretos; `SecretLeakError` antes de enviar; `find_secrets` en QF |
| RK-2B-09 | **MITIGADO** | corpus B1 solo sintético sanitizado + sha256; manipulación detectada → `BenchmarkError` |
| RK-2B-10 | **CERRADO** | contratos OLA 2A intactos; RC6 `15ae1d4` sin commits de OLA 2B |

**Riesgo residual (abierto para la siguiente fase):** precisión de predicado baja
(heurístico en sombra, sin calibración), temporalidad y rumores débiles. No es un
riesgo de seguridad (dry-run), sino de calidad: exige revisión humana total antes
de cualquier uso. Se traslada a la fase de calibración con modelos reales.
