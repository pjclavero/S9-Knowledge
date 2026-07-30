# S9-Knowledge V3 — estado del programa y decisiones

Fecha: 2026-07-28 · Actualizado: 2026-07-30 · Rama actual: `main` · Base congelada de contratos:
`v3-contracts-frozen-1.0.0`

Este documento es el mapa del programa: qué está construido y verificado, qué se
midió de verdad, qué falló y por qué, y qué decisiones quedan sobre la mesa. Es el
punto de entrada; cada bloque tiene su documento propio en `docs/v3/`.

---

## 1. Qué hay construido

| Bloque | Documento | Estado |
|---|---|---|
| Auditoría del sistema actual | `00-audit-current-system.md` | Cerrado |
| Contratos `v3-internal-v1` (9) | `01-contracts-v3.md` | **Congelados** (tag) |
| Multimodal | `02-multimodal.md` | CONFORME, mergeado |
| Extractor (determinista y auxiliares) | `03-extractor.md` | CONFORME, mergeado |
| Resolución de identidad | `04-resolution.md` | CONFORME, mergeado |
| Motor local (autoridad) | `05-local-engine.md` | CONFORME, mergeado |
| Ledger temporal bitemporal | `06-temporal-ledger.md` | CONFORME, mergeado |
| Proveedores (Ollama / NVIDIA) | `07-providers.md` | CONFORME, mergeado |
| Benchmarks y dataset `dev` | `08-benchmarks.md` | CONFORME, mergeado |
| Writer con gate de operador | `09-writer.md` | CONFORME, mergeado |
| Held-out independiente | `10-heldout.md` | Mergeado, **sin usar** |
| Cadena extremo a extremo | `11-e2e.md` | Mergeado |
| Extractor semántico episódico | `12-semantic-extractor.md` | Mergeado |
| Semántico conectado a la cadena + negaciones | `15-semantic-extractor-e2e-integration.md` | Mergeado |

Cada bloque pasó por editor, revisor independiente y correcciones. Seis de los
nueve recibieron un NO CONFORME inicial: historia mutable en el ledger, cruce de
workspaces por el historial, contradicción intra-lote inexistente, fuga de API key
por redirect, `Retry-After` sin tope, y claims anclados a evidencia que no decía lo
que afirmaban. Todos corregidos y verificados con los ataques originales.

## 2. Lo que se midió de verdad

Todo sobre el split `dev` (16 episodios, 6 fuentes, 3 mundos). El held-out **no se
ha tocado**.

| | A · determinista | C1 · qwen2.5:7b local | C2 · llama-3.3-70b nube |
|---|---|---|---|
| Menciones R / P | **0.745 / 0.905** | 0.471 / 0.632 | 0.431 / 0.629 |
| Tipo de entidad correcto | 0.000 | 0.917 | **1.000** |
| Claims correctos (tp) | **0** | 5 | 6 |
| Predicado top-1 / top-2 | 0 / 0 | 0.20 / 0.20 | 0.30 / 0.30 |
| Dirección | 0 | 0.250 | 0.300 |
| Trampas pisadas (de 4) | 0 (no extrae) | **3** → **0** tras ronda 2 | **3** |
| Alucinaciones | 0 | 0 | 0 |
| Predicados fuera de ontología | 0 | 0 | 0 |
| Latencia por episodio | — | 129 s | 49.8 s |

C2 procesó 12 de 16 episodios: cuatro fallaron con `PROVIDER_UNAVAILABLE`, así que
su recall está medido con una cuarta parte del corpus sin ver.

> **Cuidado al leer esta tabla.** Son medidas del **banco aislado** (que llama
> directo a `SemanticEpisodeExtractor`) con el prompt **1.1.0**. Hasta el bloque
> 15 la cadena montaba los extractores *legacy*, así que estas cifras nunca
> dijeron nada sobre `KnowledgePipeline`. La primera medida **por la cadena**, con
> el prompt 1.2.0, está en `15-semantic-extractor-e2e-integration.md` §12.

### Primera medida POR LA CADENA (bloque 15, prompt 1.2.0, `dev`)

| | A · cadena `local_only` | D · cadena `local_plus_external` + Ollama |
|---|---|---|
| Menciones P / R / F1 | 0.905 / 0.745 / 0.817 | 0.476 / 0.765 / 0.586 |
| Tipo de entidad correcto | 0.000 | **0.949** |
| Claims extraídos → decisiones | 0 → 0 | **18 → 18** (no se pierde ninguno) |
| Claims correctos (tp) | 0 | 0 (fp 18) — falla el emparejamiento, no la cadena |
| Trampas pisadas | 0 / 4 | **0 / 4** |
| ACCEPT / REVIEW / ABSTAIN / REJECT | 0/0/0/0 | 0 / 7 / 10 / 1 |
| Planes aprobados | 0 | 0 |
| Latencia · llamadas | 272 ms · 0 | 48 min · 58 |

Lo que esto añade a lo que ya se sabía:

(a) **A da exactamente lo mismo aislado y en cadena** — prueba de que el
orquestador no añade ni quita nada.

(b) En D **no se pierde un solo claim entre etapas** (18 extraídos, 18 decididos),
pero el 0 ACCEPT **no** se explica por la política de "origen no confiable ⇒
revisión humana": esa política explica **7 de 18 (39 %)**. Los otros **11 (61 %)**
se pararon en ejes de calidad real —`SUBJECT_NOT_GROUNDED`,
`OBJECT_NOT_GROUNDED`, `PREDICATE_NOT_IN_PROFILE`, `HALLUCINATED_MENTION`,
`HALLUCINATED_QUOTE`, `UNKNOWN_ENTITY_TYPE`—, con el modelo llegando a inventarse
el predicado `NEGATED_MEMBER_OF` en vez de usar `negated: true`. Levantar hoy la
política daría 7 escrituras como mucho, no 18.

(c) Los claims no puntúan porque `claim_key` devuelve `None` cuando un argumento
pierde la adjudicación de su mención: eso explica el `tp=0 / fp=18` por completo y
es la justificación medida del reconciliador, confirmada dentro de la cadena.

(d) La caída de precisión de **menciones** (0.905 → 0.476) está **resuelta** por la
corrida C1 aislada, y no era una sola causa: de los 43 fp, **15 son falsos
positivos genuinos del modelo** (medidos sin ninguna unión, P 0.625) y **~24 los
añade la unión**. El reconciliador sigue justificado, pero no basta.

### C1 aislado con prompt 1.2.0 (16/16 JSON válido, 182,4 s/episodio)

| | A · determinista | **C1 · semántico solo** | D · unión |
|---|---|---|---|
| Menciones P / R / F1 | 0.905 / 0.745 / 0.817 | 0.625 / 0.490 / 0.549 | 0.476 / 0.765 / 0.586 |
| Claims tp / fp / fn | 0 / 0 / 20 | **8** / 10 / 12 | **0** / 18 / 20 |
| Claims F1 | — | **0.421** | **0.000** |
| Predicado top-1 / top-2 | 0 / 0 | 0.05 / **0.10** | 0 / 0 |
| Trampas pisadas | 0/4 | 0/4 | 0/4 |

Dos resultados nuevos:

1. **La unión destruye los claims, probado con control.** C1 y D llevan los MISMOS
   18 claims del modelo; lo único que cambia es unirlos con el determinista, y el
   resultado pasa de tp 8 a tp 0. Es la justificación definitiva del
   `ProposalReconciler`.
2. **Por primera vez el modelo da candidatos múltiples**: `top-2` (0.10) duplica a
   `top-1` (0.05). Con el prompt 1.1.0, `top-2 == top-1` siempre y el desempate del
   motor no se ejercitaba nunca. Sigue siendo un valor bajo, pero el mecanismo está
   vivo.

### Lecturas

1. **El extractor determinista no extrae.** Cero claims sobre un corpus que no fue
   escrito para sus reglas, y cero menciones sin glosario. Sus 14 reglas léxicas no
   aparecen ni una vez en `dev`.
2. **La arquitectura semántica es sólida:** cero alucinaciones, cero predicados
   fuera de ontología, evidencia anclada al 100 %, mismo contrato con proveedor
   local y remoto.
3. **Ningún modelo da candidatos múltiples.** `top-2 = top-1` en ambos: es el
   prompt, no el modelo. La capacidad de desempate del motor nunca se ejercita.
4. **Los dos modelos pisaban las mismas 3 de 4 trampas** (contrafactual,
   ficción-dentro-de-ficción, pregunta): no era cuestión de tamaño, era el prompt y
   la capa local. El 0/4 del determinista es trivial — no pisa trampas porque no
   extrae nada. La ronda 2 del prompt lo dejó en 0/4 con el mismo modelo pequeño, y
   descubrió que las tres "pisadas" eran **abstenciones bien razonadas del modelo**
   que el arnés contaba como claims: el modelo acertaba, sobraba el documento.
5. **Determinista y semántico son complementarios**, y hoy se estorban: proponen la
   misma mención con dos identificadores y el emparejamiento uno a uno se la
   adjudica a uno solo, dejando los claims del otro sin argumentos alineados. Es la
   justificación medida del reconciliador.

## 3. Decisiones tomadas

- **Contratos congelados.** Lo que no cabe viaja en `metadata` (única excepción a
  `additionalProperties: false`). No se ha añadido un solo campo a ningún schema.
- **El held-out no se mide hasta que el extractor produzca algo.** Es un activo de
  un solo uso limpio: medir contra él y ajustar mirando el resultado lo convierte en
  dev y repite el error de V2.
- **Camino legacy cerrado con llave.** `S9K_ALLOW_REAL_INGEST` gatea `ingest_rpg.py`
  con aborto duro, cubriendo también la ruta por subproceso desde YouTube.
- **El writer no escribe sin gate de operador**, dry-run por defecto, y el
  `plan_hash` se teclea fuera de banda — leerlo del plan que se autoriza convierte
  la condición en una tautología.
- **Modelo local:** `qwen2.5:7b` es el techo del hardware disponible. NVIDIA es
  **nube**: el contenido sale de la máquina, y conviene decidirlo explícitamente por
  workspace antes de ingerir material sensible.

- **El extractor de la cadena es el semántico, y no hay vuelta atrás.** Hasta el
  bloque 15, `KnowledgePipeline` montaba los extractores **legacy** cuando la
  configuración pedía Ollama o externo, así que las métricas C1/C2 de la tabla de
  arriba —obtenidas con `semantic_bench`, que llama directo al extractor— no
  decían nada sobre la cadena. Ahora los dos carriles son
  `SemanticEpisodeExtractor` sobre su puerto, sin bandera para volver al legacy, y
  `ExtractionPipeline.local_default()` sigue intacto como gate determinista.
  Detalle en `15-semantic-extractor-e2e-integration.md`.
- **Una relación negada es un hecho, no una duda.** `negation_kind` (SIMPLE,
  NEVER, CESSATION, NOT_YET, SCOPE_AMBIGUOUS) viaja en `metadata` — sin tocar un
  solo schema— y el motor lo usa para distinguir *contradicción* de *transición*:
  una cesación con afirmación positiva vigente cierra su vigencia y la sucede; sin
  afirmación previa, **no la inventa**.

## 4. Lo que falta, por orden

1. **Prompt: candidatos múltiples y no-factividad.** Ataca los dos defectos
   medidos y es barato. En curso.
2. **`ProposalReconciler`**: agrupar por clave canónica antes del motor, conservar
   evidencia de todas las fuentes, y convertir el desacuerdo de predicado sobre el
   mismo par en una revisión en vez de en dos escrituras.
3. **Política de origen no confiable ≠ revisión humana**: hoy todo claim de LLM nace
   condenado a revisión; el motor debería poder aprobar una propuesta que supere
   todas las verificaciones locales reforzadas.
4. **Contexto episódico** (anterior/siguiente), con la evidencia aprobable siempre
   anclada al episodio actual.
5. **Held-out, una sola vez**, cuando 1-3 estén cerrados y el prompt congelado.
6. **Informe final** `S9_KNOWLEDGE_V3_RESULTS.md` y PR de entrega sin merge.

## 5. Deuda declarada

- `SnapshotAssertion.is_live()` quedó como código muerto (la regla vive en
  `blocks_new_claims()`).
- Los dos `GraphSnapshot` incompatibles se puentean en el orquestador; el `Protocol`
  es `runtime_checkable`, así que el `isinstance` no protege.
- La correferencia no comprueba concordancia de género.
- Los hashes del plan son verificables pero **no autenticados**: `signature` y
  `key_id` están reservados y sin uso.
- Ninguna prueba contra un Neo4j real: que las consultas hagan allí lo que dicen es
  verificación de despliegue pendiente.
- La release RC5.1 de producción no carga la configuración de proveedores V3;
  las plantillas corregidas en el Lote 6 aún no están desplegadas.
- **El camino de escritura de la negación tiene cobertura CERO en producción.**
  `extraction/deterministic.py:643` (`review = bool(negated or ...)`, preexistente)
  hace que TODO claim negado, de cualquier tipo y por cualquier carril, nazca con
  `review_required=True` → `REVIEW` → plan con cero operaciones. La afirmación
  negativa, la garantía de "sin arista positiva" y el `SUPERSEDE_ASSERTION` con
  concurrencia optimista sólo se ejercitan con claims sintéticos de test. Decidir
  si un negado que supera todas las verificaciones locales puede aprobarse es del
  organizador; la línea NO se ha tocado.
- **Límites léxicos de la negación, medidos**: 20 de 20 verbos de actitud fuera de
  `SCOPE_VERBS` (`duda`, `niega`, `asegura`, `sostiene`, `opina`…) niegan
  mecánicamente la relación (fail-closed peligroso); 8 de 8 cesaciones reales
  fuera de `CESSATION_PHRASES` (`se marchó de`, `fue destituido de`, `perdió el
  liderazgo de`) no se detectan (fail-open benigno).
- El coste real de Ollama en esta ronda: 50,1 s/llamada y 181,7 s/episodio,
  **×1,41** sobre los 129 s/episodio del bloque 12.

## 6. Actualización de estado — 2026-07-30

- V3 quedó mergeada en `main` mediante la PR #110; ya no está limitada a la
  rama indicada en la cabecera histórica de este documento.
- Los Lotes 1, 2, 2b, 3 y 6 del
  [`plan consolidado`](32-plan-consolidado-extractor-y-nucleo.md) están
  completados y mergeados mediante las PRs #111–#114.
- La política graduada de negaciones y temporalidad está implementada, pero sus
  flags permanecen **OFF** hasta completar la medición en sombra. No hay
  autorización implícita para activarla.
- Producción en VM105 continúa en RC5.1. V3 no está desplegada.
