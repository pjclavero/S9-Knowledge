# Notas de validación semántica — L5A

Generado por: Agente C, Prioridad 2 — S9 Knowledge
Fuente de verdad: `data-engine/app/schemas/rpg_schema.py` y `data-engine/app/review/validator.py`

---

## Esquema de relaciones válidas

Las relaciones en `ALLOWED_RELATION_TYPES` se agrupan por dominio semántico.
Las columnas de tipo de nodo son orientativas: el validator actual comprueba
conflictos solo cuando `from_type` o `to_type` están presentes en el candidato.

| Relación | Origen típico | Destino típico | Notas |
|---|---|---|---|
| `MEMBER_OF` | Character / Creature | Faction / Clan / Family / School | Pertenencia a grupo |
| `BELONGS_TO` | Character / Object / Artifact | Faction / Character / Location | Propiedad o pertenencia |
| `FOUGHT_AT` | Character / Creature | Location / Region | Combate en lugar concreto |
| `HAS_FOUGHT` | Character | Character / Creature | Solo entre seres; jamás contra Location |
| `LOVES` | Character | Character | Solo entre seres; invalida si to_type ∈ {Location, Region, Faction, Clan, Object, Artifact} |
| `SPOUSE_OF` | Character | Character | Solo entre seres; invalida si to_type ∈ {Location, Region, Faction, Clan, Object} |
| `PARENT_OF` | Character | Character / Creature | Invalida si to_type ∈ {Location, Region, Faction, Clan} |
| `ALLY_OF` | Character / Faction | Character / Faction | Alianza política o personal |
| `ENEMY_OF` | Character / Faction | Character / Faction | Enemistad o conflicto activo |
| `RIVAL_OF` | Character | Character | Rivalidad personal o profesional |
| `ALLIED_WITH` | Character / Faction | Character / Faction | Sinónimo ampliado de ALLY_OF |
| `LOCATED_IN` | Character / Location / Object | Location / Region | Ubicación física |
| `OCCURS_IN` | Event / Encounter / Combat | Location / Region | Lugar donde ocurre un evento |
| `APPEARS_IN` | Character / Creature | Session / Document / Chapter | Aparece en fuente narrativa |
| `CONTAINS` | Location / Faction / Document | any | Contiene a otro nodo |
| `MENTIONS` | Document / Session / Transcript | any | Referencia en fuente |
| `OWNS` | Character / Faction | Object / Artifact | Posesión |
| `USES` | Character | Object / Artifact / Spell | Uso activo |
| `TEACHES` | Character | Character | Transmisión de conocimiento |
| `LEARNS` | Character | Spell / Concept / Rule | Aprendizaje |
| `CREATED_BY` | Object / Artifact / Spell | Character | Autoría |
| `DESCENDANT_OF` | Character / Family | Character / Family | Linaje |
| `SERVES` | Character | Character / Faction | Servicio o vasallaje |
| `GOVERNS` | Character / Faction | Location / Region / Faction | Gobierno o control |
| `AFFECTS` | Spell / Event / Concept | Character / Location | Efecto sobre entidad |
| `REQUIRES` | Task / Spell | Object / Character / Concept | Prerequisito |
| `CONTRADICTS` | Document / Concept | Document / Concept | Contradicción narrativa |
| `INVESTIGATES` | Character | Event / Character / Object / Concept | Investigación activa |
| `SUSPECTS` | Character | Character / Faction / Event | Sospecha narrativa |
| `INTERROGATES` | Character | Character | Interrogatorio |
| `WARNED_BY` | Character | Character | Recibió advertencia |
| `WARNS` | Character | Character / Faction | Emite advertencia |
| `HAS_VISION_OF` | Character | Character / Event / Location | Visión premonitoria |
| `SEES_IN_VISION` | Character | Character / Event / Object | Lo visto en la visión |
| `HAS_SYMBOL_OF` | Character / Object | Faction / Clan | Porta símbolo de clan |
| `DISAPPEARED_NEAR` | Character / Object | Location | Desaparición en un lugar |
| `MEETS` | Character | Character | Encuentro físico o narrativo |
| `KNOWS` | Character | Character | Conoce a alguien |
| `ORDERS` | Character | Character / Faction | Órdenes jerárquicas |
| `PLOTS_AGAINST` | Character / Faction | Character / Faction | Conspiración |
| `PROTECTS` | Character | Character / Location / Object | Protección activa |
| `MENTOR_OF` | Character | Character | Relación mentor-discípulo |
| `STUDENT_OF` | Character | Character | Relación discípulo-maestro |
| `BETRAYS` | Character | Character / Faction | Traición |
| `COMMANDS` | Character / Faction | Character / Faction | Mando jerárquico |
| `WORKS_FOR` | Character | Character / Faction | Empleo o servicio |
| `THREATENS` | Character | Character / Faction | Amenaza |
| `BLACKMAILS` | Character | Character | Chantaje |
| `FEARS` | Character | Character / Creature / Faction | Temor |
| `TRUSTS` | Character | Character | Confianza explícita |
| `DISTRUSTS` | Character | Character | Desconfianza explícita |
| `SEEN_IN` | Creature / Character | Location / Region | Avistamiento |
| `ENCOUNTERED_AT` | Character / Creature | Location | Encuentro en un lugar |
| `DEFEATED_AT` | Character / Creature | Location | Derrota en un lugar |
| `KILLED_AT` | Character / Creature | Location | Muerte en un lugar |
| `ESCAPED_FROM` | Character / Creature | Location / Character | Huida |
| `GUARDS` | Character / Creature | Location / Object | Custodia |
| `HAUNTS` | Spirit / Creature | Location | Acechamiento sobrenatural |
| `SUMMONED_BY` | Spirit / Creature / Demon | Character | Invocación |
| `CORRUPTED_BY` | Character / Creature | Demon / Spirit / Artifact | Corrupción |
| `ATTACKED` | Character / Creature | Character / Creature | Ataque entre seres |
| `HELPED` | Character | Character | Ayuda activa |
| `TALKED_TO` | Character | Character | Conversación directa |
| `FOUND_IN` | Object / Artifact | Location | Hallazgo de objeto en lugar |
| `HIDDEN_IN` | Object / Character | Location | Ocultado en lugar |
| `TRAVELS_TO` | Character | Location | Desplazamiento |
| `COMES_FROM` | Character | Location / Region | Origen geográfico |
| `RULES_OVER` | Character / Faction | Location / Region / Faction | Gobierno |
| `OCCURS_DURING` | Event / Encounter | Event / Session | Simultaneidad temporal |
| `PARTICIPATES_IN` | Character | Event / Encounter / Session | Participación |
| `CAUSES` | Character / Event | Event / Encounter | Causalidad narrativa |
| `LEADS_TO` | Event / Decision | Event / Encounter | Consecuencia |
| `DISCOVERS` | Character | Object / Location / Concept / Event | Descubrimiento |
| `REVEALS` | Character / Event | Character / Concept | Revelación |
| `CHANGES_STATUS_OF` | Event | Character / Faction | Cambio de estado |
| `STARTS_TASK` | Character | Task | Inicio de tarea |
| `COMPLETES_TASK` | Character | Task | Completar tarea |
| `FAILS_TASK` | Character | Task | Fallo de tarea |
| `ASSIGNED_TO` | Task | Character | Asignación |
| `BLOCKED_BY` | Task | Task / Character / Event | Bloqueo |
| `COMPLETED_BY` | Task | Character | Completado por |
| `SOURCE_OF` | Document / Transcript | Character / Event | Fuente de información |
| `EXTRACTED_FROM` | Character / Event | Document / Transcript | Extracción de fuente |
| `HAS_IMAGE` | Character / Location / Event | Image | Imagen asociada |
| `HAS_TRANSCRIPT` | Session | Transcript | Transcripción asociada |
| `KNOWS_ABOUT` | Character | Character / Event / Faction / Location | Conocimiento informado |
| `HAS_SEEN` | Character | Character / Location / Object / Event | Visto directamente |
| `HAS_MET` | Character | Character | Conocido en persona |
| `HAS_HEARD_ABOUT` | Character | Character / Event / Faction | Oído de segunda mano |
| `HAS_TALKED_TO` | Character | Character | Ha hablado con |
| `DISCOVERED` | Character | Object / Location / Concept | Descubrimiento pasado |
| `WAS_PRESENT_AT` | Character | Event / Location | Presencia en evento o lugar |
| `PARTICIPATED_IN` | Character | Event / Encounter | Participación pasada |
| `WITNESSED` | Character | Event / Combat | Fue testigo de |
| `WAS_TOLD_BY` | Character | Character | Informado por |
| `TELLS` | Character | Character | Cuenta a alguien |
| `TELLS_ABOUT` | Character | Character / Event | Cuenta sobre algo/alguien |
| `SHARED_WITH` | Character / Concept | Character | Información compartida |
| `KNOWN_BY_PARTY` | Character / Event / Object | — | Conocido por el grupo |
| `KNOWN_PUBLICLY` | Character / Event / Faction | — | Conocimiento público |
| `INVOLVES` | Event / Task | Character / Faction | Involucra a |
| `DECIDES` | Character | Event / Task / Concept | Decisión narrativa |
| `AGREES_TO` | Character | Task / Event / Concept | Acuerdo |
| `CHECKS` | Character | Object / Location / Concept | Comprobación |
| `HOLDS` | Character | Object / Artifact | Porta físicamente |
| `TASK_ASSIGNED_TO` | Task | Character | Tarea asignada |
| `TASK_TARGETS` | Task | Character / Event / Location | Objetivo de la tarea |
| `SEARCHES_FOR` | Character | Character / Object / Location | Búsqueda activa |

---

## Combinaciones inválidas conocidas

Definidas explícitamente en `validator._ENTITY_RELATION_CONFLICT`.
Cuando `to_type` del candidato pertenece al conjunto de tipos conflictivos,
el validator emite un issue `invalid` (nunca `dubious`) con sugerencia si existe.

| Relación | to_type inválido | Acción correcta | Sugerencia del validator |
|---|---|---|---|
| `HAS_FOUGHT` | `Location` | Usar `FOUGHT_AT` cuando el destino es un lugar | `FOUGHT_AT` |
| `HAS_FOUGHT` | `Region` | Usar `FOUGHT_AT` cuando el destino es una región | `FOUGHT_AT` |
| `HAS_FOUGHT` | `Faction` | Usar `ATTACKED` o revisar si es combate grupal | `FOUGHT_AT` (sugerencia genérica) |
| `HAS_FOUGHT` | `Clan` | Igual que Faction | `FOUGHT_AT` (sugerencia genérica) |
| `LOVES` | `Location` | Revisar: probable error de clasificación | — |
| `LOVES` | `Region` | Revisar: probable error de clasificación | — |
| `LOVES` | `Faction` | Revisar: probable error de clasificación | — |
| `LOVES` | `Clan` | Revisar: probable error de clasificación | — |
| `LOVES` | `Object` | Revisar: probable error de clasificación | — |
| `LOVES` | `Artifact` | Revisar: puede ser `OWNS` o `USES` | — |
| `SPOUSE_OF` | `Location` | Error claro; revisar fuente | — |
| `SPOUSE_OF` | `Region` | Error claro; revisar fuente | — |
| `SPOUSE_OF` | `Faction` | Error claro; revisar fuente | — |
| `SPOUSE_OF` | `Clan` | Error claro; revisar fuente | — |
| `SPOUSE_OF` | `Object` | Error claro; revisar fuente | — |
| `PARENT_OF` | `Location` | Probable metáfora narrativa; marcar needs_review | — |
| `PARENT_OF` | `Region` | Probable metáfora narrativa; marcar needs_review | — |
| `PARENT_OF` | `Faction` | Posible `GOVERNS` o `CREATED_BY`; revisar | — |
| `PARENT_OF` | `Clan` | Posible `GOVERNS` o `CREATED_BY`; revisar | — |

**Nota sobre `from_type`:** el validator también comprueba el campo `from_type`.
Si `from_type` pertenece al conjunto conflictivo para una relación, el issue
también se emite (pero esto es menos habitual en datos reales del pipeline).

---

## Casos ambiguos L5A

Los siguientes casos requieren intervención humana o contexto adicional para
resolver correctamente. El decider los enruta a `needs_review`.

### Apodos y títulos compartidos

- **"El Cazador"** — puede ser alias de múltiples personajes según la sesión.
  En transcripciones ASR puede aparecer como "el Cazador", "Cazador" o "cazador".
  Sin match de glosario, debe ir a `needs_review`.

- **"Sensei"** / **"Maestro"** / **"El Maestro"** — títulos honoríficos que no
  identifican a una persona concreta. El extractor los filtra por `_GENERIC_NAMES`
  en la lógica de alias, pero pueden escapar como candidato si van acompañados de
  un nombre propio posterior.

- **"El Escorpión"** — puede referirse al Clan Escorpión (Faction) o a un
  personaje apodado así. El tipo depende del contexto de la frase.

### Lugares con variantes temporales

- **"Castillo Viejo" / "Antiguo Castillo"** — pueden ser el mismo lugar que
  "Castillo [nombre]" en épocas distintas, o lugares diferentes. El fuzzy
  resolver puede proponer ambos como candidatos; el humano debe confirmar.

- **"La Ciudad"** como referencia sin nombre propio — ambiguo sin contexto.
  El extractor no debería emitirlo como candidato (es una cadena de longitud
  corta y sin mayúsculas propias), pero el LLM puede incluirlo.

### Nombres con partículas de clan (L5A específico)

- Nombres japoneses en L5A siguen el patrón **Clan Apellido** (ej. "Doji Satsume").
  El apellido solo (ej. "Doji") puede ser el clan (Faction) o el apellido familiar.
  Si aparece sin nombre propio, el tipo es ambiguo.

- **"Bayushi"** como token único: puede ser Bayushi (persona) o el prefijo de
  clan. El extractor solo tiene base_conf 0.65 para single-token sin glosario
  y sin evidencia explícita → cap a 0.70 → va a `needs_review`.

### Entidades colectivas

- **"El grupo"**, **"los personajes"**, **"los magistrados"** — referencias
  colectivas que el schema resuelve a la entidad canónica "Grupo de la sesión"
  (`COLLECTIVE_ENTITY_REFS` en `rpg_schema.py`). El extractor heurístico no
  las crea como entidades individuales, pero el LLM puede incluirlas.

### Errores ASR frecuentes

- **"Clan Grula"** (por "Clan Grulla") — el matcher normaliza sin tildes pero
  no corrige errores de consonante. Sin glosario, el resolver no lo matcheará
  con el nodo canonical.

- **"Doji Satsume" vs "Doji Satsumé"** — las tildes en nombres japoneses son
  inconsistentes entre sesiones. `_normalize_for_compare` elimina diacríticos
  antes del lookup, por lo que el glosario debe almacenar la clave normalizada.

---

## Reglas de resolución de alias en L5A

El resolver heurístico (`resolver._resolve_one`) aplica las siguientes
estrategias en orden de confianza para buscar entidades existentes en Neo4j:

1. **Coincidencia exacta** sobre `canonical_name` — score 1.0, match_type `exact`
2. **Alias** — el nombre aparece en la lista `aliases` del nodo — score 0.95, match_type `alias`
3. **Normalizado** (`toLower`) — score 0.85, match_type `normalized`

Reglas adicionales aplicadas en `rpg_schema.resolve_entity_ref`:

4. **Case-insensitive** — sin diferenciar mayúsculas
5. **Sin tildes** (`_normalize_key`) — elimina diacríticos y colapsa espacios
6. **Por último término** — apellido o primer nombre por separado (ej. "Satsume" → "Doji Satsume")
7. **Por subcadena segura** — solo si la subcadena tiene >= 3 caracteres y el match es único

La función `add_auto_aliases` en `rpg_schema.py` añade automáticamente el
**último término** del nombre canónico como alias para Characters de dos o más
palabras (ej. "Kakita Asuka" → alias "Asuka"), salvo que el término sea
genérico (lista `_GENERIC_NAMES`).

### Prioridad de canonicalización en el extractor

El extractor heurístico busca la clave normalizada (`_normalize_for_compare`)
del nombre detectado directamente en el dict del glosario. Si hay match,
reemplaza el nombre por el `canonical_term` almacenado. Esta canonicalización
ocurre **después** de calcular la confidence, por lo que el alias detectado
recibe el boost de glosario (+0.20) antes de ser renombrado al canonical.

### Alias no resueltos (prioridad de revisión humana)

Los siguientes patrones producen candidatos que el resolver marcará `needs_review`
sin match exacto en Neo4j si el glosario no los contempla explícitamente:

- Nombres con partícula honorífica: "Doji Satsume-dono", "Bayushi-sama"
- Referencias en tercera persona con artículo: "la Bayushi", "el Doji"
- Transliteraciones alternativas: "Kakita" / "Kachita" (error ASR)
- Nombres solo en hiragana/katakana transliterados al español con variantes
