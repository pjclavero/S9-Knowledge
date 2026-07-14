# 39 · Calibración de autoaprobación basada en riesgo — modo sombra

**Estado: MODO SOMBRA — NO ACTIVO**
**Fecha:** 2026-07-15
**Fuente de calibración:** `source_narrative_01` (primera ingesta controlada, docs/38)

> Este documento contiene el **análisis** de una futura política `risk_based_autoapproval`.
> **No activa ninguna decisión automática.** La política real solo se habilitará tras alcanzar
> los umbrales de precisión sobre las primeras fuentes reales revisadas por humanos.

---

## 1. Objetivo

Automatizar el mayor porcentaje posible de entidades manteniendo la seguridad. La revisión
humana total (`full_human_review`) es temporal, solo para obtener datos de calibración de la
primera fuente. Objetivo posterior: 80–90 % de entidades automáticas, 10–20 % a revisión;
las relaciones permanecen en revisión hasta superar sus umbrales.

---

## 2. Regla sombra inicial

Un candidato se marca `SHADOW_AUTOAPPROVE` **solo si** cumple TODOS:

```
kind = entity
extractor = hybrid
evidencia explícita
tipo permitido (Character|Location|Faction|Object|Event|Concept)
sin ambigüedad
sin duplicado probable
nombre canónico válido (no casing anómalo, no tipo inválido)
no palabra común
no candidato débil de un solo token (sin glosario)
confianza >= 0.85
acuerdo heuristic + LLM (provenance=both) O coincidencia inequívoca con glosario/Neo4j (match exact/alias)
```

El resto → `SHADOW_REVIEW`.

---

## 3. Características registradas por candidato (features)

Para cada entidad se registra: detección heurística, detección LLM, acuerdo, confianzas
(heuristic/LLM/hybrid), evidencia explícita, tipo válido, alias conocido, coincidencia exacta
con Neo4j, posible duplicado, ambigüedad, y la recomendación de revisión preparada.

---

## 4. Resultado sombra en la fuente de calibración

| Métrica | Valor |
|---|---:|
| Entidades | 9 |
| SHADOW_AUTOAPPROVE | 2 |
| SHADOW_REVIEW | 7 |
| Cobertura automática potencial | 22 % |
| Revisión potencial | 78 % |

**Precisión sombra: no calculable todavía** — requiere comparar con las decisiones humanas, que
aún no están autorizadas (docs/38 §8).

### Limitación observada (accionable)
El campo `_provenance` (acuerdo heuristic/LLM) que produce el filtro híbrido **no se persiste**
en `candidates.json`, por lo que la regla sombra cae a la coincidencia `match_type` y resulta
conservadora (22 %). **Mejora propuesta:** persistir `_provenance` en el candidato para que la
regla sombra pueda usar el acuerdo heuristic+LLM (rule A), lo que elevaría la cobertura de forma
segura. Esta mejora entrará como PR de código separado.

---

## 5. Umbrales para activación futura (no activos)

```
precisión sombra >= 0.98 en las primeras fuentes reales
cero falsos positivos graves
cero candidatos sin evidencia
cero duplicados ambiguos autoaprobados
relaciones: permanecen en revisión hasta F1 >= 0.60 y P >= 0.75
```

Solo cuando estos umbrales se cumplan sobre varias fuentes reales revisadas se propondrá activar
`risk_based_autoapproval` (probablemente como una política intermedia entre `normal` y
`full_human_review`), y siempre con muestreo de auditoría humana.

---

## 6. Estado

```
Modo sombra: NO ACTIVO
Precisión: pendiente (requiere decisiones humanas autorizadas)
Siguiente paso: comparar shadow vs humano tras la primera ingesta autorizada
```
