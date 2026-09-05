# 53 — Ingesta real: el vertical slice de una fuente de operador

**Carril A.** Rama de trabajo, no toca `BASE RC V3.1` (`f725bd8`).

## 1. El hueco que esto tapa

El repositorio tenía extractor, reconciliador, resolutor, motor, ledger, writer,
autorización y visor. Lo que **no** tenía era una puerta de operador: `pipeline/
runner.py` corre la cadena sobre un **split del gold** y la puntúa con el arnés.
Sus fuentes son documentos del dataset; sus identificadores están redactados a
mano; sus bytes, cuando los hay, son una *reconstrucción* declarada como tal
(`sources.reconstruct_bytes`).

Este bloque añade la otra puerta:

```
export PYTHONPATH=data-engine/app
python3 -m knowledge_v3.pipeline.ingest_cli examples/ingesta-v3/nota-cofradia-de-ambar.md \
    --perfil examples/ingesta-v3/perfil-operador.json \
    --catalogo examples/ingesta-v3/catalogo-workspace.json \
    --dry-run
```

`fichero -> SourceInput -> SourceCase -> episodios -> evidencia -> extracción ->
reconciliación -> resolución -> motor -> GraphMutationPlan`.

**Nunca escribe.** No hay `--apply`, no se construye ningún driver y pasar la
bandera es un error explícito del parser, no un no-op. La escritura contra un
Neo4j efímero es del carril C.

## 2. El defecto GATE4-03, reproducido y corregido

`SourceEpisode.from_dict` rechazaba un episodio de texto que sencillamente no
trajera `speaker`, `turn` ni `table`:

```
ContractV3Error: faltan campos obligatorios: ['speaker', 'table', 'turn']
```

Causa: el JSON Schema congelado **no** los pone en `required`, pero el dataclass
los declaraba sin `default`, así que `V3Document._optional_names()` no los veía.
El modelo Python era más estricto que el contrato publicado.

Corrección: los tres llevan `default=None`. **No** entran en `OMIT_IF_NONE`
porque el schema los declara `nullable`, así que `to_dict()` los sigue emitiendo
con `null` y la serialización es byte a byte la de antes: sólo se relaja la
LECTURA.

El `xfail(strict=True)` y su entrada `GATE4-03` de `.github/xfail-registro.txt`
se retiran a la vez — dejar la entrada pondría el gate en rojo por su segunda
dirección.

La comprobación que evita la reincidencia no mira ese campo: **parsea los
schemas** y exige, para *toda* la familia de contratos, que
`properties - required ⊆ _optional_names()`. Hoy el único divergente era el
episodio; mañana se detecta solo.

## 3. El contrato entre carriles: `ingest-run/v1`

Módulo `knowledge_v3/pipeline/ingest_report.py`. Es la frontera que **B**, **C**
y **D** consumen, para que nadie se acople a `SourceRun` (un dataclass privado
del orquestador, con objetos vivos dentro).

| clave | contenido | quién la consume |
|---|---|---|
| `run` | fuente, `input_hash`, workspace, perfil, instante, `writer_mode` | todos |
| `asset`, `episodes`, `evidence` | documentos `source-asset` / `source-episode` / `evidence-fragment` | trazabilidad |
| `mentions`, `resolutions` | `entity-mention`, `entity-resolution` | B |
| `candidates.link_existing` / `.create_entity` / `.review_identity` | proyección de las resoluciones **por su campo `action`** | **B** |
| `claims`, `abstentions` | `claim-proposal` | D |
| `decisions` | veredicto del motor + `findings` con sus dos códigos | **D** |
| `assertions` | `fact-assertion` | ledger / visor |
| `plan` | `graph-mutation-plan` sellado, con `plan_hash` | **C** |
| `review_plan` | plan de revisión | D |
| `contradictions` | conflictos que el motor adjuntó a la decisión | D |
| `totals` | conteos, todos `len()` de las listas de arriba | auditoría |
| `carencias` | lo que hoy no hay, con su código y su motivo | todos |

Dos reglas de este documento:

1. **Ningún campo se inventa.** Cada documento sale del `to_dict()` de su
   contrato congelado. `candidates`, `decisions`, `abstentions` y
   `contradictions` son *proyecciones*: reordenan lo que ya está.
2. **Ningún hueco se rellena con un cero.** Lo que el motor no produce sale en
   `carencias`. El proyecto ya tuvo un contador que contaba claves de
   diccionario y siempre daba 2.

`findings` publica los **dos** códigos de cada hallazgo: el canónico del
contrato (`REVIEW_ENTITY`) y el descriptivo del motor
(`ENTITY_NOT_IN_SNAPSHOT`). Publicar sólo el canónico deja seis causas
distintas indistinguibles, que es justo lo que un revisor necesita separar.

## 4. La corrida real

Fuente: `examples/ingesta-v3/nota-cofradia-de-ambar.md` (349 bytes, MARKDOWN).
Acta e informe: `docs/v3/ingesta-real/`.

| magnitud | n |
|---|---|
| episodes | 7 |
| evidence | 7 |
| mentions | 10 |
| resolutions | 10 |
| LINK_EXISTING | 9 |
| CREATE_ENTITY | 1 |
| claims | 5 |
| abstentions | 2 |
| decisions | 5 (ACCEPT 1, REVIEW 2, ABSTAIN 2) |
| assertions | 1 |
| plan_operations | 2 |

`ALLY_OF(Cofradia de Ambar, Casa del Ciervo)` es lo único que el motor aprueba,
con evidencia literal verificada. La frase negada
(*«Sela Marrec no pertenece al Consejo de Umbra»*) llega al motor como
`MEMBER_OF` **negado** y sale en `REVIEW`: no se asserta como hecho.
`Bren Halloway` no está en el grafo y se propone como alta (`CREATE_NEW`,
`NO_CANDIDATE`) — eso es lo que el carril B recoge.

## 5. Carencias observadas (no supuestas)

* **D-6 — el extractor no tiene reconocedor de entidades propio.** Sus menciones
  salen del glosario (alias/facciones/títulos del perfil + nombres del catálogo)
  o del patrón `<título declarado> <Nombre Propio>`. Una fuente con nombres que
  nadie declaró produce **cero menciones**. Medido: con `aliases`, `factions` y
  `titles` vacíos, la misma nota da 0 menciones y el informe emite
  `SIN_GLOSARIO` + `SIN_MENCIONES`. **Esto es hoy el límite real de "meter una
  fuente nueva", no el CLI.**
* **El snapshot del motor sale del catálogo, no del resolutor.** Sin pasar
  `catalog_entities` a `KnowledgePipeline.run`, TODO cae por
  `ENTITY_NOT_IN_SNAPSHOT` aunque el resolutor haya enlazado con confianza 1.0.
  Observado durante el desarrollo de este CLI y corregido en él.
* **`review_plan` no lleva operaciones.** El planner sólo materializa las
  `ACCEPT`. El carril D tiene que consumir `decisions`, no
  `review_plan.mutation_operations`. Declarado como
  `PLAN_REVISION_SIN_OPERACIONES`.
* **Sin escritura.** `SIN_ESCRITURA` es una carencia permanente de este CLI por
  diseño.
* **Los identificadores no son los del gold.** El normalizador los deriva por
  sha256 (`ep-…`, `ef-…`); esta salida no es comparable con el arnés, y no
  pretende serlo (defecto D-4, `11-e2e.md §5`).

## 6. Qué falta para llegar a Neo4j

1. Un **Neo4j efímero** (contenedor de prueba) y su gate — carril C.
2. `OperatorRequest` con `apply=True` exige driver, `operator_id`,
   `expected_plan_hash` y las declaraciones de entorno del writer. El plan que
   este CLI publica ya trae `plan_hash` y `snapshot_id`: es exactamente lo que
   ese gate compara.
3. El catálogo, que aquí es un fichero, en producción lo da el propio grafo.
   Mientras el dry-run no abra conexiones, seguirá siendo un fichero.
