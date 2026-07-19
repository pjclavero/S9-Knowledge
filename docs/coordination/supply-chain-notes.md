# Supply Chain Notes (B-SEC-1)

Notas de configuracion de supply chain para S9 Knowledge. Autor: Agente B1.

## Estado de ecosistemas detectados

| Ecosistema      | Presente | Ubicacion                                             |
|-----------------|----------|-------------------------------------------------------|
| pip             | Si       | `data-engine/requirements.lock` (+ `.in`), `viewer/requirements.txt` |
| github-actions  | Si       | `.github/workflows/ci.yml`                            |
| npm             | No       | No existe ningun `package.json` fuera de node_modules |
| docker          | No       | No existe ningun `Dockerfile`                         |

## Dependabot (`.github/dependabot.yml`)

- `version: 2`.
- pip x2: `/data-engine` y `/viewer`, weekly, limit 5, grupo `patch-minor`
  (patch + minor agrupados en un solo PR). Los **majors NO se agrupan**:
  Dependabot los abre en PRs separados por defecto, para revision manual.
- github-actions: `/`, weekly, limit 3.
- **Sin auto-merge**: no se configura ninguna automatizacion de merge. Toda
  actualizacion requiere revision humana (coherente con la politica de
  "no cambios en prod sin confirmar").

## pip-audit (`.github/workflows/supply-chain.yml`)

- Workflow **separado** de `ci.yml` (no se duplican jobs de test).
- Job `pip-audit`: instala `pip-audit` y audita ambos ficheros de requirements.
- Todos los pasos usan `set -euo pipefail` y **sin `|| true`**: un CVE hace
  fallar el job de forma visible.
- Se anade trigger `schedule` (semanal) ademas de push/PR, para detectar CVE
  nuevas que aparezcan sobre dependencias ya fijadas.

## Pinning de GitHub Actions (observacion)

Estado actual en `ci.yml`: las actions estan fijadas por **tag flotante**
(`actions/checkout@v4`, `actions/setup-python@v5`), no por SHA completo.

- Riesgo: un tag puede ser reapuntado; el pinning por SHA es la practica
  recomendada por OpenSSF Scorecard para inmutabilidad.
- Recomendacion (NO aplicada aqui: `ci.yml` es area del Organizador): migrar a
  pinning por SHA con comentario del tag, p.ej.
  `uses: actions/checkout@<sha>  # v4.x`.
- Dependabot `github-actions` mantiene actualizados ambos formatos (tag o SHA),
  por lo que el pinning por SHA sigue recibiendo PRs de bump.

## SBOM (propuesto, NO aplicado)

- Propuesta: generar SBOM CycloneDX en el workflow de supply chain, p.ej. con
  `cyclonedx-py` (o `pip-audit --format cyclonedx-json`) y publicarlo como
  artefacto del job.
- No se implementa en esta iteracion para mantener el alcance de B-SEC-1
  acotado a Dependabot + pip-audit. Queda como siguiente paso.

## Trivy (NOT_AVAILABLE)

- Trivy aplica principalmente a imagenes de contenedor y sistemas de ficheros.
- **No hay Dockerfile** en el repo, por lo que el escaneo de imagenes no aplica.
- Estado: NOT_AVAILABLE. Reevaluar si en el futuro se anaden Dockerfiles;
  entonces se puede anadir un job Trivy (fs + image) a `supply-chain.yml`.
