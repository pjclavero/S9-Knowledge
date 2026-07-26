# Defectos abiertos del motor V2 — verificación sobre `8fc7c8d`

**Commit auditado:** `8fc7c8d45b2a03be92b7935f9d9b9c2bd32390bb` (= `origin/main`).
**Fuente de la lista:** `docs/relation-engine-v2-results.md` §8, tabla *"Defectos ABIERTOS"*.
**Método:** localización del código exacto + reproducción con el arnés oficial
(`relations.benchmark.cli`, proveedores desactivados). Rutas relativas a
`data-engine/app/` salvo indicación.

## Resumen

| Id | Gravedad | Estado en `8fc7c8d` | Evidencia |
|---|:--:|:--:|---|
| B5-D4 | MEDIA | **CONFIRMADO** | `relations/syntax.py:1212-1222`, `1119-1137` |
| B5-D7 | INFO | **CONFIRMADO** | `relations/syntax.py:1126` |
| Negación 4/9 | MEDIA | **CONFIRMADO Y REMEDIDO** | `relations/abstention.py:426-431` |
| B7 envolvente `TIER_NORMALIZED` | BAJA | **CONFIRMADO** | `relations/external_ai_shadow.py:459` vs `relations/evidence_realignment.py:73` |
| B7 `validate_external_verdict` sin llamador | BAJA | **CONFIRMADO** | `relations/external_consult.py:356` |
| `pair_F1` no mejoró (11 FN) | — | **CONFIRMADO Y REMEDIDO** | 4 corridas propias: `f1=0.8113`, `fn=11` |

**Ninguno de los seis ha sido corregido tras el merge del V2.** Verificado además que
`git diff --name-only 5ad9f18 8fc7c8d -- data-engine/app/relations` está **vacío**: el módulo
`relations/` no ha recibido un solo cambio desde el merge del PR #105.

---

## 1. B5-D4 — Retención global de texto crudo en caché, sin TTL ni API pública de reset

**CONFIRMADO.**

- `relations/syntax.py:1212` — `_DEFAULT_ANALYZER: Optional[SyntaxAnalyzer] = None` es una
  **variable global de módulo**.
- `relations/syntax.py:1215-1222` — `get_default_analyzer()` la inicializa de forma perezosa a
  un `CachingSyntaxAnalyzer(HeuristicSyntaxAnalyzer(), maxsize=512)` y la **comparte para todo
  el proceso**.
- `relations/syntax.py:1119-1137` — `CachingSyntaxAnalyzer.analyze` guarda con clave
  `(text, language)`: **la clave ES el texto crudo del segmento**, y el valor
  (`SyntaxAnalysis`) también contiene `text`. Es decir, se retiene el texto **dos veces** por
  entrada.
- `relations/syntax.py:1158` — `_DEFAULT_CACHE_MAXSIZE = 512`.
- `relations/pipeline.py:679` — `safe_analyze(get_default_analyzer(), text)`: **toda** segmento
  procesada por el pipeline pasa por esa caché global.

Precisiones respecto al enunciado original:

- **No hay TTL.** Confirmado: no existe ninguna ocurrencia de `ttl`/`TTL` ni de expiración
  temporal en `relations/syntax.py`. El único desalojo es **LRU por tamaño** (`maxsize=512`,
  líneas 1133-1136); las 512 últimas entradas viven indefinidamente.
- **La "API pública de reset" es parcial, no inexistente.** `CachingSyntaxAnalyzer.cache_clear()`
  sí existe y es pública (`syntax.py:1139-1143`), y `get_default_analyzer` está en `__all__`,
  de modo que `syntax.get_default_analyzer().cache_clear()` funciona. Lo que **no existe** es
  una función de módulo (`reset_default_analyzer()` o equivalente) que limpie o descarte el
  singleton `_DEFAULT_ANALYZER`, ni figura ninguna en `__all__` (líneas 1260-1276). Nadie la
  llama en producción: `grep cache_clear` fuera de `syntax.py` no devuelve llamadores.
- **Cruce de fronteras.** La clave no incluye `workspace` ni `source_id`. En un proceso longevo
  que sirva varios workspaces, el texto crudo del workspace A permanece en memoria mientras se
  procesa el B. El *resultado* no se contamina —la clave es el texto exacto y el analizador
  heurístico es puro y determinista, así que un acierto entre workspaces devolvería el análisis
  correcto—, pero la **retención** sí cruza. Roza el invariante 13 del informe rector
  (`docs/S9_KNOWLEDGE_INFORME_MEJORA_MOTOR_CONSOLIDADO_V2.md:322`, *"La caché nunca cruza
  workspaces"*).

Condición del Supervisor: *"Cerrar B5-D4 y B5-D7 antes de que este código salga de sombra."*
**Sigue sin cerrarse.**

---

## 2. B5-D7 — El objeto cacheado se comparte por identidad

**CONFIRMADO.**

- `relations/syntax.py:1121-1126` — en el acierto, `analyze` devuelve **el mismo objeto**
  (`return cached`), sin copia ni `replace`.
- `SyntaxAnalysis` es un `@dataclass(frozen=True)` (`relations/syntax.py`, declaración de la
  clase). El congelado impide la mutación normal, pero **no** `object.__setattr__(obj, ...)`,
  que es exactamente el vector descrito: quien lo hiciera corrompería el análisis para **todos**
  los llamadores posteriores que acierten en la misma clave.

Gravedad INFO, coherente con lo documentado: requiere que alguien salte deliberadamente el
congelado. No hay ningún caso así en el código actual.

---

## 3. Negación — precisión real de la señal que dispara los rechazos

**CONFIRMADO, y remedido con datos propios.**

Código:

- `relations/pipeline.py:457` — `negated=bool(sigmap.get("negation"))`: el campo del contrato
  se rellena directamente con la señal.
- `relations/signals.py:426-432` — `signal_negation` es un detector de **pistas léxicas**
  (`_cue_signal(ctx, "negation", _NEGATION_CUES, ...)`), sin análisis de alcance.
- `relations/abstention.py:426-431` — `if bool(_get(candidate, "negated")):` produce un motivo
  con severidad `REJECTING`, porque `relations/abstention.py:198` fija
  `reject_on_negation: bool = True` **por defecto**.
- `relations/abstention.py:462-466` — un motivo `REJECTING` no bloqueado se convierte en
  `VERDICT_REJECT`.

Medición propia (`--mode baseline1`, proveedores desactivados, corpus B1 intacto):

| | v1 | v2 |
|---|--:|--:|
| Candidatos con `negated=True` emitidos (sobre los 52) | 10 | 10 |
| De ellos, correctos contra el GT | 4 | 4 |
| **Precisión sobre los 52 candidatos** | **4/10 = 0.400** | **4/10 = 0.400** |
| **Precisión sobre los 43 emparejados** (la cifra del informe) | 4/8 = 0.500 | **4/9 = 0.444** |
| `negation_correct` global | 39/43 = 0.9070 | 38/43 = 0.8837 |
| Subgrupo `negated_relations` (recall) | 4/4 = 1.000 | 4/4 = 1.000 |

El **4/9** de §8.5 se reproduce exactamente: 43 emparejados − 38 correctos = 5 errores; los 4
GT-negados emparejados se aciertan todos (recall 4/4), luego los 5 errores son **falsos
positivos** ⇒ 4 TP / 9 predichos.

Y se confirma el mecanismo descrito ("los falsos positivos los absorbe la guarda de
`MODEL_CONFLICT` — suerte, no garantía"): de los 10 candidatos marcados `negated=True` en v2,
sólo 5 llegan a `recommendation="reject"`, y de esos 5 **4 son correctos y 1 es falso**
(`src-08 pacto-escarlata RELATED_TO guardia-hierro`, un par que ni siquiera existe en el GT).
Los otros 5 falsos positivos quedan en `human` por `MODEL_CONFLICT`/`HUMAN_REQUIRED`. Que
**ningún** rechazo caiga sobre una relación que el GT acepta es lo que sostiene los "0 falsos
ACCEPT sin un solo rechazo falso" — pero lo sostiene una guarda que no fue diseñada para esto.

**Conclusión operativa sin cambios:** *no promocionar el camino de rechazo más allá de modo
sombra.*

---

## 4. B7 — La envolvente de aceptación no es idéntica: `TIER_NORMALIZED` es inalcanzable en la ruta real

**CONFIRMADO.** Y está documentado en el propio código.

- `relations/evidence_realignment.py:73` — `REALIGN_OK_TIERS = frozenset({TIER_EXACT, TIER_NORMALIZED})`:
  el realineador **declara** dos peldaños aceptables.
- `relations/evidence_realignment.py:267` — el peldaño `TIER_NORMALIZED` sólo se emite cuando la
  cita **no** es subcadena literal y sólo casa tras normalización tipográfica.
- **Camino de API** (`relations/external_consult.py:323-334`): acepta `TIER_EXACT` como
  `PROTOCOL_LITERAL` y `TIER_NORMALIZED` como `PROTOCOL_REALIGNMENT`, sujeto a
  `allow_realignment_fallback` (que por defecto es `True`, línea 160). Es decir, **aquí
  `TIER_NORMALIZED` sí es alcanzable**.
- **Camino real** (`relations/external_ai_shadow.py:451-494`): la línea **459**
  `elif ev not in seg: errors.append("evidencia_inexistente: ...")` corta **antes** de invocar
  el realineador. Cuando en la línea 484 se llama a `realign_evidence_unique`, ya se ha
  garantizado que la cita es subcadena literal, luego el resolutor **sólo puede devolver
  `TIER_EXACT` o un fallo por ambigüedad**. El propio comentario de las líneas 491-494 lo dice:
  *"en la rama legacy solo sobrevive `exact`, luego esto es una reafirmación estructural, no un
  cambio de ancla"*.

Es **fail-closed** (el camino real es más estricto, nunca más laxo), tal y como estaba
documentado. El riesgo sigue siendo el mismo: **dos envolventes de aceptación distintas** para
la misma garantía, y un peldaño con tests que nadie ejerce en producción. Es deriva futura,
no un agujero hoy.

---

## 5. B7 — `validate_external_verdict` sin ningún llamador de producción

**CONFIRMADO.**

- Definición: `relations/external_consult.py:356`. Exportada en `__all__`
  (`relations/external_consult.py:638`).
- `grep -rn 'validate_external_verdict' --include='*.py' .` sobre todo el repo devuelve **28
  referencias en sólo 2 ficheros**: 4 en el propio módulo (docstrings de las líneas 31 y 50, la
  definición y el `__all__`) y 24 en `data-engine/app/tests/test_relation_v2_b7_external.py`,
  de las cuales **23 son llamadas reales** (`consult.validate_external_verdict(...)`) y 1 es una
  mención en docstring. **Cero llamadores de producción.**
- El propio test lo dice por escrito: `tests/test_relation_v2_b7_external.py:1197` —
  *"El pipeline NO pasa por `validate_external_verdict`: entra por …"*.
- La ruta que sí se ejecuta es la de `relations/external_ai_shadow.py` (validación duplicada,
  ver defecto 4), consumida por `relations/consensus_adapter.py:68,339,393`.

Una API de seguridad con 24 tests y ningún llamador puede divergir de la ruta real sin que
nada se ponga rojo. Es precisamente el patrón que el Supervisor señaló como lección del
programa ("tests en verde que no ejercitaban la ruta real"): **sigue vivo**.

---

## 6. `pair_F1` no mejoró — 11 falsos negativos

**CONFIRMADO, remedido en las 4 corridas de este baseline.**

`global_existence` es idéntico en los cuatro carriles:

```
P=0.8269  R=0.7963  F1=0.8113  TP=43  FP=9  FN=11
```

El selector de predicados no cambia la **generación de pares**, sólo el nombre del predicado;
por eso v1 y v2 comparten exactamente el mismo `pair_F1`. Las 11 relaciones del GT que nunca
se emparejan (`errors.false_negatives` del JSON) siguen sin generarse: incluyen elipsis de
sujeto (`rel-006`, `rel-007`), direccionalidad `PARENT_OF` (`rel-008`, `rel-009`), alias
reflexivo (`rel-010`) y pronombre objeto (`rel-029`).

Es el techo que el programa V2 **no tocó** y que ninguna mejora posterior de predicado,
dirección o temporalidad puede recuperar: si el par no se genera, no hay nada que corregir.

---

## Anexo — limitaciones §8 que NO son defectos de código pero siguen vigentes

- **§8.1 / §8.2 — `n=54` con `dev == test`.** Confirmado: `manifest.json` declara 54 relaciones
  y 16 fuentes; no existe partición held-out en `tests/data/relation_benchmark/`. El rango
  honesto de predicado sigue siendo **[0.42, 0.81]**.
- **§8.6 — `veto_on_temporal_not_in_force` no dispara.** No re-medido en este bloque.
- **§8.7 — proveedores reales nunca ejecutados.** Confirmado también aquí: los 4 runs reportan
  `local=NOT_EXECUTED external=NOT_EXECUTED`, `0` llamadas, `transport_errors=0`.
- **§8.8 — spaCy/Stanza sin medir.** Confirmado: siguen sin instalar (2 skips, ver
  `skipped-tests.md`).
- **Nota del arnés no listada en §8:** `benchmark-*.json` incluye un `config_notes` que declara
  que `max_time_per_candidate_ms` **está declarado pero NO se aplica**: el pipeline no lo
  comprueba en ningún punto. Es un control de recursos inefectivo, y sigue vigente.
