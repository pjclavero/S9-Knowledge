# Especificación UX — Revisión de relaciones (v1)

> **ALCANCE Y ESTATUS.** Este documento es **solo diseño**. NO implementa rutas
> HTTP, NO define esquema de base de datos, NO toca el visor, el producto, las
> bases ni `.github`. Ninguna acción descrita aquí está construida ni conectada.
> Es una especificación de experiencia de usuario para una futura interfaz de
> revisión humana de relaciones candidatas. Cualquier verbo en futuro
> ("permitirá", "mostrará", "podrá") describe intención de diseño, no código
> existente.

Alineación de vocabulario: los términos usados aquí se toman **literalmente**
del contrato y de las señales ya implementadas en modo lectura, para no crear un
segundo vocabulario:

- Contrato de datos: `data-engine/app/relations/contracts.py`
  (`relation-candidate/internal-v1`).
- Señales heurísticas: `data-engine/app/relations/signals.py`
  (`relation-signals/v1`).
- Adaptador sintáctico: `data-engine/app/relations/syntax.py`
  (`relation-syntax/v1`).
- Consenso de revisores (shadow): `data-engine/app/external_ai/consensus.py`.

Esta UX **consume** esos artefactos; no los modifica ni redefine.

---

## 1. Principios rectores

1. **La UI no decide, la persona decide.** Igual que las señales producen
   evidencia y no decisiones, la interfaz presenta evidencia y recomendaciones;
   la aprobación siempre es un acto humano explícito.
2. **Nada se auto-aplica.** Las recomendaciones del consenso
   (`shadow_recommendation`) se muestran como sugerencia en **modo sombra**;
   nunca disparan una escritura por sí solas.
3. **Aislamiento por workspace.** Toda vista, lista y acción está acotada al
   `workspace` activo. No se mezclan candidatos de workspaces distintos en la
   misma pantalla ni en la misma acción masiva.
4. **Evidencia siempre visible.** Ninguna relación se revisa sin mostrar su
   `evidence_text` resaltada dentro de su `source_segment`, con `source_id` y
   `source_page`.
5. **Trazabilidad total.** Cada acción humana queda registrada (quién, qué,
   cuándo, sobre qué candidato, en qué workspace) y es reversible mientras la
   política lo permita.
6. **Determinismo de presentación.** El orden de señales, estados y candidatos
   es estable y reproducible, reflejando el orden determinista del pipeline.

---

## 2. Modelo de datos que la UI presenta (solo lectura del contrato)

La UI proyecta los 20 campos de `RelationCandidate` sin inventar ninguno.
Agrupación propuesta para presentación:

| Grupo UI | Campos del contrato |
|---|---|
| Tripleta | `subject_id`, `predicate`, `object_id`, `direction` |
| Tipos ontológicos | `subject_type`, `object_type` |
| Evidencia | `evidence_text`, `evidence_start`, `evidence_end`, `source_id`, `source_page`, `source_segment` |
| Modelado epistémico | `negated`, `temporal_scope`, `epistemic_status` |
| Procedencia del método | `extraction_method`, `model`, `confidence` |
| Gobierno | `workspace`, `validation_flags` |

Enumeraciones que la UI etiqueta con lenguaje humano (valor canónico → etiqueta):

- `direction`: `SUBJECT_TO_OBJECT` → "sujeto a objeto"; `OBJECT_TO_SUBJECT` →
  "objeto a sujeto"; `UNDIRECTED` → "sin dirección".
- `extraction_method`: `HEURISTIC` → "heurística"; `LLM_LOCAL` → "LLM local";
  `NVIDIA` → "IA externa (NVIDIA)"; `ONTOLOGY` → "ontología".
- `epistemic_status`: `ASSERTED` → "afirmado"; `RUMORED` → "rumoreado";
  `HYPOTHETICAL` → "hipotético"; `INTENDED` → "pretendido".

Regla de presentación heredada del contrato: una relación solo se rotula como
"hecho confirmado" en la UI si `is_affirmative()` sería verdadero, es decir
`negated == False` **y** `epistemic_status == ASSERTED`. En cualquier otro caso
la UI muestra un distintivo (negada / no afirmada) para evitar que la persona la
apruebe como hecho positivo por descuido.

---

## 3. Vistas

### 3.1 Vista por documento

Objetivo: revisar todas las relaciones extraídas de una misma fuente en su
contexto textual.

- Encabezado: `source_id`, título de la fuente, `workspace`, contador por estado
  de consenso.
- Panel izquierdo: el `source_segment` / documento con **todas** las evidencias
  resaltadas; al pasar el foco por una relación se resalta su
  `[evidence_start, evidence_end)`.
- Panel derecho: lista de relaciones candidatas de ese documento, ordenadas de
  forma determinista (por posición de evidencia y luego por identificador).

```
+-------------------------------------------------------------------------+
| Documento: grimorio-cap03  ·  workspace: campaña-norte  ·  pág. 12      |
| Consenso:  STRONG 4 · PARTIAL 2 · CONFLICT 1 · HUMAN 1 · INVALID 0      |
+----------------------------------+--------------------------------------+
| ...el capitán [Aldric] juró      | > Aldric  PERTENECE_A  Guardia_Gris  |
| lealtad a la [Guardia Gris] tras |   afirmado · dir: sujeto->objeto     |
| la caída de Vardh. Nunca sirvio  |   consenso: STRONG · conf 0.88       |
| a los [Cuervos]...               | ------------------------------------ |
|   ^^^^^^ evidencia resaltada     | > Aldric  SIRVE_A  Cuervos           |
|                                  |   [NEGADA] · dir: sujeto->objeto     |
|                                  |   consenso: PARTIAL · conf 0.61      |
+----------------------------------+--------------------------------------+
```

### 3.2 Vista por entidad

Objetivo: ver la vecindad relacional de una entidad concreta.

- Cabecera de entidad: `id`, tipo ontológico, workspace.
- Dos secciones: relaciones donde la entidad es **sujeto** y donde es **objeto**,
  respetando `direction`.
- Agrupación por `predicate` normalizado (MAYÚSCULAS con guion_bajo, tal como lo
  produce `normalize_predicate`).
- Marca de duplicados potenciales: candidatos que comparten
  (subject, predicate, object) o (subject, predicate) con distinto objeto se
  agrupan para facilitar "marcar duplicado" o "fusionar".

```
+-------------------------------------------------------------------------+
| Entidad: Aldric  ·  tipo: Character  ·  workspace: campaña-norte        |
+-------------------------------------------------------------------------+
| Como SUJETO                                                             |
|   PERTENECE_A  -> Guardia_Gris     STRONG   conf 0.88   [afirmado]      |
|   SIRVE_A      -> Cuervos          PARTIAL  conf 0.61   [negada]        |
|   POSEE        -> Espada_de_Vardh  CONFLICT conf 0.55   (2 candidatos)  |
| Como OBJETO                                                            |
|   <- LIDERA    Comandante_Ruvel    HUMAN    conf 0.49   [rumoreado]     |
+-------------------------------------------------------------------------+
```

### 3.3 Vista por conflicto

Objetivo: priorizar los casos que el consenso no resolvió con acuerdo fuerte.

- Filtra por estado de consenso: `MODEL_CONFLICT`, `HUMAN_REQUIRED`,
  `INVALID_RESPONSES`, `PARTIAL_CONSENSUS`.
- Muestra las decisiones de ambos revisores lado a lado (`reviewer_a`,
  `reviewer_b`), la adjudicación si existe y el campo `reason`.
- Es la cola de trabajo principal para la persona revisora.

```
+-------------------------------------------------------------------------+
| Conflictos · workspace: campaña-norte · 3 pendientes                    |
+-------------------------------------------------------------------------+
| Aldric POSEE Espada_de_Vardh                     estado: MODEL_CONFLICT |
|   Revisor A: reject   (evidencia: "...perdio la espada...")            |
|   Revisor B: accept   (evidencia: "...portaba la espada...")          |
|   Adjudicación: (ninguna)   ·   Recomendación sombra: human            |
|   Motivo: "Conflicto de polaridad entre revisores (a=reject, b=accept)"|
|   [ Aprobar ] [ Editar ] [ Rechazar ] [ Escalar ] [ Aplazar ]          |
+-------------------------------------------------------------------------+
```

---

## 4. Panel de detalle de una relación

Al abrir un candidato, la UI despliega un panel de detalle con toda la evidencia
explicable. Ninguna sección es opcional para el conflicto; para acuerdos fuertes
las secciones densas pueden ir colapsadas.

### 4.1 Tripleta y tipos

Muestra `subject_id --[predicate]--> object_id` con `direction`, más
`subject_type` / `object_type`. Si un tipo no está en `ALLOWED_ENTITY_TYPES`
(`Character, Location, Faction, Object, Event, Concept`), se marca como aviso.

### 4.2 Evidencia resaltada

`source_segment` completo con `[evidence_start, evidence_end)` resaltado y cita
literal `evidence_text`. Se muestran `source_id`, `source_page`,
`source_segment`. Regla del contrato: si `extraction_method != ONTOLOGY`, la
evidencia textual es obligatoria; una relación ontológica sin evidencia se rotula
"derivada de ontología" en vez de mostrar cita vacía.

### 4.3 Modelado epistémico

Distintivos para `negated`, `epistemic_status` y `temporal_scope`
(`temporal_scope` puede ser nulo). La negación y un `epistemic_status` distinto
de `ASSERTED` se muestran de forma prominente porque cambian el significado de
aprobar.

### 4.4 Señales heurísticas (`relation-signals/v1`)

Se listan las 13 señales en su orden estable. Cada fila muestra `name`, `value`,
la `evidence` (cita literal) y la `explanation` legible. Las señales son
**evidencia, no decisión**; la UI lo indica explícitamente.

| Señal | Qué informa |
|---|---|
| `distance` | caracteres/tokens entre menciones |
| `same_sentence` | si comparten frase |
| `same_clause` | si comparten cláusula |
| `type_compatibility` | categorías ontológicas compatibles (MEMBERSHIP, LOCATION, POSSESSION, PARTICIPATION) |
| `svo_pattern` | verbo-cue entre menciones (sujeto-verbo-objeto) |
| `membership` | marcador de pertenencia |
| `possession` | marcador de posesión |
| `location` | marcador de ubicación |
| `negation` | marcador de negación |
| `temporality` | marcadores/fechas de alcance temporal |
| `modality` | probabilidad/obligación |
| `rumor` | marcador de rumor (epistémico) |
| `repetition` | número de co-ocurrencias documentales |

```
+-------------------------------------------------------------------------+
| Señales heurísticas (evidencia, no decisión)                            |
+---------------------+-----------+-----------------------+---------------+
| señal               | valor     | evidencia             | explicación   |
+---------------------+-----------+-----------------------+---------------+
| same_sentence       | true      | "Aldric juro lealtad  | misma frase   |
|                     |           |  a la Guardia Gris"   |               |
| negation            | false     | ""                    | sin marcador  |
| repetition          | 3         | "..." || "..." ||"..."| co-ocurre x3  |
| type_compatibility  | [MEMBER.] | Character->Faction    | compatible    |
+---------------------+-----------+-----------------------+---------------+
```

### 4.5 Explicación sintáctica (`relation-syntax/v1`)

Señales estructurales del adaptador sintáctico: sujeto/verbo/objeto aproximados,
voz pasiva, negación estructural, idioma detectado y modo degradado si el
proveedor no aplica reglas específicas del idioma. Se presenta como apoyo a la
interpretación, marcando cuándo el análisis corre en modo degradado.

### 4.6 Recomendaciones de proveedores (modo sombra)

Muestra, por revisor, la decisión propuesta sin aplicarla:

- **LLM local** (`extraction_method = LLM_LOCAL`, `model`).
- **IA externa NVIDIA** (`extraction_method = NVIDIA`, `model`), en sombra.

La UI deja claro con una etiqueta persistente "SOMBRA — no se aplica" que estas
recomendaciones no escriben nada.

### 4.7 Razones del consenso

Del `ConsensusResult`: `state`, `shadow_recommendation`, `reviewer_a`,
`reviewer_b`, `adjudication` (si hay) y `reason` textual. Mapeo de estados a
etiqueta humana:

| Estado (`external_ai.models`) | Etiqueta UI | Significado |
|---|---|---|
| `STRONG_CONSENSUS` | Acuerdo fuerte | decisión, nombre, tipo y evidencia coinciden |
| `PARTIAL_CONSENSUS` | Acuerdo parcial | misma polaridad, difieren detalles |
| `MODEL_CONFLICT` | Conflicto | polaridades opuestas o uno incierto |
| `INVALID_RESPONSES` | Respuesta inválida | falta decisión de algún revisor |
| `HUMAN_REQUIRED` | Requiere humano | ambos revisores inciertos |

Recomendaciones sombra posibles (`shadow_recommendation`): `accept`, `edit`,
`reject`, `use_existing`, `uncertain`, `human`. La UI las muestra como
sugerencia, nunca preseleccionadas de forma que un envío accidental las aplique.

---

## 5. Acciones futuras (NO implementadas)

> Ninguna de estas acciones está construida. Esta sección define **intención de
> diseño** de la barra de acciones. No hay rutas ni persistencia detrás.

| Acción | Descripción de diseño | Efecto epistémico previsto |
|---|---|---|
| **Aprobar** | Aceptar la relación tal cual. Requiere `is_affirmative()` o confirmación explícita si está negada / no afirmada. | Marca candidata como aceptada para futura promoción (no escribe grafo en este lote). |
| **Editar** | Corregir `predicate`, tipos, `direction`, límites de evidencia o modelado epistémico antes de aceptar. | Registra la relación editada y el diff frente al original. |
| **Rechazar** | Descartar la relación. Pide motivo. | Marca rechazada con razón trazable. |
| **Marcar duplicado** | Señalar que otra candidata expresa lo mismo. | Enlaza a la relación canónica elegida. |
| **Usar relación existente** | Equivalente a `use_existing`: apuntar a una relación ya presente en lugar de crear otra. | Referencia la existente; evita duplicación. |
| **Fusionar relaciones** | Combinar dos o más candidatas (misma tripleta / evidencia complementaria) en una. | Consolida evidencia y procedencia de las fuentes fusionadas. |
| **Solicitar reprocesado** | Pedir que el pipeline recalcule señales/consenso (p. ej. tras corregir tipos). | Encola reproceso; no lo ejecuta en este lote. |
| **Aplazar** | Posponer sin decidir. | Mueve a "aplazadas"; conserva estado. |
| **Escalar** | Derivar a revisor con más permisos (conflictos difíciles). | Cambia asignación; añade nota. |

Reglas de coherencia de diseño:

- **Aprobar** una relación con `negated == True` o `epistemic_status != ASSERTED`
  exige confirmación adicional que reconozca explícitamente que **no** es un hecho
  positivo confirmado.
- **Fusionar** y **marcar duplicado** solo entre candidatas del **mismo
  workspace**.
- **Usar relación existente** debe resolver a un único destino; si hay ambigüedad
  (equivalente al `use_existing_conflict` del consenso), la UI obliga a elegir.

---

## 6. Seguridad UX

### 6.1 Confirmación de acciones masivas

- Toda acción sobre selección múltiple muestra un diálogo con recuento exacto,
  desglose por estado de consenso y por workspace, y la acción a aplicar.
- Las acciones destructivas o irreversibles (rechazo masivo, fusión masiva)
  requieren confirmación reforzada (escribir/confirmar el número de elementos).
- Una acción masiva **nunca** cruza workspaces: si la selección abarca varios,
  la UI la bloquea y obliga a filtrar por uno.

### 6.2 Separación por workspace

- El `workspace` activo es visible en todo momento y forma parte de cada acción.
- No existe vista, búsqueda ni acción que combine candidatos de distintos
  workspaces (mutación 9 del gate de calidad: "mezcla de workspaces" prohibida).

### 6.3 Permisos

- Roles de diseño: *lector* (solo ver), *revisor* (aprobar/editar/rechazar/
  duplicado/existente/aplazar), *revisor sénior* (además fusionar, reprocesar,
  resolver escalados), *administrador* (gestión de workspace).
- Las acciones no permitidas aparecen deshabilitadas con motivo, no ocultas sin
  explicación, para que el permiso sea comprensible.

### 6.4 Trazabilidad

- Cada acción registra: actor, acción, `candidate_id`, `workspace`, marca de
  tiempo, estado previo y posterior, y motivo si aplica.
- El panel de detalle incluye un historial cronológico de la relación.

### 6.5 Deshacer

- Acciones reversibles ofrecen deshacer inmediato (ventana breve) y reversión
  desde el historial mientras la política lo permita.
- Deshacer es en sí una acción trazada; no borra el registro anterior.

### 6.6 Prevención de doble envío

- Cada envío de acción lleva una clave de idempotencia por (candidato, acción,
  versión vista); reintentos con la misma clave no duplican el efecto.
- El control se deshabilita en el instante del envío y muestra estado de
  progreso hasta la confirmación del servidor.
- Si la vista quedó obsoleta (otra persona actuó antes), la UI detecta el
  desajuste de versión y pide recargar en lugar de sobrescribir a ciegas.

### 6.7 Accesibilidad

- Contraste suficiente; el estado de consenso y la negación no se comunican solo
  por color (llevan texto/icono).
- Todos los controles tienen nombre accesible; las evidencias resaltadas exponen
  su texto a lectores de pantalla.
- Objetivos táctiles amplios; respeta preferencias de movimiento reducido.

### 6.8 Navegación por teclado

- Toda la revisión es operable sin ratón: mover entre candidatos, abrir detalle,
  y ejecutar acciones mediante atajos anunciados.
- Atajos propuestos (mnemotécnicos, configurables): `a` aprobar, `e` editar,
  `r` rechazar, `d` marcar duplicado, `u` usar existente, `f` fusionar,
  `p` aplazar, `s` escalar, `j`/`k` siguiente/anterior. Las acciones destructivas
  piden confirmación aunque se invoquen por teclado.
- Foco visible y orden de tabulación lógico (evidencia → señales → acciones).

### 6.9 Estados de carga

- Esqueletos de carga por panel; la evidencia y las acciones no se muestran como
  listas hasta tener datos completos, para no inducir decisiones sobre datos
  parciales.
- Cargas largas (señales/consenso) muestran progreso sin bloquear la lectura de
  lo ya disponible.

### 6.10 Errores parciales

- Si una parte falla (p. ej. el consenso no cargó pero la evidencia sí), la UI
  muestra el fallo localizado con reintento, sin ocultar el resto.
- Una acción masiva con resultados mixtos informa por elemento qué tuvo éxito y
  qué falló, y permite reintentar solo los fallidos.
- Un `INVALID_RESPONSES` de un candidato no invalida el lote: se muestra ese caso
  como pendiente sin bloquear a los demás (coherente con el consenso por
  candidato).

---

## 7. Fuera de alcance (explícito)

- No se definen endpoints, contratos HTTP ni esquemas de base de datos.
- No se implementa ningún componente de UI ni se toca el visor.
- No se conecta ningún proveedor (LLM local ni NVIDIA); sus recomendaciones se
  describen solo como presentación en modo sombra.
- No se promueve ninguna relación al grafo: aprobar/fusionar aquí son conceptos
  de diseño, sin escritura.

---

## 8. Trazabilidad de vocabulario (fuentes leídas)

| Concepto UI | Fuente en el código |
|---|---|
| 20 campos, enums, `is_affirmative`, `REFLEXIVE_PREDICATES` | `relations/contracts.py` |
| 13 señales y sus `name/value/evidence/explanation` | `relations/signals.py` |
| Sujeto/verbo/objeto, voz pasiva, idioma, modo degradado | `relations/syntax.py` |
| Estados de consenso, `shadow_recommendation`, `reason`, `use_existing_conflict` | `external_ai/consensus.py` |

Este documento no altera ninguna de esas fuentes; las referencia para mantener un
único vocabulario.
