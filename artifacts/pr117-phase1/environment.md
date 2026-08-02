# Entorno

- Host: VM105 (`common`), usuario `root`.
- Repositorio aislado: `/root/S9-Knowledge-pr117-phase1`.
- Python: 3.13.5; dependencias: `data-engine/requirements.lock` en `.venv`.
- Docker Engine: 29.5.2; API 1.54; Compose v5.1.4.
- Imagen: `neo4j:5.26-community`.
- Contenedor: `s9k-v3-writer-test-<uuid>`, `--rm`, sin volúmenes.
- Bolt: puerto aleatorio publicado solo en `127.0.0.1`.
- Credenciales: aleatorias de prueba, no registradas.
- Neo4j productivo: no usado.
