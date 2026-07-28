# -*- coding: utf-8 -*-
"""Utilidades de texto y ANCLAJE de evidencia para los extractores V3.

Dos responsabilidades, ninguna mas:

1. **Tokenizacion con offsets reales.** Todo el emparejamiento lexico (glosario,
   frases de relacion, pronombres, expresiones temporales) se hace sobre TOKENS
   normalizados individualmente, nunca sobre el texto entero normalizado: la
   normalizacion NFKD cambia la longitud de la cadena y destruiria la
   correspondencia con los offsets del episodio. Normalizando token a token, el
   par `(start, end)` que se emite es siempre un offset del texto ORIGINAL.

2. **Anclaje de citas a fragmentos reales** (`EvidenceIndex`). Es la barrera
   anti-alucinacion del subsistema: ningun proveedor (Ollama, externo, vision)
   puede aportar un `fragment_id` ni un offset; solo puede aportar una CITA, y
   la cita se verifica contra el texto literal de los fragmentos que el sistema
   local ya tenia. Si la cita no existe, la propuesta se cae.

La normalizacion se DELEGA en `glossary.glossary_store.normalize_term` (V1). No
se reimplementa aqui: si un dia cambia la normalizacion del glosario, cambia en
un solo sitio. El import es diferido y de solo lectura; este modulo no abre la
base de datos del glosario ni escribe nada.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_WS_RE = re.compile(r"\s+")
_SENTENCE_END_RE = re.compile(r"[.!?;\n\r]+")

_normalizer: Optional[Callable[[str], str]] = None


class ExtractionTextError(RuntimeError):
    """No se puede normalizar: la utilidad V1 del glosario no es importable."""


def _get_normalizer() -> Callable[[str], str]:
    """Carga diferida de `glossary.glossary_store.normalize_term`.

    Import diferido a proposito: importar el paquete `glossary` en el momento de
    importar `knowledge_v3.extraction` acoplaria el arranque del subsistema V3 a
    un paquete de V1 que solo se necesita para normalizar.
    """
    global _normalizer
    if _normalizer is None:
        try:
            from glossary.glossary_store import normalize_term  # noqa: WPS433
        except ImportError as exc:  # pragma: no cover - solo sin data-engine/app en sys.path
            raise ExtractionTextError(
                "no se pudo importar glossary.glossary_store.normalize_term: la "
                "normalizacion NO se duplica en V3, se reutiliza la de V1"
            ) from exc
        _normalizer = normalize_term
    return _normalizer


def normalize(value: str) -> str:
    """Normalizacion canonica de comparacion (la MISMA que usa el glosario V1)."""
    if not value:
        return ""
    return _get_normalizer()(value)


def collapse_whitespace(value: str) -> str:
    """Colapsa espacios preservando el texto literal (no normaliza acentos)."""
    return _WS_RE.sub(" ", value).strip()


# --------------------------------------------------------------------------
# Tokenizacion con offsets
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Token:
    """Token con su offset EXACTO en el texto original."""

    text: str
    norm: str
    start: int
    end: int
    index: int


def tokenize(text: str) -> list[Token]:
    """Tokeniza conservando offsets del texto original.

    Cada token se normaliza por separado: asi `norm` sirve para comparar y
    `(start, end)` sigue apuntando al texto tal y como esta en el episodio.
    """
    out: list[Token] = []
    for i, m in enumerate(_TOKEN_RE.finditer(text or "")):
        raw = m.group(0)
        out.append(Token(text=raw, norm=normalize(raw), start=m.start(), end=m.end(), index=i))
    return out


def token_norms(tokens: Sequence[Token]) -> list[str]:
    return [t.norm for t in tokens]


def phrase_tokens(phrase: str) -> tuple[str, ...]:
    """Secuencia de tokens normalizados de una frase de referencia (glosario, regla)."""
    return tuple(t.norm for t in tokenize(phrase) if t.norm)


def find_phrase(
    tokens: Sequence[Token],
    needle: Sequence[str],
    *,
    lo: int = 0,
    hi: Optional[int] = None,
) -> list[tuple[int, int]]:
    """Todas las apariciones de `needle` (tokens normalizados) en `tokens`.

    Devuelve pares `(indice_primer_token, indice_ultimo_token)` inclusivos.
    Emparejamiento por secuencia completa de tokens = limite de palabra por
    construccion: 'or' nunca casa dentro de 'orco'.
    """
    if not needle:
        return []
    hi = len(tokens) if hi is None else hi
    n = len(needle)
    hits: list[tuple[int, int]] = []
    for i in range(lo, max(lo, hi - n + 1)):
        if all(tokens[i + k].norm == needle[k] for k in range(n)):
            hits.append((i, i + n - 1))
    return hits


@dataclass(frozen=True)
class Sentence:
    """Frase con offsets y el rango de tokens que contiene."""

    start: int
    end: int
    first_token: int
    last_token: int

    def contains_token(self, index: int) -> bool:
        return self.first_token <= index <= self.last_token


def split_sentences(text: str, tokens: Sequence[Token]) -> list[Sentence]:
    """Corte en frases por puntuacion fuerte. Sin frases, no hay contexto acotado.

    Un extractor de precision NO debe unir un sujeto de una frase con un objeto
    de la siguiente: la frase es la unidad minima donde la evidencia textual
    puede llamarse inequivoca.
    """
    if not text:
        return []
    bounds: list[tuple[int, int]] = []
    pos = 0
    for m in _SENTENCE_END_RE.finditer(text):
        if m.start() > pos:
            bounds.append((pos, m.start()))
        pos = m.end()
    if pos < len(text):
        bounds.append((pos, len(text)))
    out: list[Sentence] = []
    for start, end in bounds:
        inside = [t.index for t in tokens if t.start >= start and t.end <= end]
        if not inside:
            continue
        out.append(Sentence(start=start, end=end, first_token=inside[0], last_token=inside[-1]))
    return out


# --------------------------------------------------------------------------
# Anclaje de evidencia
# --------------------------------------------------------------------------
#: Base de los offsets emitidos. Cuando el episodio tiene texto, los offsets son
#: del texto del episodio; cuando no lo tiene (TABLE, IMAGE...), son del texto
#: literal del fragmento que ancla la mencion. Se declara SIEMPRE en
#: `metadata.offset_basis`: un offset sin base declarada no es reproducible.
OFFSET_BASIS_EPISODE = "episode"
OFFSET_BASIS_FRAGMENT = "fragment"


@dataclass(frozen=True)
class Anchor:
    """Resultado de anclar una cita: donde esta y con que reservas."""

    fragment_id: str
    start: int
    end: int
    basis: str
    reason_codes: tuple[str, ...] = ()

    @property
    def ambiguous(self) -> bool:
        return "AMBIGUOUS_ANCHOR" in self.reason_codes


@dataclass
class EvidenceIndex:
    """Indice de los fragmentos REALES de un episodio.

    Todo lo que un extractor emite tiene que pasar por aqui. La regla es una y
    no admite excepcion: *un identificador de fragmento solo es valido si el
    sistema local lo creo, y una cita solo es valida si aparece literalmente en
    el texto de ese fragmento*.
    """

    episode_id: str
    text: Optional[str]
    fragments: tuple  # tuple[EvidenceFragment, ...] (evita import circular de tipos)
    tokens: list[Token] = field(default_factory=list)
    sentences: list[Sentence] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.tokens = tokenize(self.text or "")
        self.sentences = split_sentences(self.text or "", self.tokens)
        self._by_id = {f.fragment_id: f for f in self.fragments}
        self._norm_cache = {f.fragment_id: normalize(f.literal_text) for f in self.fragments}

    # -- consultas basicas ------------------------------------------------
    @property
    def has_text(self) -> bool:
        return bool(self.text)

    @property
    def basis(self) -> str:
        return OFFSET_BASIS_EPISODE if self.has_text else OFFSET_BASIS_FRAGMENT

    @property
    def fragment_ids(self) -> list[str]:
        return [f.fragment_id for f in self.fragments]

    def get(self, fragment_id: str):
        return self._by_id.get(fragment_id)

    def exists(self, fragment_id: str) -> bool:
        return fragment_id in self._by_id

    def covering(self, start: int, end: int) -> list[str]:
        """Fragmentos cuyo rango de offsets cubre `[start, end)` en el episodio."""
        return [
            f.fragment_id
            for f in self.fragments
            if f.start <= start and end <= f.end
        ]

    def contains_quote(self, fragment_id: str, quote: str) -> bool:
        """La cita aparece (normalizada) en el texto literal del fragmento.

        Contencion EXACTA de la cadena normalizada, nunca parecido. Un umbral de
        similitud, por alto que sea, acepta citas que el texto no dice: "Kael
        vive en Valdo" se parece un 0.98 a "Kael vive en Valdor" y no es lo
        mismo. La normalizacion (minusculas, sin tildes) es lo unico que se
        tolera, y viene del glosario V1.
        """
        norm_frag = self._norm_cache.get(fragment_id)
        if norm_frag is None:
            return False
        needle = normalize(quote)
        return bool(needle) and needle in norm_frag

    # -- anclaje ----------------------------------------------------------
    def anchor_quote(self, quote: str, claimed_fragment_id: Optional[str] = None) -> Optional[Anchor]:
        """Ancla una CITA a un fragmento real. Devuelve None si no existe.

        Orden de comprobaciones (y por que):

        1. Si el proveedor propone un `fragment_id`, solo se acepta si existe
           **y** contiene la cita. Un id inventado no se corrige en silencio:
           se marca `FRAGMENT_ID_NOT_FOUND` / `QUOTE_NOT_IN_CLAIMED_FRAGMENT` y
           se intenta reanclar por contenido.
        2. Reanclaje por contenido: se busca la cita en todos los fragmentos.
           Un solo acierto = anclaje limpio; varios = anclaje ambiguo (se toma
           el primero en orden documental y se marca para revision); ninguno =
           la propuesta se rechaza.
        """
        quote = collapse_whitespace(quote or "")
        if not quote:
            return None
        reasons: list[str] = []
        if claimed_fragment_id is not None:
            if not self.exists(claimed_fragment_id):
                reasons.append("FRAGMENT_ID_NOT_FOUND")
            elif not self.contains_quote(claimed_fragment_id, quote):
                reasons.append("QUOTE_NOT_IN_CLAIMED_FRAGMENT")
            else:
                span = self._locate(quote, claimed_fragment_id)
                if span is not None:
                    start, end, basis = span
                    return Anchor(claimed_fragment_id, start, end, basis, tuple(reasons))
                reasons.append("QUOTE_NOT_IN_CLAIMED_FRAGMENT")

        matches = [fid for fid in self.fragment_ids if self.contains_quote(fid, quote)]
        if not matches:
            return None
        if len(matches) > 1:
            # AMBIGUOUS_ANCHOR NO es decorativo: quien lo reciba tiene que
            # abstenerse. La misma cita en dos fragmentos puede estar afirmada
            # en uno y negada en el otro, y elegir el primero es elegir a ciegas.
            reasons.append("AMBIGUOUS_ANCHOR")
        if claimed_fragment_id is not None:
            reasons.append("REANCHORED_BY_CONTENT")
        chosen = matches[0]
        span = self._locate(quote, chosen)
        if span is None:
            return None
        start, end, basis = span
        return Anchor(chosen, start, end, basis, tuple(reasons))

    def context_window(self, anchor: "Anchor") -> tuple[str, list[Token], int, int, int]:
        """Texto REAL que rodea al ancla: `(texto, tokens, lo, hi, focus)`.

        Es lo que permite comprobar el SENTIDO de una cita y no solo su
        existencia: la frase del episodio donde cae el ancla (o el fragmento
        entero si el episodio no tiene texto). `focus` es el primer token del
        ancla, para poder mirar solo lo que viene ANTES cuando se busca una
        negacion.
        """
        if self.has_text and anchor.basis == OFFSET_BASIS_EPISODE:
            enclosing = [s for s in self.sentences if s.start <= anchor.start < s.end]
            text = self.text or ""
            if enclosing:
                sentence = enclosing[0]
                lo, hi = sentence.first_token, sentence.last_token + 1
                window_text = text[sentence.start:sentence.end]
            else:
                lo, hi = 0, len(self.tokens)
                window_text = text
            focus = next(
                (t.index for t in self.tokens if lo <= t.index < hi and t.start >= anchor.start),
                hi,
            )
            return window_text, self.tokens, lo, hi, focus
        frag = self.get(anchor.fragment_id)
        literal = frag.literal_text if frag is not None else ""
        tokens = tokenize(literal)
        focus = next((t.index for t in tokens if t.start >= anchor.start), len(tokens))
        return literal, tokens, 0, len(tokens), focus

    def anchor_span(self, start: int, end: int) -> Optional[Anchor]:
        """Ancla un span calculado LOCALMENTE sobre el texto del episodio."""
        covering = self.covering(start, end)
        if not covering:
            return None
        return Anchor(covering[0], start, end, OFFSET_BASIS_EPISODE, ())

    def _locate(self, quote: str, fragment_id: str) -> Optional[tuple[int, int, str]]:
        """Offsets locales de la cita DENTRO del fragmento elegido.

        La busqueda esta acotada al rango `[frag.start, frag.end)` del fragmento
        a proposito. Buscar en el episodio entero devolvia, en silencio, offsets
        que caian en OTRO fragmento: el documento decia estar anclado en A y sus
        offsets apuntaban a B. Si la cita no aparece en el fragmento elegido,
        aqui no se resuelve: se devuelve None y el que llama decide (reanclar o
        rechazar).
        """
        frag = self.get(fragment_id)
        if frag is None:
            return None
        if self.has_text:
            text = self.text or ""
            window = text[frag.start:frag.end]
            idx = window.find(quote)
            if idx >= 0:
                return frag.start + idx, frag.start + idx + len(quote), OFFSET_BASIS_EPISODE
            window_tokens = [
                t for t in self.tokens if t.start >= frag.start and t.end <= frag.end
            ]
            span = self._token_span(window_tokens, quote)
            if span is not None:
                return span[0], span[1], OFFSET_BASIS_EPISODE
            return None
        idx = frag.literal_text.find(quote)
        if idx >= 0:
            return idx, idx + len(quote), OFFSET_BASIS_FRAGMENT
        span = self._token_span(tokenize(frag.literal_text), quote)
        if span is not None:
            return span[0], span[1], OFFSET_BASIS_FRAGMENT
        return None

    @staticmethod
    def _token_span(tokens: Sequence[Token], quote: str) -> Optional[tuple[int, int]]:
        """Busqueda tolerante a acentos/mayusculas, pero SIEMPRE por tokens."""
        needle = phrase_tokens(quote)
        hits = find_phrase(tokens, needle)
        if not hits:
            return None
        first, last = hits[0]
        return tokens[first].start, tokens[last].end
