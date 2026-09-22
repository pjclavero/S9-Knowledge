# -*- coding: utf-8 -*-
"""VERACIDAD DE LA TARJETA DE REVIEW.

    La tarjeta donde el operador toma una decisión debe representar fielmente
    tanto el ESTADO QUE ESTÁ VIENDO como la ACCIÓN QUE REALMENTE REALIZÓ.

Dos defectos de esa misma propiedad, los dos medidos por un operador
recorriendo el producto, los dos reproducidos aquí antes de arreglarse.

DEFECTO 1 — LA TARJETA PINTA «No disponible» PARA UN HECHO NEGADO
=================================================================
`GET /v3/review`, tarjeta de «Daiki Oharu **no** lidera la Casa del Ciervo»:

    Sujeto … · Predicado LEADS · Dirección SUBJECT_TO_OBJECT
    Negación: No disponible          <-- idéntico a un claim afirmativo

y más abajo, EN LA MISMA TARJETA, la prosa del motor: `NEGATED_CLAIM`, «la
frase niega la relación en vez de afirmarla». La tarjeta se contradecía a sí
misma en el recuadro donde se decide.

La causa: la plantilla leía `item.proposal.negation`, clave que el exportador
real NO escribe —el campo se llama `negated`, plano—, así que el
`default("No disponible")` disparaba SIEMPRE, para `true` y para `false`.

Un corte anterior cerró esto en la pantalla de resultado, la de procedencia y
la ficha de entidad, y se dejó JUSTO la pantalla donde la persona decide. Esto
no reabre aquél: es otra superficie, y de hecho eran DOS (ver abajo).

DEFECTO 2 — F-7: EL ACTA AFIRMA UNA CORRECCIÓN QUE EL REVISOR NO HIZO
======================================================================
Pulsar «Aprobar» sin tocar nada grababa en el acta persistida:

    "human_decision": "APPROVE"   junto a   "correction": {"scope": "not_available"}

El campo Alcance viene precargado con `item.proposal.scope`, y el exportador
escribe ahí el literal `not_available`. El navegador lo reenvía —hace lo que
debe— y el servidor lo recogía como corrección del humano. La cadena
`decision_audit`, encadenada por hash, FIRMABA una afirmación falsa sobre lo
que hizo la persona.

LA TERCERA SUPERFICIE, que apareció al inventariar consumidores
================================================================
`/panel/review` (`chassis/review_item.html`) pintaba bajo el rótulo «Negación»
el `negation_kind` —la CLASE de negación, no el signo—. Medido sobre el
paquete del exportador real: `negated=True` con `negation_kind="UNKNOWN"`, que
`review_console_v2._clean` convierte en ausencia. Resultado: «Negación: no
disponible» para el mismo hecho negado, por una causa distinta. El `negated`
correcto ya se calculaba en `row_view` y no llegaba a la pantalla.

Arreglar una tarjeta y dejar la otra habría repetido exactamente lo que pasó
con el corte del signo. Las dos están aquí.

DE DÓNDE SALE EL DATO, que es parte de la medición
===================================================
NADA de `negated=True` inyectado en el objeto del test. El corpus lo produce
la CADENA REAL: bytes -> `KnowledgePipeline` -> `review_export`, sobre frases
de verdad, y lo que llega a la tarjeta es lo que el exportador escribió. Si se
inyectara, esto sólo demostraría que la UI sabe pintar un dato fabricado por el
arnés.

    negated=True   "Daiki Oharu no lidera la Casa del Ciervo."     -> REVIEW
    negated=False  "Dicen que Daiki Oharu lidera la Casa del Ciervo." -> REVIEW

EL TERCER ESTADO ES LA EXCEPCIÓN DECLARADA, y se declara: el exportador actual
hace `claim.get("negated", False)`, así que NUNCA omite el campo. Un paquete
SIN `negated` sólo puede ser uno ESCRITO ANTES de que el campo existiera. Ese
caso se construye copiando un documento real y QUITANDO la clave —una ausencia,
que es justo lo que no se puede fabricar afirmativamente—. Queda dicho que esa
pieza no viene del productor de hoy.

Y EL TECHO, DICHO ENTERO
========================
* Aquí se pide LA PANTALLA (GET del HTML) y se lee EL ACTA PERSISTIDA (desde el
  fichero, releído con `read_history`). No se afirma sobre diccionarios
  intermedios: el defecto 1 era «el dato llega y la plantilla no lo pinta» y el
  defecto 2 era «el formulario manda y el servidor lo cree», y una prueba sobre
  el objeto en memoria habría seguido verde con los dos defectos puestos.
* El writer y Neo4j NO intervienen: el driver que usa la cadena aquí es el que
  ESTALLA si alguien lo toca. Que el signo sobreviva writer -> Neo4j -> lector
  lo mide `test_signo_de_negacion_writer_a_visor_neo4j.py`; un verde aquí no
  sustituye a aquél.
* La app es la real (`app.main` importado, routers y plantillas reales), pero
  el lector se instala por dependencia (`lector_por_dependencia`): esto NO mide
  autorización.
"""
from __future__ import annotations

import html as _html
import json
import re
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.authz.dependencies import get_filtered_provider, get_visibility_scope
from app.authz.scope import UNRESTRICTED
from app.deps import get_provider
from app.labels import (
    NEGACION_AFIRMATIVO,
    NEGACION_NEGADO,
    NEGACION_NO_DISPONIBLE,
    NEGACION_LABELS_ES,
)
from app.routers import v3_review as router_module
from app.services.review_console_v2 import row_view
from app.services.v3_review import ReviewService, read_history

# ---------------------------------------------------------------------------
# EL CORPUS: LA CADENA REAL, NO UN DICCIONARIO A MANO
# ---------------------------------------------------------------------------
_REPO = Path(__file__).resolve().parents[2]
_DE = _REPO / "data-engine"

T_NEGADO = "Daiki Oharu no lidera la Casa del Ciervo."
T_AFIRMATIVO = "Dicen que Daiki Oharu lidera la Casa del Ciervo."


def _cadena_real(source_id: str, texto: str) -> dict:
    """Un documento de revisión producido por la CADENA ENTERA sobre bytes.

    Importa `data-engine` de forma perezosa y DENTRO de la función: el
    `conftest.py` del visor limpia `sys.modules['app.*']` para que `app`
    resuelva al visor, y arrastrar los imports de la cadena al nivel de módulo
    reabriría esa colisión.
    """
    guardado = list(sys.path)
    try:
        for p in (str(_DE / "app"), str(_DE / "app" / "tests"), str(_DE)):
            if p not in sys.path:
                sys.path.insert(0, p)
        from test_knowledge_v3_e2e_fixtures import (
            NOW, WORKSPACE, ExplodingDriver, base_config, gold_dev, snapshot_entities,
        )
        from knowledge_v3.multimodal.base import IngestOptions, SourceInput
        from knowledge_v3.pipeline import KnowledgePipeline
        from knowledge_v3.pipeline.pipeline import SourceCase
        from knowledge_v3.review_export import review_documents

        caso = SourceCase(
            source_id=source_id,
            source=SourceInput(
                data=texto.encode("utf-8"), original_name=f"{source_id}.md",
                original_location=f"mem://{source_id}", mime_type="text/markdown",
                source_kind="MARKDOWN",
            ),
            ingest_options=IngestOptions(
                workspace=WORKSPACE, collection_id="collection:pruebas",
                ingested_at=NOW, created_at=NOW, game_profile="generic",
                language_hint="es",
            ),
        )
        gold = gold_dev()
        # El driver que ESTALLA: si algo de esto tocara Neo4j, fallaría en voz
        # alta en vez de pasar en silencio.
        pipeline = KnowledgePipeline(base_config(gold, writer_driver=ExplodingDriver()))
        resultado = pipeline.run([caso], catalog_entities=snapshot_entities(gold))
        docs = review_documents(resultado, workspace=WORKSPACE)
        assert len(docs) == 1, (
            f"LA CADENA REAL NO PRODUJO UNA (Y SÓLO UNA) PROPUESTA DE REVISIÓN "
            f"para {texto!r}: {len(docs)} documentos. Sin propuesta no hay "
            f"tarjeta que medir, y el corpus de este fichero deja de ser real."
        )
        return docs[0]
    finally:
        sys.path[:] = guardado


@pytest.fixture(scope="module")
def corpus() -> dict[str, dict]:
    """Los tres signos. Dos salen de la cadena; el tercero se declara arriba."""
    negado = _cadena_real("tarjeta-negado", T_NEGADO)
    afirmativo = _cadena_real("tarjeta-afirmativo", T_AFIRMATIVO)

    # CONTROL POSITIVO DE LA PROCEDENCIA. Si el exportador dejara de escribir
    # el signo, o lo escribiera al revés, el corpus de este fichero sería
    # mentira y todo lo de abajo mediría otra cosa. Se comprueba aquí, una vez.
    assert negado["proposal"]["negated"] is True, (
        f"EL CORPUS NO ES LO QUE DICE SER: la cadena real, sobre {T_NEGADO!r}, "
        f"exportó negated={negado['proposal']['negated']!r} en vez de True. "
        f"No es la tarjeta lo que falla: es el dato que llega a ella."
    )
    assert afirmativo["proposal"]["negated"] is False, (
        f"EL CORPUS NO ES LO QUE DICE SER: la cadena real, sobre "
        f"{T_AFIRMATIVO!r}, exportó "
        f"negated={afirmativo['proposal']['negated']!r} en vez de False."
    )
    assert "NEGATED_CLAIM" in negado["engine_decision"]["reason_codes"], (
        "EL CORPUS NO TRAE LA CONTRADICCIÓN QUE SE MIDE: sin `NEGATED_CLAIM` "
        "la tarjeta no contiene la prosa que decía lo contrario que el campo "
        "estructurado, y la pieza B no se puede comprobar."
    )

    # EL TERCER ESTADO. Ausencia REAL de la clave: un paquete escrito antes de
    # que el campo existiera. Se QUITA, no se inventa. Ver el docstring.
    sin_signo = json.loads(json.dumps(negado))
    sin_signo["proposal"].pop("negated")
    sin_signo["source_id"] = "tarjeta-sin-signo"
    sin_signo["episode_id"] = "episode-sin-signo"
    # IDENTIDAD PROPIA. Copiar el documento copia también su `proposal_id`, y
    # dos propuestas con el mismo id son LA MISMA para la cola: una de las dos
    # desaparece de la pantalla y el caso se mediría sobre la otra.
    sin_signo["proposal_id"] = negado["proposal_id"] + ":sin-signo"
    assert "negated" not in sin_signo["proposal"]
    assert sin_signo["proposal_id"] != negado["proposal_id"]

    return {"negado": negado, "afirmativo": afirmativo, "sin_signo": sin_signo}


@pytest.fixture
def consola(tmp_path, corpus, lector_por_dependencia):
    """La app real, servida sobre un almacén con los tres documentos."""
    import app.main  # noqa: F401  (instala `chassis_nav` en el entorno Jinja)

    proposals = tmp_path / "proposals"
    proposals.mkdir()
    for nombre, doc in corpus.items():
        (proposals / f"{nombre}.json").write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8"
        )
    # El fichero de decisiones va FUERA del directorio de propuestas: dentro,
    # Review responde 500 al intentar leerlo como si fuera un paquete.
    decisiones = tmp_path / "actas" / "decisiones.jsonl"
    decisiones.parent.mkdir()

    service = ReviewService(proposals, decisiones)
    original = router_module._service
    router_module._service = lambda: service

    api = FastAPI()
    api.include_router(router_module.router)
    api.dependency_overrides[get_visibility_scope] = lambda: UNRESTRICTED
    api.dependency_overrides[get_filtered_provider] = lambda: get_provider()
    try:
        yield TestClient(api), service, decisiones, corpus["negado"]["workspace"]
    finally:
        router_module._service = original


# ---------------------------------------------------------------------------
# AYUDAS DE LECTURA DEL HTML SERVIDO
# ---------------------------------------------------------------------------
_TARJETA = re.compile(r"<article class=\"v3r-item\".*?</article>", re.S)
_SIGNO = re.compile(r"<dt>Negación</dt>\s*<dd[^>]*data-signo=\"([^\"]*)\"[^>]*>(.*?)</dd>", re.S)


def _tarjetas(html: str) -> list[str]:
    return _TARJETA.findall(html)


def _tarjeta_de(html: str, source_id: str) -> str:
    for tarjeta in _tarjetas(html):
        if source_id in tarjeta:
            return tarjeta
    raise AssertionError(
        f"NO HAY TARJETA PARA {source_id!r} EN LA PANTALLA SERVIDA. "
        f"Las presentes son: "
        f"{[t[:120] for t in _tarjetas(html)] or 'ninguna'}. "
        f"Sin tarjeta no se mide el campo: esto NO es «el campo está mal», es "
        f"«la propuesta no llegó a la cola»."
    )


def _signo_pintado(tarjeta: str) -> tuple[str, str]:
    """`(código, texto)` del campo Negación TAL Y COMO SE SIRVE."""
    m = _SIGNO.search(tarjeta)
    if m is None:
        raise AssertionError(
            "EL CAMPO «Negación» NO APARECE EN LA TARJETA SERVIDA con un "
            "`data-signo`. O la plantilla dejó de publicar el código del signo "
            "(y entonces la pantalla vuelve a ser un texto suelto sin autoridad "
            "detrás), o el rótulo cambió de nombre. Fragmento: "
            + tarjeta[:400]
        )
    return m.group(1), _html.unescape(m.group(2)).strip()


def _formulario_tal_cual(tarjeta: str) -> dict[str, str]:
    """Los campos que el NAVEGADOR enviaría de esta tarjeta SIN TOCAR NADA.

    Se leen del marcado servido, no se escriben a mano: el defecto F-7 vivía
    precisamente en un `value=` precargado, y un formulario inventado por el
    test no lo habría llevado nunca.
    """
    trozo = tarjeta[tarjeta.index('action="/v3/review/decide"'):]
    trozo = trozo[:trozo.index("</form>")]
    datos: dict[str, str] = {}
    for nombre, valor in re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', trozo):
        datos[nombre] = _html.unescape(valor)
    for nombre in re.findall(r'<input[^>]*name="([^"]+)"', trozo):
        datos.setdefault(nombre, "")
    # Un <select> que nadie toca envía su primera <option>, que aquí es
    # «Mantener» (value="").
    for nombre in re.findall(r'<select[^>]*name="([^"]+)"', trozo):
        datos.setdefault(nombre, "")
    return datos


# ===========================================================================
# PIEZA A — EL SIGNO MOSTRADO. Los tres estados, y el tercero no es el segundo.
# ===========================================================================
class TestAElSignoQueLaTarjetaMuestra:

    def test_negado_true_la_tarjeta_dice_que_esta_negado(self, consola):
        """NEGATIVO 1. Rojo si un hecho negado se pinta como cualquier otra cosa."""
        client, _, _, ws = consola
        html = client.get(f"/v3/review?workspace={ws}").text
        codigo, texto = _signo_pintado(_tarjeta_de(html, "tarjeta-negado"))
        assert codigo == NEGACION_NEGADO, (
            f"HECHO NEGADO PINTADO COMO {codigo!r}. El almacén trae "
            f"`negated: true` —lo escribió la cadena real sobre {T_NEGADO!r}— y "
            f"la tarjeta donde se decide publica otro signo. Ésta es la forma "
            f"exacta del defecto: el operador decide sobre un estado que no es "
            f"el que tiene delante."
        )
        assert texto == NEGACION_LABELS_ES[NEGACION_NEGADO], (
            f"El código es correcto pero la frase servida es {texto!r}: la "
            f"traducción del código dejó de llegar a la pantalla."
        )

    def test_negado_false_la_tarjeta_dice_que_NO_esta_negado(self, consola):
        """NEGATIVO 2. El simétrico: marcarlo todo como negado no aprueba esto."""
        client, _, _, ws = consola
        html = client.get(f"/v3/review?workspace={ws}").text
        codigo, texto = _signo_pintado(_tarjeta_de(html, "tarjeta-afirmativo"))
        assert codigo == NEGACION_AFIRMATIVO, (
            f"HECHO AFIRMATIVO PINTADO COMO {codigo!r}. El almacén trae "
            f"`negated: false` sobre {T_AFIRMATIVO!r}. Pintar como negado un "
            f"hecho afirmativo es tan grave como lo contrario, y sin este caso "
            f"la forma más fácil de aprobar el anterior sería marcarlo todo."
        )
        assert texto == NEGACION_LABELS_ES[NEGACION_AFIRMATIVO]

    def test_negado_ausente_es_no_disponible_y_NUNCA_se_vuelve_false(self, consola):
        """NEGATIVO 3. AUSENCIA != CERO, y la pantalla lo DICE en vez de callar."""
        client, _, _, ws = consola
        html = client.get(f"/v3/review?workspace={ws}").text
        codigo, texto = _signo_pintado(_tarjeta_de(html, "tarjeta-sin-signo"))
        assert codigo != NEGACION_AFIRMATIVO, (
            "UNA PROPUESTA SIN `negated` SE PINTÓ COMO AFIRMATIVA. Ausencia no "
            "es cero: un paquete escrito antes de que el campo existiera no es "
            "un hecho que afirme la relación, es un hecho cuyo signo NADIE HA "
            "LEÍDO. Colapsar el tercer estado sobre el segundo es el defecto "
            "simétrico, y por la puerta de atrás."
        )
        assert codigo == NEGACION_NO_DISPONIBLE, (
            f"El signo ausente se pintó como {codigo!r}. Se esperaba el tercer "
            f"estado explícito."
        )
        assert texto == NEGACION_LABELS_ES[NEGACION_NO_DISPONIBLE], (
            f"El hueco se sirvió como {texto!r}. Callar es indistinguible de "
            f"«afirmativo», que es exactamente el defecto."
        )

    def test_el_lector_de_la_tarjeta_no_es_una_clave_inventada(self, consola):
        """NEGATIVO 4, control POSITIVO de resultado conocido, en esta tabla.

        `proposal.negation` es LA CLAVE DEL DEFECTO: no existe en el paquete
        real. Si el presentador leyera de ahí —o de cualquier otra clave que el
        exportador no escribe— el signo de los tres casos se derrumbaría sobre
        «no disponible», que es como estaba. Aquí se comprueba que leer esa
        clave NO reproduce lo que la pantalla enseña, es decir, que la pantalla
        NO está leyendo de ahí.
        """
        _, service, _, _ = consola
        for nombre, esperado in (
            ("negado", NEGACION_NEGADO),
            ("afirmativo", NEGACION_AFIRMATIVO),
        ):
            doc = service.queue(
                service.workspaces()[0], include_decided=True
            ).items
            item = next(i for i in doc if i["source_id"] == f"tarjeta-{nombre}")
            assert item["proposal"].get("negation") is None, (
                "EL PAQUETE REAL TRAE AHORA UNA CLAVE `negation`. La premisa de "
                "este corte era que no existe; si el exportador empezara a "
                "escribirla, hay dos fuentes para el mismo hecho y hay que "
                "decidir cuál manda ANTES de seguir."
            )
            assert item["signo"] == esperado, (
                f"El signo publicado para {nombre!r} es {item['signo']!r}."
            )

    def test_la_mutacion_a_la_clave_antigua_derrumba_los_tres_casos(self, consola):
        """NEGATIVO 4 (segunda mitad): el mutante, EJECUTADO, y su efecto.

        No se afirma «si alguien leyera `negation` esto fallaría»: se lee de
        `negation` aquí mismo, sobre el MISMO paquete que sirve la pantalla, y
        se comprueba que el resultado es el defecto original. Eso convierte la
        afirmación en algo medido en vez de razonado.
        """
        from app.labels import negation_code

        _, service, _, ws = consola
        items = service.queue(ws, include_decided=True).items
        assert items, "La cola está vacía: no hay nada sobre lo que mutar."
        derrumbados = [
            negation_code((i["proposal"] or {}).get("negation"))
            for i in items
        ]
        assert set(derrumbados) == {NEGACION_NO_DISPONIBLE}, (
            f"EL CONTROL NO SE PONE ROJO COMO DEBÍA: leyendo la clave del "
            f"defecto (`proposal.negation`) se esperaba que los "
            f"{len(items)} casos se derrumbaran sobre «no disponible», y "
            f"salió {derrumbados!r}. Si esto no se derrumba, el mutante no "
            f"reproduce el defecto y este fichero no está midiendo lo que dice."
        )
        vivos = sorted({i["signo"] for i in items})
        assert vivos != [NEGACION_NO_DISPONIBLE], (
            "LA PANTALLA PUBLICA EXACTAMENTE LO QUE PUBLICABA EL DEFECTO: "
            "todos los casos en «no disponible». El lector volvió a la clave "
            "antigua."
        )


# ===========================================================================
# PIEZA B — COHERENCIA DE LA TARJETA. Nada dentro del recuadro se contradice.
# ===========================================================================
class TestBLaTarjetaNoSeContradiceASiMisma:

    def test_la_prosa_y_el_campo_estructurado_dicen_lo_mismo(self, consola):
        """El corazón del defecto 1: los dos textos convivían en el recuadro."""
        client, _, _, ws = consola
        html = client.get(f"/v3/review?workspace={ws}").text
        tarjeta = _tarjeta_de(html, "tarjeta-negado")
        codigo, _ = _signo_pintado(tarjeta)
        prosa_niega = "niega la relación" in tarjeta
        assert prosa_niega, (
            "LA TARJETA DEL HECHO NEGADO YA NO EXPLICA QUE NIEGA. Se perdió la "
            "prosa de `NEGATED_CLAIM`, que es la mitad de la coherencia que "
            "este test vigila: sin ella no hay contradicción posible, pero "
            "tampoco explicación para quien decide."
        )
        assert codigo == NEGACION_NEGADO, (
            f"LA TARJETA SE CONTRADICE DENTRO DEL MISMO RECUADRO: la prosa dice "
            f"que la frase NIEGA la relación y el campo estructurado publica "
            f"{codigo!r}. El operador tiene delante dos afirmaciones "
            f"incompatibles sobre el hecho que va a aprobar."
        )

    def test_la_evidencia_literal_negativa_acompana_al_signo_negado(self, consola):
        client, _, _, ws = consola
        html = client.get(f"/v3/review?workspace={ws}").text
        tarjeta = _tarjeta_de(html, "tarjeta-negado")
        assert "no lidera" in tarjeta, (
            "LA EVIDENCIA LITERAL NEGATIVA NO ESTÁ EN LA TARJETA. El signo "
            "podría ser correcto y la persona seguiría sin ver la frase que lo "
            "justifica."
        )
        assert _signo_pintado(tarjeta)[0] == NEGACION_NEGADO


# ===========================================================================
# PIEZA E — LA SEGUNDA TARJETA. El otro consumidor, no el mismo arreglo dos veces.
# ===========================================================================
class TestELaOtraTarjetaDondeTambienSeDecide:
    """`/panel/review`. Tenía el MISMO síntoma por una causa DISTINTA."""

    def test_la_consola_publica_el_signo_y_no_la_clase_de_negacion(self, corpus):
        from app.services.v3_review import ReviewService as _RS  # noqa: F401

        negado = corpus["negado"]
        assert negado["proposal"]["negation_kind"] == "UNKNOWN", (
            "LA PREMISA DE ESTE CASO CAMBIÓ: el corpus real ya no trae "
            "`negation_kind='UNKNOWN'` para el hecho negado, así que la "
            "confusión entre CLASE y SIGNO que se mide aquí ya no se "
            "reproduce con este dato."
        )
        fila = row_view({**negado, "proposal": negado["proposal"]})
        assert fila["negated"] is True
        assert fila["signo"] == NEGACION_NEGADO, (
            f"LA SEGUNDA TARJETA PUBLICA {fila['signo']!r} PARA UN HECHO "
            f"NEGADO. Arreglar `/v3/review` y dejar `/panel/review` leyendo el "
            f"campo antiguo es exactamente lo que pasó con el corte del signo."
        )
        assert fila["negation_kind"] is None, (
            "La clase de negación dejó de ser una ausencia aquí; si ahora trae "
            "valor, revisa que el rótulo «Negación» siga siendo el SIGNO."
        )

    def test_el_campo_negacion_de_la_consola_no_se_derrumba_por_la_clase(self, corpus):
        """CONTROL POSITIVO: la causa vieja, ejecutada, sí se derrumba.

        Lo que pintaba la plantilla antes era `negation_kind` pasado por
        `_clean`, y `_clean` traduce «UNKNOWN» a ausencia. Se reproduce aquí
        para que conste que el «no disponible» de aquella pantalla venía de
        ahí, y no de otra cosa.
        """
        from app.services.review_console_v2 import _clean

        assert _clean(corpus["negado"]["proposal"]["negation_kind"]) is None, (
            "EL CONTROL NO REPRODUCE LA CAUSA: se esperaba que `_clean` "
            "convirtiera la clase «UNKNOWN» en ausencia, que es lo que hacía "
            "salir «no disponible» en la consola para un hecho negado."
        )
        fila = row_view(corpus["negado"])
        assert fila["signo_label"] == NEGACION_LABELS_ES[NEGACION_NEGADO], (
            "La consola vuelve a no decir el signo."
        )


# ===========================================================================
# PIEZA C — F-7. APROBAR NO FABRICA UNA CORRECCIÓN.
# ===========================================================================
class TestCAprobarSinTocarNadaNoFabricaCorreccion:

    def test_el_formulario_servido_SIGUE_trayendo_el_alcance_precargado(self, consola):
        """La premisa del defecto, comprobada: el navegador SÍ manda el campo.

        Si esto dejara de ser cierto, el test de abajo pasaría por la razón
        equivocada —«no hay corrección porque no se envió nada»— y el arreglo
        real quedaría sin vigilar. Por eso la premisa se afirma aparte.
        """
        client, _, _, ws = consola
        html = client.get(f"/v3/review?workspace={ws}").text
        datos = _formulario_tal_cual(_tarjeta_de(html, "tarjeta-negado"))
        assert datos.get("scope") == "not_available", (
            f"EL FORMULARIO YA NO MANDA `scope=not_available` (manda "
            f"{datos.get('scope')!r}). La corrección fantasma se cerró "
            f"quitando el campo del formulario en vez de dejando de creérselo "
            f"en el servidor: el siguiente consumidor que precargue un valor "
            f"vuelve a tener el agujero, y este fichero ya no lo vería."
        )

    def test_aprobar_sin_tocar_nada_deja_CERO_correcciones_en_el_acta(self, consola):
        """NEGATIVO 5, ATACADO POR EFECTO: se lee el acta PERSISTIDA."""
        client, _, decisiones, ws = consola
        html = client.get(f"/v3/review?workspace={ws}").text
        datos = _formulario_tal_cual(_tarjeta_de(html, "tarjeta-negado"))
        datos["human_decision"] = "APPROVE"

        respuesta = client.post("/v3/review/decide", data=datos, follow_redirects=False)
        assert respuesta.status_code == 303, (
            f"La aprobación no se aceptó ({respuesta.status_code}): "
            f"{respuesta.text[:300]}"
        )

        actas = read_history(decisiones)
        assert len(actas) == 1, f"Se esperaba un acta y hay {len(actas)}."
        acta = actas[0]
        assert acta["human_decision"] == "APPROVE"
        assert acta["correction"] == {}, (
            f"EL ACTA PERSISTIDA AFIRMA UNA CORRECCIÓN QUE EL REVISOR NO HIZO: "
            f"{acta['correction']!r}. Se pulsó «Aprobar» con el formulario TAL "
            f"COMO LO MANDA EL NAVEGADOR, sin tocar un solo campo. La cadena "
            f"`decision_audit` está encadenada por hash: esto no es un adorno "
            f"de pantalla, es el registro firmando algo falso sobre lo que hizo "
            f"la persona."
        )
        assert acta["correction_changes"] == {}, (
            f"El acta declara cambios {acta['correction_changes']!r} en una "
            f"aprobación sin modificaciones."
        )

    def test_el_acta_leida_del_fichero_coincide_con_la_del_almacen(self, consola):
        """El acta se ataca por EFECTO en los DOS sitios donde se persiste."""
        client, service, decisiones, ws = consola
        html = client.get(f"/v3/review?workspace={ws}").text
        datos = _formulario_tal_cual(_tarjeta_de(html, "tarjeta-negado"))
        datos["human_decision"] = "APPROVE"
        client.post("/v3/review/decide", data=datos, follow_redirects=False)

        del_fichero = read_history(decisiones)[0]
        del_almacen = service.store.decisions()[-1]
        assert del_almacen["correction"] == {}, (
            f"EL ALMACÉN (autoridad) guarda una corrección fantasma: "
            f"{del_almacen['correction']!r}, aunque el fichero JSONL esté "
            f"limpio. Mirar sólo el JSONL habría dado un verde falso."
        )
        assert del_fichero["record_hash"] == del_almacen["record_hash"], (
            "El acta del fichero y la del almacén no son la misma: una de las "
            "dos superficies de auditoría está contando otra historia."
        )


# ===========================================================================
# PIEZA D — LA CORRECCIÓN REAL EXISTE, CON `before`/`after` DE VERDAD.
# ===========================================================================
class TestDLaCorreccionRealNoSePierde:
    """EL SIMÉTRICO de la pieza C, y es la mitad que más fácil se rompe.

    La forma barata de matar las correcciones fantasma es dejar de registrar
    correcciones. Estos casos lo impiden.
    """

    def _decidir(self, consola, source_id, cambios, decision="APPROVE"):
        client, _, decisiones, ws = consola
        html = client.get(f"/v3/review?workspace={ws}").text
        datos = _formulario_tal_cual(_tarjeta_de(html, source_id))
        datos["human_decision"] = decision
        datos.update(cambios)
        respuesta = client.post("/v3/review/decide", data=datos, follow_redirects=False)
        return respuesta, read_history(decisiones)

    def test_cambiar_false_a_true_registra_UNA_correccion_exactamente_esa(self, consola):
        """NEGATIVO 6."""
        respuesta, actas = self._decidir(
            consola, "tarjeta-afirmativo", {"negated": "true"}
        )
        assert respuesta.status_code == 303, respuesta.text[:300]
        assert len(actas) == 1
        acta = actas[0]
        assert acta["correction"] == {"negated": True}, (
            f"UNA CORRECCIÓN HUMANA REAL SE PERDIÓ O SE DEFORMÓ: el operador "
            f"marcó «Negada» sobre una propuesta afirmativa y el acta guarda "
            f"{acta['correction']!r}. Evitar las correcciones fantasma no "
            f"puede costar las correcciones verdaderas."
        )
        assert acta["correction_changes"] == {
            "negated": {"before": False, "before_present": True, "after": True}
        }, (
            f"EL `before`/`after` NO DESCRIBE EL CAMBIO QUE OCURRIÓ: "
            f"{acta['correction_changes']!r}. Se esperaba exactamente "
            f"False -> True. Un acta que dice «hubo corrección» sin decir DE "
            f"QUÉ A QUÉ no permite reconstruir lo que hizo la persona."
        )

    def test_cambiar_true_a_false_registra_la_correccion_inversa(self, consola):
        """NEGATIVO 7. El inverso, para que no valga con acertar en un sentido."""
        respuesta, actas = self._decidir(consola, "tarjeta-negado", {"negated": "false"})
        assert respuesta.status_code == 303, respuesta.text[:300]
        acta = actas[0]
        assert acta["correction"] == {"negated": False}, (
            f"LA CORRECCIÓN INVERSA NO SE REGISTRÓ: {acta['correction']!r}. "
            f"Ojo al modo de fallo barato: quedarse sólo con los valores "
            f"«verdaderos» descarta `False` por falsedad de Python y pierde "
            f"justo esta corrección."
        )
        assert acta["correction_changes"] == {
            "negated": {"before": True, "before_present": True, "after": False}
        }, f"El `before`/`after` inverso es {acta['correction_changes']!r}."

    def test_una_correccion_de_alcance_de_verdad_si_se_registra(self, consola):
        """El alcance NO quedó capado por arreglar la corrección fantasma."""
        respuesta, actas = self._decidir(
            consola, "tarjeta-negado", {"scope": "durante el asedio"}
        )
        assert respuesta.status_code == 303, respuesta.text[:300]
        acta = actas[0]
        assert acta["correction"] == {"scope": "durante el asedio"}, (
            f"UNA CORRECCIÓN DE ALCANCE ESCRITA POR LA PERSONA SE PERDIÓ: "
            f"{acta['correction']!r}. El arreglo de F-7 se pasó de frenada y "
            f"ahora ignora el campo entero en vez de sólo el valor sin cambio."
        )
        assert acta["correction_changes"]["scope"] == {
            "before": "not_available", "before_present": True,
            "after": "durante el asedio",
        }, f"{acta['correction_changes']!r}"

    def test_poner_el_signo_donde_no_lo_habia_es_una_correccion_real(self, consola):
        """AUSENCIA != CERO, ahora del lado de la corrección.

        La propuesta sin `negated` y el operador marca «Afirmativa»: eso es una
        decisión humana (ausente -> False), no un reenvío. Si se tratara la
        ausencia como `False`, este cambio se leería «igual que la propuesta» y
        se tiraría — perdiendo la decisión.
        """
        respuesta, actas = self._decidir(
            consola, "tarjeta-sin-signo", {"negated": "false"}
        )
        assert respuesta.status_code == 303, respuesta.text[:300]
        acta = actas[0]
        assert acta["correction"] == {"negated": False}, (
            f"SE PERDIÓ UNA DECISIÓN HUMANA POR CONFUNDIR AUSENTE CON `False`: "
            f"{acta['correction']!r}. La propuesta NO traía signo; que la "
            f"persona lo fije es información nueva, no un reenvío."
        )
        assert acta["correction_changes"]["negated"] == {
            "before": None, "before_present": False, "after": False,
        }, (
            f"El acta no distingue «la propuesta no traía el campo» de «la "
            f"propuesta decía null»: {acta['correction_changes']!r}"
        )

    def test_el_autor_el_momento_y_el_ambito_de_la_correccion_son_reales(self, consola):
        _, actas = self._decidir(consola, "tarjeta-negado", {"negated": "false"})
        acta = actas[0]
        for campo in ("reviewer", "timestamp", "workspace", "proposal_id"):
            assert acta.get(campo), (
                f"EL ACTA DE UNA CORRECCIÓN REAL NO DICE {campo!r}. Sin autor, "
                f"momento y ámbito, «hubo una corrección» no es auditable."
            )
        assert acta["record_hash"], "El acta de la corrección no está firmada."


# ===========================================================================
# NEGATIVOS 8 Y 9 — LOS DOS MUTANTES DEL ACTA, EJECUTADOS
# ===========================================================================
class TestLosDosMutantesDelActa:
    """La afirmación no cuenta hasta que hay una prueba capaz de ponerse ROJA.

    Los dos controles de abajo EJECUTAN la mutación sobre el productor real
    (`_correccion_efectiva`) y comprueban que el efecto es el defecto. No se
    razona sobre lo que pasaría: se hace que pase.
    """

    def test_quitar_la_captura_del_cambio_deja_el_acta_sin_before_after(self, consola):
        """NEGATIVO 8: sin captura, la corrección real deja de ser reconstruible."""
        from app.services import v3_review as srv

        client, _, decisiones, ws = consola
        original = srv._correccion_efectiva
        # MUTANTE: se registra el valor nuevo pero NO se captura el cambio.
        srv._correccion_efectiva = lambda correction, claim: (
            original(correction, claim)[0], {}
        )
        try:
            html = client.get(f"/v3/review?workspace={ws}").text
            datos = _formulario_tal_cual(_tarjeta_de(html, "tarjeta-afirmativo"))
            datos["human_decision"] = "APPROVE"
            datos["negated"] = "true"
            client.post("/v3/review/decide", data=datos, follow_redirects=False)
            acta = read_history(decisiones)[0]
        finally:
            srv._correccion_efectiva = original

        assert acta["correction"] == {"negated": True}
        assert acta["correction_changes"] == {}, (
            "EL MUTANTE NO PRODUJO SU EFECTO: se le quitó la captura del "
            "cambio y el acta sigue trayendo `correction_changes`. Un control "
            "que no muerde no delata nada, y este fichero estaría afirmando "
            "una garantía que no vigila."
        )
        # Y ahora lo que importa: CON la mutación puesta, el caso de la pieza D
        # tiene que ponerse rojo. Se comprueba aquí mismo, no se promete.
        assert acta["correction_changes"] != {
            "negated": {"before": False, "before_present": True, "after": True}
        }, "El mutante no cambió nada observable."

    def test_fabricar_una_correccion_sin_cambio_reabre_F7(self, consola):
        """NEGATIVO 9: el mutante que se cree el formulario, y su efecto medido."""
        from app.services import v3_review as srv

        client, _, decisiones, ws = consola
        original = srv._correccion_efectiva
        # MUTANTE: el servidor vuelve a creerse todo lo que el navegador manda.
        srv._correccion_efectiva = lambda correction, claim: (dict(correction or {}), {})
        try:
            html = client.get(f"/v3/review?workspace={ws}").text
            datos = _formulario_tal_cual(_tarjeta_de(html, "tarjeta-negado"))
            datos["human_decision"] = "APPROVE"
            client.post("/v3/review/decide", data=datos, follow_redirects=False)
            acta = read_history(decisiones)[0]
        finally:
            srv._correccion_efectiva = original

        assert acta["human_decision"] == "APPROVE"
        assert acta["correction"] == {"scope": "not_available"}, (
            f"EL MUTANTE NO REPRODUCE F-7: se esperaba que, creyéndose el "
            f"formulario tal cual, el acta volviera a afirmar "
            f"`{{'scope': 'not_available'}}` tras un simple «Aprobar», y trae "
            f"{acta['correction']!r}. Si esto no reaparece, el control no "
            f"apunta al defecto que dice vigilar y su verde no vale."
        )


# ===========================================================================
# EL CIERRE DE CORRECT: un `CORRECT` sin ningún cambio no es una corrección.
# ===========================================================================
def test_correct_que_reenvia_la_propuesta_intacta_se_rechaza(consola):
    """La otra puerta de F-7: `CORRECT` colado por el campo precargado.

    La ruta HTTP sólo miraba que el formulario trajera ALGO relleno, y
    `scope=not_available` bastaba. Habría grabado un `CORRECT` con `correction`
    vacío: un acta que dice «la persona corrigió» sin corrección dentro.
    """
    client, _, decisiones, ws = consola
    html = client.get(f"/v3/review?workspace={ws}").text
    datos = _formulario_tal_cual(_tarjeta_de(html, "tarjeta-negado"))
    datos["human_decision"] = "CORRECT"

    respuesta = client.post("/v3/review/decide", data=datos, follow_redirects=False)
    assert respuesta.status_code == 400, (
        f"UN `CORRECT` SIN NINGÚN CAMBIO FUE ACEPTADO ({respuesta.status_code}). "
        f"El acta diría que la persona corrigió algo, y el campo `correction` "
        f"estaría vacío."
    )
    assert read_history(decisiones) == [], (
        "El `CORRECT` vacío se rechazó en la respuesta pero SÍ dejó acta: el "
        "rechazo es cosmético."
    )
