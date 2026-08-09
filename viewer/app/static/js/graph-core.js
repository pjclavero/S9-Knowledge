/**
 * graph-core.js — lógica pura del visor de grafo (sin DOM, sin red).
 *
 * Se carga como script clásico en el navegador (expone `window.S9KGraphCore`)
 * y también se puede requerir desde Node para los tests (`module.exports`).
 *
 * Aquí NO se decide qué puede ver un usuario: la visibilidad y la
 * autorización las resuelve el backend antes de servir el JSON. Este módulo
 * solo filtra y ordena lo que el backend ya ha entregado.
 */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.S9KGraphCore = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  // ---------------------------------------------------------------------
  // Colores por tipo de entidad (también usados por la leyenda)
  // ---------------------------------------------------------------------
  var TYPE_COLORS = {
    Character: "#6ea8fe",
    NonHuman: "#6ea8fe",
    Creature: "#e5534b",
    Spirit: "#a371f7",
    Demon: "#a371f7",
    Beast: "#e5534b",
    Location: "#3fb950",
    Region: "#3fb950",
    Faction: "#f5a623",
    Clan: "#f5a623",
    Family: "#f5a623",
    School: "#f5a623",
    Group: "#f5a623",
    Object: "#d29922",
    Artifact: "#d29922",
    Event: "#58a6ff",
    Encounter: "#58a6ff",
    Combat: "#e5534b",
    Session: "#8b949e",
    Document: "#8b949e",
    Chapter: "#8b949e",
    Transcript: "#8b949e",
    Image: "#8b949e",
    Concept: "#bc8cff",
    Task: "#79c0ff",
    Rule: "#79c0ff",
    Spell: "#bc8cff"
  };

  var DEFAULT_COLOR = "#9aa0ae";

  function colorForType(type) {
    return Object.prototype.hasOwnProperty.call(TYPE_COLORS, type)
      ? TYPE_COLORS[type]
      : DEFAULT_COLOR;
  }

  // ---------------------------------------------------------------------
  // Texto
  // ---------------------------------------------------------------------

  /** Minúsculas y sin tildes, para que "Ryoko" case con "Ryōko" y "Sion" con "Sión". */
  function normalizeText(value) {
    if (value === null || value === undefined) return "";
    var s = String(value).toLowerCase();
    if (typeof s.normalize === "function") {
      s = s.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
    }
    return s.trim();
  }

  /**
   * Texto sobre el que busca el visor: nombre · alias · tipo · resumen ·
   * IDENTIFICADOR ESTABLE DE DOMINIO (`entity_id`).
   *
   * Sobre el identificador, tres reglas que no son cosmética:
   *
   *  1. Se indexa `entity_id` y NADA MÁS. `node.id` NO entra: en el proveedor
   *     Neo4j ese campo es el `elementId`, que no es identidad durable —se
   *     regenera al restaurar un dump—, y hacerlo buscable convertiría un
   *     detalle del almacén en una clave de búsqueda del producto.
   *  2. Solo se indexa lo que el BACKEND HA ENTREGADO en este nodo. Este
   *     módulo no compone, deriva ni adivina identificadores.
   *  3. Por lo tanto, y esto es el resultado que se congela: solo se puede
   *     encontrar por ID aquello que la vista autorizada ya contiene. Un
   *     `entity_id` que la política no entregó no está en ningún índice, así
   *     que buscarlo es indistinguible de buscar un id inventado.
   */
  function nodeHaystack(node) {
    if (!node) return "";
    var parts = [node.label, node.type_label, node.type, node.short_summary, node.entity_id];
    var aliases = node.aliases || [];
    for (var i = 0; i < aliases.length; i++) parts.push(aliases[i]);
    return normalizeText(parts.filter(Boolean).join("   "));
  }

  /** ¿El nodo casa con el texto buscado? Query vacía = casa con todo. */
  function matchesQuery(node, query) {
    var q = normalizeText(query);
    if (!q) return true;
    return nodeHaystack(node).indexOf(q) !== -1;
  }

  /**
   * Busca nodos y los devuelve ordenados por calidad de coincidencia:
   * exacta > empieza por > contiene; a igualdad, alfabético.
   */
  function searchNodes(nodes, query, options) {
    var opts = options || {};
    var q = normalizeText(query);
    if (!q) return [];
    var scored = [];
    (nodes || []).forEach(function (n) {
      var label = normalizeText(n.label);
      var score;
      if (label === q) score = 0;
      else if (label.indexOf(q) === 0) score = 1;
      else if (label.indexOf(q) !== -1) score = 2;
      else if (nodeHaystack(n).indexOf(q) !== -1) score = 3;
      else return;
      scored.push({ node: n, score: score, label: label });
    });
    scored.sort(function (a, b) {
      if (a.score !== b.score) return a.score - b.score;
      return a.label < b.label ? -1 : a.label > b.label ? 1 : 0;
    });
    var out = scored.map(function (s) { return s.node; });
    if (opts.limit && out.length > opts.limit) out = out.slice(0, opts.limit);
    return out;
  }

  // ---------------------------------------------------------------------
  // Inventario de tipos (para filtros y leyenda)
  // ---------------------------------------------------------------------

  function tally(items, keyFn, labelFn) {
    var map = Object.create(null);
    (items || []).forEach(function (item) {
      var key = keyFn(item) || "";
      if (!key) return;
      if (!map[key]) map[key] = { type: key, label: labelFn(item) || key, count: 0 };
      map[key].count += 1;
    });
    return Object.keys(map)
      .map(function (k) { return map[k]; })
      .sort(function (a, b) {
        if (b.count !== a.count) return b.count - a.count;
        return a.type < b.type ? -1 : a.type > b.type ? 1 : 0;
      });
  }

  function collectEntityTypes(nodes) {
    return tally(nodes, function (n) { return n.type; }, function (n) { return n.type_label || n.type; });
  }

  function collectRelationTypes(edges) {
    return tally(edges, function (e) { return e.type; }, function (e) { return e.label || e.type; });
  }

  // ---------------------------------------------------------------------
  // Filtrado
  // ---------------------------------------------------------------------

  /**
   * Convierte una selección de filtro en un conjunto.
   *
   * Se distinguen TRES casos, y la diferencia entre los dos últimos es la que
   * arregla el defecto de «todas marcadas y todas desmarcadas dan lo mismo»:
   *
   *   - `null` / `undefined` → no hay filtro: pasa todo.
   *   - array vacío `[]`     → el usuario ha desmarcado TODAS las casillas:
   *                            no pasa nada. Antes esto se trataba como «no
   *                            filtrar», así que desmarcarlo todo mostraba el
   *                            grafo entero.
   *   - array con elementos  → pasa solo lo listado.
   */
  function toSet(values) {
    if (values === null || values === undefined) return null;
    var arr = Array.isArray(values) ? values : Array.from(values);
    var set = Object.create(null);
    arr.forEach(function (v) { set[String(v)] = true; });
    return set;
  }

  function inSet(set, value) {
    return set === null || Object.prototype.hasOwnProperty.call(set, String(value));
  }

  /**
   * Aplica los filtros de la UI sobre el grafo ya recibido del backend.
   *
   * - `entityTypes` / `relationTypes`: `null` = "no filtrar"; lista vacía =
   *   "nada seleccionado", que no deja pasar nada (ver `toSet`).
   * - `query`: filtra nodos por texto (además de servir para localizar).
   * - Una relación sobrevive solo si su tipo pasa el filtro Y sus dos
   *   extremos siguen presentes: nunca se dibujan aristas colgando.
   * - `hideIsolated`: descarta nodos que se quedan sin ninguna relación.
   */
  function filterGraph(graph, filters) {
    var g = graph || {};
    var f = filters || {};
    var typeSet = toSet(f.entityTypes);
    var relSet = toSet(f.relationTypes);
    var query = f.query || "";

    var nodes = (g.nodes || []).filter(function (n) {
      return inSet(typeSet, n.type) && matchesQuery(n, query);
    });

    var present = Object.create(null);
    nodes.forEach(function (n) { present[String(n.id)] = true; });

    var edges = (g.edges || []).filter(function (e) {
      if (!inSet(relSet, e.type)) return false;
      return Object.prototype.hasOwnProperty.call(present, String(e.from)) &&
             Object.prototype.hasOwnProperty.call(present, String(e.to));
    });

    if (f.hideIsolated) {
      var connected = Object.create(null);
      edges.forEach(function (e) {
        connected[String(e.from)] = true;
        connected[String(e.to)] = true;
      });
      nodes = nodes.filter(function (n) {
        return Object.prototype.hasOwnProperty.call(connected, String(n.id));
      });
    }

    return { nodes: nodes, edges: edges };
  }

  function graphStats(graph) {
    var g = graph || {};
    return { nodes: (g.nodes || []).length, edges: (g.edges || []).length };
  }

  function neighborIdsOf(edges, nodeId) {
    var id = String(nodeId);
    var seen = Object.create(null);
    (edges || []).forEach(function (e) {
      if (String(e.from) === id) seen[String(e.to)] = true;
      else if (String(e.to) === id) seen[String(e.from)] = true;
    });
    return Object.keys(seen);
  }

  /** Une un subgrafo (p.ej. los vecinos expandidos) sin duplicar ids. */
  function mergeGraph(base, incoming) {
    var b = base || {};
    var i = incoming || {};
    function dedupe(a, c) {
      var out = [];
      var seen = Object.create(null);
      (a || []).concat(c || []).forEach(function (item) {
        if (!item || item.id === undefined || item.id === null) return;
        var key = String(item.id);
        if (seen[key]) return;
        seen[key] = true;
        out.push(item);
      });
      return out;
    }
    return { nodes: dedupe(b.nodes, i.nodes), edges: dedupe(b.edges, i.edges) };
  }

  // ---------------------------------------------------------------------
  // Estado reproducible en la URL
  //
  // Solo viajan parámetros de presentación (texto buscado, tipos, límite,
  // etiquetas). Nada de identidad, personaje, visibilidad ni permisos: eso
  // lo decide el servidor y no debe poder "pedirse" desde la barra del
  // navegador.
  // ---------------------------------------------------------------------

  var ALLOWED_STATE_KEYS = ["q", "types", "rels", "limit", "labels", "iso"];

  function parseState(search) {
    var raw = String(search || "");
    if (raw.charAt(0) === "?") raw = raw.slice(1);
    // `null` en los tipos = el parámetro no venía en la URL, o sea «sin
    // filtro». Un `types=` vacío SÍ viaja y significa «nada seleccionado».
    var state = { q: "", entityTypes: null, relationTypes: null, limit: null, showEdgeLabels: true, hideIsolated: false };
    if (!raw) return state;
    raw.split("&").forEach(function (chunk) {
      if (!chunk) return;
      var eq = chunk.indexOf("=");
      var key = decodeURIComponent((eq === -1 ? chunk : chunk.slice(0, eq)).replace(/\+/g, " "));
      var value = eq === -1 ? "" : decodeURIComponent(chunk.slice(eq + 1).replace(/\+/g, " "));
      if (ALLOWED_STATE_KEYS.indexOf(key) === -1) return; // se ignora lo desconocido
      if (key === "q") state.q = value;
      else if (key === "types") state.entityTypes = value ? value.split(",").filter(Boolean) : [];
      else if (key === "rels") state.relationTypes = value ? value.split(",").filter(Boolean) : [];
      else if (key === "limit") {
        var n = parseInt(value, 10);
        state.limit = isNaN(n) ? null : n;
      } else if (key === "labels") state.showEdgeLabels = value !== "0";
      else if (key === "iso") state.hideIsolated = value === "1";
    });
    return state;
  }

  function serializeState(state) {
    var s = state || {};
    var parts = [];
    if (s.q) parts.push("q=" + encodeURIComponent(s.q));
    // `null` no viaja (no hay filtro); `[]` viaja vacío para que al recargar
    // se recupere «nada seleccionado» y no «todo».
    if (s.entityTypes) parts.push("types=" + encodeURIComponent(s.entityTypes.join(",")));
    if (s.relationTypes) parts.push("rels=" + encodeURIComponent(s.relationTypes.join(",")));
    if (s.limit) parts.push("limit=" + encodeURIComponent(String(s.limit)));
    if (s.showEdgeLabels === false) parts.push("labels=0");
    if (s.hideIsolated) parts.push("iso=1");
    return parts.length ? "?" + parts.join("&") : "";
  }

  // ---------------------------------------------------------------------
  // Estados y mensajes de error saneados
  //
  // El usuario nunca ve rutas internas, trazas ni identificadores que la
  // política haya podido ocultar: solo un mensaje por familia de estado.
  // ---------------------------------------------------------------------

  var ERROR_MESSAGES = {
    unauthenticated: "Tu sesión ha caducado. Vuelve a iniciar sesión para ver el grafo.",
    forbidden: "No tienes acceso a este contenido.",
    not_found: "No se ha encontrado lo solicitado.",
    unavailable: "La fuente de datos no está disponible ahora mismo. Inténtalo de nuevo en unos minutos.",
    timeout: "La consulta ha tardado demasiado. Prueba a reducir el límite de nodos.",
    network: "No se ha podido contactar con el servidor.",
    unknown: "No se ha podido cargar el grafo.",
    // El servidor está VIVO y los datos pueden llegar perfectamente: lo que
    // falta es la biblioteca de dibujo (vendor bloqueado por `integrity`,
    // fichero corrupto o borrado). Decir "no se ha podido contactar con el
    // servidor" en ese caso manda a la persona a mirar donde no es.
    renderer: "El componente que dibuja el grafo no se ha cargado. Recarga la página; si vuelve a ocurrir, avisa a quien administre el visor."
  };

  function errorKindForStatus(status) {
    var code = Number(status);
    if (code === 401) return "unauthenticated";
    if (code === 403) return "forbidden";
    if (code === 404) return "not_found";
    if (code === 504) return "timeout";
    if (code === 503 || code === 502) return "unavailable";
    if (code === 0 || isNaN(code)) return "network";
    return "unknown";
  }

  /** Mensaje presentable a partir de un status HTTP. Nunca filtra detalles. */
  function errorMessageForStatus(status) {
    return ERROR_MESSAGES[errorKindForStatus(status)];
  }

  /**
   * Estado de la vista para pintar el mensaje adecuado.
   * "empty" = el workspace no ha devuelto nada; "no_results" = hay datos pero
   * los filtros/búsqueda no dejan nada visible.
   */
  function viewState(loaded, filtered, options) {
    var opts = options || {};
    // Sin biblioteca de dibujo no hay nada que enseñar aunque los datos
    // lleguen: es el estado más fuerte y va primero.
    if (opts.rendererMissing) return "renderer";
    if (opts.loading) return "loading";
    if (opts.error) return "error";
    var total = graphStats(loaded);
    var shown = graphStats(filtered);
    if (total.nodes === 0) return "empty";
    if (shown.nodes === 0) return "no_results";
    return "ready";
  }

  return {
    TYPE_COLORS: TYPE_COLORS,
    DEFAULT_COLOR: DEFAULT_COLOR,
    ERROR_MESSAGES: ERROR_MESSAGES,
    ALLOWED_STATE_KEYS: ALLOWED_STATE_KEYS,
    colorForType: colorForType,
    normalizeText: normalizeText,
    matchesQuery: matchesQuery,
    searchNodes: searchNodes,
    collectEntityTypes: collectEntityTypes,
    collectRelationTypes: collectRelationTypes,
    filterGraph: filterGraph,
    graphStats: graphStats,
    neighborIdsOf: neighborIdsOf,
    mergeGraph: mergeGraph,
    parseState: parseState,
    serializeState: serializeState,
    errorKindForStatus: errorKindForStatus,
    errorMessageForStatus: errorMessageForStatus,
    viewState: viewState
  };
});
