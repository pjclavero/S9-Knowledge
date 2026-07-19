# RK-05 — Default de Neo4j del visor: fail-closed

## Qué cambia

`viewer/app/config.py`, setting `S9K_NEO4J_URI`:

- Antes: `bolt://192.168.1.205:7687` (IP productiva como default).
- Ahora: `bolt://127.0.0.1:7687` (loopback), igual que hace `data-engine`.

## Por qué

El default anterior era una IP de producción. Si alguien arrancaba el visor con
`S9K_GRAPH_PROVIDER=neo4j` sin definir `S9K_NEO4J_URI`, la aplicación apuntaba
directamente a la base de datos productiva. El nuevo default apunta a loopback:
falla de forma cerrada respecto a producción (no puede alcanzar prod por
accidente) y es coherente con el resto del repositorio
(`data-engine` ya usa `bolt://127.0.0.1:7687` como default).

## Impacto en producción — ninguno

Producción (RC5.1) **ya define `S9K_NEO4J_URI` explícitamente por entorno**, así
que el cambio de default no altera el comportamiento desplegado. Este cambio no
toca configuración desplegada, ni Ansible, ni systemd, ni relaciones. La regla
operativa sigue siendo: en producción se configura `S9K_NEO4J_URI` de forma
explícita vía entorno.

## Tests

- Nuevo: `viewer/tests/test_neo4j_default_fail_closed.py`. Verifica que el
  default no es un host productivo (`192.168.1.205`, `100.103.100.105`,
  `duckdns`) y que es loopback o vacío. **No abre conexiones de red**: solo
  inspecciona la configuración.
- En laboratorio/CI siempre se usa `S9K_GRAPH_PROVIDER=mock`, por lo que el
  cortafuegos de tests sigue bloqueando cualquier acceso a producción.
