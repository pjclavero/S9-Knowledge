# PR117 fase 1

Base `55daf6cdafefbbdd5d6735e13e97d88e4c5d20a0`. Validación ejecutada en
VM105 contra Neo4j 5.26 Community efímero, sin URI, credenciales, red ni
volumen productivos.

Se añadió el bootstrap explícito e idempotente de la restricción compuesta de
`V3AppliedOperation`, cobertura real ID-01..ID-08 y regresiones de cesación.
Las operaciones vacías eran correctas: el caso no tenía afirmación activa y el
motor falló cerrado con `CESSATION_WITHOUT_ACTIVE_ASSERTION`.

Puertas 4 y 6 permanecen **NO CONFORME**. No se ejecutó held-out.
