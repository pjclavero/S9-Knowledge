# -*- coding: utf-8 -*-
"""Ingesta V3 de una fuente REAL de operador, en dry-run.

    export PYTHONPATH=data-engine/app
    python3 -m knowledge_v3.pipeline.ingest_cli <fichero> \
        --perfil examples/ingesta-v3/perfil-operador.json \
        --catalogo examples/ingesta-v3/catalogo-workspace.json \
        --dry-run

QUE ES ESTO Y QUE NO ES
-----------------------
`pipeline.runner` corre la cadena sobre un SPLIT DEL GOLD y la puntua con el
arnes. Es medicion, no operacion: sus fuentes son documentos del dataset y sus
identificadores estan redactados a mano. Este modulo es la otra puerta, la que
faltaba: coge **bytes de un fichero del operador**, los mete por el normalizador
real y publica lo que la cadena produjo.

    fichero -> SourceInput -> SourceCase -> episodios + evidencia
            -> extraccion -> reconciliacion -> resolucion -> motor -> plan

NO ESCRIBE EN NEO4J
-------------------
`--dry-run` es el defecto y hoy el UNICO modo. No hay `--apply`: escribir exige
un driver, un grafo efimero y el gate del writer, y eso es del carril C. Este
modulo no construye ningun driver, igual que `runner.py` no lo construye, y la
ausencia de la bandera es la garantia — no un booleano que alguien pueda poner
a `True`.

DE DONDE SALE EL MUNDO
----------------------
El extractor determinista no tiene reconocedor de entidades propio: sus
menciones salen del GLOSARIO (alias del perfil + nombres del catalogo) o del
patron `<titulo declarado> <Nombre Propio>` (defecto D-6, `docs/v3/11-e2e.md`).
Por eso el CLI pide un perfil y admite un catalogo, y por eso, cuando el
glosario queda vacio, lo DECLARA (`SIN_GLOSARIO`) en vez de publicar un cero
mudo.

DETERMINISMO
------------
La cadena no llama al reloj: `--ahora` y `--ingerido-en` son datos. Si no se
dan, el CLI lee el reloj UNA vez, en la frontera, y lo declara en el informe;
dentro de la cadena sigue siendo un dato inyectado.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from ..contracts.base import sha256_hash
from ..contracts.game_profile import GameProfile
from ..extraction.lexicon import Lexicon, LexiconEntry
from ..multimodal.base import IngestOptions, SourceInput
from ..multimodal.registry import default_registry
from ..resolution.catalog import CatalogEntity, InMemoryEntityCatalog
from .config import PipelineConfig
from . import bridge
from .errors import PipelineError
from .ingest_report import ingest_report, to_markdown
from .pipeline import KnowledgePipeline, SourceCase

#: Extension -> `source_kind`, solo para las que este CLI declara soportar de
#: verdad. Lo demas se le deja al registro de adaptadores, que resuelve por
#: MIME y extension y falla con un mensaje claro si no sabe.
KIND_BY_EXTENSION = {
    ".md": "MARKDOWN",
    ".markdown": "MARKDOWN",
    ".txt": "TEXT",
    ".text": "TEXT",
    ".note": "NOTE",
}


def _utc_now() -> str:
    """Reloj leido UNA vez, en la frontera. Dentro de la cadena es un dato."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def load_profile(path: Path, *, workspace: Optional[str] = None) -> GameProfile:
    """`GameProfile` del operador, validado contra el contrato congelado."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    profile = GameProfile.from_dict(doc)
    if workspace is not None and profile.workspace != workspace:
        raise PipelineError(
            "config",
            f"el perfil {path} es del workspace {profile.workspace!r} y se pidio "
            f"{workspace!r}. No se reescribe en silencio: corrige uno de los dos",
        )
    return profile


def load_catalog(path: Optional[Path]) -> list[dict[str, Any]]:
    """Entidades declaradas del workspace. Lista vacia si no hay fichero."""
    if path is None:
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    entities = doc.get("entities") if isinstance(doc, dict) else doc
    if not isinstance(entities, list):
        raise PipelineError(
            "input", f"{path}: se esperaba una lista `entities` de entidades"
        )
    for entity in entities:
        missing = {"entity_id", "type", "name"} - set(entity)
        if missing:
            raise PipelineError(
                "input", f"{path}: entidad sin {sorted(missing)}: {entity!r}"
            )
    return entities


def build_catalog(entities: Sequence[dict], workspace: str) -> InMemoryEntityCatalog:
    """Catalogo del resolutor: SOLO lo que ya existe en el grafo.

    Las provisionales quedan fuera a proposito — mismo criterio que
    `sources.entity_catalog`: una entidad que aun no existe no puede ser
    candidata a enlace, y es justo lo que obliga al motor a proponer un alta.
    """
    return InMemoryEntityCatalog(
        [
            CatalogEntity(
                entity_id=e["entity_id"],
                workspace=workspace,
                entity_type=e["type"],
                canonical_name=e["name"],
                aliases=tuple(e.get("aliases") or ()),
            )
            for e in entities
            if not e.get("provisional")
        ]
    )


def build_lexicon(entities: Sequence[dict], profile: GameProfile) -> Lexicon:
    """Glosario: alias del perfil (sin tipo) + nombres del catalogo (con tipo).

    Las provisionales SI entran: el extractor tiene que saber leer el nombre
    aunque la entidad no exista todavia en el grafo.
    """
    catalog = [
        LexiconEntry(
            canonical=e["name"],
            entity_type=e["type"],
            variants=tuple(e.get("aliases") or ()),
            confidence=0.9,
            origin="catalog",
        )
        for e in entities
    ]
    return Lexicon.from_profile(profile).merged(Lexicon(catalog))


def build_source(path: Path, *, source_kind: Optional[str] = None) -> SourceInput:
    """Bytes REALES del fichero. Nada se reconstruye ni se rellena."""
    data = path.read_bytes()
    if not data:
        raise PipelineError("input", f"{path}: fichero vacio; no hay fuente que ingerir")
    extension = path.suffix.lower()
    mime, _ = mimetypes.guess_type(path.name)
    return SourceInput(
        data=data,
        original_name=path.name,
        original_location=path.resolve().as_uri(),
        mime_type=mime,
        source_kind=source_kind or KIND_BY_EXTENSION.get(extension),
    )


def supported_kinds() -> list[str]:
    """Lo que el registro de adaptadores dice soportar. Observado, no cableado."""
    return default_registry().source_kinds()


def run_ingest(
    path: Path,
    *,
    profile_path: Path,
    catalog_path: Optional[Path] = None,
    workspace: Optional[str] = None,
    collection_id: Optional[str] = None,
    now: Optional[str] = None,
    ingested_at: Optional[str] = None,
    source_kind: Optional[str] = None,
) -> dict:
    """Corre la cadena sobre UN fichero y devuelve el informe estructurado."""
    profile = load_profile(profile_path, workspace=workspace)
    ws = profile.workspace
    moment = now or _utc_now()
    ingested = ingested_at or moment
    collection = collection_id or f"collection:{ws}"

    entities = load_catalog(catalog_path)
    source = build_source(path, source_kind=source_kind)
    options = IngestOptions(
        workspace=ws,
        collection_id=collection,
        ingested_at=ingested,
        game_profile=profile.profile_id,
    )
    config = PipelineConfig(
        workspace=ws,
        collection_id=collection,
        profile=profile,
        now=moment,
        ingested_at=ingested,
        catalog=build_catalog(entities, ws),
        lexicon=build_lexicon(entities, profile),
        # DRY-RUN: sin driver, el writer solo puede simular.
        apply=False,
        writer_driver=None,
        ablation="operator_ingest",
    )
    case = SourceCase(
        source_id=path.name, source=source, ingest_options=options
    )
    lexicon = config.lexicon
    # El snapshot del motor arranca del catalogo: sin el, NINGUNA entidad
    # existe para el motor y todo cae por `ENTITY_NOT_IN_SNAPSHOT` aunque el
    # resolutor haya enlazado con confianza 1.0. Mismo puente que usa el runner.
    result = KnowledgePipeline(config).run(
        [case], catalog_entities=bridge.entities_from_catalog(entities)
    )
    return ingest_report(
        result,
        source_path=path,
        input_hash=sha256_hash(source.data.decode("utf-8", errors="replace")),
        source_bytes=len(source.data),
        catalog_entities=entities,
        profile=profile,
        lexicon_entries=len(getattr(lexicon, "entries", ()) or ()),
        clock_read_at_boundary=now is None,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="knowledge_v3.pipeline.ingest_cli",
        description=(
            "Mete una fuente real por la cadena V3 y publica lo que produjo. "
            "DRY-RUN siempre: no escribe en Neo4j y no admite --apply."
        ),
    )
    parser.add_argument("fichero", type=Path, help="fuente a ingerir (.md, .txt)")
    parser.add_argument(
        "--perfil", type=Path, required=True, help="GameProfile del workspace (JSON)"
    )
    parser.add_argument(
        "--catalogo", type=Path, default=None,
        help="entidades ya existentes en el grafo (JSON). Sin el, el glosario "
             "solo tiene los alias del perfil",
    )
    parser.add_argument("--workspace", default=None, help="debe coincidir con el perfil")
    parser.add_argument("--collection", default=None)
    parser.add_argument("--source-kind", default=None, help="fuerza el adaptador")
    parser.add_argument("--ahora", default=None, help="instante inyectado (ISO-8601 Z)")
    parser.add_argument("--ingerido-en", default=None, dest="ingerido_en")
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="no escribe en el grafo. Es el defecto y el unico modo",
    )
    parser.add_argument(
        "--formato", choices=("markdown", "json", "ambos"), default="markdown",
        help="markdown = acta legible; json = informe estructurado; ambos = las dos",
    )
    parser.add_argument(
        "--out-dir", type=Path, default=None,
        help="escribe acta.md e informe.json ahi en vez de por la salida estandar",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args, extra = parser.parse_known_args(argv)
    if extra:
        # `--apply` no es "todavia no implementado": es que escribir de verdad
        # exige driver, grafo efimero y el gate del writer. Un mensaje claro
        # vale mas que una bandera que no hace nada.
        if "--apply" in extra:
            parser.error(
                "--apply no existe en este CLI. La escritura la ejerce el writer "
                "controlado (carril C) contra un Neo4j efimero y con su gate; "
                "este modulo no construye ningun driver"
            )
        parser.error(f"argumentos desconocidos: {extra}")

    try:
        report = run_ingest(
            args.fichero,
            profile_path=args.perfil,
            catalog_path=args.catalogo,
            workspace=args.workspace,
            collection_id=args.collection,
            now=args.ahora,
            ingested_at=args.ingerido_en,
            source_kind=args.source_kind,
        )
    except PipelineError as exc:
        print(f"ERROR [{exc.stage}]: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    acta = to_markdown(report)
    if args.out_dir is not None:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / "acta.md").write_text(acta, encoding="utf-8")
        (args.out_dir / "informe.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"acta:    {args.out_dir / 'acta.md'}")
        print(f"informe: {args.out_dir / 'informe.json'}")
        return 0

    if args.formato in ("json", "ambos"):
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if args.formato in ("markdown", "ambos"):
        print(acta)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
