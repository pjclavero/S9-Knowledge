# S9 Knowledge — Ingesta multimodal automática, temporalidad y apoyo externo

## 1. Objetivo

S9 Knowledge debe poder recibir documentos, imágenes, notas y audios sin obligar al usuario a:

- renombrar archivos;
- crear carpetas por sesión;
- rellenar formularios;
- asignar manualmente cada fuente;
- revisar transcripciones completas;
- decidir qué proveedor o modelo debe procesar cada elemento.

El usuario únicamente aporta el material. El sistema debe encargarse de agruparlo, clasificarlo, procesarlo, contrastarlo y preparar candidatos de conocimiento.

La arquitectura debe mantener una regla permanente:

> **Los modelos externos aportan músculo de procesamiento. S9 Knowledge mantiene el control, valida las salidas y decide qué puede incorporarse al conocimiento.**

---

## 2. Principio arquitectónico

Los modelos externos nunca sustituyen al servidor ni actúan como autoridad sobre los datos.

```text
IA externa
→ procesa, interpreta y propone

S9 Knowledge
→ coordina, valida, contrasta, clasifica y decide
```

El servidor local conserva siempre:

- la orquestación;
- las colas de trabajo;
- los permisos;
- la separación por workspace;
- la procedencia;
- los hashes;
- los límites de uso;
- la validación de formatos;
- la comprobación de evidencias;
- los offsets;
- el consenso;
- la revisión humana selectiva;
- la autorización de escritura;
- la persistencia final en Neo4j.

Los proveedores externos nunca deben:

- escribir directamente en Neo4j;
- aprobar candidatos;
- modificar bases de datos;
- cambiar permisos;
- decidir qué se considera verdadero;
- activar una ingesta;
- saltarse las políticas de revisión;
- operar sin límites, timeouts y trazabilidad.

---

## 3. Diseño general de la ingesta

```text
Usuario
└── sube archivos sin prepararlos

S9 Knowledge
├── detecta nuevos materiales
├── agrupa archivos relacionados
├── separa lore base y sesiones
├── clasifica el tipo de fuente
├── divide el trabajo en lotes
├── envía tareas pesadas a proveedores externos
├── valida todas las respuestas
├── clasifica temporalidad y certeza
├── genera candidatos
├── compara con el grafo existente
├── acumula nueva evidencia
├── resuelve o mantiene dudas
└── autoriza la persistencia final
```

Los proveedores externos pueden encargarse de:

- transcripción de audio;
- diarización;
- OCR;
- visión;
- análisis textual;
- extracción asistida;
- segunda opinión;
- revisión semántica.

---

# Parte I — Imágenes, notas y documentos visuales

## 4. Tratamiento de imágenes con notas sueltas

Una imagen con notas dispersas no puede procesarse únicamente como una transcripción plana.

El sistema debe intentar detectar:

- bloques de texto;
- posición de cada bloque;
- títulos;
- listas;
- flechas;
- líneas;
- recuadros;
- agrupaciones;
- proximidad;
- colores;
- orden de lectura;
- relaciones visuales.

Ejemplo:

```text
Akodo Toturi
├── Clan León
├── Campeón
└── Enemigo de Kachiko
```

El modelo visual debe reconstruir una estructura aproximada:

```json
{
  "subject": "Akodo Toturi",
  "notes": [
    "Clan León",
    "Campeón",
    "Enemigo de Kachiko"
  ]
}
```

Después, el modelo textual puede proponer candidatos:

```text
Akodo Toturi → MEMBER_OF → Clan León
Akodo Toturi → HAS_TITLE → Campeón
Akodo Toturi → ENEMY_OF → Kachiko
```

Estas relaciones no deben considerarse hechos confirmados por defecto.

---

## 5. Grados de evidencia visual

La fuerza de una relación depende del tipo de evidencia disponible.

### Evidencia textual explícita

```text
“Akodo Toturi pertenece al Clan León”
```

Resultado:

```text
Relación fuerte
```

### Asociación gráfica

```text
Akodo Toturi → Clan León
```

Resultado:

```text
Relación probable
```

### Proximidad visual

```text
“Akodo Toturi” aparece cerca de “Clan León”
```

Resultado:

```text
Candidato débil
```

Una proximidad o una flecha pueden indicar relación, pero no siempre permiten determinar el predicado correcto.

---

## 6. Representación estructurada de la imagen

La salida visual debería conservar el texto y su posición.

```json
{
  "blocks": [
    {
      "id": "block_1",
      "text": "Akodo Toturi",
      "role": "main_subject",
      "bbox": [0.35, 0.10, 0.60, 0.18]
    },
    {
      "id": "block_2",
      "text": "Enemigo de Kachiko",
      "role": "note",
      "linked_to": "block_1",
      "bbox": [0.65, 0.30, 0.90, 0.38]
    }
  ]
}
```

El campo `bbox` permite mantener la posición relativa del contenido y auditar posteriormente cómo se interpretó la imagen.

---

# Parte II — Candidatos, duda y confirmación posterior

## 7. Estados de los candidatos

Las relaciones ambiguas no deben descartarse ni convertirse inmediatamente en relaciones reales.

Estados recomendados:

```text
CONFIRMED
PROBABLE
POSSIBLE
DOUBTFUL
CONFLICTING
REJECTED
```

Ejemplo:

```yaml
subject: Akodo Toturi
predicate: MEMBER_OF
object: Clan León
status: POSSIBLE
confidence: 0.48
evidence_kind: visual_association
requires_confirmation: true
```

---

## 8. Separación entre conocimiento confirmado y candidatos

No conviene guardar relaciones dudosas como relaciones normales del grafo.

Debe existir una capa separada:

```text
Grafo confirmado
```

y otra para:

```text
Candidatos pendientes
```

Modelo sugerido:

```text
RelationCandidate
- subject
- proposed_predicate
- object
- confidence
- status
- evidence_ids
- supporting_sources
- contradicting_sources
- created_from
- last_evaluated_at
- requires_review
```

---

## 9. Confirmación mediante el grafo existente

Antes de dejar una relación pendiente, el sistema puede consultar el conocimiento aprobado:

- si existe el sujeto;
- si existe el objeto;
- si ya hay una relación entre ambos;
- si existen relaciones compatibles;
- si hay evidencia textual con procedencia;
- si existe una contradicción;
- si el predicado propuesto es compatible con el resto del contexto.

### Evidencia sólida previa

```text
Toturi ──MEMBER_OF──> Clan León
Fuente: manual X, página 34
```

La nueva nota visual puede pasar a:

```text
CONFIRMED_BY_EXISTING_EVIDENCE
```

La confirmación procede de la evidencia anterior, no de la imagen.

### Evidencia compatible pero insuficiente

```text
Toturi ──CHAMPION_OF──> Clan León
```

La propuesta `MEMBER_OF` puede pasar a:

```text
PROBABLE
```

pero no queda confirmada automáticamente.

### Evidencia contradictoria

La propuesta pasa a:

```text
CONFLICTING
```

y queda preparada para revisión o futura reevaluación.

---

## 10. Confirmación mediante futuras entradas

Un candidato puede permanecer pendiente y reevaluarse al llegar nueva información.

```text
Entrada 1:
Imagen con “Toturi — Clan León”
→ POSSIBLE

Entrada 2:
Audio: “Toturi fue campeón del Clan León”
→ PROBABLE

Entrada 3:
Manual: “Akodo Toturi, miembro del Clan León”
→ CONFIRMED
```

El sistema debe conservar:

- historial de cambios;
- evidencias usadas;
- fuentes favorables;
- fuentes contrarias;
- versión de la política;
- modelo o proveedor que propuso la relación;
- decisión final.

---

# Parte III — Relaciones vivas y cambios de verdad

## 11. Relaciones que cambian con el tiempo

Una relación puede haber sido cierta durante un periodo y cambiar posteriormente.

Ejemplo:

```text
A y B fueron aliados.
Después pasan a ser enemigos.
```

La alianza no se elimina:

```yaml
predicate: ALLY_OF
valid_from: 1120
valid_to: 1123
status: HISTORICAL
```

Se crea una nueva relación:

```yaml
predicate: ENEMY_OF
valid_from: 1123
valid_to: null
status: CURRENT
```

Regla:

```text
No borrar ALLY_OF y crear ENEMY_OF
```

Sino:

```text
Cerrar ALLY_OF
→ crear ENEMY_OF
→ enlazar el cambio con el evento que lo explica
```

---

## 12. Cuando una afirmación resulta falsa

También puede cambiar lo que se creía saber.

Ejemplo:

```text
Primera versión:
A mató a B

Revelación posterior:
C mató a B
```

La primera afirmación no debe borrarse.

Debe marcarse como:

```text
RETRACTED
CONTRADICTED
FALSE
SUPERSEDED
```

y conservar:

- la fuente original;
- quién lo afirmó;
- cuándo se consideró válido;
- qué evidencia lo contradijo;
- qué afirmación lo sustituyó.

---

## 13. Estados temporales y epistemológicos

Estados de vigencia:

```text
CURRENT
HISTORICAL
PROPOSED
DISPUTED
CONTRADICTED
RETRACTED
SUPERSEDED
UNKNOWN
```

Estados de certeza:

```text
CONFIRMED
PROBABLE
POSSIBLE
RUMOR
FALSE
```

No deben mezclarse en un único campo.

Ejemplos válidos:

```text
HISTORICAL + CONFIRMED
CURRENT + DISPUTED
RETRACTED + FALSE
PROPOSED + POSSIBLE
```

---

# Parte IV — Temporalidad y evolución del conocimiento

## 14. Tres cronologías diferentes

S9 Knowledge debe distinguir al menos tres tiempos.

### Tiempo del mundo narrado

Cuándo ocurrió realmente algo.

```text
event_time
valid_from
valid_to
```

### Tiempo del descubrimiento

Cuándo se reveló, publicó o conoció.

```text
discovered_at
discovered_in_session
published_at
```

### Tiempo del sistema

Cuándo se procesó y registró.

```text
ingested_at
recorded_at
```

Ejemplo:

```text
La traición ocurrió durante el año 1120.
Se reveló en un libro publicado después.
S9 Knowledge procesó ese libro meses más tarde.
```

Las tres fechas son diferentes.

---

## 15. Evolución del conocimiento

La temporalidad no solo sirve para ordenar lo que ocurre, sino para reconstruir cómo cambia lo que se sabe.

Ejemplo:

```text
Libro 1:
Se cree que A traicionó a B.

Libro 2:
Aparece una pista que pone esa versión en duda.

Libro 3:
Se descubre que C manipuló los hechos.

Libro 4:
Se confirma que A era inocente.
```

El sistema debe poder responder:

- qué se sabía hasta una fuente concreta;
- cuándo se reveló que una versión era falsa;
- qué afirmaciones estaban vigentes en un momento;
- qué fuente cambió la interpretación;
- qué secretos siguen sin confirmar;
- cómo evolucionó la comprensión de un evento.

---

## 16. Conocimiento por actor

En fases avanzadas puede distinguirse:

```text
global_knowledge
reader_knowledge
character_knowledge
faction_knowledge
```

Ejemplo:

```text
El lector sabe que C es el traidor.
A todavía no lo sabe.
B sospecha de C.
El Clan León cree que el culpable es D.
```

Estas afirmaciones no son contradictorias porque pertenecen a poseedores de conocimiento diferentes.

---

# Parte V — Sesiones y cronología de campaña

## 17. La sesión no es el reloj de la historia

El número de sesión indica el orden de juego, no el tiempo narrativo.

Una sesión puede abarcar:

- diez segundos de combate;
- varias horas;
- varios meses;
- un flashback;
- un salto de años;
- la continuación inmediata de la sesión anterior.

Por tanto, deben mantenerse dos cronologías:

```text
Cronología de sesiones
Cronología del mundo narrado
```

---

## 18. Estructura recomendada

```text
Campaña
└── Sesión
    └── Escena
        └── Eventos, afirmaciones y relaciones
```

Cada sesión puede tener:

```text
campaign_id
session_number
played_at
previous_session
next_session
```

Cada escena puede tener:

```text
session_id
scene_order
world_time_start
world_time_end
time_precision
temporal_mode
```

---

## 19. Modos temporales de escena

```text
CURRENT
FLASHBACK
FLASHFORWARD
TIME_SKIP
SIMULTANEOUS
UNKNOWN
```

Ejemplo:

```text
Sesión 18
├── Escena 1: día 20, por la mañana
├── Escena 2: recuerdo de hace cinco años
├── Escena 3: día 20, por la tarde
└── Epílogo: seis meses después
```

---

## 20. Precisión temporal

No debe inventarse una fecha exacta cuando solo existe una referencia aproximada.

```text
EXACT
DAY
MONTH
SEASON
YEAR
RELATIVE
UNKNOWN
```

Ejemplos:

```text
EXACT
→ 14 de mayo de 1123, 18:30

SEASON
→ primavera de 1123

RELATIVE
→ tres meses después

UNKNOWN
→ momento no determinado
```

---

## 21. Una escena puede ocupar varias sesiones

Ejemplo:

```text
Sesión 21:
empieza el combate.

Sesión 22:
continúa el mismo combate segundos después.

Sesión 23:
termina la misma escena.
```

El cambio de sesión no obliga a avanzar el tiempo narrativo.

---

## 22. Revelaciones posteriores sobre hechos antiguos

Ejemplo:

```text
Sesión 30:
se descubre que la traición ocurrió durante la sesión 12.
```

Debe registrarse:

```text
event_time: momento narrativo de la sesión 12
discovered_in_session: 30
recorded_at: momento de procesamiento
```

La revelación pertenece a la sesión 30, pero el evento histórico pertenece al momento anterior.

---

# Parte VI — Dos vistas de navegación

## 23. Vista por sesión

Debe mostrar qué se jugó, añadió o descubrió en cada sesión.

```text
Sesión 12
├── archivos procesados
├── escenas
├── personajes nuevos
├── relaciones nuevas
├── relaciones modificadas
├── rumores
├── contradicciones
└── conocimiento disponible al terminar
```

---

## 24. Vista histórica

Debe ordenar los acontecimientos por el tiempo real del mundo.

```text
1123 → alianza
1124 → traición
1124 → comienza la enemistad
1125 → se descubre la causa real
```

Una revelación procesada en la sesión 20 puede aparecer históricamente en un evento ocurrido mucho antes.

---

# Parte VII — Asignación automática de archivos a sesiones

## 25. Principio de experiencia de usuario

El usuario no debe:

- renombrar archivos;
- crear carpetas especiales;
- indicar manualmente el número de sesión;
- rellenar formularios;
- confirmar cada lote.

Flujo:

```text
Usuario sube archivos
→ sistema los detecta
→ los agrupa automáticamente
→ identifica lore o sesión
→ procesa el contenido
→ corrige la agrupación si aparece nueva evidencia
```

---

## 26. Señales para agrupar archivos

El sistema puede utilizar:

1. fecha y hora de creación;
2. fecha y hora de subida;
3. proximidad temporal;
4. contenido de los archivos;
5. referencias como “sesión anterior”, “hoy” o “tres meses después”;
6. coincidencia de personajes;
7. coincidencia de lugares;
8. coincidencia de acontecimientos;
9. continuidad con la última sesión;
10. tipo de documento;
11. estructura del archivo;
12. carpeta de origen, si aporta información;
13. nombre del archivo, si contiene una pista.

La fecha de subida debe ser una señal, no la única regla.

---

## 27. Agrupación automática por lotes

Ejemplo:

```text
Viernes 20:10 → audio.m4a
Viernes 23:40 → notas.jpg
Sábado 00:15 → resumen.md
```

Resultado:

```text
Sesión detectada 12
```

Cinco días después:

```text
Miércoles 19:50 → audio.m4a
Miércoles 23:10 → notas.jpg
```

Resultado:

```text
Sesión detectada 13
```

---

## 28. Niveles de confianza

```text
Confianza alta
→ asignación automática silenciosa

Confianza media
→ asignación provisional y reevaluación posterior

Confianza baja
→ archivo procesado, pero pendiente de sesión
```

Nada dudoso debe bloquear el procesamiento.

---

## 29. Modelo de asignación

```yaml
session_assignment:
  session_id: S12
  status: AUTO_ASSIGNED
  confidence: 0.91
  signals:
    - upload_proximity
    - content_continuity
    - same_characters
    - follows_previous_events
```

Si más adelante se corrige:

```yaml
session_assignment:
  session_id: S10
  status: AUTO_REASSIGNED
  previous_session_id: S12
  reason:
    - explicit_content_reference
    - narrative_continuity
```

La reasignación no debe obligar a repetir todo el procesamiento.

---

## 30. Lore base

Los manuales, libros y documentos generales deben clasificarse como:

```text
LORE_BASE
```

Pueden considerarse equivalentes a un estado inicial o “sesión 0”, pero no son una sesión jugada.

Señales para detectar lore base:

- tipo de documento;
- extensión y estructura;
- contenido general de ambientación;
- ausencia de referencias a una partida concreta;
- coincidencia con fuentes ya clasificadas;
- ubicación original;
- estilo editorial;
- índice, capítulos y paginación.

---

## 31. Experiencia visible para el usuario

La interfaz debería mostrar información resumida:

```text
Nueva sesión detectada
5 archivos procesados
3 escenas identificadas
12 hechos nuevos
4 relaciones actualizadas
2 cuestiones pendientes
```

El usuario solo debería intervenir cuando exista una ambigüedad con consecuencias importantes.

---

# Parte VIII — Audio y transcripción externa

## 32. Objetivo

Los audios pueden consumir muchos recursos y tardar demasiado si se procesan íntegramente con CPU local.

La transcripción pesada debe poder realizarse fuera del servidor.

Regla:

> **El servicio externo transcribe. S9 Knowledge divide, controla, valida, reconstruye y decide.**

---

## 33. Flujo de audio

```text
Audio nuevo
→ detección automática
→ hash y metadatos
→ conversión ligera
→ división en fragmentos
→ transcripción externa
→ tiempos y hablantes
→ reconstrucción
→ validación de integridad
→ corrección con glosario
→ clasificación de relevancia
→ extracción de conocimiento
```

---

## 34. División en fragmentos

Un audio largo no debe enviarse como una única unidad.

Ejemplo:

```text
00:00–10:05
09:55–20:05
19:55–30:05
...
```

El solapamiento evita cortar frases.

Ventajas:

- reintentar solo el bloque fallido;
- repartir carga;
- continuar tras un error;
- guardar checkpoints;
- procesar partes en paralelo;
- no perder todo el trabajo por un fallo final.

---

## 35. Reparto de responsabilidades

### Proveedor externo ASR

Puede encargarse de:

- reconocimiento de voz;
- detección de idioma;
- marcas temporales;
- puntuación;
- diarización;
- transcripción de varias horas;
- separación de hablantes.

### Modelos externos de texto

Pueden ayudar a:

- corregir nombres propios;
- corregir lugares;
- reconocer clanes y facciones;
- aplicar glosarios;
- detectar segmentos ambiguos;
- proponer una transcripción corregida.

### S9 Knowledge

Mantiene:

- la fuente original;
- el texto ASR original;
- el texto corregido;
- el motivo de la corrección;
- la marca temporal;
- el proveedor;
- el modelo;
- la confianza;
- la evidencia de audio.

---

## 36. Proveedores NVIDIA considerados

Candidatos alojados para pruebas:

```text
Principal:
nvidia/parakeet-1.1b-rnnt-multilingual-asr

Comparador especializado en español:
nvidia/parakeet-ctc-0.6b-es

Respaldo:
openai/whisper-large-v3 mediante NVIDIA
```

La disponibilidad gratuita debe comprobarse en la cuenta real.

No debe confundirse:

```text
Downloadable
```

con:

```text
Free Endpoint
```

o acceso alojado de desarrollo.

---

## 37. Uso eficiente de proveedores

No conviene enviar todo el audio a varios modelos.

```text
Modelo principal
→ procesa todo el audio

Segundo modelo
→ solo procesa fragmentos:
   - con baja confianza;
   - con nombres dudosos;
   - con voces solapadas;
   - con omisiones;
   - con contradicciones;
   - importantes para la campaña.
```

`faster-whisper` local debe quedar como respaldo selectivo, no como trabajador principal.

---

## 38. Tolerancia a fallos

```text
NVIDIA disponible
→ trabajador principal

NVIDIA sin créditos o no disponible
→ trabajo en cola
→ reintento posterior
→ proveedor alternativo
→ faster-whisper local solo como fallback controlado
```

El sistema debe incluir:

- timeouts;
- reintentos limitados;
- circuit breaker;
- control de créditos;
- caché por hash;
- reanudación;
- procesamiento idempotente.

---

# Parte IX — Conversación casual y contenido fuera de partida

## 39. Problema

En una grabación de partida pueden aparecer:

- conversaciones personales;
- bromas;
- comida;
- móviles;
- trabajo;
- comentarios externos;
- pausas;
- pruebas de sonido;
- conversaciones no relacionadas con la campaña.

No todo lo transcrito debe pasar a extracción.

---

## 40. Clasificación de relevancia

Cada fragmento debe clasificarse como:

```text
IN_GAME
OFF_TOPIC
UNCERTAIN
```

Ejemplos:

```text
“Entramos en el castillo”
→ IN_GAME

“¿Pedimos pizza?”
→ OFF_TOPIC

“Ese hombre no es de fiar”
→ UNCERTAIN
```

Los segmentos dudosos deben reevaluarse usando el contexto anterior y posterior.

---

## 41. Señales de relevancia

El sistema puede usar:

- nombres de personajes;
- lugares;
- facciones;
- vocabulario del juego;
- continuidad temática;
- identidad del hablante;
- referencias al mundo real;
- cambios bruscos de tema;
- expresiones como “fuera de personaje”;
- frases como “mi personaje hace”;
- intervención del máster;
- términos del glosario;
- eventos ya presentes en el grafo.

---

## 42. No todo lo relacionado con la partida es un hecho

El sistema debe distinguir:

```text
FACT
REPORTED
RUMOR
BELIEF
CLAIM
POSSIBILITY
HYPOTHESIS
DOUBT
JOKE
CONTRADICTED
UNKNOWN
```

Ejemplos:

```text
“Toturi está en el palacio”
→ posible afirmación factual

“Creo que Toturi está en el palacio”
→ BELIEF

“El máster dijo que Toturi está en el palacio”
→ REPORTED

“¿Y si Toturi estuviera en el palacio?”
→ HYPOTHESIS

“Seguro que Kachiko es un dragón, ja, ja”
→ JOKE o HYPOTHESIS
```

Nunca debe convertirse una broma en un hecho.

---

## 43. Tratamiento de fragmentos

```text
IN_GAME
→ pasa a clasificación epistémica y extracción

OFF_TOPIC
→ no entra en el grafo

UNCERTAIN
→ se conserva y se reevalúa
```

La conversación casual puede conservarse temporalmente en la transcripción bruta, pero nunca debe incorporarse automáticamente al conocimiento.

Por privacidad, podría existir una política para borrar después los fragmentos `OFF_TOPIC`, conservando únicamente:

- marca temporal;
- clasificación;
- motivo del descarte;
- hash;
- auditoría mínima.

---

# Parte X — Experiencia de usuario y automatización

## 44. Principio de interacción

El sistema debe deducir automáticamente:

- qué archivos están relacionados;
- qué pertenece a lore;
- qué pertenece a una sesión;
- qué parte del audio es de partida;
- qué relaciones son posibles;
- qué conocimiento ha cambiado;
- qué necesita revisión.

El usuario solo debe recibir resúmenes y alertas relevantes.

---

## 45. Panel recomendado

Ejemplo de resumen:

```text
Audio procesado: 3 h 12 min
Contenido de partida: 2 h 21 min
Conversación casual descartada: 42 min
Fragmentos dudosos: 9 min

Nueva sesión detectada: S12
Archivos asociados: 5
Escenas identificadas: 3
Hechos nuevos: 12
Relaciones actualizadas: 4
Candidatos pendientes: 2
Contradicciones: 1
```

El usuario puede corregir algo desde el panel cuando lo considere necesario, pero no debe ser un paso obligatorio.

---

# Parte XI — Modelo mínimo de datos

## 46. Source

```text
Source
- source_id
- workspace
- campaign_id
- session_id
- source_role
- uploaded_at
- created_at
- source_kind
- hash
- assignment_method
- assignment_confidence
- is_baseline_lore
```

---

## 47. Session

```text
Session
- campaign_id
- session_id
- session_number
- played_at
- detected_at
- assignment_status
- confidence
```

---

## 48. Scene

```text
Scene
- scene_id
- session_id
- scene_order
- world_time_start
- world_time_end
- time_precision
- temporal_mode
```

---

## 49. Assertion o relación

```text
Assertion
- subject
- predicate
- object
- valid_from
- valid_to
- discovered_at
- discovered_in_session
- ingested_at
- epistemic_status
- truth_status
- confidence
- source
- evidence
- known_by
- supersedes
- contradicts
```

---

## 50. RelationCandidate

```text
RelationCandidate
- candidate_id
- subject
- proposed_predicate
- object
- status
- confidence
- evidence_kind
- evidence_ids
- supporting_sources
- contradicting_sources
- created_from
- created_at
- last_evaluated_at
- requires_review
```

---

# Parte XII — Reglas de seguridad y control

## 51. Salidas externas no confiables

Toda salida de un modelo externo debe considerarse:

```text
UNTRUSTED
SHADOW_ONLY
VALIDATED_LOCALLY
TRACEABLE
REVERSIBLE
NON_PERSISTENT_UNTIL_APPROVED
```

---

## 52. Validaciones obligatorias

Antes de persistir:

- validar el esquema;
- comprobar offsets;
- comprobar evidencia;
- comprobar sujeto y objeto;
- validar predicado;
- validar negación;
- validar temporalidad;
- validar estado epistémico;
- comprobar workspace;
- comprobar duplicados;
- comprobar contradicciones;
- aplicar política de confianza;
- registrar procedencia.

---

## 53. Escritura final

```text
IA externa propone
→ S9 Knowledge valida
→ consenso clasifica
→ revisión humana solo si es necesaria
→ autorización de persistencia
→ escritura controlada en Neo4j
```

---

# Parte XIII — Prioridades de implementación

## 54. Fase inmediata

1. Mantener el programa actual de calibración.
2. Integrar proveedores externos solo en modo sombra.
3. Probar transcripción alojada de NVIDIA.
4. Comparar modelos ASR con audios reales.
5. Añadir clasificación `IN_GAME / OFF_TOPIC / UNCERTAIN`.
6. Mantener `faster-whisper` como fallback selectivo.
7. No permitir escritura directa en Neo4j.

---

## 55. Fase posterior

1. Detección automática de lotes y sesiones.
2. Separación automática entre lore y campaña.
3. Modelo de escenas.
4. Temporalidad narrativa.
5. Evolución del conocimiento.
6. Candidatos provisionales.
7. Reevaluación automática con nuevas fuentes.
8. Vistas por sesión e historia.
9. Panel de incidencias y correcciones.

---

## 56. Mejora futura

El uso de embeddings y búsqueda semántica puede quedar para una versión posterior.

Posible flujo futuro:

```text
Pregunta
→ consulta al grafo
→ búsqueda semántica en fuentes originales
→ recuperación de evidencias
→ Ollama redacta la respuesta
```

No es una prioridad para la primera ingesta.

---

# 57. Conclusión

El diseño debe permitir que el usuario únicamente suba sus materiales.

```text
Usuario
→ aporta documentos, imágenes y audios

Servicios externos
→ aportan capacidad de cálculo

S9 Knowledge
→ organiza, valida, contrasta, conserva la historia y decide
```

Principio final:

> **El usuario solo aporta el material. Los proveedores externos aportan músculo. S9 Knowledge organiza, contrasta, valida y decide sin perder el control del conocimiento.**
