#!/usr/bin/env python3
"""Exporta el grafo de propiedades a notas SilverBullet."""
import argparse
import json
import sys
from pathlib import Path

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", required=True)
    p.add_argument("--entities-json", required=True)
    p.add_argument("--spaces-dir")
    args = p.parse_args()

    spaces_dir = args.spaces_dir or f"/opt/knowledge-services/spaces/{args.workspace}"

    with open(args.entities_json) as f:
        data = json.load(f)

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from ingest_rpg import export_to_markdown
    from schemas.rpg_schema import EntityBase, RelationshipBase

    entities = [EntityBase(**e) for e in data.get("entities", [])]
    relationships = [RelationshipBase(**r) for r in data.get("relationships", [])]

    export_to_markdown(entities, relationships, args.workspace,
                       "manual", spaces_dir)
    print(f"Exportación completada: {len(entities)} entidades")

if __name__ == "__main__":
    main()
