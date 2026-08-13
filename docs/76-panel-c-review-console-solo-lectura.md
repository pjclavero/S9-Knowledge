# Hueco C del chasis — Review Console, SOLO LECTURA

Primera vuelta del carril C sobre el chasis de montaje (`docs/69`) y sobre la
autorización que dejó el P0 de autoridad única (`docs/75`). Objetivo declarado:
**una consola de revisión de solo lectura montada sobre el chasis y la
autorización actuales, con un gate de integración verde** — no una consola
completa de funciones.

Árbol medido: rama `feat/review-console-c`, nacida de `main` `ec8db32`.

## 1. Qué se recuperó y qué se rehízo

La arqueología diferencial de `docs/74 §8` se verificó antes de usarla, por
hash de objeto Git, no leyendo el documento:

```
$ git rev-parse d1690524:viewer/app/services/v3_review.py origin/main:viewer/app/services/v3_review.py
ba42df7710394a73a241f8177d197bd8e0a08c16
ba42df7710394a73a241f8177d197bd8e0a08c16
$ git rev-parse d1690524:viewer/app/routers/v3_review.py  origin/main:viewer/app/routers/v3_review.py
1bedb11fed2cf952c3c6525183ee6cccefaa6ce9
1bedb11fed2cf952c3c6525183ee6cccefaa6ce9
```

Confirmado: los dos módulos de los que depende la consola **no han cambiado ni
un byte** entre la base de la rama vieja y `main`. La incompatibilidad era de
montaje, no de lógica. `viewer/app/main.py` sí difiere (`14675eb` vs `f9f00aa`),
que es exactamente el montaje del chasis.

| Fichero | Decisión | Justificación medida |
|---|---|---|
| `viewer/app/services/review_console_v2.py` | **RECUPERADO** desde `origin/feat/review-console-v2-readonly`, primero byte a byte (`sha256 b81fb25a…` idéntico al del blob de la rama vieja), y después con tres añadidos declarados abajo | Lógica pura de presentación. No importa nada del chasis, ni de autorización, ni de FastAPI. Su única dependencia externa es `reason_label` de `services/v3_review.py`, que es idéntico en `main` |
| `viewer/app/routers/review_console_v2.py` | **NO PORTADO — REESCRITO** como `viewer/app/routers/chassis_review.py` | Declaraba `APIRouter(prefix="/console")` colgando del router de la cola. El contrato publicado exige prefijo `/panel/review`, nombre `chassis_review`, rol `reviewer` y plantilla `chassis/review.html`. Los cuerpos de los dos handlers se conservan en lo sustancial; el encuadre entero es nuevo |
| Las +10 líneas en `routers/v3_review.py` | **NO PORTADAS** | Eran el `include_router` metido dentro de la cola «porque `main.py` tiene otros propietarios». El chasis existe para borrar ese apaño: hoy el montaje es un dato en `FEATURE_SLOTS`. `routers/v3_review.py` queda **intacto** en esta rama |
| `viewer/app/templates/review_console_v2.html` | **NO PORTADA — REESCRITA** como `templates/chassis/review.html` | Fijaba `action="/v3/review/console"`. Ahora extiende `chassis/_slot.html` (hereda sus tres estados `data-state`) y **toda** URL sale de `url_for`, resuelta por nombre de ruta |
| `viewer/app/templates/review_console_v2_item.html` | **NO PORTADA — REESCRITA** como `templates/chassis/review_item.html` | Mismo motivo |
| `viewer/tests/test_review_console_v2.py` | **NO PORTADO — REESCRITO** como `viewer/tests/test_panel_review_console.py` | Los 33 tests viejos montan un `FastAPI()` privado del test. La regla de la suite del chasis lo prohíbe expresamente: una app de mentira comparte el código de los routers pero **no el montaje**, y el montaje es justo lo que había que rehacer. Las afirmaciones de lógica se conservan; el encuadre HTTP se rehizo contra `app.main.app` |
| `docs/55-…` / `docs/62-…` de la rama vieja | **NO PORTADO** | El de la rama ya venía renumerado a 62 por colisión con el `docs/55` de `main`. Su contenido describe el montaje viejo. Este documento (`docs/76`) lo sustituye; el número 76 estaba libre y el gate de numeración queda verde |

### Los tres añadidos al servicio recuperado

El fichero se recuperó primero idéntico (hash arriba) y luego se modificó en
tres puntos, todos declarados y todos calibrados:

1. `decision_is_known()` — **importa** `VALID_ENGINE_DECISIONS` de
   `services/v3_review.py`; no redeclara una segunda lista de estados válidos.
2. `row_view` publica `decision_known` / `shadow_decision_known`.
3. El acuerdo motor↔sombra exige además que **las dos partes sean estados
   reconocidos**: dos valores idénticos que nadie entiende no son un acuerdo.

## 2. Las nueve piezas de `docs/74 §8.3`, una a una

| # | Pieza | Qué se hizo | Dónde se comprueba |
|---|---|---|---|
| 1 | Primero filtrar, después paginar | Conservada intacta (`build_view` → `apply_filters` → `sort_rows` → `paginate`); contadores del conjunto filtrado | `test_los_contadores_son_del_conjunto_filtrado_no_de_la_pagina`, `test_paginar_no_filtra_nunca` · mutante **M4** |
| 2 | Acuerdo sólo con las dos partes | Conservada y **endurecida**: además de existir, las dos partes tienen que ser estados reconocidos | `test_sin_sombra_no_hay_acuerdo`, `test_un_acuerdo_entre_estados_desconocidos_no_es_acuerdo` · mutantes **M7**, **M5** |
| 3 | `not_available` es ausencia | Conservada, y comprobada además **en la pantalla renderizada**, no sólo en la proyección | `test_not_available_es_ausencia_no_un_valor`, `test_not_available_no_se_pinta_en_la_pantalla` · mutante **M6** |
| 4 | Orden por prioridad (`REVIEW` > `ABSTAIN` > `REJECT_INVALID`) | Conservada | `test_los_vecinos_siguen_el_orden_filtrado` (afirma el orden servido por HTTP: `bajo, alto, abstiene`) · mutante **R7** |
| 5 | Vecinos anterior/siguiente en el orden filtrado, con posición y total | Conservada; la ficha se resuelve contra el conjunto filtrado ENTERO, no contra la página | `test_los_vecinos_siguen_el_orden_filtrado`, `test_la_ficha_no_se_limita_a_la_primera_pagina` · mutante **M11** |
| 6 | 404 indistinguible (inexistente / fuera de ámbito / excluido por filtro) | Conservada; se compara **código y cuerpo**, no sólo el código | `test_fuera_de_ambito_inexistente_y_filtrado_dan_el_mismo_404`, `test_un_workspace_fuera_de_ambito_es_404_como_uno_inexistente` · mutante **M8** |
| 7 | Paquete ilegible → 503 sin volcar rutas ni trazas | Conservada y **endurecida**: el detalle es `type(exc).__name__`, nunca `str(exc)` (que puede traer la ruta del fichero) | `test_paquete_ilegible_da_503_sin_filtrar_rutas` · mutante **M9** |
| 8 | `DEFAULT_LOW_CONFIDENCE = 0.6` es criterio de PRESENTACIÓN | Conservada. El test **mide el paquete exportado** y exige que no traiga ninguna clave de umbral; si el motor empezara a exportarlos, se pone rojo | `test_el_umbral_de_baja_confianza_es_criterio_de_presentacion` · mutante **R8** |
| 9 | Solo lectura por enumeración de métodos | Conservada y **corregida tras la revisión**: la enumeración es del ESPACIO DE URL de la app, no del módulo (§4bis) | `test_ninguna_ruta_del_espacio_del_panel_acepta_escritura`, `test_la_enumeracion_del_espacio_del_panel_no_puede_salir_vacia`, `test_el_panel_no_monta_ningun_metodo_de_escritura` · mutantes **R5**, **R6**, **M10** |

## 3. La autorización actual, y el test que impide volver atrás

`build_viewer_context` degrada a `role="anonymous"` cuando
`S9K_AUTH_ENABLED` está desactivado: sin principal no hay autoridad. La consola
vieja se escribió cuando ese mismo caso producía `admin_full=True`.

`test_sin_auth_no_reaparece_el_comportamiento_permisivo` fija el resultado
sobre el ámbito **que produce el productor de contextos**, no uno fabricado a
mano: con auth desactivada, material de partida no se entrega ni en la lista,
ni en los contadores, ni por ID, y `ctx.admin_full` es `False`.

**Una consola vacía en ese contexto es el comportamiento correcto.** No es una
pantalla que arreglar.

### «Consola vacía es correcto» es CONTINGENTE, no absoluto

Es el punto que un lector puede entender al revés, así que va con la medida
delante. El corpus de revisión se acota con `scope.partida_only()` (lo hace
`ReviewService`, no este router), de modo que la barrera aplicable es la de
**partida**, no la de workspace. Una propuesta **sin `partida_id`** no es
material de una partida ajena: es **capa juego compartida**, lore, y se
entrega.

Medido con `S9K_AUTH_ENABLED` desactivado, ámbito producido por
`build_viewer_context` (`admin_full=False`), en
`test_sin_auth_la_capa_juego_SI_es_visible_y_eso_tambien_es_la_politica`:

| Propuesta | ¿En la lista? | Contador `visible` | Ficha por ID |
|---|---|---|---|
| `con-partida` (`partida_id="partida-A"`) | **no** | no cuenta | **404** |
| `capa-juego` (sin `partida_id`) | **sí** | cuenta | **200**, con el texto del episodio |
| | | total **1** de 2 | |

Es decir: con auth desactivada un anónimo **sí puede ver lore**. Eso **no es
una vía reabierta por este carril** —es la política heredada aplicada de forma
consistente, y el mutante **M3** lo confirma: sustituir el ámbito de la
petición por `UNRESTRICTED` pone rojo el test de al lado—, pero **la frase
"la consola sale vacía" no puede leerse como una garantía de que el anónimo no
ve nada**. Sale vacía para el material que tiene partida, que es donde está la
diferencia entre el comportamiento viejo y el nuevo.

El router además no declara vocabulario propio de autorización, y eso se
comprueba **sobre el AST** —no leyendo el fichero—: sin `admin_full`, sin tabla
de rangos, sin comparar roles. Reintroducir el `_RANK` local pone rojo el test
(mutante **M13**).

## 4. Calibración: cada garantía puesta en rojo

`python3 scripts/calibrar_panel_review.py`. Por cada caso: sha256 del fichero,
mutación efímera, ejecución del subconjunto **nombrado** de tests, restauración
y sha256 de vuelta. Se exige (a) verde sobre el árbol sin mutar —un rojo
permanente no demuestra nada—, (b) rojo con el defecto, (c) que los tests en
rojo sean **exactamente los declarados** —un rojo por el motivo equivocado es
más peligroso que un verde— y (d) reversión idéntica por hash.

| Caso | Defecto inyectado | Tests en rojo | Reversión |
|---|---|---|---|
| M1 | El interruptor del hueco deja de apagar | `test_sin_el_interruptor_el_panel_no_se_sirve`, `test_solo_true_y_1_encienden_el_panel` (5 param.) | idéntica |
| M2 | El interruptor se evalúa ANTES de la guarda | `test_un_anonimo_no_puede_enumerar_si_el_panel_esta_encendido` | idéntica |
| M3 | El router usa `UNRESTRICTED` en vez del ámbito de la petición | `test_sin_auth_no_reaparece_el_comportamiento_permisivo`, `test_el_material_de_otra_partida_…`, `test_la_sustitucion_de_ambito_muerde` | idéntica |
| M4 | Se pagina antes de filtrar | `test_los_contadores_son_del_conjunto_filtrado_no_de_la_pagina` | idéntica |
| M5 | Todo estado se declara conocido | `test_un_estado_desconocido_no_se_declara_conocido`, `…_se_marca_en_la_pantalla`, `test_un_acuerdo_entre_estados_desconocidos_no_es_acuerdo` | idéntica |
| M6 | `not_available` deja de traducirse a ausencia | `test_not_available_es_ausencia_no_un_valor`, `…_no_se_pinta_en_la_pantalla` | idéntica |
| M7 | Se declara acuerdo sin sombra | `test_sin_sombra_no_hay_acuerdo` | idéntica |
| M8 | 403 «no es tuya» para material fuera de ámbito | `test_fuera_de_ambito_inexistente_y_filtrado_dan_el_mismo_404` | idéntica |
| M9 | El 503 publica `str(exc)` | `test_paquete_ilegible_da_503_sin_filtrar_rutas` | idéntica |
| M10 | Se monta un `POST /panel/review/aprobar` | `test_el_panel_no_monta_ningun_metodo_de_escritura` | idéntica |
| M11 | `neighbours` devuelve la primera fila sea cual sea el id | `test_la_ficha_es_la_de_la_fila_que_se_abrio`, `test_los_vecinos_siguen_el_orden_filtrado` | idéntica |
| M12 | La plantilla escribe `action="/panel/review"` a mano | `test_las_plantillas_no_llevan_urls_escritas_a_mano` | idéntica |
| M13 | Se reintroduce un `_RANK` local en el router | `test_el_panel_no_declara_vocabulario_propio_de_autorizacion` | idéntica |
| **R5** | **`@app.post("/panel/review/aprobar")` montado desde `viewer/app/main.py`**, fuera de este carril | `test_ninguna_ruta_del_espacio_del_panel_acepta_escritura` | idéntica |
| **R6** | La enumeración recorre `app.routes` sin aplanar (ve **0** rutas del prefijo) | `test_la_enumeracion_del_espacio_del_panel_no_puede_salir_vacia` | idéntica |
| **R7** | Se invierte `_DECISION_PRIORITY` (pieza 4) | `test_los_vecinos_siguen_el_orden_filtrado` | idéntica |
| **R8** | El filtro de baja confianza deja de aplicar el umbral (pieza 8) | `test_el_umbral_de_baja_confianza_es_criterio_de_presentacion` | idéntica |

**17/17**, verdes sin mutar, rojas con el defecto, reversión idéntica por hash.

## 4bis. S1 — la frontera de solo lectura era del MÓDULO, no del ESPACIO DE URL

Hallazgo de la revisión independiente, y el más importante de este carril
porque **B/F/G iban a heredar el patrón**.

La primera versión de la garantía enumeraba `panel.router.routes`. Eso hace
dura la frontera **dentro de este fichero** y **no** en `/panel/review/**`. El
revisor montó `@app.post("/panel/review/aprobar")` **desde `viewer/app/main.py`**
—fuera de este módulo, que es como aparecería de verdad: otro carril colgando
una ruta en el espacio de URL ajeno— y midió **45/45 VERDE** mientras la ruta
respondía **200 sin autenticar y escribía en disco**. Nadie la veía.

**Corregido.** La comprobación recorre ahora las rutas **de la app** cuyo
`path` empieza por `SLOT.prefix`, y lo hace **recursivamente** con el mismo
`iter_mounted_routes` que usa el barrido de autorización del chasis. Los dos
detalles importan:

- **Recorrer la app, no el router**: es lo que convierte «este módulo no
  escribe» en «nadie escribe en este espacio de URL».
- **Recorrer recursivamente**: un barrido de primer nivel sobre `app.routes`
  devuelve **cero** rutas de este prefijo, porque FastAPI >= 0.116 mete los
  routers incluidos en envoltorios `_IncludedRouter`. El primer intento del
  revisor cayó justo ahí: **un arnés vacío que habría "demostrado" cualquier
  cosa**. Por eso la corrección trae además un **suelo de plausibilidad**
  (`test_la_enumeracion_del_espacio_del_panel_no_puede_salir_vacia`), que exige
  ver al menos 3 rutas y, nombradas, las dos que este carril declara.

Los dos mutantes correspondientes (**R5**, **R6**) están en la tabla de arriba:
antes de la corrección R5 pasaba en VERDE; ahora se pone ROJA, y R6 caza el
modo de fallo del propio instrumento. **Éste es el patrón que B, F y G deben
copiar**: comprobar el propio router deja la puerta abierta.

### Supervivientes y ablaciones, sin racionalizar

- **`test_los_metodos_de_escritura_son_rechazados_por_http` NO puede cobrarse
  como defensa.** Sondea **sólo** el prefijo raíz (`POST /panel/review` → 405).
  Medido: con un POST colgado en cualquier subruta —de este módulo (M10) o de
  otro (R5)— **sigue verde**. Es redundancia inofensiva, no garantía; se
  conserva porque cubre que la ruta raíz no acepte escritura ni con el panel
  encendido, y así está anotado en el propio test.
- **`test_el_panel_no_monta_ningun_metodo_de_escritura` es redundante por
  construcción** con la enumeración del espacio de URL. Se conserva porque
  **localiza** el fallo: dice que el POST lo puso *este* fichero y no otro.
  Ablación honesta: quitarlo no dejaría ningún defecto sin cazar.
- **El control de colapso del arnés es un test, no una nota al pie.**
  `test_la_sustitucion_de_ambito_muerde` exige que quitar la sustitución de
  `get_visibility_scope` **cambie** el resultado. Sin él, todas las pruebas de
  aislamiento serían compatibles con un ámbito inerte.
- **`get_visibility_context` no se sustituye en ningún test.** Se llama como
  función normal desde `get_filtered_provider` y desde `get_visibility_scope`
  (`viewer/app/authz/dependencies.py`), así que sobrescribirlo con
  `dependency_overrides` es **inerte**: saldría verde por no morder. Lo que
  entra por `Depends` en este router es `get_visibility_scope`, y es lo único
  que se sustituye. Ese punto de inyección **no se ha tocado**.
- **El comprobador de URLs literales retira los comentarios Jinja antes de
  mirar.** Sin ese paso daba un falso positivo con su propio comentario de
  cabecera, que nombra el prefijo para explicar la regla. Es el falso positivo
  «citar es afirmar» ya registrado en este repo, y el mismo caso que el mutante
  M5 del mapa de rutas (`docs/68`): una mención en un comentario no crea ni
  cubre ninguna ruta.

## 5. Medidas sobre este árbol

| Medida | Resultado |
|---|---|
| `viewer` completo (`python3 -m pytest tests -q` desde `viewer/`) | **1295 passed, 191 skipped** |
| `tests/test_docs_numbering.py` + `deploy/tests` | **255 passed, 1 skipped, 6 xfailed** |
| `viewer/tests/test_chassis_mount_contract.py` | **68 passed, 1 skipped** (el contrato publicado sigue intacto) |
| `viewer/tests/test_panel_review_console.py` | **48 passed** |
| `scripts/calibrar_panel_review.py` | **17/17 calibradas** |

**Corrección de una cifra declarada.** La primera versión de este documento
decía `1291 passed`; el revisor midió `1292` sobre árbol limpio. Tenía razón y
la causa es mía: medí la suite completa **antes** de añadir el test 45 del
panel (`test_el_umbral_de_baja_confianza_…`) y no la volví a correr. Cifra
declarada sobre un árbol que ya no era el entregado — el fallo exacto que este
proyecto persigue. Las cifras de arriba están remedidas sobre el árbol actual,
que además incorpora los tres tests nuevos de la revisión (48 en el panel,
1295 en total: 1292 + 3).

## 6. Estado del interruptor

`S9K_PANEL_C_ENABLED` sigue **apagado por defecto** en `viewer/.env.example` y
no se ha cambiado. Encender el panel en cualquier despliegue es una decisión
del operador, no de este carril. Con el flag ausente, la ruta responde 404 —
indistinguible de una ruta inexistente — y el menú no pinta el enlace.

## 7. Límites conocidos, dichos y no disimulados

1. **No hay comparación de TIEMPO en el 404 indistinguible.** Se comprueban
   código y cuerpo idénticos. Medir el tiempo con fiabilidad exige un banco que
   este carril no tiene, y afirmarlo sin medirlo sería peor que no afirmarlo.
2. **La banda de rendimiento no se ha recalibrado.** La puerta de calibración
   de `benchmarks/perf/` **rehusará** en cuanto se toque `viewer/app/**`, y eso
   es correcto: el `sha_del_sistema_medido` ha cambiado. No se ha desactivado
   ni se ha regenerado el artefacto, porque el instrumento que lo regeneraría
   (`benchmarks/perf/calibracion.py`) tiene una avería propia ya registrada —
   aborta con un 404 en C3, reproducible sobre `main` sin cambios — y
   regenerar con un instrumento averiado produce una cifra peor que ninguna.
   Es deuda separada de este carril.
3. **Los «invariantes M5/M9 del motor de revisión» no existen con ese nombre en
   el árbol. CONFIRMADO Y CERRADO** por la revisión independiente, con búsqueda
   propia suya: en este árbol `M5`/`M9` son identificadores de mutantes de
   calibración de otros gates (`docs/65`, `docs/66`, `docs/68`, `docs/75`) y la
   nomenclatura de fases M0–M5 de multipartida. No hay nada más que hacer aquí. Se buscó (`grep` sobre `viewer/`, `data-engine/`, `docs/`,
   `shared/`): en este repositorio `M5`/`M9` son **identificadores de mutantes
   de calibración** de otros gates —`docs/68` (M5: una ruta sólo mencionada en
   un comentario no crea nada; M9: un `NavItem` a una ruta no montada revienta)
   y `docs/75` (M5: `admin_full` supera un `deny`; M9: bypass por alias
   local)—, además de la nomenclatura de fases M5a/M5b/M5c de multipartida. Lo
   que este panel puede afirmar es que **sigue pasando esos gates ajenos** —la
   suite del chasis queda en 68 passed y la del P0 de autoridad no se ha
   tocado— y que sus propios mutantes M5 y M9 cubren el estado desconocido y el
   503 sin fuga. Si el operador se refería a otra cosa, hace falta que la
   nombre: inventar aquí una interpretación y declararla cubierta sería
   justamente lo que no se debe hacer.
4. **Esta vuelta no trae funciones nuevas de revisión.** No hay exportación, ni
   acciones en lote, ni atajos de teclado, ni marcado. Es deliberado: la meta
   era el montaje sobre el chasis y la autorización actuales.
