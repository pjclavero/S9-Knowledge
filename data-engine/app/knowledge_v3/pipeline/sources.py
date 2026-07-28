# -*- coding: utf-8 -*-
"""De un split del dataset a entradas de la cadena.

DOS PUERTAS, Y LA ELECCION NO ES COSMETICA
------------------------------------------
`from_episodes()` arranca la cadena en el extractor con los episodios y las
evidencias del gold. `from_raw()` reconstruye bytes y arranca en el
normalizador.

Solo la primera es MEDIBLE contra el gold, y la razon es estructural (ver
docs/v3/11-e2e.md §5, defecto D-4): las claves de emparejamiento del arnes son
`(episode_id, start, end)` para menciones y fragmentos, y `(source_asset_id,
sequence)` para episodios. Los identificadores del gold (`episode:leyenda-
cronica:e01`, `asset:leyenda-cronica`) fueron REDACTADOS, no producidos: el
normalizador deriva los suyos por sha256 (`ep-6938a54e...`) y numera las
secuencias desde 0, mientras el gold numera desde 1. Nada empareja. Una corrida
desde bytes puntua cero en todo, y ese cero no diria nada del sistema.

Por eso la medicion nominal entra por episodios y la puerta de bytes existe
para las pruebas conjuntas que SI la necesitan (normalizador + extractor), donde
lo que se comprueba es que la cadena se sostiene sobre la salida real del
normalizador, no que coincida con unos identificadores inventados.

Ademas, el dataset `dev` NO CONTIENE FUENTES: guarda el `SourceAsset` (un
descriptor con `byte_size` y `content_hash`) pero no el fichero. Los bytes que
`from_raw()` entrega son una RECONSTRUCCION a partir del gold, declarada como
tal en `metadata`, y su hash no coincide con el `content_hash` del asset.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Optional, Sequence

from ..benchmarks.loader import GoldDataset, GoldSource
from ..contracts.episode import SourceEpisode
from ..contracts.evidence import EvidenceFragment
from ..contracts.game_profile import GameProfile
from ..contracts.source_asset import SourceAsset
from ..extraction.lexicon import Lexicon, LexiconEntry
from ..multimodal.base import IngestOptions, SourceInput
from ..resolution.catalog import CatalogEntity, InMemoryEntityCatalog
from .config import GoldInjection
from .errors import PipelineError
from .pipeline import SourceCase

#: Fuentes cuyos bytes se pueden reconstruir del gold sin inventar contenido.
RECONSTRUCTIBLE = ("MARKDOWN", "TEXT", "NOTE", "TABLE", "AUDIO", "VIDEO", "IMAGE")


def _sorted_episodes(source: GoldSource) -> list[dict]:
    return sorted(source.episodes, key=lambda e: e["sequence"])


def profile_of(gold: GoldDataset, profile_id: str) -> GameProfile:
    """Perfil del catalogo del split, ya validado contra el contrato congelado."""
    try:
        doc = gold.profiles[profile_id]
    except KeyError as exc:
        raise PipelineError(
            "input",
            f"el split {gold.split!r} no trae el perfil {profile_id!r}; "
            f"tiene {sorted(gold.profiles)}",
        ) from exc
    return GameProfile.from_dict(doc)


def from_episodes(source: GoldSource, *, with_gold: bool = True) -> SourceCase:
    """Entrada por episodios: el gold hace de salida del normalizador.

    `with_gold=True` adjunta las resoluciones y los claims gold para que las
    ablaciones `*_to_engine` puedan sustituirlos. La cadena NO los usa salvo
    que la configuracion lo pida (`entity_source`/`claim_source` = "gold").
    """
    episodes = [SourceEpisode.from_dict(e) for e in _sorted_episodes(source)]
    fragments = [EvidenceFragment.from_dict(f) for f in source.fragments]
    gold = GoldInjection()
    if with_gold:
        from ..contracts.claim import ClaimProposal
        from ..contracts.resolution import EntityResolution

        gold = GoldInjection(
            resolutions=[EntityResolution.from_dict(r) for r in source.resolutions],
            claims=[ClaimProposal.from_dict(c) for c in source.claims],
        )
    return SourceCase(
        source_id=source.source_id,
        asset=SourceAsset.from_dict(source.asset),
        episodes=episodes,
        fragments=fragments,
        gold=gold,
    )


def reconstruct_bytes(source: GoldSource) -> tuple[bytes, Optional[dict]]:
    """Bytes plausibles de la fuente, mas el `payload` que su adaptador pide.

    No se inventa contenido: todo sale del texto o de la tabla que el gold ya
    publica. Lo unico que se anade es la ESTRUCTURA del formato (separadores de
    parrafo, cabecera CSV, envoltura de transcripcion), que es justamente lo
    que el normalizador tiene que saber leer.
    """
    kind = source.asset["source_kind"]
    episodes = _sorted_episodes(source)

    if kind in ("MARKDOWN", "TEXT", "NOTE"):
        return "\n\n".join(e["text"] or "" for e in episodes).encode("utf-8"), None

    if kind == "TABLE":
        table = next((e["table"] for e in episodes if e.get("table")), None)
        if not table:
            raise PipelineError("input", f"{source.source_id}: TABLE sin bloque `table`")
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(table["header"])
        writer.writerows(table["rows"])
        return buf.getvalue().encode("utf-8"), {"has_header": True, "delimiter": ","}

    if kind in ("AUDIO", "VIDEO", "YOUTUBE"):
        segments = [
            {
                "text": e["text"] or "",
                "start": e.get("time_start"),
                "end": e.get("time_end"),
                "speaker": (e.get("speaker") or {}).get("label"),
                "speaker_id": (e.get("speaker") or {}).get("speaker_id"),
            }
            for e in episodes
        ]
        duration = max((s["end"] or 0.0) for s in segments) if segments else 0.0
        payload = {
            "structured_data": {
                "segments": segments,
                "duration_seconds": duration,
                "language": source.asset.get("language_hint"),
            }
        }
        return b"AUDIO-RECONSTRUIDO-DEL-GOLD", payload

    if kind in ("IMAGE", "CHARACTER_SHEET", "HANDWRITING", "MAP", "DIAGRAM"):
        regions = [
            {
                "region_id": f"r{i}",
                "bbox": e.get("bbox") or {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
                "mode": "OCR" if e["modality"] == "OCR_TEXT" else "DESCRIBE",
                "page": e.get("page"),
            }
            for i, e in enumerate(episodes)
        ]
        return b"IMAGEN-RECONSTRUIDA-DEL-GOLD", {"regions": regions}

    raise PipelineError(
        "input", f"{source.source_id}: no se sabe reconstruir bytes de {kind!r}"
    )


def from_raw(source: GoldSource, *, collection_id: Optional[str] = None) -> SourceCase:
    """Entrada por bytes: la cadena arranca en el normalizador de verdad."""
    asset = source.asset
    data, payload = reconstruct_bytes(source)
    options = IngestOptions(
        workspace=asset["workspace"],
        collection_id=collection_id or asset["collection_id"],
        ingested_at=asset["ingested_at"],
        created_at=asset.get("created_at"),
        game_profile=asset.get("game_profile", "generic"),
        language_hint=asset.get("language_hint"),
        privacy_class=asset.get("privacy_class", "INTERNAL"),
        copyright_class=asset.get("copyright_class", "UNKNOWN"),
        **(asset.get("processing_policy") or {}),
    )
    return SourceCase(
        source_id=source.source_id,
        source=SourceInput(
            data=data,
            original_name=asset["original_name"],
            original_location=asset["original_location"],
            mime_type=asset.get("mime_type"),
            source_kind=asset["source_kind"],
            payload=payload,
        ),
        ingest_options=options,
    )


def cases_from_gold(
    gold: GoldDataset,
    *,
    entry: str = "episodes",
    only: Sequence[str] = (),
) -> list[SourceCase]:
    """Todas las fuentes del split como entradas de la cadena, en orden estable."""
    if entry not in ("episodes", "raw"):
        raise PipelineError("input", f"puerta de entrada desconocida: {entry!r}")
    sources = sorted(gold.sources, key=lambda s: s.source_id)
    if only:
        wanted = set(only)
        sources = [s for s in sources if s.source_id in wanted]
    build = from_episodes if entry == "episodes" else from_raw
    return [build(s) for s in sources]


def catalog_entries(gold: GoldDataset) -> list[dict[str, Any]]:
    """Entidades del catalogo del split: estado previo del grafo, no respuesta."""
    return list(gold.entities)


def entity_catalog(gold: GoldDataset, workspace: str) -> InMemoryEntityCatalog:
    """Catalogo del resolutor con las entidades YA EXISTENTES del workspace.

    Es estado del mundo, no gold: el resolutor tiene que poder enlazar contra
    lo que ya hay en el grafo, igual que en produccion enlazaria contra Neo4j.
    Las provisionales se excluyen: por definicion aun no existen.
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
            for e in gold.entities
            if not e.get("provisional")
        ]
    )


def workspace_lexicon(gold: GoldDataset, profile: GameProfile) -> Lexicon:
    """Glosario del workspace: alias del perfil + nombres del catalogo.

    Las dos fuentes son referencia del mundo, no respuestas. El perfil aporta
    las variantes de superficie (incluidas las degradadas por OCR, que estan
    declaradas ahi a proposito) y el catalogo aporta el TIPO, que el perfil no
    lleva: `Lexicon.from_profile` deja `entity_type=None` en todos sus alias, y
    sin tipo el eje de dominio/rango del motor no puede juzgar nada.

    Sin glosario el extractor determinista no encuentra NADA (ver 11-e2e.md,
    defecto D-6): sus menciones salen del lexico o de los titulos del perfil, y
    no tiene ningun reconocedor propio.
    """
    catalog_entries_ = [
        LexiconEntry(
            canonical=e["name"],
            entity_type=e["type"],
            variants=tuple(e.get("aliases") or ()),
            confidence=0.9,
            origin="catalog",
        )
        for e in gold.entities
    ]
    return Lexicon.from_profile(profile).merged(Lexicon(catalog_entries_))


__all__ = [
    "RECONSTRUCTIBLE",
    "cases_from_gold",
    "catalog_entries",
    "entity_catalog",
    "from_episodes",
    "from_raw",
    "profile_of",
    "reconstruct_bytes",
    "workspace_lexicon",
]
