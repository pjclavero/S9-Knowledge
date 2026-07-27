# 52 · Motor de extracción de relaciones — Informe para auditoría externa

**Estado:** el motor está **congelado en `main`** (rama `main`, commit de cierre del
programa de calibración) y **no está activado en producción**: no ingiere, no escribe
en Neo4j y no autoaprueba nada. Este documento resume **cómo funciona**, **qué
problemas tiene** y **por dónde mejorarlo**, para que un revisor externo pueda
auditarlo sin conocimiento previo del proyecto.

> **Hallazgo material del programa de calibración (0-9):** medido de verdad con dos
> proveedores distintos (Ollama y NVIDIA), la calidad actual **no justifica reducir la
> supervisión humana**. El cuello de botella no es el modelo de IA, sino el **anclaje
> de evidencia** (localizar la cita literal exacta que respalda cada relación). Este
> informe explica por qué y propone líneas de mejora.

---

## 1. Qué hace el motor (visión de una frase)

Dado un documento ya segmentado con entidades reconocidas, el motor propone
**relaciones candidatas** entre pares de entidades (p.ej. `A —MEMBER_OF→ B`), cada
una con su **evidencia textual**, su predicado, dirección, negación, temporalidad y
estado epistémico (afirmado / rumor / hipotético). Todo en **DRY-RUN**: produce
candidatos, **no** los escribe en la base de conocimiento.

---

## 2. Arquitectura y ficheros (mapa para el auditor)

El paquete vive en `data-engine/app/relations/`. Import root de la app:
`data-engine/app`. El pipeline es **un orquestador**: no reimplementa las piezas, las
encadena.

### 2.1 Flujo de datos (end-to-end, determinista)

```
payload {workspace, document, segments:[{text, entities:[{id,start,end,type}]}]}
   │
   ▼
[pairs.generate_pairs]      → pares candidatos (A,B) dentro de una ventana
   │
   ▼
[signals.compute_all_signals] → señales heurísticas explicables
   │                             (misma frase, SVO, distancia, negación,
   │                              modalidad, rumor, compatibilidad de tipos…)
   ▼
[syntax.get_analyzer("heuristic")] → estructura sintáctica (stdlib, sin red)
   │
   ▼
[pipeline._build_candidate] → RelationCandidate (contrato de 20 campos)
   │   predicado, dirección, confianza, EVIDENCIA (span literal), temporalidad,
   │   epistémico, negación…
   ▼
[local_llm_shadow] (opcional)   ┐  proveedores EN SOMBRA, desactivados por defecto,
[external_ai_shadow] (opcional) ┘  jamás deciden ni escriben; sólo opinan
   │
   ▼
[consensus_adapter.compute_relation_consensus] → estado canónico
       (STRONG_CONSENSUS / PARTIAL / MODEL_CONFLICT / INVALID / HUMAN_REQUIRED)
   │
   ▼
salida JSON/JSONL determinista + traza de observabilidad redactada
```

### 2.2 Ficheros clave

| Fichero | LOC | Rol | Relevancia para la auditoría |
|---|---:|---|---|
| `relations/pipeline.py` | 943 | **Orquestador end-to-end** (DRY-RUN). Construye el candidato y ancla la evidencia. | **ALTA** — aquí está el defecto de anclaje (`_build_candidate`, líneas 310-351). |
| `relations/contracts.py` | 356 | Contrato `RelationCandidate` (20 campos), validación, serialización. | Media — define qué es una relación válida (campos 8-10 = evidencia). |
| `relations/pairs.py` | 482 | Generación determinista de pares candidatos y su ventana de contexto. | Media — recall de pares (¿se generan todos los pares reales?). |
| `relations/signals.py` | 578 | Señales heurísticas explicables (misma frase, SVO, distancia, tipos…). | Media — base del predicado y la confianza. |
| `relations/syntax.py` | 848 | Analizador sintáctico heurístico (stdlib, sin dependencias pesadas). | Media — estructura SVO. |
| `relations/prompts/templates.py` | 838 | Plantillas de prompt versionadas por predicado (para los LLM en sombra). | **ALTA** — el prompt es donde se le pide al modelo la evidencia literal. |
| `relations/external_ai_shadow.py` | 594 | Proveedor externo (NVIDIA NIM) en sombra: prompt → verdicto, validación estricta. | **ALTA** — rechaza por evidencia (líneas 320-338). |
| `relations/local_llm_shadow.py` | 697 | Proveedor local (Ollama) en sombra. | Alta — mismo patrón que el externo. |
| `relations/consensus_adapter.py` | 557 | Consenso entre heurística + local + externo → estado canónico. | Media. |
| `relations/epistemic.py` | 245 | Clasificación epistémica (afirmado/rumor/hipotético/intención). | Baja-Media. |
| `relations/temporality.py` | 313 | Clasificación temporal (pasado/futuro/en curso/terminado). | Baja-Media. |
| `relations/vocabulary.py` | 265 | Vocabulario canónico de predicados (alias, simetría). | Baja. |
| `relations/observability.py` | 485 | Traza/eventos redactados (no vuelca texto en claro). | Baja. |
| `relations/benchmark/` | — | Arnés de medición (matching, métricas, informe, CLI). **No es el motor**, es el metro. | **ALTA para auditar la medición**. |

---

## 3. El problema central: **anclaje de evidencia**

Una relación sólo es utilizable si viene con la **cita exacta** del texto que la
justifica (`evidence_text` + offsets `evidence_start`/`evidence_end`). Ahí es donde
el motor falla, en **dos capas de la misma causa**.

### 3.1 Capa heurística — la evidencia es un span mecánico, no la cita justa

En `pipeline.py:310-351` (`_build_candidate`):

```python
lo = min(pair.subject_start, pair.object_start)
hi = max(pair.subject_end, pair.object_end)
...
evidence_text = seg_text[lo:hi]        # ← span que va de una mención a la otra
```

La evidencia es **todo el tramo de texto entre las dos entidades** (desde la primera
mención hasta la última). Eso tiene dos consecuencias:

- Si las entidades están separadas en la frase, ese span **arrastra texto de sobra**
  (cláusulas intermedias que no son la justificación).
- El benchmark puntúa la evidencia por **IoU** (intersección/unión) contra el span
  curado del ground truth, con umbral `EVIDENCE_IOU_THRESHOLD = 0.5`
  (`benchmark/matching.py:52,91-97,142-143`). Un span demasiado ancho tiene **unión
  grande → IoU bajo → `evidence_correct = False`**.

La puerta de calidad exige que el **80 %** de las relaciones simples tengan la
evidencia bien anclada (`report.py THRESHOLDS["evidence"] = 0.80`). Con evidencia
mecánica, no se llega.

> Matiz importante: `offsets_correct` sólo exige **solapamiento > 0**
> (`matching.py:144`) y su umbral es 0.90 — es más fácil de cumplir. El que se cae es
> **`evidence`** (IoU ≥ 0.5), es decir, no basta con "tocar" la zona: hay que acertar
> el span con precisión razonable.

### 3.2 Capa LLM — el modelo no devuelve una cita literal con offsets consistentes

Cuando se activan los proveedores en sombra, al modelo se le pide explícitamente
(`external_ai_shadow.py:245-247`, `prompts/templates.py`):

```
"evidence_text": <cita LITERAL copiada del DOCUMENTO, NUNCA inventada>,
"evidence_start": <offset int >= 0>, "evidence_end": <offset int >= start>
```

y el validador **rechaza en firme** si la cita no cuadra
(`external_ai_shadow.py:320-338`):

- `evidence_text` vacía o ausente → rechazo;
- `evidence_text` **no es subcadena literal** del segmento → `evidencia_inexistente`;
- `segmento[start:end]` **no coincide** con `evidence_text` → `offsets_invalidos`.

Resultado medido en el Bloque 7 (real, no simulado): **NVIDIA 27/27 y Ollama con la
mayoría de rechazos por evidencia**. Los modelos tienden a **parafrasear** la cita o a
dar offsets que no casan carácter a carácter, y el validador —correctamente estricto,
para no meter basura— los tira.

### 3.3 Síntesis del cuello de botella

Ambas capas dicen lo mismo: **el sistema todavía no sabe señalar, con precisión de
offsets, la porción mínima de texto que prueba cada relación.** La heurística la
sobre-extiende; el LLM la parafrasea. Por eso:

- la métrica `evidence` no supera su umbral;
- P/R/F1 salen **idénticos con y sin proveedores** (0.7407 / 0.7692 / 0.7547): el LLM
  no aporta mejora porque su aportación se cae en la validación de evidencia
  → **garantía de sombra confirmada**, pero también **techo de calidad confirmado**;
- la política de reducción de revisión (Bloque 8) da **0 % de cobertura
  auto-proponible**: sin evidencia fiable, nada puede aprobarse sin humano
  (fail-closed a `REVIEW_REQUIRED`), que es el comportamiento correcto.

---

## 4. Observaciones secundarias (para que el auditor no las pase por alto)

1. **Confianza heurística fija y poco discriminante** (`pipeline.py:287-301`): suma de
   bonificaciones acotada a 0.9; no está calibrada contra aciertos reales, así que no
   sirve como probabilidad.
2. **Predicado por defecto genérico** (`GENERIC_PREDICATE = "RELATED_TO"`): cuando
   ninguna señal decide, se cae a un predicado poco informativo; conviene medir qué
   fracción de candidatos termina en `RELATED_TO`.
3. **Analizador sintáctico heurístico** (stdlib): sin dependencia de un parser real
   (spaCy/stanza). Es robusto y sin red, pero limita la calidad de la estructura SVO y,
   por tanto, de la dirección y del predicado.
4. **Recall de pares acotado por ventana** (`pairs.py`, `context_mode="sentence"`):
   relaciones inter-frase (correferencia, cadenas largas) pueden no generar par → falso
   negativo que ninguna mejora de evidencia arreglaría.
5. **Estrictez de offsets del validador LLM**: es correcta para seguridad, pero hoy es
   binaria; no admite una tolerancia controlada (p.ej. normalización de espacios) que
   podría recuperar respuestas buenas con offsets levemente desalineados.

---

## 5. Cómo reproducir y medir (para el auditor)

Todo es **offline y determinista**; no requiere red ni secretos.

```bash
# desde data-engine/app
python3 -m pytest tests/ -k relation -q          # 890 tests del motor + arnés

# suite de invariantes transversales (garantías de seguridad del programa)
python3 -m pytest tests/test_relation_calibration_final_quality_block9.py -q
```

- **Umbrales de calidad**: `relations/benchmark/report.py` → `THRESHOLDS`
  (evidence=0.80, offsets=0.90, simple_relations_recall=0.80, negation=0.80,
  temporality=0.60, rumors=0.60, predicate_structural=0.50). **No deben bajarse**; si el
  auditor propone tocarlos, que lo justifique aparte.
- **Emparejamiento y evidencia**: `relations/benchmark/matching.py`
  (`structural_flags`, `EVIDENCE_IOU_THRESHOLD`).
- **Resultados del benchmark**: `docs/50-relation-benchmark-results.md`.
- **Runtime del pipeline**: `docs/51-relation-pipeline-runtime.md`.
- **Informe de cierre del programa**:
  `docs/coordination/sequential-program/program-closure-report.md`.

---

## 6. Ideas de mejora (priorizadas, para debatir con el auditor)

> Ninguna de estas ideas está implementada; son hipótesis a evaluar. **Cualquier
> cambio debe medirse con el mismo benchmark antes/después y mantener las garantías de
> la §7.**

### Prioridad ALTA — atacan directamente el anclaje de evidencia

1. **Anclar la evidencia a la frase mínima, no al span entre menciones.** Sustituir
   `seg_text[lo:hi]` por la **cláusula/frase que contiene ambas menciones**
   (`signals._sentence_bounds` ya calcula límites de frase). Debería subir el IoU
   drásticamente sin tocar el modelo. *Bajo riesgo, alto impacto esperado.*
2. **Re-alinear la cita del LLM contra el texto** en lugar de rechazarla: si el modelo
   devuelve `evidence_text` parafraseada, buscar el **mejor match literal** en el
   segmento (fuzzy/`difflib`) y **recomputar los offsets** desde el texto real; sólo
   rechazar si no hay match por encima de un umbral. Convierte muchos rechazos en
   aciertos **sin relajar la garantía** (la evidencia sigue siendo literal del
   documento).
3. **Tolerancia de offsets controlada y auditable**: normalizar espacios/comillas antes
   de comparar `segmento[start:end]` con `evidence_text`; documentar la normalización.
   Recupera respuestas buenas con desalineación trivial.

### Prioridad MEDIA — mejoran la base sobre la que se ancla

4. **Prompt few-shot centrado en la cita**: añadir ejemplos en `prompts/templates.py`
   que muestren *exactamente* cómo copiar la subcadena y contar offsets; pedir al modelo
   que **devuelva sólo índices** (start/end) y que el sistema extraiga la cita, en vez de
   pedir la cita en texto (elimina la paráfrasis de raíz).
5. **Confianza calibrada**: sustituir la suma fija (`_confidence`) por una calibración
   (isotónica/Platt) contra el ground truth, para que `confidence` sea una probabilidad
   real utilizable por la política de revisión.
6. **Parser sintáctico opcional**: permitir un proveedor de sintaxis más fuerte
   (spaCy/stanza) detrás del mismo interfaz `get_analyzer`, activable y medible, sin
   romper el modo stdlib por defecto.

### Prioridad BAJA — cobertura y robustez

7. **Ventana inter-frase para pares**: evaluar `context_mode` que capture relaciones a
   más de una frase, midiendo el trade-off recall/ruido.
8. **Endurecer el chequeo AST de sombra** (deuda declarada en el Bloque 9): el test de
   "no importar neo4j" es evadible por `importlib`/`__import__` indirecto; reforzarlo.

### Enfoque de medición sugerido para el auditor

- Empezar por la idea **1** (frase mínima) y volver a correr el benchmark: si la métrica
  `evidence` sube por encima de 0.80 sólo con eso, gran parte del problema es
  presentación de la evidencia, no capacidad del modelo.
- Después la **2** (re-alineado del LLM) para ver si el proveedor deja de salir plano
  frente al offline.
- Cada experimento: **A/B con el mismo corpus**, tabla antes/después por métrica.

---

## 7. Qué NO se debe romper (garantías innegociables)

El programa de calibración fijó como tests ejecutables (48 pruebas en
`tests/test_relation_calibration_final_quality_block9.py`) siete invariantes. Cualquier
mejora debe **conservarlos**:

1. **Garantía de sombra**: los proveedores nunca escriben en Neo4j ni deciden.
2. **Fail-closed**: sin modelo/endpoint explícito no se contacta ningún proveedor real.
3. **Umbrales de calidad intactos**: no bajar `THRESHOLDS` para "aprobar".
4. **Política de revisión fail-closed**: por defecto `REVIEW_REQUIRED`.
5. **Doble llave** para activar proveedores (`--enable-providers` + `S9K_BENCH_PROVIDERS=1`).
6. **Clasificación de proveedor** con default seguro (INDETERMINATE).
7. **Manifiesto fail-closed**: autenticidad (HMAC) ≠ integridad (sha256).

Y las prohibiciones operativas del proyecto: no desplegar, no ingerir en real, no tocar
VM105/Neo4j/`auth.db`/`jobs.db`, no crear tag/Release RC6, no imprimir secretos.

---

## 8. Resumen para el auditor externo (TL;DR)

- El motor **funciona, es determinista y es seguro** (todo en sombra, sin escritura).
- **No es apto para ingesta todavía** porque **no ancla la evidencia con precisión**:
  la heurística sobre-extiende el span y el LLM parafrasea la cita; ambos fallan la
  validación de evidencia (IoU ≥ 0.5 / subcadena literal + offsets).
- El techo está en la **presentación/localización de la evidencia**, no en el modelo:
  NVIDIA y Ollama dan **exactamente las mismas métricas** que el modo offline.
- **Primer experimento recomendado**: anclar la evidencia a la **frase mínima** que
  contiene ambas menciones y re-medir. Es barato y ataca la causa directa.
- **No tocar** las siete garantías de la §7 ni los umbrales.
