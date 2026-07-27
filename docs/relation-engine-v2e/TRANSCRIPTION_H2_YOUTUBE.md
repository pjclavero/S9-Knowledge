# Transcripción H2 — faster-whisper `small` frente a los subtítulos de YouTube

**Fecha:** 2026-07-27 · **Vídeo:** `m_MVcTx8P9s` — «La Leyenda de los cinco Anillos — El Castillo
Esmeralda (8/14) | Fantasy Flight Games (FFG)», 7 273 s (2 h 01 min 13 s)
**Nuestra transcripción:** `faster-whisper`, modelo **`small`**, `es`, 1 813 líneas con marcas
`[HH:MM:SS]`, 16 084 palabras
**Segunda opinión:** subtítulos **auto-generados** de YouTube (`yt-dlp --write-auto-sub
--skip-download`), pista `es`, 2 518 cues deduplicados, 15 937 palabras
**Red:** usada **exclusivamente** para descargar esos subtítulos, con autorización explícita del
operador. Ningún proveedor de IA. Nada nuestro se ha subido a ninguna parte.
**Al repositorio:** métricas, hashes y **citas cortas**. Ni el audio, ni el vídeo, ni ninguna de las
dos transcripciones completas.

---

## 0. ENCUADRE — léase antes que cualquier número

**Los subtítulos de YouTube NO son ground truth.** Son la salida de **otro sistema automático de
reconocimiento de voz**, con sus propios errores. Este documento compara **dos ASR entre sí**.

Consecuencias, que gobiernan todo lo que sigue:

- **No hay WER ni CER verdaderos** aquí. Lo que se publica es una **tasa de discrepancia** con la
  forma de un WER, tomando YouTube como referencia **no verdadera**. La cifra mide *desacuerdo*, no
  *error*.
- **Donde los dos discrepan, la conclusión es «aquí hace falta oído humano»**, jamás «YouTube
  acierta». En §4 hay un ejemplo donde el acierto es nuestro y otro donde es de YouTube.
- Esto **reutiliza y confirma** el trabajo previo `docs/40-youtube-whisper-transcription-benchmark.md`
  (dictamen **`APTA CON REVISIÓN DE CONFLICTOS`**, ~91 % de segmentos auto-aceptables y ~7 % de
  conflictos con modelo **`medium`** sobre una ventana de 10 min). No se rehace: se extiende a
  **`small`** y a **las 2 horas completas**.

---

## 1. Resultado agregado

| Medida | Valor |
|---|--:|
| Palabras (nuestra `small`) | 16 084 |
| Palabras (YouTube ASR) | 15 937 |
| Palabras coincidentes (alineado por ventanas de 60 s) | 12 759 |
| Sustituciones / inserciones / borrados | 2 853 / 1 092 / 964 |
| **Tasa de discrepancia de palabra** (forma de WER, referencia no verdadera) | **0.3080** |
| **Acuerdo global de palabra** | **0.7969** |
| **Acuerdo de carácter** | **0.8840** |
| Discrepancia de carácter (forma de CER) | 0.1154 |
| Acuerdo medio por ventana de 60 s | 0.7834 (mediana 0.8058) |

### Comparación por ventanas de 60 s (122 ventanas)

| Con el umbral de `docs/40` (acuerdo ≥ 0.60) | Ventanas | % | `docs/40` (`medium`, 10 min) |
|---|--:|--:|--:|
| Auto-aceptable | 116 | **95 %** | 91 % |
| **Conflicto (< 0.60) → revisión humana** | **6** | **5 %** | 9 % |

| Con un umbral más exigente (≥ 0.80) | Ventanas | % |
|---|--:|--:|
| Acuerdo alto | 68 | 56 % |
| Acuerdo medio (0.60–0.80) | 48 | 39 % |
| Conflicto (< 0.60) | 6 | 5 % |

Con el **mismo criterio** que `docs/40`, el resultado **reproduce su hallazgo** a lo largo de dos
horas enteras: ~95 % auto-aceptable, ~5 % en conflicto. Pero el acuerdo global de `small` es
**0.797** frente al **0.887** que `docs/40` midió con `medium`. **No es una comparación controlada**
(otro vídeo, 10 min frente a 121 min), así que **no demuestra** que `medium` sea 0.09 mejor; sí
apunta en esa dirección y no hay ningún dato que apunte en la contraria.

---

## 2. Hallazgo de cobertura: nos faltan los últimos 78 segundos

Nuestra transcripción termina en **7 195 s**. El vídeo dura **7 273 s** y los subtítulos de YouTube
llegan a 7 265 s. **Faltan ~78 s (1,1 %) del final**, y las dos ventanas de 60 s con acuerdo 0.000
de §3 son exactamente ésas: no son un desacuerdo, son **audio que no hemos transcrito**.

Lo que hay ahí, según YouTube, es el **cierre de la sesión** («aquí termina la sesión de hoy… con
esta invitación a té… empezamos la siguiente sesión…»), es decir **el resumen de continuidad entre
episodios**: justo el contenido con más valor para un grafo episódico.

**Esto es un fallo silencioso de nuestro pipeline de transcripción, no del modelo.** Ningún control
lo detectó. Un *quality gate* de cobertura (duración transcrita ÷ duración del audio ≥ 0.99) lo
habría capturado, y no existe.

---

## 3. Las 6 ventanas en conflicto

Ventanas nombradas `HH:MM` (minuto de inicio dentro del vídeo).

| Ventana | Acuerdo | Palabras nuestra / YouTube | Qué pasa |
|---|--:|--:|---|
| 02:00 – 02:01 | 0.000 | 0 / 184 | **no transcrito** (§2) |
| 02:01 – 02:02 | 0.000 | 0 / 20 | **no transcrito** (§2) |
| 01:11 | 0.502 | 112 / 111 | bucle de repetición nuestro (§4c) |
| 00:32 | 0.595 | 121 / 131 | nombres de personaje (§4a) |
| 00:50 | 0.595 | 94 / 74 | no inspeccionada al detalle |
| 00:47 | 0.598 | 179 / 152 | no inspeccionada al detalle |

---

## 4. Dónde discrepan, con las citas

**(a) 00:32 — el nombre de un personaje jugador.**

> nuestra: «…decirle algo a **Hanzo**? ¿**Hanzo**, tú quieres hacer algo cuando llegan tus dos
> compañeros? ¿Vosotros dos? **Daiki**, **Hasu**.»
> YouTube: «…queréis decirle algo a **hans o hans o** tú quieres hacer algo y cuando llegan sus dos
> compañeros… vosotros dos **daiki a su**…»

**Aquí acertamos nosotros y YouTube destroza el nombre.** «Hanzo» → «hans o»; «Hasu» → «a su».

**(b) 00:51 — terminología del sistema.** *(acuerdo 0.621: ventana de acuerdo medio, no de conflicto; se cita porque el modo de fallo es el mismo)*

> nuestra: «…es el primer ataque que hacen los **Mirumotos**…»
> YouTube: «…es el primer ataque que hace en **los minutos**…»

`Mirumoto` es una familia de L5A. **Acertamos nosotros**; YouTube produce una palabra común
plausible que un grafo ingeriría como ruido sin levantar ninguna alarma.

**(c) 01:11 — un bucle de repetición nuestro.**

> nuestra: «¿Qué hacéis? ¿Estáis ahí para os? Seguís para os ahí. **¿Qué hacéis? ¿Estáis ahí para
> os? Seguís para os ahí.**»
> YouTube: «qué hacéis **66 parados parados ahí** yo miro a 61 digo me prometiste algo»

**Aquí fallamos nosotros**: `small` entra en un bucle y **repite una frase entera** —el modo de
fallo clásico de Whisper—, además de convertir «Sé-Yuro» en «seis y juro». YouTube tampoco acierta
(«66», «61»), pero **no alucina texto duplicado**. Una repetición literal es peor para un grafo que
una palabra mal transcrita: **crea evidencia falsa que parece confirmación**.

### Nombres propios: el desacuerdo se concentra exactamente donde más duele

| Término | nuestra (`small`) | YouTube |
|---|--:|--:|
| **Hanzo** (PJ) | 24 | **0** |
| **Hasu** (PJ) | 35 | **0** |
| **Daiki** (PJ) | 38 | 19 |
| **Koharu** (PNJ) | 9 | **0** |
| **Doji Satsume** (trama) | 10 / 6 | **0 / 0** |
| Grulla (clan) | **0** (dice «gruya» ×4) | 4 |
| León (clan) | 16 | 17 |
| Esmeralda | 28 | 27 |
| clan / magistrado / escorpión | 18 / 16 / 8 | 18 / 14 / 8 |

**Los sustantivos comunes coinciden casi perfectamente. Los nombres propios no coinciden en
absoluto.** YouTube no produce **ni una sola vez** Hanzo, Hasu, Koharu, Doji ni Satsume (dice
«hanson» ×8, «asume» ×6, «daikin» ×5); nosotros no producimos «Grulla» ni una vez (decimos «gruya»).

Además, **nuestra propia transcripción no es internamente consistente**: la misma entidad aparece
como `daiki` (38) y `daiqui` (10), y como `hanzo` (24) y `hanso` (6). **Un extractor de entidades
crearía dos nodos distintos para la misma persona**, dentro del mismo documento. Eso ya se observa
en H2: `src-26` dice «clan gruya» y `src-28` dice «daiqui».

**Esto confirma, con dos horas en vez de diez minutos, el hallazgo clave de `docs/40`:** el acuerdo
global es alto y **los pocos conflictos concentran los errores de nombre propio**, que son
precisamente los que deforman un grafo de conocimiento.

---

## 5. ¿Basta el modelo `small`?

**No. Con los datos de aquí, `small` es insuficiente para ingesta y `medium` es el mínimo.**

| Evidencia | Dato |
|---|---|
| Acuerdo global `small` (2 h) | **0.7969** |
| Acuerdo global `medium` en `docs/40` (10 min, otro vídeo) | 0.887 |
| Bucles de repetición literal de `small` | detectados (§4c) |
| Cobertura del audio | **98,9 %**: 78 s finales sin transcribir |
| Nombres propios internamente inconsistentes | `daiki`/`daiqui`, `hanzo`/`hanso` |

Los dos primeros no son comparables de forma estricta y **así hay que citarlos**; los tres últimos
son fallos observados **directamente** en la salida de `small` y no dependen de ninguna comparación.

**Recomendación, con su coste.** `docs/40` §9 midió `medium` a **RTF 0.56** en VM105 (CPU): unas
**~67 min de proceso por vídeo de 2 h**. Es asumible por sesión y bajo demanda, no para la serie
entera de golpe. Lo que **no** es asumible es ingerir salida de `small` sin revisión.

**Lo que ni `small` ni `medium` arreglan:** ningún ASR va a acertar «Mirumoto», «Kakita Riko» o
«Doji Satsume» de forma fiable. La solución no es sólo un modelo mayor, sino
**`initial_prompt`/glosario del workspace + revisión humana de los segmentos en conflicto**, que es
exactamente la política de `docs/40` §8. Este trabajo la **refuerza** y le añade dos requisitos:

1. **Quality gate de cobertura** (duración transcrita ÷ duración del audio ≥ 0.99). Habría cazado
   §2. **Hoy no existe.**
2. **Detector de repeticiones literales** (n-gramas idénticos consecutivos). Habría cazado §4c.
   **Hoy no existe.**

---

## 6. Dictamen

```
Transcripción del Castillo Esmeralda 8/14 con faster-whisper `small`:
NO APTA PARA INGESTA. Reprocesar con `medium` + glosario, y aun asi
revisar a oido los segmentos en conflicto de nombre propio.

La transcripcion de YouTube NO es la alternativa: es peor en nombres
propios (0 de 5 nombres de personaje). Su valor es ser una SEGUNDA
OPINION que senala DONDE mirar, no QUE poner.
```

Coherente con `docs/40` §17 y con la memoria del proyecto: **la primera ingesta no debe hacerse con
una transcripción de vídeo**, y menos con ésta.

## 7. Qué NO se ha medido

- **WER y CER verdaderos.** Siguen sin existir: no hay referencia humana. Sigue pendiente la
  recomendación de `docs/40` §11 — **transcribir a mano 5–10 min** y calibrar contra eso. Es la
  única forma de saber cuál de los dos ASR acierta en cada conflicto.
- **`medium` o `large` sobre *este* vídeo.** No se han ejecutado: son ~67 min de CPU por pasada en
  VM105 y no se ha tocado VM105. La comparación `small` vs `medium` de §5 **cruza vídeos y
  ventanas** y así se declara.
- **El efecto real sobre el grafo.** H2 sólo contiene 11 relaciones de la transcripción; el impacto
  de los errores de nombre propio sobre la ingesta completa no está cuantificado.
- **Los subtítulos manuales.** No existen para este vídeo (sólo pista automática), igual que en
  `docs/40`.
- **Las otras 13 sesiones** de la serie y el resto de material de `leyenda`.

## 8. Reproducción

```bash
yt-dlp --skip-download --write-auto-sub --sub-lang 'es.*' --sub-format vtt \
       -o 'yt_%(id)s.%(ext)s' 'https://www.youtube.com/watch?v=m_MVcTx8P9s'
```

`sha256` del VTT descargado (pista `es`, 2026-07-27):
`5ccd45c1aa63bfd17d121ba5d9c86db32a0ffe77375441f555c705e9ad13da71`
*(el subtítulo automático puede regenerarse en el servidor; el hash sirve para saber si se comparó
la misma versión, no como sello de integridad de una fuente estable).*

Alineación por ventanas de 60 s, normalización a minúsculas sin diacríticos ni puntuación,
`difflib.SequenceMatcher` por ventana. El script vive fuera del repositorio porque consume la
transcripción completa, que no puede versionarse.
