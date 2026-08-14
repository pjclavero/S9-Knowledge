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

| Caso (matriz de la política) | Anónimo | Lector legítimo |
|---|---|---|
| capa juego, `player` | no *(antes **sí**, con el texto completo)* | **sí** |
| capa juego, `reference` | no | **sí** |
| capa juego, `secret` | no | no |
| capa juego, `narrator` | no | no |
| capa juego, `deny` | no | no |
| visibilidad inválida | no | no |
| sin ámbito declarado | no | no |
| partida ajena | no | no |
| partida sin sesión de revelación | no | no |
| sesión futura | no | **sí** (según rol/tope) |
| workspace ajeno | no | no |
| **TOTAL** | **0 de 11** | **4 de 11** |

Fijada en `viewer/tests/test_panel_entities.py` (carril G),
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
| **M3** | conceder por **ausencia de partida**: `partida_in_scope` → `True` | **1** prueba | panel C | `c896051c659af3e8` ✔ |
| **M4** | el **productor** concede la llave al anónimo | **11** pruebas | G, F, C + suite HTTP | `37d225920b2207dd` ✔ |
| **M5** | **colapso**: retirar la llave también al legítimo (ocultar de más) | **26** pruebas | G + suite HTTP | `37d225920b2207dd` ✔ |

**M5 es el control que impide «arreglar» esto apagando el visor.** Un usuario
autenticado y autorizado sigue viendo lo suyo, y si dejara de verlo, 26 pruebas
lo dicen.

### Ablación: qué se puede cobrar como defensa y qué no

* **La regla 2b-bis del motor es necesaria** — M1 la anula y 10 pruebas caen.
* **El cambio de `partida_in_scope` es necesario** — M3 lo anula por separado y
  el panel C cae. Es decir: **no es redundante con el motor**; es la única
  defensa del corpus que no vive en el grafo. Si no se hubiera tocado, la
  decisión estaría aplicada a medias y con el CI en verde.
* **M3 sólo pone roja 1 prueba.** Se dice tal cual, sin adornarlo: la cobertura
  de esa segunda puerta es **mucho más fina** que la del motor. Es suficiente
  para demostrar que la defensa muerde, no para afirmar que está bien cubierta.

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

Las otras pruebas que sólo corren en CI son las de navegador (Playwright), que
no construyen contexto ni dependen de la capa juego.

---

## 8. Supervivientes y limitaciones, sin racionalizar

1. **Con la autenticación desactivada el visor ya no sirve absolutamente nada.**
   Es la consecuencia buscada, pero es un cambio de comportamiento operativo
   real: cualquier despliegue que dependiera del modo abierto para *ver algo*
   deja de hacerlo. No es un efecto lateral escondido, es la decisión.
2. **La cobertura de `partida_in_scope` es fina** (M3 → 1 prueba). Dicho en §5.
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
