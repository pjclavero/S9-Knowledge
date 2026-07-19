# Informe de validación — Bloque 6: Ensemble calibrado

**Fecha:** 2026-07-20
**Rama:** `feat/relation-calibrated-ensemble-v1`
**Módulo:** `relations/ensemble.py` — `ENSEMBLE_VERSION = "relation-ensemble-1.0.0"`,
`ENSEMBLE_SCHEMA = "relation-ensemble/v1"`
**Combinador delegado:** `relations.consensus_adapter` (`relation-consensus-1.0.0`)
**Estado:** IMPLEMENTING (sin cableado en `run_pipeline`, sin proveedores reales)

## 1. Objetivo

Calibrar la zona gris de la decisión sobre relaciones candidatas con **umbrales y
pesos versionados**, y **explicar** cada decisión enumerando qué aportó cada fuente
—incluidas las que no estaban disponibles—. Todo ello **sin autoaprobar nada** y sin
duplicar la taxonomía de estados ni el combinador de consenso existente.

## 2. Encuadre: capa de calibración, NO un segundo combinador

Este es el punto de diseño más importante del bloque y condiciona todo lo demás.

`consensus_adapter.compute_relation_consensus` ya combina las **4 vías** del
pipeline de relaciones (heurísticas R2, sintaxis R3, LLM local R5, IA externa R6) y
es el **combinador canónico**. El Bloque 6 **no lo reescribe, no lo depreca y no lo
duplica**: el ensemble se construye **encima** de él.

Reparto de responsabilidades:

| Responsabilidad | Quién decide |
|---|---|
| Invalidaciones duras (contrato inválido, mezcla de workspaces, proveedor presente inválido, evidencia ausente) | `consensus_adapter` (**delegado**) |
| Combinación base de las 4 vías | `consensus_adapter` (**delegado**) |
| Calibración de la zona gris (umbrales/pesos versionados) | `ensemble` |
| Incorporación de las fuentes deterministas B3/B4/B5 | `ensemble` |
| Explicación de contribuciones y conflictos tipificados | `ensemble` |

Si el consenso delegado devuelve `INVALID_RESPONSES`, el ensemble **respeta el
veredicto tal cual** (estado `INVALID_RESPONSES`, recomendación `human`) y no
calibra nada; el motivo lo declara explícitamente: «Invalidacion DELEGADA en
consensus_adapter (no recalculada)». Ninguna de esas invalidaciones se
reimplementa aquí.

## 3. Hallazgo clave: los Bloques 3/4/5 no estaban cableados

Al construir el ensemble se detectó el hallazgo con más valor real del bloque:

> Los módulos de los Bloques 3, 4 y 5 —`vocabulary.py` (canonicalización de
> predicados), `temporality.py` (clasificación temporal) y `epistemic.py` (estado
> epistémico)— **no estaban cableados en producción**. Existían, estaban probados y
> versionados, pero **solo sus tests los ejercitaban**: ninguna decisión del
> pipeline de relaciones los consumía como fuente.

El ensemble los incorpora **por fin** como fuentes deterministas de primera clase,
con peso propio, versión propia trazada y capacidad de generar conflictos
tipificados. Ese es el valor sustantivo del Bloque 6: no un nuevo algoritmo de
consenso, sino **poner a trabajar el trabajo ya hecho**.

## 4. Diseño

### 4.1 `SourceContribution` — ninguna contribución se pierde

Dataclass **frozen** que representa la aportación de UNA fuente:

```text
source · availability · polarity · weight · score · version · reason_codes
```

Se emite **SIEMPRE una entrada por cada una de las 7 fuentes configuradas**,
incluso cuando la fuente está ausente o es inevaluable. La ausencia se representa
explícitamente, no por omisión:

- `availability` ∈ `PRESENT · NOT_EXECUTED · FAILED_CLOSED · SKIPPED · INVALID`.
  Los tres estados de ausencia de proveedor se **reutilizan** de
  `relations.pipeline` (`PROVIDER_NOT_EXECUTED` / `PROVIDER_FAILED_CLOSED` /
  `PROVIDER_SKIPPED`); no se inventa una taxonomía paralela.
- `polarity` ∈ `positive · negative · abstain · none`. El invariante lo impone el
  `__post_init__`: **una fuente no presente solo admite `polarity = "none"`**.
- `decisive` es `True` únicamente si la fuente está `PRESENT` y su polaridad es
  `positive` o `negative`; solo las decisivas entran en el score ponderado.

Consecuencia directa: **ausencia ≠ rechazo**. Una fuente ausente aporta `score = 0`
y no participa en el denominador de la media ponderada; no vota en contra ni resta.

### 4.2 `EnsembleConfig` — pesos y umbrales versionados con `config_hash`

Dataclass **frozen** con los pesos por fuente y los umbrales de calibración:

| Parámetro | Valor por defecto | Significado |
|---|---|---|
| `strong_threshold` | 0.75 | Score mínimo para aspirar a STRONG |
| `partial_threshold` | 0.45 | Score mínimo para PARTIAL |
| `conflict_margin` | 0.15 | Zona muerta alrededor de 0 → HUMAN_REQUIRED |
| `min_decisive_sources` | 2 | Fuentes decisivas mínimas para STRONG |
| `profile` | `default-1.0.0` | Nombre del perfil |
| `weights_version` | `relation-ensemble-weights-1.0.0` | Versión de los pesos |
| `thresholds_version` | `relation-ensemble-thresholds-1.0.0` | Versión de los umbrales |

`weights_version` y `thresholds_version` son **independientes** de
`ENSEMBLE_VERSION`: recalibrar no cambia el código ni los contratos, solo esta capa.
Los pesos se normalizan a `MappingProxyType` (inmutable) y se validan: fuente
conocida, numérico, no negativo. Los umbrales exigen
`0 < partial_threshold <= strong_threshold <= 1`.

`config_hash` es un **sha256 truncado a 16 hex** sobre la serialización canónica de
`to_dict()` (misma función `_canonical` que el pipeline). Es **determinista**: la
misma configuración produce siempre el mismo hash, y ese hash viaja en cada
decisión, de modo que cualquier resultado archivado es **reproducible**.

**Reproducibilidad de la configuración:**

- `PROFILES` es un `MappingProxyType` **inmutable** de perfiles nombrados;
  `DEFAULT_PROFILE = PROFILES["default-1.0.0"]`.
- `config_from_dict(data)` aplica **lista blanca** de claves (las de
  `DEFAULT_PROFILE.to_dict()`) y **rechaza explícitamente** las claves de escritura
  de `relations.pipeline._FORBIDDEN_CONFIG_KEYS` (`write`, `apply`, `persist`,
  `commit`, `auto_approve`…), tanto en el nivel raíz como dentro de `weights`. El
  ensemble no puede ser configurado para escribir: no hay ruta que lo permita.

### 4.3 `EnsembleDecision` — tres barreras contra la autoaprobación

Dataclass **frozen** con el resultado calibrado de UN candidato. Conserva la
trazabilidad de la delegación (`consensus_state`, `consensus_recommendation`,
`consensus_reason_codes`) junto al resultado calibrado (`state`, `recommendation`,
`score`, `contributions`, `conflicts`, `reason`, `config_hash`, `profile`,
`ensemble_version`, `schema`).

Las **tres barreras** se validan en el `__post_init__`, así que una decisión
insegura **no puede construirse**:

1. **Modo sombra obligatorio** — `shadow` debe ser `True`. Una decisión con efectos
   es inconstruible.
2. **Estado canónico** — `state` debe pertenecer a `CONSENSUS_STATES`, importado de
   `external_ai.models` (STRONG_CONSENSUS · PARTIAL_CONSENSUS · MODEL_CONFLICT ·
   INVALID_RESPONSES · HUMAN_REQUIRED). **No se duplica la taxonomía de estados.**
3. **Recomendación acotada y no prohibida** — `recommendation` debe estar en
   `consensus_adapter.RELATION_RECOMMENDATIONS` (`propose` · `reject` · `human`) y
   además no puede pertenecer a `_FORBIDDEN_RECOMMENDATIONS` (`approve`,
   `auto_approve`, `write`, `apply`…). **El techo es `propose`.**

`to_dict()` / `to_json()` serializan de forma determinista (`sort_keys=True`).

### 4.4 `combine()` y su flujo

```python
combine(candidate, *, signals=None, syntax=None, local=None, external=None,
        config=DEFAULT_PROFILE,
        local_availability=None, external_availability=None) -> EnsembleDecision
```

Recibe evaluaciones **ya calculadas** (o `None`). **Nunca** invoca Ollama ni NVIDIA
ni abre red, disco o Neo4j. Flujo:

1. **Delegación** en `compute_relation_consensus(...)`. Si el estado es
   `INVALID_RESPONSES`, se devuelve tal cual con las 7 contribuciones marcadas
   `INVALID`/`SKIPPED` (`candidate_not_evaluable`) y recomendación `human`.
2. **Derivación de las fuentes deterministas B3/B4/B5** sobre una **copia validada**
   del candidato (`_validated_copy` nunca muta el original).
3. **Ponderación** de las contribuciones decisivas: media ponderada
   `sum(w·score)/sum(w)` redondeada a 6 decimales, y aplicación de los umbrales de
   `config` en `_derive_state`.

Determinismo estructural: el orden de las contribuciones es el alfabético canónico
de `ENSEMBLE_SOURCES`; las señales se leen a través de `_signal_map`, que es
**independiente del orden** de la lista; los conflictos se deduplican y ordenan
canónicamente; no se itera sobre sets sin ordenar; no hay `time` ni `random`.

## 5. Las 7 fuentes y qué aporta cada una

| Fuente | Bloque / origen | Peso | Qué aporta | Positivo | Negativo | Abstiene |
|---|---|---|---|---|---|---|
| `heuristics` | R2 · `signals.py` | 0.6 | Soporte estructural de las señales (`same_clause`, `same_sentence`, `svo_pattern`) | Hay soporte estructural | — | Señales presentes sin soporte estructural |
| `syntax` | R3 · `syntax.py` | 0.8 | Presencia de una tripleta S-V-O completa en alguna oración | Hay patrón SVO | — | Sin patrón SVO |
| `vocabulary` | **B3** · `vocabulary.py` | 1.0 | Canonicalización del predicado + compatibilidad ontológica de tipos | Canónico y tipos compatibles (1.0) o canónico sin tipos (0.5) | Tipos **incompatibles** | Sin canónico o `requires_human` |
| `temporality` | **B4** · `temporality.py` | 0.7 | Clase temporal del texto contrastada con `temporal_status_of(temporal_scope)` | Coinciden clase declarada y del texto | Clases distintas y ambas informativas | Sin alcance declarado, o texto `ATEMPORAL` |
| `epistemic` | **B5** · `epistemic.py` | 1.0 | Estado epistémico del texto contrastado con `epistemic_status` del candidato | Coinciden | `is_epistemically_safe` = False (cue no-asertivo con `ASSERTED`) | Divergencia **segura** (el candidato es más conservador que el texto) |
| `local_llm` | R5 · proveedor | 1.2 | Recomendación del LLM local, mapeada con `_LOCAL_POLARITY` | Polaridad positiva | Polaridad negativa | `uncertain`/`human` o recomendación desconocida |
| `external_ai` | R6 · proveedor | 1.4 | Recomendación en sombra de la IA externa, mapeada con `_EXTERNAL_POLARITY` | Polaridad positiva | Polaridad negativa | Proveedor se abstiene |

Cada contribución declara la **versión del módulo de origen** (`SIGNALS_VERSION`,
`SYNTAX_VERSION`, `VOCAB_VERSION`, `TEMPORALITY_VERSION`, `EPISTEMIC_VERSION`,
`CONSENSUS_VERSION`), de modo que una decisión archivada dice exactamente con qué
versión de cada fuente se tomó.

Las tres fuentes **B3/B4/B5** son la incorporación nueva del bloque; las otras
cuatro ya estaban cableadas vía `consensus_adapter`.

## 6. Conflictos tipificados

Los conflictos son objetos `{type, detail, sources}`, deduplicados y ordenados
canónicamente. Los cinco tipos admitidos (`CONFLICT_TYPES`):

| Tipo | Se registra cuando… |
|---|---|
| `provider_polarity` | LLM local y IA externa votan en **sentidos opuestos** |
| `negation` | `signal.negation`, `syntax.negated`, `local.negated` o `external.verdict.negated` **discrepan** de `candidate.negated` |
| `epistemic` | Hay cue epistémico no-asertivo y el candidato declara `ASSERTED` (guardia `is_epistemically_safe`) |
| `temporal` | La clase temporal declarada en `temporal_scope` contradice la clase del texto |
| `predicate_mismatch` | El predicado del veredicto externo **no empareja** (alias-aware, `predicates_match`) con el del candidato |

Además, los `reason_codes` del consenso delegado se **traducen** a conflicto
tipificado en lugar de perderse: `provider_polarity_conflict` →
`provider_polarity`, `negation_contradiction` → `negation`,
`epistemic_contradiction` → `epistemic`.

**Cualquier conflicto tipificado presente ⇒ `MODEL_CONFLICT` / `human`.** No se
promedia por encima de una contradicción.

## 7. Reglas de calibración (`_derive_state`)

Se aplican **en orden**:

1. **Conflictos ⇒ `MODEL_CONFLICT` / `human`.** El detalle enumera los tipos.
2. **Zona muerta:** `|score| <= conflict_margin` ⇒ `HUMAN_REQUIRED` / `human`. Un
   empate no se resuelve inventando una decisión: lo resuelve una persona.
3. **STRONG (positivo)** requiere **todo** lo siguiente:
   `score >= strong_threshold` · sin conflictos · `n_decisive >= min_decisive_sources` ·
   evidencia real (`has_evidence`) · **al menos un proveedor PRESENTE** ·
   consenso delegado en `STRONG_CONSENSUS` o `PARTIAL_CONSENSUS`. Recomendación:
   `propose`.
4. **PARTIAL:** `score >= partial_threshold` ⇒ `PARTIAL_CONSENSUS` / `propose`.
5. **Polaridad negativa:** solo si el **consenso delegado ya recomendó `reject`** y
   `-score >= partial_threshold`. Sin esa corroboración ⇒ `HUMAN_REQUIRED`.
6. **Cualquier otro caso ⇒ `HUMAN_REQUIRED` / `human`.**

### Decisiones de diseño del implementador

- **STRONG exige ≥1 proveedor PRESENTE.** Las fuentes deterministas (B3/B4/B5) y las
  heurísticas **corroboran, no sustituyen**. Un candidato apoyado solo por reglas
  deterministas nunca alcanza STRONG por sí solo: como máximo llega a PARTIAL. Es
  deliberado — las reglas deterministas comprueban coherencia interna del candidato,
  no la verdad del enunciado.
- **Techo de calibración.** El ensemble **nunca sube a STRONG** desde
  `HUMAN_REQUIRED`, `MODEL_CONFLICT` o `INVALID_RESPONSES` del consenso delegado
  (regla 3: el estado delegado debe ser STRONG o PARTIAL). Sí calibra hacia arriba
  dentro de la zona gris (`PARTIAL → STRONG`) y hacia abajo (`HUMAN → PARTIAL`)
  cuando las fuentes deterministas y los proveedores lo sostienen.
- **`reject` es siempre delegado.** El ensemble **nunca inventa un rechazo**: solo
  preserva la polaridad negativa que el consenso delegado ya había recomendado. Un
  score negativo sin corroboración va a revisión humana, no a rechazo automático.
- **`conflict_margin` como zona muerta.** El margen alrededor de 0 no se resuelve por
  redondeo hacia el lado más cercano; se resuelve escalando a `HUMAN_REQUIRED`.

## 8. Garantías de seguridad

- **Sin autoaprobación.** Tres barreras independientes en `EnsembleDecision`
  (shadow obligatorio, estado canónico, recomendación válida y no prohibida). El
  techo es `propose`; `approve`/`auto_approve`/`write`/`apply` son inconstruibles.
- **Ausencia ≠ rechazo.** Un proveedor ausente produce `availability` ∈
  `NOT_EXECUTED · FAILED_CLOSED · SKIPPED`, `polarity = "none"` y `score = 0`; no
  cuenta como voto ni resta. Distinguir «no se ejecutó» de «falló cerrado» de «se
  omitió» es parte del contrato de la contribución.
- **Sin duplicación de taxonomías.** Estados de `external_ai.models.CONSENSUS_STATES`;
  recomendaciones de `consensus_adapter.RELATION_RECOMMENDATIONS`; disponibilidades
  de proveedor de `relations.pipeline`. El ensemble no define ninguna taxonomía
  propia salvo las suyas específicas (polaridades y tipos de conflicto).
- **Determinismo total.** Sin red, disco, escritura, LLM, `time`, `random` ni
  iteración sobre sets. Orden canónico de fuentes y conflictos; lectura de señales
  independiente del orden; `config_hash` reproducible; serialización con claves
  ordenadas.
- **Sin mutación.** `_validated_copy` trabaja sobre una copia; los pesos y perfiles
  son `MappingProxyType`; todas las dataclasses son `frozen`.
- **Sin escritura configurable.** `config_from_dict` rechaza las claves de escritura
  del pipeline con `EnsembleConfigError`.
- **Explicabilidad completa.** Siempre 7 contribuciones, con `reason_codes`, la
  versión de cada fuente, el estado y los `reason_codes` del consenso delegado, el
  `config_hash`, el `profile` y un `reason` en texto.

## 9. Qué queda FUERA de este bloque

- **No se cablea en `run_pipeline`.** El ensemble **no** es un paso obligatorio del
  pipeline en el Bloque 6. Su integración se hace en un bloque posterior, **con su
  propio gate** y su propia validación. Hoy es una capa disponible, no un camino
  crítico.
- **Sin proveedores reales en CI.** El ensemble no ejecuta Ollama ni NVIDIA: recibe
  evaluaciones ya calculadas o `None`. En CI no hay proveedores reales, así que las
  rutas con proveedor se ejercitan con evaluaciones sintéticas y las rutas sin
  proveedor con `None` + `availability` explícita.
- **Sin recalibración empírica de pesos.** Los pesos y umbrales de
  `default-1.0.0` son un punto de partida razonado, no un ajuste medido sobre el
  benchmark. La recalibración con datos corresponde al Bloque 7 (reejecución del
  benchmark) y no requiere tocar código: solo un perfil nuevo con su
  `weights_version` / `thresholds_version` y su `config_hash`.
- **Sin escritura en Neo4j ni cambio de contrato.** `SCHEMA_VERSION` y
  `relations/contracts.py` no se tocan.

## 10. Estado de producción

Intacta. No se tocó VM105, Neo4j, `auth.db`, `jobs.db`, timers ni servicios.
`S9K_ALLOW_REAL_INGEST = off`. `release/rc6-candidate = 15ae1d4` (**inmutable**).
