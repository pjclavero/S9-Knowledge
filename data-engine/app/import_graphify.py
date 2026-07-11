#!/usr/bin/env python3
"""Importa graph.json de Graphify a Neo4j (experimental)."""
import argparse
import json
import logging
import sys
from pathlib import Path

log = logging.getLogger("import-graphify")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

TECH_NODE_TYPES = frozenset({
    "Repository", "Directory", "File", "Module", "Package", "Class", "Function", "Method",
    "APIEndpoint", "Database", "Table", "DockerService", "Host", "VirtualMachine",
    "Container", "Port", "MQTTTopic", "EnvironmentVariable", "Configuration", "Dependency",
})

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", required=True)
    p.add_argument("--graph", required=True)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    gfile = Path(args.graph)
    if not gfile.exists():
        log.error("No existe: %s", gfile)
        sys.exit(1)

    with open(gfile) as f:
        data = json.load(f)

    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    log.info("Graphify graph: %d nodos, %d aristas", len(nodes), len(edges))

    if args.dry_run:
        for n in nodes[:10]:
            log.info("[dry-run] Nodo: %s (type=%s)", n.get("label", "?"), n.get("type", "?"))
        for e in edges[:10]:
            log.info("[dry-run] Arista: %s -[%s]-> %s",
                     e.get("source", "?"), e.get("relation", "?"), e.get("target", "?"))
        log.info("[dry-run] No se escribió nada en Neo4j")
        return

    log.info("Importación real no implementada todavía. Usa --dry-run para previsualizar.")

if __name__ == "__main__":
    main()
