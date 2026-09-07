# Ingesta V3 de una fuente REAL

Este directorio contiene lo mínimo que un operador necesita para meter un
fichero suyo por la cadena V3 y ver qué produce:

| fichero | qué es |
|---|---|
| `nota-cofradia-de-ambar.md` | la fuente real: una nota de sesión en Markdown |
| `perfil-operador.json` | el `GameProfile` del workspace (ontología: tipos, predicados, títulos) |
| `catalogo-workspace.json` | las entidades que YA existen en el grafo del workspace |

## Cómo se corre (dry-run OFFLINE, sin tocar Neo4j)

```
export PYTHONPATH=data-engine/app
python3 -m knowledge_v3.pipeline.ingest_cli examples/ingesta-v3/nota-cofradia-de-ambar.md \
    --perfil examples/ingesta-v3/perfil-operador.json \
    --catalogo examples/ingesta-v3/catalogo-workspace.json \
    --dry-run
```

`--dry-run` sigue siendo el comportamiento **por defecto**: con `--catalogo` no
se construye ningún driver de Neo4j.

## Los mandos que existen de verdad

Esta tabla se comprueba **contra el parser**, no de memoria
(`knowledge_v3.pipeline.ingest_cli.build_parser`). La versión anterior de este
README negaba que existiera `--apply`. Existe, y `--desde-grafo` además abre
conexión con Neo4j.

| mando | qué hace |
|---|---|
| `--perfil` | `GameProfile` del workspace (obligatorio salvo en `--revisar`) |
| `--catalogo` | entidades ya existentes, leídas de un JSON. Alternativa OFFLINE a `--desde-grafo` |
| `--workspace` `--partida` `--collection` | ámbito de la corrida |
| `--sesion` | sesión de **revelación** (T2): desde qué sesión de juego puede revelarse lo que se ingiere. **Obligatoria con `--partida`** y sólo válida con ella; `0` = conocido desde el inicio. Sin ella, el ámbito de partida no se planifica (`PLAN_SESION_NO_DECLARADA`): no se asume `0` ni se degrada a capa juego |
| `--source-kind` | fuerza el adaptador multimodal |
| `--ahora` `--ingerido-en` | relojes inyectados (ISO-8601 Z) |
| `--dry-run` | no escribe. Es el defecto |
| `--formato` | `markdown` / `json` / `ambos` |
| `--out-dir` | escribe `acta.md`, `informe.json`, `plan.json`, `procedencia.json`, `rollback.json`, `promociones.json` y `decisiones.json` |
| `--desde-grafo` | **abre driver**: el catálogo se LEE del grafo (solo lectura) |
| `--decisiones` | documento de decisiones de identidad. **Se escribe solo cuando la corrida abrió el grafo** (`--desde-grafo` o `--apply`): sin grafo no hay con qué reconciliar, y el mando lo dice en vez de ignorar la ruta en silencio |
| `--promociones` | documento de PROMOCIONES de revisión: sale de cada ingesta con lo que el motor mandó a `REVIEW` y sus motivos, y se lee en la siguiente |
| `--promover` `--nota-promocion` | modo REVISIÓN: **la salida que `REVIEW` no tenía**. Firma la promoción de un claim en revisión asumiendo sus motivos actuales. No fija la decisión: retira los hallazgos firmados y la **recalcula**, así que un `REJECT` o un `ABSTAIN` sobreviven a cualquier promoción, y si los motivos cambian la firma caduca (`PROMOTION_STALE`) y no se aplica |
| `--rollback-out` | dónde guardar el **documento de rollback** del apply: la póliza que `knowledge_v3.writer.cli_rollback` ejecuta para deshacerlo |
| `--revisar` `--aprobar-alta` `--revisor` | modo REVISIÓN: aprueba altas, no ingiere ni conecta |
| `--tipo-alta` | `ENTITY_ID=TIPO`. Declara el `entity_type` de un alta que se aprueba. Hace falta cuando el resolutor no pudo inferirlo — el caso típico en un grafo nuevo. Sin tipo, la creación no se puede construir: el mando **lo dice** y falla cerrado, en vez de descartar el alta en silencio |
| `--apply` | **ESCRITURA REAL**. Exige además el gate del writer |
| `--operador` | quien autoriza el APPLY |
| `--neo4j-uri` `--neo4j-user` `--neo4j-password-file` `--neo4j-database` | conexión. La contraseña va por CAMINO de fichero o stdin, **nunca por argv** |

## Códigos de salida: son API

Un runner desatendido no lee el acta, lee el `rc`. La tabla la fija
`knowledge_v3.writer.exit_codes` y la comparten todos los mandos del writer:

| `rc` | significado |
|---|---|
| `0` | desenlace correcto y limpio (`APPLIED`, o `SIMULATED` en dry-run) |
| `1` | el desenlace **no** es correcto: `BLOCKED` (el gate paró el APPLY), `REJECTED`, `ABORTED`, `INCONSISTENT` |
| `2` | error de uso o de configuración (argparse ya usa 2) |
| `3` | hay altas de entidad sin aprobar: no se escribe |

**Un APPLY que el gate bloquea sale `1`, no `0`.** Antes salía `0` con cero
operaciones escritas y el grafo intacto, mientras que olvidar `--operador` sí
salía `2`: la inconsistencia era interna al mismo mando.

## El acta no afirma lo que no ocurrió

La sección de carencias emite una entrada de escritura **derivada del desenlace
real**, no una frase fija:

| desenlace | código en el acta |
|---|---|
| `SIMULATED` | `SIN_ESCRITURA` — «no se escribió nada», y dice si se abrió driver o no |
| `APPLIED` | `ESCRITURA_APLICADA`, con el número de operaciones |
| `BLOCKED` | `ESCRITURA_BLOQUEADA`, con los códigos del gate |
| otros | `ESCRITURA_NO_COMPLETADA`, con los códigos |

Antes se anexaba siempre `SIN_ESCRITURA | dry-run: no se abrió ningún driver y
no se tocó Neo4j`, incluso con `--desde-grafo` (driver abierto y Neo4j
consultado) y con `--apply` (que no es dry-run). El texto se construía aparte
del resultado, así que podía mentir — y mentía.

## El ruido del driver va por stderr

Con `--desde-grafo`, el driver de Neo4j emite avisos
(`UnknownPropertyKeyWarning`) sobre un grafo recién arrancado. **Medido: salen
por `stderr`, no por `stdout`.** `stdout` queda limpio para el acta y el JSON,
así que una tubería `... | jq` funciona sin filtrar nada.

## Por qué hace falta un catálogo, y qué pasa sin él

El extractor determinista **no tiene reconocedor de entidades propio**: sus
menciones salen del glosario (alias del perfil + nombres del catálogo) o del
patrón `<título declarado> <Nombre Propio>` (defecto D-6 de
`docs/v3/11-e2e.md`). Sin catálogo ni alias, una fuente con nombres nuevos
produce **cero menciones**, y eso no es un fallo del CLI: es lo que hoy hace el
motor.

El CLI lo dice en voz alta en vez de enseñar un cero mudo: si el glosario está
vacío emite `SIN_GLOSARIO` y la sección de carencias del acta lo recoge.

En producción el catálogo lo da Neo4j, con `--desde-grafo`.
