# -*- coding: utf-8 -*-
"""Derivacion determinista de identificadores del normalizador.

Regla unica: **ningun identificador se inventa**. Todos se derivan por sha256
del JSON canonico de los campos que definen la identidad logica del objeto. Dos
ejecuciones sobre el mismo fichero y las mismas opciones producen exactamente
los mismos IDs, en el mismo orden y con la misma serializacion byte a byte.

Por que no un UUID aleatorio: un UUID hace que reingerir el mismo PDF cree una
segunda cadena de procedencia que el ledger no puede reconciliar con la primera.
El hash lo impide por construccion.
"""
from __future__ import annotations

import hashlib
from typing import Any

from ..contracts import canonical_json

#: Longitud del digest hexadecimal que se incrusta en el ID. 32 hex = 128 bits:
#: sobra para que la colision sea inalcanzable y el ID siga siendo legible.
ID_DIGEST_LEN = 32


def digest_of(payload: dict[str, Any]) -> str:
    """sha256 hexadecimal del JSON canonico de `payload`."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def derive_id(prefix: str, payload: dict[str, Any]) -> str:
    """Identificador estable `<prefix>-<digest>` derivado de `payload`.

    Cumple `stable_id` del contrato: empieza por caracter alfanumerico y solo
    usa `[A-Za-z0-9._:-]`.
    """
    return f"{prefix}-{digest_of(payload)[:ID_DIGEST_LEN]}"


def sha256_bytes(data: bytes) -> str:
    """sha256 hexadecimal del contenido binario REAL (no de su representacion)."""
    return hashlib.sha256(data).hexdigest()


def hash_field(hex_value: str) -> dict[str, str]:
    """Envuelve un digest hexadecimal en el bloque `hash` del contrato."""
    if len(hex_value) != 64 or any(c not in "0123456789abcdef" for c in hex_value):
        raise ValueError(f"digest sha256 invalido: {hex_value!r}")
    return {"algorithm": "sha256", "value": hex_value}


def asset_id_for(workspace: str, collection_id: str, content_hash_hex: str) -> str:
    """ID del asset: workspace + coleccion + hash del contenido.

    El workspace entra en la derivacion a proposito: el aislamiento entre
    bovedas es duro, y dos bovedas que ingieren el mismo fichero NO deben
    compartir identificador de asset aunque compartan `content_hash`.
    """
    return derive_id(
        "sa",
        {
            "workspace": workspace,
            "collection_id": collection_id,
            "content_hash": content_hash_hex,
        },
    )


def episode_id_for(asset_id: str, sequence: int, content_hash_hex: str) -> str:
    """ID del episodio: asset + posicion + hash de su propio contenido."""
    return derive_id(
        "ep",
        {"asset_id": asset_id, "sequence": sequence, "content_hash": content_hash_hex},
    )


def fragment_id_for(
    episode_id: str, start: int, end: int, media_type: str, literal_text: str
) -> str:
    """ID del fragmento: episodio + tramo anclado + tipo + literal exacto."""
    return derive_id(
        "ef",
        {
            "episode_id": episode_id,
            "start": start,
            "end": end,
            "media_type": media_type,
            "literal": literal_text,
        },
    )


def speaker_id_for(asset_id: str, label: str) -> str:
    """ID de hablante estable dentro del asset.

    Deriva de la etiqueta que trae la diarizacion, no de un contador: si el
    proveedor reordena los turnos, el hablante sigue siendo el mismo.
    """
    return derive_id("spk", {"asset_id": asset_id, "label": label})
