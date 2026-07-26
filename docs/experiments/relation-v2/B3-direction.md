# Bloque 3 — Dirección como **módulo independiente y robusto**

**Programa:** motor de relaciones v2 · **Rama:** `feat/relation-engine-v2-hybrid` ·
**Antecedente:** `B2-predicate-selector.md` (HEAD B2 `a420c16`).

Bloque 3 extrae la resolución de **dirección semántica** a un módulo puro y
determinista, `relations/direction.py`, y hace que el camino v2 lo **consuma** en
lugar de la dirección por defecto del predicado (`pipeline._direction_for`, que sólo
sabía dar `SUBJECT_TO_OBJECT` para dirigidos y `UNDIRECTED` para simétricos, **nunca**
`OBJECT_TO_SUBJECT`). El objetivo no es perseguir la cifra sino **consolidar** la
dirección como eje propio, cubrir casos (pasiva, agente, inversa, simetría, pronombre,
correferencia, interfrase, sujeto omitido) y ganar robustez.

Trabajo offline, sin red, sin escritura, determinista. **No** se bajan `THRESHOLDS`,
**no** se toca el GT/corpus, **no** se relaja ningún assert. El default `v1` sigue
siendo bit-a-bit idéntico al comportamiento base (dirección incluida).

---

## 1. Arquitectura del módulo

`relations/direction.py` expone una función pura:

```
resolve_direction(predicate, subject_start, subject_end,
                  object_start, object_end, seg_text, syntax=None) -> DirectionResult
```

`DirectionResult(direction, confidence, rationale)`. Convención de las menciones
(igual que `relations.pairs`): **sujeto = mención textual previa**, **objeto = mención
posterior**. La dirección se resuelve **relativa a ese par**:

- `SUBJECT_TO_OBJECT` — la fuente semántica es la primera mención (sujeto textual).
- `OBJECT_TO_SUBJECT` — la fuente es la segunda mención (lectura textual invertida).
- `UNDIRECTED` — predicado simétrico (el orden de almacenamiento no es dirección).

Señales consultadas, en **orden de prioridad** (de más fiable a menos), cada una con
una confianza ordinal:

| # | Señal | Fuente | Confianza | `rationale` |
|---|---|---|---|---|
| 0 | **Simetría** (guarda) | `ontology.is_symmetric` | 0.90 | `symmetric_undirected` |
| 1 | Sujeto/objeto **gramatical** (voz activa) | `syntax.py` (SVO) | 0.75 | `grammatical_subject` |
| 2 | **Pasiva + agente** ("… por X") | gramática general + `syntax.passive` | 0.85 | `passive_agent` |
| 3 | Expresión **inversa** (pasiva) | `ontology.passive_expressions` | 0.80 | `inverse_expression` |
| 5 | Expresión **activa** / preposición | `ontology.active_expressions` | 0.70 | `active_expression` |
| 6 | **Correferencia**/pronombre básico | `syntax.py` (pronombre sujeto) | 0.60 | `coref_pronoun` |
| 7 | **Orden textual** (fallback débil) | — | 0.50 | `textual_order` |

`RELATED_TO` y cualquier predicado fuera de la ontología → `UNDIRECTED`
(`generic_undirected`, conf 0.50), paridad con el pipeline previo.

**Simetría como guarda.** Aunque la spec la numera 4ª, es un **invariante del
predicado**: se comprueba primero y corta (un simétrico es `UNDIRECTED` haya o no
estructura de "por" alrededor). El orden 1–3/5–7 gobierna la orientación de los
**dirigidos**.

### Cómo maneja pasiva / inversa / simetría

- **Pasiva + agente (regla GENERAL).** Busca `" por "` en la ventana; exige evidencia
  de pasiva (participio regular `-ado/-ada/-ido/-ida` o irregular frecuente justo
  antes, o `syntax.passive=True`). El agente es la fuente, **pero sólo se ancla si ese
  agente es una de las dos menciones del par**: si tras `"por"` viene una **tercera
  entidad**, la señal se **abstiene** (no inventa orientación). Esto no depende del
  léxico del predicado — resuelve `"fue robado por…"` aunque `robar` no esté en la
  ontología.
- **Inversa (léxico de la ontología).** Las `passive_expressions` de un dirigido
  codifican la lectura inversa (`"hijo de"`, `"pertenece a"`). Si aparece una pasiva y
  **no** una activa, el **complemento** (mención posterior a la expresión) es la fuente
  → `OBJECT_TO_SUBJECT`. La activa hace lo simétrico: fuente = mención anterior.
- **Simetría.** `ALLIED_WITH, ENEMY_OF, SIBLING_OF, MARRIED_TO, ALIAS_OF` (derivados de
  `ontology.SYMMETRIC_PREDICATES`) → `UNDIRECTED`.

Detalle de robustez: el plegado de acentos preserva longitud (traducción 1:1
`á→a`, `ñ→n`) para que los offsets del anclaje no se desalineen.

---

## 2. Integración en el pipeline (sólo v2)

`pipeline._build_candidate` recibe ahora `syntax_analysis` (ya se computaba una vez
por segmento) y, en el camino `predicate_selector=v2`, deriva la dirección con
`direction.direction_for_pair(predicate, pair, seg_text, syntax=…)`. El camino `v1`
(default) **no se toca**: sigue usando `_DIR_BY_PRED` y es metric-neutral. El contrato
de 20 campos no cambia (sólo cambia el **valor** del campo `direction` en v2).

---

## 3. Medición A/B honesta (`--mode baseline1`, corpus real, TP=43)

| Métrica | base (`v1`) | v2 (B2, sin B3) | **v2 + B3** |
|---|---|---|---|
| `direction_exact` | 0.6279 (27/43) | 0.8372 (36/43) | **0.9302 (40/43)** |
| `direction_orientation_ok` | 0.7674 (33/43) | 0.9535 (41/43) | 0.9535 (41/43) |
| `predicate_exact` | 0.2093 | 0.8140 | 0.8140 |
| `evidence_correct` | 0.9333 | 0.9333 | 0.9333 |
| `pair_F1` (existencia) | 0.8113 | 0.8113 | 0.8113 |

**B3 SÍ mejora** `direction_exact`: **0.8372 → 0.9302** (+0.093, +4 aciertos), usando
sólo gramática general + ontología. Recupera exactamente los casos que el pipeline
antes nunca podía acertar (los `OBJECT_TO_SUBJECT` reales: pasiva con agente e inversa
de parentesco/posesión). `direction_orientation_ok`, `predicate_exact`,
`evidence_correct` y `pair_F1` quedan **idénticos**: **cero regresiones**. `v1` sigue
en 0.6279 (bit-a-bit).

### Los 3 fallos de dirección restantes (honestidad)

Los mismatches que quedan en v2+B3 **no** son del módulo de dirección: son casos donde
el **selector de predicado** cayó a `RELATED_TO` (abstención/sin soporte), y sobre un
predicado desconocido la dirección correcta es `UNDIRECTED` (que es lo que el módulo
da). Son `ALLIED_WITH`/`MENTOR_OF`/`KNOWS` que el GT marca `SUBJECT_TO_OBJECT` pero para
los que no se comprometió predicado. Es decir: **el techo restante es de predicado, no
de orientación**. El módulo no puede orientar lo que no tiene predicado.

---

## 4. Sin calcos del corpus

Las reglas son gramática GENERAL del español (pasiva perifrástica *ser/estar +
participio + por*, núcleos relacionales inversos) y la **fuente única** `ontology.py`
(expresiones activas/pasivas y simetría ya existentes en B1/B2). **No** se añadió
ninguna expresión ni patrón calcado de frases concretas del corpus para subir la cifra
(la lección de B2). Los ejemplos de los tests usan entidades inventadas
(Marcus/Kael/Gorm/…), no las del benchmark, para validar reglas, no textos.

---

## 5. Casos cubiertos (`tests/test_relation_v2_b3_direction.py`, 24 tests)

A→B activa · B→A inversa · sujeto/objeto gramatical (activa, y con sujeto en 2ª
mención) · pasiva + agente (regla general) · agente de pasiva de **tercero** (se
abstiene) · `passive_hint` desde sintaxis · inversa de parentesco (`hija de`) vs activa
(`padre de`) · simétrica → `UNDIRECTED` (5 predicados) · orden textual engañoso ·
pronombre/correferencia básica · interfrase · sujeto omitido (pro-drop) · `RELATED_TO`
y predicado desconocido → `UNDIRECTED` · determinismo. Sin `skip`/`xfail`; asserts que
muerden (dirección + `rationale`).

---

## 6. Suites

- `pytest tests/ -k relation -q` → **988 passed**, 538 deselected.
- `pytest tests/test_relation_calibration_final_quality_block9.py` → **48 passed**.
- `pytest tests/test_relation_v2_b3_direction.py` → **24 passed**.

Sin `THRESHOLDS` tocados, sin red, sin escritura, determinista (`deterministic=True`
en el arnés).

---

## 7. Ficheros

- **Nuevo** `relations/direction.py` — módulo puro de dirección.
- **Nuevo** `tests/test_relation_v2_b3_direction.py` — 24 tests.
- **Modificado** `relations/pipeline.py` — v2 consume `direction.py`; se pasa
  `syntax_analysis` a `_build_candidate`. `v1` intacto.
- **Nuevo** `docs/experiments/relation-v2/B3-direction.md` — este documento.
