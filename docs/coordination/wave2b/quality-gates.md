# Gates de calidad — OLA 2B

Dos revisiones del Supervisor por entrega. Verde no basta.

## Rev.1 (pre-PR): arquitectura, alcance, duplicación, riesgos, pruebas, reutilización de external_ai/contratos.
## Rev.2 (pre-merge): diff real acotado, tests contra PRODUCTO real (sin copias en tests), sin skips injustificados, sin red, sin escritura en dry-run, sin autoaprobación, preserva workspace/evidencia/negación/temporalidad, determinismo, CI del head exacto.

## 12 mutaciones obligatorias (P8, gate 12/12 — cada una DEBE romper un test)
1. workspace vacío aceptado
2. offsets ignorados
3. evidencia inexistente aceptada
4. límite combinatorio quitado
5. JSON inválido aceptado
6. autoaprobación
7. red permitida en tests
8. escritura en dry-run
9. mezcla de workspaces
10. negación ignorada
11. temporalidad perdida
12. determinismo roto

## Dictámenes: CONFORME · CONFORME CON OBSERVACIONES · NO CONFORME · BLOQUEADO. Solo CONFORME permite merge.
