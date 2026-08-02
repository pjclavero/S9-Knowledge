# Neo4j efímero

**BLOQUEADO**: Docker CLI está instalado, pero el usuario no puede abrir
`/var/run/docker.sock`. Los 11 tests de writer real se omitieron por esa causa.
Al activar el fichero E2E se observó además que la regresión de cesación
`test_el_plan_de_una_cesacion_si_supersede` falla con operaciones vacías.

No se usó ningún Neo4j productivo.
