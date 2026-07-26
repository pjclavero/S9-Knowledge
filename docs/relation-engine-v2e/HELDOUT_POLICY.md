# Política del corpus HELD-OUT del motor de relaciones

**Programa:** Motor V2 temporal, episódico y trazable · **Bloque 0.2 (paralelo a B0)**
**Rama:** `work/rel-v2e-b02-heldout` · **Base:** `origin/main` = `8fc7c8d`
**Corpus que regula:** `data-engine/app/tests/data/relation_heldout/` (H1, v1.0.0)
**Arnés:** `data-engine/app/relations/benchmark/` — **el único**. No se crea ningún otro.

---

## 0. Por qué existe este documento

El motor v2 mide **`predicate_correct` = 0.8140** sobre el corpus B1, pero ese corpus tiene
**n=54 y dev == test**: no hay conjunto reservado. Una ablación demostró que **~70 % de la
ganancia inicial era sobreajuste al corpus** (0.907 → 0.814 tras purgar expresiones calcadas),
y el informe de resultados fija el rango honesto en **[0.42, 0.81]** sin saber en qué punto
cae de verdad (`docs/relation-engine-v2-results.md` §8.1, §8.2 y dictamen del supervisor).

Un held-out sólo vale si **nadie lo usa para mejorar el motor**. Un corpus reservado que se
consulta al depurar deja de ser reservado en la primera consulta, y a partir de ahí sus cifras
son tan optimistas como las de dev. Este documento define, de forma **auditable**, cómo se
mantiene esa separación y **cómo se demuestra** que se ha mantenido.

---

## 1. Las reglas, una por línea

| # | Regla | Cómo se comprueba |
|---|---|---|
| R1 | Existen **tres conjuntos disjuntos**: **desarrollo** (B1), **validación** (aún no creado) y **held-out final** (H1). | `manifest.workspaces` disjuntos + test de disyunción |
| R2 | El held-out **NO se usa para escribir reglas, expresiones, listas léxicas, umbrales ni prompts**. | Auditoría de diff: ningún módulo del motor puede citar entidades de H1 |
| R3 | El held-out **NO se lee "para entender un fallo"**. Si un fallo hay que estudiarlo, se reproduce en dev o en un caso nuevo inventado. | Declaración en `SEAL.json` + revisión del PR |
| R4 | El held-out **sólo se ejecuta en los checkpoints declarados** (§4) y en el benchmark final. | `SEAL.json.executions` |
| R5 | **Prohibido modificar el held-out después de verlo.** Ni una coma, ni un `expected_decision`, ni una nota. | Los `sha256` del manifiesto y de `SEAL.json` deben coincidir |
| R6 | **Prohibido “arreglar” un caso porque el motor debería acertarlo.** Ese impulso es exactamente lo que la política existe para bloquear. | Igual que R5: cualquier retoque mueve un hash |
| R7 | El corpus **se sella antes** de la primera medición y el sello registra **quién, cuándo y con qué `code_sha`** se ejecutó. | `SEAL.json` + test `test_seal_matches_manifest` |
| R8 | Las cifras del held-out **se publican tal como salen**, incluidas las malas, y **sin suavizar**. | `HELDOUT_BASELINE_H1.md` |
| R9 | **Un solo arnés.** El held-out se corre con `relations/benchmark/` vía `--corpus-dir`. Está prohibido crear un segundo runner, un segundo emparejador o un segundo juego de métricas. | El corpus no contiene código de medición |
| R10 | El corpus **B1 no se toca**. El held-out **añade**, nunca sustituye. | `git diff` sobre `tests/data/relation_benchmark/` debe ser vacío |
| R11 | Ninguna ejecución del held-out abre **red**, ni usa **proveedores** (Ollama/NVIDIA), ni escribe en **Neo4j**. | `provider_status = NOT_EXECUTED` en cada informe |
| R12 | Si alguien **mira el held-out fuera de un checkpoint**, se declara **QUEMADO** y se regenera (§5). | Procedimiento de quemado |
| R13 | Al repositorio **nunca** sube material real: ni PDFs, ni audio, ni vídeo, ni transcripciones de partidas. Sólo métricas, hashes, estadísticas agregadas y **casos sintéticos inspirados**. | §7, revisión del PR y `.gitignore` del manifiesto local |
| R14 | Toda cifra del held-out se acompaña de **n** y de las filas **inacertables por construcción** (§6). | Tablas del informe |
| R15 | El held-out **no define umbrales de gate**. Los gates del arnés son los de B1; si un gate falla en held-out, se reporta, **no se rebaja**. | Diff de `report.py` vacío |

---

## 2. Separación desarrollo / validación / held-out

| Conjunto | Ubicación | n | Para qué SÍ | Para qué NO |
|---|---|--:|---|---|
| **Desarrollo (B1)** | `tests/data/relation_benchmark/` | 54 rel · 16 fuentes | Escribir reglas, ajustar expresiones, depurar, iterar libremente | Estimar rendimiento en producción |
| **Validación** | *pendiente de crear* | — | Elegir entre variantes ya construidas; ajuste de umbrales | Escribir reglas nuevas |
| **Held-out final (H1)** | `tests/data/relation_heldout/` | 45 rel · 30 fuentes · 24 casos | **Sólo medir**, en checkpoints | Absolutamente todo lo demás |

**Disyunción demostrada, no prometida.** `tests/test_relation_heldout_corpus.py` comprueba que
entre B1 y H1 **no comparten ni un identificador de entidad, ni un texto de mención, ni un
token de nombre de más de 3 caracteres, ni un workspace**. B1 vive en `eldoria`/`umbral`/
`nova-frontier`; H1 vive en `ferrovia`/`mareas`/`orbita`.

**Independencia de redacción.** Las fuentes de H1 se escribieron **sin consultar** las listas
`active_expressions` / `passive_expressions` de `relations/ontology.py` ni el selector v2,
precisamente para no reproducir las expresiones que el motor ya conoce. Es la contrapartida
directa del sobreajuste que destapó la ablación de B2.

---

## 3. Sellado: cómo se demuestra que no ha habido contaminación

El sellado es **hash-first**: no se pide confianza, se comprueba.

1. `manifest.json` fija, por fuente, `sha256`, `bytes` y `chars`, y además el `sha256` del
   ground truth y del índice de casos.
2. `SEAL.json` **congela** esos mismos hashes junto con la fecha de sellado, el `code_sha` del
   motor en el momento de medir y el registro de **todas** las ejecuciones.
3. `tests/test_relation_heldout_corpus.py` recalcula los hashes y exige que
   **corpus == manifiesto == sello**. Si alguien cambia un byte de una fuente, el test se pone
   rojo y el PR no pasa.
4. Cada informe del arnés incluye `corpus.ground_truth_sha256` y `corpus_hashes`: una cifra
   publicada queda **atada** al corpus exacto con el que se obtuvo.
5. El generador `tools/build_heldout_corpus.py` es determinista: regenerarlo debe reproducir
   **los mismos hashes**. Si no los reproduce, el corpus ha cambiado.

**Sello vigente (H1 v1.0.0):**

- `manifest.json` → `2a39448adbfe4a1cc12241bbb41be02b7c0046cb0bfbf8c60a77dde0c3ce3da0`
- `ground_truth/relations.json` → ver `SEAL.json.ground_truth_sha256`
- 30 fuentes, 45 relaciones, 24 casos.

**Lo que el sello prueba y lo que no.** Prueba **integridad** (el corpus no cambió) y
**trazabilidad** (qué código lo midió). **No** prueba autenticidad criptográfica frente a un
adversario con permiso de escritura en la rama: quien pueda reescribir el corpus puede
reescribir el sello. Contra eso protege la **revisión del PR** y el historial de git, no el
hash. Se dice aquí para no vender una garantía que el mecanismo no da.

---

## 4. Checkpoints: los únicos momentos en que se ejecuta

| Checkpoint | Cuándo | Qué se corre | Quién autoriza |
|---|---|---|---|
| **CP-0** | Al sellar el corpus, **antes** de tocar el motor | 4 perfiles (`baseline1`/`ensemble_offline` × selector `v1`/`v2`), proveedores desactivados | Responsable del held-out |
| **CP-1** | Al cerrar la mitad del programa | Los mismos 4 perfiles | Organizador del programa |
| **CP-2** | Benchmark final, antes de cualquier dictamen de producción | Los mismos 4 perfiles | Supervisor |

Reglas del checkpoint:

- Se ejecuta **entero** o no se ejecuta: nada de "correr sólo la fuente que falla".
- El resultado se publica **completo**, con las métricas malas incluidas.
- Entre checkpoints, **nadie abre los ficheros del corpus**. Ni para leer, ni para "comprobar
  una cosa".
- Cada ejecución **añade una entrada** a `SEAL.json.executions`. Un informe sin entrada en el
  sello es un informe no autorizado.
- **CP-0 ya se ejecutó** (2026-07-26, `code_sha` `8fc7c8d…`): resultados en
  `HELDOUT_BASELINE_H1.md`. El corpus **no se modificó** después de ver esas cifras.

---

## 5. Qué hacer si alguien lo mira por error

No hay sanción ni discusión: hay **procedimiento**. Mirarlo por error es un accidente barato;
ocultarlo es lo que invalida el programa.

1. **Declararlo en voz alta**, el mismo día, en el informe del bloque en curso.
2. **Marcar el corpus como QUEMADO**: añadir `"burned": true` y el motivo a `SEAL.json`. A
   partir de ese momento, **ninguna cifra obtenida con él puede citarse como held-out**; pasa
   a ser, como mucho, un segundo conjunto de desarrollo.
3. **Regenerar** un corpus nuevo (H2) con **entidades y expresiones distintas**, misma
   cobertura de casos, y **volver a sellarlo**. El corpus quemado se conserva en el repo con la
   marca, no se borra: borrarlo destruiría la trazabilidad de la contaminación.
4. **Re-medir desde cero** el checkpoint afectado sobre H2.
5. Si lo que se miró fue **una sola fuente**, sigue quemándose el corpus **entero**: no se sabe
   qué recuerda quien lo miró, y el coste de regenerarlo es mucho menor que el de publicar una
   cifra contaminada.

Casos que **cuentan** como "mirarlo": abrir un `.txt` del corpus para depurar, leer el ground
truth para entender un fallo, inspeccionar el JSONL de predicciones del held-out con el texto a
la vista, o pedirle a un agente que "mire por qué falla ese caso".

Casos que **no** cuentan: leer este documento, leer el `README.md` del corpus, leer las tablas
agregadas del informe, o ejecutar el arnés en un checkpoint autorizado sin abrir las fuentes.

---

## 6. Filas inacertables por construcción (honestidad de las métricas)

El corpus contiene 4 filas cuyo predicado **no puede acertarse nunca**, y es intencionado:

| Centinela | Filas | Qué mide |
|---|--:|---|
| `NO_RELATION` | 3 | Ruido: el par coexiste en el texto pero **no hay relación**. La decisión esperada es `REJECT`. Ningún predicado es correcto. |
| `SPONSORS` | 1 | Predicado **fuera de la ontología** del motor. Mide **cobertura**, no habilidad. |

Regla **R14**: toda cifra de `predicate_correct` del held-out se publica **dos veces** — sobre
el corpus completo y excluyendo estas filas — para que nadie pueda acusar al corpus de bajar la
nota con trampas, ni usar la exclusión para inflarla.

**Limitación conocida del arnés, declarada aquí porque afecta al diseño del corpus:** el runner
deriva las entidades de entrada **de las menciones del ground truth**
(`benchmark/runner.py::derive_entities`). Una fuente **sin ninguna relación anotada** no
produce entidades y, por tanto, el pipeline no ve nada: sería una prueba vacua. Por eso el ruido
se codifica como filas `NO_RELATION` dentro de fuentes que sí tienen entidades, en lugar de como
fuentes vacías. Es una restricción del arnés existente, no una elección estética, y se documenta
para que nadie la lea como una concesión al motor.

---

## 7. Incorporación de material REAL (preparado, **NO ejecutado**)

Existe material real en **Nextcloud (vm100, `192.168.1.200`, `/mnt/ncdata`)**: PDFs de **varios
juegos de rol** y **vídeos de partidas con réplica en YouTube**. Este bloque **no tiene acceso a
esa máquina y no ha intentado conectarse**. Lo que sigue es el camino dejado listo.

### 7.1. Restricción legal y de privacidad — **INNEGOCIABLE**

- Los **manuales de rol tienen derechos de autor**. Las **grabaciones de partidas son datos
  personales** (voces de personas identificables, conversación privada).
- **JAMÁS se sube al repositorio de GitHub** ni un PDF, ni un audio, ni un vídeo, ni una
  transcripción de partida real, ni un fragmento literal de manual — tampoco "sólo un párrafo
  para el test".
- Al repo suben **exclusivamente**: (a) **métricas derivadas**, (b) **hashes**, (c)
  **estadísticas agregadas** y (d) **casos sintéticos inspirados** en los patrones observados,
  reescritos con entidades inventadas.
- Un caso sintético inspirado es **legítimo** si conserva el *patrón lingüístico* (voz pasiva,
  rumor, salto temporal…) y **no conserva** ni el texto, ni los nombres propios, ni la trama
  reconocible del original. Si al leerlo se identifica la obra o la partida, **no vale**.
- Los datos personales de las grabaciones no se procesan más allá de lo necesario para la
  medición, y las transcripciones derivadas heredan la misma prohibición que el audio.

### 7.2. Fuera del repo, pero **reproducible**

El corpus real vive **sólo en local/Nextcloud** y se referencia por manifiesto:

```
<HELDOUT_REAL_ROOT>/            # ruta LOCAL, nunca en git, fijada por variable de entorno
  manifest.local.json           # el ÚNICO artefacto que se replica (sin contenido)
  sources/                      # PDFs, audios, transcripciones — NO se copian al repo
  derived/                      # transcripciones y métricas intermedias — NO se copian
```

`manifest.local.json` contiene, por documento: `doc_id` estable, **ruta relativa** a
`HELDOUT_REAL_ROOT` (nunca absoluta), `sha256`, tamaño, tipo (`pdf` / `audio` / `video`),
juego de rol, idioma, duración o número de páginas, y — para los vídeos — el `video_id` de
YouTube de la réplica. Con ese manifiesto, cualquiera que tenga acceso legítimo al material
reconstruye el mismo conjunto y verifica que es **bit a bit el mismo** que se midió. Al repo se
sube, como mucho, un `manifest.local.EXAMPLE.json` con dos entradas ficticias que documente el
formato.

Reglas operativas: rutas relativas siempre; `HELDOUT_REAL_ROOT` por variable de entorno; el
manifiesto real y todo `sources/`, `derived/` quedan excluidos por `.gitignore`; y ninguna
herramienta del repo escribe dentro de `HELDOUT_REAL_ROOT`.

### 7.3. Ground truth gratis: YouTube como segunda opinión

Los vídeos de partidas **tienen réplica en YouTube**, así que la transcripción de YouTube sirve
de contraste para la nuestra. **Este trabajo ya está hecho y no se rehace**:
`docs/40-youtube-whisper-transcription-benchmark.md` (dictamen *APTA CON REVISIÓN DE
CONFLICTOS*). Lo que aporta y se reutiliza tal cual:

- Acuerdo token-level whisper↔YouTube-ASR de **0.887** en la ventana medida.
- **Limitación de referencia que hay que respetar:** los vídeos disponibles tenían subtítulos
  **auto-generados**, no manuales. YouTube-ASR es **una segunda opinión automática, no un
  ground truth humano**; sin referencia humana **no hay WER verdadero**. Cualquier informe que
  presente la transcripción de YouTube como "verdad" estará usando mal docs/40.
- **Detector de segmentos conflictivos** (umbral 0.6): 91 % `AUTO_ACCEPT`, 7 %
  `REVIEW_CONFLICT`, 2 % `REJECT_SEGMENT`. Los conflictos **concentran los errores de nombre
  propio**, que son justamente los que rompen la extracción de relaciones.
- **Política de fuente** (docs/40 §8): subtítulos manuales → texto principal; sólo auto →
  whisper como principal y YouTube-ASR como segunda opinión; conflicto → **sólo los segmentos
  conflictivos** a revisión humana.

### 7.4. Procedimiento (7 pasos, ninguno ejecutado en este bloque)

1. **Inventario, sin copiar nada.** Listar el material accesible en Nextcloud y escribir
   `manifest.local.json` (hashes + metadatos). Se anota **qué juego de rol** es cada PDF: la
   diversidad de sistemas es parte del valor, porque cada manual tiene su jerga relacional.
2. **Autorización explícita del operador**, por escrito, para tocar vm100. Sin ella, el paso 1
   no empieza.
3. **Transcripción** de los vídeos con el pipeline ya validado (faster-whisper `medium`) y
   descarga de los subtítulos de YouTube de la réplica; comparación con el detector de
   conflictos de docs/40. Todo ello **dentro de `HELDOUT_REAL_ROOT`**.
4. **Anotación humana** de relaciones sobre una muestra pequeña y **acotada** (orientación:
   60–100 relaciones), priorizando los segmentos `AUTO_ACCEPT` y revisando a mano los
   `REVIEW_CONFLICT`. La anotación se guarda **fuera del repo**, con el mismo esquema de
   `ground_truth/relations.json`.
5. **Medición** con el arnés único, apuntando `--corpus-dir` al corpus local. Sale un JSON de
   métricas; **al repo sube el JSON de métricas y los hashes, nunca el corpus**.
6. **Destilación a casos sintéticos.** De cada patrón que el motor falle se escribe un caso
   **inventado** que lo reproduce, y ése sí entra en el repo — en un corpus H2 nuevo, **nunca**
   modificando H1 (regla R5).
7. **Cierre:** informe con métricas reales agregadas + hashes + los casos sintéticos derivados.
   El material original **se queda donde estaba**.

**Lo que este bloque NO ha hecho y no debe darse por hecho:** no se ha accedido a vm100, no se
ha transcrito nada, no se ha anotado material real, y no hay ni una cifra de rendimiento sobre
material real. Todo §7 es **plan**, no resultado.

---

## 8. Qué invalidaría esta política

Se dice explícitamente para que sea falsable:

- Que un módulo del motor mencione una entidad de `ferrovia`/`mareas`/`orbita`.
- Que un commit modifique un fichero de `tests/data/relation_heldout/` sin subir la versión del
  corpus y sin actualizar `SEAL.json`.
- Que aparezca una cifra de held-out en un informe sin su entrada correspondiente en
  `SEAL.json.executions`.
- Que se ejecute el held-out con proveedores reales sin la doble llave del arnés.
- Que un fichero de material real (PDF, audio, vídeo, transcripción) llegue al repositorio.
