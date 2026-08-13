// Capa cliente: cuantas relaciones ENTRAN en filterGraph y cuantas SALEN.
const path = require("path");
const core = require(path.resolve(__dirname, "../../../viewer/app/static/js/graph-core.js"));
const g = JSON.parse(require("fs").readFileSync(process.argv[2], "utf-8"));
const sinFiltros = core.filterGraph(g, {});
console.log(`entran nodos=${g.nodes.length} aristas=${g.edges.length}`);
console.log(`salen  nodos=${sinFiltros.nodes.length} aristas=${sinFiltros.edges.length}  (sin filtros de usuario)`);
// Control: el medidor debe poder ponerse ROJO.
const conFiltro = core.filterGraph(g, { relationTypes: ["TIPO_QUE_NO_EXISTE"] });
console.log(`CONTROL filtro imposible -> aristas=${conFiltro.edges.length} (debe ser 0)`);
const conOculto = core.filterGraph(g, { hideIsolated: true });
console.log(`hideIsolated=true -> nodos=${conOculto.nodes.length} aristas=${conOculto.edges.length}`);
