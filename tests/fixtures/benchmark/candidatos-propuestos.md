# Tabla de candidatos — Corpus benchmark Prioridad 2

Generado por: auto-agent-A-2026-07-14  
Annotation pass: 1 (pendiente revisión humana)

---

## Fuentes del corpus

| ID | Tipo | Origen | Tamaño aprox | Contenido esperado | Riesgo privacidad | Motivo inclusión |
|---|---|---|---|---|---|---|
| source_transcript_clean_01 | transcript_session | repo/existente | ~185 tokens | 6 Characters, 2 Locations, 2 Factions, 2 Objects | NINGUNO — fixture público | Línea base limpia; nombres propios compuestos bien formados; calibración del extractor heurístico |
| source_transcript_session_02 | transcript_session | repo/existente | ~155 tokens | 5 Characters (incl. criaturas), 4 Locations, 2 Factions, 1 Object | NINGUNO — fixture público | Introduce tipos menos frecuentes (criaturas, Espíritu); object compartido cross-session (máscara rota) |
| source_transcript_asr_01 | transcript_session | sintético/benchmark | ~165 tokens | 5 Characters (formas erróneas), 4 Locations, 2 Factions, 1 Object + 3 negativos esperados | NINGUNO — inventado | Test de robustez ASR; errores fonéticos sistemáticos; falsos positivos esperados (Llevás, Todo, Como) |
| source_notes_01 | session_notes | sintético/benchmark | ~105 tokens | 5 Characters (2 solo por alias), 3 Locations, 1 Faction, 2 Objects | NINGUNO — inventado | Test de alias implícitos; formato abreviado de notas; relaciones no explícitas |
| source_resolution_01 | transcript_session | sintético/benchmark | ~145 tokens | 7 Characters (1 near-dup), 2 Locations, 2 Factions | NINGUNO — inventado | Test de resolución y deduplicación; near-duplicate Kakita Asuko; alias explícito resuelto en texto |

---

## Entidades esperadas por fuente

| ID fuente | Entidades esperadas | Negativas explícitas | Ambiguas | Casos resolución |
|---|---|---|---|---|
| source_transcript_clean_01 | 12 (6 Chr, 2 Loc, 2 Fac, 2 Obj) | 5 | 1 | 0 |
| source_transcript_session_02 | 12 (5 Chr, 4 Loc, 2 Fac, 1 Obj) | 3 | 2 | 0 |
| source_transcript_asr_01 | 11 (5 Chr, 4 Loc, 1 Fac, 1 Obj) | 7 (incl. 4 formas erróneas ASR) | 2 | 0 |
| source_notes_01 | 11 (5 Chr, 3 Loc, 1 Fac, 2 Obj) | 5 | 1 | 3 (2 aliases, 1 descriptor) |
| source_resolution_01 | 10 (5 Chr, 2 Loc, 2 Fac + 1 Chr near-dup) | 3 | 1 | 3 (1 alias, 1 near-dup, 1 apellido) |

**Total corpus: 56 entidades esperadas (distintas), 23 negativas, 7 ambiguas, 6 casos de resolución**

---

## Relaciones esperadas por fuente

| ID fuente | Relaciones esperadas (true) | Relaciones negativas (false) |
|---|---|---|
| source_transcript_clean_01 | 4 (MEMBER_OF ×3, KNOWS ×1) | 2 |
| source_transcript_session_02 | 4 (FOUGHT_AT, MEMBER_OF, HAS_FOUGHT, KNOWS) | 2 |
| source_transcript_asr_01 | 0 | 2 |
| source_notes_01 | 3 (KNOWS ×2, MEMBER_OF ×1) | 1 |
| source_resolution_01 | 5 (MEMBER_OF ×2, KNOWS ×3) | 2 |

---

## Decisiones de anotación no obvias

1. **Árbol Blanco del Vacío como Location**: Clasificado como Location aunque "Vacío" es un concepto metafísico en L5A. El criterio es el uso geográfico en el texto ("cerca del Árbol Blanco del Vacío"). Marcado como ambiguo para revisión.

2. **Espíritu del Río como Character, no Concept**: Tiene agencia activa (habla, ayuda al grupo). El criterio es la agencia narrativa, no la naturaleza ontológica.

3. **Oni de la Montaña Negra como Character**: El esquema L5A no tiene tipo "Criatura". Se mapea a Character porque el extractor LLM usa Character para entidades con agencia. El heurístico no tiene tipo Criatura.

4. **Kakita Asuko como entidad independiente**: NO se fusiona con Kakita Asuka aunque difieren en un carácter. El benchmark castiga la auto-fusión sin evidencia. La resolución correcta es proponer para revisión humana.

5. **Objetos sin mayúscula (máscara rota, segundo fragmento)**: Incluidos como entidades esperadas aunque el extractor heurístico no los capturará (regex exige inicial mayúscula). Esto mide la ventaja del LLM sobre el heurístico en objetos no capitalizados.

6. **Relaciones negativas source_transcript_asr_01 = 0 positivas**: En un texto con errores ASR, las relaciones son difíciles de extraer con los patrones del heurístico (que espera formas correctas de verbos). Se incluyeron solo 2 relaciones negativas para documentar casos de sobre-extracción esperados.

7. **PARTICIPATED_IN con Location marcado como false**: La relación `Kakita Asuka PARTICIPATED_IN Ciudad Moto` es semánticamente inválida en el esquema (PARTICIPATED_IN aplica a Events). Se documenta como caso negativo para calibrar el validador de tipos.

---

## Pendiente de revisión humana

- [ ] Confirmar clasificación de "Árbol Blanco del Vacío" (Location vs Concept)
- [ ] Confirmar que "Espíritu del Río" es Character y no Concept
- [ ] Confirmar que "Culto del Pozo Viejo" es Faction y no Concept
- [ ] Validar que "Kakita Asuko" no debe auto-resolverse en ningún caso
- [ ] Revisar si "Templo sur" (source_notes_01) merece entidad ambigua o negativa
- [ ] Confirmar tokens aproximados (estimados, no contados con tokenizador real)
