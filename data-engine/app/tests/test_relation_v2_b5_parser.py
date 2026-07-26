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
    FALLBACK_NOTE_PREFIX,
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


# --------------------------------------------------------------------------
# 8. Correccion supervisada tras la auditoria del revisor de B5
#    (defectos D1/D2/D3/D6 y mutantes supervivientes M6/M12/M13/M14)
# --------------------------------------------------------------------------
def test_pereza_con_libreria_PRESENTE_m6(tmp_path, monkeypatch):
    """M6: `available()` debe consultar, NO importar, aunque la libreria EXISTA.

    Los tests de pereza que solo comprueban `"spacy" not in sys.modules` son
    vacuos en un entorno sin spaCy. Aqui se FABRICA un paquete instalable de
    mentira que explota si se importa, y se comprueba que `available()` devuelve
    True sin llegar a ejecutarlo.
    """
    paquete = tmp_path / "spacy"
    paquete.mkdir()
    (paquete / "__init__.py").write_text(
        "raise AssertionError('la libreria pesada NO debe importarse')",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    import importlib

    importlib.invalidate_caches()
    monkeypatch.delitem(sys.modules, "spacy", raising=False)

    an = LazyModelSyntaxAnalyzer("spacy")
    assert an.available() is True, "find_spec debe VER el paquete"
    assert "spacy" not in sys.modules, "available() NO debe importar la libreria"


def test_fallback_available_refleja_al_de_respaldo_m12():
    """M12: `available()` del fallback no puede ser True incondicional."""

    class NuncaDisponible(HeuristicSyntaxAnalyzer):
        name = "nunca"

        def available(self) -> bool:
            return False

    an = FallbackSyntaxAnalyzer(LazyModelSyntaxAnalyzer("spacy"), NuncaDisponible())
    assert an.available() is False
    ok = FallbackSyntaxAnalyzer(LazyModelSyntaxAnalyzer("spacy"))
    assert ok.available() is True


def test_get_analyzer_cache_true_envuelve_m13():
    """M13: la opcion publica `cache=True` debe envolver de verdad."""
    assert isinstance(get_analyzer("heuristic", cache=True), CachingSyntaxAnalyzer)
    assert not isinstance(get_analyzer("heuristic"), CachingSyntaxAnalyzer)
    an = get_analyzer("spacy", fallback=True, cache=True)
    assert isinstance(an, CachingSyntaxAnalyzer)
    an.analyze(TEXTO)
    an.analyze(TEXTO)
    assert an.hits == 1


def test_auditoria_ast_caza_red_ofuscada_m14():
    """M14: la lista negra de nombres no basta; se audita tambien el import dinamico.

    `importlib.import_module` solo puede llamarse con un literal de una lista
    blanca. Asi, partir la cadena ('url'+'open') deja de ser una via de escape.
    """
    import ast

    arbol = ast.parse((APP / "relations" / "syntax.py").read_text(encoding="utf-8"))
    permitidos = {"spacy", "stanza", "importlib.util"}
    dinamicos = [
        n
        for n in ast.walk(arbol)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "import_module"
    ]
    for call in dinamicos:
        assert call.args, "import_module sin argumento"
        arg = call.args[0]
        assert isinstance(arg, ast.Constant) and isinstance(arg.value, str), (
            "import_module debe recibir un literal de cadena, no una expresion "
            "(evita ofuscar 'url'+'open')"
        )
        assert arg.value in permitidos, f"modulo dinamico no permitido: {arg.value}"
    # `getattr` dinamico sobre un modulo es la otra via de ofuscacion.
    for n in ast.walk(arbol):
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "getattr":
            arg = n.args[1] if len(n.args) > 1 else None
            assert isinstance(arg, ast.Constant), (
                "getattr con nombre calculado: posible ofuscacion de red"
            )


def test_fallback_marca_degradacion_en_campo_estructurado_d1():
    """D1: una corrida caida al fallback NO puede parecer una corrida sana."""

    class Roto(HeuristicSyntaxAnalyzer):
        name = "roto"

        def available(self) -> bool:
            return True

        def analyze(self, text, *, language=None):
            raise RuntimeError("modelo corrupto")

    sano = HeuristicSyntaxAnalyzer().analyze(TEXTO)
    assert sano.degraded is False

    an = FallbackSyntaxAnalyzer(Roto())
    degradado = an.analyze(TEXTO)
    assert degradado.degraded is True, "la degradacion debe ser legible por maquina"
    assert an.degradations == 1
    assert "modelo corrupto" in (an.last_error or "")
    assert any(n.startswith(FALLBACK_NOTE_PREFIX) for n in degradado.notes)


def test_fallback_no_se_traga_memoryerror_d1():
    """D1: un OOM no es 'proveedor roto'; degradar en silencio lo ocultaria."""

    class SinMemoria(HeuristicSyntaxAnalyzer):
        name = "oom"

        def available(self) -> bool:
            return True

        def analyze(self, text, *, language=None):
            raise MemoryError("sin memoria")

    with pytest.raises(MemoryError):
        FallbackSyntaxAnalyzer(SinMemoria()).analyze(TEXTO)


def test_cache_desaloja_lru_de_verdad_d2():
    """D2: politica LRU real; solo-insercion congelaria el cache para siempre."""
    an = CachingSyntaxAnalyzer(HeuristicSyntaxAnalyzer(), maxsize=2)
    an.analyze("uno")
    an.analyze("dos")
    an.analyze("tres")  # desaloja "uno" (el menos usado recientemente)
    assert an.evictions == 1
    assert len(an._cache) == 2
    an.analyze("uno")  # era el desalojado -> miss
    assert an.hits == 0
    # "tres" sigue vivo: acierto.
    an.analyze("tres")
    assert an.hits == 1


def test_cache_lru_renueva_con_el_uso_d2():
    """Un acierto renueva la entrada: lo caliente no se desaloja antes que lo frio."""
    an = CachingSyntaxAnalyzer(HeuristicSyntaxAnalyzer(), maxsize=2)
    an.analyze("viejo")
    an.analyze("nuevo")
    an.analyze("viejo")  # hit -> "viejo" pasa a ser el mas reciente
    an.analyze("tercero")  # debe desalojar "nuevo", no "viejo"
    assert an.analyze("viejo") is not None and an.hits == 2
    assert ("nuevo", None) not in an._cache


def test_cache_maxsize_invalido_es_error():
    with pytest.raises(SyntaxAdapterError):
        CachingSyntaxAnalyzer(HeuristicSyntaxAnalyzer(), maxsize=0)


def test_cache_clear_reinicia_desalojos():
    an = CachingSyntaxAnalyzer(HeuristicSyntaxAnalyzer(), maxsize=1)
    an.analyze("a")
    an.analyze("b")
    assert an.evictions == 1
    an.cache_clear()
    assert an.evictions == 0
