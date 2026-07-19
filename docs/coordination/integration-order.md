# Orden de integración y dependencias

PRs **pequeños**, nunca una rama gigante. Cada PR: contrato + tests + auditoría
independiente + CI verde + diff aislado + modo sombra (sin producción).

## Carril R (RC6) — independiente, no espera a A/B

1. R1 — auditoría pre-RC6 (este PR de coordinación incluye el informe).
2. R2 — documentación pre-RC6 (checklist de release, sin crear RC6).
3. R3 — dictamen pre-RC6.

RC6 **no** incorpora A ni B. La creación/despliegue de RC6 es una decisión posterior
del operador, fuera de este programa.

## Carril A (relaciones) — secuencia por dependencia

```
A-REL-1 contratos internos
   └─> A-REL-2 generador de pares ─┐
   └─> A-REL-3 extractor sintáctico ─┤
   └─> A-REL-4 prompts RPG ──────────┴─> A-REL-5 ensemble sombra ─> A-REL-6 benchmark (docs/41,42)
```

- Ensemble depende de los extractores individuales.
- Benchmark depende del pipeline funcional.
- No declarar mejora si empeoran las entidades existentes.

## Carril B (plataforma)

```
B-SEC-1 Dependabot (independiente, primero)
B-EXP-1c contrato export/import ─> B-EXP-2 export v1 ─> B-IMP-1 import dry-run
B-IMG-1 contrato multimedia ─> B-IMG-2 OCR base ─> B-IMG-3 comprensión visual
B-OBS-1 observabilidad (independiente)
B-UX-1 prototipos (dep. contratos backend) — registro de rutas vía PR Organizador
```

- Import depende del contrato export/import.
- UX depende de contratos backend.

## Dependencias transversales

- La **integración global** de cualquier carril depende de la auditoría del Equipo Q.
- Cambios en áreas compartidas (deps, main.py, workflows, contracts) → PR de
  integración del Organizador, nunca del equipo.

## Reglas de merge

- Sin `--delete-branch` en `gh pr merge`; la rama remota se borra tras confirmar el merge.
- `--force-with-lease` con lease explícito para republicar ramas.
- Ningún equipo modifica `main` directamente.
- Ningún PR se fusiona sin Supervisor rev.2 = CONFORME.
