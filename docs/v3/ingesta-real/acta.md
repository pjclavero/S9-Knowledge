# Acta de ingesta V3 — nota-cofradia-de-ambar.md

## SOURCE

- fichero: `examples/ingesta-v3/nota-cofradia-de-ambar.md`
- source_kind: `MARKDOWN`  (349 bytes)
- INPUT HASH: `sha256:64628f643b15eb13da95a0e71e1830b442cc073d18c93671a5916196335d5b73`
- workspace: `ws-cofradia`  ·  perfil: `generic`
- collection: `collection:ws-cofradia`
- instante inyectado: `2026-09-05T10:00:00Z`
- modo del writer: **DRY_RUN**  ·  apply: `False`
- catalogo declarado: 6 entidades (5 enlazables)
- latencia: 252.336 ms  ·  llamadas a proveedor: 0

## Conteos

| magnitud | n |
|---|---|
| episodes | 7 |
| evidence | 7 |
| mentions | 10 |
| resolutions | 10 |
| link_existing | 9 |
| create_entity | 1 |
| review_identity | 0 |
| claims | 5 |
| abstentions | 2 |
| decisions | 5 |
| assertions | 1 |
| contradictions | 0 |
| plan_operations | 2 |
| review_operations | 0 |
| decisions_by_outcome | {'ABSTAIN': 2, 'ACCEPT': 1, 'REVIEW': 2} |

> Todos estos numeros son `len()` de las listas que este mismo
> informe publica: se pueden recontar sobre el JSON.

## EPISODES

| episode_id | seq | modality | texto (inicio) |
|---|---|---|---|
| ep-cbc9027cc26ecb38c74b22672f2706c5 | 0 | TEXT | # Nota de sesion — La Cofradia de Ambar |
| ep-7f98a67a1e4f40d5fc20a062ce122ee4 | 1 | TEXT | ## Quien estaba en la mesa |
| ep-e561281a791bcf14a75fb4fbf2ad8856 | 2 | TEXT | Sela Marrec es miembro de la Cofradia de Ambar y vive en Vado Alto. |
| ep-1dc2444539a37682a25d43ebc755c3d3 | 3 | TEXT | Bren Halloway lidera la Cofradia de Ambar desde la tercera luna de la  |
| ep-d60ef1cda9ec71cb1b5ef75c5f28867b | 4 | TEXT | ## Lo que se acordo |
| ep-35a91c10f843f2c81f6065c1cea9d71d | 5 | TEXT | La Cofradia de Ambar es aliada de la Casa del Ciervo. |
| ep-3ddffc13da7acd7d19c44d3fc3ad6949 | 6 | TEXT | Sela Marrec no pertenece al Consejo de Umbra. |

## EVIDENCE

| fragment_id | episode_id | literal |
|---|---|---|
| ef-ebffcfe91b028d2a131b9f21a138b3a6 | ep-cbc9027cc26ecb38c74b22672f2706c5 | # Nota de sesion — La Cofradia de Ambar |
| ef-5e77e4e52224529b7e273b063cba82f2 | ep-7f98a67a1e4f40d5fc20a062ce122ee4 | ## Quien estaba en la mesa |
| ef-d6fdfb05879f7b13c8b910d49c15cdd4 | ep-e561281a791bcf14a75fb4fbf2ad8856 | Sela Marrec es miembro de la Cofradia de Ambar y vive en Vad |
| ef-7bd17977ce01366cee8f198967d47dd3 | ep-1dc2444539a37682a25d43ebc755c3d3 | Bren Halloway lidera la Cofradia de Ambar desde la tercera l |
| ef-c96fa7e3bbf189f9cd1fd7f5a2db9e71 | ep-d60ef1cda9ec71cb1b5ef75c5f28867b | ## Lo que se acordo |
| ef-dcac9508aeb6d063682cc7b47009735a | ep-35a91c10f843f2c81f6065c1cea9d71d | La Cofradia de Ambar es aliada de la Casa del Ciervo. |
| ef-2d98b0404929eee4d2405ffd115c23b1 | ep-3ddffc13da7acd7d19c44d3fc3ad6949 | Sela Marrec no pertenece al Consejo de Umbra. |

## ENTITIES (menciones detectadas)

| mention_id | superficie | tipos | conf | episode_id |
|---|---|---|---|---|
| 46fff6878efeb241 | Cofradia de Ambar | Faction | 0.9 | ep-cbc9027cc26ecb38c74b22672f2706c5 |
| 2fd8d6debbdbeb0d | Sela Marrec | Character | 0.9 | ep-e561281a791bcf14a75fb4fbf2ad8856 |
| 3ce43b3607ff715b | Cofradia de Ambar | Faction | 0.9 | ep-e561281a791bcf14a75fb4fbf2ad8856 |
| 7085d008f11b69fe | Vado Alto | Location | 0.9 | ep-e561281a791bcf14a75fb4fbf2ad8856 |
| b6fbc9c0ac27d2ad | Bren Halloway | Character | 0.9 | ep-1dc2444539a37682a25d43ebc755c3d3 |
| 452c2289a148da59 | Cofradia de Ambar | Faction | 0.9 | ep-1dc2444539a37682a25d43ebc755c3d3 |
| aef08a46c08a7164 | Cofradia de Ambar | Faction | 0.9 | ep-35a91c10f843f2c81f6065c1cea9d71d |
| bc6211e9d6fb8654 | Casa del Ciervo | Faction | 0.9 | ep-35a91c10f843f2c81f6065c1cea9d71d |
| 188635668a576b55 | Sela Marrec | Character | 0.9 | ep-3ddffc13da7acd7d19c44d3fc3ad6949 |
| 370f74bcf742491c | Consejo de Umbra | Faction | 0.9 | ep-3ddffc13da7acd7d19c44d3fc3ad6949 |

## LINK_EXISTING (menciones enlazadas a entidades del grafo)

| resolution_id | entidad | conf | motivos |
|---|---|---|---|
| resolution:a8e045a6b3434913 | entity:sela-marrec | 1.0 | STRONG_MATCH,EXACT_NAME,SURFACE_SIMILARITY,TYPE_COMPATIBLE |
| resolution:9bae8dcc4552d198 | entity:sela-marrec | 1.0 | STRONG_MATCH,EXACT_NAME,HISTORY_SESSION,SURFACE_SIMILARITY,TYPE_COMPATIBLE |
| resolution:72334b1c8f2c04a3 | entity:consejo-umbra | 1.0 | STRONG_MATCH,EXACT_NAME,SURFACE_SIMILARITY,TYPE_COMPATIBLE |
| resolution:73bef16ed5135f39 | entity:cofradia-ambar | 1.0 | STRONG_MATCH,EXACT_NAME,SURFACE_SIMILARITY,TYPE_COMPATIBLE |
| resolution:bc28abf80c2d2903 | entity:cofradia-ambar | 1.0 | STRONG_MATCH,EXACT_NAME,HISTORY_SESSION,SURFACE_SIMILARITY,TYPE_COMPATIBLE |
| resolution:54f91ca603de7acb | entity:cofradia-ambar | 1.0 | STRONG_MATCH,EXACT_NAME,HISTORY_SESSION,SURFACE_SIMILARITY,TYPE_COMPATIBLE |
| resolution:a4fd0ea3dac7cda3 | entity:vado-alto | 1.0 | STRONG_MATCH,EXACT_NAME,SURFACE_SIMILARITY,TYPE_COMPATIBLE |
| resolution:a6ba8779313aeaf8 | entity:cofradia-ambar | 1.0 | STRONG_MATCH,EXACT_NAME,HISTORY_SESSION,SURFACE_SIMILARITY,TYPE_COMPATIBLE |
| resolution:5ff358053042a7c0 | entity:casa-ciervo | 1.0 | STRONG_MATCH,EXACT_NAME,SURFACE_SIMILARITY,TYPE_COMPATIBLE |

## CREATE_ENTITY (altas propuestas — carril B)

| resolution_id | accion | tipo | conf | motivos |
|---|---|---|---|---|
| resolution:43e5617ed53c9380 | CREATE_NEW | Character | 0.9 | NO_CANDIDATE,DERIVED_ID |

## RELATIONS (claims propuestos por el extractor)

| claim_id | frase | predicados | negado | conf | abst | rev |
|---|---|---|---|---|---|---|
| a74e1f4095d12c46 | es miembro de |  | False | 0.0 | True | True |
| 88d2610a027d8b41 | vive en |  | False | 0.0 | True | True |
| e3a51fcb3d1bfe0f | lidera | LEADS | False | 0.72 | False | False |
| 83ab075abd667658 | es aliada de | ALLY_OF | False | 0.7 | False | False |
| fe992c855fc10191 | pertenece al | MEMBER_OF | True | 0.75 | False | True |

## REVIEW (decisiones del motor)

| claim_id | decision | predicado | sujeto | objeto | neg | conf | motivos |
|---|---|---|---|---|---|---|---|
| a74e1f4095d12c46 | ABSTAIN |  |  |  | False | 0.0 | CLAIM_ABSTAINED_UPSTREAM,EVIDENCE_LITERAL_VERIFIED,EXTRACTOR_REQUESTED_REVIEW,PREDICATE_ABSENT,EPISTEMIC_UNKNOWN,TEMPORAL_UNSPECIFIED |
| 88d2610a027d8b41 | ABSTAIN |  |  |  | False | 0.0 | CLAIM_ABSTAINED_UPSTREAM,EVIDENCE_LITERAL_VERIFIED,EXTRACTOR_REQUESTED_REVIEW,PREDICATE_ABSENT,EPISTEMIC_UNKNOWN,TEMPORAL_UNSPECIFIED |
| e3a51fcb3d1bfe0f | REVIEW | LEADS |  | entity:cofradia-ambar | False | 0.72 | ENTITY_RESOLUTION_DEFERRED,EVIDENCE_LITERAL_VERIFIED,TEMPORAL_UNSPECIFIED |
| 83ab075abd667658 | ACCEPT | ALLY_OF | entity:cofradia-ambar | entity:casa-ciervo | False | 0.7 | EVIDENCE_LITERAL_VERIFIED,SYMMETRIC_PREDICATE,TEMPORAL_UNSPECIFIED |
| fe992c855fc10191 | REVIEW | MEMBER_OF | entity:sela-marrec | entity:consejo-umbra | True | 0.75 | EVIDENCE_LITERAL_VERIFIED,EXTRACTOR_REQUESTED_REVIEW,NEGATED_CLAIM,TEMPORAL_UNSPECIFIED |

## ABSTAIN

| claim_id | frase | motivo |
|---|---|---|
| a74e1f4095d12c46 | es miembro de | ['COORDINATED_OBJECT'],MEMBER_OF |
| 88d2610a027d8b41 | vive en | ['COORDINATED_SUBJECT', 'MULTIPLE_SUBJECT_CANDIDATES', 'TYPE_INCOMPATI |

## Contradicciones

_(ninguna)_

## ASSERTIONS

| assertion_id | predicado | sujeto | objeto | estado |
|---|---|---|---|---|
| assertion:b4b9a50837526e362e | ALLY_OF | entity:cofradia-ambar | entity:casa-ciervo | ASSERTED |

## PLAN de escritura

- plan_id: `plan:91f2e4f3063cc68e4c19d85ecc88acc1`
- plan_hash: `b748451505d651fd8aa865f56c6f0d1bcf52981ff56c95d0ee66f4bf60c97132`
- snapshot_id: `snapshot:sha256:33b7905e9c034a5969e0c075333ca71bb652bf3721baf0e5a06794986fc29e01`
- aprobado por el motor: **True**
- expira: `2026-09-06T10:00:00Z`

| op | detalle |
|---|---|
| CREATE_ASSERTION | {'operation_id': 'op:claim:extract.deterministic:83ab075abd667658:assert', 'decision_id': 'decision:claim:extr |
| PROJECT_RELATION | {'operation_id': 'op:claim:extract.deterministic:83ab075abd667658:project', 'decision_id': 'decision:claim:ext |

## Diagnosticos de la cadena

_(ninguna)_

## CARENCIAS declaradas

Lo que esta corrida NO puede enseñar, y por que. No se rellena
con ceros que parezcan datos.

| codigo | detalle |
|---|---|
| PLAN_REVISION_SIN_OPERACIONES | 4 decisiones en REVIEW/ABSTAIN pero el plan de revision no lleva ninguna operacion de mutacion: el planner solo materializa las ACCEPT. Lo que el carril D tiene que consumir es `decisions`, no `review_plan.mutation_operations` |
| SIN_ESCRITURA | dry-run: no se abrio ningun driver y no se toco Neo4j. Escribir es del carril C, contra un grafo efimero y con el gate del writer |
