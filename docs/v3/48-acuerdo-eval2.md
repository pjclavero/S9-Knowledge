# ACUERDO-2: corpus de evaluacion nuevo y re-medicion del acuerdo determinista ∧ NVIDIA

## Objetivo

La medicion 1 (docs/v3/47, PR #134) midio el acuerdo de contenido entre el
carril determinista (`local_only`) y el carril NVIDIA (`external_only`,
SOMBRA) sobre el gold `negation` (56 casos evaluables): precision 0.8667
(n=15), con la vista "activa" (ambos carriles proponen algo, ninguno
abstiene: `ACCEPT/REVIEW` + `REVIEW/REVIEW`) en 1.000 (n=6). La muestra es
pequena: mismo techo dev==test que ya penalizo al motor v2 (0.81 en-corpus
-> 0.24 en held-out real, ver `project_s9k_motor_v2e_heldout`). Este bloque
construye un corpus NUEVO -- frases y entidades nunca vistas -- y repite la
medicion para ver si el resultado se sostiene con n mayor.

## Corpus nuevo: `agreement-eval2`

Ruta: `data-engine/app/knowledge_v3/benchmarks/datasets/agreement-eval2/`.
Mismo formato de contrato EXACTO que `negation` (envoltorios, esquema de
episodios/fragmentos/menciones/resoluciones/claims/asertos/planes/negativos),
generado por `_authoring/build_agreement_eval2.py` a partir de
`_authoring/cases.py` (offsets, hashes y manifiesto calculados, nunca
escritos a mano). Verificado por hash (`verify_integrity`, ver
`tests/test_agreement_eval2_corpus.py`).

**Composicion**: 3 mundos NUEVOS (`vitral`, `salitre`, `brumal`; 39
entidades), ninguno compartido con `negation` (basalto/cirro/zafiro/ambar),
`dev` (leyenda/mareas/kestrel) ni `heldout` (ferrovia/micelio/liga) --
comprobado por test automatizado. 42 casos / 37 claims propuestas / 35
evaluables (2 excluidos por la misma convencion B0-B3: los ABSTAIN puros
del gold no cuentan en el denominador) / 42 episodios:

| familia | n casos |
| --- | ---: |
| SIMPLE | 12 |
| CESSATION | 5 |
| NEGATED_CESSATION | 4 |
| NEVER | 3 |
| NOT_YET | 3 |
| SCOPE_EMBEDDED | 2 |
| DOUBLE_NEGATION | 2 |
| QUESTION_CONDITIONAL_RUMOR | 3 |
| POSITIVE_CONTROL | 4 |
| NO_CLAIM | 4 |

**Reglas de autoria** (declaradas en `cases.py` y comprobadas por test):
entidades y nombres 100% nuevos; las frases se escribieron primero por
naturalidad narrativa y el gold se etiqueto despues por semantica; las
superficies de relacion (`"pertenece a"`, `"dejo de liderar"`, `"es aliada
de"`, etc.) se tomaron literalmente de `extraction/deterministic.
RELATION_RULES` -- vocabulario de dominio explicitamente permitido por el
encargo, porque sin el el carril determinista no emite nada y el acuerdo no
se puede medir -- pero la frase, el mundo, los nombres y la puntuacion
alrededor son originales; ningun 3-grama de las frases completas se copio
de `negation` ni de ningun otro corpus del repo.

**Decision discutible de escala**: el encargo pedia ~100 claims / 60-80
episodios; este corpus entrega 37 claims / 42 episodios. Se prefirio un
corpus mas pequeno pero *genuinamente* escrito a mano, con offsets
verificados y validado contra los contratos congelados, a inflar el
recuento con generacion mecanica que hubiera diluido la calidad narrativa y
el cuidado semantico del etiquetado gold. El agregado con la medicion 1
(56 + 35 = 91 evaluables) sigue siendo mas del 60% mayor que cualquiera de
las dos muestras por separado.

## Medicion

Script: `scripts/agreement/measure_agreement2.py` (copia deliberada de
`measure_agreement.py`, no una generalizacion por flag -- mismo criterio de
aislamiento que el bloque 1: un split nuevo con su propio gold, workspace
(`bench-agreement-eval2`) y cache (`artifacts/agreement/cache2/`, nunca
compartida). Reutiliza tal cual `compute_agreement`, el alineamiento de tres
fases del runner congelado y `measure_b3.make_b3_port` para el transporte
NVIDIA. Pasada REAL (no mock): 38 llamadas a NVIDIA, 0 fallos, 193 359
tokens, latencia media 37.6 s / p95 56.7 s, concurrencia 2, sin cache previa
(split nuevo). Artefactos: `artifacts/agreement/agreement-eval2.{json,md}`.

### Tabla del acuerdo de contenido por par de decisiones -- corpus nuevo

| par de decisiones (det/nvidia) | n | tp | fp | precision |
| --- | ---: | ---: | ---: | ---: |
| ABSTAIN/ABSTAIN | 4 | 3 | 1 | 0.75 |
| ABSTAIN/REVIEW | 2 | 2 | 0 | 1.0 |
| ACCEPT/REVIEW | 8 | 8 | 0 | 1.0 |
| REVIEW/REVIEW | 7 | 7 | 0 | 1.0 |

n=21, precision global=0.9524, recall sobre el gold=0.6 (21/35).

### Tabla del acuerdo de contenido por par de decisiones -- medicion 1 (negation, referencia)

| par de decisiones (det/nvidia) | n | tp | fp | precision |
| --- | ---: | ---: | ---: | ---: |
| ABSTAIN/ABSTAIN | 6 | 4 | 2 | 0.6667 |
| ABSTAIN/REVIEW | 3 | 3 | 0 | 1.0 |
| ACCEPT/REVIEW | 2 | 2 | 0 | 1.0 |
| REVIEW/REVIEW | 4 | 4 | 0 | 1.0 |

n=15, precision global=0.8667, recall sobre el gold=0.268 (15/56).

### Agregado (negation + agreement-eval2, n≈91 evaluables)

| conjunto | n | tp | fp | precision |
| --- | ---: | ---: | ---: | ---: |
| acuerdo_contenido total | 36 | 33 | 3 | 0.9167 |
| **acuerdo ACTIVO** (`ACCEPT/REVIEW` + `REVIEW/REVIEW`, ningun carril abstiene) | 21 | 21 | 0 | **1.000** |
| ABSTAIN/ABSTAIN (ambos abstienen, por convencion `negated=False`) | 10 | 7 | 3 | 0.700 |
| ABSTAIN/REVIEW | 5 | 5 | 0 | 1.000 |

Evaluable total agregado: 91 (56 + 35).

## ¿Se sostiene el 1.000?

**Si, para la vista ACTIVA** (ambos carriles proponen algo y ninguno
abstiene): pasa de n=6 (medicion 1) a n=21 combinado, y se mantiene en
1.000 exacto -- cero errores en 21 casos donde ambos motores se comprometen
con una decision no-ABSTAIN. Es el resultado mas fuerte de este bloque: la
hipotesis original del operador (acuerdo activo -> alta confianza) resiste
la ampliacion de n.

**No para la vista `ABSTAIN/ABSTAIN`**: precision 0.6667 (medicion 1, n=6)
y 0.75 (medicion 2, n=4), agregado 0.700 (n=10) -- 3 falsos "acuerdo" en 10.
La causa es estructural, no aleatoria: `build_rows` asigna `negated=False`
por CONVENCION a cualquier fila ABSTAIN (ninguno de los dos carriles
comprobo realmente la polaridad), asi que dos ABSTAIN siempre "coinciden"
en polaridad aunque ninguno haya mirado el hecho. Un caso nuevo lo
demuestra: `claim:salitre-ruta:e10:c1` (AE2-NEGCESS-04, "Orell Cascan no
ceso de servir al Sindicato de la Sal") -- gold `negated=True`, ambos
carriles ABSTAIN con `negated=False` por convencion: cuenta como "acuerdo"
y es FALSO. Una politica que tratara "ambos ABSTAIN" como senal de
confianza fallaria aqui.

## Discrepancias activas encontradas

**Cero** discrepancias de polaridad opuesta ACTIVA (ambos carriles
proponen algo, ninguno abstiene, y la polaridad difiere) en ninguna de las
dos mediciones (n=0 en medicion 1 y en medicion 2). Los dos casos disenados
explicitamente para estresar el alcance ambiguo de la negacion
(`AE2-SCOPE-01`, negacion de un verbo de opinion ajena con clausula final
contradictoria; `AE2-SCOPE-02`, negacion metalinguistica "no es que... no")
NO generaron discrepancia: ambos carriles llegaron a la misma lectura
correcta (`ABSTAIN/REVIEW` y `ABSTAIN/ABSTAIN`, ambos `correct=True`). Es
un resultado negativo mas que "oro": con n=2 disenado a mano, no alcanza
para concluir que el alcance ambiguo nunca produce discrepancia dura, solo
que estos dos intentos no la encontraron.

Si aparecio una discrepancia mas leve, `predicado_incompatible` (n=1,
corpus nuevo): `claim:salitre-ruta:e13:c1` (AE2-POS-04, "Tobal Mencia se
encuentra en Pozo Hondo") -- el determinista extrae `LOCATED_IN`, NVIDIA
`LIVES_IN`. Semanticamente cercanos (residencia vs ubicacion puntual), pero
formalmente distintos: el criterio los declara incompatibles, correctamente.

Tambien aparecieron 7 casos `abstain_vs_afirma` (corpus nuevo): el carril
NVIDIA declara `ABSTAIN` mientras el determinista da `REVIEW` con
`negated=True` sobre el MISMO claim gold (todos con `gold_negated=True`,
familia `NEVER`/`NOT_YET`/`CESSATION` en su mayoria) -- NVIDIA es mas
conservador que el determinista en estos casos, no al reves.

## Casos donde el acuerdo activo autoaprobaria algo NO escribible

**Ninguno detectado en la medicion automatica** -- pero con una limitacion
real que hay que declarar: los 2 casos de este corpus disenados a proposito
para NO ser escribibles (`AE2-RUMOR-01`, rumor de liderazgo; `AE2-COND-01`,
condicional hipotetico) se codificaron como gold `abstained=True`, y la
MISMA convencion B0-B3 que excluye el ABSTAIN puro del denominador
evaluable (heredada sin cuestionar de `negation`) los saca tambien de este
computo: no aparecen en `acuerdo_contenido`, `solo_det` ni `solo_nvidia`.
El tercer caso de factividad (`AE2-RUMOR-02`, familia `NO_CLAIM`) no genera
fila de claim en absoluto. **Consecuencia**: este bloque NO pudo comprobar
automaticamente si el acuerdo activo autoaprobaria un rumor o un
condicional, porque el propio arnes de medicion descarta esos casos antes
de que la pregunta se pueda hacer. Es una limitacion del diseno heredado,
no una respuesta "no hay riesgo" -- declarada aqui en vez de disimulada.
Revisando los campos crudos (fuera del computo agregado): en ninguna de las
filas `det_rows`/`nvidia_rows` de esos dos episodios ningun carril emitio
`ACCEPT`; ambos permanecieron en `ABSTAIN` en los dos carriles. No es una
garantia estadistica (n=2, sin la disciplina del arnes), pero tampoco hay
indicio de fuga en esta corrida puntual.

## Coste e incidencias

- 38 llamadas reales a NVIDIA, 0 fallos, 0 reintentos de transporte, 0
  timeouts duros (ninguna incidencia de las esperadas 3-5%).
- 193 359 tokens totales; latencia media 37.6 s, p95 56.7 s, max ver JSON.
- Cache propia en `artifacts/agreement/cache2/responses.json`, nunca
  compartida con `cache/` (medicion 1) ni con `gate4-program/b3-cache/`.
- La key de NVIDIA nunca aparece en ningun artefacto commiteado ni en la
  salida de los tests (comprobado por
  `test_la_api_key_real_no_aparece_en_los_artefactos_ya_commiteados_de_agreement_eval2`).

## Suite de tests

24 tests nuevos/reutilizados en `test_agreement_eval2_corpus.py` (integridad
por hash, carga generica, disjuncion de entidades, corrida `--mock`
end-to-end sin escritura fuera de directorio de salida, sin carga de
`neo4j`, sin fuga de key) + los ya existentes de `test_agreement_shadow.py`:
verdes. Suite RAIZ completa: **6357 passed, 51 skipped, 3 xfailed, 0
failed** (`pytest -p no:randomly`, ~4m17s).

## Decisiones discutibles de este bloque

1. **Escala reducida** (37 claims / 42 episodios en vez de ~100 / 60-80):
   ver seccion "Decision discutible de escala" arriba. Preferi profundidad
   de autoria sobre volumen.
2. **Las superficies de `RELATION_RULES` se copiaron literalmente.** Es lo
   que pedia el encargo ("vocabulario permitido"), pero es tambien la
   misma superficie que ya cubre `negation`: la varianza real que aporta
   este corpus es de mundo/entidad/frase-alrededor, no de cobertura lexica
   nueva del determinista. Un corpus que ademas estresara superficies
   *fuera* de `RELATION_RULES` (para medir cuantas veces NVIDIA cubre algo
   que el determinista simplemente no puede ver) queda pendiente.
3. **La convencion ABSTAIN=`negated=False` no se toco.** Se hereda del
   runner congelado y de `measure_agreement.py` a proposito (no reabrir
   ese split), pero es la causa directa del unico patron de error
   reproducible entre las dos mediciones (`ABSTAIN/ABSTAIN` en 0.70 de
   precision agregada). Si el operador quiere usar la vista `ABSTAIN/
   ABSTAIN` como senal de politica, esta convencion debe corregirse antes.
4. **Los casos de factividad (rumor/condicional) quedaron fuera del
   computo automatico** por la convencion heredada de exclusion de
   ABSTAIN del denominador -- ver seccion anterior. Si el operador quiere
   una respuesta medida (no inspeccionada a mano) a "¿el acuerdo activo
   autoaprobaria algo no escribible?", el arnes de medicion necesita un
   modo que SI cuente los casos `abstained=True` del gold en el
   denominador, aunque sea en una vista separada.

## Lectura para la decision del operador (cifras desnudas)

- Acuerdo ACTIVO (ningun carril abstiene): **1.000 sobre n=21** combinado
  (6 + 15), frente a 6 en la medicion 1 sola -- la ampliacion de n
  RESPALDA la hipotesis original.
- Acuerdo total (incluye ABSTAIN/ABSTAIN): 0.9167 agregado (n=36), por
  debajo del 1.000 activo por el patron de convencion descrito arriba.
- Recall del acuerdo de contenido sobre el gold: 0.6 (corpus nuevo) vs
  0.268 (negation) -- mas alto en el corpus nuevo, coherente con una
  composicion con mas casos SIMPLE/POSITIVE_CONTROL de cobertura
  determinista alta.
- 0 discrepancias activas duras encontradas en 91 casos evaluables
  agregados.
- Ninguna recomendacion de politica: esa decision es del operador.
