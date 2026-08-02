# Revisión humana V3 y candidatos de glosario

Fecha: 2026-07-30

## Tres superficies distintas

| Ruta | Función | Autoridad |
|---|---|---|
| `/reviews` | Visor histórico de paquetes y quality reports por fuente. | Histórica; no es la cola V3. |
| `/review-console` | Laboratorio V1: summaries, preview de plan y decisiones `review-decision v1`. | Experimental; no gobierna V3. |
| `/v3/review` | Cola real alimentada por resultados del pipeline V3. | **Única fuente de verdad de revisión V3.** |

No deben agregarse sus recuentos ni trasladarse decisiones entre superficies:
sus contratos y almacenes son distintos.

## Exportador: dirección única

La frontera es:

`PipelineResult → paquete inmutable content-addressed → proposals/ → viewer`.

`knowledge_v3.review_export` no importa el viewer y el viewer no importa el
motor. El exportador incluye `REVIEW`, `ABSTAIN` y `REJECT_INVALID`; omite
`ACCEPT`. No hay flujo inverso del visor al resultado del motor ni al writer.

Cada propuesta conserva workspace, fuente, episodio y texto; evidencia literal
con offsets; tripleta, dirección, negación, alcance y estado epistémico;
decisión y razones del motor; resolución, alternativas, procedencia y versiones;
`proposal_id` y `proposal_hash`. Los paquetes son inmutables, deterministas,
atómicos, content-addressed e idempotentes.

## Decisiones, STALE_REVIEW y cadena

El contrato humano admite `APPROVE`, `REJECT` y `CORRECT`, con revisor,
`request_id`, propuesta completa, justificación/corrección, versiones y hashes.
La ruta HTTP exige `expected_proposal_hash`: si no coincide con el contenido que
el revisor vio, devuelve `STALE_REVIEW`, no escribe la decisión y registra la
incidencia aparte.

Las decisiones forman un JSONL append-only enlazado mediante `previous_hash` y
`record_hash`. La idempotencia por `request_id` evita duplicados; corregir o
deshacer añade una nueva entrada con `supersedes_decision_id`, nunca reescribe
ni borra la anterior. La salvedad conocida es que `proposal_id` y
`proposal_hash` son 1:1: si una reexportación cambia el contenido, puede verse
como propuesta inexistente (HTTP 400) en vez de `STALE_REVIEW`; sigue sin
escribir.

## Candidatos de glosario

Sólo una corrección humana explícita puede proponer:

- `CANONICAL_TERM_CANDIDATE`
- `ALIAS_CANDIDATE`
- `SPOKEN_FORM_CANDIDATE`
- `ENTITY_TYPE_CANDIDATE`
- `KNOWN_MISRECOGNITION_CANDIDATE`

Un `REJECT` no genera candidatos. La clave semántica normalizada deduplica por
workspace, tipo, valor canónico, valor candidato y entidad resuelta. Las
repeticiones agregan ocurrencias, fuentes, episodios, evidencias y decisiones
de origen sin perder versiones: el almacén también es append-only.

Todo candidato nace y permanece `PROPOSED`. `GlossaryCandidateStore` sólo
expone `root`, `list` y `propose`: no existe API de aplicar, aprobar, fusionar,
actualizar o borrar. El glosario efectivo se mantuvo byte-equivalente antes y
después del E2E (SHA-256
`f9de1bc7d6e377299dcccdd42c1d7a8ab68beb1f47361ef68e40959dad7ce46d`).

## Qué no se aplica

Una aprobación humana no es un plan, no llama a Neo4j y no muta el grafo. Una
corrección no cambia automáticamente el claim original, el gold, la ontología,
el `GameProfile` ni el glosario efectivo. Un candidato no se convierte en regla
ni alias operativo. El aprendizaje estructurado que explote el historial sigue
pendiente.

## Cómo revisar los informes finales

1. Abrir `artifacts/v3-final-validation/gates-summary.md` como índice, pero
   comprobar el veredicto final consolidado en
   `docs/v3/35-final-core-validation-results.md`.
2. Para una propuesta, verificar primero `workspace`, evidencia literal,
   `proposal_hash`, decisión efectiva y reasons; no inferir autoridad de la
   sombra.
3. Contrastar el flujo humano con `gate6b-human-review.md` y el E2E con
   `e2e-results.md`.
4. Tratar los candidatos de `/v3/review/glossary-candidates` como propuestas
   auditables, nunca como glosario aplicado.
5. Leer siempre las limitaciones de puertas 4 y 6 y la incidencia de Ollama:
   un gate seguro por inanición o fallo cerrado no demuestra cobertura.

Fuentes: `knowledge_v3/review_export.py`,
`viewer/app/services/{v3_review,v3_glossary_candidates}.py`,
`viewer/app/routers/v3_review.py` y
`artifacts/v3-final-validation/gate6b-human-review.md`.
