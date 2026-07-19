# Plantilla de checkpoint

Se publica al terminar cada bloque. Copiar y rellenar.

```text
CHECKPOINT — BLOQUE N

Bloque:
Objetivo:
Estado:
Auditoría:
Rama:
Worktree:
PR:
Head:
Merge commit:
Tests específicos:
Tests globales:
Mutation checks:
CI de PR:
CI post-merge de main:
Supervisor:
Hallazgos:
Correcciones:
Riesgos residuales:
Producción:
Neo4j:
Ingestas:
S9K_ALLOW_REAL_INGEST:
release/rc6-candidate:
Tag RC6:
Release RC6:
Despliegue:
Main final:
Autorización del siguiente bloque:
```

La última línea (`Autorización del siguiente bloque:`) debe terminar con exactamente una de:

```text
SIGUIENTE BLOQUE AUTORIZADO
SIGUIENTE BLOQUE NO AUTORIZADO
PROGRAMA BLOQUEADO
```

## Invariantes que todo checkpoint debe reafirmar

- `release/rc6-candidate = 15ae1d4f364b19e601bbe32a5e3904e889c8bf65`
- `Tag RC6 = no creado`, `Release RC6 = no creada`, `Despliegue RC6 = no realizado`
- `Producción = intacta`, `Reinicios = 0`, `S9K_ALLOW_REAL_INGEST = off`
- `Neo4j = 199 nodos / 140 relaciones` (sin cambios), `Ingestas reales = 0`
