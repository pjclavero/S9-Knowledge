# Tests

Línea base real: 8 passed, 3 failed en 45.53 s. Los tres fallos eran conteos
que incluían las nuevas marcas `V3AppliedOperation`.

Suite enfocada intermedia: 160 passed, 1 failed en 109.15 s. El fallo era una
precondición del fixture E2E: las entidades del snapshot no estaban sembradas
en el Neo4j efímero.

Resultados finales:

- enfocada writer + Neo4j + E2E real: 161 passed en 106.89 s;
- data-engine: 4775 passed, 40 skipped, 3 xfailed;
- viewer: 423 passed, 2 skipped en 14.25 s;
- combinada: 5198 passed, 42 skipped, 3 xfailed en 114.68 s;
- seeds 1/7/42/123: 31 passed cada uno, en 101.08/103.28/98.52/94.15 s.

Los skips de Neo4j que aparecen en la suite combinada son los esperados cuando
esa invocación no lleva `S9K_WRITER_NEO4J_REAL=1`; la ejecución real separada
tuvo cero skips. No hubo fallos ni errores finales.
