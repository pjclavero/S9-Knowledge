# 38 · Ensayo E2E previo a la primera ingesta real — Prioridad 3A

**Clasificación: ENSAYO E2E PREVIO A LA PRIMERA INGESTA REAL** (fuente **sintética**, ; NO es la primera ingesta real).
**Estado: PREPARACIÓN — SIN ESCRITURA**
**Fecha:** 2026-07-15
**Commit:** `91de633` (main desplegado)
**Rama operativa:** `ops/priority-3-first-controlled-ingest`

> Ninguna escritura en Neo4j. `S9K_ALLOW_REAL_INGEST` unset durante toda la fase.
> Este documento se completará con los resultados reales **tras** la autorización humana
> y la ingesta. Las secciones marcadas `PENDIENTE` no se ejecutan en esta fase.

---

## 1. Snapshot de preparación (Neo4j, antes)

| Métrica | Valor real |
|---|---:|
| Nodos | 199 |
| Relaciones | 140 |
| Índices | 2 |
| Constraints | 0 |
| `S9K_ALLOW_REAL_INGEST` | unset |
| Servicios | neo4j healthy, visor activo, rclone activo, Ollama qwen2.5:7b accesible |
| Jobs de ingesta activos | 0 |

Fuentes ya presentes en Neo4j (procedencia): `l5a_game_masters_guide_2da` (99 nodos),
`test_creatures_locations_timeline` (13 nodos).

---

## 2. Fuente seleccionada (§4–§5)

| Campo | Valor |
|---|---|
| `source_id` | `source_narrative_01` |
| Tipo | narrativo (texto sintético validado, workspace `leyenda`) |
| Tamaño | 469 bytes, 2 segmentos |
| SHA256 (fuente) | `a54c6233097be511bf614039fbedbfb9d2e4302e2f15b66528cfb6278a0f29a0` |
| Estado de ingesta previa | **NOT_INGESTED** (`source_id` con 0 nodos en Neo4j) |
| Ground truth | pase 3, `reviewed=true` (8 entidades esperadas) |
| Ruta | fixture del repositorio (no privada) |

### Motivo de selección (menor riesgo)
Fuente pequeña, validada (GT pase 3), sin errores ASR, con nombres propios explícitos, F1
de entidades = 1.000 en el benchmark confirmatorio (docs/37), y **no ingerida**. Se excluyeron:
`source_transcript_session_02` (= `test_creatures_locations_timeline`, **ya ingerido**),
`source_transcript_asr_01` (errores ASR), `source_resolution_01` (ambigüedad/duplicados por
diseño), `media_2bdf6005fcffd476` (real pero 30 segmentos, no "pequeño", con falsos positivos).

> Nota: 2 entidades de la fuente (**Akodo Toturi**, **Clan Grulla**) ya existen como nodos
> exactos (del game master's guide) → se resolverán como `USE_EXISTING`, no como duplicados.
> Esto NO significa que la fuente esté ingerida (su `source_id` no está presente).

---

## 3. Pipeline sin escritura (§7)

Configuración: `S9K_REVIEW_EXTRACTOR=hybrid`, `S9K_REVIEW_POLICY=full_human_review`, `S9K_ALLOW_REAL_INGEST` unset.

| Validación | Resultado |
|---|---|
| Segmentos totales / extraíbles | 2 / 2 |
| Modo solicitado / ejecutado | hybrid / hybrid |
| Llamadas LLM correctas | > 0 (heurístico 13, LLM 13) · fallback = **false** |
| Candidatos totales | 14 (9 entidades, 5 relaciones) |
| Autoaprobados | **0** (política full_human_review) |
| Entidades sin evidencia / sin source_id | 0 / 0 |
| Neo4j modificado | **NO** |

---

## 4. Relaciones — todas excluidas (§8)

| Métrica | Valor |
|---|---:|
| Detectadas | 5 |
| Sin evidencia | 0 |
| Extremos no resueltos | 0 |
| Excluidas de la primera ingesta | 5 (todas) |

Recomendación por relación: `REJECT_FOR_FIRST_INGEST` · motivo `first_controlled_ingest_entities_only`.
(La decisión humana definitiva no se registra en esta fase.)

---

## 5. Revisión de entidades propuesta (§9–§10)

Orden: casos que requieren atención primero.

| Recomendación | Entidad | Tipo | Conf | Resolución | Motivo |
|---|---|---|---:|---|---|
| REJECT | Clan Escorpión | Clan (**tipo inválido**) | 0.85 | use_existing/exact | duplicado con tipo inválido (existe versión Faction) |
| EDIT | clan León | Faction | 0.92 | use_existing/exact | casing no canónico → normalizar "Clan León" |
| EDIT | clan Grulla | Faction | 0.92 | use_existing/exact | casing no canónico → normalizar "Clan Grulla" |
| USE_EXISTING | Akodo Toturi | Character | 0.90 | use_existing/exact | match exacto con nodo existente |
| APPROVE_UNCHANGED | Otosan Uchi | Location | 0.85 | create_new | conf alta |
| APPROVE_UNCHANGED | Río Kanji | Location | 0.90 | create_new | conf alta |
| APPROVE_UNCHANGED | Matsu Tsuko | Character | 0.90 | create_new | conf alta |
| APPROVE_UNCHANGED | Clan Escorpión | Faction | 0.92 | exact | conf alta (versión con tipo válido) |
| APPROVE_UNCHANGED | Bayushi Kachiko | Character | 0.90 | create_new | conf alta |

**Resumen:** 9 entidades · APPROVE_UNCHANGED 5 · USE_EXISTING 1 · EDIT 2 · REJECT 1 · AMBIGUOUS 0 · relaciones excluidas 5.

> El `full_human_review` capturó problemas reales de calidad (duplicado con tipo inválido "Clan",
> casing "clan León"/"clan Grulla") que una autoaprobación habría dejado pasar. Estos casos son
> exactamente el objetivo de calibración de la primera ingesta.

`review_report_sha256` = `5ac551136281236d405d0df2c9777a01d42d9aeaa4e7d9bbe44d010c23005540`

---

## 6. Automatización sombra (§11)

| Métrica | Valor |
|---|---:|
| SHADOW_AUTOAPPROVE | 2 |
| SHADOW_REVIEW | 7 |
| Cobertura automática potencial | 22 % |
| Revisión potencial | 78 % |

Detalle y metodología en [docs/39](39-risk-based-autoapproval-calibration.md). **Modo sombra: NO ACTIVO.**
La precisión sombra no puede calcularse hasta comparar con las decisiones humanas (pendiente de autorización).

---

## 7. Seguridad (§12)

| Métrica | Antes | Después (fase de preparación) |
|---|---:|---:|
| Nodos Neo4j | 199 | 199 |
| Relaciones Neo4j | 140 | 140 |
| `S9K_ALLOW_REAL_INGEST` | unset | unset |
| approved_payload de escritura | — | **no generado** |
| Ingesta ejecutada | — | **NO** |

Delta nodos = 0 · Delta relaciones = 0.

---

## 8. Gate de autorización humana (§13)

La operación se detiene aquí. Para continuar (registrar decisiones, generar payload, backup,
dry-run, autorización de escritura), el operador humano debe proporcionar:

```
AUTHORIZE_REVIEW_DECISIONS:
source_id=source_narrative_01
review_report_sha256=5ac551136281236d405d0df2c9777a01d42d9aeaa4e7d9bbe44d010c23005540
operator=<identidad real>
approve_recommendations=yes
exceptions=<none o lista>
```

> La identidad del operador **no se inventa**. No se registran decisiones ni se hace backup ni
> se escribe en Neo4j hasta recibir esta autorización con un operador real.

---

## 9. PENDIENTE (tras autorización)
- Registro de decisiones humanas (CLI append-only).
- Payload revisado + SHA256.
- Backup inmediatamente anterior + copia externa verificada.
- Autorización de escritura (`AUTHORIZE_FIRST_REAL_INGEST`).
- Escritura real (one-shot), delta Neo4j, auditoría, rollback dry-run.

---

## Dictamen
```
Ensayo E2E (fuente sintética): PREPARADO PARA AUTORIZACIÓN DE REVISIÓN
Primera ingesta real: NO INICIADA (source_narrative_01 es texto sintético)
```
