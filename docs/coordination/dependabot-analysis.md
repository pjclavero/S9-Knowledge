# Análisis de Dependabot y supply chain (Equipo B, B-SEC-1)

Estado en `main@6d6c21f`: **no existe** `.github/dependabot.yml`. CI tiene un único
workflow (`.github/workflows/ci.yml`) con 8 jobs. Ecosistemas detectados:

- **pip**: `data-engine/requirements.lock` + `requirements.in`,
  `viewer/requirements.txt`. (Actions instala versiones pinneadas.)
- **github-actions**: `ci.yml` usa `actions/checkout@v4`, `actions/setup-python@v5`.
- **npm**: no hay `package.json` (viewer es Jinja+FastAPI). No aplica por ahora.
- **docker**: no hay `Dockerfile` en el árbol raíz auditado. No aplica por ahora.

## Configuración propuesta (`.github/dependabot.yml` — área compartida, PR Organizador)

```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/data-engine"
    schedule: { interval: "weekly" }
    open-pull-requests-limit: 5
    groups:
      patch-minor: { update-types: ["patch", "minor"] }
    labels: ["dependencies", "data-engine"]
  - package-ecosystem: "pip"
    directory: "/viewer"
    schedule: { interval: "weekly" }
    open-pull-requests-limit: 5
    groups:
      patch-minor: { update-types: ["patch", "minor"] }
    labels: ["dependencies", "viewer"]
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule: { interval: "weekly" }
    open-pull-requests-limit: 3
    labels: ["ci", "dependencies"]
```

Política: **majors en PRs separados**, **sin auto-merge de major**, CI obligatorio
antes de cualquier merge, grupos patch/minor para reducir ruido.

## Controles de supply chain propuestos (jobs de CI, PR Organizador)

- `pip-audit` sobre ambos requirements (falla en vulnerabilidad conocida; sin `|| true`).
- `Trivy`/`Grype` en modo filesystem si se añaden imágenes Docker.
- secret scan (ya existe la comprobación de secretos en deploy; ampliar a repo).
- **pinning de Actions por SHA** cuando sea viable (checkout/setup-python).
- SBOM opcional (CycloneDX) como artefacto.

## Gate

No se fusiona ninguna actualización automáticamente. Todo PR de Dependabot pasa CI +
revisión. `dependabot.yml` y los jobs nuevos entran por **PR de integración del
Organizador** (área compartida `.github/`), no por el equipo B directamente.

Riesgo asociado: RK-09 (major roto) — mitigado por "no auto-merge de major".
