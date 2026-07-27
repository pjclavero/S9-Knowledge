# Motor de relaciones v2 — Auditoría (Etapa 1) y Diseño (Etapa 2)

**Rama:** `feat/relation-engine-v2-hybrid` · **Commit base:** `dcded31` (origin/main) ·
**Estado:** ETAPA 1 cerrada; ETAPA 2 (diseño) pendiente de aprobación del Supervisor antes
de implementar. **No se ha tocado el motor todavía.**

Objetivo del programa: mejorar **predicado, dirección, temporalidad, decisión y strict_F1**
del motor PROPIO (offline, sombra, fail-closed, sin escritura Neo4j), demostrado por
benchmark A/B, sin sobreajustar al corpus.

---

## 1. Diagnóstico — CONFIRMADO (con datos)

### 1.1. Techo mecánico del predicado
`relations/pipeline.py:_choose_predicate` solo puede emitir **5 predicados**:
`{MEMBER_OF, OWNS, LOCATED_IN, PARTICIPATED_IN, RELATED_TO}` (vía `_CUE_PREDICATE`,
`_CATEGORY_PREDICATE`, `GENERIC_PREDICATE`). La ontología (`ALLOWED_RELATION_TYPES`) tiene
**113**.

- El GT del corpus B1 (54 relaciones) usa **20 tipos** de predicado.
- **Solo 25/54 = 0.463** tienen un predicado que el motor actual PUEDE emitir.
- El resto (53.7%) es **imposible por construcción** → `predicate_exact` techado en ~0.46;
  el medido (0.256) está aún por debajo (dentro de los 5, tampoco acierta siempre).

**Conclusión:** el cuello no es "el motor elige mal" sino que **no puede siquiera nombrar**
más de la mitad de las relaciones. Cualquier mejora real EXIGE ampliar el espacio de salida.

### 1.2. Matriz de predicados (GT del corpus)

| Predicado GT | n | En ontología | Emitible por motor actual |
|---|--:|:--:|:--:|
| MEMBER_OF | 10 | sí | **sí** |
| PARTICIPATED_IN | 6 | sí | **sí** |
| OWNS | 5 | sí | **sí** |
| LOCATED_IN | 4 | sí | **sí** |
| ALLIED_WITH | 3 | sí | no |
| PARENT_OF | 3 | sí | no |
| ENEMY_OF | 2 | sí | no |
| GUARDS | 2 | sí | no |
| MENTOR_OF | 2 | sí | no |
| TRUSTS | 1 | sí | no |
| KNOWS | 1 | sí | no |
| LIVES_IN | 3 | **NO** | no |
| ALIAS_OF | 2 | **NO** | no |
| FOUNDED | 2 | **NO** | no |
| SUCCEEDED | 2 | **NO** | no |
| CAUSED | 2 | **NO** | no |
| LEADS | 1 | **NO** | no |
| CREATED | 1 | **NO** | no |
| MARRIED_TO | 1 | **NO** | no |
| SIBLING_OF | 1 | **NO** | no |

### 1.3. Desajuste ground-truth ↔ ontología (segundo hallazgo)
**9 tipos del GT (~15 relaciones) NO están en `ALLOWED_RELATION_TYPES`.** Antes de medir
nada hay que **reconciliar** esto (Bloque 0), sin amañar: o se añaden a la ontología (si son
canónicos legítimos), o el GT usa alias que deben mapear a un canónico. Cada corrección del
corpus/ontología irá en **commit separado**, con antes/después, aprobada por Revisor y
Supervisor. **No se toca el GT para favorecer al motor.**

> Nota: `LIVES_IN` vs `LOCATED_IN`, `LEADS` vs un futuro `LEADS`, `ALIAS_OF`, `SIBLING_OF`,
> `MARRIED_TO`, `PARENT_OF` (familia) son candidatos claros a entrar en el núcleo común de
> la ontología v2 (§7.1 del prompt). Requiere revisión humana del diseño.

---

## 2. Diseño objetivo (Etapa 2) — resumen para aprobación

### 2.1. Arquitectura por componentes (no monolito)
```
entidades → pares → detector de existencia → familias candidatas →
predicados candidatos → filtro ontológico (dominio/rango) → ranking determinista →
dirección (módulo independiente) → temporalidad/vigencia → epistémico →
validación de evidencia → consenso → {aprobación sombra | revisión parcial | abstención}
```
Cada etapa **desactivable** (ablation) y con confianza propia. Contrato de 20 campos
intacto; las abstracciones nuevas son internas o via adaptador (como hizo V4).

### 2.2. Cambios clave
- **Ontología como fuente única** (`vocabulary.py` extendido): canónico, alias, familia,
  **dominio/rango**, inversa, simetría, expresiones activa/pasiva, confundibles, temporalidad.
  Elimina divergencias entre pipeline/signals/plantillas/tests/benchmark.
- **Selector de predicado v2**: genera CANDIDATOS con score y **abstiene** si no hay margen
  (`REVIEW_PREDICATE`), en vez de la cascada de 5. Tipos = filtro, no selector.
- **Dirección**: módulo independiente (activa/pasiva/agente/inversa/simetría/preposición/
  correferencia; orden textual solo fallback débil). Simétricos → `semantic_direction=NONE`.
- **Temporalidad/vigencia**: estados `ACTIVE/ENDED/PLANNED/HYPOTHETICAL/RECURRING/UNKNOWN`
  + `valid_from/valid_to`; permite transiciones (ALLY→ENDED→ENEMY) sin sobrescribir historia.
- **Decisión/abstención**: estados `SHADOW_APPROVED/REVIEW_*/CONFLICT/INSUFFICIENT_EVIDENCE/
  REJECTED` (sin escritura; `AUTO_APPROVED` solo como resultado de benchmark, nunca write).
- **Parser opcional** (spaCy/Stanza) tras interfaz, **desactivable, fallback stdlib**,
  comparado (no asumido mejor).
- **IA externa V3 (fragmentos) como vía preferida**; V2 (realineamiento) solo fallback con
  coincidencia única no ambigua. La IA externa **nunca** escribe/autoaprueba/anula rechazo local.

### 2.3. Bloques (commit + tests + revisión + A/B por bloque)
```
B0 benchmark + reconciliación GT/ontología   B1 ontología v2
B2 selector de predicados                    B3 dirección
B4 temporalidad                              B5 parser opcional
B6 consenso y abstención                     B7 IA externa V3
B8 benchmark final + informe
```

### 2.4. Gates experimentales (para considerar mejora real; NO se rebajan umbrales existentes)
`predicate_exact ≥ 0.50 · direction_exact ≥ 0.75 · temporal ≥ 0.60 · strict_F1 ≥ 0.35`,
sin bajar `pair_F1` ni `evidence_correct`, sin romper determinismo/seguridad, sin escritura.
Línea base a batir (medida): predicate 0.256, direction 0.628, temporal 0.442,
decision 0.302, strict_F1 0.208, evidence_correct 0.907, pair_F1 0.811.

### 2.5. Riesgos y rollback
- **Sobreajuste al corpus (54 rel):** prohibido entrenar modelo productivo; motor
  estructurado + reglas de ontología; validar con abstención y por-clase, no solo global.
- **Reconciliación GT:** riesgo de amañar → commits separados, antes/después, doble aprobación.
- **Rollback:** todo tras flags con default = comportamiento base; rama aislada; sin merge.

---

## 3. Estado y siguiente paso
Etapa 1 (auditoría) **cerrada**: diagnóstico confirmado + matriz + desajuste GT/ontología.
**Pendiente:** aprobación del plan (Etapa 2) antes de implementar B0→B8. No se ha modificado
ningún fichero del motor.
