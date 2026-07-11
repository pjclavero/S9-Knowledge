#!/usr/bin/env python3
"""Ingesta experimental de código en Property Graph."""
import argparse
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger("property-graph-code")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

EXCLUDE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "build", "dist", "vendor"}
EXCLUDE_FILES = {".env", ".env.local", ".env.production"}
EXCLUDE_EXT = {".key", ".pem", ".crt", ".p12", ".pfx", ".cer"}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--dry-run", action="store_true", default=True)
    args = p.parse_args()

    repo = Path(args.repo)
    if not repo.exists():
        log.error("Repositorio no existe: %s", repo)
        sys.exit(1)

    files_found = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fname in files:
            fpath = Path(root) / fname
            if fname in EXCLUDE_FILES or fpath.suffix in EXCLUDE_EXT:
                continue
            files_found.append(fpath)

    log.info("Archivos encontrados: %d", len(files_found))
    for f in files_found[:20]:
        log.info("  [dry-run] %s", f.relative_to(repo))

    if not args.dry_run:
        log.warning("Procesamiento real no implementado todavía. Requiere revisión antes de activar.")

if __name__ == "__main__":
    main()
