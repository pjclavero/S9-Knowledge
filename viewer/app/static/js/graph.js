/**
 * graph.js — capa de interfaz del visor de grafo (DOM + vis-network).
 *
 * Toda la lógica pura (búsqueda, filtros, estado de URL, mensajes) vive en
 * graph-core.js y se prueba por separado. Aquí solo hay pegamento: eventos,
 * pintado y llamadas a la API.
 *
 * Este fichero no toma decisiones de autorización: pinta exactamente lo que
 * la API devuelve, que ya viene filtrado por el backend.
 */
(function () {
  "use strict";

  var core = window.S9KGraphCore;

  var workspace = window.S9K_WORKSPACE || "leyenda";
  var defaultLimit = window.S9K_GRAPH_LIMIT || 300;

  // --- Referencias al DOM -------------------------------------------------
  var $ = function (id) { return document.getElementById(id); };

  var canvas = $("graph-canvas");
  var statusBox = $("graph-status");
  var counterNodes = $("counter-nodes");
  var counterEdges = $("counter-edges");
  var searchInput = $("search-input");
  var searchResults = $("search-results");
  var limitSelect = $("limit-select");
  var reloadBtn = $("reload-btn");
  var fitBtn = $("fit-btn");
  var resetBtn = $("reset-btn");
  var labelsToggle = $("labels-toggle");
  var isolatedToggle = $("isolated-toggle");
  var entityTypeList = $("entity-type-filters");
  var relationTypeList = $("relation-type-filters");
  var legendList = $("graph-legend");
  var filtersPanel = $("filters-panel");
  var filtersToggle = $("filters-toggle");
  var clearFiltersBtn = $("clear-filters-btn");
  var detailPanel = $("side-panel");
  var detailClose = $("side-panel-close");
  var detailBody = $("side-panel-body");

  // --- Estado -------------------------------------------------------------
  var loaded = { nodes: [], edges: [] };   // lo último recibido de la API
  var visible = { nodes: [], edges: [] };  // tras aplicar filtros
  var state = core.parseState(window.location.search);
  var network = null;
  var visNodes = null;
  var visEdges = null;
  var loading = false;
  var lastErrorStatus = null;
  var selectedId = null;
  // ¿Ha terminado vis-network de estabilizar el layout físico? Mientras sea
  // `false` el lienzo se está moviendo solo y comparar dos capturas no
  // significa nada.
  var stabilized = false;
  // vis-network se sirve vendorizado con `integrity`. Si el navegador bloquea
  // el fichero (hash que no cuadra) o el fichero no está, `vis` no existe. Eso
  // NO es un fallo de red ni del servidor y no debe contarse como tal.
  var rendererMissing = (typeof vis === "undefined") || !vis || typeof vis.Network !== "function";

  if (!state.limit) state.limit = defaultLimit;

  // ---------------------------------------------------------------------
  // Utilidades de pintado
  // ---------------------------------------------------------------------

  function esc(s) {
    return String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function fieldRow(label, value) {
    var v = (value !== null && value !== undefined && value !== "") ? esc(value) : "—";
    return '<div class="field"><div class="field-label">' + esc(label) + "</div>" +
           '<div class="field-value">' + v + "</div></div>";
  }

  function isNarrow() {
    return window.innerWidth <= 900;
  }

  // ---------------------------------------------------------------------
  // URL reproducible
  // ---------------------------------------------------------------------

  function syncUrl() {
    var qs = core.serializeState({
      q: state.q,
      entityTypes: state.entityTypes,
      relationTypes: state.relationTypes,
      limit: state.limit,
      showEdgeLabels: state.showEdgeLabels,
      hideIsolated: state.hideIsolated
    });
    var url = window.location.pathname + qs;
    try {
      window.history.replaceState(null, "", url);
    } catch (e) {
      /* navegador sin history API: la URL simplemente no se actualiza */
    }
  }

  // ---------------------------------------------------------------------
  // Estados de la vista
  // ---------------------------------------------------------------------

  var STATE_TEXT = {
    loading: "Cargando el grafo…",
    empty: "Este workspace no tiene contenido visible todavía.",
    no_results: "Ningún elemento cumple los filtros o la búsqueda actual.",
    ready: ""
  };

  function renderStatus() {
    var kind = core.viewState(loaded, visible, {
      loading: loading,
      error: lastErrorStatus !== null,
      rendererMissing: rendererMissing
    });
    var text;
    if (kind === "error") {
      text = core.errorMessageForStatus(lastErrorStatus);
    } else if (kind === "renderer") {
      text = core.ERROR_MESSAGES.renderer;
    } else {
      text = STATE_TEXT[kind] || "";
    }
    statusBox.className = "graph-status graph-status-" + kind;
    if (!text) {
      statusBox.hidden = true;
      statusBox.textContent = "";
    } else {
      statusBox.hidden = false;
      statusBox.textContent = text;
    }
    if (kind === "error" || kind === "renderer" || kind === "no_results" || kind === "empty") {
      statusBox.setAttribute("role", "status");
    }
  }

  function renderCounters() {
    var shown = core.graphStats(visible);
    var total = core.graphStats(loaded);
    counterNodes.textContent = shown.nodes === total.nodes
      ? String(shown.nodes)
      : shown.nodes + " / " + total.nodes;
    counterEdges.textContent = shown.edges === total.edges
      ? String(shown.edges)
      : shown.edges + " / " + total.edges;
  }

  // ---------------------------------------------------------------------
  // Filtros y leyenda
  // ---------------------------------------------------------------------

  function renderCheckboxList(container, items, selected, groupName, withColor) {
    container.innerHTML = "";
    if (!items.length) {
      var p = document.createElement("p");
      p.className = "empty-hint";
      p.textContent = "Sin tipos que mostrar.";
      container.appendChild(p);
      return;
    }
    items.forEach(function (item) {
      var id = groupName + "-" + item.type.replace(/[^A-Za-z0-9_-]/g, "_");
      var row = document.createElement("label");
      row.className = "filter-row";
      row.setAttribute("for", id);

      var cb = document.createElement("input");
      cb.type = "checkbox";
      cb.id = id;
      cb.value = item.type;
      // `selected === null` = no hay filtro: todas las casillas marcadas.
      cb.checked = selected === null ? true : selected.indexOf(item.type) !== -1;
      cb.setAttribute("data-filter-group", groupName);
      cb.addEventListener("change", onFilterChange);
      row.appendChild(cb);

      if (withColor) {
        var swatch = document.createElement("span");
        swatch.className = "legend-swatch";
        swatch.style.background = core.colorForType(item.type);
        swatch.setAttribute("aria-hidden", "true");
        row.appendChild(swatch);
      }

      var text = document.createElement("span");
      text.className = "filter-label";
      text.textContent = item.label;
      row.appendChild(text);

      var count = document.createElement("span");
      count.className = "filter-count";
      count.textContent = String(item.count);
      row.appendChild(count);

      container.appendChild(row);
    });
  }

  function renderLegend(entityTypes) {
    legendList.innerHTML = "";
    entityTypes.forEach(function (item) {
      var li = document.createElement("li");
      var swatch = document.createElement("span");
      swatch.className = "legend-swatch";
      swatch.style.background = core.colorForType(item.type);
      swatch.setAttribute("aria-hidden", "true");
      li.appendChild(swatch);
      var span = document.createElement("span");
      span.textContent = item.label;
      li.appendChild(span);
      legendList.appendChild(li);
    });
    if (!entityTypes.length) {
      var li2 = document.createElement("li");
      li2.className = "empty-hint";
      li2.textContent = "—";
      legendList.appendChild(li2);
    }
  }

  /**
   * Lectura de las casillas de un grupo.
   *
   * Devuelve `null` cuando están TODAS marcadas ("no hay filtro", y la URL
   * queda limpia) y un array —posiblemente vacío— en cualquier otro caso.
   * Todas desmarcadas ya no equivale a todas marcadas: da lista vacía, y una
   * lista vacía no deja pasar nada.
   */
  function collectSelected(groupName) {
    var out = [];
    var total = 0;
    var boxes = document.querySelectorAll('input[data-filter-group="' + groupName + '"]');
    Array.prototype.forEach.call(boxes, function (b) {
      total += 1;
      if (b.checked) out.push(b.value);
    });
    if (total > 0 && out.length === total) return null;
    return out;
  }

  function onFilterChange() {
    state.entityTypes = collectSelected("etype");
    state.relationTypes = collectSelected("rtype");
    applyFilters();
    syncUrl();
  }

  function rebuildFilterUi() {
    var entityTypes = core.collectEntityTypes(loaded.nodes);
    var relationTypes = core.collectRelationTypes(loaded.edges);
    // Un filtro guardado en la URL cuyo tipo ya no existe se descarta.
    // `null` (sin filtro) se deja tal cual: no hay nada que depurar.
    var known = entityTypes.map(function (t) { return t.type; });
    if (state.entityTypes) {
      state.entityTypes = state.entityTypes.filter(function (t) { return known.indexOf(t) !== -1; });
    }
    var knownRel = relationTypes.map(function (t) { return t.type; });
    if (state.relationTypes) {
      state.relationTypes = state.relationTypes.filter(function (t) { return knownRel.indexOf(t) !== -1; });
    }

    renderCheckboxList(entityTypeList, entityTypes, state.entityTypes, "etype", true);
    renderCheckboxList(relationTypeList, relationTypes, state.relationTypes, "rtype", false);
    renderLegend(entityTypes);
  }

  // ---------------------------------------------------------------------
  // Render del grafo
  // ---------------------------------------------------------------------

  function toVisNode(n) {
    return {
      id: n.id,
      label: n.label,
      title: n.type_label,
      // El color de resalte repite el del tipo a propósito: si al seleccionar
      // un nodo cambiase de color, dejaría de casar con la leyenda justo en el
      // momento en que la persona lo está mirando.
      color: {
        background: core.colorForType(n.type),
        border: "#0b0d12",
        highlight: { background: core.colorForType(n.type), border: "#e6e8ee" }
      },
      font: { color: "#e6e8ee" },
      shape: "dot",
      size: 14
    };
  }

  function toVisEdge(e) {
    return {
      id: e.id,
      from: e.from,
      to: e.to,
      label: state.showEdgeLabels ? (e.label || e.type) : "",
      arrows: "to",
      font: { color: "#9aa0ae", size: 10, strokeWidth: 0 },
      color: { color: "#444b5c", highlight: "#6ea8fe" }
    };
  }

  function drawGraph() {
    // Sin biblioteca de dibujo el resto de la página (filtros, contadores,
    // buscador, mensaje de estado) tiene que seguir funcionando en vez de
    // morir con un ReferenceError en la primera línea.
    if (rendererMissing) return;
    visNodes = new vis.DataSet(visible.nodes.map(toVisNode));
    visEdges = new vis.DataSet(visible.edges.map(toVisEdge));

    if (network) {
      stabilized = false;
      network.setData({ nodes: visNodes, edges: visEdges });
      return;
    }

    stabilized = false;
    network = new vis.Network(
      canvas,
      { nodes: visNodes, edges: visEdges },
      {
        physics: { stabilization: true, barnesHut: { gravitationalConstant: -4000 } },
        interaction: { hover: true, keyboard: { enabled: true, bindToWindow: false }, navigationButtons: false }
      }
    );

    // `stabilized` lo emite vis-network cuando el motor de físicas deja de
    // mover los nodos. Deliberadamente NO se escucha `startStabilizing` para
    // volver a poner la bandera en `false`: ese evento también se emite cuando
    // el motor se reactiva por su cuenta, y en esos casos no siempre llega un
    // `stabilized` de vuelta, con lo que la bandera se quedaría en `false`
    // para siempre. Lo único que rehace el layout de verdad es cargar datos
    // nuevos, y de eso se ocupa `drawGraph`.
    network.on("stabilized", function () { stabilized = true; });
    network.on("stabilizationIterationsDone", function () { stabilized = true; });

    network.on("click", function (params) {
      if (params.nodes.length > 0) {
        selectNode(params.nodes[0]);
      } else if (params.edges.length > 0) {
        var edge = findEdge(params.edges[0]);
        if (edge) renderEdgePanel(edge);
      } else {
        clearDetail();
      }
    });

    network.on("doubleClick", function (params) {
      if (params.nodes.length > 0) expandNeighbors(params.nodes[0]);
    });
  }

  function findNode(id) {
    for (var i = 0; i < loaded.nodes.length; i++) {
      if (String(loaded.nodes[i].id) === String(id)) return loaded.nodes[i];
    }
    return null;
  }

  function findEdge(id) {
    for (var i = 0; i < loaded.edges.length; i++) {
      if (String(loaded.edges[i].id) === String(id)) return loaded.edges[i];
    }
    return null;
  }

  function applyFilters() {
    visible = core.filterGraph(loaded, {
      entityTypes: state.entityTypes,
      relationTypes: state.relationTypes,
      hideIsolated: state.hideIsolated
    });
    drawGraph();
    renderCounters();
    renderStatus();
  }

  // ---------------------------------------------------------------------
  // Ficha lateral
  // ---------------------------------------------------------------------

  function openDetail() {
    detailPanel.classList.remove("side-panel-closed");
    detailPanel.setAttribute("aria-hidden", "false");
  }

  function clearDetail() {
    selectedId = null;
    detailBody.innerHTML = '<p class="empty-hint">Pincha un nodo o una relación para ver su ficha. ' +
      "Doble clic sobre un nodo para traer sus vecinos.</p>";
    if (isNarrow()) {
      detailPanel.classList.add("side-panel-closed");
      detailPanel.setAttribute("aria-hidden", "true");
    }
  }

  function setDetail(html) {
    detailBody.innerHTML = html;
    openDetail();
  }

  function selectNode(id) {
    var node = findNode(id);
    if (!node) return;
    selectedId = String(node.id);
    renderNodePanel(node);
    if (network) {
      network.selectNodes([node.id]);
    }
  }

  function renderNodePanel(node) {
    setDetail(
      "<h2>" + esc(node.label) + "</h2>" +
      '<p><span class="pill">' + esc(node.type_label) + "</span>" +
      (node.confidence_label ? ' <span class="pill">Confianza: ' + esc(node.confidence_label) + "</span>" : "") +
      "</p>" +
      fieldRow("Descripción", node.description) +
      fieldRow("Alias", (node.aliases || []).join(", ")) +
      fieldRow("Fuente", node.source_document) +
      fieldRow("Páginas", (node.source_pages || []).join(", ")) +
      fieldRow("Estado de revisión", node.review_status_label) +
      '<div class="panel-actions">' +
      '<button type="button" class="btn" id="center-node-btn">Centrar</button> ' +
      '<button type="button" class="btn" id="expand-node-btn">Expandir vecinos</button> ' +
      '<a class="btn" href="/entities/' + encodeURIComponent(node.id) + '">Ficha completa</a>' +
      "</div>" +
      '<p class="panel-note" id="expand-note" hidden></p>'
    );
    var centerBtn = $("center-node-btn");
    if (centerBtn) centerBtn.addEventListener("click", function () { focusNode(node.id); });
    var expandBtn = $("expand-node-btn");
    if (expandBtn) expandBtn.addEventListener("click", function () { expandNeighbors(node.id); });
  }

  function renderEdgePanel(edge) {
    var fromNode = findNode(edge.from);
    var toNode = findNode(edge.to);
    setDetail(
      "<h2>Relación</h2>" +
      "<p>" + (fromNode ? esc(fromNode.label) : "?") + " → <strong>" +
      esc(edge.label || edge.type) + "</strong> → " + (toNode ? esc(toNode.label) : "?") + "</p>" +
      (edge.confidence_label ? '<p><span class="pill">Confianza: ' + esc(edge.confidence_label) + "</span></p>" : "") +
      fieldRow("Descripción / evidencia", edge.description) +
      fieldRow("Fuente", edge.source_document) +
      fieldRow("Páginas", (edge.source_pages || []).join(", ")) +
      fieldRow("Estado de revisión", edge.review_status_label)
    );
  }

  // ---------------------------------------------------------------------
  // Navegación del lienzo
  // ---------------------------------------------------------------------

  function focusNode(id) {
    if (!network) return;
    try {
      network.focus(id, { scale: 1.4, animation: { duration: 400, easingFunction: "easeInOutQuad" } });
      network.selectNodes([id]);
    } catch (e) {
      /* el nodo puede haber quedado fuera por un filtro: no es un error */
    }
  }

  function fitView() {
    if (network) network.fit({ animation: { duration: 300, easingFunction: "easeInOutQuad" } });
  }

  /**
   * Deja los filtros como recién llegado: tipos sin filtrar, sin búsqueda y
   * sin "ocultar sueltos". Lo comparten el botón "Quitar filtros" y
   * "Reiniciar vista" (que además reencuadra el lienzo): antes cada uno
   * limpiaba un subconjunto distinto y "Quitar filtros" se dejaba fuera la
   * búsqueda y la casilla de nodos sueltos.
   */
  function clearAllFilters() {
    state.q = "";
    state.entityTypes = null;
    state.relationTypes = null;
    state.hideIsolated = false;
    if (searchInput) searchInput.value = "";
    if (isolatedToggle) isolatedToggle.checked = false;
    renderSearchResults([]);
    rebuildFilterUi();
    applyFilters();
    syncUrl();
  }

  function resetView() {
    state.showEdgeLabels = true;
    if (labelsToggle) labelsToggle.checked = true;
    clearAllFilters();
    // "Volver a la vista inicial" incluye la selección: dejar la ficha de un
    // nodo abierta después de reiniciar es un resto del estado anterior.
    // ("Quitar filtros" sí la respeta: quitar un filtro no es deseleccionar.)
    clearDetail();
    fitView();
  }

  // ---------------------------------------------------------------------
  // Búsqueda: localizar + centrar + resaltar
  // ---------------------------------------------------------------------

  function renderSearchResults(matches) {
    searchResults.innerHTML = "";
    if (!state.q) {
      searchResults.hidden = true;
      return;
    }
    searchResults.hidden = false;
    if (!matches.length) {
      var li = document.createElement("li");
      li.className = "empty-hint";
      li.textContent = "Sin coincidencias.";
      searchResults.appendChild(li);
      return;
    }
    matches.forEach(function (n) {
      var li = document.createElement("li");
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "search-result";
      btn.textContent = n.label + " · " + (n.type_label || n.type || "");
      btn.addEventListener("click", function () {
        selectNode(n.id);
        focusNode(n.id);
      });
      li.appendChild(btn);
      searchResults.appendChild(li);
    });
  }

  /**
   * Cierra el desplegable de resultados SIN tocar `state.q`.
   *
   * Cerrar la lista no es «cancelar la búsqueda»: el término sigue escrito, en
   * la URL y en el campo. Por eso no se pasa por `renderSearchResults([])`,
   * que con `state.q` puesto volvería a mostrarla con «Sin coincidencias».
   */
  function closeSearchResults() {
    searchResults.innerHTML = "";
    searchResults.hidden = true;
  }

  function runSearch() {
    state.q = searchInput.value.trim();
    var matches = core.searchNodes(visible.nodes, state.q, { limit: 12 });
    renderSearchResults(matches);
    if (matches.length) {
      selectNode(matches[0].id);
      focusNode(matches[0].id);
      // Ya se ha elegido: mantener abierto un menú de elección después de
      // elegir por la persona tapa el grafo (la lista es absoluta y va por
      // encima del lienzo) y le roba los clics siguientes. Al teclear de
      // nuevo, el manejador `input` vuelve a abrirla.
      closeSearchResults();
    }
    syncUrl();
  }

  // ---------------------------------------------------------------------
  // Carga de datos
  // ---------------------------------------------------------------------

  function apiUrl() {
    var params = new URLSearchParams();
    params.set("workspace", workspace);
    params.set("limit", String(state.limit || defaultLimit));
    return "/api/graph?" + params.toString();
  }

  function loadGraph() {
    loading = true;
    lastErrorStatus = null;
    renderStatus();

    return fetch(apiUrl(), { headers: { accept: "application/json" } })
      .then(function (res) {
        if (!res.ok) {
          lastErrorStatus = res.status;
          loaded = { nodes: [], edges: [] };
          visible = { nodes: [], edges: [] };
          throw new Error("http");
        }
        return res.json();
      })
      .then(function (data) {
        loaded = { nodes: data.nodes || [], edges: data.edges || [] };
        loading = false;
        rebuildFilterUi();
        applyFilters();
        if (state.q) {
          searchInput.value = state.q;
          runSearch();
        }
      })
      .catch(function () {
        loading = false;
        if (lastErrorStatus === null) lastErrorStatus = 0; // fallo de red
        drawGraph();
        renderCounters();
        renderStatus();
      });
  }

  /**
   * Trae los vecinos de un nodo desde /api/entities/{id} y los añade al grafo.
   *
   * REGLA: la interfaz no decide qué está autorizado y TAMPOCO informa de lo
   * que falta. Pide los vecinos de X y pinta exactamente lo que el backend
   * devuelve. No hay contador de "N de M", ni hueco, ni diferencia visible
   * entre "no tiene más vecinos" y "los tiene pero no te tocan": un número
   * ahí revelaría la existencia de lo que la política acaba de ocultar.
   * Por eso el mensaje de éxito es siempre el mismo, con datos nuevos o sin
   * ellos.
   */
  var EXPAND_DONE = "Se muestran los elementos disponibles para tu vista.";
  function expandNeighbors(nodeId) {
    var note = $("expand-note");
    function say(msg) {
      if (note) { note.hidden = false; note.textContent = msg; }
    }
    say("Buscando vecinos…");
    fetch("/api/entities/" + encodeURIComponent(nodeId), { headers: { accept: "application/json" } })
      .then(function (res) {
        if (!res.ok) {
          // "Sin acceso" NO se deduce: se lee del status. El backend responde
          // 404 tanto si la entidad no existe como si la política la oculta
          // (el proveedor filtrado devuelve `None` en ambos casos), así que un
          // 404 se cuenta como "no encontrado" y nunca como "no autorizado":
          // decir "no tienes acceso" ante un 404 confirmaría que existe.
          // Solo 401/403 —que vienen del guarda, no del contenido— permiten
          // hablar de acceso.
          say(core.errorMessageForStatus(res.status));
          throw new Error("http");
        }
        return res.json();
      })
      .then(function (data) {
        var newNodes = [];
        var newEdges = [];
        ["outgoing", "incoming"].forEach(function (key) {
          (data[key] || []).forEach(function (rel) {
            newEdges.push(rel);
            if (rel.other_entity) newNodes.push(rel.other_entity);
          });
        });
        loaded = core.mergeGraph(loaded, { nodes: newNodes, edges: newEdges });
        rebuildFilterUi();
        applyFilters();
        say(EXPAND_DONE);
        focusNode(nodeId);
      })
      .catch(function () {
        if (note && !note.textContent) say(core.ERROR_MESSAGES.unknown);
      });
  }

  // ---------------------------------------------------------------------
  // Eventos
  // ---------------------------------------------------------------------

  function bindEvents() {
    reloadBtn.addEventListener("click", loadGraph);
    fitBtn.addEventListener("click", fitView);
    resetBtn.addEventListener("click", resetView);
    detailClose.addEventListener("click", clearDetail);
    clearFiltersBtn.addEventListener("click", clearAllFilters);

    searchInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        runSearch();
      } else if (e.key === "Escape") {
        searchInput.value = "";
        state.q = "";
        renderSearchResults([]);
        syncUrl();
      }
    });
    searchInput.addEventListener("input", function () {
      state.q = searchInput.value.trim();
      renderSearchResults(core.searchNodes(visible.nodes, state.q, { limit: 12 }));
    });

    limitSelect.addEventListener("change", function () {
      state.limit = parseInt(limitSelect.value, 10) || defaultLimit;
      syncUrl();
      loadGraph();
    });

    labelsToggle.addEventListener("change", function () {
      state.showEdgeLabels = labelsToggle.checked;
      applyFilters();
      syncUrl();
    });

    isolatedToggle.addEventListener("change", function () {
      state.hideIsolated = isolatedToggle.checked;
      applyFilters();
      syncUrl();
    });

    filtersToggle.addEventListener("click", function () {
      var collapsed = filtersPanel.classList.toggle("filters-collapsed");
      filtersToggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    });

    // Atajos de teclado globales (no interfieren al escribir en un campo).
    document.addEventListener("keydown", function (e) {
      var tag = (e.target && e.target.tagName) || "";
      var typing = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
      if (e.key === "/" && !typing) {
        e.preventDefault();
        searchInput.focus();
        searchInput.select();
      } else if (e.key === "Escape" && !typing) {
        clearDetail();
      } else if ((e.key === "f" || e.key === "F") && !typing && !e.ctrlKey && !e.metaKey) {
        fitView();
      } else if ((e.key === "e" || e.key === "E") && !typing && selectedId) {
        expandNeighbors(selectedId);
      }
    });
  }

  // ---------------------------------------------------------------------
  // Ventana de observación (SOLO LECTURA)
  //
  // Por qué existe: hay estado del visor que es perfectamente visible para
  // una persona —qué nodo está seleccionado, cuánto zoom hay, si el lienzo
  // sigue moviéndose— y que sin embargo una prueba no puede leer del DOM,
  // porque el grafo se pinta en un <canvas> y vis-network no publica nada.
  // Sin poder leerlo, una prueba de «buscar A y buscar B producen lo mismo»
  // se queda ciega justo en los canales donde una fuga sería más difícil de
  // ver a simple vista.
  //
  // LÍMITES, que son los que hacen que esto no sea una puerta trasera:
  //  - Solo LEE. No selecciona, no mueve, no carga, no filtra.
  //  - Devuelve identificadores de nodos que ESTÁN dibujados ahora mismo en
  //    la pantalla de quien mira: no añade ni un dato que no estuviera ya
  //    delante de sus ojos, y nada que el backend no le hubiera entregado.
  //  - No toca `loaded`: de aquí no se puede sacar el grafo.
  //
  // POR QUÉ SE CONGELA (Object.freeze + defineProperty no escribible)
  // ----------------------------------------------------------------
  // No es confidencialidad: esto solo devuelve lo ya dibujado. Es INTEGRIDAD
  // DE LA PRUEBA. Tres de los diecisiete canales de `_huella_de_busqueda`
  // (selección, encuadre y la espera de estabilización) se leen a través de
  // este objeto. Mientras fuera reemplazable —lo era: `writable`,
  // `configurable` y sustituible entero desde la consola— cualquier script de
  // la página podía devolver constantes y la huella seguiría saliendo igual
  // sin observar nada. Congelado, un intento de reescribirlo falla en modo
  // estricto y no tiene efecto fuera de él.
  // ---------------------------------------------------------------------

  var vistaDeObservacion = Object.freeze({
    /** ¿El motor de físicas ha dejado de mover los nodos? */
    isStabilized: function () { return rendererMissing ? true : stabilized; },
    /** Selección REAL de vis-network (no la ficha lateral, que es su reflejo). */
    selection: function () {
      if (!network) return null;
      return {
        nodes: network.getSelectedNodes().map(String).sort(),
        edges: network.getSelectedEdges().map(String).sort()
      };
    },
    /** Encuadre del lienzo: zoom y centro. */
    viewport: function () {
      if (!network) return null;
      var p = network.getViewPosition();
      return { scale: network.getScale(), x: p.x, y: p.y };
    }
  });

  Object.defineProperty(window, "S9KGraphView", {
    value: vistaDeObservacion,
    writable: false,
    configurable: false,
    enumerable: true
  });

  // ---------------------------------------------------------------------
  // Arranque
  // ---------------------------------------------------------------------

  function init() {
    var allowed = ["100", "300", "1000"];
    limitSelect.value = allowed.indexOf(String(state.limit)) !== -1 ? String(state.limit) : "300";
    state.limit = parseInt(limitSelect.value, 10);
    searchInput.value = state.q || "";
    labelsToggle.checked = state.showEdgeLabels !== false;
    isolatedToggle.checked = !!state.hideIsolated;
    clearDetail();
    bindEvents();
    loadGraph();
  }

  init();
})();
