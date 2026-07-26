# Bloque 1 — Cierre de defectos abiertos del motor V2

**Programa:** "Motor V2 temporal, episódico y trazable" (S9-Knowledge).
**Rama:** `exp/relation-engine-v2-temporal-provenance-v1`.
**Base:** `97b9a51` (Bloque 0: auditoría y baseline reproducible).
**Alcance:** cerrar o encapsular los seis defectos abiertos localizados por el Bloque 0.
**NO es un bloque de calidad:** ninguna métrica del motor puede moverse, y no se ha movido
(ver §3, neutralidad demostrada a nivel de hash).

---

## 1. Resumen ejecutivo

| # | Defecto | Estado | Cómo |
|:-:|---|:--:|---|
| 1 | B5-D4 — caché de texto crudo, sin TTL ni reset del singleton | **CERRADO** | Clave por huella, ámbito por ejecución, TTL, `reset_default_analyzer()`, métricas |
| 2 | B5-D7 — objeto cacheado compartido por identidad | **CERRADO** | Copia profunda al guardar y al servir; lo guardado no sale nunca |
| 3 | B7 — dos envolventes de aceptación (`TIER_NORMALIZED`) | **CERRADO** | Se cierra el camino **permisivo**: `REALIGN_OK_TIERS = {exact}` |
| 4 | B7 — `validate_external_verdict` sin llamador de producción | **CERRADO** | Conectada: el camino real del motor delega en ella |
| 5 | Señal de negación 4/9 | **ENCAPSULADO + MEDIDO** | Nueva métrica de **precisión** que sí puede ponerse roja; el camino de rechazo NO se promociona |
| 6 | `pair_F1 = 0.8113` con 11 FN | **DOCUMENTADO** | Fuera de alcance por instrucción: es el Bloque 2 |

Prohibiciones respetadas: no se tocó `.github/workflows/`, ni `THRESHOLDS`, ni el corpus, ni
el ground truth (`15973d18…cc5c` idéntico en las cuatro corridas), ni
`RelationCandidate/internal-v1`, ni los defaults del motor (`predicate_selector="v1"`,
`consensus_policy="auto"`, proveedores `False`, `external_protocol="legacy"`). No hubo red,
ni proveedores reales, ni Neo4j, ni ingestas, ni despliegues.

---

## 2. Defecto por defecto

### 2.1 B5-D4 — Retención global de texto crudo (CERRADO)

**Era:** `relations/syntax.py` guardaba `(texto_crudo, idioma) -> SyntaxAnalysis` en un
singleton de proceso (`_DEFAULT_ANALYZER`), sin TTL, con LRU 512 como único desalojo, sin
función de reset del singleton y sin ningún llamador que lo limpiase. El texto quedaba
retenido **dos veces** (en la clave y en el valor) y cruzaba fronteras de documento y de
workspace en un proceso longevo.

**Ahora:**

| Exigencia | Implementación | Test que la fija |
|---|---|---|
| Caché acotada | LRU (`maxsize`, 512 por defecto) **+ TTL** (`DEFAULT_CACHE_TTL_SECONDS = 900 s`), reloj inyectable | `test_desalojo_LRU_real_y_metricas_de_la_cache`, `test_la_cache_CADUCA_por_antiguedad_no_solo_por_LRU` |
| Aislamiento por documento/ejecución | `scope` forma parte de la clave; `set_scope()` **purga**; el pipeline crea un analizador por corrida (`new_scoped_analyzer("{ws}\|{doc}\|{exec}")`) y lo descarta al terminar | `test_RUTA_REAL_el_pipeline_usa_un_analizador_POR_EJECUCION` |
| API explícita de reset del singleton | `syntax.reset_default_analyzer()`, en `__all__`, idempotente | `test_reset_default_analyzer_DESCARTA_el_singleton_de_modulo` |
| No conservar texto innecesariamente | La clave es `(scope, idioma, sha256(texto), len)`: el texto ya **no** vive en la clave | `test_la_clave_de_la_cache_NO_es_el_texto_crudo` |
| No compartir contenido entre workspaces | El ámbito lleva el workspace; ámbitos distintos no comparten ninguna entrada, y cambiar de ámbito purga la retención | `test_dos_ambitos_distintos_no_comparten_entrada`, `test_la_cache_esta_AISLADA_POR_AMBITO_y_purga_al_cambiar` |
| Métricas hits/misses/evictions | `stats()` (+ `expirations`, `size`), volcadas a la **traza** del pipeline | `test_desalojo_LRU_real_y_metricas_de_la_cache`, `test_RUTA_REAL_las_metricas_de_cache_llegan_a_la_traza` |
| Tests de proceso longevo | 3 documentos × 400 segmentos: el tamaño nunca supera el tope y no queda retención al cerrar | `test_proceso_LONGEVO_no_crece_sin_limite_ni_retiene_al_final` |

**Dónde van las métricas y por qué.** A la observabilidad (`component="pipeline.syntax_cache"`),
no a `summary`. `summary` entra en el `result_hash` funcional: meter ahí una medida de
eficiencia cambiaría el hash de dos salidas idénticas. La traza está excluida de ese hash a
propósito. Requirió añadir un campo `metrics: dict` (sólo numérico) a `RelationEvent`; es
aditivo y no toca el contrato `internal-v1`.

**Un acierto no renueva el TTL.** La entrada caduca por antigüedad, no por desuso: si el
acierto reiniciase el reloj, un texto muy consultado quedaría retenido para siempre, que es
literalmente el defecto. Fijado por `test_un_acierto_NO_renueva_el_TTL`.

### 2.2 B5-D7 — Objeto compartido por identidad (CERRADO)

`SyntaxAnalysis` es `frozen`, pero `object.__setattr__` lo salta, y el acierto devolvía **el
mismo objeto** a todos los llamadores.

La caché ahora guarda una **copia profunda privada** y entrega **otra copia profunda** en cada
acierto: el objeto almacenado no sale nunca del analizador. Se eligió copia profunda y no
`dataclasses.replace` porque `SyntaxAnalysis` contiene tuplas de `SyntaxSentence`/`SyntaxToken`
igualmente congelados: una copia superficial dejaba el vector abierto un nivel más abajo (lo
confirmó el mutante M8, ver §4).

Control de no-trivialidad: `test_la_cache_sigue_siendo_METRIC_NEUTRAL` compara la salida
cacheada con la del analizador desnudo — cachear con copia no cambia ni un campo.

### 2.3 B7 — Envolvente de aceptación (CERRADO, por el lado estricto)

**Era:** el realineador declaraba dos peldaños aceptables (`exact`, `normalized`). El camino de
API (`external_consult`) alcanzaba los dos; el camino real del motor (`external_ai_shadow`)
corta antes con `ev not in seg`, así que `TIER_NORMALIZED` era **inalcanzable en producción**.
Dos envolventes para la misma garantía.

**Regla aplicada (innegociable):** se cierra el camino **más permisivo**, jamás se abre el
estricto. En concreto:

* `evidence_realignment.REALIGN_OK_TIERS` pasa de `{exact, normalized}` a `{exact}`.
* `realign_evidence_unique` sigue **calculando** el peldaño normalizado, pero devuelve
  `ok=False, tier="normalized"`: es un **diagnóstico** ("casaba salvo tipografía"), no una
  aceptación. Se conserva porque produce un código de error distinguible; no ancla nada.
* Consecuencia: `PROTOCOL_REALIGNMENT` y `allow_realignment_fallback` quedaban sin rama que
  los emitiese. Se **eliminan**: un interruptor de seguridad que enciende una envolvente que
  el camino real no tiene es exactamente una API de seguridad decorativa.

Efecto en producción: **ninguno**. En el camino real ese peldaño ya era inalcanzable; el
cambio sólo elimina la divergencia. Es más estricto, nunca más laxo (fail-closed).

Fijado por `test_REALIGN_OK_TIERS_solo_admite_exact`,
`test_TIER_NORMALIZED_no_ancla_en_NINGUNA_de_las_dos_rutas` y, sobre todo,
`test_las_dos_rutas_ACEPTAN_EXACTAMENTE_LO_MISMO`, que barre siete citas por **ambos** caminos
y exige que acepten y rechacen lo mismo, con un control de no-trivialidad (al menos una se
acepta).

### 2.4 B7 — `validate_external_verdict` sin llamador (CERRADO, conectada)

**Era:** 28 referencias en 2 ficheros, 23 llamadas y todas de tests. Cero producción.

**Ahora:** el camino real la invoca. `external_ai_shadow._validate_verdict` ya no reimplementa
el anclaje (llamada suelta a `realign_evidence_unique`): llama a
`external_consult.validate_external_verdict` y **sólo emite verdicto si devuelve `ACCEPTED`**,
tomando de ella `evidence_text`/`evidence_start`/`evidence_end`. La envolvente pasa a existir
en un único sitio.

Se conservan los comprobantes propios del camino real (literalidad `ev in seg` y validación de
los offsets que manda el modelo) porque son **adicionales**, no alternativos: son más
estrictos que lo que exige `external_consult`, y quitarlos habría relajado el camino real para
igualarlo — precisamente lo prohibido.

Para que la delegación fuese posible sin relajar nada hubo que **cerrar un hueco simétrico** en
`validate_external_verdict`: tenía un cortocircuito que devolvía sin mirar la cita cuando el
veredicto era `uncertain`, mientras el camino real sí la validaba. Ahora la evidencia se
resuelve para **todo** veredicto. Es estrictamente más validación; la postura de `uncertain`
sigue siendo `ABSTAIN` pase lo que pase (`_VERDICT_STANCE`), y `apply_consultation` sólo mira
la postura, así que la decisión es idéntica: lo único que cambia es que el `status` deja de
mentir.

Pruebas de ruta real: `test_LA_RUTA_REAL_PASA_POR_validate_external_verdict` (espía sobre la
función, entrando por `_validate_verdict`) y
`test_LA_RUTA_REAL_COMPLETA_pasa_por_validate_external_verdict` (entrando por la puerta
pública `evaluate_relation_external` con un proveedor falso, protocolo `legacy`, sin red).

**Se descartó eliminarla por código muerto**: `_resolve_evidence`, `ExternalConsultConfig` y el
protocolo de fragmentos cuelgan de ella; borrarla arrastraba una cascada mucho mayor que el
alcance de un bloque de defectos, y la alternativa ofrecida (conectarla a una ruta real con
tests de integración) era realizable sin relajar ninguna garantía.

### 2.5 Señal de negación 4/9 (ENCAPSULADO + MEDIDO)

**El camino de rechazo NO se ha promocionado.** `relations/abstention.py` no se ha tocado:
`reject_on_negation=True` y `predicate_abstention_blocks_reject=True` siguen exactamente como
estaban, en sombra, a la espera del held-out que construye otro agente (no se ha tocado nada
suyo). Fijado por `test_el_camino_de_RECHAZO_por_negacion_NO_se_promociona`.

**El hallazgo del coordinador se confirma y se ataja.** El gate `negation` lee
`negated_relations.negation_correct`, que es el **recall** sobre las 4 relaciones negadas del
ground truth: vale 1.0 y **no puede ponerse rojo** por muchos falsos positivos que dispare la
señal. Es un gate que no puede fallar.

Se añade `structural_quality.negation_signal` — la **precisión** de la señal, que es lo que
gobierna los rechazos — y el gate `negation_precision`:

```
predicted_positive = 9   true_positive = 4   false_positive = 5   precision = 0.4444
```

Que sí se pone rojo, y se demuestra que puede hacerlo con un test que lo fuerza en ambas
direcciones (`test_el_gate_negation_NO_PUEDE_ponerse_rojo_y_el_nuevo_SI`: con 0, 5 y 30 falsos
positivos, `negation` sigue en PASS y `negation_precision` pasa a FAIL).

**Por qué es INFORMATIVA y no gobierna el dictamen.** Es la decisión declarada del bloque, y la
instrucción la contemplaba explícitamente. `decide_verdict` deriva el dictamen de una lista
cerrada de gates de calidad; meter ahí una métrica que **nace en rojo** cambiaría el dictamen
de las cuatro corridas por una medición que ya era verdad antes de este bloque. Eso convertiría
un bloque de cierre de defectos en un cambio de veredicto encubierto. Convertirla en gate duro
es una decisión de calidad y corresponde al Bloque 2 o posterior. Lo que se cierra hoy es la
**ceguera**: la cifra existe, se publica en el JSON y en el Markdown del arnés, y puede
ponerse roja.

`THRESHOLDS` queda **intacto** (test que lo fija literal); el suelo nuevo vive aparte en
`report.NEGATION_PRECISION_FLOOR = 0.80`, que es aditivo.

Sin positivos predichos la métrica se declara `NOT_EVALUATED`, no 0.0 ni 1.0: "no medido" no
es "medido y bien".

### 2.6 `pair_F1 = 0.8113` con 11 FN (DOCUMENTADO, fuera de alcance)

No atacado, por instrucción explícita: es el Bloque 2. Se confirma en las cuatro corridas de
este bloque, idéntico a la baseline B0:

```
P=0.8269  R=0.7963  F1=0.8113  TP=43  FP=9  FN=11
```

El selector de predicados no cambia la generación de pares, sólo el nombre del predicado; por
eso v1 y v2 comparten `pair_F1`. Las 11 relaciones del ground truth que nunca se emparejan
(elipsis de sujeto, direccionalidad `PARENT_OF`, alias reflexivo, pronombre objeto) siguen sin
generarse: si el par no se genera, no hay nada que corregir aguas abajo.

---

## 3. Neutralidad: A/B contra la baseline del Bloque 0

Cuatro corridas (`baseline1` y `ensemble_offline` × selector `v1` y `v2`), proveedores
desactivados, corpus intacto. Artefactos en `artifacts/relation-v2e/blocks/b01/`.

| Corrida | F1 B0 → B1 | TP/FP/FN B0 → B1 | Dictamen | `result_hashes` idénticos | `negation_precision` |
|---|---|---|---|:--:|---|
| `baseline1` v1 | 0.8113 → 0.8113 | 43/9/11 → 43/9/11 | `APTO CON REVISION HUMANA TOTAL` (igual) | **sí** | 0.5000 · PARTIAL |
| `baseline1` v2 | 0.8113 → 0.8113 | 43/9/11 → 43/9/11 | `APTO PARA CONTINUAR EN MODO SOMBRA` (igual) | **sí** | 0.4444 · FAIL |
| `ensemble_offline` v1 | 0.8113 → 0.8113 | 43/9/11 → 43/9/11 | `APTO CON REVISION HUMANA TOTAL` (igual) | **sí** | 0.5000 · PARTIAL |
| `ensemble_offline` v2 | 0.8113 → 0.8113 | 43/9/11 → 43/9/11 | `APTO PARA CONTINUAR EN MODO SOMBRA` (igual) | **sí** | 0.4444 · FAIL |

`result_hashes` es el hash funcional por fuente que emite el propio pipeline (16 fuentes). Que
coincida uno a uno con el de B0 es una prueba más fuerte que comparar métricas agregadas:
**la salida del motor es byte a byte la misma**. `deterministic=True` y `verdict_scope=COMPLETO`
en las cuatro. `ground_truth_sha256 = 15973d18…cc5c` en las cuatro, igual que en B0.

Los dos valores de `negation_precision` reproducen exactamente lo que midió el Bloque 0: 4/8
con selector v1 y 4/9 con v2. La métrica es nueva; la realidad que describe no.

Rendimiento (`performance.json`): el `wall` de las cuatro corridas queda en 0,43–0,52 s frente
a 0,47–0,59 s en B0, y `harness_total_ms` en 59–89 ms frente a 51–97 ms. La copia profunda de
la caché no produce una regresión medible a esta escala; con 16 fuentes y textos cortos el
ruido de medida domina, así que **no se afirma mejora ni empeoramiento**.

---

## 4. Mutación

18 mutantes aplicados sobre el código de **producción** (no sobre alias ni constantes muertas),
purgando `__pycache__` antes y después de cada uno. Registro completo en
`artifacts/relation-v2e/blocks/b01/mutation-log.md`.

**Resultado final: 18/18 muertos.** Dos supervivientes en la primera ronda, ambos reportados y
corregidos con tests nuevos (no se relajó ningún mutante):

| Superviviente | Por qué sobrevivió | Cómo se mató |
|---|---|---|
| **M3** `DEFAULT_CACHE_TTL_SECONDS = None` | Todos los tests de TTL inyectaban el valor a mano; ninguno comprobaba que el analizador **de producción** naciera con caducidad | `test_el_analizador_de_PRODUCCION_nace_con_TTL_y_con_tope` |
| **M8** copia superficial (`dataclasses.replace`) | El test de anidamiento envenenaba el objeto del **fallo** de caché, que no es el que se guarda; con copia superficial la contaminación sólo viaja por el objeto servido en un **acierto** | Se reescribió `test_la_contaminacion_alcanza_tambien_a_las_estructuras_anidadas` para envenenar el objeto de un acierto y comprobar el tercer llamador |

Los dos supervivientes son hallazgos reales de este bloque: en ambos casos el invariante estaba
enunciado pero el test no lo ejercía en la ruta que importaba. Es el mismo patrón que el
Bloque 0 denunció, encontrado esta vez en el propio trabajo del Bloque 1.

---

## 5. Suites

Purgando `__pycache__` antes y después. **No se usa `PYTHONDONTWRITEBYTECODE=1`**: rompe
`deploy/tests/test_release_checksum.py::test_import_real_de_python_no_altera_checksum`, cuya
premisa es que el import genere bytecode (incidencia registrada en el Bloque 0).

| Suite | Bloque 0 | Bloque 1 |
|---|---|---|
| `data-engine/app/tests/` | 2443 passed, 2 skipped | **2339 passed, 2 skipped** |
| Combinada (`pytest -q`) | 3198 passed, 5 skipped | **3094 passed, 5 skipped** |

**El conteo baja 104 y la aritmética es exacta.** No se ha saltado, marcado como `xfail` ni
borrado ningún test para pasar:

| Concepto | Δ |
|---|--:|
| `_ALL_CONSULTATIONS` pierde un protocolo (`PROTOCOL_REALIGNMENT`, catálogo cerrado): el barrido exhaustivo pasa de 555 a 420 casos | −135 |
| `test_configuracion_de_consulta_invalida_falla_ruidosamente` pierde el caso `allow_realignment_fallback` (el campo ya no existe) | −1 |
| Tests nuevos en `test_relation_v2_b7_external.py` (`solo_exact_puede_reportar_ok`, `incertidumbre_con_evidencia_inventada`) | +2 |
| Fichero nuevo `test_relation_v2e_block1_defects.py` | +30 |
| **Total** | **−104** |

El barrido exhaustivo sigue siendo exhaustivo: cubre el producto completo de estados ×
recomendaciones × consultas posibles, y su test de cobertura (`test_barrido_exhaustivo_cubre_todas_las_combinaciones`)
se actualizó al nuevo cardinal. Menos casos porque hay menos combinaciones **posibles**, no
porque se hayan dejado de comprobar.

Los 5 skips son los mismos de B0 (Playwright, spaCy, Stanza, NVIDIA live, Ollama live): no se
ha añadido ninguno.

---

## 6. Qué queda abierto

1. **`pair_F1` = 0.8113 con 11 FN** — intacto por instrucción. Bloque 2.
2. **Precisión de la negación (0.4444)** — medida y visible, pero **sigue siendo mala**. La
   métrica no la arregla; sólo impide que pase desapercibida. Promocionar el camino de rechazo
   sigue prohibido hasta que exista held-out.
3. **`negation_precision` es informativa, no gobierna el dictamen.** Convertirla en gate de
   calidad es una decisión pendiente del operador o del bloque de calidad correspondiente.
4. **`n=54` con `dev == test`** — el rango honesto de predicado sigue siendo [0.42, 0.81].
   Ningún trabajo de este bloque lo mejora ni lo empeora.
5. **`max_time_per_candidate_ms` declarado pero no aplicado** (nota del arnés detectada en B0).
   No se ha tocado: es un control de recursos inefectivo y sigue vigente.
6. **`veto_on_temporal_not_in_force` no dispara** (§8.6) — no re-medido en este bloque.
7. **Proveedores reales y spaCy/Stanza sin medir** — sin cambios; requieren doble llave y
   autorización explícita del operador.
8. **`consultation_from_evaluation` con `document`** — hallazgo lateral de este bloque: la rama
   que reverifica la evidencia contra el documento **nunca se ejecuta en producción**, porque
   `consensus_adapter` y `ensemble` la llaman siempre con `document=None`. No es un agujero
   (sin documento nunca declara `ACCEPTED`, que es lo conservador), pero es otra rama de
   seguridad sin llamador real. **No se ha tocado**: cae fuera del alcance de los seis defectos
   asignados. Se reporta para que alguien decida.
9. **`.github/workflows/` sin tocar** (bloqueado por política). Nada de este bloque lo
   requiere: los comandos usados son los mismos que ejecuta CI.
