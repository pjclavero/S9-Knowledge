# -*- coding: utf-8 -*-
"""Protocolo de SELECCION POR FRAGMENTOS para la consulta a IA externa (Bloque 7).

Problema que resuelve
---------------------
El protocolo clasico exige que el modelo externo devuelva ``evidence_text`` MAS los
offsets exactos ``evidence_start``/``evidence_end``. Contar caracteres es justo la
tarea que peor hacen los LLM: parafrasean levemente la cita y desalinean los offsets,
de modo que ``external_ai_shadow._validate_verdict`` los rechaza por
``evidencia_inexistente`` u ``offsets_invalidos`` aunque el JUICIO sea correcto.

Este modulo invierte la responsabilidad:

  1. El SISTEMA fragmenta el DOCUMENTO REAL en frases con IDs estables (``f-001``,
     ``f-002``, ...) y fija los offsets.
  2. El modelo solo ELIGE fragmentos por su ID.
  3. El SISTEMA reconstruye los offsets desde los ids elegidos.

La literalidad de la evidencia deja de ser algo que se COMPRUEBA y pasa a ser algo que
se CONSTRUYE: la evidencia devuelta es, por construccion, ``document[start:end]``.

Procedencia
-----------
Adaptado de la rama de experimentacion ``exp/pr95-v3-fragment-selection`` (``28ce8a1``,
fichero ``relations/fragment_protocol.py``), leida en SOLO LECTURA. Aquella rama no se
ha modificado, fusionado ni cherry-pickeado.

Alcance / limites (por diseno)
------------------------------
  * NO migra el contrato persistente de ``RelationCandidate`` (20 campos): los
    ``fragment_ids`` viven en el protocolo de consulta, no en el nodo persistido.
  * Modulo PURO y DETERMINISTA: sin red, sin disco, sin reloj, sin azar, sin escritura.
  * Reutiliza ``relations.signals._sentence_bounds`` para las fronteras de frase (no
    duplica logica de segmentacion).

El protocolo esta VERSIONADO (``FRAGMENT_PROTOCOL_VERSION``): cualquier cambio en la
forma del contrato de fragmentos o en la semantica de reconstruccion debe subirla.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional, Sequence

# Reutilizacion: fronteras de frase deterministas (fuente canonica, no se duplica).
from relations.signals import _sentence_bounds

FRAGMENT_PROTOCOL_VERSION = "relation-fragment-protocol/v1"

#: Cota determinista para acotar tokens en documentos largos. Si el documento produce
#: mas fragmentos, se conservan los PRIMEROS (orden natural del documento) y se marca
#: el truncamiento: nada se descarta en silencio.
DEFAULT_MAX_FRAGMENTS = 200

#: Longitud (hex) del hash de contenido normalizado. Trazabilidad sin cargar el prompt.
_CONTENT_HASH_LEN = 16

_WS_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Normalizacion e identidad estable
# ---------------------------------------------------------------------------
def normalize_for_identity(text: str) -> str:
    """Normalizacion CANONICA para calcular la identidad de un fragmento.

    Absorbe diferencias TRIVIALES que no cambian el contenido:
      * Forma Unicode: se fuerza NFC (NFC y NFD colapsan al mismo resultado).
      * Espaciado: cualquier secuencia de blancos se colapsa a un espacio y se recortan
        los bordes.

    NO cambia mayusculas ni contenido lexico: dos frases distintas siguen dando
    identidades distintas.
    """
    if not isinstance(text, str):
        text = str(text)
    nfc = unicodedata.normalize("NFC", text)
    return _WS_RE.sub(" ", nfc).strip()


def content_hash(text: str) -> str:
    """Hash estable del contenido NORMALIZADO de un fragmento."""
    return hashlib.sha256(
        normalize_for_identity(text).encode("utf-8")
    ).hexdigest()[:_CONTENT_HASH_LEN]


# ---------------------------------------------------------------------------
# Fragmento estable
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Fragment:
    """Fragmento estable del documento.

    ``start``/``end`` son offsets (en caracteres) dentro del documento REAL, de modo
    que ``document[start:end] == text`` SIEMPRE. La identidad combina el ORDEN
    (``fragment_id`` posicional ``f-NNN``) y el HASH del contenido normalizado.
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
) -> list:
    """Fragmenta el documento en frases estables y NO solapadas.

    Determinista y puro. Recorre el documento con ``_sentence_bounds`` (reutilizado de
    ``relations.signals``), descarta los tramos formados solo por blancos y asigna IDs
    posicionales estables ``f-001``, ``f-002``...

    Garantias:
      * Los fragmentos NO se solapan y respetan el orden del documento.
      * ``document[frag.start:frag.end] == frag.text`` (literalidad por construccion).
      * Cota de tokens: con mas de ``max_fragments`` fragmentos se conservan los
        primeros. Determinista y reproducible.
    """
    if not document:
        return []
    if not isinstance(document, str):
        document = str(document)
    if not isinstance(max_fragments, int) or isinstance(max_fragments, bool) or max_fragments < 1:
        raise ValueError("max_fragments debe ser un entero >= 1")

    fragments: list = []
    n = len(document)
    pos = 0
    idx = 0
    while pos < n:
        _ini, fin = _sentence_bounds(document, pos, pos)
        # Invariante de progreso: _sentence_bounds avanza siempre para pos < n, pero
        # se blinda para no poder entrar en bucle infinito con entradas patologicas.
        if fin <= pos:
            fin = pos + 1
        raw = document[pos:fin]
        stripped = raw.strip()
        if stripped:
            lead = len(raw) - len(raw.lstrip())
            start = pos + lead
            end = start + len(stripped)
            idx += 1
            fragments.append(
                Fragment(
                    fragment_id=f"f-{idx:03d}",
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


def build_fragment_index(fragments: Iterable) -> dict:
    """Indexa fragmentos por su ``fragment_id`` (para reconstruccion rapida)."""
    return {f.fragment_id: f for f in fragments}


# ---------------------------------------------------------------------------
# Render para el prompt
# ---------------------------------------------------------------------------
def render_fragments_for_prompt(
    fragments: Sequence,
    *,
    sanitizer=None,
    max_fragment_chars: int = 500,
) -> str:
    """Renderiza los fragmentos como lineas ``f-NNN: <texto>`` para el prompt.

    ``sanitizer`` (opcional; en el pipeline es ``relations.prompts.sanitize_document``)
    neutraliza delimitadores e inyeccion en el texto MOSTRADO. NO afecta a los offsets
    ni a la reconstruccion, que operan siempre sobre el documento REAL: por eso una
    inyeccion dentro de un fragmento no puede alterar la evidencia reconstruida.
    """
    lines: list = []
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
# Reconstruccion + literalidad por construccion
# ---------------------------------------------------------------------------
@dataclass
class ReconstructResult:
    """Resultado de reconstruir offsets desde ``fragment_ids``.

    Si ``ok`` es False, ``errors`` explica el motivo. Si ``ok`` es True,
    ``text == document[start:end]`` es subcadena LITERAL del documento.
    """

    ok: bool
    start: int = -1
    end: int = -1
    text: str = ""
    fragment_ids: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "fragment_ids": list(self.fragment_ids),
            "errors": list(self.errors),
        }


def reconstruct_evidence(
    document: Optional[str],
    index: Mapping,
    fragment_ids: Sequence,
) -> ReconstructResult:
    """Reconstruye la evidencia (offsets + texto) desde una lista de ``fragment_ids``.

    Reglas (fail-closed):
      * ``fragment_ids`` debe ser lista/tupla NO vacia de strings.
      * TODO id debe existir en el indice; un id inexistente => rechazo (no se ignora
        ni se aproxima: el modelo no puede inventar anclajes).
      * El orden de los ids es IRRELEVANTE: se toma el minimo ``start`` y el maximo
        ``end`` de los fragmentos seleccionados y se devuelve ``document[start:end]``,
        subcadena literal por construccion (incluye el texto intermedio si los
        fragmentos no son contiguos, lo que preserva coherencia y literalidad).

    INVARIANTE: si ``ok``, entonces ``document[start:end] == text`` y
    ``0 <= start <= end <= len(document)``.

    LIMITACION CONOCIDA (`min(start)..max(end)`)
    --------------------------------------------
    La reconstruccion es un span CONTIGUO, no la union de los fragmentos elegidos.
    Elegir ``["f-001", "f-009"]`` devuelve **todo lo que hay entre medias**, no dos
    trozos. Consecuencias:

      * La literalidad NUNCA se rompe (siempre es una rodaja real del documento), que
        es la propiedad que sostiene el bloque.
      * Pero un modelo puede AMPLIAR la cita mas alla de lo que justifica su juicio
        eligiendo dos ids muy separados, y la evidencia anotada seria mas larga de lo
        debido.

    Hoy es INOCUO para la decision: la unica postura que puede derivarse de una
    evidencia aceptada es ``REINFORCE``, y `apply_consultation` no mueve ni el estado
    ni la recomendacion con un refuerzo (solo degrada). Es decir, el peor caso es una
    ANOTACION mas larga de la cuenta, nunca una decision distinta. Si en el futuro el
    refuerzo llegara a pesar en la decision, esto DEBE volverse un rechazo (o una
    union de spans), no antes.
    """
    doc = document or ""
    errors: list = []

    if not isinstance(fragment_ids, (list, tuple)) or len(fragment_ids) == 0:
        return ReconstructResult(ok=False, errors=["fragment_ids vacio o no es lista"])
    if not isinstance(index, Mapping):
        return ReconstructResult(ok=False, errors=["indice de fragmentos invalido"])

    selected: list = []
    seen: set = set()
    for fid in fragment_ids:
        if not isinstance(fid, str) or not fid.strip():
            errors.append(f"fragment_id no string o vacio: {fid!r}")
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

    # Guardas defensivas de la invariante (no deberian dispararse nunca: si lo hacen,
    # el indice no corresponde al documento y eso es fail-closed, no una aproximacion).
    if not (0 <= start <= end <= len(doc)):
        return ReconstructResult(
            ok=False,
            errors=[f"offsets_invalidos: [{start},{end}] fuera de [0,{len(doc)}]"],
        )
    if text != doc[start:end] or text not in doc:
        return ReconstructResult(
            ok=False, errors=["evidencia_inexistente: reconstruccion no literal"]
        )

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
