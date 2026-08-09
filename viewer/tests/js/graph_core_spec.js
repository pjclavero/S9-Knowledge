/**
 * Especificación de graph-core.js (lógica pura del visor de grafo).
 *
 * Se ejecuta con `node graph_core_spec.js`. Imprime una línea por caso y
 * termina con código 1 si falla alguno: el test de pytest que lo invoca
 * (`viewer/tests/test_graph_ux_v2.py::test_graph_core_js_spec`) se pone rojo
 * con ese código de salida. En CI lo ejecuta el job `test-graph-js`, que
 * instala Node y prohíbe los skips.
 *
 * ALCANCE: solo lógica pura. Lo que necesita DOM o navegador (que buscar
 * centre el nodo, que la ficha se abra, que la URL restaure los filtros)
 * vive en `viewer/tests/browser/test_browser_graph_ux.py`, no aquí.
 *
 * Sin dependencias externas a propósito: no hay node_modules en el repo.
 */
"use strict";

const path = require("path");
const assert = require("assert");

const CORE = path.resolve(__dirname, "..", "..", "app", "static", "js", "graph-core.js");
const core = require(CORE);

let passed = 0;
const failures = [];

function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log("ok   - " + name);
  } catch (err) {
    failures.push(name + ": " + err.message);
    console.log("FAIL - " + name + " :: " + err.message);
  }
}

// --- Grafo de prueba ----------------------------------------------------
const GRAPH = {
  nodes: [
    { id: "n1", label: "Tamori Shiro", type: "Character", type_label: "Personaje", aliases: ["El Sabio"] },
    { id: "n2", label: "Ryōko Owari", type: "Location", type_label: "Lugar", aliases: [] },
    { id: "n3", label: "Clan Escorpión", type: "Faction", type_label: "Facción", aliases: ["Bayushi"] },
    { id: "n4", label: "Kuni Yori", type: "Character", type_label: "Personaje", aliases: [] },
    { id: "n5", label: "Amuleto de jade", type: "Object", type_label: "Objeto", aliases: [] }
  ],
  edges: [
    { id: "e1", from: "n1", to: "n2", type: "LOCATED_IN", label: "está en" },
    { id: "e2", from: "n1", to: "n3", type: "MEMBER_OF", label: "miembro de" },
    { id: "e3", from: "n4", to: "n3", type: "MEMBER_OF", label: "miembro de" },
    { id: "e4", from: "n4", to: "n5", type: "OWNS", label: "posee" }
  ]
};

// ---------------------------------------------------------------------
// Búsqueda
// ---------------------------------------------------------------------

test("búsqueda: encuentra por prefijo del nombre", () => {
  const res = core.searchNodes(GRAPH.nodes, "Tamori");
  assert.strictEqual(res.length, 1);
  assert.strictEqual(res[0].id, "n1");
});

test("búsqueda: ignora mayúsculas y tildes/macrones", () => {
  const res = core.searchNodes(GRAPH.nodes, "ryoko");
  assert.strictEqual(res.length, 1, "esperaba encontrar 'Ryōko Owari' buscando 'ryoko'");
  assert.strictEqual(res[0].id, "n2");
});

test("búsqueda: encuentra por alias", () => {
  const res = core.searchNodes(GRAPH.nodes, "Bayushi");
  assert.strictEqual(res.length, 1);
  assert.strictEqual(res[0].id, "n3");
});

// HALLAZGO H4. El caso anterior ("Kuni" contra "Kuni Yori el Viejo") pasaba
// por el desempate ALFABÉTICO, no por el score: "kuni" < "kuni yori el viejo".
// Borrando la ordenación por score, la prueba seguía verde. Los tres casos que
// siguen están elegidos para que el orden alfabético diga LO CONTRARIO que el
// score: si alguien quita el `a.score - b.score`, se ponen rojos.

test("búsqueda: la exacta gana a la que solo contiene, aunque vaya después alfabéticamente", () => {
  const nodes = [
    { id: "a", label: "Aa Kuni de la Montaña", type: "Character" },  // contiene (score 2)
    { id: "b", label: "Kuni", type: "Character" }                    // exacta   (score 0)
  ];
  const res = core.searchNodes(nodes, "Kuni");
  assert.strictEqual(res[0].id, "b",
    "la exacta debe ir primero; por orden alfabético saldría 'Aa Kuni…'");
});

test("búsqueda: el prefijo gana a la que solo contiene, contra el alfabeto", () => {
  const nodes = [
    { id: "a", label: "Agasha Tamori", type: "Character" },  // contiene "tamori" (score 2)
    { id: "b", label: "Tamori Shiro", type: "Character" }    // empieza por      (score 1)
  ];
  const res = core.searchNodes(nodes, "Tamori");
  assert.deepStrictEqual(res.map((n) => n.id), ["b", "a"],
    "el prefijo debe ir primero; alfabéticamente 'Agasha…' iría antes");
});

test("búsqueda: el alias (última familia) va detrás del nombre, contra el alfabeto", () => {
  const nodes = [
    { id: "a", label: "Aa Bayushi no es su nombre", type: "Faction", aliases: [] },
    { id: "b", label: "Zzz Clan Escorpión", type: "Faction", aliases: ["Bayushi"] },
    { id: "c", label: "Bayushi", type: "Character", aliases: [] }
  ];
  const res = core.searchNodes(nodes, "Bayushi");
  assert.deepStrictEqual(res.map((n) => n.id), ["c", "a", "b"],
    "orden esperado: exacta, contiene-en-el-nombre, solo-en-alias");
});

test("búsqueda: sin coincidencias devuelve lista vacía", () => {
  assert.deepStrictEqual(core.searchNodes(GRAPH.nodes, "zzzz-no-existe"), []);
});

test("búsqueda: query vacía no devuelve resultados (no es 'todo')", () => {
  assert.deepStrictEqual(core.searchNodes(GRAPH.nodes, "   "), []);
});

test("búsqueda: respeta el límite de resultados", () => {
  const res = core.searchNodes(GRAPH.nodes, "a", { limit: 2 });
  assert.ok(res.length <= 2, "el límite debe recortar la lista");
});

test("matchesQuery: query vacía casa con todo", () => {
  assert.strictEqual(core.matchesQuery(GRAPH.nodes[0], ""), true);
});

// ---------------------------------------------------------------------
// Filtros
// ---------------------------------------------------------------------

test("filtro: sin filtros devuelve el grafo entero", () => {
  const out = core.filterGraph(GRAPH, {});
  assert.strictEqual(out.nodes.length, 5);
  assert.strictEqual(out.edges.length, 4);
});

test("filtro por tipo de entidad: solo pasan los nodos de ese tipo", () => {
  const out = core.filterGraph(GRAPH, { entityTypes: ["Character"] });
  assert.strictEqual(out.nodes.length, 2);
  assert.deepStrictEqual(out.nodes.map((n) => n.id).sort(), ["n1", "n4"]);
});

test("filtro por tipo de entidad: no quedan aristas colgando", () => {
  const out = core.filterGraph(GRAPH, { entityTypes: ["Character"] });
  const ids = out.nodes.map((n) => String(n.id));
  out.edges.forEach((e) => {
    assert.ok(ids.indexOf(String(e.from)) !== -1 && ids.indexOf(String(e.to)) !== -1,
      "arista " + e.id + " apunta a un nodo filtrado");
  });
  assert.strictEqual(out.edges.length, 0);
});

test("filtro por tipo de relación: descarta las relaciones de otro tipo", () => {
  const out = core.filterGraph(GRAPH, { relationTypes: ["MEMBER_OF"] });
  assert.strictEqual(out.nodes.length, 5, "el filtro de relación no debe borrar nodos");
  assert.deepStrictEqual(out.edges.map((e) => e.id).sort(), ["e2", "e3"]);
});

test("filtro combinado: entidad + relación", () => {
  const out = core.filterGraph(GRAPH, {
    entityTypes: ["Character", "Faction"],
    relationTypes: ["MEMBER_OF"]
  });
  assert.strictEqual(out.nodes.length, 3);
  assert.strictEqual(out.edges.length, 2);
});

test("filtro + búsqueda: la query recorta también los nodos", () => {
  const out = core.filterGraph(GRAPH, { query: "kuni" });
  assert.strictEqual(out.nodes.length, 1);
  assert.strictEqual(out.nodes[0].id, "n4");
  assert.strictEqual(out.edges.length, 0);
});

test("filtro: tipo inexistente deja el grafo vacío (estado sin resultados)", () => {
  const out = core.filterGraph(GRAPH, { entityTypes: ["NoExiste"] });
  assert.strictEqual(out.nodes.length, 0);
  assert.strictEqual(out.edges.length, 0);
});

test("filtro: ocultar nodos sueltos elimina los que quedan sin relación", () => {
  const out = core.filterGraph(GRAPH, { relationTypes: ["OWNS"], hideIsolated: true });
  assert.deepStrictEqual(out.nodes.map((n) => n.id).sort(), ["n4", "n5"]);
  assert.strictEqual(out.edges.length, 1);
});

// HALLAZGO H5. Antes, `[]` se trataba como "no filtrar": desmarcar TODAS las
// casillas mostraba el grafo entero, exactamente igual que marcarlas todas.
// Ahora hay tres estados y estos dos casos los separan.

test("filtro: todas desmarcadas ([]) no deja pasar nada", () => {
  const out = core.filterGraph(GRAPH, { entityTypes: [] });
  assert.strictEqual(out.nodes.length, 0, "lista vacía = nada seleccionado, no 'todo'");
  assert.strictEqual(out.edges.length, 0);
});

test("filtro: 'todas desmarcadas' y 'sin filtro' NO dan el mismo resultado", () => {
  const nada = core.filterGraph(GRAPH, { entityTypes: [] });
  const todo = core.filterGraph(GRAPH, { entityTypes: null });
  assert.strictEqual(todo.nodes.length, 5);
  assert.notStrictEqual(nada.nodes.length, todo.nodes.length);
});

test("filtro: todas desmarcadas en relaciones deja los nodos pero ninguna arista", () => {
  const out = core.filterGraph(GRAPH, { relationTypes: [] });
  assert.strictEqual(out.nodes.length, 5);
  assert.strictEqual(out.edges.length, 0);
});

test("filtro: no muta el grafo original", () => {
  core.filterGraph(GRAPH, { entityTypes: ["Character"], hideIsolated: true });
  assert.strictEqual(GRAPH.nodes.length, 5);
  assert.strictEqual(GRAPH.edges.length, 4);
});

// ---------------------------------------------------------------------
// Inventario de tipos / leyenda
// ---------------------------------------------------------------------

test("tipos de entidad: se agrupan con su recuento y el más frecuente va primero", () => {
  const types = core.collectEntityTypes(GRAPH.nodes);
  assert.strictEqual(types[0].type, "Character");
  assert.strictEqual(types[0].count, 2);
  assert.strictEqual(types.length, 4);
});

test("tipos de relación: se agrupan con su recuento", () => {
  const rels = core.collectRelationTypes(GRAPH.edges);
  const memberOf = rels.filter((r) => r.type === "MEMBER_OF")[0];
  assert.strictEqual(memberOf.count, 2);
  assert.strictEqual(memberOf.label, "miembro de");
});

test("leyenda: cada tipo conocido tiene color y los desconocidos uno por defecto", () => {
  assert.strictEqual(core.colorForType("Character"), core.TYPE_COLORS.Character);
  assert.strictEqual(core.colorForType("TipoQueNoExiste"), core.DEFAULT_COLOR);
  assert.strictEqual(core.colorForType("constructor"), core.DEFAULT_COLOR,
    "no debe filtrarse nada del prototipo de Object");
});

// ---------------------------------------------------------------------
// Contadores y estados
// ---------------------------------------------------------------------

test("contadores: nodos y relaciones visibles", () => {
  const out = core.filterGraph(GRAPH, { entityTypes: ["Character", "Faction"] });
  assert.deepStrictEqual(core.graphStats(out), { nodes: 3, edges: 2 });
});

test("estado: cargando", () => {
  assert.strictEqual(core.viewState(GRAPH, GRAPH, { loading: true }), "loading");
});

test("estado: vacío cuando el backend no devuelve nada", () => {
  const empty = { nodes: [], edges: [] };
  assert.strictEqual(core.viewState(empty, empty, {}), "empty");
});

test("estado: sin resultados cuando hay datos pero los filtros no dejan nada", () => {
  const filtered = core.filterGraph(GRAPH, { query: "no-existe-nada" });
  assert.strictEqual(core.viewState(GRAPH, filtered, {}), "no_results");
});

test("estado: listo cuando hay algo que pintar", () => {
  assert.strictEqual(core.viewState(GRAPH, GRAPH, {}), "ready");
});

test("estado: error manda sobre el resto", () => {
  assert.strictEqual(core.viewState(GRAPH, GRAPH, { error: true }), "error");
});

// HALLAZGO H3. Si el vendor de vis-network no carga (integrity que no cuadra,
// fichero borrado), el servidor está PERFECTAMENTE vivo. Contarlo como fallo
// de red mandaba a la persona a mirar la conexión en vez del despliegue.

test("estado: si falta la biblioteca de dibujo, ese estado manda incluso sobre el error", () => {
  assert.strictEqual(core.viewState(GRAPH, GRAPH, { rendererMissing: true }), "renderer");
  assert.strictEqual(
    core.viewState(GRAPH, GRAPH, { rendererMissing: true, error: true, loading: true }),
    "renderer");
});

test("estado: el mensaje de 'falta el componente' no culpa al servidor ni a la red", () => {
  const msg = core.ERROR_MESSAGES.renderer;
  assert.ok(msg && msg.length > 0, "no hay mensaje para el fallo del vendor");
  assert.notStrictEqual(msg, core.ERROR_MESSAGES.network);
  assert.ok(!/contactar con el servidor/i.test(msg),
    "el fallo del vendor no debe presentarse como 'no se ha podido contactar con el servidor'");
});

// ---------------------------------------------------------------------
// Errores saneados
// ---------------------------------------------------------------------

test("errores: cada status HTTP tiene su familia", () => {
  assert.strictEqual(core.errorKindForStatus(401), "unauthenticated");
  assert.strictEqual(core.errorKindForStatus(403), "forbidden");
  assert.strictEqual(core.errorKindForStatus(404), "not_found");
  assert.strictEqual(core.errorKindForStatus(503), "unavailable");
  assert.strictEqual(core.errorKindForStatus(504), "timeout");
  assert.strictEqual(core.errorKindForStatus(0), "network");
  assert.strictEqual(core.errorKindForStatus(418), "unknown");
});

test("errores: el mensaje al usuario no filtra rutas, trazas ni códigos", () => {
  Object.keys(core.ERROR_MESSAGES).forEach((k) => {
    const msg = core.ERROR_MESSAGES[k];
    assert.ok(msg.length > 0, "mensaje vacío para " + k);
    assert.ok(!/\//.test(msg), "el mensaje '" + msg + "' contiene una barra (posible ruta)");
    assert.ok(!/Traceback|Exception|Error:|neo4j|bolt:/i.test(msg),
      "el mensaje '" + msg + "' filtra detalle técnico");
    assert.ok(!/\b\d{3}\b/.test(msg), "el mensaje '" + msg + "' filtra un código HTTP");
  });
});

test("errores: un status desconocido no revienta ni devuelve vacío", () => {
  assert.strictEqual(typeof core.errorMessageForStatus(999), "string");
  assert.ok(core.errorMessageForStatus(999).length > 0);
});

// ---------------------------------------------------------------------
// Estado reproducible en la URL
// ---------------------------------------------------------------------

test("URL: ida y vuelta del estado", () => {
  const st = {
    q: "Tamori Shiro",
    entityTypes: ["Character", "Faction"],
    relationTypes: ["MEMBER_OF"],
    limit: 300,
    showEdgeLabels: false,
    hideIsolated: true
  };
  const parsed = core.parseState(core.serializeState(st));
  assert.strictEqual(parsed.q, st.q);
  assert.deepStrictEqual(parsed.entityTypes, st.entityTypes);
  assert.deepStrictEqual(parsed.relationTypes, st.relationTypes);
  assert.strictEqual(parsed.limit, 300);
  assert.strictEqual(parsed.showEdgeLabels, false);
  assert.strictEqual(parsed.hideIsolated, true);
});

test("URL: el estado por defecto no ensucia la barra de direcciones", () => {
  assert.strictEqual(core.serializeState({ q: "", entityTypes: null, relationTypes: null }), "");
});

test("URL: sin parámetros de tipo, el estado dice 'sin filtro' (null), no 'nada' ([])", () => {
  const parsed = core.parseState("");
  assert.strictEqual(parsed.entityTypes, null);
  assert.strictEqual(parsed.relationTypes, null);
});

test("URL: 'nada seleccionado' sobrevive a la recarga y no se convierte en 'todo'", () => {
  const qs = core.serializeState({ entityTypes: [], relationTypes: [] });
  assert.ok(qs.indexOf("types=") !== -1, "un filtro vacío tiene que viajar en la URL: " + qs);
  const parsed = core.parseState(qs);
  assert.deepStrictEqual(parsed.entityTypes, []);
  assert.deepStrictEqual(parsed.relationTypes, []);
});

test("URL: los parámetros sensibles o desconocidos se ignoran", () => {
  const parsed = core.parseState(
    "?q=x&character_id=99&view_as=gm&visibility=secret&known_by=abc&scope=partida7&partida_id=7"
  );
  assert.strictEqual(parsed.q, "x");
  const keys = Object.keys(parsed);
  ["character_id", "view_as", "visibility", "known_by", "scope", "partida_id"].forEach((k) => {
    assert.ok(keys.indexOf(k) === -1, "el estado de la URL no debe aceptar '" + k + "'");
  });
});

test("URL: solo hay claves de presentación en la lista blanca", () => {
  assert.deepStrictEqual(core.ALLOWED_STATE_KEYS.slice().sort(),
    ["iso", "labels", "limit", "q", "rels", "types"]);
});

test("URL: un límite no numérico se descarta", () => {
  assert.strictEqual(core.parseState("?limit=abc").limit, null);
});

test("URL: valores con espacios y comas sobreviven al viaje", () => {
  const parsed = core.parseState(core.serializeState({ q: "clan escorpión & cía" }));
  assert.strictEqual(parsed.q, "clan escorpión & cía");
});

// ---------------------------------------------------------------------
// Expandir vecinos
// ---------------------------------------------------------------------

test("vecinos: se listan en ambos sentidos", () => {
  assert.deepStrictEqual(core.neighborIdsOf(GRAPH.edges, "n1").sort(), ["n2", "n3"]);
  assert.deepStrictEqual(core.neighborIdsOf(GRAPH.edges, "n3").sort(), ["n1", "n4"]);
});

test("merge: no duplica nodos ni relaciones ya presentes", () => {
  const merged = core.mergeGraph(GRAPH, {
    nodes: [{ id: "n1", label: "Tamori Shiro" }, { id: "n9", label: "Nuevo" }],
    edges: [{ id: "e1" }, { id: "e9", from: "n1", to: "n9", type: "KNOWS" }]
  });
  assert.strictEqual(merged.nodes.length, 6);
  assert.strictEqual(merged.edges.length, 5);
  assert.strictEqual(merged.nodes.filter((n) => n.id === "n1").length, 1);
});

test("merge: descarta elementos sin id en vez de romperse", () => {
  const merged = core.mergeGraph(GRAPH, { nodes: [{ label: "sin id" }, null], edges: [] });
  assert.strictEqual(merged.nodes.length, 5);
});

// ---------------------------------------------------------------------
console.log("");
console.log(passed + " pasados, " + failures.length + " fallidos");
if (failures.length) {
  console.error("FALLOS:\n  " + failures.join("\n  "));
  process.exit(1);
}
