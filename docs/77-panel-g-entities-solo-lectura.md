# Hueco G del chasis — Panel de Entidades, SOLO LECTURA

Primera vuelta del carril G sobre el chasis de montaje (`docs/69`), sobre la
autorización que dejó el P0 de autoridad única (`docs/75`) y sobre la doctrina
de contadores de `docs/73`. Objetivo declarado: **un panel de entidades de solo
lectura montado sobre el chasis y la autorización actuales, con gate verde** —
no un gestor de entidades.

Árbol medido: rama `feat/panel-entities-g`, nacida de `main` `1f70726`.

**G es el hueco de rol MÁS BAJO de los cuatro** (`viewer`, contra `reviewer` de
C y F y `admin` de B). Es, por tanto, el panel con mayor superficie de
exposición, y todo lo que sigue está escrito con ese sesgo: lo que más se mide
aquí es qué ve quien menos derecho tiene.

## 1. Qué muestra, y de dónde sale cada dato

Dos pantallas, ambas GET, ambas alimentadas por **un único origen**: el
proveedor que entrega `get_filtered_provider` (es decir,
`PolicyFilteredProvider` envolviendo al proveedor base). No hay ninguna
consulta al proveedor crudo, ni un segundo camino de datos.

| Pantalla | Ruta | Dato | Origen exacto |
|---|---|---|---|
| Lista | `/panel/entities` (`chassis_entities`) | filas de entidad | `provider.list_entities(ws, …)` → `serializers.serialize_node` |
| | | contador «visibles» | `provider.list_entities(ws, limit=1, offset=0)[1]` — total del ámbito autorizado, sin filtros de presentación |
| | | contador «tras filtros» | `provider.list_entities(…)[1]` con los filtros aplicados |
| | | contador «en esta página» | `len(filas)` |
| | | facetas de tipo | `provider.entity_types(ws)` (recuento sobre nodos ya filtrados) |
| | | etiqueta de estado de revisión | `serialize_node` → `labels.review_status_label` (contrato `review-status/v1`) |
| Ficha | `/panel/entities/item/{entity_id}` (`chassis_entities_item`) | entidad | `provider.entity(entity_id)` → `serialize_node` |
| | | relaciones | `provider.relations_for_entity(entity_id)` → `serialize_edge`, con el otro extremo resuelto por `provider.entity(...)` |

**Nada de esto es una capacidad nueva.** Los cuatro métodos ya los usaban
`/entities`, `/entities/{id}`, `/api/entities` y `/api/entities/{id}`. Este
carril **no ha añadido ni un endpoint de backend**, ni ha tocado el proveedor,
ni la política. Lo que sí se rechazó por quedar fuera del alcance conservador:

- búsqueda por relación o navegación de vecindad a más de un salto (exigiría
  una consulta nueva en el proveedor);
- exportación (CSV/JSON) del listado (endpoint nuevo);
- `source_kind`, `visibility` y `quality_status` como filtros de la pantalla:
  el proveedor los acepta, pero publicarlos como facetas obliga a decidir si el
  conjunto de valores ofrecidos es a su vez un canal de inferencia, y eso es
  medida propia que esta vuelta no trae.

La validación de parámetros de listado (tope de página, longitud de `q`, lista
blanca de ordenaciones) se **importa** de `routers/readonly.py`
(`_validate_query_params`) en vez de reescribirse: una segunda copia sería una
segunda política de recorte capaz de divergir en silencio.

## 2. Montaje: el contrato, sin renegociarlo

Prefijo `/panel/entities`, nombre de ruta `chassis_entities`, rol `viewer`,
plantilla `chassis/entities.html`, interruptor `S9K_PANEL_G_ENABLED` — los
cuatro valores salen de `FEATURE_SLOTS`, no de una cadena escrita en el módulo.
La tabla `CONTRATO_PUBLICADO` de `test_chassis_mount_contract.py` **no se ha
tocado**.

Se añade una ruta de detalle, `chassis_entities_item`
(`/panel/entities/item/{entity_id}`), que **no** entra en `NAV`: es una ficha a
la que se llega desde la lista, no una entrada de menú
(`test_la_ficha_no_es_una_entrada_de_menu`).

Guarda e interruptor, **en ese orden**: `slot_guard(SLOT)` primero,
`slot_enabled(SLOT)` después. Encender un panel no autoriza a nadie, y con el
orden invertido un anónimo enumera qué paneles están encendidos comparando 404
contra 302 (calibrado: **G2**).

Ninguna URL escrita a mano en las plantillas: todo enlace y todo `action` se
resuelve por nombre de ruta con `url_for` (calibrado: **G14**).

## 3. Qué ve un ANÓNIMO con la autenticación desactivada

Es el apartado central de este carril, y va con la medida delante.

`build_viewer_context` degrada a `role="anonymous"` cuando `S9K_AUTH_ENABLED`
está desactivado: sin principal no hay autoridad (`docs/75`). El aviso crítico
que dejó medido el carril C (`docs/76 §3`) aplica aquí **con más fuerza**,
porque este panel lee del grafo y su rol publicado es el más bajo del sistema.

Medida directa, sobre la app real, con el proveedor BASE sustituido por una
matriz de once nodos —uno por barrera de la política— y **la cadena de
autorización real atravesada entera** (`get_filtered_provider` →
`get_visibility_context` → `build_viewer_context` → `PolicyFilteredProvider` →
`VisibilityPolicy`). Workspace del visor: `alpha`.

| Entidad de la matriz | Barrera que la gobierna | ¿En la lista? | ¿Cuenta? | Ficha por ID |
|---|---|---|---|---|
| `lore-player` (`scope=juego`, `visibility=player`) | ninguna: lore compartido | **sí** | **sí** | **200, con el texto completo** |
| `lore-secreto` (`visibility=secret`) | regla 3 · `can_view_secret=False` | no | no | 404 |
| `lore-narrador` (`visibility=narrator`) | regla 3 · capa GM | no | no | 404 |
| `lore-referencia` (`visibility=reference`) | regla 3 · `can_view_reference=False` en anónimo | no | no | 404 |
| `lore-futuro` (`known_from_session=3`) | regla 4 · tope `NOT_APPLICABLE` | no | no | 404 |
| `partida-A` (`scope=partida`) | regla 2b · `allowed_partida_ids` vacío | no | no | 404 |
| `workspace-ajeno` (`workspace=beta`) | regla 2 · workspace | no | no | 404 |
| `sin-scope` (sin `scope`) | regla 2b · ámbito no declarado | no | no | 404 |
| `visibilidad-rara` (`visibility=publico`) | regla 0 · vocabulario cerrado | no | no | 404 |
| `visibilidad-deny` (`visibility=deny`) | regla 0 · estado terminal | no | no | 404 |
| `known-by-malformado` (`known_by="PJ01"`) | regla 2c · campo de autorización ilegible | no | no | 404 |
| | | | **total 1 de 11** | |

Lo que esta tabla dice, en una frase: **con auth desactivada un anónimo SÍ ve
lore de capa juego, y su ficha responde 200 con el contenido**. Todo lo demás
—incluido, y esto es lo importante, todo el material con `partida_id`— queda
fuera de la lista, fuera de los contadores y fuera del acceso por ID.

Y lo que **no** dice: no es una vía reabierta por este carril. Es la política
heredada aplicada de forma consistente, y el mutante **G3** lo confirma —leer
por el proveedor crudo en vez del filtrado pone en rojo cinco pruebas—. Tampoco
se ha «arreglado» por cuenta propia: se ha medido, se ha declarado y se ha
fijado como test (`test_tabla_de_lo_que_ve_un_anonimo_con_auth_desactivada`,
once celdas, bidireccional).

### La `visibility` SÍ se normaliza, y la normalización es SIMÉTRICA

Conviene escribirlo porque leído a medias parece lo contrario. `can_view`
normaliza el valor almacenado (`raw.strip().lower()`) **antes** de contrastarlo
con el vocabulario cerrado, así que mayúsculas y espacios no cambian la
decisión. Lo que importa es que eso vale en **las dos direcciones**: no sólo
`PLAYER` sigue siendo visible, sino que `SECRET`, `NARRATOR` y `DENY` en
mayúsculas siguen denegando. Medido sobre el panel, con un anónimo:

| `visibility` almacenada | ¿en la lista? | ficha |
|---|---|---|
| `player` / `PLAYER` / `" Player "` | sí | 200 |
| `secret` / `SECRET` / `" SECRET "` | no | 404 |
| `narrator` / `NARRATOR` | no | 404 |
| `deny` / `DENY` | no | 404 |
| `reference` / `REFERENCE` | no | 404 |

Es decir: la normalización **no es una vía de fuga**. Sería un defecto si sólo
se aplicara al lado permisivo —un `SECRET` que se cayera del vocabulario y
acabara tratado como dato inválido *más permisivo*—, y no es el caso: el
vocabulario es cerrado y un valor irreconocible deniega (`visibility_invalid`).

**La tabla es bidireccional a propósito.** Una tabla de sólo noes se satisface
con un panel roto que no muestra nada nunca, así que:

- la celda que dice **sí** exige además que la ficha entregue el CONTENIDO, no
  sólo un 200;
- `test_un_viewer_autenticado_ve_MAS_que_un_anonimo` mide el contraste con un
  principal real: un `viewer` autenticado tiene `can_view_reference=True` y el
  anónimo no, así que ve **2** entidades donde el anónimo ve **1**;
- `test_una_partida_activa_abre_su_material_y_solo_el_suyo` mide la otra
  dirección: con `partida-A` activa, `partida-A` aparece y responde 200,
  mientras `lore-secreto` sigue en 404;
- `test_el_control_de_autorizacion_COLAPSA` exige que un `admin` vea lo que un
  `viewer` no ve. Si cambiar el principal no cambiara el resultado, la cadena
  estaría inerte y toda la tabla sería adorno.

**Un panel vacío en ese contexto es CORRECTO**, y también está fijado: sin lore
de capa juego, un anónimo recibe `data-state="empty"` y contador `0`
(`test_un_panel_vacio_para_un_anonimo_es_correcto`). No es una pantalla que
arreglar.

### Vocabulario de autorización: ninguno propio

El router no compara roles, no lee `admin_full`, no evalúa `known_by`,
`can_view_secret`, `allowed_partida_ids`, `max_visible_session` ni
`partida_in_scope`, y no importa `get_provider` (el crudo). Se comprueba
**sobre el AST**, no leyendo el fichero: una mención en un comentario no cuenta
ni a favor ni en contra
(`test_el_panel_no_declara_vocabulario_propio_de_autorizacion`,
`test_el_panel_usa_el_proveedor_filtrado_y_no_el_crudo`; mutante **G15**).

**No ha hecho falta ninguna dimensión que el registro M5b no declare.** Las
cinco que gobiernan lo que este panel muestra —`visibility`, `known_by`,
workspace, partida y tope de sesión— se evalúan donde ya vivían.

### El punto de inyección congelado no se toca

`get_visibility_context` se llama como **función normal** desde
`get_filtered_provider`, así que sustituirlo con `dependency_overrides` es
**inerte**: saldría verde sin morder. Esta suite no lo usa. Lo que sustituye es
el **proveedor BASE** (`app.deps.get_provider`), de modo que la política corre
de verdad encima, y que el control puede **colapsar** se exige con un test, no
con una nota al pie.

## 4. Frontera de SOLO LECTURA, y cómo se garantiza

Tres capas, ninguna de ellas prosa:

1. **Enumeración del ESPACIO DE URL, no del módulo.** Se recorren las rutas de
   la **app** bajo `SLOT.prefix` con `iter_mounted_routes` —el mismo censo que
   usa el barrido de autorización del chasis—, y la superficie de escritura se
   pregunta a `write_methods`, que **falla cerrado**: una ruta sin `methods`
   enumerables (un WebSocket, un `Mount` opaco) se declara capaz de escribir.
   Es el patrón que dejó medido `docs/76 §4bis`, y se calibra con la escritura
   colgada **desde `main.py`** (**G9**) y con una sub-app montada bajo el
   prefijo (**G10**): comprobar el propio router deja las dos puertas abiertas.
2. **Suelo de plausibilidad.** Un arnés que enumera 0 rutas «demostraría»
   cualquier cosa. Se exige ver **≥ 3 rutas con path RESOLUBLE** y, nombradas,
   las dos que este carril declara (`/panel/entities` y
   `/panel/entities/item/{entity_id}`). Sólo cuentan las resolubles a
   propósito: `route_in_prefix` falla cerrado, así que una ristra de rutas con
   path indeterminable caería «dentro» del prefijo y el suelo se cumpliría a sí
   mismo con el propio fallo cerrado. Calibrado: **G11**.
3. **Frontera de SEGMENTO, con las dos bandas.** `/panel/entitiesXYZ/borrar`
   **no** es de este panel y el gate no puede acusarlo (**G12**, falso
   positivo), y el contrapeso exige que la frontera no se convierta en un
   «siempre False» que apague el gate (`test_el_gate_si_reclama_lo_que_es_suyo`).
   Importa aquí más que en C: `/entities` ya existe en el visor.

Y la otra mitad, la que la enumeración de rutas **no** cubre: que el camino GET
que sí existe no ejerza ningún efecto lateral.
`test_recorrer_el_panel_solo_invoca_lecturas_del_proveedor` usa un proveedor
espía que registra cada método invocado y exige que todos estén en la lista de
lecturas de la interfaz `GraphProvider`. Calibrado con **G13**: se inyecta una
llamada a un método de escritura y el espía la caza.

En la **interfaz** tampoco hay acciones: el único `<form>` es `method="get"` y
no aparece ningún botón de editar, fusionar, renombrar o borrar
(`test_las_plantillas_no_ofrecen_ninguna_accion_de_escritura`, mutante
**G16**). No es redundante con lo anterior: aquello prueba que nadie **puede**
escribir; esto, que el panel no lo **ofrece**. Un botón que promete fusionar y
no puede es una funcionalidad anunciada y ausente.

## 5. Indistinguibilidad y contadores

**Recurso no autorizado == inexistente.** `PolicyFilteredProvider.entity`
devuelve `None` tanto para una entidad que no existe como para una existente y
no visible, y aquí las dos acaban en el **mismo 404 con el mismo cuerpo**. Se
comparan **código y cuerpo**, no sólo el código, contra las diez entidades
ocultas de la matriz. El mutante **G7** mete el id pedido en el cuerpo del 404 —
lo justo para que el cuerpo varíe con la petición— y las dos pruebas se ponen
rojas.

La revisión independiente la midió **más fuerte de lo que este documento
afirmaba**: comparó el cuerpo **byte a byte por sha256** y las **cabeceras
completas**, y los diez ocultos salen idénticos al inexistente —**34 bytes**, sin
eco del identificador, ni con `<script>` ni con 200 caracteres—.

### Un id con `/` sale por el ENRUTADO, no por el handler (menor, declarado)

Medido, y con el matiz que importa:

```
'no-existe'                  404, 34 bytes, sha256 0219103e…
'lore-secreto'               404, 34 bytes, sha256 0219103e…   (idéntico)
'xxxx…' (200 caracteres)     404, 34 bytes, sha256 0219103e…   (idéntico)
'<script>alert(1)</script>'  404, 22 bytes, sha256 37ec4665…
'a/b'                        404, 22 bytes, sha256 37ec4665…   (idéntico)
```

Un identificador que contiene `/` no encaja en
`/panel/entities/item/{entity_id}`, así que lo rechaza el enrutado de Starlette
**antes** de llegar a este panel y el cuerpo es el genérico de 22 bytes. Nótese
que el caso de `<script>` **no** es una particularidad del marcado: lo que lo
desvía es la barra de la etiqueta de cierre.

**No rompe la indistinguibilidad**, y no por afirmación sino por medida: la
diferencia la marca la **forma del identificador**, no la existencia del
recurso. Una entidad que **sí existe** y cuyo id lleva barra recibe exactamente
la misma respuesta —mismo sha256— que un id con barra que no existe, y su
contenido no se escapa por esa vía. Lo fija
`test_un_id_con_barra_no_llega_al_handler_y_TAMPOCO_distingue`, que lleva además
el control positivo de que el 404 del handler **sí** es otro cuerpo: sin él, la
prueba sería compatible con que todo diese 22 bytes.

**Contadores después de la autorización, y del conjunto autorizado.**
`list_entities` del proveedor filtrado aplica la política sobre el conjunto
entero y **sólo entonces** pagina, así que su `total` es «cuántas autorizadas
hay», nunca «cuántas hay en la base». Es la misma doctrina que `graph_view.py`
y `docs/73`: un total calculado antes de filtrar revelaría **por diferencia** lo
que la política acaba de ocultar.

Y se hace la comprobación que `docs/73` exige a quien publique cifras: **barrer
el tope de página**. Medido con un principal que ve 2 entidades de 11:

| `limit` | 1 | 2 | 5 | 50 | 200 | 2000 |
|---|---|---|---|---|---|---|
| contador «visibles» | 2 | 2 | 2 | 2 | 2 | 2 |
| contador «tras filtros» | 2 | 2 | 2 | 2 | 2 | 2 |

El total no se mueve: es propiedad del conjunto autorizado, no del recorte. El
mutante **G4** cambia esa cifra por el total del proveedor **crudo** (10) y
pone en rojo tres pruebas — es exactamente el canal de inferencia que `docs/73`
describe.

**Ausencia ≠ cero.** Si el proveedor falla, la pantalla entra en estado de
error y **no publica ninguna cifra**: un `0` ahí afirmaría «hay cero entidades
autorizadas» cuando lo cierto es «no se pudo saber» (mutante **G5**). Y un
anónimo con auth activa no recibe ninguna cifra en absoluto: recibe la
redirección a `/login`.

**Estados desconocidos, fallo cerrado.** Un `review_status` fuera del
vocabulario canónico se pinta como `no reconocido (…)` y nunca con el aspecto
de un estado legítimo; la decisión vive en `labels.review_status_label` contra
el contrato `review-status/v1`, y aquí no hay una segunda lista. Los errores
publican `type(exc).__name__`, **nunca** `str(exc)`: el proveedor de la prueba
lanza un mensaje con una URI con credenciales a propósito, y el test lo vería
salir (mutante **G6**).

## 6. Calibración: cada garantía puesta en rojo

`python3 scripts/calibrar_panel_entities.py`. Por cada caso: sha256 del
fichero, mutación efímera, ejecución del subconjunto **nombrado** de tests,
restauración y sha256 de vuelta. Se exige (a) verde sobre el árbol sin mutar —un
rojo permanente no demuestra nada—, (b) rojo con el defecto, (c) que dentro del
subconjunto declarado el rojo caiga en la comprobación **declarada** —un rojo
por el motivo equivocado es más peligroso que un verde—, (d) reversión idéntica
por hash y (e) que los rojos **COLATERALES** sobre la suite completa sean
**exactamente los declarados** (ver la corrección de abajo).

| Caso | Defecto inyectado | Fichero | Tests en rojo | Reversión |
|---|---|---|---|---|
| G1 | El interruptor deja de apagar | router | `test_sin_el_interruptor_el_panel_no_se_sirve`, `test_solo_true_y_1_encienden_el_panel` (6 param.) | idéntica |
| G2 | El interruptor se evalúa ANTES de la guarda | router | `test_un_anonimo_no_puede_enumerar_si_el_panel_esta_encendido` | idéntica |
| G3 | Se lee por el proveedor CRUDO en vez del filtrado | router | `test_sin_auth_no_reaparece_el_comportamiento_permisivo`, `test_tabla_de_lo_que_ve_un_anonimo…`, `test_los_contadores_son_del_conjunto_autorizado`, `test_el_control_de_autorizacion_COLAPSA`, `test_el_panel_usa_el_proveedor_filtrado_y_no_el_crudo` | idéntica |
| G4 | El contador sale del conjunto crudo (fuga por diferencia) | router | `test_los_contadores_son_del_conjunto_autorizado`, `test_barrer_el_tope_de_pagina_no_mueve_el_total`, `test_un_panel_vacio_para_un_anonimo_es_correcto` | idéntica |
| G5 | Un fallo del proveedor se publica como «cero entidades» | router | `test_la_ausencia_de_datos_no_se_publica_como_cero`, `test_un_proveedor_caido_da_503_sin_filtrar_rutas` | idéntica |
| G6 | El 503 publica `str(exc)` | router | `test_un_proveedor_caido_da_503_sin_filtrar_rutas` | idéntica |
| G7 | El cuerpo del 404 nombra la entidad pedida | router | `test_no_autorizado_e_inexistente_dan_EL_MISMO_404`, `test_el_cuerpo_del_404_no_nombra_la_entidad_pedida` | idéntica |
| G8 | Se monta un `POST /panel/entities/fusionar` en el módulo | router | `test_el_panel_no_monta_ningun_metodo_de_escritura`, `test_ninguna_ruta_del_espacio_del_panel_acepta_escritura` | idéntica |
| **G9** | **`@app.post("/panel/entities/fusionar")` montado desde `viewer/app/main.py`**, fuera de este carril | main | `test_ninguna_ruta_del_espacio_del_panel_acepta_escritura` | idéntica |
| **G10** | Sub-app montada en `/panel/entities/admin` con un `POST` | main | `test_ninguna_ruta_del_espacio_del_panel_acepta_escritura` | idéntica |
| G11 | La enumeración recorre `app.routes` sin aplanar (ve **0** rutas) | suite | `test_la_enumeracion_del_espacio_del_panel_no_puede_salir_vacia` | idéntica |
| G12 | La frontera vuelve a ser de texto (`startswith`) | suite | `test_el_gate_no_acusa_a_un_vecino_de_prefijo` | idéntica |
| G13 | El GET invoca un método de escritura del proveedor | router | `test_recorrer_el_panel_solo_invoca_lecturas_del_proveedor` | idéntica |
| G14 | La plantilla escribe `action="/panel/entities"` a mano | plantilla | `test_las_plantillas_no_llevan_urls_escritas_a_mano` | idéntica |
| G15 | Se reintroduce un `_RANK` local en el router | router | `test_el_panel_no_declara_vocabulario_propio_de_autorizacion` | idéntica |
| G16 | La plantilla ofrece un botón «Fusionar seleccionadas» | plantilla | `test_las_plantillas_no_ofrecen_ninguna_accion_de_escritura` | idéntica |
| G17 | Se quita la premisa «sin datos» del contrato del chasis (§7) | suite chasis | `test_slot_renders_empty_state_instead_of_exploding` (4 param.) | idéntica |
| **G18** | Se borran los contadores del producto (calibración del **control positivo**, no de una garantía) | plantilla | `test_un_contador_no_aparece_antes_de_autorizar`, `test_los_contadores_son_del_conjunto_autorizado`, `test_barrer_el_tope_de_pagina_no_mueve_el_total`, `test_un_panel_vacio_para_un_anonimo_es_correcto`, `test_sin_auth_no_reaparece_el_comportamiento_permisivo` | idéntica |
| **G19** | Se quita el ÚNICO formulario del panel: el bucle deja de ejercer nada (calibración del **control de ejercicio**) | plantilla | `test_las_plantillas_no_ofrecen_ninguna_accion_de_escritura` | idéntica |
| **G20** | Se mete un `<form method="post">` en la plantilla de la FICHA (la que hoy tiene cero formularios) | plantilla ficha | `test_las_plantillas_no_ofrecen_ninguna_accion_de_escritura` | idéntica |

**20/20**, verdes sin mutar, rojas con el defecto y reversión idéntica por hash.

### Corrección: «ningún rojo fuera de los declarados» estaba SOBREVENDIDO

La versión anterior de este documento decía que ninguna mutación producía rojos
fuera del subconjunto declarado. **El arnés no podía saberlo**: ejecutaba los
casos con `-k`, así que **nunca corría el resto de la suite bajo mutación**. La
frase prometía lo que el instrumento no medía — lo señaló la revisión
independiente, que además midió el contraejemplo (**G3 produce 6 rojos fuera de
lo declarado**).

No se ha rebajado la frase: **se ha medido**. El guion corre ahora, por cada
mutación, la **suite COMPLETA** del visor, y los colaterales se **declaran caso
a caso**; si la medida no coincide exactamente con lo declarado, el caso falla.
Cuesta unos 50 s por caso y ese es el precio de poder afirmarlo.

Medido (20 casos, suite completa bajo cada mutación):

| Caso | Colaterales | Cuáles, y por qué son correctos |
|---|---|---|
| G3 | **6** | `test_no_autorizado_e_inexistente_dan_EL_MISMO_404`, `test_una_partida_activa_abre_su_material_y_solo_el_suyo`, `test_la_ficha_no_revela_relaciones_hacia_lo_que_no_se_ve`, `test_barrer_el_tope_de_pagina_no_mueve_el_total`, `test_un_panel_vacio_para_un_anonimo_es_correcto`, `test_el_cuerpo_del_404_no_nombra_la_entidad_pedida` — leer por el proveedor crudo rompe **todas** las barreras a la vez |
| G1 | 1 | `test_slot_is_off_when_flag_is_absent` (contrato del chasis: mismo interruptor, los cuatro huecos) |
| G2 | 1 | `test_disabled_slots_are_not_enumerable_by_an_anonymous` (ídem) |
| G4 | 1 | `test_sin_auth_no_reaparece_el_comportamiento_permisivo` (el contador crudo delata lo oculto) |
| G8, G9, G10 | 1 c/u | `test_no_mounted_route_serves_200_to_anonymous` (el barrido de autorización ve la ruta nueva sin guarda) |
| G11 | 1 | `test_ninguna_ruta_del_espacio_del_panel_acepta_escritura` (con el censo ciego, la frontera tampoco puede afirmarse) |
| G5, G6, G7, G12–G20 | **0** | — |

**Ninguno es un defecto del producto**: los 12 colaterales son defensa en
profundidad, y que existan es mejor noticia que su ausencia. Lo que estaba mal
era la **afirmación**, no el sistema. G18 sale con **0 colaterales**, que es lo
que la revisión independiente ya había medido por su cuenta.

### Incidente del propio instrumento, y su arreglo

Durante este trabajo el guion se **mató a mitad** de una ejecución larga y el
`finally` de restauración no llegó a correr: la mutación de G12 —sobre la propia
suite— se quedó en el árbol, y la siguiente medición dio un rojo que **no era
del producto**. Es el fallo de «medir sobre árbol contaminado» dentro de la
herramienta puesta para evitarlo. La restauración se registra ahora también en
`atexit` y en `SIGINT`/`SIGTERM`/`SIGHUP`, y tras la ejecución completa se
verificó con `git diff` que los seis ficheros mutables vuelven byte a byte.

### Dos suelos autocumplidos, encontrados y cerrados

El segundo lo señaló la revisión independiente, y es de la **misma familia** que
el primero. En `test_las_plantillas_no_ofrecen_ninguna_accion_de_escritura`, el
bucle `for f in formularios: assert 'method="get"' in f` **no ejecuta nada** si
no hay formularios — y `entities_item.html` tiene **cero**. Medido antes de
arreglarlo, con el falso negativo **en VERDE primero**: convirtiendo también el
formulario de filtros de `entities.html` en un `<div>`, la comprobación entera
quedaba vacía y **pasaba en verde**.

Arreglado con un **control de ejercicio**: el conjunto de plantillas del panel
tiene que aportar al menos un formulario que el bucle haya llegado a mirar. No
se exige un número por plantilla, que congelaría el producto —un formulario GET
nuevo es legítimo—. Dos mutantes lo calibran por las dos bandas: **G19** quita
el único formulario (el bucle deja de ejercer nada) y **G20** mete un
`<form method="post">` en la plantilla de la ficha (el bucle sí vigila esa
plantilla cuando tiene formularios).

`test_un_contador_no_aparece_antes_de_autorizar` tenía una mitad **cierta por
construcción**: un 302 no tiene cuerpo, así que «un anónimo no recibe
contadores» se cumple sola, y la prueba habría pasado con los contadores
borrados del producto, con la plantilla vacía o con el panel desmontado. Se le
ha pegado el **control positivo** —la MISMA petición, con un principal válido,
tiene que traer cifras—, de modo que lo que se afirma no es «no hay cuerpo»
sino que **la diferencia la pone la autorización**. El mutante **G18** existe
para calibrar ese control: borra los contadores y exige que la prueba se entere.

### Supervivientes y ablaciones, sin racionalizar

- **`test_los_metodos_de_escritura_son_rechazados_por_http` NO se cobra como
  defensa.** Sondea **sólo** el prefijo raíz. Medido: con el POST de **G8**
  colgado en una subruta sigue **VERDE**. Es redundancia inofensiva —cubre que
  la ruta raíz no acepte escritura ni con el panel encendido— y así está
  anotado en el propio test y excluido de la lista de G8. La revisión
  independiente lo reprodujo montando `POST /panel/entities/fusionar`: el
  sondeo del prefijo raíz devuelve 404 y el test queda verde. La defensa
  efectiva es la enumeración del espacio de URL, y sólo ella.
- **`test_el_panel_no_monta_ningun_metodo_de_escritura` es redundante por
  construcción** con la enumeración del espacio de URL (G8 pone las dos rojas).
  Se conserva porque **localiza** el fallo: dice que el POST lo puso *este*
  fichero y no otro. Ablación honesta: quitarlo no dejaría ningún defecto sin
  cazar.
- **`test_el_cuerpo_del_404_no_nombra_la_entidad_pedida` es redundante** con la
  comparación de cuerpos de `test_no_autorizado_e_inexistente_dan_EL_MISMO_404`
  (G7 pone las dos rojas). Se conserva por lo mismo: nombra el modo de fallo
  concreto.
- **La tabla del §3 no puede derivarse del sistema medido.** El conjunto
  `VISIBLES_PARA_ANONIMO` está escrito a mano en la suite. Si se calculara
  pidiéndoselo a la política, el test no podría discrepar con ella nunca.
- **El contraste con `admin` es un test, no una nota.** Sin
  `test_el_control_de_autorizacion_COLAPSA`, todas las celdas «no» de la tabla
  serían compatibles con un panel inerte.
- **El comprobador de URLs literales retira los comentarios Jinja antes de
  mirar.** Sin ese paso da un falso positivo con el propio comentario de
  cabecera, que nombra el prefijo para explicar la regla. Es el falso positivo
  «citar es afirmar» ya registrado en este repo.

## 6 bis. Verificación independiente

Un revisor ajeno al carril **reprodujo la tabla del §3 con banco propio**
—sustituyendo `app.deps.get_provider`, no el punto congelado— y obtuvo las
**mismas once celdas**, incluido el control de colapso. Además atacó el panel
por diez vías nuevas y **ninguna se coló**. De su trabajo salen tres refuerzos
ya incorporados arriba (indistinguibilidad por sha256 y cabeceras; barrido de
contadores hasta 100.000 con facetas recomputadas y total mentido descartado;
verificación línea a línea del cambio en fichero compartido) y las **dos
correcciones** que motivan esta revisión del documento: la afirmación
sobrevendida de los colaterales (§6) y el segundo suelo autocumplido (§6).

## 7. Un cambio en fichero COMPARTIDO — pendiente de aprobación

`viewer/tests/test_chassis_mount_contract.py::test_slot_renders_empty_state_instead_of_exploding`
se puso **ROJO en `[G]`** en cuanto el hueco dejó de estar vacío. La medida:

```
GET /panel/entities  (viewer autenticado, proveedor por defecto del banco)
-> 200, data-state="ready", "(1–9 de 9)"
el test exigía data-state="empty"
```

El test decía «sin datos» y **no montaba esa premisa**: se apoyaba en que los
cuatro huecos estaban vacíos, que es una propiedad accidental del chasis recién
puesto y no de la pantalla. El proveedor por defecto del banco es
`MockGraphProvider` sobre `examples/sample_graph.json`, cuyos nodos **sí** pasan
la política para un `viewer`. Es decir: el rojo era del test, no del panel.

Lo hecho es **añadir la premisa, no debilitar la afirmación**: una fixture
sustituye el proveedor base por uno vacío para ese único test, y las dos
aserciones (`empty` presente, `error` ausente) quedan **intactas**. Ahora el
test mide lo que su docstring dice, para los cuatro huecos, y quitar la premisa
lo vuelve a poner rojo (mutante **G17**).

**Se declara aquí porque es un fichero del carril del chasis, no de G**, y
porque **F va a chocar con exactamente lo mismo** el día que monte funcionalidad
que lea del grafo. (El hueco **B**, ya fusionado, no se ve afectado: lee de
`jobs_client` y `health_storage`, no del `GraphProvider`, así que esta fixture
le es inerte — comprobado sobre `origin/main`.) Si el operador prefiere que la
premisa la ponga el carril del chasis y no éste, el cambio es un único bloque
aditivo y se revierte sin tocar nada más. `CONTRATO_PUBLICADO` **no se ha
tocado**, y la revisión independiente lo verificó línea a línea: **68
inserciones y 1 borrado**, que es sólo la firma de la función al ganar el
parámetro-fixture, sin ninguna aserción alterada.

## 8. Medidas sobre este árbol

| Medida | Resultado |
|---|---|
| `viewer` completo sobre `origin/main` `1f70726` (línea base de partida) | **1317 passed, 191 skipped** |
| `viewer` completo sobre esta rama | **1378 passed, 191 skipped** (+61, exactamente los de este carril) |
| `viewer/tests/test_panel_entities.py` | **61 passed** |
| `viewer/tests/test_chassis_mount_contract.py` | **88 passed, 1 skipped** (el skip sigue siendo `test_slot_denies_insufficient_role[G]`) |
| `tests/test_docs_numbering.py` | **3 passed** |
| `.github/scripts/check_unicode.py` | OK |
| `scripts/calibrar_panel_entities.py` | **20/20 calibradas**, colaterales medidos sobre la suite completa |

El skip de `[G]` es el de siempre y sigue siendo correcto: `viewer` es el rol
más bajo del sistema, así que no existe uno inferior con el que probar la
denegación por rol insuficiente. Lo que sí se prueba es que el rol publicado
entra (200) y que el anónimo no (302).

## 9. Estado del interruptor

`S9K_PANEL_G_ENABLED` sigue **apagado por defecto** en `viewer/.env.example` y
no se ha cambiado. Encender el panel en cualquier despliegue es una decisión del
operador, no de este carril. Con el flag ausente la ruta responde 404 —
indistinguible de una ruta inexistente — y el menú no pinta el enlace.

## 10. Límites conocidos, dichos y no disimulados

1. **No hay comparación de TIEMPO en el 404 indistinguible.** Se comparan código
   y cuerpo. Medir tiempos con fiabilidad exige un banco que este carril no
   tiene, y afirmarlo sin medirlo sería peor que no afirmarlo. Mismo límite que
   `docs/76 §7.1`.
2. **La medida del §3 es sobre `MockGraphProvider`, no sobre Neo4j** — pero el
   riesgo es **MEDIO, no alto**, y conviene decir por qué con las dos mitades.

   *Lo que rebaja el riesgo, verificado:* `Neo4jGraphProvider` **sí proyecta**
   las cinco dimensiones que la política lee —`scope`, `partida_id`,
   `known_by`, `known_by_characters` y `known_from_session`
   (`neo4j_provider.py:31-41`)— y esa lista está **congelada por una red
   preexistente y verde**, `test_productor_de_cada_campo_de_autorizacion.py`
   (**9 passed**). Además, `viewer/tests/test_neo4j_integration_authz.py`
   ejerce la cadena proveedor → serializador → política **contra una base
   VIVA**: el job `Authz integration (Neo4j efímero)` levanta Neo4j 5.26 y
   **falla si alguna prueba se omite** o si no se ejecuta ninguna. En el run de
   este PR: **19 passed** contra la base efímera.

   *Lo que NO cubre, y es el residuo real:* esas 19 pruebas ejercen el
   **proveedor**, no **este panel**. Las rutas `/panel/entities` sólo se han
   medido contra `MockGraphProvider`, así que lo que sigue sin ejercerse contra
   una base viva es la composición completa *panel → proveedor real*. En local,
   sin `NEO4J_TEST_URI`, esas 19 se **omiten** (medido: 19 skipped), de modo que
   quien mida sólo en su máquina no ve esa cobertura. Cerrar el residuo es
   trabajo del carril del proveedor o de un carril de integración, no de éste,
   y va a decisión del operador.
3. **Los contadores no se han barrido contra un corpus grande.** El barrido de
   `limit` va de 1 a 2000 sobre 11 nodos, así que demuestra que el total es
   invariante al recorte, no que el panel aguante un grafo real. La revisión
   independiente lo llevó hasta **100.000** con el total inmóvil, y comprobó
   además `offset` fuera de rango sin canal de inferencia, las facetas
   **recomputadas tras la política** (los tipos ocultos no aparecen ni
   nombrados ni contados) y un proveedor base que **miente en el total**: la
   mentira se descarta, porque el total que se publica se recuenta sobre el
   conjunto autorizado. Nada de eso cambia el límite: sigue sin medirse el
   rendimiento sobre un grafo real. La banda de
   rendimiento es deuda de `benchmarks/perf/`, cuyo instrumento de calibración
   tiene una avería propia ya registrada en `docs/76 §7.2` y que **no está
   cableado en `ci.yml`**.
4. **No se ha auditado el resto del espacio `/panel/**` de otros carriles.** El
   gate de este panel mira `/panel/entities` y sólo eso, por construcción de la
   frontera de segmento.
5. **Esta vuelta no trae funciones nuevas de gestión de entidades.** No hay
   edición, ni fusión, ni renombrado, ni borrado, ni exportación. Es deliberado:
   la meta era el panel de solo lectura sobre el chasis y la autorización
   actuales.
