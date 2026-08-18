# Requisitos para un futuro retro-relleno de `entity_id` (ENTREGABLE APARTE)

**Este carril NO sanea ni retro-rellena nada, y no toca producción.** Lo que
sigue son los requisitos que el trabajo de unicidad ha dejado a la vista para
que ese saneamiento —de otro carril y con decisión del operador— sea posible.
Es una lista de condiciones, no un plan de ejecución.

## Punto de partida medido (preflight de sólo lectura, otro agente)

- `:Entity` → 199 nodos, **0 con `entity_id`**. La propiedad no existe en toda
  la base. Tampoco `assertion_id`, `relation_id`, `id` ni `uuid`.
- `:V3Entity` no existe como etiqueta (0 nodos).
- `workspace` presente en los 199 y único: `"leyenda"`.
- **Cero constraints y cero índices** de aplicación.
- Colisiones de `entity_id`: **0 — pero de AUSENCIA, no de limpieza.**
- `canonical_name` **ya colisiona hoy**: 4 claves, mayor grupo 3, 9 nodos.

## Consecuencia directa

La derivación actual, `sha256(workspace \x1f superficie_normalizada \x1f tipo)`
(`data-engine/app/knowledge_v3/resolution/provisional.py`), se apoya en la
superficie del nombre. Aplicada tal cual a los 199 nodos actuales, **produciría
colisiones desde el minuto uno** en aquellos grupos que además compartan tipo, y
la restricción de unicidad no llegaría siquiera a poder crearse. Por eso la
barrera del resolver (`Neo4jGraphProvider.entity`, fail-closed con 2+) es la
única defensa que cubre este escenario, y por eso se ha implementado.

## Requisitos que un retro-relleno tendría que cumplir

1. **Derivación inyectiva sobre el corpus real, o desempate explícito.** Si dos
   entidades distintas y legítimas comparten `(workspace, superficie, tipo)`, la
   función no puede darles el mismo id. Hace falta o bien una dimensión más en
   la derivación (que **no** puede ser un contador ni un UUID sin romper el
   determinismo que `provisional.py` justifica), o bien una decisión humana de
   fusión/separación registrada como dato, no como efecto colateral del script.
2. **Medida ANTES de escribir.** El recuento de colisiones de la derivación
   candidata sobre el volcado real, publicado como cifra, y declarado total o
   cota. Cero colisiones medidas es la precondición de crear la restricción.
3. **La restricción se crea DESPUÉS del relleno, y su creación es la prueba.**
   Neo4j rechaza crear una restricción de unicidad que los datos ya violan: el
   `CREATE CONSTRAINT` es, él mismo, el verificador. Si falla, el relleno estaba
   mal y no hay que forzarlo.
4. **`workspace` presente en todo nodo direccionable.** La clave es
   `(workspace, entity_id)` — la que `writer/executor.py::_assert_absent` aplica
   ya en cada creación ("la identidad de un `entity_id`/`assertion_id` es única
   en todo el workspace, cruzando capa juego y todas sus partidas"). Ambas
   propiedades están siempre presentes en un nodo direccionable, así que la
   restricción cubre también la capa juego; lo que **no** cubre es un nodo sin
   `workspace`, que tampoco es direccionable. (La primera versión de este carril
   usó la terna con `partida_id` y dejaba la capa juego entera sin cubrir,
   porque Neo4j no aplica una restricción compuesta a un nodo al que le falta
   una propiedad y el lore se escribe con `partida_id: None`.)
5. **Ninguna URL durable puede cambiar de destino sin que alguien lo decida.**
   Un relleno que reasigne `entity_id` a un nodo ya enlazado rompe marcadores.
   Con la base actual esto no aplica (no hay `entity_id` que romper), pero el
   requisito se anota para el día que sí exista.

## Lo que NO es un requisito de este carril

Que el visor quede vacío contra los datos actuales (199 nodos sin `entity_id`,
excluidos por el Cypher del proveedor) es un **bloqueo de despliegue**, no un
defecto del código, y el operador lo ha separado explícitamente.
