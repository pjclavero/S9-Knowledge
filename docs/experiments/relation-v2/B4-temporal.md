# Bloque 4 — Temporalidad y **vigencia** como módulo robusto

**Programa:** motor de relaciones v2 · **Rama:** `feat/relation-engine-v2-hybrid` ·
**Antecedente:** `B3-direction.md` (HEAD B3 `9c0ea89`).

Bloque 4 consolida la **resolución temporal / de vigencia** en un módulo puro y
determinista, `relations/temporal_v2.py`, que el camino **v2** consume para poblar
`temporal_scope`. El default **v1** queda **intacto y metric-neutral**
(sigue usando `pipeline._temporal_scope`, que lee `signal_temporality`).

Trabajo offline, sin red, sin escritura, determinista. **No** se bajan `THRESHOLDS`,
**no** se toca el GT/corpus, **no** se relaja ningún assert. Cero calcos del corpus:
todo el léxico/morfología es **general del español** y los tests usan entidades
**inventadas**.

---

## 1. Por qué la temporalidad estaba baja (diagnóstico honesto)

El arnés mide `temporal_correct = temporality.temporal_status_of(pred.temporal_scope)
== gt.temporal_status`. El clasificador v1 (`relations/temporality.py`) marca
`has_temporal_signal = False` para el **presente simple** (cópula/estado sin fecha),
así que el pipeline lo materializa como `temporal_scope = None`, y
`temporal_status_of(None) = None`, que **nunca** casa con `PRESENT`.

Con el desglose real de los 43 TP (v2 pre-B4), los aciertos (20) venían **todos** del
subgrupo fuerte (PAST/FUTURE/ENDED); las **27 relaciones PRESENT** del GT puntuaban
mal por construcción. Además, la morfología de pasado de v1 (`\w+ó`) **no** capturaba
el pretérito **plural** (`participaron`, `sirvieron`) ni el **imperfecto**
(`lideraba`), dejando esos pasados como `None`.

Confusión v2 pre-B4 (gt → pred), 43 TP:

```
PRESENT -> None : 15     PAST -> PAST : 13     FUTURE -> FUTURE : 5
PAST    -> None : 3      ENDED-> ENDED: 2      PRESENT-> PAST : 2
ENDED   -> None : 1      ONGOING->None: 1      PRESENT-> ENDED: 1
```

Las dos palancas legítimas: (a) **emitir** la clase PRESENT para la aserción
relacional en presente, y (b) **ampliar** la morfología de pasado. Ninguna es un
calco: son gramática general.

---

## 2. Arquitectura del módulo

`relations/temporal_v2.py` expone una función pura:

```
resolve_temporal(text) -> TemporalResolution
resolve_for_pair(seg_text, pair) -> TemporalResolution      # ventana = frase del par
temporal_scope_for_pair(seg_text, pair) -> str | None       # scope para el pipeline v2
segment_transitions(text) -> list[TemporalPhase]            # fases sin sobrescribir
```

`TemporalResolution(state, temporal_status, markers, dates, interval, signals,
rationale, version)`:

- **`state`** — estado de **vigencia** rico (`TemporalState`): `ACTIVE`, `ENDED`,
  `PLANNED`, `HYPOTHETICAL`, `RECURRING`, `UNKNOWN`.
- **`temporal_status`** — clase del **contrato** (una de
  `temporality.TEMPORAL_CLASSES`: PAST/PRESENT/FUTURE/ONGOING/ENDED/ATEMPORAL). Es la
  que **dirige la métrica**: se serializa como **prefijo** de `to_scope_string()`, de
  modo que `temporality.temporal_status_of` la lee **sin reclasificar**.
- **`signals`** (`TemporalSignals`) — `valid_from` / `valid_to` (de `desde` / `hasta`
  + año), `event_time` (año del evento), `temporal_expression`, `relative_to`
  (anclas: `antes de`, `tres años después`, `sesión anterior`…), `is_potential`,
  `is_recurring`, `is_pending`. `source_time` / `asserted_at` quedan `None` (no hay
  tiempo de fuente/asersión disponible offline: **no se inventa**).

Mapeo estado → clase del contrato (`STATE_TO_STATUS`), coherente con el arnés:

| estado | clase | nota |
|---|---|---|
| `ENDED` | `ENDED` / `PAST` | cese explícito → ENDED; evento cerrado (pretérito/fecha) → PAST |
| `PLANNED` | `FUTURE` | futuro / “todavía no” |
| `HYPOTHETICAL` | `FUTURE` | condicional (`podría`) = no actual |
| `RECURRING` | `ONGOING` | habitual/genérico |
| `ACTIVE` | `PRESENT` / `ONGOING` | presente simple → PRESENT; continuidad (`desde`,`aún`,`sigue`) → ONGOING |
| `UNKNOWN` | `ATEMPORAL` | sin alcance resoluble |

### Prioridad de decisión (documentada y estable)

```
ENDED(cese|hasta+fecha) > todavía-no(PLANNED) > FUTURO(léxico|-rá) >
ONGOING(continuidad) > PASADO(pretérito sg/pl · imperfecto · léxico · fecha) >
HYPOTHETICAL(potencial→FUTURE) > RECURRING(cuantificador universal→ONGOING) >
PRESENTE(cópula o default de aserción)
```

El orden de las **clases fuertes** replica el de v1 (ENDED>FUTURE>ONGOING>PAST) para
**no regresar** los aciertos ya existentes; lo nuevo se **inserta debajo**.

### Léxico/morfología general (no calcos)

- Cese: `ya no`, `dejó de`, `terminó`, `abandonó`, `antiguo`, `ex`, `otrora`, …
- Futuro: `será`, `planea`, `promete`, `-rá/-rán`; pendiente: `todavía no`, `aún no`.
- Continuidad: `desde`, `aún`, `sigue`, `todavía`, `actualmente`, `hoy en día`.
- Pasado: `-ó` (sg), **`-aron/-ieron/-eron` (pl)**, **`-aba/-aban` (imperfecto)**,
  `fue/era`, `tras`, `hace años`, `antaño`, fecha suelta.
- Recurrente: `todo/toda/cada/siempre/suele/anualmente` + presente.
- Presente: cópula `es/son/está`, `pertenece`, `reside`, `preside`, `custodia`…; y
  **default**: una aserción relacional **sin marca** es **presente** (regla general),
  no `ATEMPORAL` — ése es el cambio central respecto a v1.

---

## 3. Transiciones sin sobrescribir historia

`segment_transitions(text)` descompone un texto con transición
(`aliado → ya no → enemigo`; `capitán → antigua capitana`) en una **secuencia
ordenada** de `TemporalPhase(order, text, resolution)`, cada fase con su **propia**
resolución inmutable. **No** colapsa ni machaca: `ALLY_OF/ACTIVE → ALLY_OF/ENDED →
ENEMY_OF/ACTIVE` se representa como estados **separados**. Además, resolver una
relación **nunca** muta otra (funciones puras, dataclasses `frozen`), y la
**contradicción temporal aparente** (dos fuentes en momentos distintos sobre el mismo
par) se resuelve por fuente: cada aserción conserva su clase (una `PAST`, otra
`ENDED`) sin contradecirse. El arnés sigue emparejando **una** predicción por par y
segmento; el escalonado es de **representabilidad**, cubierto por tests.

---

## 4. Integración en el pipeline

`pipeline._build_candidate`: en el camino `predicate_selector == "v2"`,
`temporal_scope = temporal_v2.temporal_scope_for_pair(seg_text, pair)` (ventana
acotada a la frase del par vía `signals._sentence_bounds`, igual que `direction.py`).
El camino `v1` conserva `temporal_scope = _temporal_scope(sigmap)` **sin cambios**.
El contrato (`temporal_scope: Optional[Any]`, 20 campos) no se toca.

---

## 5. Medición A/B honesta (`--mode baseline1`)

Sobre los **43 TP** (idénticos en ambos: pares/F1/evidencia intactos):

| métrica | v1 (`--predicate-selector v1`) | v2 + B4 (`v2`) | gate |
|---|---|---|---|
| **temporal_correct** | **0.4419** (19/43) | **0.8837** (38/43) | **≥ 0.60 ✅** |
| temporal (subgrupo fuerte) | 0.76 (19/25) | 0.96 (24/25) | — |
| predicate_correct | 0.2093 | **0.8140** (35/43) | ≥ 0.814 ✅ |
| strict_predicate F1 | 0.1698 | **0.6604** | ✅ |
| direction_correct | 0.6279 | **0.9302** (40/43) | ≥ 0.930 ✅ |
| direction_orientation_ok | 0.7674 | **0.9535** | ✅ |
| evidence_correct | 0.9070 | **0.9302** | ✅ |
| global F1 / P / R | 0.8113 / 0.8269 / 0.7963 | **idénticos** | ✅ |

`temporal_v2` **alcanza el gate con margen** (0.8837 ≥ 0.60) **sin** degradar
predicado, dirección, evidencia ni F1. `v1` queda **bit-idéntico** (temporal 0.4419).
Determinismo del arnés: `deterministic=True`, `hashes_equal=True`.

### Los 5 fallos restantes (honestidad > cifra)

Se dejan **sin forzar** porque corregirlos exigiría un calco del corpus o
desambiguación aspectual que no generaliza:

1. `sirvieron juntos` → `PAST`, GT `ENDED` (relación de co-servicio terminada sin cue
   explícito de cese).
2. mismo texto, otra relación → `PAST`, GT `PRESENT` (aspecto: evento pretérito con
   estado presente resultante).
3. `abandonó la Guardia y se unió al Pacto` → `ENDED`, GT `PRESENT`: el cue `abandonó`
   de la **otra** relación contamina la ventana (transición dentro de la frase).
4. `Su maestra … enseñó` → `PAST`, GT `PRESENT` (relación de tutela presente con
   evento pretérito en la ventana).
5. `Es posible que … aún viva … fundó` → `PAST`, GT `PRESENT` (pretérito `fundó` gana
   a `aún`).

Ninguno se “arregla” con un patrón calcado: se declaran como límite conocido.

---

## 6. Suites (verdes, deterministas)

- `tests/test_relation_v2_b4_temporal.py` — **29 passed** (casos obligatorios:
  presente, pasado sg/pl/imperfecto, futuro, fecha absoluta/relativa, intervalo,
  `desde`/`hasta`, vigente, terminada, antiguo cargo, planeada, `todavía no`,
  hipotética, recurrente, `ya no`, transición, contradicción aparente, referencia no
  resoluble, adaptador de par). Entidades **inventadas**, sin skip/xfail.
- `pytest tests/ -k relation` — **1017 passed, 538 deselected**.
- `tests/test_relation_calibration_final_quality_block9.py` — **48 passed**.

---

## 7. Ficheros

- **Nuevo** `data-engine/app/relations/temporal_v2.py` — módulo B4.
- **Nuevo** `data-engine/app/tests/test_relation_v2_b4_temporal.py` — 29 tests.
- **Editado** `data-engine/app/relations/pipeline.py` — el camino v2 consume
  `temporal_v2`; v1 intacto.
- **Nuevo** `docs/experiments/relation-v2/B4-temporal.md` — este documento.
