# Bancos de medida — saturación del grafo en `/api/graph`

Evidencia reproducible de `docs/72-saturacion-del-grafo-diagnostico.md`.
Medido contra el árbol `e0305cc`. Sólo lectura: **ningún banco escribe en el código medido**.

Ejecutar desde este directorio:

| Comando | Qué mide |
|---|---|
| `python3 harness_gsat.py --mode random --limit 300` | Balance por capa L0→L5 (provider mock) |
| `python3 harness_gsat.py --mode head --limit 300` | **Control A (positivo)**: retención debe ser 100 % |
| `python3 harness_gsat.py --mode head --limit 300 --edge-vis secret` | **Control B (violación)**: la columna de política debe ponerse ROJA |
| `python3 harness_gsat.py --mode comunidades --limit 300` | Caso ALINEADO (orden ≈ topología): el plausible en producción |
| `python3 harness_gsat.py --mode comunidades_barajadas --limit 300` | Misma topología, orden barajado: aísla la alineación |
| `python3 harness_http.py` | Balance por HTTP real: L5a (auth apagada) y L5b (`reviewer` real) + control |
| `python3 harness_neo4j.py` | Camino Neo4j con driver de pega que ejecuta la semántica de `LIMIT` |
| `python3 harness_ablacion.py` | **Ablación** del `LIMIT` del `rel_query` de Neo4j |
| `python3 harness_opciones.py` | Efecto medido de las opciones 0/A/B/C/D |
| `python3 dump_payload.py && node harness_cliente.js payload_n2000.json` | Capa cliente (`graph-core.js` con Node) |

Requisitos: Python con las dependencias del visor, y `node` para la capa cliente.
`jq` no se usa en ningún punto.

Aviso: `harness_gsat.py` usa a propósito un espectador `reviewer` **sin** `admin_full`.
Con `admin_full=True` la política no se evalúa y el control B no puede ponerse rojo:
sería un instrumento muerto (ver §3 del documento).

El mismo aviso vale para `harness_http.py`, y ahí mordió: **no basta con no pasar `admin_full`**.
Si no se fija `S9K_AUTH_ENABLED=true`, el valor por defecto es `False` y el propio
`build_viewer_context` devuelve `admin_full=True`. Y tampoco basta con sobrescribir
`get_visibility_context`: `/api/graph` depende de `get_filtered_provider`, que lo llama como
función normal y no vía `Depends`, así que ese override **se ignora en silencio**.

**Estos bancos NO los ejecuta CI.** Lo que sí se ejecuta en cada corrida es
`viewer/tests/test_saturacion_grafo_caracterizacion.py`, que fija el desplome y lleva su propia
calibración (roja si alguien arregla el truncado y roja si empeora).
