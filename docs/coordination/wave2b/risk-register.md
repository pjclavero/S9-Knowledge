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
