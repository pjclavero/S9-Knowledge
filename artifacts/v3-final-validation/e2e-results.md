# E2E GLOBAL — Escenarios E2E-01..E2E-14

**Rama:** `integration/v3-final-core-validation`
**Fichero de pruebas:** `data-engine/app/tests/test_knowledge_v3_e2e_global.py`
**Resultado exacto:** `39 passed, 2 skipped, 2 xfailed in 11.22s`
**Writer:** SIEMPRE dry-run. Driver por defecto = `ExplodingDriver` (estalla si alguien lo toca).
**Proveedores:** ningún proveedor real. Ni Ollama (`127.0.0.1:11434`) ni NVIDIA. El carril de
proveedor entra por `ScriptedExternalPort` / `ExplodingExternalPort` de los fixtures existentes.
**Neo4j:** nunca se abre.

---

## 1. Qué añade este bloque y qué NO repite

`test_knowledge_v3_e2e.py` (932 líneas, 10 clases `TestConjunta01..10`) ya cubre los pares de
etapas y las defensas: normalizador+extractor, extractor+motor, motor+ledger, cadena completa,
con/sin externo, sin Ollama, proveedor corrupto, workspace ajeno y plan no firmado. **Todas entran
por EPISODIOS del gold.**

Este bloque **no repite nada de eso**. Cubre el eje ortogonal: la ruta completa **desde BYTES**
(normalizador real incluido) recorrida una vez por **cada clase de fenómeno** que el sistema dice
saber distinguir. La pregunta no es "¿se sostienen dos etapas juntas?" sino "¿qué sale por el otro
extremo cuando entra ESTE texto?".

### Hallazgo previo que condicionó el diseño (medido, no supuesto)

La cadena en `local_only` sobre las **seis fuentes completas del split `dev`** produce
**CERO claims**:

| fuente | episodios | menciones | claims | decisiones |
|---|---|---|---|---|
| kestrel-informe | 3 | 9 | **0** | 0 |
| kestrel-tripulacion | 1 | 3 | **0** | 0 |
| leyenda-cronica | 3 | 11 | **0** | 0 |
| leyenda-escaneo | 3 | 5 | **0** | 0 |
| mareas-cuaderno | 3 | 9 | **0** | 0 |
| mareas-sesion | 3 | 5 | **0** | 0 |

Todas paran en `stopped_at="engine"` con `stop_reason="el extractor no propuso ningun claim para
esta fuente"`. Causa: el `DeterministicExtractor` exige una de sus frases de relación **literales**
(`RELATION_RULES`: `lidera`, `es miembro de`, `vive en`, …) y la prosa literaria del gold usa otras
formas (`dirigió`, `firmaron`, `llevan enfrentados`).

Consecuencia de diseño: los escenarios usan **texto corto escrito para el escenario**, pero con las
**entidades reales del split `dev`** (`Ilaria Vandreth`, `Casa del Ciervo`, `Daiki Oharu`), entrando
por el **catálogo y el glosario reales** del workspace. No se fabrica ninguna entidad. La constante
en los 14 escenarios es el par sujeto/objeto; lo único que cambia es el **marco**, de modo que
cualquier diferencia de salida sólo puede venir del marco.

---

## 2. Tabla de escenarios

Leyenda de estado: **PASA** · **FALLA** · **DIFERIDO-puerta7**

| # | Escenario | Entrada (texto) | Etapas verificadas | Resultado esperado | Resultado observado | Estado |
|---|---|---|---|---|---|---|
| **E2E-01** | Hecho determinista | `Ilaria Vandreth lidera la Casa del Ciervo.` | norm (asset+1 ep `ep-*`+1 frag) → extract (2 menciones, 1 claim, 0 diagnósticos) → reconcile → resolve (2× `LINK_EXISTING`) → motor → planner → ledger → writer | ACCEPT, plan aprobado, dry-run simulado | `ACCEPT` `LEADS` `SUBJECT_TO_OBJECT` conf **0.72**, findings `EVIDENCE_LITERAL_VERIFIED`+`TEMPORAL_UNSPECIFIED`; plan `approved=True`, 2 ops (`CREATE_ASSERTION`), IDs `entity:leyenda:ilaria` → `entity:leyenda:casa-ciervo`; 1 entrada de ledger; writer `SIMULATED`, `codes=[]` | **PASA** |
| **E2E-02** | Hecho semántico | mismo texto + puerto semántico guionizado (`LEADS` 0.9) | ruta completa con `providers=local_plus_external`; extractor semántico real (anclaje de cita, tope de confianza externo) | la propuesta externa entra, se marca y **no manda** | **2 decisiones**: externa `REVIEW` conf **0.6** (tope externo) con `EXTERNAL_PROPOSAL`; local `ACCEPT` conf 0.72. Plan firmado por el motor local, `approved=True`, writer `SIMULATED` | **PASA** (carril real medido en **puerta 5** por el coordinador) |
| **E2E-03** | Negación simple | `Daiki Oharu no lidera la Casa del Ciervo.` | ruta completa | REVIEW, negación marcada, sin escritura | `REVIEW`, `negated=True`, `negation_kind="SIMPLE"`, `NEGATED_CLAIM`, predicado **conservado** (`LEADS`); `plan=None`; `review_plan.approved=False` con **0 operaciones**; sin entradas de ledger | **PASA** |
| **E2E-04** | Cesación | `Ilaria Vandreth ya no lidera la Casa del Ciervo.` | ruta completa | CESSATION distinguida de SIMPLE | `REVIEW`, `negation_kind="CESSATION"`, `CESSATION_WITHOUT_ACTIVE_ASSERTION` (no se inventa vigencia que cerrar); `plan=None`. Contraste con E2E-03 verificado: los `findings` difieren | **PASA** |
| **E2E-05** | Negación de cesación | `Ilaria Vandreth no dimitio de su cargo y lidera la Casa del Ciervo.` | `cues.analyze_raw_text` + ruta completa | no leerlo como cesación | clasificador: `negation_kind="SCOPE_AMBIGUOUS"`, `REVIEW_NEGATION_SCOPE`. Cadena: `ABSTAIN`, `CLAIM_ABSTAINED_UPSTREAM`, **sin** `CESSATION_WITHOUT_ACTIVE_ASSERTION`; plan `approved=False`, 0 ops | **PASA** (con límite declarado, §3) |
| **E2E-06** | Pregunta | `¿Ilaria Vandreth lidera la Casa del Ciervo?` | norm + extract | ni un claim | 2 menciones (las entidades se mencionan de verdad), **0 claims**, diagnóstico `INTERROGATIVE_CONTEXT`; `stopped_at="engine"`, 0 decisiones, `plan=None` | **PASA** |
| **E2E-07** | Contrafactual | `De haber sobrevivido al asedio, Ilaria Vandreth lidera la Casa del Ciervo.` | norm + extract | ni un claim | **0 claims**, diagnóstico `COUNTERFACTUAL_CONTEXT`, `stopped_at="engine"`. Control con el mismo hecho sin marco → `ACCEPT` (lo que bloquea es el marco, no la frase) | **PASA** |
| **E2E-08** | Proveedor caído | mismo texto + `ExplodingExternalPort` (`ProviderUnavailable`) | ruta completa con externo muerto | la cadena **termina su trabajo**, no sólo sobrevive | diagnóstico `PROVIDER_UNAVAILABLE`; carril local `ACCEPT` `LEADS`; plan `approved=True`; writer `SIMULATED`. Ninguna **mención** de origen externo; el claim con sello externo sale `ABSTAIN` / `PREDICATE_ABSENT` | **PASA** |
| **E2E-09** | Predicados rivales | mismo texto + puerto con `LEADS` 0.55 / `MEMBER_OF` 0.52 | ruta completa | ambigüedad resuelta **en el motor**, no en el extractor | `REVIEW` con `PREDICATE_AMBIGUOUS` + `PREDICATE_LOW_CONFIDENCE`; `MEMBER_OF` **no** aparece en las operaciones aprobadas. Control sin rival: no marca ambigüedad | **PASA** |
| **E2E-10** | Identidad no resuelta | `Kestrel Umbrio lidera la Casa del Ciervo.` (+ puerto semántico) | ruta completa | provisional, no invención ni descarte | resolutor: 1× `CREATE_PROVISIONAL` → `entity:prov:e6e780c6…`; motor: `REVIEW` con `ENTITY_PROVISIONAL`; `plan=None`, sin escritura | **PASA** |
| **E2E-11** | Revisión humana | texto de E2E-03 → `review_export.review_documents` | ruta completa + canal humano `/v3/review` | el REVIEW llega al humano | **1 documento**; `evidence.literal_text` == texto del episodio; `engine_decision.decision="REVIEW"` con `NEGATED_CLAIM`; `proposal.predicate="LEADS"`, `negated=True`; `proposal_id="review:…"`, `proposal_hash` de 64 chars. Control: un ACCEPT **no** genera documento | **PASA** (con defecto D-G2 adjunto, §4) |
| **E2E-12** | Corrección humana | E2E-01 asentado → `ledger.retract(reason_code="OPERATOR_RETRACTION")` | motor → ledger → snapshot de la siguiente fuente | la corrección **surte efecto** | antes: `status=ASSERTED`, snapshot con 1 afirmación. Después: `status=RETRACTED`, `live()==[]`, **snapshot con 0 afirmaciones**. Historial conserva `["ASSERTED","RETRACTED"]` (retractar ≠ borrar). Un motivo no canónico es rechazado | **PASA** |
| **E2E-13** | Alias candidato | `Vandreth lidera la Casa del Ciervo.` | ruta completa | enlaza al canónico, pero cuesta confianza | `ACCEPT`, `subject_entity_id=entity:leyenda:ilaria`, writer `SIMULATED`; confianza **0.612 vs 0.72** del nombre canónico | **PASA** |
| **E2E-14** | Error OCR | `Ilaria Vandreth lidera la Casa de1 Ciervo.` | ruta completa | reconoce la variante declarada, sin tratarla como limpia | `ACCEPT`, `object_entity_id=entity:leyenda:casa-ciervo`, writer `SIMULATED`; confianza **0.612 vs 0.72**. Una degradación **no declarada** (`Kasa del Zierbo`) produce **0 claims**: el reconocimiento viene del glosario, no de magia | **PASA** |
| **—** | E2E-01 aplicado de verdad | plan de E2E-01 con `apply=True` | writer contra Neo4j efímero + `idempotency_key` | escritura real e idempotente | no ejecutado en este árbol | **DIFERIDO-puerta7** |
| **—** | E2E-12 propagado al grafo | retractación de E2E-12 | propagación al grafo, no sólo al ledger en memoria | grafo actualizado | no ejecutado en este árbol | **DIFERIDO-puerta7** |

**Transversal:** un test parametrizado sobre 9 de los escenarios comprueba que **ninguno** toca el
driver de Neo4j (`ExplodingDriver` habría estallado).

---

## 3. Límite declarado en E2E-05

No existe ningún texto que el `DeterministicExtractor` acepte en el que convivan **una frase de
cesación negada** y **una de sus frases de relación literales**. Motivo estructural: las frases de
cesación piden infinitivo (`dejo de liderar`, `cesa de servir`) y las frases de relación son formas
conjugadas (`lidera`, `es miembro de`). Comprobado empíricamente sobre 6 formulaciones
(`no deja de liderar`, `nunca dejo de liderar`, `nunca abandona`, `no abandona`, `nunca ceso en`,
`no dimitio de`): las que llevan infinitivo no producen claim (el extractor no encuentra la
relación); las que sí producen claim se clasifican `SCOPE_AMBIGUOUS`.

Lo que E2E-05 **sí demuestra** —y es la propiedad de seguridad que importa— es que la cadena
**no lee una cesación negada como cesación**: se abstiene. El riesgo real (cerrar la vigencia de una
relación que el texto afirma) **no se materializa**.

---

## 4. Hallazgos

### D-G1 — Un rumor explícito se acepta como hecho del mundo · **REAL, fail-open**

`knowledge_v3/extraction/cues.py:52` (`EPISTEMIC_CUES`) contiene `se rumorea`, `dicen que`,
`se dice que`, `segun cuentan`, `supuestamente`, `al parecer` — pero **no** `corre el rumor de que`.

Reproducción mínima:

```python
# ACEPTADO como hecho del mundo
"Corre el rumor de que Daiki Oharu lidera la Casa del Ciervo."
  -> DEC ACCEPT  LEADS  epistemic_status=ASSERTED
  -> findings: ['EVIDENCE_LITERAL_VERIFIED', 'TEMPORAL_UNSPECIFIED']
  -> plan.approved = True, 2 operaciones de mutación
  -> writer dry-run: SIMULATED

# CONTROL: la misma frase con una marca que sí está en la lista
"Se dice que Daiki Oharu lidera la Casa del Ciervo."
  -> DEC REVIEW  LEADS  epistemic_status=RUMORED
  -> findings incluyen 'EPISTEMIC_NOT_ASSERTED'
```

A nivel de clasificador: `cues.analyze_raw_text("Corre el rumor de que …")` devuelve
`hint="ASSERTED"`, `reason_codes=()`, `cues=()`.

**Gravedad.** No es una laguna teórica: la construcción aparece **literalmente en el corpus dev**
(`leyenda-cronica` e03: *"Corre el rumor de que la Casa del Ciervo y el Consejo de Umbra firmaron un
pacto secreto…"*). Hoy está enmascarada porque el extractor determinista no reconoce `firmaron`
como frase de relación y no llega a producir claim. En cuanto el carril semántico proponga esa
relación —que es exactamente para lo que existe—, el rumor entra al grafo como hecho asertado.

**Test:** `TestDefectosDeProduccion::test_DG1_un_rumor_explicito_no_deberia_aprobarse`
con `xfail(strict=True)`, más el control en verde
`test_DG1_control_la_marca_reconocida_si_frena`. **No se ha parcheado.**

### D-G2 — Todo documento de revisión humana oculta de quién habla · **REAL, tres claves inexistentes**

`knowledge_v3/review_export.py:66-83` cruza claims y resoluciones con claves que **no existen en los
contratos**:

| línea | clave que busca | campo real del contrato |
|---|---|---|
| `claim.get("subject_mention_id")` | `subject_mention_id` | `ClaimProposal.subject_mentions` (plural, lista) |
| `claim.get("object_mention_id")` | `object_mention_id` | `ClaimProposal.object_mentions` (plural, lista) |
| `_lookup(resolutions, "mention_id", …)` | `mention_id` | `EntityResolution.mention_ids` (plural, lista) |

Resultado: **todos** los `.get()` devuelven `None` y **todos** los `_lookup` fallan, en **todo**
documento de revisión.

Reproducción mínima:

```python
# Caso E2E-10, donde el resolutor SÍ asignó una entidad:
resoluciones reales:
  ['mention:extract.semantic:b858…'] -> entity:prov:e6e780c6f180cfcc   CREATE_PROVISIONAL
  ['mention:reconciled:6602…']       -> None                          LINK_EXISTING

documento de revisión producido:
  proposal.subject = "UNKNOWN"
  proposal.object  = "UNKNOWN"
  resolution       = {"subject": None, "object": None}
```

**Gravedad.** `review_export` es **el** canal por el que la decisión del motor llega al humano
(`export_review_package` → `/v3/review`). El revisor recibe literalmente
`UNKNOWN — LEADS — UNKNOWN` y no puede saber sobre qué entidades está juzgando. Toda la revisión
humana del sistema está operando a ciegas sobre los argumentos de la relación.

**Test:** `test_DG2_el_documento_de_revision_deberia_decir_de_quien_habla` con
`xfail(strict=True)`, más `test_DG2_las_claves_que_review_export_busca_no_existen`, que aísla la
causa raíz comparando contra `dataclasses.fields()`. **No se ha parcheado.**

### O-1 — Un proveedor caído deja un claim con sello externo · **observación, no defecto**

Con el puerto externo muerto, el extractor semántico produce igualmente un claim con
`provider_trace = [{"provider": "external", "name": "external.semantic", …}]`. No es contenido del
modelo (nunca contestó): es el **registro del intento**, y ese claim sale `ABSTAIN` con
`PREDICATE_ABSENT`. Comportamiento fail-closed correcto, pero conviene saberlo: contar trazas con
`provider == "external"` **sobreestima** las llamadas efectivas a proveedor.

### O-2 — Un REVIEW produce un plan de revisión con cero operaciones · **por diseño, verificado**

`engine.py:207` (`split_review_plan`) separa las decisiones `REVIEW` en `review_plan`, y
`build_plan(kind="review")` genera **0 operaciones de mutación** para ellas. Es correcto: un REVIEW
no debe mutar el grafo. El canal hacia el humano no es el `review_plan` sino `review_export`
(§E2E-11) — lo cual hace que D-G2 sea **el único** camino de la decisión al revisor, y por tanto más
grave.

### O-3 — El corpus `dev` no ejercita la cadena en `local_only`

Ver §1. Seis fuentes, 42 menciones, **0 claims**. Cualquier métrica de extremo a extremo tomada
sobre `dev` en `local_only` mide un denominador cero, no un sistema.
