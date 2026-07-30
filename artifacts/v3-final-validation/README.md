# Validación final V3 — artefactos

Salidas de la campaña de validación final del rediseño V3, ejecutada sobre la
rama `integration/v3-final-core-validation` el 2026-07-30.

## Qué hay aquí

| Fichero | Qué es |
|---|---|
| `gate4-negation-metrics.json` / `.md` | Puerta 4 — negaciones E2E en sombra: las 10 métricas por familia y sus gates. |
| `gate5-authority.json` | Puerta 5 — registro por claim de los escenarios C1 (Ollama real), C2 (NVIDIA real) y D-R (determinista+semántico+reconciliador). |
| `gate6-raw-lanes*.json` | Puerta 6 — salida **cruda** de cada carril sobre el corpus de factividad. Es la medida; no se edita a mano. |
| `gate6-factivity-matrix.json` / `.md` | Puerta 6 — matriz por frase, prueba de vacuidad y veredicto por gate. |
| `gate6b-human-review.md` | Puerta 6B — revisión humana: catálogo de auditoría, 36+24 casos y no-mutación del glosario. |
| `e2e-results.md` | E2E-01..E2E-14 por la ruta completa con writer en dry-run. |
| `skips-classification.md` | Todo skip de la suite, clasificado. Los **accidentales** son el hallazgo. |
| `reproducibility.md` | Suites deterministas bajo `PYTHONHASHSEED=1,7,42,123`. |
| `perf-notes.md` | Duraciones y latencias. **Informativo: no condiciona gates.** |
| `proposals/` | Propuestas de revisión **reales**, exportadas por el pipeline, listas para servir al visor. |

## Guiones de medida

Viven aquí y **no** bajo `data-engine/` a propósito. El repo tiene un guardián
—`test_knowledge_v3_negation_battery.py::test_la_bateria_no_esta_enchufada_a_ningun_flujo_automatico`—
que prohíbe que nada bajo `data-engine/`, `scripts/`, `deploy/`, `shared/` o
`tests/` cargue o mida el split `negation`: la batería es *gold*, no un paso de
pipeline. Poner los guiones en `artifacts/` respeta esa frontera.

| Guion | Uso |
|---|---|
| `gate6_factivity_runner.py` | Ejecuta los carriles sobre el corpus de factividad y escribe el JSON crudo. |
| `gate6_report.py` | Convierte el JSON crudo en matriz, gates e informe. Separado del runner: medir cuesta minutos y llamadas reales; analizar es instantáneo. |
| `gate5_authority_runner.py` | Registro de autoridad por claim con proveedores reales. |

Invocación (las credenciales se cargan al entorno y **nunca** se escriben en
ningún artefacto):

```bash
set -a; . ~/.config/s9k/nvidia.env; set +a
S9K_REPO_ROOT=$PWD PYTHONPATH=data-engine/app \
  python3 artifacts/v3-final-validation/gate6_factivity_runner.py \
    --lanes policy,det,combined --tag=-local
```

## Dos advertencias de lectura

**1. Vacuidad.** Un carril que no extrae nada aprueba todos los gates de
seguridad por inanición: cero hechos en preguntas es trivial si también hay cero
hechos en los controles positivos. Por eso `gate6_report.py` mide primero la
vacuidad y, si un carril es vacuo, marca sus gates como **no interpretables** en
vez de darlos por buenos.

**2. El corpus de factividad es `dev-synthetic`.** Mide cobertura de familias de
no-factividad. **No** es evidencia de generalización, en la línea de lo ya
aprendido con el motor v2 (predicado 0,81 en dev==test → 0,24 en real).
