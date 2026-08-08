/**
 * Especificación de graph-core.js (lógica pura del visor de grafo).
 *
 * Se ejecuta con `node graph_core_spec.js`. Imprime una línea por caso y
 * termina con código 1 si falla alguno: el test de pytest que lo invoca
 * (test_graph_core_js.py) se pone rojo con ese código de salida.
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

test("búsqueda: coincidencia exacta va antes que la parcial", () => {
  const nodes = [
    { id: "a", label: "Kuni Yori el Viejo", type: "Character" },
    { id: "b", label: "Kuni", type: "Character" }
  ];
  const res = core.searchNodes(nodes, "Kuni");
  assert.strictEqual(res[0].id, "b", "la coincidencia exacta debe ir primero");
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
  assert.strictEqual(core.serializeState({ q: "", entityTypes: [], relationTypes: [] }), "");
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
