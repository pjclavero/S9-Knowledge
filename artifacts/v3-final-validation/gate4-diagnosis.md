# Diagnóstico de puerta 4

La política graduada no es la causa dominante del recall SIMPLE de 0.10. La
corrida principal usa `negation_policy_at_engine=true`, pero es una ablación
`local_only`: el extractor determinista sólo emitió decisiones para 8 de los 56
claims evaluables (cobertura 0.143) y sólo cubrió 2 de los 11 SIMPLE. De esos
dos, uno fue autoaprobado y el otro se abstuvo. Por tanto, el numerador SIMPLE
es 1/10 casos esperados como autoaprobables (0.10); los nueve restantes no
llegaron a la política como candidatos autoaprobables. No hay evidencia en la
medición de que un umbral de confianza de 0.6 retuviera esos nueve: son
`NO_OUTPUT`.

El SIMPLE cubierto que falla es `NEG-SIMPLE-01`. El extractor produjo el claim
sin polaridad (`predicted_negated=false`, sin `negation_kind`) y el motor lo
dejó en `ABSTAIN`; el informe del runner identifica `PREDICATE_ABSENT` en la
construcción con subordinada larga y una tercera entidad. Éste explica también
el único error de alcance entre los ocho casos cubiertos: 7/8 correctos =
0.875, por debajo de 0.95. No es un umbral graduado que deba relajarse, sino una
limitación de extracción/alineamiento de predicado y alcance en ese caso.

La cobertura global baja tiene causas cuantificadas independientes de la
política: 48/56 claims evaluables no tuvieron decisión; `ambar-escaneo` aporta
22 episodios de imagen sin texto y, sin proveedor visual/OCR, cero claims; la
sombra semántica tuvo 0 registros porque la ablación no admite proveedores. La
variante donde el extractor fuerza revisión conserva exactamente la misma
cobertura (0.143) y el mismo alcance (0.875), pero reduce el recall global de
autoaprobación de 0.0625 a 0.0, confirmando que esa bandera sí bloquea lo ya
extraído, aunque no explica el techo principal de cobertura.

No se modifican umbrales, gates, corpus ni artefactos de medición.

El corpus de factualidad contiene además un condicional sin marcador léxico
explícito: «Cumplidos los tres inviernos de servicio, ... quedaría libre».
Detectar `-ría` aisladamente no es limpio: la misma terminación aparece en
sustantivos (`armería`, `cofradía`) y una lista de excepciones sólo trasladaría
el sobreajuste. Hasta disponer de análisis morfológico determinista, el detector
léxico deja esta construcción como limitación conocida en vez de memorizar su
prefijo.

## Adenda post-F7-1 (observación del revisor final)

El revisor señaló que el «0 operaciones sombra destructivas» se midió antes
del fix F7-1 (cuando `SUPERSEDE_ASSERTION` era inalcanzable) y pidió
re-medición. Re-ejecutado el runner completo sobre HEAD con F7-1/F7-2
integrados: salida **byte-idéntica** a la versionada. El 0 es estructural,
no artefacto: (1) la evaluación sombra solo aplica a claims de origen
semántico y esta corrida es del carril determinista; (2) las cesaciones del
corpus no tienen afirmación positiva vigente en el snapshot de partida, por
lo que terminan en `CESSATION_WITHOUT_PRIOR`, nunca en supersesión. La
verificación post-fix de la supersesión real vive en la puerta 7 (VM105,
E2E de cesación aplicada contra Neo4j efímero, 53 passed).
