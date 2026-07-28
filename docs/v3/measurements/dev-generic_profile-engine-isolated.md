# Benchmark S9-Knowledge V3 — split `dev`

- corrida: `dev-generic_profile`
- subsistema declarado: `e2e`
- ablacion: `generic_profile` — Perfil de juego correcto ('generic').
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
| Resolutor · grupos emparejados | 0 |
| Resolutor · grupos gold | 31 |
| Resolutor · cobertura de grupos | 0.0000 |
| Resolutor · exactitud de identidad | 0.0000 |
| Resolutor · duplicados | n/d |
| Resolutor · fusiones indebidas | n/d |
| Resolutor · accion correcta (emparejados) | n/d |
| Resolutor · accion correcta (gold entero) | 0.0000 |
| Motor · decisiones emparejadas | 21 |
| Motor · decisiones gold | 21 |
| Motor · cobertura de decisiones | 1.0000 |
| Motor · decision (emparejadas) | 0.6667 |
| Motor · decision (gold entero) | 0.6667 |
| Motor · predicado F1 (emparejadas) | 0.9143 |
| Motor · predicado F1 (gold entero) | 0.9143 |
| Motor · direccion F1 (emparejadas) | 0.9143 |
| Motor · direccion F1 (gold entero) | 0.9143 |
| Motor · epistemico F1 (emparejadas) | 0.9000 |
| Motor · epistemico F1 (gold entero) | 0.9000 |
| Motor · negacion P (emparejadas) | 1.0000 |
| Motor · negacion R (emparejadas) | 1.0000 |
| Motor · negacion F1 (gold entero) | 1.0000 |
| Motor · temporalidad | 0.2000 |
| Motor · aprobacion falsa | 0.0909 |
| Motor · rechazo falso | 0.0000 |
| Motor · abstencion | 0.0476 |
| E2E · hechos P | 1.0000 |
| E2E · hechos R | 0.6250 |
| E2E · hechos F1 | 0.7692 |
| E2E · procedencia completa | 1.0000 |
| E2E · hechos duplicados | 0.0000 |
| E2E · planes aprobados en falso | 0.2500 |

## Secciones no evaluadas

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
