(function () {
  "use strict";

  const workspace = window.S9K_WORKSPACE || "leyenda";
  const defaultLimit = window.S9K_GRAPH_LIMIT || 300;

  const TYPE_COLORS = {
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
    Spell: "#bc8cff",
  };

  function colorForType(type) {
    return TYPE_COLORS[type] || "#9aa0ae";
  }

  const canvas = document.getElementById("graph-canvas");
  const sidePanel = document.getElementById("side-panel");
  const searchInput = document.getElementById("search-input");
  const typeFilter = document.getElementById("type-filter");
  const limitSelect = document.getElementById("limit-select");
  const reloadBtn = document.getElementById("reload-btn");

  limitSelect.value = [100, 300, 1000].includes(defaultLimit) ? String(defaultLimit) : "300";

  let network = null;
  let nodesById = {};
  let edgesById = {};

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  function fieldRow(label, value) {
    return `<div class="field"><div class="field-label">${esc(label)}</div>` +
           `<div class="field-value">${value != null && value !== "" ? esc(value) : "—"}</div></div>`;
  }

  function renderNodePanel(node) {
    sidePanel.innerHTML = `
      <h2>${esc(node.label)}</h2>
      <p><span class="pill">${esc(node.type_label)}</span>
         ${node.confidence_label ? `<span class="pill">Confianza: ${esc(node.confidence_label)}</span>` : ""}
         ${node.visibility_label ? `<span class="pill">${esc(node.visibility_label)}</span>` : ""}
      </p>
      ${fieldRow("Descripción", node.description)}
      ${fieldRow("Alias", (node.aliases || []).join(", "))}
      ${fieldRow("Fuente", node.source_document)}
      ${fieldRow("Páginas", (node.source_pages || []).join(", "))}
      ${fieldRow("Capa de conocimiento", node.knowledge_layer_label)}
      ${fieldRow("Estado de revisión", node.review_status_label)}
      <p><a class="btn" href="/entity/${encodeURIComponent(node.id)}">Ver ficha completa</a></p>
      <details>
        <summary>Datos técnicos</summary>
        <pre>${esc(JSON.stringify(node.technical || {}, null, 2))}</pre>
      </details>
    `;
  }

  function renderEdgePanel(edge) {
    const fromNode = nodesById[edge.from];
    const toNode = nodesById[edge.to];
    sidePanel.innerHTML = `
      <h2>Relación</h2>
      <p>
        ${fromNode ? esc(fromNode.label) : "?"} →
        <strong>${esc(edge.label || edge.type)}</strong> →
        ${toNode ? esc(toNode.label) : "?"}
      </p>
      <p>
         ${edge.confidence_label ? `<span class="pill">Confianza: ${esc(edge.confidence_label)}</span>` : ""}
      </p>
      ${fieldRow("Descripción / evidencia", edge.description)}
      ${fieldRow("Fuente", edge.source_document)}
      ${fieldRow("Páginas", (edge.source_pages || []).join(", "))}
      ${fieldRow("Estado de revisión", edge.review_status_label)}
      <details>
        <summary>Datos técnicos</summary>
        <pre>${esc(JSON.stringify({ relation_type: edge.type, ...(edge.technical || {}) }, null, 2))}</pre>
      </details>
    `;
  }

  async function loadEntityTypes() {
    const res = await fetch(`/api/entity-types?workspace=${encodeURIComponent(workspace)}`);
    const data = await res.json();
    const current = typeFilter.value;
    typeFilter.innerHTML = '<option value="">Todos los tipos</option>';
    (data.entity_types || []).forEach((et) => {
      const opt = document.createElement("option");
      opt.value = et.entity_type;
      opt.textContent = `${et.entity_type} (${et.count})`;
      typeFilter.appendChild(opt);
    });
    typeFilter.value = current;
  }

  async function loadGraph() {
    const params = new URLSearchParams({
      workspace,
      limit: limitSelect.value || String(defaultLimit),
    });
    if (typeFilter.value) params.set("entity_type", typeFilter.value);
    if (searchInput.value.trim()) params.set("q", searchInput.value.trim());

    const res = await fetch(`/api/graph?${params.toString()}`);
    if (!res.ok) {
      sidePanel.innerHTML = `<p class="empty-hint">Error cargando el grafo (${res.status}).</p>`;
      return;
    }
    const data = await res.json();

    nodesById = {};
    edgesById = {};
    (data.nodes || []).forEach((n) => { nodesById[n.id] = n; });
    (data.edges || []).forEach((e) => { edgesById[e.id] = e; });

    const visNodes = new vis.DataSet(
      (data.nodes || []).map((n) => ({
        id: n.id,
        label: n.label,
        title: n.type_label,
        color: { background: colorForType(n.type), border: "#0b0d12" },
        font: { color: "#e6e8ee" },
        shape: "dot",
        size: 14,
      }))
    );

    const visEdges = new vis.DataSet(
      (data.edges || []).map((e) => ({
        id: e.id,
        from: e.from,
        to: e.to,
        label: e.label || e.type,
        arrows: "to",
        font: { color: "#9aa0ae", size: 10, strokeWidth: 0 },
        color: { color: "#444b5c", highlight: "#6ea8fe" },
      }))
    );

    if (network) network.destroy();
    network = new vis.Network(
      canvas,
      { nodes: visNodes, edges: visEdges },
      {
        physics: { stabilization: true, barnesHut: { gravitationalConstant: -4000 } },
        interaction: { hover: true },
      }
    );

    network.on("click", (params) => {
      if (params.nodes.length > 0) {
        const node = nodesById[params.nodes[0]];
        if (node) renderNodePanel(node);
      } else if (params.edges.length > 0) {
        const edge = edgesById[params.edges[0]];
        if (edge) renderEdgePanel(edge);
      } else {
        sidePanel.innerHTML = '<p class="empty-hint">Pincha un nodo o una relación para ver su ficha.</p>';
      }
    });
  }

  reloadBtn.addEventListener("click", loadGraph);
  searchInput.addEventListener("keydown", (e) => { if (e.key === "Enter") loadGraph(); });
  typeFilter.addEventListener("change", loadGraph);
  limitSelect.addEventListener("change", loadGraph);

  loadEntityTypes().then(loadGraph);
})();
