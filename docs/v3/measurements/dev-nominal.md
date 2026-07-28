# Benchmark S9-Knowledge V3 — split `dev`

- corrida: `dev-nominal`
- subsistema declarado: `e2e`
- ablacion: `nominal` — Corrida de referencia: todo real, perfil correcto, con glosario.
- emparejamiento: span `exact`, umbral 0.5, clave de claim + []

| Métrica | Valor |
|---|---:|
| Extractor · menciones P | 0.5571 |
| Extractor · menciones R | 0.7647 |
| Extractor · menciones F1 | 0.6446 |
| Extractor · tipo (sobre emparejadas) | 0.9744 |
| Extractor · tipo (sobre gold entero) | 0.7451 |
| Extractor · correferencia F1 | 0.5714 |
| Extractor · claims P | 0.0000 |
| Extractor · claims R | 0.0000 |
| Extractor · claims F1 | 0.0000 |
| Extractor · trampas pisadas | 0 |
| Extractor · trampas del split | 4 |
| Extractor · trampas pisadas (tasa) | 0.0000 |
| Extractor · candidatos falsos (diluible) | 0.0000 |
| Extractor · claims sin anclar en episodio con trampa | 0 |
| Resolutor · grupos emparejados | 13 |
| Resolutor · grupos gold | 31 |
| Resolutor · cobertura de grupos | 0.4194 |
| Resolutor · exactitud de identidad | 0.7255 |
| Resolutor · duplicados | 0.0588 |
| Resolutor · fusiones indebidas | 0.0000 |
| Resolutor · accion correcta (emparejados) | 0.9231 |
| Resolutor · accion correcta (gold entero) | 0.3871 |
| Motor · decisiones emparejadas | 0 |
| Motor · decisiones gold | 21 |
| Motor · cobertura de decisiones | 0.0000 |
| Motor · decision (emparejadas) | n/d |
| Motor · decision (gold entero) | 0.0000 |
| Motor · predicado F1 (emparejadas) | n/d |
| Motor · predicado F1 (gold entero) | n/d |
| Motor · direccion F1 (emparejadas) | n/d |
| Motor · direccion F1 (gold entero) | n/d |
| Motor · epistemico F1 (emparejadas) | n/d |
| Motor · epistemico F1 (gold entero) | 0.0000 |
| Motor · negacion P (emparejadas) | n/d |
| Motor · negacion R (emparejadas) | n/d |
| Motor · negacion F1 (gold entero) | n/d |
| Motor · temporalidad | n/d |
| Motor · aprobacion falsa | n/d |
| Motor · rechazo falso | n/d |
| Motor · abstencion | n/d |

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
