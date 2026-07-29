# ProposalReconciler — especificación

Fecha: 2026-07-29 · Estado: **implementado y verificado**

> El reconciliador **no descubre identidades ni decide hechos**. Solo hace que
> varias propuestas sobre el mismo fragmento textual lleguen ordenadas,
> deduplicadas y con su dependencia correctamente representada al resolutor y al
> motor.

---

## 0. Por qué existe (medido, no supuesto)

`bench C1` frente a `cadena D`, mismo corpus, mismos 18 claims:

| | C1 semántico solo | D unión con determinista |
|---|--:|--:|
| Claims correctos | **8** (F1 0.421) | **0** (F1 0.000) |
| Menciones fp | 15 | 43 |

La unión **destruye ocho claims correctos**. `claim_key` devuelve `None` cuando un
argumento pierde la adjudicación de su mención, y el emparejamiento uno a uno del
arnés se la adjudica a un solo extractor. De los 43 falsos positivos de menciones,
15 son genuinos del modelo y ~24 los añade la unión: **no era una sola causa**.

## 1. Test de aceptación (se escribe antes que el código)

```
Con reconciliador, la unión determinista + semántico debe conservar
al menos los 8 claims correctos que el semántico produce en solitario.
```

Si no los conserva, el bloque ha fallado. Es binario y no admite interpretación.

## 2. Lo que sí hace

Alinear identificadores distintos para **la misma aparición textual**, deduplicar lo
verdaderamente equivalente, combinar procedencias, combinar candidatos compatibles,
registrar apoyos por proveedor y por familia independiente, **conservar
desacuerdos**, producir orden canónico y emitir razones de fusión y de no fusión.

## 3. Lo que no hace

Resolver alias · resolver pronombres · fusionar entidades · consultar el grafo ·
decidir temporalidad · decidir contradicciones · aprobar claims · elevar confianza
por mayoría · decidir qué modelos son independientes · borrar propuestas en
conflicto · interpretar qué proveedor tiene razón.

**No consulta**: alias históricos, entidades canónicas, Neo4j, memoria del
workspace, correferencias entre tramos distintos, títulos ni nombres alternativos.

## 4. La frontera con el resolutor

```
Reconciliador:  propuestas          → menciones textuales coherentes
Resolutor:      menciones textuales → entidades canónicas
```

`det-m-17` y `sem-m-04`, ambas sobre `Toturi [0,6]` del mismo episodio: **sí se
reconcilian** — señalan el mismo tramo. `Toturi [0,6]` y `el Emperador [20,31]`:
**no** — son menciones textuales distintas, y decidir si son la misma entidad es
del resolutor, que ya tiene cascada, historial y aislamiento por workspace.

## 5. Unidad de reconciliación

No es la entidad, sino `workspace + source + episode + tramo textual + tipo de
propuesta`. Clave de menciones derivada de `episode_id`, `start_offset`,
`end_offset` y superficie normalizada. Diferencias pequeñas de segmentación solo
con reglas **deterministas y conservadoras**; ante cualquier duda, se conservan los
dos spans. **Nunca similitud semántica** para decidir que dos menciones son iguales.

> **Consecuencia aguas abajo que hay que probar.** Conservar `"Clan del León"` y
> `"el Clan del León"` sin fusionar deja dos menciones solapadas para el resolutor
> — que es exactamente la situación que hoy rompe el emparejamiento. Test
> obligatorio: **dos menciones solapadas no fusionadas no pueden acabar produciendo
> dos entidades ni dos claims duplicados aguas abajo**. Si lo hacen, la
> conservación prudente del reconciliador se paga en el resolutor y hay que
> resolverlo allí, no relajando aquí.

## 6. Independencia declarada, no deducida

```yaml
extractor_independence:
  deterministic:          {family: lexical-rules}
  table:                  {family: structural-table}
  temporal:               {family: temporal-rules}
  semantic-ollama-qwen:   {family: semantic-prompt-v1.2}
  semantic-nvidia-llama:  {family: semantic-prompt-v1.2}
```

Qwen y Llama con el mismo prompt son **una sola familia**: comparten prompt,
ontología, esquema, ejemplos, definición de factualidad, diseño de candidatos y
buena parte de los modos de fallo. Está medido — pisaban las mismas 3 de 4 trampas.

El motor recibe los tres valores, no un contador de votos:

```yaml
support:
  proposals: 3
  providers: 3
  independent_families: 2
```

Acuerdo **dentro** de una familia → consistencia o reproducibilidad.
Acuerdo **entre** familias → evidencia adicional real.
Ni siquiera lo segundo aprueba nada: informa al motor.

La tabla es una **hipótesis arquitectónica versionada**, no una afirmación
estadística. Se mide después con los errores del corpus: ¿con qué frecuencia fallan
juntos?, ¿en qué categorías coinciden?, ¿aporta información nueva cada familia?

> **Pregunta que la tabla debe responder por escrito:** si el prompt pasa de v1.2 a
> v1.3, ¿siguen siendo la misma familia? La familia se define por el **diseño** del
> prompt, no por su número de versión — pero hay que decidirlo explícitamente o la
> tabla envejecerá sin que nadie lo note.

## 7. Nunca vota

Prohibido: *"dos modelos dicen LEADS y uno MEMBER_OF, gana LEADS"*. Qwen y Llama
pueden compartir exactamente el mismo error inducido por el prompt. La salida
conserva los candidatos con su procedencia y sus familias, y el motor evalúa
dominio, rango, evidencia, dirección, ontología, temporalidad, factualidad,
contradicciones, historial y procedencia.

## 8. Ante la duda, no fusionar

```
Falso negativo de reconciliación → propuestas duplicadas al motor: coste, recuperable
Falso positivo de reconciliación → mezcla hechos distintos: pérdida irreversible
```

**La precisión de fusión importa más que su recall.**

**Se fusiona** con: mismo episodio, mismos anclajes de sujeto y objeto, mismo tramo
de evidencia (o equivalencia demostrable), misma polaridad, predicado igual o
candidatos compatibles, misma dirección, sin diferencias temporales ni epistémicas.

**No se fusiona** nunca: `lideraba` con `ya no lidera` · `pertenece` con `no
pertenece` · `lidera` con `se rumorea que lidera` · `lideró antes de la guerra` con
`lideró después` · `dejó de liderar` con `no dejó de liderar`.

Ante cualquier diferencia de negación, tipo de negación, factualidad, modalidad,
tiempo, evidencia o alcance: **se conservan separadas**. El motor decidirá si es
transición, conflicto, supersesión, rumor, duplicado o hechos compatibles.

Temporalidad: puede **observar** `temporal_signature` pero no resolverla. Idéntica →
posible fusión; distinta o incompleta → no fusionar. Nunca convierte `SIMPLE +
CESSATION` en un claim único.

> `temporal_signature` debe estar **normalizada y ser determinista**. Si se deriva
> de expresiones temporales en crudo, dos formas de escribir la misma fecha darán
> firmas distintas y el reconciliador dejará de fusionar cosas idénticas — o peor,
> fusionará según cómo estuviera escrito el texto.

## 9. Salida determinista y canónica (contrato, no detalle)

Misma entrada → mismos grupos, mismos identificadores derivados, mismo orden, misma
serialización. Con independencia del orden de llegada, la concurrencia, el orden de
los diccionarios o qué proveedor respondió antes.

Orden canónico de menciones: `workspace`, `source_id`, `episode_id`, `start_offset`,
`end_offset`, `mention_type`, `surface_normalized`, `proposal_origin`.
De claims: `episode_id`, `evidence_start`, `subject_anchor`, `predicate`,
`object_anchor`, `negated`, `negation_kind`, `epistemic_status`,
`temporal_signature`, `origin`.

Identificadores derivados de **hash canónico del contenido**, nunca de contadores
dependientes del orden de ejecución.

Invariancias probadas:

```
reconcile(input) == reconcile(shuffle(input))     # permutación
reconcile(reconcile(input)) == reconcile(input)   # idempotencia
serialize(run1) == serialize(run2)                # reproducibilidad
```

> La idempotencia **solo es formulable si la salida es del mismo tipo que la
> entrada** (propuestas reconciliadas, no "grupos" de otro tipo). Hay que decidirlo
> en el diseño: o la salida es reintroducible, o el test se enuncia de otra forma.

## 10. Rendimiento

Etapa propia instrumentada: `s9_stage_duration_seconds{stage="reconciliation"}`,
`s9_reconciliation_{input_proposals,output_proposals,groups,merged,preserved_ambiguous}_total`.
Medir tiempo total y por episodio (p50, p95, máximo), memoria, propuestas de entrada
y salida, grupos, fusionadas y preservadas por duda.

Regla, sin límite arbitrario en milisegundos: **el reconciliador no puede
convertirse en etapa dominante**. Con los modelos actuales la extracción tarda
decenas o cientos de segundos por episodio, así que debe ser una fracción pequeña —
**pero hay que medirlo también en modo sin LLM**, porque en la ruta determinista una
implementación cuadrática sería el nuevo cuello de botella.

Agrupar primero por claves baratas (episodio → zona de offsets → tipo → polaridad →
evidencia) y comparar solo dentro de esos grupos. Nada de todos contra todos.

## 11. Tests imprescindibles

| Caso | Esperado |
|---|---|
| Misma mención, ids distintos (`det-m1`/`sem-m9`, `Toturi [0,6]`) | **Fusiona** |
| Alias distinto (`Toturi [0,6]` / `el Emperador [20,31]`) | No fusiona |
| Pronombre (`Toturi` / `él`) | No fusiona |
| Qwen + Llama, mismo prompt | `providers 2`, `independent_families 1` |
| Determinista + semántico | `providers 2`, `independent_families 2` |
| `lideraba` / `ya no lidera` | No fusiona |
| `pertenece` / `no pertenece` | No fusiona |
| `dejó de liderar` / `no dejó de liderar` | No fusiona |
| 100 permutaciones de la misma entrada | Salida idéntica |
| Doble pasada | Idempotente |
| Rendimiento | 10, 100, 1.000 propuestas; duplicados masivos; sin fusiones |
| **Un solo extractor** | **Identidad**: sin nada que reconciliar, la salida es la entrada. Protege la ruta determinista de los gates |
| **Menciones solapadas conservadas** | No producen entidades ni claims duplicados aguas abajo |
| **ACEPTACIÓN** | **Los 8 claims del semántico sobreviven a la unión** |

## 12. Secuencia

```
1. Cerrar y medir la baseline actual                    ← hecho
2. Implementar el reconciliador con alcance textual estricto
3. Declarar las familias de independencia
4. Salida canónica y determinista
5. Regla "ante la duda, conservar"
6. Tests de reproducibilidad y rendimiento
7. Repetir A, C1, C2 y D
8. ¿Sobreviven los ocho claims semánticos?
9. Analizar qué pérdidas quedan en el resolutor o en el motor
10. Después, la política de aprobación de negaciones
```

## 13. Verificación de la implementación

Verificado el 2026-07-30 sin modificar los contratos congelados ni efectuar
inferencia de red:

- Los 10 casos de `data-engine/app/tests/test_knowledge_v3_reconcile.py` cubren
  fusión textual, conservación ante polaridad/predicados rivales, familias de
  independencia, permutaciones, idempotencia, identidad de un extractor y el
  caso mínimo de aceptación.
- `test_knowledge_v3_reconcile_validation.py` añade procesos independientes con
  `PYTHONHASHSEED=0`, `1` y `random`. Los tres produjeron exactamente el mismo
  SHA-256 canónico:
  `8325f19204fc7eb9836cab6b3f560bf4912ffff3b1a5c97effb2cef56137f3d2`.
- El benchmark sintético, generado con `random.Random(20260730)`, obtuvo para
  10/100/1.000 propuestas medianas de 0,310/37,147/81,831 ms (siete pasadas;
  mínimos 0,271/35,649/81,082 ms). Las claves se agrupan mediante tablas hash y
  cada grupo se ordena canónicamente: la estructura observada es compatible con
  coste O(n log n), sin comparación todos-contra-todos. El test exige 1.000
  propuestas en menos de 30 s y un umbral de escala deliberadamente generoso.
- El arnés `knowledge_v3.extraction.semantic_bench` incorpora `D-R`: ejecuta
  `ProposalReconciler` sobre la unión D. Con las 16 respuestas del caché
  `docs/v3/measurements/runs/c1-cache.json` (16 hits, 0 misses), C1 obtiene 8
  claims correctos (F1 0,421053), D obtiene 0 (F1 0) y D-R recupera los 8
  (F1 0,421053). D-R reduce los falsos positivos de menciones de 43 a 16.
  En la corrida documentada, D tardó 235 ms y D-R 445 ms (210 ms añadidos
  por reconciliación, incluida la validación contractual).
  El resultado completo queda en
  `docs/v3/measurements/runs/bench-C1-D-DR.json`.
- El criterio normativo de los ocho claims queda fijado explícitamente por
  `test_aceptacion_los_ocho_claims_de_c1_sobreviven_en_D_R`; el test anterior
  `test_aceptacion_la_union_no_puede_destruir_los_claims_del_semantico`
  conserva además el caso mínimo unitario de un claim.

Comando offline reproducible:

```bash
PYTHONPATH=data-engine/app python3 -m knowledge_v3.extraction.semantic_bench \
  --config A --config C1 --config D --config D-R \
  --cache docs/v3/measurements/runs/c1-cache.json \
  --out docs/v3/measurements/runs/bench-C1-D-DR.json
```
