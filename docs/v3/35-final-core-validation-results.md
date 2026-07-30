# Resultados finales de validación del núcleo V3

Fecha: 2026-07-30

## Identidad y configuración

- Commit base: `d50c9312914f3ae5277d3e8fedfe47628666a9c6`
  (`docs/v3-sync-post-lotes`).
- HEAD validado: `296e762533326ff474c0a7dcf33c3de57d5f6b08`.
- Rama: `integration/v3-final-core-validation`.
- Motor y writer locales; writer dry-run salvo la puerta 7 contra Neo4j
  efímero y aislado. Proveedores reales sólo en las medidas declaradas.
- Umbrales, corpus y artefactos de medición no se relajaron durante la
  corrección.

## Veredicto por puerta

| Puerta | Veredicto | Evidencia vinculante |
|---|---|---|
| 3 — planner | **CONFORME** | P3-1 corregido y convertido en regresión verde. |
| 4 — negaciones | **NO CONFORME** | Alcance 0.875 < 0.95; recall de autoaprobación SIMPLE 0.10 < 0.75. Cobertura determinista 8/56; causa raíz en `gate4-diagnosis.md`. |
| 5 — autoridad local | **CONFORME** | 5/5 gates duros con Ollama y NVIDIA reales; ninguna escritura decidida por proveedor o sombra. |
| 6 — factualidad | **NO CONFORME** | 2 violaciones residuales; acuerdo 79.17% < 100%; generalización no factiva 0.231. |
| 6B — revisión humana | **CONFORME** | Feed real, control de acceso, decisiones append-only, STALE seguro y glosario efectivo sin mutación. |
| 7 — Neo4j real | **CONFORME** | **53 passed en VM105** contra Neo4j efímero, incluida la primera aplicación real de un plan producido por el motor. |

La puerta 4 no falla principalmente por el umbral de política: 48/56 claims no
llegaron a decisión. Entre los 8 cubiertos, el alcance fue 7/8; sólo 2 de los 11
SIMPLE llegaron al motor. La puerta 6 tampoco se cierra por la mejora 4→2:
fuera del corpus la política sigue leyendo 20/26 no factivas como hechos.

## Defectos encontrados y corregidos

- **P3-1:** el planner admitía contradicciones de lote por una ruta; se endureció
  la admisión y el xfail quedó como regresión verde.
- **D-G1:** cues no reconocía construcciones reales de rumor/hipótesis y podía
  aprobarlas como mundo; se amplió la detección, sin declarar generalización.
- **D-G2:** `review_export` buscaba campos singulares inexistentes y mostraba
  sujetos/objetos desconocidos; se adaptó a los contratos plurales reales.
- **P5-1:** una respuesta de proveedor `200 {}` parecía éxito sin diagnóstico;
  ahora deja rastro y conserva el cierre sin escritura.
- **F7-1:** las aserciones del snapshot carecían de `state_hash`, haciendo
  inalcanzable una cesación real; se propagó el ancla de concurrencia.
- **F7-2:** el planner incluía `assertion_id` como propiedad reservada y el
  writer abortaba el primer apply; se separó el identificador del payload.

## Suite, skips y reproducibilidad

Resultado final agregado: **5183 passed, 36 skipped, 3 xfailed**. Los 36 skips
fueron clasificados y hubo **0 accidentales**; corresponden a integraciones
externas o dependencias explícitas, no a pérdida silenciosa descubierta.

La reproducibilidad determinista se verificó con
`PYTHONHASHSEED=1,7,42,123`: 3 sondas × 4 procesos nuevos = 12 ejecuciones y
cero variación intra-sonda. `plan_hash` e `idempotency_key` están incluidos en
los hashes comprobados. El carril generativo de proveedor queda fuera de esa
garantía y mostró 7/24 cambios entre corridas idénticas.

## Rendimiento informativo

Estas cifras no condicionan gates. En una máquina con carga 9.0–11.5, NVIDIA
procesó 24 frases/48 llamadas en 1 372 s, con mediana 50 107 ms y 0 errores.
El prompt mínimo de NVIDIA tardó 6 213 ms. Ollama tardó 87 844 ms en frío y
2 032–2 527 ms en caliente con el prompt mínimo; el prompt real es mucho más
costoso. Las suites base tardaron 93–97 s (`data-engine/app`) y ~30 s
(`viewer`); `policy` sobre 100 frases tardó <1 s y `det` <5 s.

## Incidencia operativa

`qwen2.5:7b` en esta CPU no completa el prompt real dentro del timeout de 600 s
para la mitad de los episodios medidos: **2/4 terminaron
`PROVIDER_UNAVAILABLE`**. El sistema falla de forma segura y continúa el lote,
pero el carril Ollama **no es utilizable para ingesta tal como está**.

Fuentes: `artifacts/v3-final-validation/{gates-summary,gate4-negation-metrics,
gate4-diagnosis,gate5-authority,gate6-factivity-matrix,gate6-findings,
gate6b-human-review,e2e-results,skips-classification,reproducibility,perf-notes}.*`
y el historial Git de la rama.
