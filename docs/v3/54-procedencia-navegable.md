# 54 — Procedencia navegable: de la asercion al literal y a la fuente

**Equipo 1, tanda 2.** Cierra la unica propiedad del vertical slice que un
supervisor independiente dejo en rojo: *«la fuente es navegable»*.

## 1. El hallazgo que lo origina

Ejecutada la cadena completa (plan real de ingesta → writer → Neo4j real), el
grafo resultante contenia **solo**:

    V3Entity x2 · V3Assertion x1 · V3AppliedOperation x2

Cero nodos de episodio, fragmento o asset; cero aristas de una asercion hacia
su evidencia. El literal que sostiene el conocimiento vivia unicamente en el
`informe.json` que imprime el CLI de ingesta —un fichero suelto que **ningun
componente persiste**—. La procedencia se recuperaba siguiendo a mano una
cadena de identificadores por fuera del grafo.

Lo que si existia era la cadena de ids: `writer/executor.py::_provenance`
estampa en cada nodo escrito `evidence_fragment_ids` y `source_asset_id`. Eran
referencias **sin destino**.

## 2. Lo que se persiste

Tres etiquetas nuevas, proyeccion plana de tres contratos **ya congelados**:

| Etiqueta      | Contrato                          | Identidad durable              |
|---------------|-----------------------------------|--------------------------------|
| `V3Source`    | `source-asset/v3-internal-v1`     | `(workspace, source_asset_id)` |
| `V3Episode`   | `source-episode/v3-internal-v1`   | `(workspace, episode_id)`      |
| `V3Evidence`  | `evidence-fragment/v3-internal-v1`| `(workspace, fragment_id)`     |

Cada nodo lleva `provenance_contract` con el identificador del contrato del que
sale, `workspace` y `partida_id` estampados por el escritor (nunca por el
documento), y las propiedades escalares del contrato con **su nombre del
contrato**. Un bloque de hash `{algorithm, value}` se proyecta a
`<campo>_value`; lo que Neo4j no admite (mapas anidados, listas de mapas) **no
se escribe y se declara** en `omitted_fields` del resultado, para que nadie
confunda «no esta» con «no lo habia». Medido en la corrida real:

* `V3Source`: `processing_policy`, `provider_trace`
* `V3Episode`: `metadata`, `provider_trace`, `quality`
* `V3Evidence`: `provider_trace`

## 3. Las aristas

    (:V3Source)-[:HAS_EPISODE]->(:V3Episode)-[:HAS_FRAGMENT]->(:V3Evidence)
                                                                    ^
                                          (:V3Assertion)-[:SUPPORTED_BY]-+
                                                 |
                                    [:HAS_SUBJECT|HAS_OBJECT]
                                                 v
                                            (:V3Entity)

Ninguna anade una referencia nueva: **materializa** una que ya existia como
campo de un contrato congelado o como propiedad que el writer ya estampaba.

| Arista         | Referencia que materializa                        |
|----------------|---------------------------------------------------|
| `HAS_EPISODE`  | `source-episode.source_asset_id`                  |
| `HAS_FRAGMENT` | `evidence-fragment.episode_id`                    |
| `SUPPORTED_BY` | `evidence_fragment_ids` (estampada por el writer) |
| `HAS_SUBJECT`  | `subject_entity_id` de la asercion                |
| `HAS_OBJECT`   | `object_entity_id` de la asercion                 |

Los extremos se emparejan **siempre por la clave durable**. El `elementId` de
Neo4j no se guarda, no se devuelve y no aparece en ninguna consulta del modulo.

## 4. CARENCIA DE CONTRATO (declarada, no disfrazada)

**Ningun contrato congelado nombra estas etiquetas ni estos tipos de
relacion.** `graph-mutation-plan/v3-internal-v1` solo admite relaciones entre
entidades (`LINK_EXISTING`, `PROJECT_RELATION`), y sus operaciones no pueden
expresar «escribe este fragmento de evidencia». Por eso la procedencia:

* **no viaja en el plan** y no la ejecuta `execute_plan`;
* se escribe en **su propia transaccion**, despues de la del plan.

Esto es una carencia real que el equipo de contratos deberia cerrar: hoy la
forma de los nodos de procedencia la fija este modulo derivandola de los tres
contratos de documento, no un contrato de grafo. Se declara aqui en vez de
fabricar un contrato nuevo por cuenta propia.

## 5. Por que NO va dentro de la transaccion del plan

La transaccion del writer es todo-o-nada **sobre el conocimiento**. Meterle una
escritura que el plan no declara convertiria un fallo de procedencia en un plan
revertido —y el plan es lo que un operador aprobo—. Por la misma razon, un
fallo del volcado se **anota** (`PROVENANCE_FAILED`) y no propaga: el
conocimiento ya esta escrito, una excepcion tardia no lo desharia y lo unico
que conseguiria es ocultar que el plan si se aplico. El diagnostico deja
constancia de que ese conocimiento quedo sin procedencia navegable.

## 6. Frontera de seguridad: lo que este bloque NO cruza

Persistir evidencia pone **el literal de la fuente** en la base. La regla
aplicada es fail-closed:

1. **Etiquetas nuevas.** El visor (`viewer/app/providers/neo4j_provider.py`)
   consulta exclusivamente `(n:Entity)` y `(n:Entity)-[r]->(m:Entity)`.
   Ninguna de sus consultas alcanza un nodo de procedencia. **Observado** en la
   corrida real: `nodos_visor = 0`, `aristas_visor = 0`.
2. **Sin `visibility`.** Los nodos se escriben SIN propiedad de visibilidad ni
   `known_by`, que es el estado que el motor de politicas trata como DENY. Un
   olvido no publica nada.
3. **Sin superficie de lectura nueva para el usuario final.** `provenance.trace`
   es una lectura de diagnostico (misma categoria que `writer/reads.py`), no un
   endpoint.

**Lo que queda ABIERTO y no es de este equipo:** exponer evidencia a un lector
final exige una decision de visibilidad —¿que ve un jugador del literal que
sostiene un hecho que si puede ver?— coherente con `LORE_ANONIMO = DENEGADO` y
con que la ausencia de partida no concede visibilidad. Esa decision es de
authz/politicas. Mientras no exista, la evidencia solo es alcanzable por quien
ya tiene acceso directo a la base. **Y hay un hecho nuevo que el operador debe
conocer: el texto literal de las fuentes pasa a estar en reposo en Neo4j**,
protegido por el control de acceso de la base y no por la visibilidad por
personaje.

**Alcance de lo que se vuelca:** la etapa 7b persiste **todos** los episodios y
fragmentos de la corrida, no solo los que sostienen una asercion aprobada. Es
deliberado —lo que se manda a revision tambien necesita su evidencia
localizable— y es material en reposo adicional: entra en la misma advertencia
del parrafo anterior.

## 7. Idempotencia

Sin `MERGE` —la guardia `cypher.assert_safe` lo prohibe, y con razon: un MERGE
ciego crea o pisa segun el estado del grafo—. Cada escritura comprueba primero
la ausencia con una consulta acotada por la clave durable y solo entonces hace
`CREATE`. Ademas, `bootstrap_writer_schema` aplica tres restricciones de
unicidad `(workspace, <id>)` sobre las tres etiquetas: la comprobacion evita el
duplicado, la restriccion lo hace **imposible**.

Observado repitiendo la ingesta completa: `total_created == 0`, recuentos
identicos y huella del grafo identica.

## 8. Como reproducir la evidencia

    S9K_WRITER_NEO4J_REAL=1 python3 \
      artifacts/equipo1-procedencia/demostracion_procedencia_navegable.py

Levanta un Neo4j efimero (mismo mecanismo que la fixture de
`test_knowledge_v3_writer_neo4j_real`), recorre la cadena V3 desde bytes con
`apply=True`, y consulta el grafo despues. La salida completa esta en
`artifacts/equipo1-procedencia/evidencia-ejecucion.txt`.

Lo que no necesita contenedor esta en
`data-engine/app/tests/test_knowledge_v3_writer_provenance.py` y corre siempre.

## 9. Lo que sigue faltando

* Un contrato de grafo que nombre estas etiquetas y aristas (§4).
* La decision de visibilidad de la evidencia (§6).
* El `informe.json` del carril A (`ingest-run/v1`) sigue siendo la unica sede
  de los diagnosticos y las carencias de una corrida. Este bloque saca del
  informe la **procedencia**; no el resto.
