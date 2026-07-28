# Benchmark S9-Knowledge V3 — split `dev`

- corrida: `dev-nominal`
- subsistema declarado: `e2e`
- ablacion: `nominal` — Corrida de referencia: todo real, perfil correcto, con glosario.
- emparejamiento: span `exact`, umbral 0.5, clave de claim + []

| Métrica | Valor |
|---|---:|
| Extractor · menciones P | 0.9048 |
| Extractor · menciones R | 0.7451 |
| Extractor · menciones F1 | 0.8172 |
| Extractor · tipo (sobre emparejadas) | 0.9737 |
| Extractor · tipo (sobre gold entero) | 0.7255 |
| Extractor · correferencia F1 | 0.6667 |
| Extractor · claims P | n/d |
| Extractor · claims R | 0.0000 |
| Extractor · claims F1 | n/d |
| Extractor · trampas pisadas | 0 |
| Extractor · trampas del split | 4 |
| Extractor · trampas pisadas (tasa) | 0.0000 |
| Extractor · candidatos falsos (diluible) | n/d |
| Extractor · claims sin anclar en episodio con trampa | 0 |
| Resolutor · grupos emparejados | 13 |
| Resolutor · grupos gold | 31 |
| Resolutor · cobertura de grupos | 0.4194 |
| Resolutor · exactitud de identidad | 0.7255 |
| Resolutor · duplicados | 0.0000 |
| Resolutor · fusiones indebidas | 0.0000 |
| Resolutor · accion correcta (emparejados) | 0.9231 |
| Resolutor · accion correcta (gold entero) | 0.3871 |

## Secciones no evaluadas

- `e2e`: la prediccion no trae afirmaciones
- `engine`: la prediccion no trae decisiones del motor (ni sueltas ni en plan)
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
