# T1 y T2: la party deja de ser una ACL, la revelación se cablea

El tercer dictamen independiente dejó dos hallazgos que no eran defectos a
corregir sino **semántica a decidir**: las reglas de *party* y de *sesión
futura* existían en el motor pero no en el sistema real. Ningún escritor produce
`party`, `is_public` ni `session_index` —la ingesta usa `known_by_party`,
`known_publicly`, `known_from_session`— y el `ViewerContext` real no poblaba
`party_membership` ni `max_visible_session`. Dos reglas evaluándose sobre campos
inexistentes, con un contexto que nunca las activaba. En verde.

El operador decidió en direcciones opuestas, y esa asimetría es lo interesante.

## T1 — La party no será una ACL dinámica

**Retirada** como regla de autorización del visor.

El comportamiento que se rechaza:

```
party_membership actual
  → acceso automático a todo lo que esa party conoció alguna vez
```

En una campaña eso es semánticamente falso. Un personaje que se incorpora al
grupo en la sesión 20 no debería conocer el secreto que el grupo descubrió en la
sesión 3. Una ACL evaluada en cada petición no tiene memoria de *cuándo* se supo
algo, y por eso no puede expresar la pregunta que el producto necesita.

La party pasa a ser **fuente de concesión**, no frontera:

```
evento / revelación a la party P
        ↓
resolver miembros presentes / autorizados
        ↓
knowledge_grant individual
        ↓
known_by materializado
```

En consecuencia: `known_by_party` se conserva como procedencia de ingesta;
`party_membership` puede usarse al **crear** grants, pero no concede nada en
`can_view()`; `party` e `is_public` dejan de ser vocabulario autoritativo de
M5b; `known_publicly=true` se traduce explícitamente a contenido de jugador
publicado de esa partida. **No se mantiene una traducción permanente entre dos
modelos**: eso es lo que produce fugas más adelante.

Encaja con la decisión previa de que `known_by` sea la proyección actual de un
futuro `knowledge_grant` temporal.

## T2 — La sesión de revelación sí es requisito, y se cablea entera

Aquí la decisión es la contraria: **se conserva y se cablea de extremo a
extremo**. Poder decir qué podía conocer un personaje hasta una sesión dada es
una función central de S9 Knowledge.

Pero no sobre `session_index`. Hay que distinguir dos cosas que no son iguales:

| campo | significa |
|---|---|
| `session_index` | a qué episodio **pertenece** algo |
| `known_from_session` | desde qué sesión **puede revelarse** |

Si en la sesión 12 se descubre que un asesinato ocurrió cinco años antes, el
tiempo del evento es "hace cinco años", el episodio fuente es la sesión 12, y
`known_from_session` es 12. **El visor usa la revelación, no la cronología del
hecho.**

Semántica adoptada:

- `known_from_session = 0` → conocido desde el inicio. Es una **declaración
  positiva**, no una ausencia.
- `known_from_session = N` → invisible para una perspectiva con
  `max_visible_session < N`.
- Contenido **de partida** sujeto a progresión sin declararla → el writer lo
  rechaza antes de Neo4j. La ausencia no se interpreta como "siempre visible".
- Contenido de **ámbito juego** (manuales, reglas, lore compartido declarado) no
  está sujeto a esta barrera y no la exige.

### De dónde sale `max_visible_session`

Del **servidor**, nunca del cliente:

```
usuario → partida activa → concesión de partida → max_visible_session
```

Vive en `partida_access` (esquema v3), junto a `character_id`. Un
`?max_visible_session=99` sería una barrera que el propio protegido puede
levantar. **Sin tope declarado el tope es `0`**, no "sin límite" (ver el quinto
dictamen, más abajo): ver material no revelado exige `can_view_future = true`,
que `reviewer` y `admin` ya declaran positivamente.

Esto arregla además, de paso, el segundo apagado que señaló el dictamen:
`active_character` tampoco lo poblaba nadie, así que `knows()` devolvía siempre
`False` y **todo el mecanismo `known_by` era inerte en producción**.

### `known_by` no salta la barrera histórica

Corrección sobre el motor anterior, y el punto más fino de T2. `known_by` es la
proyección del estado **actual** de conocimiento: dice que el PJ lo sabe, no
desde cuándo. Si bastara para saltarse el tope:

```
PJ conoce el secreto desde la sesión 12; known_by contiene al PJ
usuario pide "ver como PJ hasta la sesión 5"
  → spoiler
```

...producido justamente por la función que existe para evitarlo. Hasta M5b-5,
sólo saltan el tope `can_view_future` explícito o, cuando exista el ledger
temporal, un `knowledge_grant` con `valid_from_session <= max_visible_session`.
Por eso la regla se evalúa **fuera** del `if not knows`.

`session_index` **no** se mantiene como alias silencioso: el motor lo ignora y
las fixtures se renombraron.

## El motor resultante

```
1. visibility válida            → si no, DENY
2. deny                         → DENY absoluto (también admin)
3. workspace                    → obligatorio y autorizado
4. scope                        → juego | partida, explícito
5. partida                      → partida activa autorizada
6. nivel                        → player / narrator / secret / reference
7. sesión de revelación         → known_from_session <= max_visible_session,
                                   salvo can_view_future
8. conocimiento individual      → known_by / knowledge_grant
9. visible
```

Y desaparece `party_membership → acceso directo`.

## Quinto dictamen: la ausencia tampoco vale aquí

El cuarto arreglo (escribir la progresión en la concesión) resultó ser **opt-in**,
y el quinto revisor lo reprodujo por HTTP real: `NULL` seguía significando "sin
tope", y un `ALTER TABLE ADD COLUMN` deja a `NULL` **todas** las concesiones
anteriores — precisamente las que motivaron el hallazgo. La barrera sólo actuaba
si el operador se acordaba de rellenar un campo opcional del formulario.

La corrección aplica aquí la misma regla que ya regía el ámbito: **una propiedad
ausente nunca se interpreta como el permiso más amplio.** Sin tope declarado, el
tope es `0`. Quien deba ver material no revelado lo obtiene por una capacidad
explícita (`can_view_future`, que ya tienen `reviewer` y `admin`), no por un
hueco en una tabla. La justificación anterior —"NULL = sin tope, para narrador"—
no se sostenía: no existe el rol `narrator`, y los dos roles que sí deben ver
futuro ya lo declaran positivamente.

Se corrigen además, del mismo dictamen:

- `_progresion_de_campana` fallaba **abierto**: base ausente, excepción o fila
  inexistente daban "sin tope". El comentario decía "no se inventa un tope"
  mientras inventaba el más permisivo de todos.
- El `UPDATE` usaba `COALESCE`, así que **la concesión de personaje no se podía
  revocar** desde el panel: reconceder con el campo en blanco no borraba nada, y
  como `active_character` salta la regla de nivel, lo que sobrevivía era un
  bypass invisible en la interfaz. Reconceder declara ahora el estado completo.
- `PartidaAccess` no leía las dos columnas nuevas y el panel no las mostraba: un
  permiso que el operador no ve es un permiso que no sabe que ha dado.
- La red anti-reincidencia de H-C **no podía detectar lo que decía detectar**:
  cubría campos de nodo pero no las dimensiones del contexto (o sea, no habría
  visto H-A), su filtro de exclusión dejaba entrar 169 ficheros de prueba —de
  modo que un campo presente sólo en fixtures contaba como productor real, el
  defecto del primer dictamen— y se satisfacía con una mención en un comentario
  o en una lista de prohibición. Ahora excluye pruebas y fixtures de verdad,
  descarta comentarios y cubre `max_visible_session` y `character_id`.
- `readonly.py` importaba `get_provider` sin usarlo, junto al filtrado: un resto
  que invita a saltarse la política por error.

## Estado

- 740 pruebas del visor y 196 de raíz en verde.
- La suite contra Neo4j efímero cubre ahora la revelación sobre datos reales:
  pasada visible, futura oculta, `known_by` que **no** salta el tope,
  `can_view_future` que sí, tope 0, valor corrupto que deniega sin error, y la
  coincidencia entre lista, conteos, grafo y acceso por ID.
- **Despliegue: sigue sin autorizar.** Requiere dictamen CONFORME de un revisor
  independiente. No vale que quien corrige declare CONFORME.
