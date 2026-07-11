# Diseño: Visibilidad del Conocimiento por Personaje

**Versión:** 1.0  
**Fecha:** 2026-07-09  
**Estado:** Diseño de referencia  
**Relacionado con:** `rpg_schema.py` 1.4+, pipeline de extracción, visor/API (implementación futura)

---

## 1. Problema

El modelo de conocimiento basado únicamente en sesión es insuficiente para RPG narrativo. Una entidad puede aparecer en la sesión 4, pero un jugador no debe verla si su personaje no la conoce.

**Ejemplo concreto:**  
En la sesión 4, Kakita Asuka y Kimi se enfrentan a un Oni en las montañas. Bayushi Hisao no estuvo presente. Por tanto:

- Asuka conoce al Oni (lo combatió).
- Kimi conoce al Oni (lo combatió).
- Hisao **no sabe nada del Oni** en ese momento.

Si el visor mostrara "todo lo de la sesión 4", Hisao (o su jugador) vería información que su personaje no tiene. Esto rompe la inmersión y el secreto narrativo.

El sistema debe soportar dos niveles de visibilidad que se aplican de forma conjunta.

---

## 2. Dos Niveles de Visibilidad

### Nivel 1: Por sesión / campaña

Filtra qué entidades y relaciones pertenecen a las sesiones visibles para el usuario (hasta la sesión seleccionada). Establece el universo de datos accesible.

### Nivel 2: Por conocimiento de personaje

Dentro de las sesiones visibles, filtra qué conoce realmente el personaje activo del usuario. Aplica sobre el universo del nivel 1.

**Ambos niveles se aplican en cascada.** Un usuario en modo `character_knowledge` solo ve entidades que:

1. Existen en sesiones hasta la seleccionada (nivel 1), Y
2. Su personaje tiene una relación de conocimiento explícita hacia ellas (nivel 2).

---

## 3. Relaciones de Conocimiento Canónicas

Estas relaciones modelan cómo un personaje sabe de una entidad. Se almacenan en el grafo de conocimiento (Neo4j) y se etiquetan en español en la interfaz.

| Relación (código)      | Etiqueta ES               | Descripción                                              |
|------------------------|---------------------------|----------------------------------------------------------|
| `KNOWS_ABOUT`          | sabe de                   | Conocimiento genérico, mínimo nivel de saber              |
| `HAS_SEEN`             | ha visto                  | Lo vio con sus propios ojos                               |
| `HAS_MET`              | ha conocido               | Contacto personal directo                                 |
| `HAS_HEARD_ABOUT`      | ha oído hablar de         | Conocimiento de segunda mano, puede ser rumor             |
| `HAS_FOUGHT`           | ha combatido contra       | Enfrentamiento directo                                    |
| `HAS_TALKED_TO`        | ha hablado con            | Conversación directa                                      |
| `DISCOVERED`           | descubrió                 | El personaje fue el primero en encontrarlo                |
| `WAS_PRESENT_AT`       | estuvo presente en        | Presencia en un evento                                    |
| `PARTICIPATED_IN`      | participó en              | Participación activa en un evento                         |
| `WITNESSED`            | fue testigo de            | Observó sin participar directamente                       |
| `WAS_TOLD_BY`          | fue informado por         | Recibió información de otra persona                       |
| `TELLS`                | cuenta a                  | Un personaje informa a otro                               |
| `TELLS_ABOUT`          | cuenta sobre              | Un personaje relata algo sobre una entidad               |
| `SHARED_WITH`          | compartido con            | Conocimiento transferido explícitamente                   |
| `KNOWN_BY_PARTY`       | conocido por el grupo     | Todo el grupo activo lo sabe                              |
| `KNOWN_PUBLICLY`       | conocido públicamente     | Información de dominio público en el mundo               |
| `INVOLVES`             | involucra a               | Una entidad participa en un evento                        |

> **Nota:** Estas relaciones y sus propiedades ya están soportadas en el schema del pipeline (`rpg_schema.py` 1.4+). La aplicación de las reglas de visibilidad se implementará en el visor y la API (trabajo futuro).

---

## 4. Propiedades de Conocimiento

### 4.1 En nodos (entidades)

| Propiedad              | Tipo / Valores                                                         | Descripción                                              |
|------------------------|------------------------------------------------------------------------|----------------------------------------------------------|
| `known_by_scope`       | `character` \| `party` \| `public` \| `narrator` \| `admin_only`      | Ámbito mínimo de visibilidad                              |
| `known_by_characters`  | lista de nombres de personaje                                          | Personajes que explícitamente conocen esta entidad       |
| `known_by_users`       | lista de usernames                                                     | Usuarios con visibilidad directa (override admin)        |
| `known_by_party`       | booleano                                                               | True si todo el grupo activo lo sabe                     |
| `known_publicly`       | booleano                                                               | True si es información pública en el mundo               |
| `known_from_session`   | número de sesión                                                       | Sesión en la que se adquirió el conocimiento             |
| `known_from_date`      | fecha ISO                                                              | Fecha en que se registró el conocimiento                 |

### 4.2 En relaciones de conocimiento

| Propiedad              | Tipo / Valores                                                                              | Descripción                                              |
|------------------------|---------------------------------------------------------------------------------------------|----------------------------------------------------------|
| `knowledge_quality`    | `seen` \| `met` \| `fought` \| `talked_to` \| `heard_about` \| `discovered` \| `witnessed` \| `inferred` \| `rumor` \| `confirmed` | Calidad/tipo del conocimiento |
| `knowledge_confidence` | float 0.0–1.0                                                                               | Certeza del personaje sobre este conocimiento            |
| `shared_from_character`| nombre de personaje                                                                         | Quién compartió la información (si aplica)              |
| `shared_to_character`  | nombre de personaje                                                                         | A quién se le compartió                                  |
| `shared_at_session`    | número de sesión                                                                            | Sesión en la que se produjo el intercambio              |

---

## 5. Modos de Visualización

El sistema ofrece cinco modos de visualización que determinan qué ve cada tipo de usuario:

### `admin_full`
Ve absolutamente todo: entidades secretas, del narrador, futuras, de referencia, marcadas como `admin_only`. Sin filtros. Modo para administradores de la campaña.

### `narrator`
Ve todo excepto entidades marcadas `admin_only`. Incluye secretos narrativos, información futura, entidades no descubiertas por los jugadores. Modo para el narrador de la partida.

### `party`
Ve todo lo que el grupo activo conoce: entidades con `known_by_party=true` o `known_publicly=true`, más lo que cualquier personaje del grupo haya compartido con el grupo. No ve secretos individuales de otros personajes ni información del narrador.

### `session_public`
Ve solo la información pública hasta la sesión seleccionada: entidades con `known_publicly=true` y relaciones no marcadas como secretas. Modo para lectores o espectadores sin personaje.

### `character_knowledge`
Ve únicamente lo que sabe el personaje activo del usuario. Es el modo principal de juego. Aplica las reglas del apartado 6.

---

## 6. Regla de Visibilidad para Usuario Normal (modo `character_knowledge`)

Un usuario en este modo ve una entidad si y solo si se cumple **al menos una** de las siguientes condiciones:

1. El personaje activo tiene una relación de conocimiento directa hacia esa entidad (`HAS_SEEN`, `HAS_MET`, `HAS_FOUGHT`, `HAS_TALKED_TO`, `HAS_HEARD_ABOUT`, `DISCOVERED`, `WITNESSED`, `KNOWS_ABOUT`, `WAS_TOLD_BY`, `PARTICIPATED_IN`, `WAS_PRESENT_AT`).
2. La entidad tiene `known_by_party=true` y el personaje es miembro del grupo activo en esa sesión.
3. La entidad tiene `known_publicly=true` (información pública del mundo).
4. El nombre del personaje activo figura en `known_by_characters` de la entidad.
5. El username del usuario figura en `known_by_users` de la entidad (override manual por admin).

**Nunca ve** (sin permiso explícito de admin) entidades con `known_by_scope` en:

- `secret` — secreto narrativo no descubierto
- `narrator` — solo para el narrador
- `future` — información de sesiones aún no jugadas
- `reference` — entidad de referencia interna sin presencia en la historia
- `manual` — ocultada manualmente por el admin
- `admin_only` — restringida al administrador

---

## 7. Regla de Visibilidad para Relaciones

Una relación entre dos entidades es visible para el usuario si se cumplen **todas** las condiciones:

1. Ambas entidades extremo son visibles para el usuario según las reglas del apartado 6.
2. La relación no está marcada como `secret=true` (o bien está marcada como `discovered_by` el personaje activo).
3. La relación pertenece a sesiones dentro del rango visible del usuario.
4. La relación no tiene `known_by_scope` en `narrator`, `future` o `admin_only`.
5. Si la relación requiere conocimiento específico (p. ej., `IS_ENEMY_OF`), el personaje debe tener la calidad de conocimiento suficiente (ver apartado 9).
6. No está explícitamente ocultada por el admin para ese usuario o personaje.

**Ejemplo:** Bayushi Reika existe en el grafo y es visible como personaje público (noble conocida). Sin embargo, la relación `IS_ENEMY_OF` entre Reika y el clan Kakita está marcada `secret=true`. Hisao ve que Reika existe, pero no sabe que es enemiga hasta que su personaje lo descubra en el juego.

---

## 8. Ejemplo Completo: El Oni (Sesiones 4 y 5)

### Sesión 4: El combate

**Entidades implicadas:**
- `Oni_Montaña_Kurai` (criatura, `known_by_scope=character`)
- `Kakita Asuka` (personaje jugador)
- `Kimi` (personaje jugador)
- `Bayushi Hisao` (personaje jugador — ausente)
- `Combate_Oni_S4` (evento)
- `Montañas_Kurai` (lugar)
- `Sesion_4` (sesión)

**Relaciones creadas en el grafo:**

```
(Combate_Oni_S4)-[:INVOLVES]->(Oni_Montaña_Kurai)
(Combate_Oni_S4)-[:INVOLVES]->(Kakita_Asuka)
(Combate_Oni_S4)-[:INVOLVES]->(Kimi)
(Combate_Oni_S4)-[:OCCURS_DURING]->(Sesion_4)
(Combate_Oni_S4)-[:OCCURS_IN]->(Montañas_Kurai)
```

**Relaciones de conocimiento derivadas (solo para presentes):**

```
(Kakita_Asuka)-[:HAS_FOUGHT {knowledge_quality:"fought", knowledge_confidence:1.0, known_from_session:4}]->(Oni_Montaña_Kurai)
(Kakita_Asuka)-[:PARTICIPATED_IN {known_from_session:4}]->(Combate_Oni_S4)
(Kimi)-[:HAS_FOUGHT {knowledge_quality:"fought", knowledge_confidence:1.0, known_from_session:4}]->(Oni_Montaña_Kurai)
(Kimi)-[:PARTICIPATED_IN {known_from_session:4}]->(Combate_Oni_S4)
```

**NO se crea conocimiento para Hisao.** Bayushi Hisao no estuvo presente; su personaje no tiene ninguna relación con el Oni ni con el evento en la sesión 4.

### Sesión 5: Kimi le cuenta a Hisao

**Texto de ejemplo:** *"Kimi le contó a Hisao sobre el Oni que encontraron en las montañas."*

**Relaciones creadas:**

```
(Kimi)-[:TELLS {shared_to_character:"Bayushi_Hisao", shared_at_session:5}]->(Bayushi_Hisao)
(Kimi)-[:TELLS_ABOUT {shared_to_character:"Bayushi_Hisao", shared_at_session:5}]->(Oni_Montaña_Kurai)
(Bayushi_Hisao)-[:HAS_HEARD_ABOUT {
  knowledge_quality:"heard_about",
  knowledge_confidence:0.7,
  shared_from_character:"Kimi",
  known_from_session:5
}]->(Oni_Montaña_Kurai)
```

A partir de la sesión 5, el jugador de Hisao puede ver al Oni en modo `character_knowledge`, pero con el nivel de detalle correspondiente a `HAS_HEARD_ABOUT` (ver apartado 9).

---

## 9. Diferencia de Detalle Según Calidad de Conocimiento

La calidad del conocimiento determina cuánto detalle ve el personaje sobre la entidad:

| Relación / Calidad     | Lo que ve el personaje                                                                 |
|------------------------|----------------------------------------------------------------------------------------|
| `HAS_FOUGHT`           | Nombre, tipo, descripción completa, lugar del encuentro, resultado del combate, todas las propiedades de combate visibles |
| `HAS_SEEN`             | Nombre, que existe, dónde fue visto, descripción visual básica                         |
| `HAS_HEARD_ABOUT`      | Solo el nombre, marcado como **rumor** (`knowledge_quality=rumor`), sin descripción ni localización confirmada |
| `KNOWS_ABOUT`          | Información básica pública: nombre, tipo general, nada confidencial                    |
| `DISCOVERED`           | Acceso completo a toda la información de la entidad disponible hasta esa sesión; el personaje es el descubridor registrado |

El visor aplica estos filtros al renderizar las fichas de entidad: una entidad conocida por `HAS_HEARD_ABOUT` muestra solo el nombre y la etiqueta "oído hablar", mientras que una conocida por `HAS_FOUGHT` muestra la ficha completa con stats de combate si los tiene.

---

## 10. Vista Normal por Sesión y Selector de Modo

### Vista por sesión

El visor ofrece un selector de sesión. Al elegir la sesión N, el usuario ve la información acumulada hasta esa sesión, filtrada según su modo activo. Las entidades y relaciones con `known_from_session > N` no aparecen.

### Selector de Modo

**Modos para jugadores:**

| Modo                  | Descripción                                                                |
|-----------------------|----------------------------------------------------------------------------|
| Sesión pública        | Solo información pública de la sesión seleccionada                         |
| Grupo                 | Todo lo que el grupo activo conoce en esa sesión                           |
| Mi personaje          | Solo lo que sabe el personaje activo (modo `character_knowledge`)          |

**Modos adicionales para admin:**

| Modo                  | Descripción                                                                |
|-----------------------|----------------------------------------------------------------------------|
| Jugador simulado      | Ver el grafo exactamente como lo vería un jugador concreto (para comprobación) |
| Narrador              | Vista narrador: todo menos `admin_only`                                    |
| Completo              | Vista `admin_full`: sin filtros                                            |

---

## 11. Panel /control/visibility

El panel de administración de visibilidad permite gestionar el conocimiento de forma manual cuando el pipeline automático no cubre un caso o cuando el narrador necesita ajustar.

### Acciones disponibles:

**Sobre entidades:**
- Marcar entidad como conocida por un personaje específico (crea relación `KNOWS_ABOUT` o la especificada).
- Marcar entidad como conocida por el grupo (`known_by_party=true`).
- Marcar entidad como pública (`known_publicly=true`).
- Ocultar entidad a jugadores específicos (override `known_by_scope=manual`).

**Sobre relaciones:**
- Marcar relación como secreta (`secret=true`): visible para narrador, oculta para jugadores.
- Marcar relación como descubierta por un personaje (`discovered_by=nombre`): se vuelve visible para ese personaje.
- Compartir relación con personaje o grupo.

**Transferencia de conocimiento:**
- Compartir entidad de un personaje a otro (crea `TELLS_ABOUT` + `HAS_HEARD_ABOUT`).
- Compartir entidad con todo el grupo (actualiza `known_by_party=true`).

---

## 12. Detección Automática en Extracción

El pipeline de extracción de texto (`rpg_schema.py` 1.4+) detecta patrones lingüísticos para crear automáticamente las relaciones de conocimiento correctas.

### Patrones y relaciones generadas:

| Patrón en texto                          | Relaciones creadas                                      |
|------------------------------------------|---------------------------------------------------------|
| "Asuka vio al Oni"                       | `(Asuka)-[:HAS_SEEN]->(Oni)`                           |
| "Kimi luchó contra el Oni"               | `(Kimi)-[:HAS_FOUGHT]->(Oni)`                          |
| "Hisao oyó hablar de un Oni"             | `(Hisao)-[:HAS_HEARD_ABOUT]->(Oni)` con `knowledge_quality=rumor` |
| "Kimi le contó a Hisao sobre el Oni"     | `(Kimi)-[:TELLS]->(Hisao)`, `(Kimi)-[:TELLS_ABOUT]->(Oni)`, `(Hisao)-[:HAS_HEARD_ABOUT]->(Oni)` |
| "Asuka descubrió el templo oculto"       | `(Asuka)-[:DISCOVERED]->(Templo)`                      |
| "Todos vieron el cadáver del samurái"    | entidad con `known_by_party=true`                      |

### Regla importante:

> "El Oni existe en las montañas" — Esta afirmación del narrador añade la entidad al grafo, pero **NO implica que ningún personaje la conozca**. Solo crea el nodo con `known_by_scope=narrator`. El conocimiento de los personajes se crea únicamente cuando el texto indica explícitamente quién lo vio, escuchó o descubrió.

---

*Fin del documento. Implementación de reglas de visibilidad: pendiente en visor/API.*
