# Cierre técnico PR #116

Base: `ee71dce374efc040003003e7d684254162f37db5`.

Se conectó la sombra al feed y al panel, se centralizó el origen semántico
post-reconciliación, se separaron identidad y versión de propuestas, se añadió
deduplicación entre paquetes, SQLite WAL para revisión multiproceso con outbox
de glosario, y autoridad transaccional de idempotencia dentro de Neo4j.

Las puertas 4 y 6 siguen NO CONFORMES. Neo4j efímero está BLOQUEADO.
