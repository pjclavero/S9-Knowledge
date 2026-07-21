# -*- coding: utf-8 -*-
"""Protocolo de SELECCION POR FRAGMENTOS (capa EXPERIMENTAL, PR#95 V3).

Motivacion
----------
El protocolo clasico exige que el modelo externo devuelva ``evidence_text`` +
offsets exactos. Los LLM manejan mal esa tarea (parafrasean la cita, desalinean
los offsets), lo que provoca rechazos por "evidencia_inexistente" u
"offsets_invalidos" aunque el juicio sea correcto.

Este modulo ofrece una alternativa DETERMINISTA y PURA (sin red, sin estado):

1. Fragmenta el DOCUMENTO REAL en segmentos estables de frase, con IDs estables
   (``f-001``, ``f-002`` ...). El sistema es quien fija los offsets; el modelo
   solo ELIGE fragmentos por su ID.
2. El evaluador presenta al modelo esos fragmentos con sus IDs.
3. A partir de los ``fragment_ids`` elegidos, el sistema RECONSTRUYE los offsets
   contra el documento real.
4. La evidencia reconstruida es SIEMPRE una subcadena literal del documento, con
   offsets coherentes (invariante estructural garantizado por construccion).

Alcance / limites (por diseno):
  * Es una capa EXPERIMENTAL. NO migra el contrato persistente de
    ``RelationCandidate`` (20 campos): los ``fragment_ids`` viven en el protocolo,
    no en el nodo persistido.
  * Sin red, sin escritura, sin Neo4j. Modulo puro y determinista.
  * Reutiliza ``relations.signals._sentence_bounds`` para las fronteras de frase
    (no duplica logica de segmentacion).

El protocolo esta VERSIONADO (``FRAGMENT_PROTOCOL_VERSION``).
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional, Sequence

# Reutilizacion: fronteras de frase deterministas (fuente canonica, no se duplica).
from relations.signals import _sentence_bounds

# Version del protocolo experimental. Cualquier cambio de forma del contrato de
# fragmentos (claves, semantica de reconstruccion) debe subir esta version.
FRAGMENT_PROTOCOL_VERSION = "v1"

# Cota determinista por defecto para acotar tokens en documentos largos: si el
# documento produce mas fragmentos, se conservan los primeros ``max_fragments``
# (orden natural del documento). La cota se documenta y es reproducible.
DEFAULT_MAX_FRAGMENTS = 200

# Longitud del hash de contenido normalizado (hex). Suficiente para trazabilidad
# sin cargar el prompt.
_CONTENT_HASH_LEN = 16

_WS_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Normalizacion e identidad estable
# ---------------------------------------------------------------------------
def normalize_for_identity(text: str) -> str:
    """Normalizacion CANONICA para calcular la identidad de un fragmento.

    Absorbe diferencias TRIVIALES que no cambian el contenido semantico del
    fragmento:
      * Forma Unicode: se fuerza NFC (NFC y NFD colapsan al mismo resultado).
      * Espaciado: cualquier secuencia de espacios/blancos se colapsa a un solo
        espacio y se recortan los bordes.

    NO cambia mayusculas ni contenido lexico: dos frases distintas siguen dando
    identidades distintas.
    """
    if not isinstance(text, str):
        text = str(text)
    nfc = unicodedata.normalize("NFC", text)
    collapsed = _WS_RE.sub(" ", nfc).strip()
    return collapsed


def content_hash(text: str) -> str:
    """Hash estable del contenido NORMALIZADO de un fragmento.

    Estable ante cambios de normalizacion triviales (NFC/NFD, espaciado): si dos
    textos normalizan igual, su hash coincide.
    """
    norm = normalize_for_identity(text)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:_CONTENT_HASH_LEN]


# ---------------------------------------------------------------------------
# Fragmento estable
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Fragment:
    """Fragmento estable del documento (frase o segmento).

    ``start``/``end`` son offsets (en caracteres) DENTRO del documento REAL, de
    modo que ``document[start:end] == text`` siempre. La identidad combina el
    ORDEN (``fragment_id`` posicional ``f-NNN``) y el HASH del contenido
    normalizado (``content_hash``), tal como pide el diseno ("hash de contenido
    normalizado + orden").
    """

    fragment_id: str
    index: int
    start: int
    end: int
    text: str
    content_hash: str

    def to_dict(self) -> dict:
        return {
            "fragment_id": self.fragment_id,
            "index": self.index,
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "content_hash": self.content_hash,
        }


def fragment_document(
    document: Optional[str],
    *,
    max_fragments: int = DEFAULT_MAX_FRAGMENTS,
) -> list[Fragment]:
    """Fragmenta el documento en frases estables, no solapadas.

    Determinista y puro. Recorre el documento usando ``_sentence_bounds``
    (reutilizado de ``signals``) para localizar cada frase, descarta los tramos
    formados solo por blancos y asigna IDs posicionales estables ``f-001``,
    ``f-002`` ...

    Garantias:
      * Los fragmentos NO se solapan y respetan el orden del documento.
      * ``document[frag.start:frag.end] == frag.text`` (literalidad por
        construccion).
      * Cota de tokens: si el documento produce mas de ``max_fragments``
        fragmentos, se conservan los primeros (orden natural). Determinista.
    """
    if not document:
        return []
    if not isinstance(document, str):
        document = str(document)

    fragments: list[Fragment] = []
    n = len(document)
    pos = 0
    idx = 0
    while pos < n:
        _ini, fin = _sentence_bounds(document, pos, pos)
        # Invariante de progreso: _sentence_bounds siempre avanza (fin > pos)
        # para pos < n, pero blindamos por si acaso.
        if fin <= pos:
            fin = pos + 1
        raw = document[pos:fin]
        stripped = raw.strip()
        if stripped:
            lead = len(raw) - len(raw.lstrip())
            start = pos + lead
            end = start + len(stripped)
            idx += 1
            frag_id = f"f-{idx:03d}"
            fragments.append(
                Fragment(
                    fragment_id=frag_id,
                    index=idx,
                    start=start,
                    end=end,
                    text=document[start:end],
                    content_hash=content_hash(stripped),
                )
            )
            if idx >= max_fragments:
                break
        pos = fin
    return fragments


def build_fragment_index(fragments: Iterable[Fragment]) -> dict[str, Fragment]:
    """Indexa fragmentos por su ``fragment_id`` (para reconstruccion rapida)."""
    return {f.fragment_id: f for f in fragments}


# ---------------------------------------------------------------------------
# Render para el prompt (presenta los fragmentos con sus IDs)
# ---------------------------------------------------------------------------
def render_fragments_for_prompt(
    fragments: Sequence[Fragment],
    *,
    sanitizer=None,
    max_fragment_chars: int = 500,
) -> str:
    """Renderiza los fragmentos como lineas ``f-NNN: <texto>`` para el prompt.

    ``sanitizer`` (opcional) neutraliza delimitadores/inyeccion en el texto
    MOSTRADO; NO afecta a los offsets ni a la reconstruccion (que operan sobre el
    documento real). Cada fragmento se acota a ``max_fragment_chars`` en la
    presentacion (solo visual; la reconstruccion usa el texto real completo).
    """
    lines: list[str] = []
    for frag in fragments:
        shown = frag.text
        if sanitizer is not None:
            shown = sanitizer(shown)
        shown = shown.replace("\n", " ").replace("\r", " ").strip()
        if len(shown) > max_fragment_chars:
            shown = shown[:max_fragment_chars] + " [...]"
        lines.append(f"{frag.fragment_id}: {shown}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Reconstruccion + validacion de literalidad
# ---------------------------------------------------------------------------
@dataclass
class ReconstructResult:
    """Resultado de reconstruir offsets desde ``fragment_ids``.

    Si ``ok`` es False, ``errors`` explica el motivo (id inexistente, lista
    vacia, incoherencia). Si ``ok`` es True, ``text == document[start:end]`` es
    subcadena literal del documento.
    """

    ok: bool
    start: int = -1
    end: int = -1
    text: str = ""
    fragment_ids: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def reconstruct_evidence(
    document: Optional[str],
    index: Mapping[str, Fragment],
    fragment_ids: Sequence[str],
) -> ReconstructResult:
    """Reconstruye la evidencia (offsets + texto) desde una lista de fragment_ids.

    Reglas:
      * ``fragment_ids`` debe ser lista NO vacia de strings.
      * Todo id debe existir en el indice; un id inexistente => rechazo.
      * El orden de los ids es IRRELEVANTE: se toma el minimo ``start`` y el
        maximo ``end`` de los fragmentos seleccionados. La evidencia
        reconstruida es ``document[start:end]``, subcadena literal por
        construccion (incluye el texto intermedio si los fragmentos no son
        contiguos, garantizando coherencia y literalidad).

    INVARIANTE: si ``ok`` es True, ``document[start:end] == text`` y
    ``0 <= start <= end <= len(document)``.
    """
    doc = document or ""
    errors: list[str] = []

    if not isinstance(fragment_ids, (list, tuple)) or len(fragment_ids) == 0:
        return ReconstructResult(ok=False, errors=["fragment_ids vacío o no es lista"])

    selected: list[Fragment] = []
    seen: set[str] = set()
    for fid in fragment_ids:
        if not isinstance(fid, str) or not fid.strip():
            errors.append(f"fragment_id no string o vacío: {fid!r}")
            continue
        if fid not in index:
            errors.append(f"fragment_inexistente: {fid!r} no existe en el documento")
            continue
        if fid not in seen:
            seen.add(fid)
            selected.append(index[fid])

    if errors:
        return ReconstructResult(ok=False, errors=errors)

    start = min(f.start for f in selected)
    end = max(f.end for f in selected)
    text = doc[start:end]

    # Guardas defensivas de la invariante (nunca deberian dispararse).
    if not (0 <= start <= end <= len(doc)):
        return ReconstructResult(ok=False, errors=[f"offsets_invalidos: [{start},{end}] fuera de [0,{len(doc)}]"])
    if text != doc[start:end] or text not in doc:
        return ReconstructResult(ok=False, errors=["evidencia_inexistente: reconstrucción no literal"])

    return ReconstructResult(
        ok=True,
        start=start,
        end=end,
        text=text,
        fragment_ids=sorted(seen, key=lambda fid: index[fid].index),
    )


__all__ = [
    "FRAGMENT_PROTOCOL_VERSION",
    "DEFAULT_MAX_FRAGMENTS",
    "Fragment",
    "ReconstructResult",
    "normalize_for_identity",
    "content_hash",
    "fragment_document",
    "build_fragment_index",
    "render_fragments_for_prompt",
    "reconstruct_evidence",
]
