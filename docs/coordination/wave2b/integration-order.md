# Orden de integración — OLA 2B

PRs pequeños, draft, contra main. Merge solo con Supervisor CONFORME + CI verde.

```
1. Coordinación documental (este PR)
2. P7 RK-05 (fail-closed viewer neo4j default)   [independiente, prioridad]
3. R1 generador de pares
4. R2 señales heurísticas
5. R4 prompts RPG
6. R3 adaptador sintáctico
7. R7 consenso (reutiliza external_ai/consensus)
8. R5 LLM local sombra · R6 IA externa sombra
9. R8 pipeline
10. B1 corpus · B2 runner + docs/41,42
11. P1/P2/P3/P4/P5/P6 (threat model, observabilidad, specs de diseño)
12. P8 QA Wave 2B rebasado contra producto real
13. PR de integración global (áreas compartidas: pytest.ini testpaths, etc.)
14. Actualización final del tablero
```

El DAG real manda: si una dependencia cambia, se documenta y se reordena. Los
bloques independientes (P1–P6, B1, P7) no esperan al núcleo.

## Ejecución real completada (2026-07-19)

Secuencia de merge del **Lote 3** (paso 9–14 de la lista), por `git log origin/main`:

1. B1 corpus (#79) → `c92ab6b`
2. R8 pipeline (#80) → `b362a9d`
3. B2 runner + benchmark (#81) → `91f972f`
4. D1 runtime docs (#82) → `4ad4289`
5. QF QA final transversal (#83) → `74286ff`
6. Mapa de integración Lote 3 (#78) → `0909b8f`

Actualización final del tablero y cierre en
[`lote3-closeout.md`](lote3-closeout.md). **OLA 2B integrada y cerrada** en
`main` @ `0909b8f`. RC6 `15ae1d4` intacta; sin tag/Release/despliegue RC6.
