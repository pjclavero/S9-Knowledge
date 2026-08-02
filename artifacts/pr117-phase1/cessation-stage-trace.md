# Traza de cesación

## Entrada

Workspace `bench-dev`, source `p7-trace`, texto literal:
`Ilaria Vandreth ya no lidera la Casa del Ciervo.`. Un episodio y un fragmento
con offsets `0..48`.

## Extractor y reconciliador

Claim `claim:extract.deterministic:0e65b095cbb4bc6d`, productor
`extract.deterministic`, predicado `LEADS`, dirección `SUBJECT_TO_OBJECT`,
`negated=true`, `negation_kind=CESSATION`, evidencia
`ef-6982c20f0fd50e1765afb1640aaccf26`, confianza `0.72` y
`review_required=true`. No hubo fusión que alterase polaridad o procedencia.

## Resolución y snapshot

Sujeto `entity:leyenda:ilaria` y objeto `entity:leyenda:casa-ciervo`, ambos
`LINK_EXISTING`, confianza `1.0`. El snapshot original contenía **cero**
afirmaciones positivas activas compatibles.

## Motor y planner

Decisión efectiva `REVIEW`; shadow semántico no configurado (`null`).
Findings determinantes: `EXTRACTOR_REQUESTED_REVIEW` y
`CESSATION_WITHOUT_ACTIVE_ASSERTION`. Plan efectivo `null`; plan de revisión
no aprobado con cero operaciones. Todos sus validadores locales dieron `PASS`.

El control anclado conserva una única positiva activa y obtiene
`supersedes=assertion:lidera:activa`, pero la política graduada mantiene
`REVIEW`, registra `CESSATION_SHADOW_PLAN` y no produce operaciones aplicables.
