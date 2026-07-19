# DAG de dependencias — OLA 2B

```
                 relations/contracts.py (OLA 2A, en main)
                          │
        ┌────────┬────────┼────────┬─────────┐
        │        │        │        │         │
       R1       R2       R3       R4        P7 (RK-05, indep.)
      pares  señales   sintaxis  prompts
        │        │        │        │
        └───┬────┘        │        │
            │             │        │
           R7 consenso ◄──┴────────┤   (reutiliza external_ai/consensus.py)
        (R1,R2 + opcional R3/R4)   │
            │                      │
       R5 LLM local (sombra) ◄─────┘   R6 IA externa (sombra, reutiliza external_ai)
            │        │
            └───┬────┘
                │
              R8 pipeline (R1,R2,R3,R4,R7[,R5,R6])
                │
        ┌───────┴───────┐
       B1 corpus      B2 runner (docs/41,42)
                │
              P8 QA Wave 2B (rebase final contra producto real, 12/12 mutaciones)

Independientes (sin dependencias de código): P1 threat model, P2 observabilidad,
P3/P4/P5/P6 diseños (docs), B1 corpus.
```

## Puede avanzar en paralelo YA (lote 1)
P7, R1, R2, R4, P1 — ficheros disjuntos, sin dependencias entre sí.

## Requiere integración previa
R7 (tras R1+R2) · R8 (tras R1,R2,R3,R4,R7) · R5/R6 (tras R3/R4 estables) ·
B2 (tras R8+B1) · P8 (rebase final).
