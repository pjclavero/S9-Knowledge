# Ingesta V3 de una fuente REAL

Este directorio contiene lo mínimo que un operador necesita para meter un
fichero suyo por la cadena V3 y ver qué produce, **sin tocar el grafo**:

| fichero | qué es |
|---|---|
| `nota-cofradia-de-ambar.md` | la fuente real: una nota de sesión en Markdown |
| `perfil-operador.json` | el `GameProfile` del workspace (ontología: tipos, predicados, títulos) |
| `catalogo-workspace.json` | las entidades que YA existen en el grafo del workspace |

## Cómo se corre

```
export PYTHONPATH=data-engine/app
python3 -m knowledge_v3.pipeline.ingest_cli examples/ingesta-v3/nota-cofradia-de-ambar.md \
    --perfil examples/ingesta-v3/perfil-operador.json \
    --catalogo examples/ingesta-v3/catalogo-workspace.json \
    --dry-run
```

`--dry-run` es el comportamiento POR DEFECTO y hoy el único: el CLI no
construye ningún driver de Neo4j y no admite `--apply`. Escribir es del
carril C.

## Por qué hace falta un catálogo, y qué pasa sin él

El extractor determinista **no tiene reconocedor de entidades propio**: sus
menciones salen del glosario (alias del perfil + nombres del catálogo) o del
patrón `<título declarado> <Nombre Propio>` (defecto D-6 de
`docs/v3/11-e2e.md`). Sin catálogo ni alias, una fuente con nombres nuevos
produce **cero menciones**, y eso no es un fallo del CLI: es lo que hoy hace el
motor.

El CLI lo dice en voz alta en vez de enseñar un cero mudo: si el glosario está
vacío emite `SIN_GLOSARIO` y la sección de carencias del acta lo recoge.

En producción el catálogo lo da Neo4j. Aquí lo da un fichero porque el dry-run
no abre conexiones.
