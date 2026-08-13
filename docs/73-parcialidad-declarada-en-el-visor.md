# 73 — El visor declara cuándo la vista es parcial

Carril **VIEWER-PARTIALITY**. Rama `feat/viewer-parcialidad-declarada`, base `main@3f3face`.
Continuación directa de `docs/72` (PR #174): allí quedó **diagnosticado y medido** el desplome
cuadrático; aquí se cierra la parte que lo convertía en **una afirmación falsa de producto**.

## 1. Qué se arregla y qué NO

**NO se arregla el truncado.** `/api/graph` sigue devolviendo el subgrafo inducido sobre los
primeros `limit` nodos y la retención de relaciones sigue cayendo con `(limit/N)²`. El test de
caracterización `viewer/tests/test_saturacion_grafo_caracterizacion.py` sigue verde y **sin
tocar**: sigue midiendo lo mismo (llama al proveedor directamente, no al router).

**Se arregla la mentira.** Antes: el servidor no devolvía totales ni marca de truncado y el
cliente hacía `total = loaded`, así que 300 nodos y 171 aristas se presentaban **como si fueran
el grafo**. Ahora la respuesta dice si está completa o recortada, y el visor lo **declara en
pantalla** cuando no lo está.

## 2. Contrato

### Servidor — `GET /api/graph`

Añade un bloque `view` (el resto de la respuesta no cambia):

```json
{
  "workspace": "leyenda",
  "nodes": [...], "edges": [...],
  "view": {
    "limit": 300,
    "truncated": true,
    "nodes_shown": 300, "nodes_total": 2000,
    "edges_shown": 171, "edges_total": 6000
  }
}
```

`truncated` es cierto si falta **cualquier cosa**: puede caber el tope de nodos y faltar
relaciones igualmente — que es exactamente el desplome cuadrático.

Implementación: `viewer/app/graph_view.py::vista_truncada`, llamada desde
`viewer/app/api/graph.py`. El router pide al proveedor filtrado **sin tope** (`limit=SIN_TOPE`,
la `_ALL` de producción importada, no una copia) y recorta después; el proveedor ya materializaba
el conjunto completo en cada llamada, así que no se añade una pasada nueva.

### Cliente — `/graph`

- `viewer/app/templates/graph.html`: `<p id="graph-partiality" role="alert">` sobre el lienzo.
  `role="alert"`, no `status`: no es un estado más de carga, es una advertencia.
- `viewer/app/static/js/graph-core.js::partialityNotice(view)` (lógica pura, probada en Node)
  redacta el aviso; `graph.js` lo pinta.
- Texto en el caso truncado: *«Vista parcial: se muestran 300 de 2000 entidades y 171 de 6000
  relaciones de las que puedes ver. Las relaciones entre las entidades no mostradas quedan fuera,
  así que esta vista NO sirve para sacar conclusiones sobre la forma del grafo.»*
- **Fail-closed**: si falta `view`, le faltan claves, trae valores que no son números o es
  incoherente (mostrado > total; «completa» con cosas fuera), sale el aviso genérico *«Vista
  posiblemente incompleta: el servidor no ha indicado si se muestra todo el grafo.»*
  Romper el metadato hace que el visor **avise más**, nunca que se calle.

## 3. Los contadores y por qué son seguros

Se muestran cuatro cifras: `nodes_shown/nodes_total` y `edges_shown/edges_total`.

**Los cuatro se calculan sobre la salida de `PolicyFilteredProvider.graph(...)`**, es decir sobre
material que YA pasó por la política. `vista_truncada` no conoce al proveedor base y no puede
consultarlo. Los totales significan *«cuántos elementos autorizados para ti hay»*, nunca *«cuántos
hay en la base»*: un total real calculado antes de filtrar sería una fuga por conteo — revelaría
por diferencia cuánto material oculto existe.

El cliente **no deriva ninguna cifra**: no resta, no divide, no calcula porcentajes. Eso está
aseverado leyendo el cuerpo de la función (`test_el_cliente_no_calcula_cifras_propias`) y contando
los números del mensaje en la spec JS (sólo aparecen los cuatro que mandó el servidor).

Se ha reutilizado el mecanismo existente: los totales salen del mismo camino filtrado que ya
usaba `counts()`, que se comprobó filtrado de verdad. **No se ha introducido vocabulario paralelo
de autorización** y no se ha tocado `viewer/app/policies/**` ni `viewer/app/authz/**`.

## 4. Evidencia — cada control se ha visto ROJO

`viewer/tests/test_parcialidad_declarada.py` (18 casos, contrato del servidor, contadores y
plantilla) + la sonda JS mutada en `viewer/tests/test_graph_ux_v2.py` (2 casos) + 5 casos nuevos
en `viewer/tests/js/graph_core_spec.js` (55 en total, antes 50).

**Por qué la parte JS vive en `test_graph_ux_v2.py` y no junto al resto**: es el fichero que el job
`test-graph-js` ejecuta **por nombre**, con Node instalado y prohibiendo skips. Puesta en
`viewer/tests/` a secas, se habría omitido en silencio por falta de Node — un gate omitido no es un
gate, y `.github/scripts/check_ci_config.py` lo detectó y se puso ROJO cuando se intentó
(evidencia adicional de que ese gate previo funciona). No se ha tocado `ci.yml`.

Mutaciones **sobre el árbol real**, ciclo verde → rojo → revertir → verde:

| # | Mutación | Resultado |
|---|---|---|
| 1 | `serialize_graph(...)` sin `view=view` en el router (la regresión exacta previa) | ROJO — `test_api_graph_http_declara_la_vista` |
| 2 | Borrar `<p id="graph-partiality">` de la plantilla | ROJO — `test_la_pagina_trae_el_hueco_del_aviso` |
| 3 | `core.partialityNotice(lastView)` → `null` en `graph.js` | ROJO — `test_el_cliente_pinta_el_aviso` |

Revertidas las tres: **1243 pasados, 191 saltados**, el mismo recuento que antes del carril más
los 20 casos nuevos de Python (18 + 2).

Mutaciones **en memoria / sobre copias**, dentro de la propia suite (para que el gate lleve su
control negativo pegado y no dependa de que alguien repita el experimento a mano):

- `view` ausente, `view` sin cada una de sus 6 claves, `view` mintiendo (`truncated:false` sobre
  una vista recortada; totales igualados a lo mostrado) ⇒ el control levanta `AssertionError`.
- **Contar ANTES de filtrar** (`test_calibracion_contar_ANTES_de_filtrar_pone_el_gate_ROJO`): los
  totales se toman del proveedor **base**, sin política — 40 en vez de 10 — y el control de la
  regla 4 lo caza. No es un número escrito a mano: se calcula de verdad con el proveedor crudo.
- **JS, mutación del fichero ejecutada con Node**
  (`test_calibracion_js_romper_el_aviso_pone_la_sonda_en_ROJO`, en `test_graph_ux_v2.py`): tres mutantes de `partialityNotice` —callar siempre, declarar todo completo,
  avisar sin decir cuánto falta— y la sonda, que pasa en verde sobre el fichero real, sale ROJA
  sobre los tres. Revertir devuelve el verde en el mismo proceso.

**Ablación / necesidad**: `test_ablacion_sin_permisos_los_totales_colapsan`. El punto de inyección
`get_visibility_context` está congelado como deuda declarada y sobrescribirlo es **inerte**, así
que un test de rol podría salir verde sin ejercer nada. Aquí se exige que el resultado **cambie**
al quitar `can_view_reference`: 40/39 → 10/9. Si esas cifras fueran iguales, ningún test de este
módulo estaría midiendo la política y el módulo entero se caería.

**Supervivientes nombrados**:

1. `test_la_vista_del_router_es_byte_a_byte_la_del_proveedor` — `vista_truncada` reproduce el
   recorte de `PolicyFilteredProvider.graph`. Es un subconjunto por pertenencia de extremos sobre
   relaciones **ya autorizadas**, no lógica de autorización duplicada; pero una divergencia futura
   sería silenciosa (el visor dibujaría un grafo y contaría otro). Este test exige la identidad de
   ids sobre n=50, 500 y 2000.
2. `test_el_caso_alineado_tambien_se_declara` — la severidad depende de la alineación (2,85 % vs
   15,33 %), la **parcialidad no**. Si el aviso sólo saliera en el caso sintético, en producción
   —que es el caso alineado— el visor volvería a mentir.

## 5. Limitaciones declaradas

- **La severidad en producción sigue sin medir** (`docs/72` §9). Este carril no la mide y no la
  necesita: el aviso no afirma cuánto se pierde en producción, sólo cuánto se ha dejado fuera
  **en esta respuesta concreta**, con las cifras que el servidor acaba de contar.
- **El truncado sigue ahí.** Declarar la parcialidad no la reduce. Las opciones A/D/H de `docs/72`
  siguen abiertas.
- **La puerta de calibración de `benchmarks/perf/` queda invalidada**, y es lo correcto: este
  carril sí toca `viewer/app/**` y el `sha_del_sistema_medido` de
  `benchmarks/perf/resultados/calibracion.json` ya no corresponde al sistema que se publica.
  `run_bench.py` **rehusará medir** hasta que se recalibre. Se intentó recalibrar y **no se pudo**:
  `calibracion.py` aborta en C3 con `/api/entities/p_0000002 -> 404`. Se comprobó que **aborta
  igual sobre `main` sin ninguno de estos cambios** (mismo árbol, cambios guardados en `stash`),
  así que es una avería previa del banco, no de este carril. Se deja el JSON **sin tocar**: un
  hash caduco hace que la puerta rehúse, que es exactamente lo que debe pasar; regenerarlo a mano
  sería avalar cifras de un sistema que ya es otro.
- **El rendimiento en el navegador no se mide en este proyecto.** El aviso añade un párrafo de
  texto; ninguna afirmación de esta nota depende de suponer qué aguanta el cliente.
- **La política se ejerce en una sola dimensión** (`can_view_reference` + workspace), igual que en
  `docs/72`. `known_by`, reglas de partida y `max_visible_session` **no están cubiertas** por
  ninguna medida de este carril.
- El aviso se prueba en el **DOM real** sólo en la medida en que los tests de navegador existentes
  lo recorren: la comprobación de que el cliente lo pinta es sobre el **texto** de `graph.js`
  (`grep` estructurado) más la lógica pura en Node. No hay captura de navegador que demuestre el
  píxel; los `.js` nunca se ejecutan en un navegador en las pruebas de este proyecto.
- **Expandir vecinos no actualiza las cifras.** `expandNeighbors` añade nodos al lienzo desde
  `/api/entities/{id}`, que por diseño no informa de lo que falta (decirlo revelaría lo que la
  política oculta). Tras expandir, el aviso sigue mostrando los contadores de la última respuesta
  de `/api/graph`: queda **conservador** —sigue siendo cierto que la vista es parcial— en vez de
  inventar un total nuevo, que es exactamente lo que prohíbe la regla 3.
