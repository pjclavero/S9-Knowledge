# -*- coding: utf-8 -*-
"""Adaptador sintactico DESACOPLADO para relaciones (`relation-syntax/v1`).

Este modulo aporta SENALES ESTRUCTURALES (frases, tokens, offsets, sujeto/verbo/
objeto aproximados, negacion, voz pasiva, idioma) que un futuro consenso podra
consumir. Es un ADAPTADOR: define una interfaz publica estable y un proveedor
por defecto LIGERO Y SIN DEPENDENCIAS (heuristico por reglas/regex). Si en el
futuro se conecta spaCy / Stanza / un servicio externo, se implementa OTRO
proveedor con la misma interfaz sin tocar el resto del pipeline.

Garantias (verificadas por los tests):

    * Import SIN efectos secundarios: importar este modulo (o el paquete
      `relations`) NO carga modelos, NO descarga nada y NO abre red.
    * El proveedor por defecto (heuristico) NO tiene dependencias pesadas, NO
      hace red y NO descarga modelos.
    * Un proveedor externo ausente falla de forma CLARA
      (`SyntaxProviderUnavailable`); el modo degradado es explicito y documentado.
    * Offsets de caracter compatibles con el texto original (incluido Unicode:
      acentos y emoji).
    * Salida SERIALIZABLE y DETERMINISTA (to_dict / to_json / from_dict,
      round-trip estable, orden estable).
    * CERO Neo4j, CERO red, CERO escritura, CERO LLM.

Este modulo NO decide relaciones ni consenso: solo describe estructura. La
agregacion es responsabilidad de otro subsistema.
"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

# Version del contrato de salida sintactica. Cada `SyntaxAnalysis` la expone.
SYNTAX_VERSION = "relation-syntax-1.0.0"

# Idiomas para los que el proveedor heuristico aplica reglas especificas
# (negacion, voz pasiva, SVO). Cualquier otro idioma corre en MODO DEGRADADO:
# solo segmentacion de frases + tokenizacion + offsets (language-agnostic),
# sin senales linguisticas. El modo degradado se marca en `SyntaxAnalysis.degraded`.
SUPPORTED_LANGUAGES: tuple[str, ...] = ("es", "en")

# Etiqueta de dependencia sintactica (subconjunto reducido y estable, inspirado
# en Universal Dependencies pero deliberadamente pequeno para un heuristico).
DEP_ROOT = "root"
DEP_SUBJECT = "nsubj"
DEP_OBJECT = "obj"
DEP_NEG = "neg"
DEP_AUX_PASS = "aux:pass"
DEP_DEP = "dep"  # dependencia generica / desconocida
DEP_PUNCT = "punct"


# ---------------------------------------------------------------------------
# Errores
# ---------------------------------------------------------------------------
class SyntaxAdapterError(Exception):
    """Error base del adaptador sintactico."""


class SyntaxProviderUnavailable(SyntaxAdapterError):
    """Un proveedor sintactico externo (spaCy/Stanza/servicio) no esta disponible.

    Se lanza de forma CLARA en lugar de degradar silenciosamente: el llamador
    decide si cae al proveedor heuristico o aborta. NUNCA se intenta descargar
    ni instalar nada.
    """


# ---------------------------------------------------------------------------
# Estructuras de datos (inmutables, serializables, deterministas)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SyntaxToken:
    """Un token con offsets sobre el TEXTO ORIGINAL completo.

    `start`/`end` son offsets de caracter [start, end) en el texto de entrada,
    de modo que ``text[start:end] == token.text`` (compatible con Unicode).
    `head` es el indice (global) del token cabeza dentro de la MISMA frase, o el
    propio indice si es raiz. `lemma` y `pos` son opcionales: el proveedor
    heuristico solo rellena POS de clases cerradas (PUNCT/NUM) y deja el resto en
    ``None`` (honesto: no inventa morfologia que no puede calcular sin modelo).
    """

    index: int
    text: str
    start: int
    end: int
    lemma: Optional[str] = None
    pos: Optional[str] = None
    head: Optional[int] = None
    dep: str = DEP_DEP
    is_negation: bool = False

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "lemma": self.lemma,
            "pos": self.pos,
            "head": self.head,
            "dep": self.dep,
            "is_negation": self.is_negation,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SyntaxToken":
        return cls(
            index=data["index"],
            text=data["text"],
            start=data["start"],
            end=data["end"],
            lemma=data.get("lemma"),
            pos=data.get("pos"),
            head=data.get("head"),
            dep=data.get("dep", DEP_DEP),
            is_negation=bool(data.get("is_negation", False)),
        )


@dataclass(frozen=True)
class SyntaxDependency:
    """Arco de dependencia sintactica head -> dependent con etiqueta `relation`.

    Indices GLOBALES de token (los mismos que `SyntaxToken.index`).
    """

    head_index: int
    dependent_index: int
    relation: str

    def to_dict(self) -> dict:
        return {
            "head_index": self.head_index,
            "dependent_index": self.dependent_index,
            "relation": self.relation,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SyntaxDependency":
        return cls(
            head_index=data["head_index"],
            dependent_index=data["dependent_index"],
            relation=data["relation"],
        )


@dataclass(frozen=True)
class SyntaxSentence:
    """Una frase con sus tokens, dependencias y senales estructurales.

    `start`/`end` acotan la frase en el texto original. `subject_index`,
    `main_verb_index` y `object_index` son indices GLOBALES de token (o ``None``
    si no se detectan; p.ej. sujeto omitido / pro-drop). `negated` y `passive`
    son heuristicos por idioma.
    """

    index: int
    text: str
    start: int
    end: int
    tokens: tuple = ()
    dependencies: tuple = ()
    subject_index: Optional[int] = None
    main_verb_index: Optional[int] = None
    object_index: Optional[int] = None
    negated: bool = False
    passive: bool = False

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "tokens": [t.to_dict() for t in self.tokens],
            "dependencies": [d.to_dict() for d in self.dependencies],
            "subject_index": self.subject_index,
            "main_verb_index": self.main_verb_index,
            "object_index": self.object_index,
            "negated": self.negated,
            "passive": self.passive,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SyntaxSentence":
        return cls(
            index=data["index"],
            text=data["text"],
            start=data["start"],
            end=data["end"],
            tokens=tuple(SyntaxToken.from_dict(t) for t in data.get("tokens", [])),
            dependencies=tuple(
                SyntaxDependency.from_dict(d) for d in data.get("dependencies", [])
            ),
            subject_index=data.get("subject_index"),
            main_verb_index=data.get("main_verb_index"),
            object_index=data.get("object_index"),
            negated=bool(data.get("negated", False)),
            passive=bool(data.get("passive", False)),
        )


@dataclass(frozen=True)
class SyntaxAnalysis:
    """Resultado completo del analisis sintactico de un texto.

    `quality` es una confianza heuristica en [0, 1]: 0.0 para texto vacio, valor
    reducido en modo degradado, mayor cuando se detecta estructura verbal. NO es
    una probabilidad calibrada, solo una senal ordinal determinista.
    """

    text: str
    language: str
    provider: str
    version: str
    sentences: tuple = ()
    degraded: bool = False
    quality: float = 0.0
    notes: tuple = ()

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "language": self.language,
            "provider": self.provider,
            "version": self.version,
            "sentences": [s.to_dict() for s in self.sentences],
            "degraded": self.degraded,
            "quality": self.quality,
            "notes": list(self.notes),
        }

    def to_json(self) -> str:
        """JSON determinista: claves ordenadas, separadores estables, UTF-8."""
        return json.dumps(
            self.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )

    @classmethod
    def from_dict(cls, data: dict) -> "SyntaxAnalysis":
        if not isinstance(data, dict):
            raise SyntaxAdapterError("from_dict espera un dict")
        return cls(
            text=data["text"],
            language=data["language"],
            provider=data["provider"],
            version=data["version"],
            sentences=tuple(
                SyntaxSentence.from_dict(s) for s in data.get("sentences", [])
            ),
            degraded=bool(data.get("degraded", False)),
            quality=data.get("quality", 0.0),
            notes=tuple(data.get("notes", [])),
        )

    @classmethod
    def from_json(cls, raw: str) -> "SyntaxAnalysis":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SyntaxAdapterError(f"JSON invalido: {exc}") from exc
        return cls.from_dict(data)


# ---------------------------------------------------------------------------
# Interfaz publica (protocolo/ABC) que todo proveedor debe cumplir
# ---------------------------------------------------------------------------
class SyntaxAnalyzer(ABC):
    """Interfaz estable de un proveedor de analisis sintactico.

    Contrato: `analyze` es PURO respecto al exterior (sin red, sin escritura,
    sin descarga) y determinista para una misma entrada. Un proveedor puede
    declararse no disponible via `available()`; en ese caso `analyze` debe
    lanzar `SyntaxProviderUnavailable`.
    """

    #: Nombre estable del proveedor (aparece en `SyntaxAnalysis.provider`).
    name: str = "abstract"

    def available(self) -> bool:
        """Devuelve True si el proveedor puede ejecutarse aqui y ahora."""
        return True

    @abstractmethod
    def analyze(self, text: str, *, language: Optional[str] = None) -> SyntaxAnalysis:
        """Analiza `text` y devuelve un `SyntaxAnalysis`.

        `language` es un hint ISO-639-1 opcional ("es"/"en"); si es ``None`` el
        proveedor puede autodetectarlo. Idiomas fuera de `SUPPORTED_LANGUAGES`
        se procesan en modo degradado (marcado en la salida), no fallan.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Reglas heuristicas (sin dependencias, sin datos externos, sin red)
# ---------------------------------------------------------------------------
# Terminadores de frase. Se conservan como parte de la frase para no perder
# offsets. `...` cuenta como un unico terminador logico via colapso.
_SENTENCE_TERMINATORS = frozenset(".!?…")  # U+2026 = HORIZONTAL ELLIPSIS

# Tokenizacion Unicode-aware: secuencias de "palabra" (letras/digitos/_) o un
# unico caracter no-espacio (puntuacion, simbolos, emoji). Preserva offsets.
_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)

# Marcadores de negacion por idioma (forma en minusculas).
_NEGATION_MARKERS = {
    "es": frozenset(
        {"no", "ni", "nunca", "jamas", "tampoco", "nada", "nadie",
         "ninguno", "ninguna", "ningun", "sin"}
    ),
    "en": frozenset(
        {"not", "no", "never", "none", "nobody", "nothing", "without",
         "neither", "nor", "n't"}
    ),
}

# Determinantes / preposiciones / conectores a saltar al buscar sujeto y objeto.
_FUNCTION_WORDS = {
    "es": frozenset(
        {"el", "la", "los", "las", "un", "una", "unos", "unas", "lo", "de",
         "del", "a", "al", "en", "con", "por", "para", "y", "e", "o", "u",
         "que", "se", "su", "sus", "le", "les"}
    ),
    "en": frozenset(
        {"the", "a", "an", "of", "to", "in", "on", "at", "with", "by", "for",
         "and", "or", "that", "his", "her", "its", "their"}
    ),
}

# Verbos frecuentes / copulas reconocidos por el heuristico (curados, en
# minusculas). El heuristico NO intenta cubrir toda la morfologia verbal: un
# proveedor con modelo (spaCy/Stanza) lo hara mejor. Ver README_syntax.md.
_COMMON_VERBS = {
    "es": frozenset(
        {"es", "son", "era", "eran", "fue", "fueron", "sera", "seran", "ser",
         "sido", "siendo", "esta", "estan", "estaba", "estaban", "estar",
         "tiene", "tienen", "tenia", "tener", "ama", "amaba", "amo", "amar",
         "mata", "mato", "matar", "ataca", "ataco", "atacar", "conoce",
         "conocio", "conocer", "vive", "viven", "vivir", "da", "dan", "dio",
         "dar", "hace", "hizo", "hacer", "va", "van", "ir", "lidera", "liderar",
         "gobierna", "gobernar", "protege", "protegio", "proteger", "traiciona",
         "traiciono", "traicionar", "destruye", "destruyo", "destruir", "crea",
         "creo", "crear", "escribe", "escribio", "escribir", "lee", "leyo",
         "leer", "dice", "dijo", "decir", "habla", "hablo", "hablar", "sigue",
         "siguio", "seguir", "derrota", "derroto", "derrotar", "salva",
         "salvo", "salvar"}
    ),
    "en": frozenset(
        {"is", "are", "was", "were", "be", "been", "being", "am", "has",
         "have", "had", "loves", "love", "loved", "kills", "kill", "killed",
         "attacks", "attack", "attacked", "knows", "know", "knew", "lives",
         "live", "lived", "gives", "give", "gave", "makes", "make", "made",
         "goes", "go", "went", "leads", "lead", "led", "governs", "govern",
         "protects", "protect", "protected", "betrays", "betray", "betrayed",
         "destroys", "destroy", "destroyed", "writes", "write", "wrote",
         "reads", "read", "sees", "see", "saw", "says", "say", "said",
         "rules", "rule", "ruled", "defeats", "defeat", "defeated", "saves",
         "save", "saved", "follows", "follow", "followed"}
    ),
}

# Auxiliares de voz pasiva por idioma.
_PASSIVE_AUX = {
    "es": frozenset(
        {"es", "son", "fue", "fueron", "era", "eran", "sera", "seran", "fui",
         "fuiste", "fuimos", "sido", "siendo", "esta", "estan", "estaba",
         "estaban"}
    ),
    "en": frozenset(
        {"is", "are", "was", "were", "be", "been", "being", "am"}
    ),
}

# Participios irregulares frecuentes usados por el heuristico de pasiva.
_IRREGULAR_PARTICIPLES = {
    "es": frozenset(
        {"escrito", "hecho", "dicho", "muerto", "roto", "visto", "puesto",
         "abierto", "cubierto", "resuelto", "vuelto"}
    ),
    "en": frozenset(
        {"written", "made", "done", "said", "given", "known", "seen", "led",
         "built", "broken", "taken", "gone", "found", "won", "lost", "sold",
         "told", "held", "kept", "left", "sent", "spent", "read"}
    ),
}

# Sufijos de participio regular (para deteccion de pasiva).
_PARTICIPLE_SUFFIX = {
    "es": ("ado", "ada", "ados", "adas", "ido", "ida", "idos", "idas"),
    "en": ("ed",),
}


def _looks_like_participle(word: str, language: str) -> bool:
    w = word.lower()
    if w in _IRREGULAR_PARTICIPLES.get(language, frozenset()):
        return True
    for suf in _PARTICIPLE_SUFFIX.get(language, ()):  # pragma: no branch
        if w.endswith(suf) and len(w) > len(suf) + 1:
            return True
    return False


def _segment_sentences(text: str) -> list[tuple[int, int]]:
    """Devuelve spans [start, end) de frases preservando offsets originales.

    Segmentacion por terminadores (. ! ? ...). Corridas consecutivas de
    terminadores se colapsan en un unico limite. El espacio inicial se descarta
    del span; el terminador final se conserva dentro del span.
    """
    spans: list[tuple[int, int]] = []
    n = len(text)
    i = 0
    start: Optional[int] = None
    while i < n:
        ch = text[i]
        if start is None and not ch.isspace():
            start = i
        if ch in _SENTENCE_TERMINATORS:
            j = i + 1
            while j < n and text[j] in _SENTENCE_TERMINATORS:
                j += 1
            if start is not None:
                spans.append((start, j))
                start = None
            i = j
            continue
        i += 1
    if start is not None:
        # Frase final sin terminador: recorta espacios de cola.
        end = n
        while end > start and text[end - 1].isspace():
            end -= 1
        if end > start:
            spans.append((start, end))
    return spans


def _is_word(token_text: str) -> bool:
    """True si el token es una 'palabra' alfanumerica (no pura puntuacion)."""
    if not token_text:
        return False
    first = token_text[0]
    return first.isalnum() or first == "_"


def _autodetect_language(word_tokens: Sequence[str]) -> str:
    """Autodeteccion barata por solapamiento de palabras funcion/negacion.

    Determinista. Sin datos externos. Empata a favor de 'es' (proyecto S9 es
    mayoritariamente espanol).
    """
    lowered = [w.lower() for w in word_tokens]
    scores = {}
    for lang in SUPPORTED_LANGUAGES:
        markers = _FUNCTION_WORDS[lang] | _NEGATION_MARKERS[lang] | _COMMON_VERBS[lang]
        scores[lang] = sum(1 for w in lowered if w in markers)
    best = max(SUPPORTED_LANGUAGES, key=lambda lang: (scores[lang], lang == "es"))
    return best


# ---------------------------------------------------------------------------
# Proveedor por defecto: heuristico, SIN dependencias
# ---------------------------------------------------------------------------
class HeuristicSyntaxAnalyzer(SyntaxAnalyzer):
    """Proveedor por defecto: reglas + regex, sin dependencias ni red.

    Segmenta frases, tokeniza (Unicode-aware con offsets), detecta negacion y
    voz pasiva por marcadores, y aproxima Sujeto-Verbo-Objeto. Todo es
    heuristico y best-effort; se documenta como tal en README_syntax.md. Un
    idioma no soportado corre en modo degradado (solo frases+tokens+offsets).
    """

    name = "heuristic"

    def available(self) -> bool:
        # Siempre disponible: no depende de nada externo.
        return True

    def analyze(self, text: str, *, language: Optional[str] = None) -> SyntaxAnalysis:
        if not isinstance(text, str):
            raise SyntaxAdapterError("text debe ser str")

        notes: list[str] = []

        # Tokenizacion global previa (solo para autodeteccion de idioma).
        all_words = [m.group(0) for m in _TOKEN_RE.finditer(text) if _is_word(m.group(0))]

        if language is None:
            lang = _autodetect_language(all_words) if all_words else "es"
            if not all_words:
                notes.append("texto vacio: idioma por defecto 'es'")
        else:
            lang = language

        degraded = lang not in SUPPORTED_LANGUAGES
        if degraded:
            notes.append(
                f"idioma '{lang}' no soportado: modo degradado "
                f"(solo frases/tokens/offsets, sin negacion/pasiva/SVO)"
            )

        sentences: list[SyntaxSentence] = []
        global_token_index = 0
        for s_idx, (s_start, s_end) in enumerate(_segment_sentences(text)):
            sent_text = text[s_start:s_end]
            sentence, global_token_index = self._analyze_sentence(
                sent_text, s_start, s_idx, global_token_index, lang, degraded
            )
            sentences.append(sentence)

        quality = self._quality(sentences, degraded, bool(all_words))

        return SyntaxAnalysis(
            text=text,
            language=lang,
            provider=self.name,
            version=SYNTAX_VERSION,
            sentences=tuple(sentences),
            degraded=degraded,
            quality=quality,
            notes=tuple(notes),
        )

    # -- interno -----------------------------------------------------------
    def _analyze_sentence(self, sent_text, s_start, s_idx, start_index, lang, degraded):
        tokens: list[SyntaxToken] = []
        idx = start_index
        neg_markers = _NEGATION_MARKERS.get(lang, frozenset())

        for m in _TOKEN_RE.finditer(sent_text):
            tok_text = m.group(0)
            g_start = s_start + m.start()
            g_end = s_start + m.end()
            is_word = _is_word(tok_text)
            if is_word:
                pos = "NUM" if tok_text.isdigit() else None
                dep = DEP_DEP
            else:
                pos = "PUNCT"
                dep = DEP_PUNCT
            is_neg = (not degraded) and is_word and tok_text.lower() in neg_markers
            if is_neg:
                dep = DEP_NEG
            tokens.append(
                SyntaxToken(
                    index=idx,
                    text=tok_text,
                    start=g_start,
                    end=g_end,
                    lemma=None,
                    pos=pos,
                    head=None,
                    dep=dep,
                    is_negation=is_neg,
                )
            )
            idx += 1

        negated = any(t.is_negation for t in tokens)
        subject_index = main_verb_index = object_index = None
        passive = False

        if not degraded:
            subject_index, main_verb_index, object_index = self._svo(tokens, lang)
            passive = self._passive(tokens, lang)

        dependencies, tokens = self._build_dependencies(
            tokens, subject_index, main_verb_index, object_index
        )

        sentence = SyntaxSentence(
            index=s_idx,
            text=sent_text,
            start=s_start,
            end=s_start + len(sent_text),
            tokens=tuple(tokens),
            dependencies=tuple(dependencies),
            subject_index=subject_index,
            main_verb_index=main_verb_index,
            object_index=object_index,
            negated=negated,
            passive=passive,
        )
        return sentence, idx

    def _svo(self, tokens, lang):
        """Aproxima (sujeto, verbo, objeto) con indices GLOBALES o None."""
        verbs = _COMMON_VERBS.get(lang, frozenset())
        func = _FUNCTION_WORDS.get(lang, frozenset())
        neg = _NEGATION_MARKERS.get(lang, frozenset())

        word_toks = [t for t in tokens if _is_word(t.text)]
        if not word_toks:
            return None, None, None

        # Verbo principal: primer verbo conocido que tenga alguna palabra antes
        # (para permitir sujeto). Si el primer verbo es el primer token, se
        # asume sujeto omitido (pro-drop) y se acepta igualmente.
        main_verb = None
        verb_pos_in_words = None
        for wi, t in enumerate(word_toks):
            if t.text.lower() in verbs:
                main_verb = t.index
                verb_pos_in_words = wi
                break
        if main_verb is None:
            return None, None, None

        # Sujeto: ultima palabra de contenido antes del verbo.
        subject = None
        for t in reversed(word_toks[:verb_pos_in_words]):
            lw = t.text.lower()
            if lw in func or lw in neg or lw in verbs:
                continue
            subject = t.index
            break

        # Objeto: primera palabra de contenido despues del verbo.
        obj = None
        for t in word_toks[verb_pos_in_words + 1:]:
            lw = t.text.lower()
            if lw in func or lw in neg or lw in verbs:
                continue
            obj = t.index
            break

        return subject, main_verb, obj

    def _passive(self, tokens, lang):
        """Heuristica de voz pasiva: AUX (ser/be...) + participio en <=4 palabras."""
        aux_set = _PASSIVE_AUX.get(lang, frozenset())
        word_toks = [t for t in tokens if _is_word(t.text)]
        for wi, t in enumerate(word_toks):
            if t.text.lower() in aux_set:
                for follow in word_toks[wi + 1: wi + 5]:
                    if _looks_like_participle(follow.text, lang):
                        return True
        return False

    def _build_dependencies(self, tokens, subject_index, main_verb_index, object_index):
        """Construye arcos y fija `head`/`dep` de tokens de forma determinista.

        Modelo minimo: el verbo principal es raiz; sujeto/objeto/negacion cuelgan
        de el. El resto cuelga del verbo (o de si mismo si no hay verbo). Devuelve
        (dependencias, tokens_actualizados).
        """
        by_index = {t.index: t for t in tokens}
        deps: list[SyntaxDependency] = []
        updated: dict[int, SyntaxToken] = {}

        root = main_verb_index

        for t in tokens:
            if t.index == root:
                head = t.index
                dep = DEP_ROOT
            elif root is not None and t.index == subject_index:
                head, dep = root, DEP_SUBJECT
            elif root is not None and t.index == object_index:
                head, dep = root, DEP_OBJECT
            elif t.is_negation:
                head = root if root is not None else t.index
                dep = DEP_NEG
            elif t.dep == DEP_PUNCT:
                head = root if root is not None else t.index
                dep = DEP_PUNCT
            else:
                head = root if root is not None else t.index
                dep = DEP_DEP
            updated[t.index] = SyntaxToken(
                index=t.index,
                text=t.text,
                start=t.start,
                end=t.end,
                lemma=t.lemma,
                pos=t.pos,
                head=head,
                dep=dep,
                is_negation=t.is_negation,
            )
            if head != t.index:
                deps.append(SyntaxDependency(head_index=head, dependent_index=t.index, relation=dep))

        # Orden determinista de arcos: por dependiente.
        deps.sort(key=lambda d: d.dependent_index)
        ordered_tokens = [updated[t.index] for t in tokens]
        return deps, ordered_tokens

    def _quality(self, sentences, degraded, has_words):
        if not has_words:
            return 0.0
        if degraded:
            return 0.2
        with_verb = sum(1 for s in sentences if s.main_verb_index is not None)
        if not sentences:
            return 0.1
        ratio = with_verb / len(sentences)
        # Base 0.4 por tener frases+tokens en idioma soportado, + hasta 0.5 por
        # cobertura verbal. Redondeo estable.
        return round(0.4 + 0.5 * ratio, 4)


# ---------------------------------------------------------------------------
# Proveedor nulo: estructura vacia, util como fallback explicito
# ---------------------------------------------------------------------------
class NullSyntaxAnalyzer(SyntaxAnalyzer):
    """Proveedor que no analiza nada (devuelve estructura vacia coherente).

    Util como fallback EXPLICITO cuando se quiere desactivar el analisis sin
    romper el contrato de salida.
    """

    name = "null"

    def analyze(self, text: str, *, language: Optional[str] = None) -> SyntaxAnalysis:
        if not isinstance(text, str):
            raise SyntaxAdapterError("text debe ser str")
        lang = language if language else "und"
        return SyntaxAnalysis(
            text=text,
            language=lang,
            provider=self.name,
            version=SYNTAX_VERSION,
            sentences=(),
            degraded=True,
            quality=0.0,
            notes=("proveedor null: sin analisis",),
        )


# ---------------------------------------------------------------------------
# Proveedores externos (spaCy/Stanza): NO implementados / NOT_EXECUTED
# ---------------------------------------------------------------------------
class ExternalModelSyntaxAnalyzer(SyntaxAnalyzer):
    """Placeholder para un proveedor con modelo (spaCy/Stanza/servicio).

    NO esta implementado deliberadamente: anadir esas dependencias esta FUERA de
    alcance de esta tarea (no se tocan requirements). `available()` es False y
    `analyze()` lanza `SyntaxProviderUnavailable` con un mensaje CLARO. Cuando se
    decida integrarlo, se subclasa esta interfaz sin cambiar el resto del
    pipeline. Ver README_syntax.md (seccion "Proveedores pesados").
    """

    def __init__(self, engine: str = "spacy"):
        self.engine = engine
        self.name = f"external:{engine}"

    def available(self) -> bool:
        return False

    def analyze(self, text: str, *, language: Optional[str] = None) -> SyntaxAnalysis:
        raise SyntaxProviderUnavailable(
            f"proveedor externo '{self.engine}' no disponible: dependencia no "
            f"instalada y NO se descarga nada. Use el proveedor 'heuristic' o "
            f"integre '{self.engine}' de forma explicita (ver README_syntax.md)."
        )


# ---------------------------------------------------------------------------
# Fabrica y ayudas de alto nivel
# ---------------------------------------------------------------------------
_BUILTIN_PROVIDERS = {
    "heuristic": HeuristicSyntaxAnalyzer,
    "null": NullSyntaxAnalyzer,
}

# Proveedores que requieren dependencias/modelos pesados (no instalados aqui).
_EXTERNAL_PROVIDERS = ("spacy", "stanza")


def get_analyzer(provider: str = "heuristic", **kwargs: Any) -> SyntaxAnalyzer:
    """Devuelve un proveedor por nombre.

    - "heuristic" (por defecto): sin dependencias, siempre disponible.
    - "null": estructura vacia.
    - "spacy" / "stanza": NO disponibles aqui -> `SyntaxProviderUnavailable`
      (fallo CLARO, nunca descarga ni instala).
    """
    if provider in _BUILTIN_PROVIDERS:
        return _BUILTIN_PROVIDERS[provider](**kwargs)
    if provider in _EXTERNAL_PROVIDERS:
        raise SyntaxProviderUnavailable(
            f"proveedor '{provider}' requiere una dependencia pesada no "
            f"instalada; no se descarga nada. Proveedores disponibles: "
            f"{sorted(_BUILTIN_PROVIDERS)}."
        )
    raise SyntaxAdapterError(
        f"proveedor desconocido '{provider}'. Disponibles: "
        f"{sorted(_BUILTIN_PROVIDERS)}; externos (no instalados): "
        f"{list(_EXTERNAL_PROVIDERS)}."
    )


def analyze(text: str, *, provider: str = "heuristic", language: Optional[str] = None) -> SyntaxAnalysis:
    """Atajo: obtiene el proveedor y analiza. Sin efectos secundarios."""
    return get_analyzer(provider).analyze(text, language=language)


def safe_analyze(
    analyzer: SyntaxAnalyzer, text: str, *, language: Optional[str] = None
) -> SyntaxAnalysis:
    """Ejecuta `analyzer.analyze` AISLANDO cualquier fallo del proveedor.

    Si el proveedor no esta disponible o lanza una excepcion, NO propaga: emite
    un `SyntaxAnalysis` degradado y coherente que registra el error en `notes`.
    Util para no dejar caer el pipeline por un proveedor roto. El proveedor
    heuristico por defecto no deberia necesitar esta red de seguridad.
    """
    try:
        return analyzer.analyze(text, language=language)
    except Exception as exc:  # aislamiento deliberado del proveedor
        name = getattr(analyzer, "name", "unknown")
        return SyntaxAnalysis(
            text=text if isinstance(text, str) else "",
            language=language if language else "und",
            provider=name,
            version=SYNTAX_VERSION,
            sentences=(),
            degraded=True,
            quality=0.0,
            notes=(f"proveedor '{name}' fallo aislado: {type(exc).__name__}: {exc}",),
        )


__all__ = [
    "SYNTAX_VERSION",
    "SUPPORTED_LANGUAGES",
    "SyntaxAdapterError",
    "SyntaxProviderUnavailable",
    "SyntaxToken",
    "SyntaxDependency",
    "SyntaxSentence",
    "SyntaxAnalysis",
    "SyntaxAnalyzer",
    "HeuristicSyntaxAnalyzer",
    "NullSyntaxAnalyzer",
    "ExternalModelSyntaxAnalyzer",
    "get_analyzer",
    "analyze",
    "safe_analyze",
]
