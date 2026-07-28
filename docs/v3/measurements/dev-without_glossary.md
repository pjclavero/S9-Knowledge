# Benchmark S9-Knowledge V3 — split `dev`

- corrida: `dev-without_glossary`
- subsistema declarado: `e2e`
- ablacion: `without_glossary` — Sin glosario ni alias del perfil.
- emparejamiento: span `exact`, umbral 0.5, clave de claim + []

| Métrica | Valor |
|---|---:|
| Extractor · menciones P | 0.0000 |
| Extractor · menciones R | 0.0000 |
| Extractor · menciones F1 | 0.0000 |
| Extractor · tipo (sobre emparejadas) | n/d |
| Extractor · tipo (sobre gold entero) | 0.0000 |
| Extractor · correferencia F1 | n/d |
| Extractor · claims P | n/d |
| Extractor · claims R | 0.0000 |
| Extractor · claims F1 | n/d |
| Extractor · trampas pisadas | 0 |
| Extractor · trampas del split | 4 |
| Extractor · trampas pisadas (tasa) | 0.0000 |
| Extractor · candidatos falsos (diluible) | n/d |
| Extractor · claims sin anclar en episodio con trampa | 0 |
| Resolutor · grupos emparejados | 0 |
| Resolutor · grupos gold | 31 |
| Resolutor · cobertura de grupos | 0.0000 |
| Resolutor · exactitud de identidad | 0.0000 |
| Resolutor · duplicados | n/d |
| Resolutor · fusiones indebidas | n/d |
| Resolutor · accion correcta (emparejados) | n/d |
| Resolutor · accion correcta (gold entero) | 0.0000 |

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
