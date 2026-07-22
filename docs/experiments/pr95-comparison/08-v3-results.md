# 08 — Resultados V3 (fragment protocol)

Flag: `RelationExternalConfig.fragment_protocol_enabled = True`. El documento se
presenta FRAGMENTADO en frases con IDs estables (`f-NNN`); el modelo elige
`fragment_ids` en vez de copiar cita/offsets. El sistema **reconstruye** los offsets
desde los IDs (min start, max end) contra el documento real: literalidad garantizada
por construccion.

## Banco sintetico — C1_common (54 casos)
| metrica | base | V3 |
|---|---|---|
| valid_response_rate | 0.185 | **0.963** |
| literal_evidence_rate (aceptado) | 1.0 | **1.0** |
| fragment_reconstruction_rate | — | 0.963 |
| invalid_fragment_rate | — | 0.037 |
| prompt_injection_success | 0 | **0** |

Aceptacion por tier: `offset_shift` 11/11, `para_light` 11/11, `para_strong` 11/11,
`exact` 10/11, `injection` **9/10**.

## Hallazgos
- **Positivo**: V3 alcanza la mayor tasa de respuesta valida (0.963) del protocolo.
  Al elegir por ID, offsets desplazados y parafrasis **dejan de importar**: el modelo
  no tiene que producir la cita literal, y la reconstruccion es literal por diseno.
- **Robustez a inyeccion**: en el tier `injection`, V3 acepta 9/10 SIN que la
  inyeccion tenga efecto (`prompt_injection_success = 0`): la evidencia aceptada es la
  rodaja de los fragmentos elegidos, no el texto inyectado, que se ignora. Este es el
  argumento fuerte de V3 frente a V2 (que sobre la misma inyeccion rechaza en el
  protocolo clasico).
- **Fail-closed**: en C3, `fragment_ids` inexistentes (`f-900/f-901`) se **rechazan**
  (invalid_fragment_rate C3 = 0.333, que corresponde al caso disenado); JSON hostil
  rechazado.
- Granularidad: la evidencia reconstruida es la **frase entera** (o union de frases),
  mas gruesa que un span ajustado; para atribucion fina eso puede sobre-extender. Es
  el precio de garantizar literalidad sin offsets del modelo.
- Determinismo 1.0; network_attempts 0; write_attempts 0.

## Veredicto V3 (independiente)
La via mas robusta del protocolo: maximo recall (0.963), literalidad 1.0 e inmunidad
efectiva a inyeccion en la evidencia, a cambio de evidencia mas gruesa (frase). El
juez real (NVIDIA) debe confirmar que el modelo elige bien los IDs; el banco sintetico
solo demuestra que el MECANISMO es correcto y seguro.
