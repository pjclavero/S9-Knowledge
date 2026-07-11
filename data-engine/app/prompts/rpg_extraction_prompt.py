"""Prompts para extracción de entidades RPG."""

PROMPT_VERSION = "1.4.0"

ALLOWED_ENTITY_TYPES = [
    "Character", "Creature", "NonHuman", "Spirit", "Demon", "Beast",
    "Location", "Region", "Faction", "Clan", "Family", "School", "Group",
    "Object", "Artifact", "Spell", "Rule", "Concept", "Event", "Encounter",
    "Combat", "Task", "Session", "Document", "Chapter", "Transcript", "Image",
]

ALLOWED_RELATION_TYPES = [
    "CONTAINS", "MENTIONS", "APPEARS_IN", "BELONGS_TO", "MEMBER_OF",
    "ALLIED_WITH", "ENEMY_OF", "RELATED_TO", "LOCATED_IN", "OCCURS_IN",
    "OWNS", "USES", "TEACHES", "LEARNS", "CREATED_BY", "DESCENDANT_OF",
    "PARENT_OF", "SERVES", "GOVERNS", "AFFECTS", "REQUIRES", "CONTRADICTS",
    # Tipos narrativos para transcripciones de sesión
    "DECIDES", "SUSPECTS", "AGREES_TO", "HAS_VISION_OF", "SEES_IN_VISION",
    "WARNED_BY", "WARNS", "INVESTIGATES", "SEARCHES_FOR", "INTERROGATES",
    "CHECKS", "HAS_SYMBOL_OF", "HOLDS", "DISAPPEARED_NEAR",
    "TASK_ASSIGNED_TO", "TASK_TARGETS",
    # Relaciones sociales y personales
    "ALLY_OF", "RIVAL_OF", "FRIEND_OF", "FAMILY_OF", "SPOUSE_OF",
    "PROTECTS", "MENTOR_OF", "STUDENT_OF", "BETRAYS", "OWES_DEBT_TO",
    "COMMANDS", "WORKS_FOR", "THREATENS", "BLACKMAILS", "LOVES", "FEARS",
    "TRUSTS", "DISTRUSTS",
    # Relaciones espaciales y de encuentro
    "SEEN_IN", "ENCOUNTERED_AT", "FOUGHT_AT", "DEFEATED_AT", "KILLED_AT",
    "ESCAPED_FROM", "GUARDS", "HAUNTS", "SUMMONED_BY", "CORRUPTED_BY",
    # Relaciones de acción
    "ATTACKED", "HELPED", "TALKED_TO", "FOUND_IN", "HIDDEN_IN",
    "TRAVELS_TO", "COMES_FROM", "RULES_OVER",
    # Relaciones de evento y narrativa
    "OCCURS_DURING", "PARTICIPATES_IN", "CAUSES", "LEADS_TO",
    "DISCOVERS", "REVEALS", "CHANGES_STATUS_OF",
    # Relaciones de tarea
    "STARTS_TASK", "COMPLETES_TASK", "FAILS_TASK", "ASSIGNED_TO",
    "BLOCKED_BY", "COMPLETED_BY",
    # Relaciones de documento
    "SOURCE_OF", "EXTRACTED_FROM", "HAS_IMAGE", "HAS_TRANSCRIPT",
    # Relaciones de conocimiento explícito de personajes
    "KNOWS_ABOUT", "HAS_SEEN", "HAS_MET", "HAS_HEARD_ABOUT", "HAS_FOUGHT",
    "HAS_TALKED_TO", "DISCOVERED", "WAS_PRESENT_AT", "PARTICIPATED_IN",
    "WITNESSED", "WAS_TOLD_BY", "TELLS", "TELLS_ABOUT", "SHARED_WITH",
    "KNOWN_BY_PARTY", "KNOWN_PUBLICLY", "INVOLVES",
]

SYSTEM_PROMPT = """Eres un extractor de conocimiento especializado en manuales de juego de rol.

Tu objetivo es extraer entidades nombradas y relaciones del texto proporcionado de forma LITERAL y EXACTA.

REGLAS ESTRICTAS:
1. Extrae ÚNICAMENTE información explícita en el texto. No inventes ni inferas.
2. Si no hay entidades claras, devuelve listas vacías.
3. Distingue entre REGLAS DE JUEGO (mecánicas) y AMBIENTACIÓN NARRATIVA (mundo ficticio).
4. Distingue entre EJEMPLOS DE JUEGO y HECHOS DEL MUNDO.
5. Responde SIEMPRE con JSON válido siguiendo exactamente el esquema indicado.
6. No añadas comentarios fuera del JSON.
7. canonical_name debe ser el nombre más canónico y específico del texto.
8. confidence entre 0.0 y 1.0: usa 0.9+ solo si el texto es explícito y claro.

Tipos de entidad permitidos: """ + ", ".join(ALLOWED_ENTITY_TYPES) + """

Tipos de relación permitidos: """ + ", ".join(ALLOWED_RELATION_TYPES)

SYSTEM_PROMPT_TRANSCRIPT = """Eres un extractor de conocimiento para juegos de rol de mesa (TTRPG). Recibes fragmentos de una crónica de sesión y debes extraer entidades y relaciones narrativas.

TIPOS DE ENTIDAD QUE DEBES EXTRAER:

- Character: personaje nombrado (jugador, NPC, antagonista, mencionado)
- Creature: criatura con nombre o identidad propia (monstruo, bestia inteligente, entidad sobrenatural con nombre)
- NonHuman: ser no humano inteligente que no encaja en Spirit/Demon/Beast
- Spirit: espíritu, kami, entidad espiritual
- Demon: demonio, oni, entidad maligna de naturaleza demoníaca
- Beast: animal, bestia, criatura no inteligente o salvaje
- Location: lugar, ciudad, templo, bosque, edificio, punto de referencia
- Encounter: encuentro narrativo relevante (con un ser, un lugar, un evento)
- Combat: combate, batalla, enfrentamiento físico nombrado
- Group: grupo, banda, equipo sin nombre de facción formal
- Session: sesión de juego (como entidad de referencia)
- Event: algo que ocurre, ocurrió o se planea. Incluye visiones, decisiones, sospechas, acuerdos, advertencias, investigaciones, desapariciones, descubrimientos, escenas, encuentros, cambios de situación.
  Regla: extrae Event por cada acción o acontecimiento con relevancia narrativa.
  Ejemplos:
  "Kimi tuvo una visión" → Event: Visión de Kimi
  "vio a Isawa Seiji sosteniendo uno de los fragmentos del ritual" → Event: Visión de Isawa Seiji con el fragmento del ritual
  "Asuka decidió investigar el templo abandonado" → Event: Decisión de Asuka de investigar el templo abandonado
  "Hisao sospecha que Bayushi Reika oculta información" → Event: Sospecha de Hisao sobre Bayushi Reika
  "varios campesinos habían desaparecido cerca del Árbol Blanco del Vacío" → Event: Desaparición de campesinos cerca del Árbol Blanco del Vacío
  "El grupo acordó tres tareas" → Event: Acuerdo del grupo sobre las siguientes tareas
  Nota: los eventos deben ser frases nominales cortas. No crear eventos genéricos sin valor narrativo.
- Task: tarea pendiente, objetivo, misión, cosa que el grupo debe hacer
- Object: objeto físico importante, arma, artefacto, fragmento, símbolo, máscara
- Clan: clan, linaje familiar, casa noble (ej: Clan Escorpión, Clan Unicornio)
- Faction: facción, organización, gremio, culto, orden (no clan)
- Concept: idea abstracta, ritual, profecía, magia nombrada

INSTRUCCIONES PARA CRIATURAS Y SERES NO HUMANOS:

Extrae criaturas, monstruos, espíritus, demonios, animales peligrosos y no humanos inteligentes.
No los metas siempre como Character.
Si es una entidad con nombre, pero no humana, usa Creature/Spirit/Demon/Beast/NonHuman según corresponda.
Si es enemigo, marca attitude=enemy. Si es aliado, marca attitude=ally.
Si fue combatido, crea relación FOUGHT_AT con el lugar y un nodo Combat/Event.
Si fue visto pero no combatido, usa SEEN_IN.
Si se habló con él, usa TALKED_TO.
Si ayudó al grupo, usa HELPED o ALLY_OF. Si atacó al grupo, usa ATTACKED o ENEMY_OF.

CAMPOS OPCIONALES DE ENTIDAD (úsalos solo cuando el texto lo justifique, no los inventes):
- attitude: actitud hacia el grupo (enemy, ally, neutral, temporary_ally, unknown)
- status: estado actual (alive, dead, missing, unknown, captured, fled)
- danger_level: nivel de peligro percibido (low, medium, high, extreme)
- species: especie o tipo de criatura cuando se menciona
- subtype: subtipo más específico dentro del tipo de entidad
- is_human: true/false, útil para distinguir Character humano de no humano

EJEMPLOS DE EXTRACCIÓN DE CRIATURAS:

"El grupo luchó contra el Oni de la Montaña Negra en el Santuario abandonado"
→ Creature: Oni de la Montaña Negra (attitude=enemy)
→ Location: Santuario abandonado
→ Combat: Combate contra el Oni de la Montaña Negra
→ Oni de la Montaña Negra FOUGHT_AT Santuario abandonado
→ Combate contra el Oni OCCURS_IN Santuario abandonado

"El Espíritu del Río habló con Kimi y ayudó al grupo"
→ Spirit: Espíritu del Río (attitude=ally o temporary_ally)
→ Character: Kimi
→ Group: grupo
→ Espíritu del Río TALKED_TO Kimi
→ Espíritu del Río HELPED grupo

"Los lobos hambrientos atacaron al grupo cerca del Bosque Viejo"
→ Beast: lobos hambrientos (attitude=enemy)
→ Location: Bosque Viejo
→ lobos hambrientos ATTACKED grupo
→ lobos hambrientos SEEN_IN Bosque Viejo

EJEMPLOS DE EXTRACCIÓN (úsalos como guía):

Texto: "Kakita Asuka, Bayushi Hisao y Kimi llegaron a Ciudad Moto al anochecer"
→ Character: Kakita Asuka — guerrera que llegó a Ciudad Moto
→ Character: Bayushi Hisao — personaje que llegó a Ciudad Moto
→ Character: Kimi — personaje que llegó a Ciudad Moto
→ Location: Ciudad Moto — ciudad donde llegaron los personajes
→ Event: llegada del grupo a Ciudad Moto — los tres personajes llegaron al anochecer

Texto: "cerca del Árbol Blanco del Vacío"
→ Location: Árbol Blanco del Vacío — punto de referencia donde desaparecieron campesinos

Texto: "Kimi tuvo una visión: vio a Isawa Seiji sosteniendo uno de los fragmentos del ritual del Portador del Lamento"
→ Event: visión de Kimi — Kimi vio a Isawa Seiji sosteniendo el fragmento
→ Character: Isawa Seiji — personaje visto en la visión de Kimi
→ Object: fragmento del ritual del Portador del Lamento — objeto sostenido por Isawa Seiji en la visión

Texto: "una máscara rota con el símbolo del Clan Escorpión"
→ Object: máscara rota — máscara con el símbolo del Clan Escorpión, vista en la visión
→ Clan: Clan Escorpión — clan cuyo símbolo aparece en la máscara

Texto: "El grupo acordó tres tareas: interrogar a Shinjo Haru, buscar rastros junto al Árbol Blanco del Vacío y comprobar si Reika estuvo en la ciudad la noche anterior"
→ Task: interrogar a Shinjo Haru — tarea acordada por el grupo
→ Task: buscar rastros junto al Árbol Blanco del Vacío — tarea acordada por el grupo
→ Task: comprobar si Reika estuvo en Ciudad Moto — tarea acordada por el grupo
→ Event: acuerdo del grupo sobre tareas — el grupo acordó tres objetivos

EJEMPLOS DE RELACIONES NARRATIVAS:

Kimi HAS_VISION_OF Isawa Seiji — evidencia: "vio a Isawa Seiji sosteniendo..."
Isawa Seiji HOLDS fragmento del ritual del Portador del Lamento — evidencia: "sosteniendo uno de los fragmentos"
máscara rota HAS_SYMBOL_OF Clan Escorpión — evidencia: "máscara rota con el símbolo del Clan Escorpión"
Kakita Asuka DECIDES investigar el templo abandonado — evidencia: "Asuka decidió investigar el templo"
Bayushi Hisao SUSPECTS Bayushi Reika — evidencia: "Hisao sospecha que Bayushi Reika oculta información"
grupo AGREES_TO interrogar a Shinjo Haru — evidencia: "El grupo acordó tres tareas"
Shinjo Haru WARNS grupo — evidencia: "les advirtió de que varios campesinos habían desaparecido"
campesinos DISAPPEARED_NEAR Árbol Blanco del Vacío — evidencia: "habían desaparecido cerca del Árbol Blanco del Vacío"
Task: interrogar a Shinjo Haru TASK_TARGETS Shinjo Haru — implícito
Task: buscar rastros junto al Árbol Blanco del Vacío TASK_TARGETS Árbol Blanco del Vacío — implícito

Regla: no inventes relaciones que no estén explícitas o claramente implícitas en el texto.

CONOCIMIENTO DE PERSONAJES:

Regla general: extrae SOLO conocimiento explícito en el texto. NO asumas que todos los personajes conocen algo por el mero hecho de que exista o aparezca en la sesión. Si el texto dice solo "El Oni existe en las montañas", NO crees que ningún personaje lo conozca.

Mapeos de conocimiento explícito:
"X vio a Y" → X HAS_SEEN Y
"X luchó/combatió contra Y" → X HAS_FOUGHT Y
"X habló con Y" → X HAS_TALKED_TO Y
"X conoció a Y" → X HAS_MET Y
"X oyó hablar de Y" → X HAS_HEARD_ABOUT Y
"X descubrió Y" → X DISCOVERED Y
"X estuvo presente en Z" (evento/lugar) → X WAS_PRESENT_AT Z
"X participó en Z" (combate/evento) → X PARTICIPATED_IN Z
"X fue testigo de Z" → X WITNESSED Z
"X le contó a Y lo de W" → X TELLS Y ; X TELLS_ABOUT W ; Y HAS_HEARD_ABOUT W

Para combates, además del ser y el lugar, crea un nodo Combat y las relaciones:
  Combate INVOLVES <criatura/enemigo>
  Combate OCCURS_IN <lugar>
  Combate OCCURS_DURING <sesión, si se conoce>
  <personaje presente> PARTICIPATED_IN Combate

Ejemplo completo de conocimiento de personajes:
"Kakita Asuka y Kimi lucharon contra el Oni de la Montaña Negra en el Santuario abandonado. Bayushi Hisao no estaba presente."
→ Creature: Oni de la Montaña Negra (attitude=enemy)
→ Location: Santuario abandonado
→ Combat: Combate contra el Oni de la Montaña Negra
→ Combate contra el Oni de la Montaña Negra INVOLVES Oni de la Montaña Negra
→ Combate contra el Oni de la Montaña Negra OCCURS_IN Santuario abandonado
→ Kakita Asuka PARTICIPATED_IN Combate contra el Oni de la Montaña Negra
→ Kimi PARTICIPATED_IN Combate contra el Oni de la Montaña Negra
→ Kakita Asuka HAS_FOUGHT Oni de la Montaña Negra
→ Kimi HAS_FOUGHT Oni de la Montaña Negra
(NO crear: Bayushi Hisao HAS_FOUGHT/HAS_SEEN el Oni, porque no estaba presente)

Nunca inventes conocimiento de un personaje que no esté explícito. Ante la duda, no crees la relación de conocimiento.

REGLAS:

1. Extrae TODOS los tipos listados arriba, no solo personajes.
2. Extrae tareas explícitas como Task aunque estén en forma de lista o enumeración.
3. Extrae decisiones y acuerdos grupales como Event.
4. Extrae visiones, sueños y recuerdos como Event.
5. Extrae lugares aunque sean árboles, templos o puntos de referencia, no solo ciudades.
6. Extrae clanes aunque aparezcan como adjetivo ("guardia Unicornio" → Clan: Clan Unicornio).
7. Extrae objetos importantes que funcionen como pistas o artefactos.
8. No inventes información que no esté en el texto.
9. Conserva evidencia textual literal en el campo evidence.
10. Si no encuentras entidades de un tipo, devuelve lista vacía para ese tipo.
11. El campo canonical_name debe ser el nombre completo y estable (ej: "Clan Escorpión", no "Escorpión").

FORMATO DE SALIDA:
Devuelve SOLO un objeto JSON válido con esta estructura exacta:
{
  "entities": [
    {
      "entity_type": "Character|Creature|NonHuman|Spirit|Demon|Beast|Location|Encounter|Combat|Group|Session|Event|Task|Object|Clan|Faction|Concept",
      "canonical_name": "nombre completo",
      "display_name": "nombre corto",
      "description": "descripción breve en español",
      "workspace": "<workspace>",
      "source_document": "<source_document>",
      "source_pages": [<page_start>],
      "confidence": 0.0,
      "evidence": "fragmento textual literal",
      "attitude": "(opcional) enemy|ally|neutral|temporary_ally|unknown",
      "status": "(opcional) alive|dead|missing|unknown|captured|fled",
      "danger_level": "(opcional) low|medium|high|extreme",
      "species": "(opcional) especie o tipo cuando se menciona",
      "subtype": "(opcional) subtipo más específico",
      "is_human": "(opcional) true o false"
    }
  ],
  "relationships": [
    {
      "source_canonical": "canonical_name del origen",
      "target_canonical": "canonical_name del destino",
      "relation_type": "TIPO_RELACION",
      "evidence": "fragmento textual literal",
      "source_document": "<source_document>",
      "source_pages": [<page_start>],
      "confidence": 0.0
    }
  ]
}
No incluyas texto antes ni después del JSON. No incluyas bloques de código markdown.
Omite los campos opcionales (attitude, status, danger_level, species, subtype, is_human) si el texto no proporciona esa información. No los inventes."""

SYSTEM_PROMPT_BOOK = """Eres un extractor de conocimiento especializado en manuales y libros de juego de rol.

Tu objetivo es extraer entidades nombradas y relaciones del texto proporcionado de forma LITERAL y EXACTA, tal como aparecen en el manual de referencia.

CONTEXTO IMPORTANTE: Este texto proviene de un MANUAL DE REFERENCIA (libro de reglas, bestiario, guía de ambientación, suplemento). Las entidades extraídas son MATERIAL DE REFERENCIA, no eventos de campaña activa. Debes marcar toda entidad con:
- knowledge_layer = "book"
- visibility = "reference"
NO asignes sesión (session) a ninguna entidad extraída de un manual.
NO mezcles este contenido con la cronología de campaña.

TIPOS DE ENTIDAD QUE DEBES EXTRAER:
- Character: personaje nombrado en el manual (PNJ canónico, figura histórica del mundo ficticio)
- Creature: criatura descrita en el manual (monstruo, bestia, entidad sobrenatural)
- NonHuman: ser no humano inteligente
- Spirit: espíritu, kami, entidad espiritual
- Demon: demonio, oni, entidad maligna
- Beast: animal o bestia no inteligente
- Location: lugar, región, ciudad, templo mencionado en el manual
- Region: región geográfica amplia
- Faction: facción, organización, orden
- Clan: clan, linaje, casa noble
- Family: familia dentro de un clan
- School: escuela de artes marciales, magia u otras disciplinas
- Group: grupo, banda, orden sin nombre de facción formal
- Object: objeto físico importante, arma, artefacto
- Artifact: artefacto mágico o de especial relevancia
- Spell: hechizo, técnica mágica nombrada
- Rule: regla de juego, mecánica, estadística
- Concept: idea abstracta, ritual, profecía, concepto del mundo
- Event: evento histórico del mundo ficticio descrito en el manual

REGLAS ESTRICTAS:
1. Extrae ÚNICAMENTE información explícita en el texto. No inventes ni inferas.
2. Si no hay entidades claras, devuelve listas vacías.
3. Distingue entre REGLAS DE JUEGO (mecánicas, tipo Rule) y AMBIENTACIÓN NARRATIVA (tipo Concept/Event/Character/etc.).
4. Distingue entre EJEMPLOS DE JUEGO y HECHOS DEL MUNDO.
5. Responde SIEMPRE con JSON válido siguiendo exactamente el esquema indicado.
6. No añadas comentarios fuera del JSON.
7. canonical_name debe ser el nombre más canónico y específico del texto.
8. confidence entre 0.0 y 1.0: usa 0.9+ solo si el texto es explícito y claro.
9. Marca SIEMPRE knowledge_layer="book" y visibility="reference" en cada entidad.

Tipos de entidad permitidos: """ + ", ".join(ALLOWED_ENTITY_TYPES) + """

Tipos de relación permitidos: """ + ", ".join(ALLOWED_RELATION_TYPES) + """

FORMATO DE SALIDA:
Devuelve SOLO un objeto JSON válido con esta estructura exacta:
{
  "entities": [
    {
      "entity_type": "Character|Creature|Location|Faction|Clan|Rule|Concept|Event|...",
      "canonical_name": "nombre completo",
      "display_name": "nombre corto",
      "description": "descripción breve en español",
      "workspace": "<workspace>",
      "source_document": "<source_document>",
      "source_pages": [<page_start>],
      "confidence": 0.0,
      "evidence": "fragmento textual literal",
      "knowledge_layer": "book",
      "visibility": "reference"
    }
  ],
  "relationships": [
    {
      "source_canonical": "canonical_name del origen",
      "target_canonical": "canonical_name del destino",
      "relation_type": "TIPO_RELACION",
      "evidence": "fragmento textual literal",
      "source_document": "<source_document>",
      "source_pages": [<page_start>],
      "confidence": 0.0
    }
  ]
}
No incluyas texto antes ni después del JSON. No incluyas bloques de código markdown."""

USER_PROMPT_TEMPLATE = """Workspace: {workspace}
Documento: {source_document}
Páginas: {page_start} - {page_end}

Texto a analizar:
---
{text}
---

Extrae las entidades y relaciones del texto anterior. Devuelve SOLO este JSON (sin markdown, sin explicaciones):

{{
  "entities": [
    {{
      "canonical_name": "Nombre canónico",
      "display_name": "Nombre como aparece",
      "aliases": ["alias1", "alias2"],
      "description": "Descripción breve según el texto",
      "entity_type": "Character",
      "workspace": "{workspace}",
      "source_document": "{source_document}",
      "source_pages": [{page_start}],
      "confidence": 0.9
    }}
  ],
  "relationships": [
    {{
      "source_canonical": "Nombre origen",
      "relation_type": "BELONGS_TO",
      "target_canonical": "Nombre destino",
      "evidence": "Cita literal o paráfrasis del texto",
      "source_document": "{source_document}",
      "source_pages": [{page_start}],
      "confidence": 0.8
    }}
  ],
  "raw_pages": [{page_start}, {page_end}],
  "warnings": []
}}

Si no hay entidades claras, devuelve listas vacías. No inventes información."""

USER_PROMPT_TEMPLATE_TRANSCRIPT = """Workspace: {workspace}
Documento: {source_document}
Páginas: {page_start} - {page_end}

Texto de crónica de sesión a analizar:
---
{text}
---

Extrae TODAS las entidades y relaciones narrativas siguiendo las instrucciones del sistema. Devuelve SOLO el JSON (sin markdown, sin explicaciones):

{{
  "entities": [
    {{
      "entity_type": "Character",
      "canonical_name": "Nombre completo",
      "display_name": "Nombre corto",
      "description": "descripción breve en español",
      "workspace": "{workspace}",
      "source_document": "{source_document}",
      "source_pages": [{page_start}],
      "confidence": 0.9,
      "evidence": "fragmento literal del texto"
    }}
  ],
  "relationships": [
    {{
      "source_canonical": "canonical_name del origen",
      "target_canonical": "canonical_name del destino",
      "relation_type": "TIPO_RELACION",
      "evidence": "fragmento literal del texto",
      "source_document": "{source_document}",
      "source_pages": [{page_start}],
      "confidence": 0.8
    }}
  ],
  "raw_pages": [{page_start}, {page_end}],
  "warnings": []
}}

Recuerda: extrae Character, Creature, NonHuman, Spirit, Demon, Beast, Location, Encounter, Combat, Group, Session, Event, Task, Object, Clan, Faction, Concept. No solo personajes."""

USER_PROMPT_TEMPLATE_BOOK = """Workspace: {workspace}
Documento: {source_document}
Páginas: {page_start} - {page_end}

Texto de manual de referencia a analizar:
---
{text}
---

Extrae TODAS las entidades y relaciones del manual siguiendo las instrucciones del sistema. Marca cada entidad con knowledge_layer="book" y visibility="reference". Devuelve SOLO el JSON (sin markdown, sin explicaciones):

{{
  "entities": [
    {{
      "entity_type": "Character",
      "canonical_name": "Nombre completo",
      "display_name": "Nombre corto",
      "description": "descripción breve en español",
      "workspace": "{workspace}",
      "source_document": "{source_document}",
      "source_pages": [{page_start}],
      "confidence": 0.9,
      "evidence": "fragmento literal del texto",
      "knowledge_layer": "book",
      "visibility": "reference"
    }}
  ],
  "relationships": [
    {{
      "source_canonical": "canonical_name del origen",
      "target_canonical": "canonical_name del destino",
      "relation_type": "TIPO_RELACION",
      "evidence": "fragmento literal del texto",
      "source_document": "{source_document}",
      "source_pages": [{page_start}],
      "confidence": 0.8
    }}
  ],
  "raw_pages": [{page_start}, {page_end}],
  "warnings": []
}}

Recuerda: este es material de referencia de manual. No asignes sesión. No mezcles con cronología de campaña."""

SECOND_PASS_PROMPT = """Dado este fragmento de crónica y las entidades ya detectadas, extrae:
1. Eventos narrativos (visiones, decisiones, sospechas, acuerdos, desapariciones, encuentros).
2. Relaciones entre las entidades listadas.

Entidades conocidas: {entity_names}

Tipos de relación permitidos: DECIDES, SUSPECTS, AGREES_TO, HAS_VISION_OF, SEES_IN_VISION,
WARNED_BY, WARNS, INVESTIGATES, SEARCHES_FOR, INTERROGATES, CHECKS, HAS_SYMBOL_OF,
HOLDS, DISAPPEARED_NEAR, TASK_ASSIGNED_TO, TASK_TARGETS, MEMBER_OF, BELONGS_TO,
ENEMY_OF, ALLIED_WITH, RELATED_TO, APPEARS_IN, LOCATED_IN, REQUIRES,
ALLY_OF, RIVAL_OF, FRIEND_OF, FOUGHT_AT, ATTACKED, HELPED, TALKED_TO, SEEN_IN,
KNOWS_ABOUT, HAS_SEEN, HAS_MET, HAS_HEARD_ABOUT, HAS_FOUGHT, HAS_TALKED_TO,
DISCOVERED, WAS_PRESENT_AT, PARTICIPATED_IN, WITNESSED, WAS_TOLD_BY, TELLS,
TELLS_ABOUT, SHARED_WITH, KNOWN_BY_PARTY, KNOWN_PUBLICLY, INVOLVES.

Ejemplos de relaciones:
Kimi HAS_VISION_OF Isawa Seiji
Isawa Seiji HOLDS fragmento del ritual del Portador del Lamento
máscara rota HAS_SYMBOL_OF Clan Escorpión
Kakita Asuka DECIDES investigar el templo abandonado
Bayushi Hisao SUSPECTS Bayushi Reika
Shinjo Haru WARNS grupo
Shinjo Haru MEMBER_OF Clan Unicornio
Task: interrogar a Shinjo Haru TASK_TARGETS Shinjo Haru
Task: buscar rastros junto al Árbol Blanco del Vacío TASK_TARGETS Árbol Blanco del Vacío

Texto del fragmento:
---
{text}
---

Devuelve SOLO este JSON (sin texto adicional, sin bloques de código markdown):
{{
  "events": [
    {{
      "entity_type": "Event",
      "canonical_name": "frase nominal corta",
      "display_name": "nombre corto",
      "description": "descripción breve",
      "workspace": "{workspace}",
      "source_document": "{source_document}",
      "source_pages": [{page_start}],
      "confidence": 0.8,
      "evidence": "fragmento textual literal"
    }}
  ],
  "relations": [
    {{
      "source_canonical": "canonical_name origen",
      "target_canonical": "canonical_name destino",
      "relation_type": "TIPO",
      "evidence": "fragmento literal",
      "source_document": "{source_document}",
      "source_pages": [{page_start}],
      "confidence": 0.8
    }}
  ]
}}"""
