# 03 — Corpus congelado (Comparativa unificada PR#95)

El corpus se congelo **antes** de ejecutar y no se adapto para favorecer a ninguna
version. Hashes en `artifacts/pr95-unified-comparison/ground-truth-hash.txt` y
`corpus-manifest.yaml`.

## C1 — corpus vigente del proyecto (B1)
- Ruta: `data-engine/app/tests/data/relation_benchmark` (16 fuentes, 54 relaciones).
- `manifest.json` sha256 `a2cc506f…d2631`; `ground_truth/relations.json` sha256 `15973d18…cc5c`.
- Verificado: **54/54** relaciones cumplen `document[start:end] == evidence_text`
  (literalidad del GT). Se carga con `verify=True` (sha256 por fuente + GT).
- Distribuciones: direccion {SUBJECT_TO_OBJECT 41, UNDIRECTED 8, OBJECT_TO_SUBJECT 5};
  temporal {PRESENT 27, PAST 18, FUTURE 5, ENDED 3, ONGOING 1}; negadas 5/54;
  epistemico {ASSERTED 46, INTENDED 3, HYPOTHETICAL 3, RUMORED 2}.
- Uso: **PISTA PIPELINE** (ejecucion real del pipeline) y base documental de la
  **PISTA PROTOCOLO** (banco sintetico construido sobre estos documentos + GT).

## C3 — corpus adversarial (protocolo)
6 casos con documento y GT propios (`ground-truth.jsonl`, prefijo `c3-*`):
evidencia repetida (dos coincidencias validas), prompt injection dentro de la
evidencia, offsets maliciosos fuera de rango, fragment IDs inexistentes, JSON hostil
(verdict fuera de catalogo + confidence>1), negacion distante + atribucion en otra
frase + rumor. Sirve para medir fail-closed y literalidad bajo ataque.

## C2 — corpus independiente REDUCIDO (declarado)
4 casos no usados para desarrollar V1-V4 (`c2-*`): positiva, direccion inversa,
hipotesis, temporalidad-pasado. **Se entrega reducido a proposito** (presupuesto de
un ciclo; el encargo autoriza priorizar C1+C3). Ampliacion (ausencia de relacion,
rumor, intencion, multi-mencion, mas interfrase) = 2a oleada.

## Banco sintetico comun
`synthetic-bank.json` (sha256 `5e143fe2…c508`). Para cada (documento, relacion GT)
genera la respuesta de un "modelo de competencia fija" a CADA protocolo con la MISMA
mezcla de dificultad (tiers: exact, offset_shift, para_light, para_strong, injection).
Es **sintetico**: NO es el juez real. El juez real es la corrida NVIDIA (fase
separada, NO ejecutada aqui).
