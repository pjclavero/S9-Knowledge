# -*- coding: utf-8 -*-
"""Carga del dataset gold y de las predicciones a medir.

El split NO esta cableado en ninguna parte: `load_gold("dev")` y
`load_gold("heldout")` recorren el mismo codigo. Cuando el equipo independiente
entregue su split, se copia el directorio y el arnes lo mide sin cambiar una
linea. Esa es la unica defensa estructural contra repetir el pecado de V2
(medir sobre el mismo material sobre el que se ajusto).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .contracts_bridge import ContractV3Error, validate_document

DATASETS_DIR = Path(__file__).resolve().parent / "datasets"

#: Ficheros de fuente esperados, en el orden de la cadena gold.
SOURCE_FILES = (
    "source_asset",
    "episodes",
    "fragments",
    "mentions",
    "resolutions",
    "claims",
    "assertions",
    "plans",
    "negatives",
    "reference_text",
)

#: Acciones de resolucion que asignan identidad y cuales campo la lleva.
_ACTION_ID_FIELD = {
    "LINK_EXISTING": "selected_entity_id",
    "CREATE_NEW": "assigned_entity_id",
    "CREATE_PROVISIONAL": "assigned_entity_id",
}


class DatasetError(RuntimeError):
    """El dataset gold no es coherente. Nunca se sigue adelante con uno roto."""


@dataclass
class GoldSource:
    """Cadena gold completa de una fuente."""

    source_id: str
    world: str
    asset: dict[str, Any]
    episodes: list[dict[str, Any]] = field(default_factory=list)
    fragments: list[dict[str, Any]] = field(default_factory=list)
    mentions: list[dict[str, Any]] = field(default_factory=list)
    resolutions: list[dict[str, Any]] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    assertions: list[dict[str, Any]] = field(default_factory=list)
    plans: list[dict[str, Any]] = field(default_factory=list)
    negatives: list[dict[str, Any]] = field(default_factory=list)
    reference_text: dict[str, str] = field(default_factory=dict)


@dataclass
class GoldDataset:
    """Dataset gold de un split completo."""

    split: str
    manifest: dict[str, Any]
    entities: list[dict[str, Any]]
    profiles: dict[str, dict[str, Any]]
    sources: list[GoldSource]

    # --- accesos derivados -------------------------------------------------
    @property
    def episodes(self) -> list[dict[str, Any]]:
        return [e for s in self.sources for e in s.episodes]

    @property
    def fragments(self) -> list[dict[str, Any]]:
        return [f for s in self.sources for f in s.fragments]

    @property
    def mentions(self) -> list[dict[str, Any]]:
        return [m for s in self.sources for m in s.mentions]

    @property
    def resolutions(self) -> list[dict[str, Any]]:
        return [r for s in self.sources for r in s.resolutions]

    @property
    def claims(self) -> list[dict[str, Any]]:
        return [c for s in self.sources for c in s.claims]

    @property
    def assertions(self) -> list[dict[str, Any]]:
        return [a for s in self.sources for a in s.assertions]

    @property
    def plans(self) -> list[dict[str, Any]]:
        return [p for s in self.sources for p in s.plans]

    @property
    def negatives(self) -> list[dict[str, Any]]:
        return [n for s in self.sources for n in s.negatives]

    @property
    def reference_text(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for s in self.sources:
            out.update(s.reference_text)
        return out

    def claims_for(self, consumer: str) -> list[dict[str, Any]]:
        """Claims gold segun quien los consume.

        ``extractor`` excluye los marcados ``ENGINE_ONLY``: son propuestas
        incorrectas que existen para que el motor tenga algo que rechazar, y
        exigirselas al extractor seria pedirle que se equivoque.
        """
        if consumer not in ("extractor", "engine"):
            raise ValueError(f"consumidor desconocido: {consumer!r}")
        if consumer == "engine":
            return self.claims
        return [
            c
            for c in self.claims
            if (c.get("metadata") or {}).get("role", "EXTRACTOR_AND_ENGINE")
            != "ENGINE_ONLY"
        ]

    @property
    def decisions(self) -> list[dict[str, Any]]:
        """Decisiones gold del motor, extraidas de los planes."""
        return [d for p in self.plans for d in p["decisions"]]

    @property
    def symmetric_predicates(self) -> frozenset[str]:
        profile = self.profiles.get("generic")
        if not profile:
            return frozenset()
        return frozenset(
            p["predicate"] for p in profile["predicates"] if p.get("symmetric")
        )

    @property
    def catalog_entity_ids(self) -> frozenset[str]:
        return frozenset(e["entity_id"] for e in self.entities)

    def mention_to_entity(self) -> dict[str, str]:
        """mencion -> entidad gold, derivado de las resoluciones."""
        out: dict[str, str] = {}
        for res in self.resolutions:
            field_name = _ACTION_ID_FIELD.get(res["action"])
            if field_name is None:
                continue
            entity_id = res.get(field_name)
            if entity_id is None:
                continue
            for mid in res["mention_ids"]:
                out[mid] = entity_id
        return out

    def coreference_clusters(self) -> list[list[str]]:
        """Grupos de menciones correferentes segun `coreference_candidates`.

        La correferencia es anotacion del EXTRACTOR: que menciones apuntan al
        mismo referente dentro del texto. Decidir a que entidad del catalogo
        corresponde ese referente es otra cosa, y la mide el resolutor con
        `mention_to_entity`. Mezclarlas haria que un fallo de identidad
        contaminase la nota de correferencia y al reves.
        """
        from .harness import clusters_from_candidates

        return clusters_from_candidates(self.mentions)


@dataclass
class PredictionBundle:
    """Salida de un subsistema (o de la cadena completa) a medir.

    Todos los campos son opcionales: medir el extractor no exige tener plan, y
    medir el normalizador no exige tener claims. Lo que no venga, no se puntua,
    y el informe dice que no se puntuo.
    """

    #: Sin valor por defecto A PROPOSITO: un bundle que no declara su split se
    #: mediria contra el gold que hubiera cargado, que es justo el accidente que
    #: separa dev de held-out. `run()` exige que coincida.
    split: str | None = None
    ablation: str = "unspecified"
    subsystem: str = "unspecified"
    run_id: str = "unspecified"
    episodes: list[dict[str, Any]] = field(default_factory=list)
    fragments: list[dict[str, Any]] = field(default_factory=list)
    mentions: list[dict[str, Any]] = field(default_factory=list)
    resolutions: list[dict[str, Any]] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    assertions: list[dict[str, Any]] = field(default_factory=list)
    plans: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PredictionBundle":
        known = {f for f in cls.__dataclass_fields__}
        unknown = sorted(set(data) - known)
        if unknown:
            raise DatasetError(f"campos desconocidos en las predicciones: {unknown}")
        if not data.get("split"):
            raise DatasetError(
                "las predicciones no declaran `split`. Es obligatorio: medir una "
                "salida contra el gold equivocado es el accidente que este arnes "
                "existe para impedir"
            )
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def from_path(cls, path: Path | str) -> "PredictionBundle":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def from_gold(cls, gold: GoldDataset, *, ablation: str = "gold_identity") -> "PredictionBundle":
        """El gold, presentado como si fuese una prediccion perfecta.

        Es la prueba de cordura del arnes: si medir el gold contra si mismo no
        da 1.0 en todo, el arnes esta roto y ningun otro numero suyo vale nada.
        """
        return cls(
            split=gold.split,
            ablation=ablation,
            subsystem="all",
            run_id="gold-identity",
            episodes=[dict(e) for e in gold.episodes],
            fragments=[dict(f) for f in gold.fragments],
            mentions=[dict(m) for m in gold.mentions],
            resolutions=[dict(r) for r in gold.resolutions],
            # Solo los claims que un buen extractor DEBE proponer: los
            # ENGINE_ONLY existen para que el motor tenga algo que rechazar, y
            # devolverselos al extractor los contaria como falsos positivos.
            claims=[dict(c) for c in gold.claims_for("extractor")],
            decisions=[dict(d) for d in gold.decisions],
            assertions=[dict(a) for a in gold.assertions],
            plans=[dict(p) for p in gold.plans],
        )


# --------------------------------------------------------------------------
# Carga
# --------------------------------------------------------------------------
def available_splits(root: Path | None = None) -> list[str]:
    root = root or DATASETS_DIR
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and (p / "manifest.json").exists())


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise DatasetError(f"falta el fichero del dataset: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _documents(path: Path, expected_split: str) -> list[Any]:
    """Documentos de un fichero del dataset, con DOBLE comprobacion de split.

    La primera defensa es el sobre del fichero. La segunda es la marca de cada
    documento, y tiene que estar aqui: instalar un split es "copiar un
    directorio", asi que un fichero traido de otro split con el sobre reescrito
    a mano pasaria la primera y no la segunda.
    """
    data = _read(path)
    if data.get("split") != expected_split:
        raise DatasetError(
            f"{path.name} declara split {data.get('split')!r} y se esperaba "
            f"{expected_split!r}: un fichero sin marca de split correcta no entra"
        )
    documents = data.get("documents", [])
    for doc in documents:
        if not isinstance(doc, dict) or "contract_id" not in doc:
            continue
        marca = (doc.get("metadata") or {}).get("benchmark") or {}
        if marca.get("split") != expected_split:
            raise DatasetError(
                f"{path.name}: el documento {doc.get('contract_id')} lleva "
                f"metadata.benchmark.split={marca.get('split')!r} y el fichero "
                f"declara {expected_split!r}. Un documento colado de otro split "
                "no entra ni aunque el sobre diga lo contrario"
            )
    return documents


def load_gold(split: str = "dev", *, root: Path | None = None, validate: bool = False) -> GoldDataset:
    """Carga un split completo. `validate=True` pasa el validador REAL a todo."""
    root = (root or DATASETS_DIR) / split
    manifest = _read(root / "manifest.json")
    if manifest.get("split") != split:
        raise DatasetError(f"el manifiesto de {split} declara otro split")

    entities_doc = _read(root / "catalog" / "entities.json")
    if entities_doc.get("split") != split:
        raise DatasetError("el catalogo de entidades no declara el split correcto")

    profiles: dict[str, dict[str, Any]] = {}
    for rel in manifest.get("catalog_files", []):
        if "game_profile" not in rel:
            continue
        for doc in _documents(root / rel, split):
            profiles[doc["profile_id"]] = doc

    sources: list[GoldSource] = []
    for entry in manifest["sources"]:
        base = root / "sources" / entry["source_id"]
        loaded = {name: _documents(base / f"{name}.json", split) for name in SOURCE_FILES}
        src = GoldSource(
            source_id=entry["source_id"],
            world=entry["world"],
            asset=loaded["source_asset"][0],
            episodes=loaded["episodes"],
            fragments=loaded["fragments"],
            mentions=loaded["mentions"],
            resolutions=loaded["resolutions"],
            claims=loaded["claims"],
            assertions=loaded["assertions"],
            plans=loaded["plans"],
            negatives=loaded["negatives"],
            reference_text={r["episode_id"]: r["text"] for r in loaded["reference_text"]},
        )
        sources.append(src)

    dataset = GoldDataset(
        split=split,
        manifest=manifest,
        entities=entities_doc["entities"],
        profiles=profiles,
        sources=sources,
    )
    if validate:
        validate_gold(dataset)
    return dataset


def contract_documents(dataset: GoldDataset) -> list[dict[str, Any]]:
    """Todos los documentos del dataset que SON contratos `v3-internal-v1`."""
    docs: list[dict[str, Any]] = list(dataset.profiles.values())
    for s in dataset.sources:
        docs.append(s.asset)
        docs.extend(s.episodes)
        docs.extend(s.fragments)
        docs.extend(s.mentions)
        docs.extend(s.resolutions)
        docs.extend(s.claims)
        docs.extend(s.assertions)
        docs.extend(s.plans)
    return docs


def validate_gold(dataset: GoldDataset) -> None:
    """Valida el dataset entero contra los contratos congelados."""
    for doc in contract_documents(dataset):
        try:
            validate_document(doc)
        except ContractV3Error as exc:
            raise DatasetError(
                f"documento gold que incumple su contrato "
                f"({doc.get('contract_id')}): {exc}"
            ) from exc


def index_by(items: Iterable[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(i[key]): i for i in items}


__all__ = [
    "DATASETS_DIR",
    "DatasetError",
    "GoldDataset",
    "GoldSource",
    "PredictionBundle",
    "SOURCE_FILES",
    "available_splits",
    "contract_documents",
    "index_by",
    "load_gold",
    "validate_gold",
]
