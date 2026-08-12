# 66 — Calidad de datos v2 (carril J)

**Rama:** `audit/data-quality-v2` · **Base:** `main = e9c66dc`

Dos decisiones del operador, ya tomadas, implementadas aquí:

1. La autorización se **deriva** del registro ejecutable M5b. No se mantiene una
   segunda lista.
2. `ReviewStatus` tiene **un único vocabulario canónico de dominio**, con
   **adaptadores en las fronteras legacy**. No se crea un quinto vocabulario.

Y un principio que gobierna el resto del documento: *una afirmación no es
evidencia porque exista un test verde*. Todo lo que se afirma aquí tiene una
mutación que lo pone rojo, en `mutaciones_calidad_datos.py`.

---

## 1. El defecto de partida: el comprobador estaba ciego donde apuntaba su CRITICAL

`viewer/tests/test_provider_authz_fields_contract.py` existe por H1: una
proyección parcial (`_node_to_dict` sin `partida_id`) apagó el aislamiento entre
partidas con 675 tests en verde. Su docstring lo explica bien: *una proyección
parcial silencia una barrera entera sin poner nada en rojo*.

Su red inversa —`test_ningun_campo_que_el_motor_consulta_queda_fuera_de_la_lista`—
buscaba en el código del motor este patrón, y sólo éste:

```python
leidos = set(re.findall(r'node\.get\(\s*["\']([a-z_]+)["\']', fuente))
```

El motor toma **la mitad de sus decisiones leyendo atributos del contexto**, no
campos de nodo: `ctx.admin_full`, `ctx.can_view_secret`, `ctx.max_visible_session`…
Esa red era, por construcción, **incapaz de ver una sola dimensión del contexto
sin declarar**. Es exactamente el fallo H-A que el registro documenta —una
dimensión con columna, lector y pruebas, y ningún escritor— y cuyo motivo de no
detección fue, literalmente, *"sólo miraba campos de nodo"*.

El comprobador sabía enunciar la lección y no sabía aplicársela.

**Hallazgo directo de cerrar esa ceguera:** el motor consume **9** dimensiones de
contexto y el registro declara **6**. Las tres que decidían sin cadena declarada:

| Dimensión | Qué hace | Por qué importa |
|---|---|---|
| `admin_full` | bypass **total** (`if ctx.admin_full: return visible`) | la dimensión con más poder del sistema no tiene autoridad, productor ni respuesta a "¿y si falta?" declaradas |
| `can_view_reference` | única llave del nivel `reference` | ninguna cadena declarada |
| `character_knowledge` | concede conocimiento por ID precomputado | se salta `known_by` por completo |

`viewer/app/policies/**` es zona prohibida para este carril, así que **no se han
declarado aquí**: quedan en `CONTEXTO_SIN_DECLARAR_EN_EL_REGISTRO`. Declararlas
en el registro es trabajo del propietario de `policies/**`; `admin_full` es
decisión del operador.

### Corrección: la primera versión de este documento afirmaba aquí algo FALSO

Decía que la cuarentena *«sólo puede encoger: el test falla si crece»*. **No era
cierto en el único caso que importa.** La comprobación era
`resueltas = CUARENTENA − sin_declarar`, que detecta entradas **rancias** pero
**no entradas nuevas**: bastaba añadir al motor una dimensión de bypass total y
meter su nombre en la cuarentena *en el mismo commit* para que la suite siguiera
en verde. El freno era humano, no mecánico — y escrito precisamente sobre
`admin_full`.

Es la misma clase de defecto que este carril vino a cerrar: una barrera declarada
que no barra. Lo encontró la revisión independiente, no yo.

**Corregido de las dos formas a la vez, porque una sola no basta:**

1. **Mecanismo.** La cuarentena se compara contra `_CUARENTENA_CONGELADA` en las
   **dos direcciones** y contra `_CUARENTENA_TAMANO_AUTORIZADO`, escrito aparte
   (`test_la_cuarentena_no_puede_CRECER_sin_una_decision_explicita`). Ampliarla
   exige tres ediciones coordinadas que aparecen juntas en el diff.
2. **Redacción.** Ningún test puede impedir que un humano edite el test, así que
   la afirmación ya no dice «es imposible que crezca». Dice lo que el mecanismo
   hace: **crecer deja de ser un efecto colateral silencioso de tocar el motor y
   pasa a ser una decisión explícita y visible en la revisión.** Sigue exigiendo
   autorización del operador.

Calibrado con la mutación **R8**, que reproduce el escenario del revisor
literalmente —dimensión nueva en `models.py`, consumida en `engine.py`, y metida
en la cuarentena, todo en el mismo cambio— y ahora se pone **ROJA**. Con la
comprobación anterior ese mismo cambio daba verde.

### Límite de alcance de la red inversa (no es regresión de este carril)

La red inversa barre **sólo `policies/engine.py` y `policies/models.py`**. Fuera
de ahí hay código que **produce** `admin_full` o que **decide** con él, y que
esta red **no mira**:

| Fichero | Qué hace | ¿Produce o consume? |
|---|---|---|
| `viewer/app/authz/context.py:88` | `if not auth_enabled and not simulated: return ViewerContext(..., admin_full=True)` | **produce** |
| `viewer/app/authz/context.py:100` | `if role == "admin" and not simulated: return ViewerContext(..., admin_full=True)` | **produce** |
| `viewer/app/authz/scope.py:131` | `bool(self.ctx.admin_full) or self.ctx.role == "admin"` | **produce** (vía equivalente, sin pasar por el campo) |
| `viewer/app/authz/filtered_provider.py` | decide con `admin_full` | consume |
| `viewer/app/main.py:320` | decide con `admin_full` | consume |
| `viewer/app/jobs_client.py:171` | decide con `admin_full` | consume |

Son **tres productores**, no uno, y ninguno está declarado en el registro
ejecutable:

1. `context.py:100` — el rol `admin` autenticado. Es el esperado.
2. `scope.py:131` — `role == "admin"` evaluado **de nuevo**, en un módulo que la
   red no inspecciona: una SEGUNDA VÍA a la misma potestad que no pasa por el
   campo `admin_full` y por tanto sobreviviría aunque el campo se quitase.
3. `context.py:88` — **el tercero, y el que menos se parece a una concesión de
   privilegio**: cuando `S9K_AUTH_ENABLED` es falso, *cualquier* petición
   anónima recibe `admin_full=True` con `role="public"`. La bandera llega desde
   `authz/dependencies.py:107` (`get_auth_settings().S9K_AUTH_ENABLED`). Es
   decir, **el bypass total del motor de visibilidad se concede por
   configuración de despliegue**, no por identidad, y el registro ejecutable —
   que es el sitio donde consta quién produce cada dimensión de autorización —
   no lo menciona. Un `admin_full` producido por una variable de entorno es
   exactamente el tipo de autoridad que este carril existe para hacer visible.

Este tercero refuerza lo que ya decía §1 sobre `scope.py`: la cuarentena de
`admin_full` documenta que la dimensión no está declarada, pero **no cubre todas
las formas de obtenerla**, y mutar `engine.py` no las alcanza. `authz/**` es
zona prohibida para este carril, así que las tres quedan **declaradas, no
corregidas** — y no se ha añadido ninguna mutación que las mida, porque medirlas
exigiría tocar código fuera del carril.

---

## 2. Las 23 divergencias: cómo se resolvieron

Los **nombres** coincidían: J listaba 7 campos y el registro declara esas mismas
7 dimensiones proyectadas. La divergencia no estaba en los nombres sino en que
**J sólo tenía nombres**. El registro declara una *cadena* por dimensión
(autoridad → productor → persistencia → transporte → contexto → consumidor, más
"¿y si falta?" y "¿y si es inválido?"); la lista de J era una tupla de cadenas de
texto con comentarios.

| # | Grupo | Qué divergía | Resolución |
|---|---|---|---|
| 1–14 | 7 dimensiones proyectadas × `missing` + `malformed` | J no transportaba **ninguna** semántica de ausencia/invalidez: congelaba la forma, nunca el comportamiento | los casos de `test_un_campo_declarado_DENY_deniega_*` se **derivan** de `missing == DENY` en el registro |
| 15–20 | 6 dimensiones del **contexto** | J no las miraba en absoluto (`in_projection=False`) | red inversa nueva sobre atributos de `ViewerContext` |
| 21–23 | 3 dimensiones **retiradas** (`party`, `is_public`, `session_index`) | J las mencionaba en prosa; nada impedía su regreso | `test_las_dimensiones_retiradas_no_vuelven_por_la_puerta_de_atras`, que lee `RETIRADAS` del registro |

**14 + 6 + 3 = 23.**

La segunda fuente se eliminó: `CAMPOS_AUTORIZACION_NODO` y
`CAMPOS_AUTORIZACION_RELACION` ahora se calculan con `_proyectados()`, que aplica
`in_projection`, `applies_to` y `stored_as`. Y hay una **meta-prueba**
(`test_la_lista_de_campos_de_autorizacion_no_se_declara_a_mano`) que se pone roja
si alguien vuelve a escribir nombres de dimensión a mano en ese fichero.

### Derivar no basta (y esto es el corazón del carril)

Si la lista se deriva y alguien **borra** una dimensión del registro, la lista
simplemente se acorta: menos casos parametrizados, todo verde. *Una derivación
sin testigo independiente convierte un borrado en un silencio.* Sería reproducir
el defecto original en un nivel más arriba.

El testigo independiente es **el código del motor**: si el motor sigue
consultando lo que el registro ya no declara, las redes inversas se ponen rojas.
Mutaciones J1 (campo de dato) y J2 (dimensión de contexto) demuestran las dos
direcciones.

---

## 3. `ReviewStatus`: vocabulario canónico y adaptadores

Se encontraron **cuatro** declaraciones separadas, y una **quinta** circulando
por los datos:

| # | Dónde | Forma |
|---|---|---|
| 1 | `data-engine/app/schemas/rpg_schema.py::ALLOWED_REVIEW_STATUS` | minúsculas, cerrado, **es lo que se persiste** |
| 2 | `viewer/app/labels.py::REVIEW_STATUS_LABELS_ES` | segunda lista a mano; decide lo que ve el humano |
| 3 | `contracts/review-ingest/v1::candidate_status` | MAYÚSCULAS, 9 valores, ciclo de vida del *candidato* |
| 4 | `review/auto_decider.py` + `approved_writer.py` | `auto_approve`/`needs_review`/`auto_reject`, y el literal `review_status="auto_approved"` |
| (5) | `cli/review_manual.py` | `pending` → **`approved`**, escrito **tal cual en el grafo** |

### El canónico elegido: (1), el vocabulario persistido en minúsculas

`{auto_extracted, needs_review, reviewed, rejected, corrected}`, movido a
`contracts/review-status/v1/model.py`. Razones, en orden:

* **Es el único que llega al dato.** Los demás son estados de un *proceso*; éste
  es el estado del hecho una vez guardado — lo que el visor filtra, ordena y
  etiqueta, y lo que sobrevive al pipeline que lo produjo.
* **Ya era cerrado y validado**, así que elegirlo no relaja nada.
* Los otros son **fronteras**: (3) es un JSON Schema congelado que describe otro
  ciclo de vida y no debe reescribirse; (4) y (5) son vocabulario interno de
  pipelines legacy. A una frontera se le pone un **adaptador**, no se le cambia
  el idioma.

No se añade un estado "aprobado por máquina": sería el quinto vocabulario que
esto viene a impedir, y además mentiría — un hecho que ningún humano ha mirado no
está revisado. `auto_approve` → `auto_extracted`.

### Hallazgo: `approved` se persistía en una propiedad supuestamente cerrada

`review_manual.py` marcaba `review_status = "approved"` y `_build_create_entity`
lo escribía **literalmente** como propiedad del nodo en Neo4j. Pero `approved`
**no pertenece** a `ALLOWED_REVIEW_STATUS` —el conjunto cerrado que rige esa
propiedad— y el visor no tenía etiqueta para él, así que la interfaz pintaba la
cadena cruda. El dato entraba al grafo hablando un idioma que el grafo no declara.

Ahora se traduce **en la frontera de escritura** (`approved` → `reviewed`), tanto
para nodos como para relaciones, y la traducción levanta si el valor no es
traducible: nunca se escribe un `review_status` que nadie sepa interpretar.

**Y ahora sí está cerrado también en el visor.** La primera versión lo dejó a
medias: `review_status_label` protegía la ficha de una entidad, pero
`quality.html` y `source_detail.html` pintaban la **clave cruda** de los
contadores agregados, así que un `approved` heredado en el grafo seguía saliendo
en el panel de calidad como un estado legítimo del sistema — agregado y contado.
Un contador no es menos dato que una ficha: si el recuento nombra estados que el
sistema no reconoce, lo que se está midiendo no es lo que se cree.
`readonly.py` etiqueta ahora esos agregados y las dos plantillas pintan la
etiqueta.

### Los tres adaptadores son igual de estrictos

`from_review_manual_status` hacía `.strip().lower()` mientras los otros dos
exigían el valor exacto. La asimetría no estaba razonada y su efecto es que
`" Approved "` se acepta por una frontera y se rechaza por las otras: *qué idioma
habla un dato* pasaba a depender de por dónde entró. Además, un `.lower()`
escondido dentro de un adaptador que decide sobre revisión humana es una
reparación que adivina. Ahora los tres son estrictos, y quien deba tolerar
formato lo hace antes de llamar y a la vista.

### Hallazgo: enumerar lo prohibido en vez de lo permitido

El guardián de la vía humana era `if rs == "auto_approved": error`. **Una lista de
un solo valor prohibido deja pasar todo lo que nadie pensó en prohibir**,
incluida una cadena arbitraria. Ahora se exige pertenencia al subconjunto
`HUMAN_REVIEWED` tras adaptar: se rechaza *por no estar permitido*, no *por estar
vetado*.

---

## 4. Ausencia de dato ≠ permiso

Tres formas de comprobarlo, todas con control positivo (`test_el_nodo_de_
referencia_es_visible_para_el_contexto_permisivo`) para que la denegación venga
del **dato ausente** y no de un lector sin permisos — un instrumento que siempre
dice que no tampoco mide nada:

* campo ausente y campo `= None` se comportan igual (que es lo que produce la
  proyección real cuando Neo4j no tiene la propiedad);
* tope de sesión ilegible **no** significa "sin tope" (H-B), y `NO_APLICA`
  tampoco abre;
* contexto completamente vacío no ve nada.

Los casos se derivan de `missing == DENY`: cambiar esa declaración en el registro
cambia lo que se exige (mutación J5).

---

## 5. Tabla de calibración

`python3 scripts/calibracion/mutaciones_calidad_datos.py` — cada fila: introducir
la violación, demostrar ROJO, revertir, demostrar VERDE. **Lo ejecuta el job
`Calibracion de gates` de CI**: vivía en la raíz, donde hay precedente
(`mutaciones.py`) pero donde ningún job lo corría, y una calibración que nadie
ejecuta se pudre hasta ser la foto de un día en vez de una propiedad del árbol.

| ID | Violación introducida | Resultado |
|---|---|---|
| J1 | se borra `known_from_session` del registro | ROJO |
| J2 | se borra la dimensión de **contexto** `max_visible_session` | ROJO |
| J3 | una dimensión deja de aplicar a relaciones | ROJO |
| J4 | una dimensión del dato deja de viajar en la proyección (H1) | ROJO |
| J5 | `missing=DENY` → `NEUTRO` | ROJO |
| J6 | el motor deja de denegar `scope` ausente | ROJO |
| J7 | el motor deja de denegar `workspace` ausente | ROJO |
| J8 | tope ilegible vuelve a significar "sin tope" (H-B) | ROJO |
| J9 | se cuela un **quinto** valor en el vocabulario canónico | ROJO |
| J10 | el canónico pierde un valor y las etiquetas no se enteran | ROJO |
| J11 | `normalize` acepta lo desconocido (default permisivo) | ROJO |
| J12 | el adaptador convierte lo automático en "revisado" | ROJO |
| J13 | el adaptador de candidatos deja de ser total | ROJO |
| J14 | la frontera de escritura escribe el idioma ajeno | ROJO |
| J15b | la vía humana deja de exigir pertenencia al conjunto permitido | ROJO |
| **R8** | **dimensión de bypass total nueva + metida en la cuarentena en el mismo commit** | **ROJO** |
| R8-control | la misma dimensión nueva **sin** meterla en la cuarentena | ROJO |

**17/17 rojo → revertir → verde.**

R8 es la fila que importa de esta segunda ronda: es el escenario exacto con el
que la revisión demostró que la cuarentena no frenaba, y con la comprobación
anterior salía **verde**. Es una mutación de **tres ficheros coordinados**
(`models.py` + `engine.py` + el fichero de la cuarentena), porque un cambio
coordinado no se reproduce mutando un solo fichero — el arnés tuvo que aprender a
hacerlo.

### Lo que la calibración encontró y no habría salido de otro modo

* **J7 salió VERDE al primer intento.** No porque el comprobador fuese ciego,
  sino porque *la mutación apuntaba a la línea equivocada*: tocaba la regla de
  pertenencia (`ws not in ctx.allowed_workspaces`), no el guardián fail-closed
  (`isinstance(ws, str)`). Calibrar también sirve para descubrir que uno estaba
  midiendo el sitio equivocado.
* **J15 salió VERDE y era un agujero real.** La suite de data-engine sólo
  ejercitaba `approved` (válido) y `auto_approved` (atrapado por la rama
  anterior); `pending`, `deferred` y `rejected` no llegaban nunca a
  `_validate_write_provenance`. Se escribió el test que faltaba
  (`test_la_validacion_de_procedencia_rechaza_todo_lo_que_no_acredite_revision`),
  y con él la mutación se pone roja (J15b).
* **R8 no lo encontró mi calibración: lo encontró la revisión independiente.**
  Yo no había escrito la mutación que medía mi propio freno, y por eso pude
  afirmar en prosa que frenaba. La lección se aplica a este documento: la parte
  más peligrosa de un carril de calibración es la afirmación que uno no se ha
  molestado en intentar romper.

### Superviviente declarado

| ID | Mutación | Por qué sobrevive |
|---|---|---|
| J15 | la misma que J15b, mirada desde la suite de **data-engine** | ningún test de data-engine hace llegar `pending`/`deferred`/`rejected` a `_validate_write_provenance`. La cobertura real vive en el visor (J15b). Describe una carencia de esa suite, no del guardián. |

No se oculta: el arnés lo ejecuta en cada corrida y avisa **si deja de sobrevivir**,
porque entonces la explicación habría caducado.

---

## 6. Lo que NO se ha probado

* **Nada contra producción.** Ni VM105, ni Neo4j productivo, ni ingesta, ni
  despliegue, ni backups. El grafo real puede contener valores `approved`
  escritos antes de este cambio; **no se ha migrado nada** y no se propone
  hacerlo aquí.
* **No se ha corregido** la falta de declaración de `admin_full`,
  `can_view_reference` y `character_knowledge`: `policies/**` es zona prohibida
  para este carril. Están en cuarentena declarada y comprobada.
* **Mutación por cobertura exhaustiva:** no se han mutado todas las líneas de los
  módulos tocados, sólo las 19 afirmaciones que este carril sostiene.
* **La red inversa es sintáctica** (expresiones regulares sobre el código del
  motor). Una lectura suficientemente indirecta —`getattr(ctx, nombre)`, un
  `node.get(variable)`— se le escaparía. Es el límite conocido del instrumento y
  se hereda del diseño anterior; se ha ampliado (contexto y aristas), no
  resuelto.
* **La red sólo barre `engine.py` y `models.py`.** Ver §1: `authz/scope.py`,
  `authz/filtered_provider.py`, `main.py` y `jobs_client.py` deciden con
  `admin_full` fuera del barrido, y hay **tres productores** de esa potestad
  —`context.py:100` (rol admin), `scope.py:131` (`role == "admin"` otra vez) y
  `context.py:88` (`S9K_AUTH_ENABLED` falso ⇒ `admin_full=True` para cualquier
  anónimo)—, ninguno declarado en el registro. Declarado, no corregido:
  `authz/**` es zona prohibida.
* **`rpg_schema._v_review` sigue degradando en silencio.** Usa
  `_coerce_vocab(..., "auto_extracted")`, así que un `review_status` ilegible que
  entre por la vía de ingesta principal se convierte en `auto_extracted` en vez
  de fallar, y `""` acaba en `None`. Es decir: **"un único idioma en el grafo"
  todavía NO es total.** Este carril ha cerrado la vía de revisión humana y la
  de relaciones; la vía de ingesta principal sigue con un default permisivo y no
  se ha tocado porque no formaba parte del encargo. Queda dicho, no arreglado.
* **La rama de relaciones es hoy inalcanzable** (`allow_relationships=False`).
  Ahora tiene testigo (`test_la_rama_de_RELACIONES_tambien_adapta_en_la_frontera`)
  pero nunca se ha ejercitado contra una ingesta real.
* **Integración real contra Neo4j:** el job `test-neo4j-authz` de CI la cubre; no
  se ha ejecutado localmente.

## 7. Ficheros

| Fichero | Cambio |
|---|---|
| `contracts/review-status/v1/model.py` | **nuevo** — vocabulario canónico + 3 adaptadores de frontera |
| `viewer/tests/test_provider_authz_fields_contract.py` | la lista a mano pasa a derivarse; 3 redes inversas nuevas |
| `viewer/tests/test_calidad_de_datos_v2.py` | **nuevo** — derivación, fail-closed, vocabulario |
| `viewer/app/labels.py` | las etiquetas se derivan del canónico; un estado no canónico ya no se pinta como legítimo |
| `data-engine/app/schemas/rpg_schema.py` | `ALLOWED_REVIEW_STATUS` deriva del canónico |
| `data-engine/app/review/ingest_approved.py` | adaptador en la frontera de escritura; guardián por conjunto permitido |
| `data-engine/app/review/approved_writer.py` | el literal legacy pasa a constante declarada del contrato |
| `data-engine/app/tests/test_safe_writer.py` | la aserción refleja el valor canónico persistido |
| `contracts/review-status/v1/tests/` | **nuevo** — pruebas propias del contrato, como sus dos hermanos |
| `viewer/app/review_status_contract.py` | **nuevo** — módulo frontera único del visor |
| `data-engine/app/review_status_contract.py` | **nuevo** — módulo frontera único del motor |
| `viewer/app/routers/readonly.py` | etiqueta los contadores agregados de `review_status` |
| `viewer/app/templates/quality.html`, `source_detail.html` | pintan la etiqueta, no la clave cruda |
| `scripts/calibracion/mutaciones_calidad_datos.py` | **nuevo** — arnés de calibración, ejecutado por CI |
| `.github/workflows/ci.yml` | el job `Calibracion de gates` ejecuta también este arnés |
| `pytest.ini` | añade `contracts/review-status/v1/tests` a `testpaths` |

### Nota sobre los dos módulos frontera

El bloque que carga el contrato por ruta estaba **copiado cuatro veces**, cada
copia con su propio `parents[N]` — irónico en un carril cuyo encargo era eliminar
segundas declaraciones. Ahora hay **dos** módulos frontera, no uno, y no por
descuido: `viewer/` y `data-engine/app/` son dos árboles de `sys.path` distintos
que no pueden importarse entre sí (ver el docstring del `conftest.py` de la
raíz). Uno por árbol es el mínimo posible; el precedente es
`authz/visibility_contract.py`. Comparten el nombre de módulo en `sys.modules`
a propósito, para que ambos obtengan **el mismo objeto `Enum`**.

Eso último era, hasta ahora, **prosa**: se afirmaba aquí y en el docstring del
módulo, y nada se ponía rojo si dejaba de ser cierto. Ahora es una medida:
`test_los_dos_modulos_frontera_exponen_EL_MISMO_objeto_Enum` compara por
IDENTIDAD (`is`), no por igualdad — `ReviewStatus` hereda de `str`, así que dos
enums duplicados seguirían comparando `==` iguales y `==` no mediría nada. La
mutación **J16** cambia `_MODULE_NAME` en el módulo frontera del visor y lo pone
rojo.

### El arnés se calibra a sí mismo

Dos defectos del propio `mutaciones_calidad_datos.py`, ambos del género "el
instrumento se pone verde por no estar midiendo":

* **Pasaba en vacío.** Con `MUTACIONES = []` imprimía `CALIBRACION COMPLETA:
  0/0` y devolvía `rc=0`: vaciar la batería entera era un cambio *verde* en CI.
  Ahora hay un suelo, `MINIMO_MUTACIONES = 19`, comprobado con un `assert`
  **antes** de la línea base. Comprobado en las dos direcciones: con el arnés
  anterior y las listas vacías, `0/0` y `rc=0`; con el actual, `AssertionError`
  y `rc=1`.
* **Dos ediciones al mismo fichero se pisaban.** Cada edición se escribía como
  `pristino.replace(...)`, de modo que en una mutación coordinada sobre un solo
  fichero sólo sobrevivía la última. Ahora cada edición parte del estado
  acumulado. La mutación **J17** es justamente ese caso —dos ediciones sobre
  `contracts/review-status/v1/model.py`—. Medido en las dos direcciones:

  | Algoritmo | Edición 1 (`MACHINE_APPROVED` en el `Enum`) | Resultado de J17 |
  |---|---|---|
  | anterior (`replace` sobre el prístino) | **perdida** | rojo por `AttributeError: type object 'ReviewStatus' has no attribute 'MACHINE_APPROVED'` — la mitad que quedó era incoherente |
  | actual (encadenado) | presente | rojo por la razón declarada: `RuntimeError: review-status/v1 declara estados sin traducción al español: ['auto_approved']` |

  En J17 el defecto producía un rojo **espurio**, no un verde; pero el verde
  falso es alcanzable y se ha medido aparte: con la edición peligrosa (la de
  J11, que se sabe roja) seguida de una edición inocua, el algoritmo anterior
  la borraba y daba `rc=0` —el arnés lo habría reportado como "esta afirmación
  no está medida"— mientras que el actual da `rc=1`. Es decir: el defecto podía
  **apagar** una mutación sin que nadie se enterase.
