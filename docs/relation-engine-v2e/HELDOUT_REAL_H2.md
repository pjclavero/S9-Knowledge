# Held-out H2 — el motor sobre MATERIAL REAL

**Fecha:** 2026-07-27 · **Rama:** `work/rel-v2e-b02-heldout`
**Arnés:** `data-engine/app/relations/benchmark/` (el único) · **Corpus:** `tests/data/relation_heldout_h2` (H2 v1.0.0)
**Perfiles:** `baseline1` y `ensemble_offline` × selector de predicado `v1` y `v2`
**Proveedores:** `local=NOT_EXECUTED`, `external=NOT_EXECUTED`, **0 llamadas** · sin red, sin Neo4j, sin ingesta
**Determinismo:** `deterministic=True` en los 4 perfiles · **Contaminación de workspace:** 0
**Umbrales, arnés y métricas: SIN TOCAR.** B1 y H1 **no** se han modificado (sus tests siguen en verde).

> El corpus se selló **antes** de la primera ejecución y **no se ha cambiado después de ver estos
> números** (`SEAL.json`). Método de muestreo, semilla y política legal: `relation_heldout_h2/README.md`.

---

## 1. Resumen en tres frases

1. **`predicate_correct` cae a 0.2391** en material real (0.8140 en B1, 0.5385 en H1). Sobre texto
   que el motor no vio nunca, escrito por otros y de otros sistemas de juego, **el motor acierta el
   predicado una de cada cuatro veces**.
2. **`temporal_correct` se hunde a 0.1957** (0.8837 en B1). La temporalidad **no generaliza en
   absoluto** al lenguaje descriptivo de un manual.
3. **La propiedad de seguridad se rompe por primera vez:** `ensemble_offline` + `v2` produce
   **2 falsos ACCEPT** sobre relaciones que el ground truth **rechaza**. En B1 y en H1 eran **0**.

**El arnés, con sus propios umbrales, falla tres gates y emite el veredicto
`APTO CON REVISIÓN HUMANA TOTAL` en los cuatro perfiles.**

---

## 2. Tabla completa — B1 / H1 / H2, carril del dictamen (`baseline1`)

| Métrica | B1 v1 | B1 **v2** | H1 v1 | H1 **v2** | H2 v1 | H2 **v2** | Δ v2: H2 − B1 |
|---|--:|--:|--:|--:|--:|--:|--:|
| `predicate_correct` | 0.2093 | **0.8140** | 0.1538 | **0.5385** | 0.1957 | **0.2391** | **−0.5749** |
| `strict_predicate.f1` | 0.1698 | **0.6604** | 0.1304 | **0.4565** | 0.1552 | **0.1897** | **−0.4707** |
| `temporal_correct` | 0.4419 | **0.8837** | 0.4103 | **0.5641** | 0.0870 | **0.1957** | **−0.6880** |
| `direction_correct` | 0.6279 | **0.9302** | 0.8462 | **0.8974** | 0.7609 | **0.6957** | **−0.2345** |
| `evidence_correct` | 0.9070 | 0.9302 | 0.8718 | 0.8462 | 0.7174 | **0.7174** | −0.2128 |
| `offsets_correct` | 0.9302 | 0.9535 | 1.0000 | 1.0000 | 1.0000 | **1.0000** | **+0.0465** |
| `types_correct` | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | **1.0000** | 0.0000 |
| `workspace_correct` | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | **1.0000** | 0.0000 |
| `epistemic_correct` | 0.8605 | 0.8605 | 0.8974 | 0.8974 | 0.8043 | **0.8043** | −0.0562 |
| `negation_correct` | 0.9070 | 0.8837 | 0.8974 | 0.8974 | 0.6957 | **0.6957** | −0.1880 |
| `decision_correct` | 0.3023 | 0.3488 | 0.3590 | 0.2564 | 0.4783 | **0.3261** | −0.0227 |
| `global_existence.f1` (**pair_F1**) | 0.8113 | 0.8113 | 0.8478 | 0.8478 | 0.7931 | **0.7931** | −0.0182 |
| `global_existence` P / R | 0.827 / 0.796 | — | 0.830 / 0.867 | — | 0.719 / 0.885 | **0.719 / 0.885** | — |
| TP / FP / FN | 43 / 9 / 11 | — | 39 / 8 / 6 | — | 46 / 18 / 6 | **46 / 18 / 6** | — |
| **Falsos ACCEPT** (GT `REJECT` → `ACCEPT`) | **4** | **0** | **6** | **0** | **0** | **0** | 0 |
| Falsos ACCEPT en sentido amplio (`REJECT`/`REVIEW` → `ACCEPT`) | 8 | **0** | 11 | **0** | 6 | **1** | **+1** |
| n emparejadas (denominador estructural) | 43 | 43 | 39 | 39 | 46 | 46 | — |
| Relaciones de ground truth | 54 | 54 | 45 | 45 | 52 | 52 | — |

## 3. Carril `ensemble_offline` — **aquí se rompe la seguridad**

| Métrica | B1 v2 | H1 v2 | **H2 v1** | **H2 v2** |
|---|--:|--:|--:|--:|
| `decision_correct` | 0.4651 | 0.3590 | 0.3261 | **0.3696** |
| **Falsos ACCEPT** (GT `REJECT` → `ACCEPT`) | **0** | **0** | **0** | **2** |
| Falsos ACCEPT en sentido amplio | 0 | 0 | 4 | **4** |
| Resto de métricas | = §2 | = §2 | = §2 | = §2 |

**Éste es el hallazgo más serio del bloque.** El «0 falsos ACCEPT» que B1 y H1 exhibían como la
propiedad que *sí* generalizaba **no sobrevive al material real**: con el consenso recalibrado, el
motor **acepta automáticamente 2 de las 3 relaciones centinela** que el ground truth marca como
inexistentes (coocurrencias en texto de reglas y en habla). Sobre 52 relaciones es una tasa
pequeña, pero **la afirmación «no afirma lo que no debe» queda refutada**: era una propiedad del
corpus sintético, no del motor.

## 4. Desglose por material — **la transcripción NO es el caso más duro**

`baseline1`, selector `v2`, subconjuntos por workspace (`run_benchmark(source_ids=…)`):

| Subconjunto | n GT | n empar. | `predicate` | `temporal` | `direction` | `evidence` | `decision` | pair_F1 | strict_F1 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **H2 completo** | 52 | 46 | **0.2391** | 0.1957 | 0.6957 | 0.7174 | 0.3261 | 0.7931 | 0.1897 |
| Sólo libros | 41 | 37 | **0.1892** | 0.1892 | 0.7027 | 0.7297 | 0.2703 | 0.8132 | 0.1538 |
| — Trudvang | 24 | 21 | 0.2381 | 0.2381 | 0.6667 | 0.7619 | 0.0952 | 0.7778 | 0.1852 |
| — Vampiro V20 | 17 | 16 | **0.1250** | 0.1250 | 0.7500 | 0.6875 | 0.5000 | 0.8649 | 0.1081 |
| **Transcripción** | 11 | 9 | **0.4444** | 0.2222 | 0.6667 | 0.6667 | 0.5556 | 0.7200 | 0.3200 |
| Sin centinelas de ruido | 49 | 43 | 0.2558 | 0.2093 | 0.6744 | 0.6977 | 0.3488 | 0.7818 | 0.2000 |

**Yo esperaba que el habla sin puntuación fuera el peor caso y me equivoqué.** La transcripción
puntúa **más alto** en predicado (0.4444) que cualquiera de los libros. La explicación no es que el
motor entienda el habla, sino que **las pocas relaciones anotables de una sesión de juego son
casi todas `MEMBER_OF` y `LOCATED_IN`** —«los magistrados del clan Grulla», «la habitación de
Daiki»— que son justamente las dos familias que el motor resuelve. Los manuales, en cambio, están
llenos de `ALLIED_WITH`, `ALIAS_OF`, `PARENT_OF`, `MENTOR_OF` y `CAUSED`, que el motor no acierta
**nunca** (§6).

**Aviso de tamaño:** n = 9 emparejadas en la transcripción. Una relación cambia la cifra 11 puntos.
**Esta fila no soporta ninguna conclusión fuerte**; se publica porque el encargo la pedía aparte.

## 5. Gates del arnés — umbrales SIN TOCAR, los mismos de B1

| Gate | Umbral | B1 v2 | H1 v2 | **H2 v2** |
|---|--:|--:|--:|--:|
| `predicate_structural` | ≥ 0.50 | 0.8140 ✅ | 0.5385 ✅ | **0.2391 ❌** |
| `temporality` | ≥ 0.60 | 0.9600 ✅ | 0.7200 ✅ | **0.2593 ❌** |
| `evidence` | ≥ 0.80 | 0.9302 ✅ | 0.8462 ✅ | **0.7174 ⚠️ PARTIAL** |
| `offsets` | ≥ 0.90 | 0.9535 ✅ | 1.0000 ✅ | **1.0000 ✅** |
| `negation` | ≥ 0.80 | 1.0000 ✅ | 1.0000 ✅ | **0.0000 ❌** (n = 1) |
| `rumors` | ≥ 0.60 | 1.0000 ✅ | 0.0000 ❌ | **1.0000 ✅** (n = 2) |
| `simple_relations` | ≥ 0.80 | 0.9333 ✅ | 0.9565 ✅ | **0.6897 ⚠️ PARTIAL** |
| `determinism` / `workspace_contamination` | duro | ✅ | ✅ | **✅** |

**Veredicto del arnés en H2: `APTO CON REVISIÓN HUMANA TOTAL`** en los cuatro perfiles (B1 v2 daba
`APTO PARA CONTINUAR EN MODO SOMBRA`; H1 v2, `APTO CON REVISIÓN DE CASOS CONFLICTIVOS`). La
degradación del veredicto es progresiva y la produce el corpus, no un cambio de umbral.

`negation` y `rumors` tienen n = 1 y n = 2. **No sostienen nada**, ni el fallo ni el acierto.

## 6. Acierto por predicado (`baseline1` v2) — dónde exactamente falla

| Predicado del GT | soporte | par detectado | **predicado exacto** |
|---|--:|--:|--:|
| `PARTICIPATED_IN` | 3 | 3 | **3 (1.00)** |
| `LOCATED_IN` | 4 | 4 | **3 (0.75)** |
| `OWNS` | 4 | 4 | **2 (0.50)** |
| `MEMBER_OF` | 15 | 14 | **3 (0.20)** |
| `ALIAS_OF` | 2 | 1 | **0** |
| `ALLIED_WITH` | 3 | 0 | **0** |
| `CAUSED` | 1 | 1 | **0** |
| `CREATED` | 2 | 2 | **0** |
| `ENEMY_OF` | 4 | 3 | **0** |
| `LEADS` | 3 | 3 | **0** |
| `LIVES_IN` | 3 | 3 | **0** |
| `MENTOR_OF` | 2 | 2 | **0** |
| `PARENT_OF` | 3 | 3 | **0** |
| `NO_RELATION` *(centinela)* | 3 | 3 *(= FP correctos de detectar)* | **0** |

**Nueve de catorce familias de predicado obtienen cero.** El motor **encuentra el par** casi
siempre (46 de 52; recall de existencia 0.885) y luego **no sabe qué es**. Las tres simétricas
(`ALLIED_WITH` 0/3 pares detectados) son las peores: en material real ni siquiera se detecta el par.

`MEMBER_OF` merece una nota: es el predicado más frecuente del corpus (15 de 52) y el motor lo
**emite** mucho, pero sólo acierta 3. Lo que pasa es que emite `MEMBER_OF` donde el GT dice otra
cosa y `RELATED_TO` donde el GT dice `MEMBER_OF`.

## 7. Métricas que no necesitan ground truth

Todas con `baseline1`, 36 documentos, 11 076 caracteres, 92 entidades derivadas.

| Medida | v1 | **v2** |
|---|--:|--:|
| Pares potenciales | 80 | 80 |
| Pares generados | 64 | 64 |
| Pares descartados por el filtro de contexto | 16 (20 %) | 16 (20 %) |
| Candidatos evaluados | 64 | 64 |
| **Predicados distintos emitidos** | **5** | **8** |
| Resultados `strong` (auto-aceptables) | **0** | **0** |
| Resultados `partial` | 29 (45 %) | 13 (20 %) |
| Resultados `human` (a revisión) | 16 (25 %) | **32 (50 %)** |
| Resultados `conflict` | 19 (30 %) | 19 (30 %) |
| `invalid` / errores / timeouts | 0 | 0 |
| **Tasa de abstención de ACCEPT** (`strong` = 0) | **100 %** | **100 %** |

**Distribución de predicados emitidos (v2):** `RELATED_TO` **26** · `LOCATED_IN` 14 · `MEMBER_OF` 8 ·
`OWNS` 6 · `PARTICIPATED_IN` 5 · `FOUNDED` 3 · `CAUSED` 1 · `MENTOR_OF` 1.
**El 41 % de las salidas del motor es el comodín `RELATED_TO`**: en material real, el selector v2
no colapsa en `LOCATED_IN` como v1 (28 de 64), pero colapsa en «no sé». En H1 emitía 11 predicados
distintos; aquí, 8.

**Literalidad de la evidencia.** `offsets_correct = 1.0000` (46/46): **cuando el motor cita, cita
bien**; los offsets apuntan exactamente al texto, incluso en un fragmento con artefactos de PDF.
Pero `evidence_correct = 0.7174`: en el 28 % de los casos **el span citado no es el que justifica
la relación**. Trazabilidad mecánica perfecta, pertinencia mediocre.

**Unicode:** 182 caracteres no ASCII en el corpus (`í`, `ó`, `á`, `é`, `ú`, `ñ`, `¿`, `…`, `“`, `”`)
y ni un solo fallo de offset. **Nada casca con Unicode.**

**Texto de dos horas — prueba de carga.** La transcripción **completa** (85 718 caracteres,
16 084 palabras, 1 813 líneas) como **un único documento y un único segmento**:
`segments_failed = 0`, `errors = 0`, `timeouts = 0`, **482 ms**, y el offset de una evidencia
situada en el carácter 16 068 sale **exacto**. **El motor no se rompe con un texto de dos horas.**
Lo que no se puede afirmar es que escale: con sólo 2 entidades derivadas hubo 1 par. La explosión
de pares real de una sesión de dos horas depende del extractor de entidades, que **no** se ha
medido aquí (§9).

## 8. Lectura honesta: ¿cuánto generaliza el motor a material real?

**Poco. Bastante menos de lo que H1 ya avisaba.**

1. **El 0.8140 de B1 estaba inflado en +0.57 absolutos**, no en +0.27. La cadena
   B1 0.8140 → H1 0.5385 → H2 **0.2391** es monótona y cada escalón añade *una* cosa: H1 añade
   entidades y expresiones nuevas; H2 añade **prosa de verdad, escrita por otra gente, de otros
   sistemas, con artefactos de extracción y habla espontánea**. El rango honesto declarado
   `[0.42, 0.81]` **no contiene el resultado real: 0.24 está por debajo del suelo del rango.**
2. **Lo que generaliza es la parte mecánica, no la semántica.** Tipos 1.0000, workspaces 1.0000,
   offsets 1.0000, determinismo, cero contaminación, cero errores: perfecto en los tres corpus.
   Predicado, temporalidad y dirección: se caen. El motor es un **localizador de pares fiable con
   un clasificador de relaciones que no funciona fuera de casa**.
3. **La temporalidad es lo peor y hay que dejar de publicar el 0.8837.** 0.1957 en material real.
   El lenguaje de manual (presente atemporal, «estaban», «han sido durante mucho tiempo») no se
   parece a nada de lo que `temporal_v2` aprendió. **No es un ajuste: es que no está resuelto.**
4. **La seguridad ya no es incondicional.** Dos falsos ACCEPT en `ensemble_offline` + v2. La
   recomendación operativa que salía de B1/H1 —«seguro en modo sombra»— **sólo se sostiene con
   `baseline1`**; con el consenso recalibrado, no.
5. **La ontología es parte del problema, no sólo el motor.** Tres relaciones del corpus real hubo
   que anotarlas con el predicado *más cercano* porque el correcto no existe («Abrazar» de V20,
   «entregarse a una fe», «maestro de bestias»). Un motor perfecto seguiría fallándolas. Ampliar
   la ontología no es cosmética: es un requisito para medir bien material real.
6. **Y aun así el motor v2 sigue siendo mejor que v1** en material real: 0.2391 vs 0.1957 de
   predicado y 0.1897 vs 0.1552 de strict F1. La mejora es **real y minúscula**: +0.043. De la
   ganancia v1→v2 que B1 mostraba (+0.6047) **sobrevive el 7 %**. En H1 sobrevivía el 64 %.

**Traducción operativa, sin adornos: con estas cifras el motor no puede proponer relaciones a
producción, ni siquiera con revisión por muestreo.** Emite 0 resultados `strong` sobre 64
candidatos: la revisión humana sería del 100 % y acertaría 1 de cada 4 predicados. Como
**detector de pares candidatos con evidencia trazable** para que un humano decida, sí sirve:
recall de existencia 0.885 y offsets exactos.

## 9. Qué NO se ha podido medir

- **Nada con proveedores reales.** `NOT_EXECUTED`, 0 llamadas, sin doble llave ni autorización.
- **El extractor de entidades.** El arnés **deriva** las entidades del ground truth por diseño. Por
  tanto **no se ha medido la explosión de pares real** sobre un documento largo, ni cuántas
  entidades espurias produciría un NER sobre 2 horas de habla. La cifra de 80 pares potenciales es
  del corpus, no del mundo.
- **La calidad del ground truth de H2.** Anotación de **un solo pase**, un anotador, sin medida de
  acuerdo. Con 17 relaciones marcadas `REVIEW` por ambigüedad genuina, **una segunda anotación
  movería estas cifras** — probablemente en ambos sentidos. Es la limitación metodológica más seria
  y no está en una nota al pie.
- **`negation` (n = 1), `rumors` (n = 2), `INTENDED` (n = 1)**: se publican porque el arnés los
  computa; **no significan nada** con esos tamaños.
- **Comparación con spaCy/Stanza o cualquier línea base externa:** no instaladas, no se descarga nada.
- **Si el corpus es representativo del material completo.** 36 fragmentos de 881 páginas y 2 horas.
  El muestreo es reproducible y no está sesgado por el léxico del motor (README §2), pero
  **es una muestra pequeña** y las cifras por workspace (n = 9 a 21) tienen intervalos amplios que
  no se han calculado.
- **Neo4j, ingesta, despliegue:** fuera de alcance por prohibición explícita. Nada se ha escrito.

## 10. Reproducción

```bash
cd data-engine/app
for mode in baseline1 ensemble_offline; do
  for sel in v1 v2; do
    python3 -m relations.benchmark.cli --mode "$mode" --predicate-selector "$sel" \
      --corpus-dir tests/data/relation_heldout_h2 --out-json "/tmp/h2_${mode}_${sel}.json"
  done
done
python3 -m pytest tests/test_relation_heldout_h2_corpus.py -q   # sellado y politica legal
```

Los subconjuntos de §4 se obtienen con `run_benchmark(corpus, source_ids=[…])` filtrando por
`workspace` del manifiesto. La comparación de transcripción está en
`TRANSCRIPTION_H2_YOUTUBE.md`.
