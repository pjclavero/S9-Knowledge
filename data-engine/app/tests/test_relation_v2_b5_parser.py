"""Bloque 5 — parser sintactico opcional (spaCy/Stanza) tras interfaz.

Lo que se garantiza aqui:

  * El proveedor fuerte es OPCIONAL y PEREZOSO: no se importa la libreria pesada
    al cargar el modulo, y si no esta instalada el fallo es CLARO.
  * NUNCA se descarga ni se instala nada (sin red, sin auto-download).
  * Existe un FALLBACK SEGURO al heuristico, con la procedencia trazada.
  * El CACHE garantiza un unico analisis por segmento y no altera el resultado.
  * El DEFAULT sigue siendo el heuristico: metric-neutral respecto a la base.

spaCy/Stanza NO estan instalados en este entorno: la ruta de conversion real
solo se ejercita con `skipif`. No se afirma ninguna mejora de calidad medida.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from relations.syntax import (  # noqa: E402
    CachingSyntaxAnalyzer,
    FallbackSyntaxAnalyzer,
    HeuristicSyntaxAnalyzer,
    LazyModelSyntaxAnalyzer,
    SyntaxAdapterError,
    SyntaxAnalysis,
    SyntaxProviderUnavailable,
    get_analyzer,
    get_default_analyzer,
)

TEXTO = "Aragorn viajo a Gondor con Boromir y defendio la ciudad."

HAS_SPACY = importlib.util.find_spec("spacy") is not None
HAS_STANZA = importlib.util.find_spec("stanza") is not None


# --------------------------------------------------------------------------
# 1. Pereza real: la libreria pesada no se importa al cargar el modulo
# --------------------------------------------------------------------------
def test_importar_syntax_no_importa_spacy_ni_stanza():
    """El modulo se carga sin arrastrar spaCy/Stanza a sys.modules."""
    import relations.syntax  # noqa: F401  (ya importado arriba)

    assert "spacy" not in sys.modules
    assert "stanza" not in sys.modules


def test_construir_lazy_no_importa_la_libreria():
    """Instanciar el proveedor tampoco importa nada pesado."""
    LazyModelSyntaxAnalyzer("spacy")
    LazyModelSyntaxAnalyzer("stanza")
    assert "spacy" not in sys.modules
    assert "stanza" not in sys.modules


def test_available_no_importa_la_libreria():
    """`available()` usa find_spec: consulta sin ejecutar el paquete."""
    LazyModelSyntaxAnalyzer("spacy").available()
    assert "spacy" not in sys.modules


# --------------------------------------------------------------------------
# 2. Motor invalido y contrato de errores
# --------------------------------------------------------------------------
def test_motor_desconocido_es_error_claro():
    with pytest.raises(SyntaxAdapterError):
        LazyModelSyntaxAnalyzer("mi-parser-inventado")


def test_get_analyzer_proveedor_desconocido():
    with pytest.raises(SyntaxAdapterError):
        get_analyzer("no-such-provider")


def test_analyze_texto_no_str_es_error():
    with pytest.raises(SyntaxAdapterError):
        LazyModelSyntaxAnalyzer("spacy").analyze(123)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# 3. Sin dependencia -> fallo CLARO, jamas descarga
# --------------------------------------------------------------------------
@pytest.mark.skipif(HAS_SPACY, reason="spaCy instalado: la ruta de ausencia no aplica")
def test_sin_spacy_el_fallo_es_explicito():
    an = LazyModelSyntaxAnalyzer("spacy")
    assert an.available() is False
    with pytest.raises(SyntaxProviderUnavailable) as exc:
        an.analyze(TEXTO)
    msg = str(exc.value).lower()
    assert "no" in msg and "descarga" in msg


@pytest.mark.skipif(HAS_SPACY, reason="spaCy instalado")
def test_get_analyzer_spacy_sin_fallback_lanza():
    """Contrato historico preservado: sin fallback explicito, falla en claro."""
    with pytest.raises(SyntaxProviderUnavailable):
        get_analyzer("spacy")


@pytest.mark.skipif(HAS_STANZA, reason="Stanza instalado")
def test_get_analyzer_stanza_sin_fallback_lanza():
    with pytest.raises(SyntaxProviderUnavailable):
        get_analyzer("stanza")


def test_codigo_no_contiene_llamadas_de_descarga():
    """Auditoria estatica sobre el AST (no sobre comentarios ni docstrings).

    Ninguna llamada del modulo puede descargar/instalar nada: ni `download(...)`,
    ni subprocess/pip, ni urllib/requests. Ademas, Stanza debe instanciarse con
    la descarga automatica DESACTIVADA (`download_method=None`).
    """
    import ast

    arbol = ast.parse((APP / "relations" / "syntax.py").read_text(encoding="utf-8"))

    prohibidos = {"download", "urlopen", "urlretrieve", "check_call", "run", "system"}
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Call):
            fn = nodo.func
            nombre = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            assert nombre not in prohibidos, f"llamada prohibida: {nombre}"
        if isinstance(nodo, (ast.Import, ast.ImportFrom)):
            mods = (
                [a.name for a in nodo.names]
                if isinstance(nodo, ast.Import)
                else [nodo.module or ""]
            )
            for m in mods:
                raiz = m.split(".")[0]
                assert raiz not in {"subprocess", "pip", "urllib", "requests", "socket"}, (
                    f"import de red/instalacion prohibido: {m}"
                )

    # La instanciacion de Stanza pasa download_method=None (descarga desactivada).
    stanza_calls = [
        n
        for n in ast.walk(arbol)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "Pipeline"
    ]
    assert stanza_calls, "se esperaba la construccion de stanza.Pipeline"
    for call in stanza_calls:
        kw = {k.arg: k.value for k in call.keywords}
        assert "download_method" in kw
        assert isinstance(kw["download_method"], ast.Constant)
        assert kw["download_method"].value is None


# --------------------------------------------------------------------------
# 4. Fallback seguro
# --------------------------------------------------------------------------
def test_fallback_sirve_el_heuristico_cuando_no_hay_primario():
    an = FallbackSyntaxAnalyzer(LazyModelSyntaxAnalyzer("spacy"))
    out = an.analyze(TEXTO)
    assert isinstance(out, SyntaxAnalysis)
    assert out.sentences, "el heuristico debe producir estructura"
    assert an.available() is True


def test_fallback_traza_la_procedencia():
    an = FallbackSyntaxAnalyzer(LazyModelSyntaxAnalyzer("spacy"))
    out = an.analyze(TEXTO)
    notas = " ".join(out.notes).lower()
    if HAS_SPACY:
        assert "spacy" in notas
    else:
        assert "fallback" in notas and "spacy" in notas


def test_fallback_no_propaga_aunque_el_primario_reviente():
    class Roto(HeuristicSyntaxAnalyzer):
        name = "roto"

        def available(self) -> bool:
            return True

        def analyze(self, text, *, language=None):
            raise RuntimeError("boom")

    an = FallbackSyntaxAnalyzer(Roto())
    out = an.analyze(TEXTO)
    assert out.sentences
    assert any("boom" in n for n in out.notes)


def test_get_analyzer_con_fallback_nunca_lanza():
    an = get_analyzer("spacy", fallback=True)
    out = an.analyze(TEXTO)
    assert out.sentences


# --------------------------------------------------------------------------
# 5. Cache: un unico analisis por segmento, sin cambiar el resultado
# --------------------------------------------------------------------------
def test_cache_analiza_una_sola_vez_por_segmento():
    class Contador(HeuristicSyntaxAnalyzer):
        def __init__(self):
            super().__init__()
            self.llamadas = 0

        def analyze(self, text, *, language=None):
            self.llamadas += 1
            return super().analyze(text, language=language)

    inner = Contador()
    an = CachingSyntaxAnalyzer(inner)
    for _ in range(5):
        an.analyze(TEXTO)
    assert inner.llamadas == 1
    assert an.hits == 4 and an.misses == 1


def test_cache_distingue_texto_e_idioma():
    an = CachingSyntaxAnalyzer(HeuristicSyntaxAnalyzer())
    an.analyze(TEXTO, language="es")
    an.analyze(TEXTO, language="en")
    an.analyze("Otro texto distinto.", language="es")
    assert an.misses == 3 and an.hits == 0


def test_cache_devuelve_resultado_identico_al_directo():
    """El cache es metric-neutral: mismo objeto de salida que sin cache."""
    directo = HeuristicSyntaxAnalyzer().analyze(TEXTO)
    cacheado = CachingSyntaxAnalyzer(HeuristicSyntaxAnalyzer()).analyze(TEXTO)
    assert cacheado.to_dict() == directo.to_dict()


def test_cache_respeta_maxsize():
    an = CachingSyntaxAnalyzer(HeuristicSyntaxAnalyzer(), maxsize=2)
    for i in range(5):
        an.analyze(f"Texto numero {i}.")
    assert len(an._cache) <= 2


def test_cache_clear_reinicia_contadores():
    an = CachingSyntaxAnalyzer(HeuristicSyntaxAnalyzer())
    an.analyze(TEXTO)
    an.analyze(TEXTO)
    an.cache_clear()
    assert an.hits == 0 and an.misses == 0 and not an._cache


# --------------------------------------------------------------------------
# 6. Default metric-neutral
# --------------------------------------------------------------------------
def test_default_sigue_siendo_heuristico():
    an = get_analyzer()
    assert isinstance(an, HeuristicSyntaxAnalyzer)


def test_default_analyzer_es_compartido_y_cacheado():
    a = get_default_analyzer()
    b = get_default_analyzer()
    assert a is b
    assert isinstance(a, CachingSyntaxAnalyzer)


def test_default_analyzer_produce_lo_mismo_que_el_heuristico_puro():
    """Invariante de metric-neutralidad del cambio en el pipeline."""
    puro = HeuristicSyntaxAnalyzer().analyze(TEXTO)
    por_defecto = get_default_analyzer().analyze(TEXTO)
    assert por_defecto.to_dict() == puro.to_dict()


def test_pipeline_usa_el_analizador_por_defecto():
    """El pipeline consume el analizador compartido, no uno nuevo por segmento."""
    fuente = (APP / "relations" / "pipeline.py").read_text(encoding="utf-8")
    assert "get_default_analyzer()" in fuente
    assert 'get_analyzer("heuristic")' not in fuente


# --------------------------------------------------------------------------
# 7. Ruta real (solo si la dependencia esta presente); aqui se OMITE
# --------------------------------------------------------------------------
@pytest.mark.skipif(not HAS_SPACY, reason="spaCy no instalado: comparacion diferida")
def test_spacy_real_respeta_el_contrato():  # pragma: no cover
    an = LazyModelSyntaxAnalyzer("spacy")
    out = an.analyze(TEXTO, language="es")
    assert out.provider == "spacy"
    assert out.sentences
    for sent in out.sentences:
        assert out.text[sent.start:sent.end] == sent.text
        for tok in sent.tokens:
            assert out.text[tok.start:tok.end] == tok.text


@pytest.mark.skipif(not HAS_STANZA, reason="Stanza no instalado: comparacion diferida")
def test_stanza_real_respeta_el_contrato():  # pragma: no cover
    an = LazyModelSyntaxAnalyzer("stanza")
    out = an.analyze(TEXTO, language="es")
    assert out.provider == "stanza"
    assert out.sentences
