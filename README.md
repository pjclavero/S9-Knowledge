# S9 Knowledge

**S9 Knowledge** es una plataforma self-hosted para convertir documentos, audios,
webs, vídeos de YouTube y notas en un **grafo de conocimiento en Neo4j**, con visor
web y permisos por usuario / personaje / bóveda (workspace).

Pensada para campañas de rol (L5A "Leyenda", Mundo de Tinieblas, Trudvang…): extrae
personajes, criaturas, lugares, facciones, objetos, eventos, combates y sesiones, y
la evolución del conocimiento de cada personaje a lo largo de la campaña.

## Estado actual (desarrollo vs. producción — 2026-08-09)

`docs/project-status.yaml` separa explícitamente tres bloques: `development`
(lo que hay en `main`), `production` (lo desplegado de verdad en VM105) y
`next_release` (el candidato y qué lo bloquea). No los confundas: desde el
merge de V3 (PR #110), `main` y VM105 van desacoplados.

> **«Está en `main`» no significa «está desplegado».** Todo lo que sigue bajo
> *Desarrollo* describe el repositorio. Nada de ello corre hoy en VM105.

> **Desarrollo (`main`, commit `84f9cc7`, último PR mergeado #204):** motor
> vigente `knowledge_v3`. Puerta 4 (cobertura del extractor) cerrada
> **PARCIAL**; Puerta 6 (factividad composicional) cerrada **CONFORME CON
> RESERVAS**; medición del acuerdo determinista∧NVIDIA completada con
> **piloto controlado** aprobado (sin reducir revisión humana todavía);
> programa **multi-partida** con M0/M2/M3/M4/M5a mergeados, **M5b cerrado**
> (contrato, writer, migración fail-closed, M5c y cadena de autorización;
> PRs #147, #150–#153), M1 bloqueado por Nextcloud y M6 pendiente. Carril D
> (E2E de navegador y QA de producto, PR #154) completado. **Carril A**
> (Graph UX V2 del visor, PR #158) y **carril L** (integridad de gates, PR
> #163) cerrados. CI dispara ya en **toda** rama (`branches: ['**']`, PR #160):
> se acabó la lista blanca de prefijos, y con ella RK-16. CI verde en
> `cb874fe`: 14/14 jobs `success` (2026-08-11).
>
> **«Corre» no es «se exige».** De esos 14 jobs, **11 son requeridos** para
> fusionar; tres corren sin bloquear (la especificación JS del grafo y los dos
> meta-gates del carril L). Un job no requerido no impide un merge en rojo: es
> un informe, no una puerta. Ver `RK-20` en
> [risk-register](docs/coordination/risk-register.md).
>
> **Producción (VM105):** sigue siendo `deploy-v0.3.0-rc5.1` (`47bc314`),
> **V3 no está desplegada** y **M5b no está desplegado**. Último estado
> verificado por SSH el **2026-08-06**: visor `s9-knowledge-viewer.service`
> active/running, login propio del visor (Basic Auth retirada del proxy),
> Neo4j 199 nodos / 140 relaciones, 1 administrador, 1 job, 0 ingestas
> (ingesta real bloqueada por doble guard), healthcheck con timer horario
> activo. **Ninguno de estos datos se ha vuelto a leer desde entonces**, y
> desde esa fecha se han ejecutado dos operaciones en el servidor
> ([`docs/53`](docs/53-recuperacion-y-credenciales-2026-08.md): rotación de la
> credencial de Neo4j y restore de ensayo desde `vzdump`, ambas el
> 2026-08-08). El estado del healthcheck está marcado
> `PENDING_VERIFICATION` en `docs/project-status.yaml`: no comprobado, ni
> bueno ni malo.
>
> El estado autoritativo y verificable está en
> [`docs/project-status.yaml`](docs/project-status.yaml). La narrativa de la
> release RC5.1 (histórica, no la línea vigente del repo) sigue en
> [`docs/02-current-state.md`](docs/archivados/02-current-state.md). External
> AI (NVIDIA) en modo sombra; burst orchestrator B1 implementado (B2/B3
> pendientes).

### Línea principal del repositorio: V3

Desde el merge de la PR #110, `main` contiene como línea vigente el subsistema
`knowledge_v3`. V3 no está desplegada en VM105: el bloque anterior describe
producción y sigue siendo independiente del estado del repositorio.

La línea V3 incluye:

- contratos congelados bajo el tag `v3-contracts-frozen-1.0.0`;
- extracción determinista y semántica episódica, seguida de reconciliación de
  propuestas antes de entrar en el motor;
- motor local como autoridad de decisión, con política graduada de negaciones y
  temporalidad implementada tras flags que permanecen **OFF** hasta medirla en sombra;
- ledger temporal bitemporal y writer Neo4j con dry-run y gate explícito del operador;
- evidencia multimodal tipada como `OCR_TEXT`, `TRANSCRIBED_TEXT` o
  `VISUAL_INFERRED`; esta última nunca se autoaprueba;
- transcripción manuscrita integrada en el carril `OCR_TEXT`.

Los Lotes 1, 2, 2b, 3 y 6 del plan técnico ya están completados y mergeados
(PRs #111–#114). Los Lotes 4 y 5 requieren decisiones de producto; la activación
de las políticas graduadas requiere medición en sombra; el despliegue V3 sigue
pendiente. El plan vigente es
[`docs/v3/32-plan-consolidado-extractor-y-nucleo.md`](docs/v3/32-plan-consolidado-extractor-y-nucleo.md).

### Estado de las puertas de calidad V3 (actualizado 2026-08-06)

Tras el merge de V3 en `main` (cadena PRs #116-#118) se ejecutaron dos
programas de calidad adicionales, ambos cerrados:

- **Puerta 4 — cobertura del extractor** (PRs #124-#130): veredicto
  **PARCIAL**. Cobertura E2E de desarrollo 0.607 (umbral ≥0.60, conforme);
  recall de auto-aprobación SIMPLE 0.10 (umbral ≥0.70, no conforme); el
  carril semántico NVIDIA en sombra resultó insuficiente (0.357); invariantes
  de precisión intactos en todo el programa. El carril OCR quedó validado
  con Tesseract 5.5.0 real en VM105 — Tesseract es un requisito de
  instalación adicional, no incluido por defecto (ver
  [`docs/v3/28-requisitos-de-instalacion.md`](docs/v3/28-requisitos-de-instalacion.md)
  y [`docs/v3/42-gate4-cierre-programa.md`](docs/v3/42-gate4-cierre-programa.md)).
- **Puerta 6 — factividad composicional** (PRs #131-#133, #136): veredicto
  **CONFORME CON RESERVAS**, ratificado por el operador el 2026-08-05. El
  operador de discurso reportado quedó conectado al extractor real de
  producción (el rework de B2 corrigió una desconexión detectada por
  revisión); el invariante fail-closed se mide en dos capas. El criterio de
  "acuerdo determinista∧NVIDIA" se abandonó para esta puerta (Postura A del
  operador). Ver
  [`docs/v3/46-gate6-cierre-programa.md`](docs/v3/46-gate6-cierre-programa.md).
- **Medición del acuerdo determinista∧NVIDIA** (PRs #134-#135): el acuerdo
  activo (ambos carriles predicen contenido sin abstenerse) se sostiene en
  27/27 y en 1.000 sobre un corpus de evaluación ampliado. El operador
  ratificó un **piloto controlado**: el subconjunto en acuerdo activo se
  ejercitará con datos reales sin reducir todavía la revisión humana, y la
  decisión de reducirla queda **gateada al despliegue de V3 y a la primera
  ingesta autorizada**. Ver
  [`docs/v3/47-acuerdo-det-nvidia.md`](docs/v3/47-acuerdo-det-nvidia.md) y
  [`docs/v3/48-acuerdo-eval2.md`](docs/v3/48-acuerdo-eval2.md).

Programa **multi-partida** (separación juego/partida, PR #137 de diseño):
en curso. Mergeados M0 (contratos, PR #138), M2 (resolutor ciego,
Invariante 1, PR #140), M3 (writer con ámbito estampado, Invariante 2,
PR #141), M4 (divergencias locales del lore, `local_override_of`, PR #142) y
M5a (selector de partida y aislamiento de ámbito en el visor, PR #143). M1
(mapeo de ingesta Nextcloud→ámbito) sigue **bloqueado** a que Nextcloud
vuelva a estar disponible; **M6** queda pendiente y es *housekeeping*
operativo sobre el grafo de prueba, con aprobación explícita del operador
como requisito. Ver
[`docs/v3/49-multipartida-diseno.md`](docs/v3/49-multipartida-diseno.md) y el
índice [`docs/v3/README.md`](docs/v3/README.md).

### M5b — niebla de guerra y cadena de autorización (cerrado en `main`)

**M5b está cerrado en el repositorio, no desplegado.** Comprende el contrato
canónico `knowledge-visibility/v1` (M5b-0, PR #147), el estampado de
visibilidad desde contrato validado en el writer (M5b-1, PR #150), la
migración fail-closed y el cierre del defecto permisivo (M5b-2/M5b-3,
PR #151), el cierre de ámbito y serializadores (M5c, PR #152) y la cadena de
autorización comprobable de extremo a extremo (M5b-C, PR #153), esta última
tras **siete rondas de revisión adversarial**. El modelo se aplica ya en las
consultas del visor en `main` (`viewer/app/authz/`, `viewer/app/policies/`).

Sobre el **grafo legacy de producción** la resolución es **NO APPLY**: el plan
`12f7278f` pasó el dry-run (339/339 objetos, 0 errores) pero no se aplica,
porque `known_by` está ausente en los 199 nodos y el sellado no tendría valor
semántico. El grafo se conserva intacto, marcado `LEGACY_TEST_GRAPH`, hasta
que V3 demuestre una primera ingesta validada. Ver
[`docs/54-migracion-visibilidad-m5b.md`](docs/54-migracion-visibilidad-m5b.md).

### Carril D — QA de producto y E2E de navegador (PR #154)

La suite Playwright del visor pasó de 24 a **148 pruebas de navegador**,
ejecutadas por el check **requerido** *Login browser contract (Playwright)*
con guard que falla si algo se salta. El carril dejó **11 defectos de
aplicación abiertos** marcados como `xfail(strict=True)` (ACC-01..ACC-09 de
accesibilidad, A-01/A-02 de páginas de error): son defectos de **código**, no
de documentación, y viven en el arnés en vez de pudrirse en un backlog. Ver
[`docs/60-qa-browser-e2e-visor.md`](docs/60-qa-browser-e2e-visor.md).

Dependencias mantenidas al día vía Dependabot: aiohttp actualizado a 3.14.3
por CVE-2026-59881/69243/69244 (PR #128); httpx, argon2-cffi, fastapi,
jinja2 y pytest actualizados (PRs #119-#123).

### Legacy v1/v2

El pipeline RPG v1/v2, sus benchmarks de extractor, el review/ingest anterior y
la documentación narrativa asociada se conservan como **legacy** y como contexto
de la release RC5.1 que continúa en producción. No son el camino de desarrollo
actual. Los documentos históricos están indexados en
[`docs/archivados/INDEX.md`](docs/archivados/INDEX.md).

## Arquitectura (resumen)

```
Fuentes (PDF, texto, audio, YouTube, web, notas)
      │
      ▼
 data-engine  ── OCR / transcripción ── Extractor V3 determinista + semántico
      │
      ▼  reconciliador ── motor local ── ledger temporal
      │
      └── plan de escritura ── gate del operador ──► Neo4j
```

La arquitectura desplegada en producción sigue siendo la de RC5.1, no este
flujo V3.

## Estructura del repositorio

```
s9-knowledge-repo/
├── README.md          · este archivo
├── CHANGELOG.md       · historial de cambios
├── ROADMAP.md         · fases y plan
├── .gitignore
├── .env.example       · variables de entorno (sin secretos)
├── docs/              · documentación (v3/ vigente · archivados/ histórico · current/ histórico)
├── data-engine/       · motor de datos (app/, tests/, docs/…)
├── viewer/            · visor web (FastAPI, desplegado en VM105:8088)
├── shared/            · utilidades compartidas (FUTURO)
├── deployments/       · despliegue VM105
├── scripts/           · scripts auxiliares
└── examples/          · ejemplos
```

Ver [`docs/04-repository-structure.md`](docs/archivados/04-repository-structure.md)
para la fotografía legacy y [`docs/v3/`](docs/v3/) para la línea vigente.

## Puesta en marcha (referencia)

Este repo es una **instantánea de lo ya hecho en el servidor VM105**. No incluye
`.venv`, estado de runtime (`state/`, `output/`, `logs/`, `staging/`), bases de
datos SQLite de runtime, `.env` con secretos ni archivos fuente pesados (PDF/audio).

1. Copia `.env.example` a `.env` y rellena los valores reales.
2. El motor de datos (`data-engine/`) requiere Python 3.11+, Neo4j y Ollama.
   Instalación legacy en
   [`docs/08-deployment-vm105.md`](docs/archivados/08-deployment-vm105.md).
3. El visor (`viewer/`) requiere Python 3.11+ y se sirve con uvicorn.
   Servicio systemd: `s9-knowledge-viewer.service`.

## Seguridad

- No se versionan secretos (`.env`, tokens, claves, certificados) ni datos de
  campaña sensibles (audios, PDFs originales, transcripciones privadas).
- Neo4j y Ollama no se exponen a Internet.
- Acceso externo via `https://knowledge.seccionnueve.duckdns.org` (HTTPS, nginx VM104).
  La autenticación es del propio visor (login con sesiones/CSRF); Basic Auth retirada del proxy.
- La credencial de Neo4j de VM105 se **rotó el 2026-08-08** (credencial nueva
  autentica, la anterior no; grafo intacto). Procedimiento y alcance en
  [`docs/53-recuperacion-y-credenciales-2026-08.md`](docs/53-recuperacion-y-credenciales-2026-08.md).
  Ningún valor de credencial se versiona.
- Ver [`docs/archivados/07-users-permissions.md`](docs/archivados/07-users-permissions.md)
  para el modelo legacy de permisos, y `viewer/app/authz/` + `viewer/app/policies/`
  para el modelo vigente (M5b/M5c) en `main`.
- Ver
  [`docs/21-external-access-and-security.md`](docs/archivados/21-external-access-and-security.md)
  para acceso externo y hardening de la release desplegada.

## Licencia

Uso interno del homelab Sección 9. Sin licencia pública definida todavía.
