# Encargo externo — carril de transcripción manuscrita y etiquetas de origen

Fecha: 2026-07-29 · Estado: **especificado, listo para implementar**
Destinatario: equipo externo (Codex u otro). Documento autocontenido.

> **Regla dura del programa, sin excepciones.**
> Una entrega sin tests **escritos Y EJECUTADOS** no se acepta, y no se revisa.
> Se entrega la salida real de la ejecución, con el número de tests, no una captura verde.

---

## 0. Por qué existe este encargo

El corpus real de este proyecto **no son libros**. Son notas de partida: manuscritas,
mezcladas con dibujos, esquemas y mapas en la misma página. Dos hechos medidos y un
hecho conocido:

1. **Tesseract no lee manuscrito.** Está entrenado en imprenta. Con letra a mano no
   da menos precisión: da basura. Para las notas del usuario **no es un plan B, no
   es una opción**.
2. **Los VLM sí transcriben, y rápido.** `llama-3.1-nemotron-nano-vl-8b-v1`
   transcribió una imagen de prueba en **1,1 s**, con un solo error de espaciado
   (`"esaliada"` por `"es aliada"`) sobre texto impreso limpio.
3. **Los VLM no dan posiciones fiables.** El mismo modelo, al pedirle bounding
   boxes, devolvió JSON impecable con coordenadas `y` de 109 y 159 **sobre una
   imagen de 90 px de alto**. La estructura era la pedida y los números estaban
   inventados.

Conclusión: el VLM entra en la cadena **como transcriptor**, no como OCR posicional.
Y nunca se le piden coordenadas.

---

## 1. Los tres carriles

| Carril | Proveedor | Anclaje de evidencia | Material |
|---|---|---|---|
| `OCR_TEXT` | Tesseract 5 + `spa` | bbox **medido** sobre la imagen | Impreso: libros, manuales, escaneos |
| `TRANSCRIBED_TEXT` | VLM | offsets **dentro de la transcripción** | Manuscrito y páginas mixtas |
| `VISUAL_INFERRED` | VLM | ninguno; descripción | Mapas, planos, ilustraciones |

**Este encargo implementa el carril intermedio.** Los otros dos ya existen.

El cambio conceptual, y es el punto que hay que entender antes de escribir código:
en `TRANSCRIBED_TEXT` **la transcripción pasa a ser el documento fuente**, con su
propio hash de contenido. Los offsets de las menciones son offsets sobre ese texto,
no sobre píxeles. Aguas abajo —episodios, extracción, resolución, motor, ledger,
writer— **no cambia absolutamente nada**. Si el implementador se ve tocando algo por
debajo de la normalización, se ha equivocado de sitio y debe parar y preguntar.

---

## 2. La cascada

```
imagen
  └─> VLM transcribe (lectura 1)
        └─> LLM revisa coherencia sobre el TEXTO (no ve la imagen)
              ├─ coherente Y sin tokens de riesgo ──────────> aceptar
              └─ incoherente O con tokens de riesgo
                    └─> VLM transcribe otra vez (lectura 2, modelo distinto)
                          └─> diff LITERAL determinista lectura 1 vs lectura 2
                                ├─ idénticas en el tramo ──> aceptar
                                └─ difieren ──────────────> marcar tramo a revisión
```

### 2.1 El disparador es doble, y esto es lo importante

Escalar **solo** por incoherencia es insuficiente, y por una razón concreta:

- Errores que **rompen la coherencia** (palabra emborronada, frase que no se
  sostiene): el LLM los caza bien. Baratos de detectar.
- Errores que **siguen siendo coherentes** (`Narek`→`Narok`, `1247`→`1241`, un
  nombre propio sustituido por otro parecido): el LLM **no los caza**, y en el peor
  caso los "corrige" hacia lo que espera. La frase se lee perfecta.

Y son justo los segundos los que importan: **nombres propios, números y fechas son
la carga útil** que acaba en el grafo. Los verbos y las preposiciones no.

Por eso se relee también todo tramo que contenga un **token de riesgo**:

- nombre propio (mayúscula inicial en posición no inicial de frase)
- número o fecha en cualquier formato
- término ausente del glosario

Sigue siendo una fracción pequeña de la página, así que el ahorro frente a releer
siempre se mantiene casi entero.

### 2.2 Prohibición explícita al transcriptor

El prompt de transcripción debe prohibir, y los tests deben comprobar:

- **No interpretar.** Transcribe lo que ve, no lo que cree que quiso decir.
- **No resumir ni normalizar.** Ni ortografía, ni mayúsculas, ni puntuación.
- **No completar.** Un trazo ilegible se marca `[ilegible]`, no se adivina.

Un modelo que rellena huecos con lo plausible es el mismo fallo que las bboxes
inventadas, pero **mucho peor**, porque el resultado se lee bien y no hay señal.

### 2.3 El diff es determinista, no un juicio

La comparación entre las dos lecturas es **string diff literal**. No se le pregunta
a un LLM cuál le convence más. Coincidencia carácter a carácter → aceptar;
diferencia → marcar el tramo.

Esto mantiene el principio de autoridad del sistema: **el modelo propone, la lógica
local decide**. Un LLM eligiendo ganador entre dos lecturas es un LLM aprobando
evidencia, y eso está prohibido en toda la arquitectura.

### 2.4 Independencia real, aquí sí

Las dos lecturas deben ser de **modelos distintos**. A diferencia de qwen y llama
con el mismo prompt semántico —que son **una sola familia** y pisan las mismas
trampas—, leer mal un trazo ambiguo es un fallo de reconocimiento visual, no del
prompt compartido. Dos modelos fallan distinto. La independencia es genuina y debe
declararse en la tabla de familias como `family: visual-transcription`.

### 2.5 Prohibido validar contra el grafo

Tentador y **circular**: "¿existe Narek? sí → lectura correcta". Una lectura
equivocada que coincide con una entidad ya conocida saldría **reforzada** en vez de
penalizada. El glosario se usa **solo** para decidir si un token es de riesgo
(ausente = riesgo), nunca para confirmar que una lectura es buena.

---

## 3. Granularidad: la duda es del tramo, no de la nota

**Requisito de producto, no detalle de implementación.** El objetivo del usuario es
no tener que pasar a limpio sus notas. Eso obliga a:

- Si en una página de 40 líneas hay duda en 2 nombres, **las otras 38 entran al
  grafo sin intervención**. No se aprueba "la nota": se confirman dos palabras.
- Un tramo dudoso **no bloquea la ingesta**. Entra marcado, con su confianza, y
  espera en la cola de revisión existente.

Marcar la página entera como dudosa porque hay una palabra dudosa **es un fallo de
la entrega**, aunque los tests pasen.

---

## 4. Etiquetas de origen (se diseñan ahora, se explotan después)

La vista por personaje —"cada usuario ve la verdad de su personaje"— **no se
implementa en esta versión**. Es una decisión tomada: para una primera versión, con
datos mezclados y casi todos subidos por el mismo usuario, una vista por personaje a
medias es **peor que no tenerla** (si filtra el 90% y se escapa un dato, el jugador
se lo cree porque el sistema se lo dijo, y el destripe no se deshace).

Pero los campos **sí entran ya**, porque son gratis hoy y caros después: sin ellos,
el día que se quiera la vista hay que **reingerir el corpus entero** para recuperar
información que estaba delante en el momento de la subida y se tiró.

En `metadata` del episodio (único hueco permitido por los contratos congelados
`v3-contracts-frozen-1.0.0` — **los esquemas no se tocan**):

| Campo | Tipo | Obligatorio | Significado |
|---|---|---|---|
| `source_file` | string | sí | Nombre de archivo original |
| `ingested_by` | string | sí | Usuario que subió el material |
| `author_hint` | string | no | **Quién escribió** la nota |
| `perspective_hint` | string | no | **Desde qué personaje** es el conocimiento |
| `session_id` | string | no | Sesión de juego |
| `in_game_date` | string | no | Fecha en el mundo del juego |

**`author_hint` y `perspective_hint` son campos distintos y deben nacer separados,
aunque al principio coincidan casi siempre.** Reconocer la letra identifica **quién
escribió**, no **quién sabe**: si el máster toma notas de toda la mesa, su letra está
en información que su personaje no debería tener. Solo `perspective_hint` filtrará el
grafo el día que exista la vista.

Fuente en esta versión: **el nombre del archivo**, explícito y manual. Nada de
inferencia. Todos los campos opcionales van **vacíos por defecto** y ningún camino
del código puede exigirlos.

---

## 5. Criterio de aceptación

**La métrica que decide es la fracción de tokens transcritos que acaba en revisión
humana.**

No se fija un número objetivo, y esto es deliberado: depende de la letra del usuario
y de cuántos nombres propios inventados haya por página, y **no está medido**. Podría
salir 5% o podría salir 30%. La entrega debe **instrumentar y reportar la cifra
real** sobre el material de prueba; inventar un umbral para poder declararlo cumplido
invalida la entrega.

Métricas obligatorias:

```
s9_transcription_{pages,spans,escalated,disagreed,to_review}_total
s9_transcription_review_fraction        # la cifra que decide
s9_stage_duration_seconds{stage="transcription"}
```

---

## 6. Tests obligatorios

| # | Caso | Esperado |
|---|---|---|
| 1 | Imprenta limpia | Transcribe; **no escala**; 0 a revisión |
| 2 | Palabra emborronada | LLM detecta incoherencia → escala |
| 3 | Nombre propio coherente pero mal leído | **Escala igual** (token de riesgo) |
| 4 | Número/fecha | **Escala siempre**, sea coherente o no |
| 5 | Término fuera de glosario | Escala |
| 6 | Dos lecturas idénticas | Acepta sin revisión |
| 7 | Dos lecturas distintas | Marca **solo el tramo**, no la página |
| 8 | Página 40 líneas, 2 dudas | **38 líneas entran al grafo** sin intervención |
| 9 | Tramo dudoso | **No bloquea la ingesta**; entra marcado |
| 10 | Trazo ilegible | `[ilegible]`, **nunca adivinado** |
| 11 | Prompt no normaliza | Ortografía/mayúsculas/puntuación intactas |
| 12 | El diff no llama a ningún LLM | Verificado, no asumido |
| 13 | Validación contra grafo | **Ausente del código** |
| 14 | Nombre coincidente con entidad conocida | **No sube** la confianza |
| 15 | Se piden bboxes al VLM | **No ocurre**; ninguna ruta lo hace |
| 16 | Offsets sobre la transcripción | Coherentes con su hash |
| 17 | Metadata sin campos opcionales | Funciona igual |
| 18 | `author_hint` ≠ `perspective_hint` | Se conservan **separados** |
| 19 | Esquemas de contrato | **Sin modificar** (hash comprobado) |
| 20 | Determinismo | Misma entrada → misma salida, N pasadas |

---

## 7. Restricciones de seguridad (vinculantes)

- **NUNCA escribir en el Neo4j de producción** (`neo4j-knowledge`, VM105).
- **Contratos congelados**: `contracts/knowledge-v3/v1/` y
  `data-engine/app/knowledge_v3/contracts/` **no se tocan**. Todo excedente va en
  `metadata`.
- **No usar** los splits `heldout` ni `negation`. **No modificar** el corpus gold.
- **No** `git commit --amend`, **no** `push --force`.
- **Claves de API**: jamás en código, logs, commits ni mensajes de error. Se leen de
  `/etc/s9-knowledge/providers.env`.
- **`PRIVATE_CONTENT_STAYS_LOCAL`**: contenido marcado privado **no sale** a
  proveedores externos, ni bajo saturación. Notas manuscritas de partida son
  candidatas naturales a privado — respetar la marca **antes** de elegir proveedor.

---

## 8. Entrega

Rama propia, PR **sin merge**. En la descripción:

1. Salida real de la ejecución de tests, **con el número de tests**.
2. **La cifra de `review_fraction` medida**, con el material sobre el que se midió.
3. Qué quedó fuera y por qué.

Se revisará contra este documento, punto por punto.
