# 81 — LORE_ANÓNIMO = DENEGADO

**Carril:** LORE-ANONIMO-DENEGADO · **Rama:** `feat/lore-anonimo-denegado` ·
**Base:** `main@420f626` · **Fecha de la decisión:** 2026-08-14 (V3 RC)

---

## 1. La decisión, literal

> **LORE_ANÓNIMO = DENEGADO en V3 RC.** Auth desactivada produce contexto
> anónimo sin privilegios. **La ausencia de partida no concede visibilidad
> adicional.** Cualquier futura exposición pública de lore requerirá una
> **política explícita y pruebas propias**.

La razón del operador, que es la parte que hay que conservar aunque el código
cambie: hacer lo contrario **reintroduciría una vía permisiva implícita**
precisamente donde ya se decidió que «auth desactivada ≠ acceso total». Si algún
día se quiere lore público, tiene que ser una **capacidad explícita y diseñada
como tal, no un fallback del sistema**.

---

## 2. Qué había, medido antes de tocar nada

Con `S9K_AUTH_ENABLED` ausente o `false`, el contexto ya era anónimo y de mínimo
privilegio: `admin_full=False`, sin `can_view_secret`, sin `can_view_reference`,
sin partidas, `max_visible_session=0`. **Eso estaba bien y no se ha tocado.**

Lo que sí pasaba: la **capa juego** (`scope=juego`, `visibility=player`) era la
única rama del ámbito **sin ninguna condición sobre el LECTOR**. Bastaba superar
la barrera de workspace, y un anónimo la supera porque el workspace por defecto
del despliegue entra en `allowed_workspaces`. En el corpus que no vive en el
grafo —propuestas V3, contratos de revisión, cola de trabajos, acotados con
`VisibilityScope.partida_only()`— pasaba lo mismo por otra puerta:
`partida_in_scope(None, ctx)` devolvía `True` incondicionalmente.

Resultado medido por **dos carriles independientes sobre huecos distintos**
(paneles G y F, `docs/77 §3` y `docs/78 §3`): **1 de 11 casos visible**, mismo
veredicto y misma proporción. Ese caso salía en la lista, contaba en los
contadores y **su ficha respondía 200 con el texto completo**.

Dicho en una frase: **la llave de la capa juego era, literalmente, no tener
partida**. Una ausencia concediendo — la misma inferencia permisiva que M5c
arrancó del dato («sin `partida_id` = lore compartido»), sobreviviendo un nivel
más arriba, en el lector.

---

## 3. Qué se cambió, y por qué es la mínima intervención

Tres líneas de decisión y una dimensión declarada. Nada más.

### 3.1 Una dimensión nueva, declarada como todas las demás

`can_view_lore` en `ViewerContext`, con valor por defecto **`False`**. El
encargo pedía no inventar vocabulario paralelo, y no se inventa: se usa el
mecanismo que ya existe. Ninguna dimensión declarada servía —`admin_full` es el
bypass total, `can_view_reference` es la llave del nivel `reference`,
`character_knowledge` concede por nodo—, así que la capa juego necesitaba llave
propia, y la lleva **declarada en el registro M5b**
(`viewer/app/policies/registry.py`) con la cadena completa: autoridad,
productor, almacenamiento, consumidores, semántica de ausencia y de invalidez,
revocación, prueba negativa y prueba HTTP de extremo a extremo.

| | |
|---|---|
| autoridad | servidor (rol del principal **autenticado**, releído en cada petición) |
| productor | `viewer/app/authz/context.py` (`build_viewer_context`) — el productor **único** |
| consumidores | `policies/engine.py`: `can_view` regla 2b-bis, y `partida_in_scope` |
| ausencia / inválido | `MINIMO` → `False` → no conceder |
| revocación | inmediata (cambio de rol) |

### 3.2 La regla, en el motor, como barrera de ÁMBITO

```
2b-bis. `scope=juego` exige `can_view_lore`  →  si no, `lore_not_allowed`
```

Va **con el ámbito**, junto a workspace y partida, **no con el nivel de
contenido**. La consecuencia importa: **`known_by` y `character_knowledge` no la
saltan**, igual que no saltan workspace ni partida. Saltan la regla de *nivel*,
que es otra cosa. Está colocada antes de `ctx.knows` y fuera del `if not knows`.

`deny` sigue siendo terminal y no se ha tocado: la regla 0 va deliberadamente
**antes** del bypass de administrador, y 2b-bis va después de ambos.

### 3.3 La segunda puerta, la del corpus fuera del grafo

```python
if partida_id is None:
    return ctx.can_view_lore   # antes: return True
```

Un registro sin partida es material de capa juego, así que pide **la misma
llave** que la capa juego pide en `can_view`. Una sola dimensión, dos
consumidores; no dos criterios que puedan divergir.

### 3.4 La cadena de autoridad no se toca

El rol sigue siendo **entrada** del constructor y no se reevalúa aguas abajo. No
hay ningún `role ==` nuevo en ningún consumidor. La cadena sigue siendo
`principal → build_viewer_context → dimensión → consumidores`, y `can_view_lore`
entra por ahí como `admin_full` y `can_view_reference`.

**Por qué es mínima:** no se ha tocado el punto de inyección congelado, ni el
chasis, ni `ci.yml`, ni los benchmarks, ni ninguna guarda de ruta, ni el
serializador, ni el Cypher. El cambio de comportamiento vive en **dos `if`** y
en el productor. Todo lo demás del diff es la consecuencia declarada: las
pruebas que fijaban el comportamiento viejo.

---

## 4. La tabla nueva: 0 de 11, medida

Contra el árbol de esta rama, con la app real y el proveedor **base**
sustituido, atravesando la cadena de autorización entera. Una fila por caso, y
las **dos** direcciones en la misma fila.

> **Corregido tras la auditoría.** La primera versión de este apartado mezclaba
> las dos tablas: listaba los casos del carril **F** y declaraba el total del
> carril **G** (3 «sí» visibles, «4 de 11» escrito). Los tests siempre
> estuvieron bien y la columna del anónimo —la que sostiene la decisión— era
> correcta; el defecto era **documental, en el artefacto de auditoría**, que es
> justo donde menos puede permitirse. Aquí van las dos, cada una copiada de su
> test, **y los conjuntos de casos NO son idénticos**: ya estaba dicho en
> `docs/78 §3` («solapados pero no idénticos»), y ésa es la razón de que un
> total no sirva para la otra.

**Carril G — `viewer/tests/test_panel_entities.py::TABLA_ANONIMO_VS_LECTOR`**

| Caso (matriz de la política) | Anónimo | Lector legítimo |
|---|---|---|
| `lore-player` | no *(antes **sí**, con el texto completo)* | **sí** |
| `lore-secreto` | no | no |
| `lore-narrador` | no | no |
| `lore-referencia` | no | **sí** |
| `lore-futuro` | no | **sí** (tope 5) |
| `partida-A` | no | **sí** (partida activa) |
| `workspace-ajeno` | no | no |
| `sin-scope` | no | no |
| `visibilidad-rara` | no | no |
| `visibilidad-deny` | no | no |
| `known-by-malformado` | no | no |
| **TOTAL** | **0 de 11** | **4 de 11** |

**Carril F — `viewer/tests/test_panel_sources.py::TABLA_ANONIMO_VS_LECTOR`**

| Caso | Anónimo | Lector legítimo |
|---|---|---|
| capa juego, `player` | no *(antes **sí**)* | **sí** |
| capa juego, `reference` | no | **sí** |
| capa juego, `secret` | no | no |
| capa juego, `narrator` | no | no |
| capa juego, `deny` | no | no |
| visibilidad inválida (`verde`) | no | no |
| sin ámbito declarado | no | no |
| partida ajena | no | no |
| partida sin sesión de revelación | no | no |
| sesión futura | no | **sí** (`can_view_future` del rol revisor) |
| workspace ajeno | no | no |
| **TOTAL** | **0 de 11** | **3 de 11** |

Las dos coinciden en lo que importa —**0 de 11 para el anónimo**— sobre
conjuntos de casos distintos, que es exactamente el argumento de la medición
original: dos arneses distintos no comparten un defecto por casualidad.

Fijadas en `viewer/tests/test_panel_entities.py` (carril G),
`viewer/tests/test_panel_sources.py` (carril F) y
`viewer/tests/test_panel_review_console.py` (carril C). En los tres:

* **se actualizó, no se borró**;
* **sigue siendo bidireccional**: la columna del lector legítimo se pone roja si
  se oculta de más;
* **sigue siendo una fila por caso**.

### El suelo de la tabla tuvo que cambiar, y hay que decirlo

El suelo anterior era `test_la_tabla_del_anonimo_no_es_unanime`: exigía que la
tabla trajese los dos veredictos, para que no se satisficiera con un panel roto.
**Con 0 de 11 ese suelo se autocumpliría al revés** —la columna del anónimo es
unánime a propósito, porque ésa es la decisión—, así que se sustituyó por uno
que no se autocumple: la columna del anónimo tiene que ser **cero**, y la del
lector legítimo **ni cero ni todo**.

---

## 5. Calibración: 5 mutaciones, ciclo completo, reversión por hash

Ningún gate entra sin control negativo conocido. Cada mutación: **VERDE →
mutar → ROJO → revertir → VERDE**, con la reversión verificada por hash del
fichero y exigiendo que el rojo lo produzcan los **guardianes declarados**, no
cualquier prueba.

| # | Mutación | Rojo | Guardianes que muerden | Hash antes = después |
|---|---|---|---|---|
| **M1** | revertir la denegación (la capa juego no pide llave) | **10** pruebas | paneles G y F + suite HTTP | `c896051c659af3e8` ✔ |
| **M2** | conceder lore por **otra vía**: `and ctx.role != "anonymous"` | **10** pruebas | paneles G y F + suite HTTP | `c896051c659af3e8` ✔ |
| **M3** | conceder por **ausencia de partida**: `partida_in_scope` → `True` | **2** pruebas | panel C | `c896051c659af3e8` ✔ |
| **M4** | el **productor** concede la llave al anónimo | **11** pruebas | G, F, C + suite HTTP | `37d225920b2207dd` ✔ |
| **M5** | **colapso**: retirar la llave también al legítimo (ocultar de más) | **26** pruebas | G + suite HTTP | `37d225920b2207dd` ✔ |

**Todas las cifras de esta columna son COTAS INFERIORES**, por dos motivos
distintos que conviene no confundir:

1. se midieron sobre una **selección** (paneles + HTTP + registro), no sobre la
   suite entera — 5 mutaciones × 2 corridas completas era inviable;
2. y sin las **190 pruebas** que esta máquina salta (ver más abajo).

La auditoría independiente, con su propia variante del control de colapso y otra
selección, obtuvo **48 rojas** donde yo declaro 26. **No es una discrepancia**:
son mutaciones y selecciones distintas midiendo la misma propiedad, y las dos
son cotas. Lo que sostiene la garantía es que el control **muerde**, no el
número; el número sólo sirve para no fingir precisión que no tengo.

**M5 es el control que impide «arreglar» esto apagando el visor.** Un usuario
autenticado y autorizado sigue viendo lo suyo, y si dejara de verlo, se pone
rojo — y dice qué fila.

### Ablación: qué se puede cobrar como defensa y qué no

* **La regla 2b-bis del motor es necesaria** — M1 la anula y 10 pruebas caen.
* **El cambio de `partida_in_scope` es necesario** — M3 lo anula por separado y
  el panel C cae. Es decir: **no es redundante con el motor**; es la única
  defensa del corpus que no vive en el grafo. Si no se hubiera tocado, la
  decisión estaría aplicada a medias y con el CI en verde.
* **M3 ponía rojas 2 pruebas** (declaré 1; la cifra correcta la dio la
  auditoría). Y la corrección que importa no es esa: **las dos eran de la
  dirección ANÓNIMA**. Nada cubría la dirección contraria de la segunda puerta
  —que un lector con derecho **siga recibiendo** propuestas V3, contratos de
  revisión y cola de trabajos sin `partida_id`—, así que el control de colapso
  **no llegaba hasta ahí**: `partida_in_scope` podía devolver `False` siempre,
  vaciando esas tres pantallas para todo el mundo, sin una sola roja.
  Cubierto ahora en §5 bis (**N3**).

---

## 5 bis. Tres garantías que se afirmaban y NO estaban protegidas

Las encontró una auditoría independiente, y las tres tienen la misma forma —la
forma que este repositorio lleva siete rondas persiguiendo—: **una afirmación
cierta en el código que ninguna prueba podía poner roja**. Ninguna era
explotable; eso se dice en cada una, y «no explotable» no es «protegido».

Fijadas en `viewer/tests/test_lore_anonimo_denegado_invariantes.py` y
calibradas con **un proceso por mutación**:

| # | Afirmación que no estaba protegida | Mutación | Rojo | Hash |
|---|---|---|---|---|
| **N1** | «una dimensión booleana de concesión no puede fallar abierta si su defecto es `False`» | invertir el **defecto del campo** a `True` | **2** | `089793fbc8ae0f82` ✔ |
| **N2** | «es de ámbito, no de nivel; por eso `known_by` no la salta» | **mover** 2b-bis dentro de `if not knows` | **3** | `c896051c659af3e8` ✔ |
| **N3** | la segunda puerta en su **dirección legítima** | `partida_in_scope` → `False` (ocultar de más) | **12** | `c896051c659af3e8` ✔ |

**N1 — el defecto del campo.** La frase está en el registro (`missing=MINIMO`),
en `models.py` y en este documento, y **invertir el defecto dejaba las 1539 en
verde**. La `prueba_negativa` que la dimensión declaraba mide **monotonía**
(«con `can_view_lore=False` no se ve más»), que es **otra propiedad**: se
cumple igual con cualquier defecto, porque pasa el valor explícitamente. No era
explotable porque el productor lo fija en sus cuatro ramas — pero **el defecto y
esas líneas explícitas son mutuamente redundantes y ninguno estaba probado por
separado** (quitar la línea explícita del anónimo también daba cero rojas). Se
añade además una comprobación **general**: ninguna dimensión booleana de
concesión del `ViewerContext` puede tener defecto `True`, para que la próxima no
nazca desprotegida.

**N2 — ámbito contra nivel.** La mutación fiel es la que describió la auditoría:
no borrar la comprobación, sino **moverla** dentro del bloque de nivel. Es más
exigente que borrarla, porque **deja el comportamiento del anónimo intacto** —un
anónimo no tiene personaje legible, así que `knows` es `False` y la comprobación
se le sigue aplicando—. Medido: con la mutación fiel, **paneles G, F y C y toda
la suite HTTP siguen VERDES**, y las **únicas 3 rojas** son las tres
parametrizaciones de la prueba nueva. Eso confirma exactamente el diagnóstico:
lo que se perdía era **defensa en profundidad, no una puerta abierta**.

**N3 — la dirección que faltaba.** Ver arriba, en la ablación.

### Y una verificación independiente del guardián por AST, con su tropiezo

La auditoría afirmó que «ningún `role ==` nuevo aguas abajo» **no es una promesa
mía sino algo IMPUESTO**: sustituir la capacidad por `ctx.role == "anonymous"`
—hoy conductualmente equivalente— lo caza la red inversa del registro. Eso hay
que verlo, no creérselo, así que lo reproduje.

**Primer intento, fallido, y se apunta porque el error es el clásico de aquí:**
corrí la mutación contra `test_registro_de_autorizacion.py` y
`test_registro_es_especificacion_ejecutable.py`, **no mordió**, y estuve a punto
de anotar «el guardián no muerde». No mordía porque **el guardián no vive ahí**:
vive en `test_provider_authz_fields_contract.py`, que es quien usa
`authz_lecturas.dimensiones_de_contexto_consumidas`. **Un rojo que no aparece
porque no has ejecutado al guardián no es un guardián dormido: es una medición
mal apuntada**, y desde fuera las dos se parecen muchísimo.

Con la selección correcta muerde, y dice exactamente lo que debe:

```
FAILED test_provider_authz_fields_contract.py::
       test_ninguna_dimension_del_contexto_que_el_motor_consulta_queda_sin_declarar_AST
       AssertionError: el motor decide con ['role'] y el registro no la declara
```

`c896051c659af3e8` → `bd4870c6c2f57acc` → `c896051c659af3e8`. Confirmado: la
cadena de autoridad única está **impuesta por el sistema**, no sostenida por mi
disciplina.

---

## 6. Prueba HTTP de extremo a extremo

`viewer/tests/test_lore_anonimo_denegado_http.py` — la que declara el registro.
No fabrica ningún contexto: crea el usuario en `auth.db`, pide con cookie de
sesión real y mira lo que devuelve el visor. Cubre, en este orden:

0. **el instrumento muerde** — cambiar el principal cambia el resultado; si no,
   el banco no está conectado a nada y todo lo demás no mediría;
1. la dimensión, en sus dos mitades sobre el mismo corpus;
2. que con auth desactivada **no se entrega nada**;
3. que **tampoco por ID** —la barrera no depende de por dónde se entre—;
4. **colapso**: el lector legítimo y el admin no pierden nada;
5. **revocación**: degradar el rol en `auth.db` retira la llave en la
   **siguiente** petición, con la misma sesión. El registro declara la
   revocación como inmediata, y una revocación que nadie ejerce es una
   declaración, no una garantía.

### El punto de inyección congelado no se ha tocado

`get_filtered_provider` llama a `get_visibility_context` como **función normal**,
no vía `Depends`. Sustituirlo con `dependency_overrides` es **inerte** y sale
verde por no morder. Ninguna prueba nueva lo usa: se sustituye el proveedor
**base** y se atraviesa la cadena real, o se sustituyen `get_filtered_provider` /
`get_visibility_scope`, que sí entran por `Depends`.

---

## 7. Alcance real del cambio, sin disimularlo

El cambio de política puso **133 pruebas en rojo** sobre 1499. No es ruido: es
la medida de cuánto material dependía de que la capa juego no pidiera llave.
Se resolvió así, y conviene saber cuál es cuál:

* **~110 pruebas**: contextos construidos a mano (`ViewerContext(...)`) que
  representan a un **lector legítimo**. Se les añadió `can_view_lore=True`, que
  es lo que el productor real les da. Concentradas en **una factoría por
  fichero**, así que son pocas líneas.
* **~35 pruebas de PANEL**: las que fijaban el comportamiento viejo. Es lo que
  se buscaba al fijarlo. Tablas actualizadas, tests invertidos con su razón
  escrita, y contrapesos nuevos donde el test invertido era el que sostenía la
  otra dirección.
* **Un grupo aparte, y es el hallazgo incómodo**: pruebas de **pintado** que
  pedían como anónimas y funcionaban porque el anónimo recibía la capa juego.
  Cerrada la vía, **habrían seguido en VERDE sin renderizar nada** — un panel
  que no muestra nada pasa cualquier prueba de que no muestra de más. Se les
  puso un lector legítimo (`lector_scope`, `cliente_lector`,
  `lector_por_dependencia`). **Ninguna de ellas se habría detectado leyendo el
  diff**; salieron de correr la suite.

**Medido sobre este árbol:** `1539 passed, 191 skipped, 0 failed`, en orden fijo
y en orden aleatorio. Línea base en `main@420f626`: `1499 passed, 191 skipped`.

### Lo que la medición local NO vio, y hay que decirlo

**Verde local no fue verde en CI.** `viewer/tests/test_neo4j_integration_authz.py`
se **salta** en esta máquina —no hay Neo4j efímero—, así que sus 19 pruebas
formaban parte de esos `191 skipped` y **nunca se ejercieron en ninguna de mis
mediciones**. En CI se pusieron rojas dos:

* `test_known_by_valido_concede_y_solo_a_quien_toca` — el nodo `conocido` es
  `scope=juego`, así que sin la llave lo denegaba 2b-bis **antes** de llegar a
  `known_by`: rojo por el motivo equivocado.
* `test_las_relaciones_llegan_con_su_visibilidad` — la única arista no secreta
  tiene `lore` (`scope=juego`) como extremo, y una relación exige que **ambos**
  extremos sean visibles. Sin la llave no quedaba ni una arista.

Se arregló con el mismo cambio mecánico que las otras diez suites
(`can_view_lore=True` en la factoría, que representa a un lector autenticado).
Pero el hallazgo que importa no es el arreglo: **una suite que no corre donde se
mide no está medida**, y «1539 passed en local» no era la cobertura que parecía.

Hay un segundo efecto de esto que conviene apuntar: mientras las aristas venían
vacías, `test_una_arista_no_revela_un_extremo_secreto` **pasaba por vacío**
—recorría una lista vacía—. Es un bucle vacío que no ejercía nada, y sólo se vio
porque el fallo de al lado obligó a mirar. Con el arreglo vuelve a ejercerse.

### Un tercer «pasa por vacío», y éste no lo encontré yo

Los bancos de medida de `docs/measurements/72-saturacion-grafo/` construyen su
`ViewerContext` **a mano** y alimentan fixturas `scope="juego"`. Sin la llave,
**todos sus nodos caen en `lore_not_allowed`: el banco mide CERO y no lo dice**.
No lo ejecuta pytest ni CI, así que nada enrojece — es exactamente el fallo
silencioso que ese banco existe para detectar, un nivel más arriba, y es
**el dual de N1**: con el defecto del campo abierto, estos harnesses habrían
seguido funcionando y el problema no habría existido.

La auditoría señaló `harness_gsat.py`. Al ir a arreglarlo resultó que **la
familia son cuatro**: `harness_gsat`, `harness_ablacion`, `harness_opciones` y
`harness_http`, todos con la misma forma. Los cuatro llevan ahora
`can_view_lore=True` —un revisor autenticado la tiene, así que añadirla es lo
que **reproduce** la medida registrada, no lo que la relaja: no se toca
workspace, ni partida, ni `known_by`, ni el tope, ni `admin_full`— y
`harness_gsat` lleva la nota de cabecera que explica por qué.

Verificado ejecutándolo: antes de la corrección medía cero en silencio; después
vuelve a dar las cifras del registro (`modo=head`, `n=300`, `cob=100.00%`).

Severidad baja —registro congelado, no es producto— pero el hallazgo que
importa es de método: **barrí las 65 construcciones directas de `ViewerContext`
de los tests y no barrí las de `docs/` ni `scripts/`**. El barrido tiene que ser
del repositorio, no de la carpeta que uno tiene en la cabeza.

Las otras pruebas que sólo corren en CI son las de navegador (Playwright), que
no construyen contexto ni dependen de la capa juego.

**Desglose de los 191 saltos, y qué implica**: 171 son de navegador (Playwright
sin librería en esta máquina), 19 los de Neo4j que se acaban de contar, y 1
lógico. CI **sí** los ejecuta y además tiene guardia anti-skip, así que no hay
riesgo de producto. Pero tiene una consecuencia que hay que escribir con todas
las letras: **los cinco recuentos de mutación de §5 son COTAS INFERIORES**, no
totales — se midieron sin esas 190 pruebas. La auditoría comprobó que ninguna de
navegador depende de que el anónimo reciba lore, así que **aquí la cota no
oculta nada**; pero es una cota, y llamarla total sería la misma clase de cifra
cierta por no mirar que este carril ha estado persiguiendo.

---

## 8. Supervivientes y limitaciones, sin racionalizar

1. **Con la autenticación desactivada el visor ya no sirve absolutamente nada.**
   Es la consecuencia buscada, pero es un cambio de comportamiento operativo
   real: cualquier despliegue que dependiera del modo abierto para *ver algo*
   deja de hacerlo. No es un efecto lateral escondido, es la decisión.
2. **La cobertura de `partida_in_scope` sigue siendo la más fina de las dos
   puertas**, aunque ya cubre las dos direcciones (§5 bis, N3). Se mide sobre
   la unidad (`VisibilityScope.allows`) y sobre el panel C, **no** por HTTP
   contra `/v3/review`, `/review-console` y `/api/jobs` a la vez.
3. **`can_view_lore` se concede por ROL, a los tres roles.** Hoy no hay ninguna
   concesión por usuario ni por workspace. Si mañana hiciera falta un rol que
   entre pero no vea lore, la dimensión lo soporta, pero **hoy no está
   ejercido** y no me lo apunto como capacidad.
4. **La columna «barrera» de `docs/77 §3` cambió de significado en varias
   filas**: para un anónimo, 2b-bis muerde antes que la regla de nivel, que la
   de sesión y que `known_by`. Esas barreras siguen midiéndose sobre el lector
   legítimo, que es quien llega hasta ellas. Está escrito allí en vez de dejar
   la tabla como estaba.
5. **No se ha medido contra Neo4j real** ni contra ningún entorno de producción.
   Todo es la app real con proveedor base sustituido y `auth.db` temporal.
6. **La coincidencia G/F de la medición vieja era «mismo veredicto y misma
   proporción sobre conjuntos solapados pero no idénticos»**, no celda a celda.
   Ya estaba corregido en `docs/78 §3` y se mantiene así.
7. **Toqué un fichero fuera de mi ámbito declarado**:
   `viewer/tests/test_neo4j_integration_authz.py`, porque mi cambio lo puso rojo
   y no se puede dejar CI en rojo. Es el mismo cambio mecánico de una línea que
   en las otras diez suites, no relaja ninguna barrera, y **queda señalado aquí
   para el carril del contrato Neo4j efímero**, por si colisiona con lo suyo.
8. **La calibración se ejerció sobre la selección de paneles + HTTP + registro**,
   no sobre la suite entera en cada ciclo (5 mutaciones × 2 corridas completas
   habría sido inviable). Los guardianes exigidos por mutación están declarados
   en §5, así que un rojo por otro sitio no cuenta como calibración.

---

## 9. Qué NO se tocó

`viewer/app/chassis.py`, `ci.yml`, `benchmarks/**`, el punto de inyección
congelado, las guardas de ruta del chasis, el serializador de Neo4j y el acotado
en Cypher. Los otros tres carriles abiertos (banco de rendimiento, contrato
Neo4j efímero, censo de rutas) no comparten ningún fichero con éste salvo los
tests de panel, que son de este bloque.
