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
declarado aquí**: quedan en `CONTEXTO_SIN_DECLARAR_EN_EL_REGISTRO`, una
cuarentena que **sólo puede encoger** (el test falla si crece *y* falla si una
deja de necesitar cuarentena y nadie la saca). Declararlas en el registro es
trabajo del propietario de `policies/**`.

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

`python3 mutaciones_calidad_datos.py` — cada fila: introducir la violación,
demostrar ROJO, revertir, demostrar VERDE.

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

**15/15 rojo → revertir → verde.**

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
  módulos tocados, sólo las 16 afirmaciones que este carril sostiene.
* **La red inversa es sintáctica** (expresiones regulares sobre el código del
  motor). Una lectura suficientemente indirecta —`getattr(ctx, nombre)`, un
  `node.get(variable)`— se le escaparía. Es el límite conocido del instrumento y
  se hereda del diseño anterior; se ha ampliado (contexto y aristas), no
  resuelto.
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
| `mutaciones_calidad_datos.py` | **nuevo** — arnés de calibración |
