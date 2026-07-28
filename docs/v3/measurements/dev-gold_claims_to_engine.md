# Benchmark S9-Knowledge V3 — split `dev`

- corrida: `dev-gold_claims_to_engine`
- subsistema declarado: `e2e`
- ablacion: `gold_claims_to_engine` — El motor recibe los claims GOLD. Aisla el motor de los errores del extractor.
- emparejamiento: span `exact`, umbral 0.5, clave de claim + []

| Métrica | Valor |
|---|---:|
| Extractor · menciones P | 0.9048 |
| Extractor · menciones R | 0.7451 |
| Extractor · menciones F1 | 0.8172 |
| Extractor · tipo (sobre emparejadas) | 0.9737 |
| Extractor · tipo (sobre gold entero) | 0.7255 |
| Extractor · correferencia F1 | 0.6667 |
| Extractor · claims P | 0.0476 |
| Extractor · claims R | 0.0500 |
| Extractor · claims F1 | 0.0488 |
| Extractor · trampas pisadas | 0 |
| Extractor · trampas del split | 4 |
| Extractor · trampas pisadas (tasa) | 0.0000 |
| Extractor · candidatos falsos (diluible) | 0.0000 |
| Extractor · claims sin anclar en episodio con trampa | 0 |
| Resolutor · grupos emparejados | 13 |
| Resolutor · grupos gold | 31 |
| Resolutor · cobertura de grupos | 0.4194 |
| Resolutor · exactitud de identidad | 0.7255 |
| Resolutor · duplicados | 0.0000 |
| Resolutor · fusiones indebidas | 0.0000 |
| Resolutor · accion correcta (emparejados) | 0.9231 |
| Resolutor · accion correcta (gold entero) | 0.3871 |
| Motor · decisiones emparejadas | 21 |
| Motor · decisiones gold | 21 |
| Motor · cobertura de decisiones | 1.0000 |
| Motor · decision (emparejadas) | 0.1905 |
| Motor · decision (gold entero) | 0.1905 |
| Motor · predicado F1 (emparejadas) | 0.8889 |
| Motor · predicado F1 (gold entero) | 0.8889 |
| Motor · direccion F1 (emparejadas) | 0.8889 |
| Motor · direccion F1 (gold entero) | 0.8889 |
| Motor · epistemico F1 (emparejadas) | 0.8500 |
| Motor · epistemico F1 (gold entero) | 0.8500 |
| Motor · negacion P (emparejadas) | 1.0000 |
| Motor · negacion R (emparejadas) | 1.0000 |
| Motor · negacion F1 (gold entero) | 1.0000 |
| Motor · temporalidad | n/d |
| Motor · aprobacion falsa | n/d |
| Motor · rechazo falso | 0.0000 |
| Motor · abstencion | 0.0476 |

## Secciones no evaluadas

- `e2e`: la prediccion no trae afirmaciones
- `normalizer`: la prediccion no trae episodios

## Gold utilizado

| Elemento | Nº |
|---|---:|
| sources | 6 |
| episodes | 16 |
| fragments | 72 |
| mentions | 51 |
| resolutions | 31 |
| claims | 21 |
| assertions | 16 |
| decisions | 21 |
| plans | 6 |
| negatives | 4 |
| entities | 20 |
