# -*- coding: utf-8 -*-
"""Una negacion clara jamas puede acabar como una afirmacion materializable.

    "X hace Y"              -> negated=False
    "X no hace Y"           -> negated=True
    "Ni siquiera X hace Y"  -> negated=True

EL DEFECTO QUE ESTE FICHERO VIGILA, medido desde texto crudo por la cadena
real sobre `origin/main@d0a0962`:

    "Ni siquiera Daiki Oharu lidera la Casa del Ciervo."
        -> negated=False, SIN abstencion, predicado LEADS (que SI esta en el
           perfil), decision ACCEPT y plan APROBADO con CREATE_ASSERTION
           (status=ASSERTED, negated=False) + PROJECT_RELATION.

Una frase NEGATIVA entraba al grafo como AFIRMACION plana y materializable.

Y NO ERA UN DEFECTO DE "ni siquiera". La causa medida es la DISTANCIA: la
ventana de negacion se anclaba en la frase de relacion (`first -
NEGATION_WINDOW`, 3 tokens), asi que la LONGITUD DEL NOMBRE DEL SUJETO decidia
si la negacion se leia o no. Con el mismo cue:

    "Tampoco Kael vive en Valdor."                    -> negated=True
    "Tampoco Daiki Oharu Kensei lidera la Casa..."    -> negated=False  (!)

Por eso los casos de aqui van SIEMPRE en pares de sujeto CORTO y sujeto LARGO:
un fichero que solo probase "Kael" habria seguido verde con el defecto puesto,
que es exactamente como el defecto sobrevivio a toda la suite hasta ahora
(`TRAP_CORPUS` solo trae "Ni siquiera **Kael** vive en Valdor").

EL TECHO DE ESTE FICHERO, dicho entero:

  * Mide el extractor DETERMINISTA y la cadena local (`local_only`, dry-run).
    No mide la frontera semantica (`semantic.py`), ni el proveedor externo, ni
    Ollama, ni Neo4j real, ni el writer con `--apply`.
  * La prueba decisiva llega hasta el PLAN. No aplica: `apply` real contra un
    grafo vivo queda fuera, y se dice en vez de insinuarse.
  * No usa el tercer estado. Este corte es `True` frente a `False`; la
    negacion de alcance ambiguo (`SCOPE_AMBIGUOUS`) y el predicado fuera del
    perfil estan elevados aparte y NO se tocan aqui.
  * **ESTE FICHERO NO GARANTIZA LA PROPIEDAD ENTERA.** Cierra UNA fuente de
    distancia —la longitud del sintagma sujeto—, no la distancia. La ventana
    sigue siendo de `NEGATION_WINDOW` tokens desde el sujeto, asi que
    cualquier material intercalado entre el negador y el sujeto reproduce la
    firma exacta del defecto. Medido sobre este mismo HEAD:

        "Ni siquiera, en el ocaso de la guerra, Ilaria Vandreth dirige la
         Casa del Ciervo."
            -> negated=False, sin revision, ACCEPT, PLAN APROBADO con
               CREATE_ASSERTION + PROJECT_RELATION

        "Nunca, que se sepa, Kael vive en Valdor."
            -> negated=False, sin revision

    Es PREEXISTENTE (idéntico en la base), no depende de las comas —sin ellas
    sale igual, luego no es la barrera de clausula— y afecta TAMBIEN a
    sujetos de un token. Queda declarado y ABIERTO. Ningun caso de aqui lo
    cubre, y ninguno finge cubrirlo.
"""
from __future__ import annotations

import pytest

from test_knowledge_v3_e2e_fixtures import (  # noqa: E402
    NOW,
    WORKSPACE,
    gold_dev,
    pipeline,
    snapshot_entities,
)
from test_knowledge_v3_extraction import (  # noqa: E402
    GOLD_LEXICON,
    single_context,
    surfaces_of,
)

from knowledge_v3.extraction.deterministic import DeterministicExtractor  # noqa: E402
from knowledge_v3.extraction.lexicon import Lexicon, LexiconEntry  # noqa: E402
from knowledge_v3.multimodal.base import IngestOptions, SourceInput  # noqa: E402
from knowledge_v3.pipeline import SourceCase  # noqa: E402

# --------------------------------------------------------------------------
# Lexico: DOS sujetos del mismo tipo y misma relacion, uno CORTO (1 token) y
# otro LARGO (2 y 3 tokens). La diferencia entre ellos es la que el defecto
# usaba para colarse.
# --------------------------------------------------------------------------
LEXICON = Lexicon(
    [
        *GOLD_LEXICON.entries,
        LexiconEntry("Daiki Oharu", "Character", (), 0.9, "glossary"),
        LexiconEntry("Daiki Oharu Kensei", "Character", (), 0.9, "glossary"),
        LexiconEntry("Casa del Ciervo", "Faction", (), 0.9, "glossary"),
    ]
)


def claim_de(texto: str):
    """El UNICO claim no abstenido que la cadena real produce del texto crudo.

    No se fabrica a mano: entra texto, sale lo que el extractor escribe. Un
    claim construido a mano habria tenido `negated` puesto por mi, y la
    procedencia del dato es parte de la medicion.
    """
    ctx, _ = single_context("ep:neg", texto, lexicon=LEXICON)
    out = DeterministicExtractor().extract(ctx)
    emitidos = [c for c in out.claims if not c.abstained]
    assert len(emitidos) == 1, (
        f"NO HAY UN CLAIM QUE MEDIR para {texto!r}: la cadena emitio "
        f"{len(emitidos)} claims no abstenidos "
        f"(abstenciones: {[c for c in out.claims if c.abstained]}, "
        f"diagnosticos: {[d.code for d in out.diagnostics]}). "
        f"Sin claim, este caso no demuestra nada sobre la negacion: no es un "
        f"verde, es un instrumento que no alcanza."
    )
    return emitidos[0], out


# ==========================================================================
# 1. PARES MINIMOS. Sujeto corto y sujeto largo, el mismo par.
# ==========================================================================
#: (texto, negado esperado, por que). El sujeto LARGO de cada trio es lo que
#: el defecto rompia.
PARES_MINIMOS: tuple[tuple[str, bool], ...] = (
    # --- trio con sujeto CORTO (1 token): verde YA antes del arreglo -------
    ("Kael vive en Valdor.", False),
    ("Kael no vive en Valdor.", True),
    ("Ni siquiera Kael vive en Valdor.", True),
    # --- trio con sujeto LARGO (2 tokens): el defecto medido --------------
    ("Daiki Oharu lidera la Casa del Ciervo.", False),
    ("Daiki Oharu no lidera la Casa del Ciervo.", True),
    ("Ni siquiera Daiki Oharu lidera la Casa del Ciervo.", True),
    # --- trio con sujeto AUN MAS LARGO (3 tokens) -------------------------
    ("Daiki Oharu Kensei lidera la Casa del Ciervo.", False),
    ("Daiki Oharu Kensei no lidera la Casa del Ciervo.", True),
    ("Ni siquiera Daiki Oharu Kensei lidera la Casa del Ciervo.", True),
)


@pytest.mark.parametrize("texto,negado", PARES_MINIMOS)
def test_el_par_minimo_se_sostiene_con_el_sujeto_corto_y_con_el_largo(texto, negado):
    claim, _ = claim_de(texto)
    if negado:
        assert claim.negated is True, (
            f"UNA FRASE NEGATIVA SALIO COMO AFIRMACION PLANA: {texto!r} "
            f"produjo negated=False. La negacion esta en el texto y el claim "
            f"no la lleva, asi que aguas abajo es indistinguible de una "
            f"afirmacion y puede materializarse como tal."
        )
        assert claim.review_required is True, (
            f"NEGADO PERO SIN REVISION: {texto!r} salio negated=True con "
            f"review_required=False. Un hecho negativo no se auto-aprueba."
        )
    else:
        assert claim.negated is False, (
            f"UNA FRASE AFIRMATIVA SALIO MARCADA COMO NEGADA: {texto!r} "
            f"produjo negated=True. Es el defecto SIMETRICO: arreglar las "
            f"negativas no puede inventar negaciones donde no las hay."
        )
        # La segunda asercion NO es decorativa: sin ella estos tres
        # parametros eran TESTIGOS MUDOS —ninguna mutacion del calibrador
        # podia enrojecerlos— y el cruce los daba por calibrados sin serlo,
        # porque colapsa la parametrizacion. Lo encontro la revision
        # independiente contando a granularidad de PARAMETRO (22/25), no de
        # caso (7/7). Ahora miden lo mismo que sus gemelos de
        # `CONTROLES_AFIRMATIVOS`.
        assert claim.review_required is False, (
            f"UNA AFIRMACION PLANA PIDIENDO REVISION: {texto!r}."
        )


def test_la_longitud_del_NOMBRE_del_sujeto_no_decide_si_se_lee_la_negacion():
    """LA CAUSA, aislada: mismo cue, mismo predicado, sujeto mas largo.

    Este es el caso que nombra el defecto. Si la ventana vuelve a anclarse en
    la frase de relacion, "Tampoco" y "Nunca" se pierden en cuanto el sujeto
    ocupa 3 tokens, y estos dos se ponen rojos mientras sus gemelos de sujeto
    corto siguen verdes.
    """
    perdidos = []
    for cue in ("Tampoco", "Nunca"):
        corto, _ = claim_de(f"{cue} Kael vive en Valdor.")
        largo, _ = claim_de(f"{cue} Daiki Oharu Kensei lidera la Casa del Ciervo.")
        if corto.negated != largo.negated:
            perdidos.append((cue, corto.negated, largo.negated))
    assert perdidos == [], (
        f"LA DISTANCIA AL PREDICADO DECIDE SI SE LEE LA NEGACION: {perdidos}. "
        f"Con el mismo cue de negacion, el sujeto corto sale negado y el "
        f"largo no. La ventana esta anclada en la frase de relacion otra vez, "
        f"asi que el nombre propio del sujeto empuja al negador fuera."
    )


# ==========================================================================
# 2. LAS VARIANTES QUE EL MOTOR DECLARA SOPORTADAS
# ==========================================================================
#: Formas que el producto DICE cubrir, con donde lo dice:
#:   * `docs/v3/03-extractor.md:128` — "Kael no vive en Valdor",
#:     "Ni siquiera Kael vive en Valdor" -> negated=True + review_required.
#:   * `docs/v3/10-heldout.md:112` — negacion A DISTANCIA con "ni siquiera".
#:   * `cues.NEGATION_CUES` = no / nunca / jamas / tampoco / ni.
#:   * `cues.NEVER_CUES` = nunca / jamas  -> NEGATION_KIND_NEVER.
#:   * `cues.NOT_YET_PHRASES` = "todavia no" / "aun no" -> NOT_YET.
#:   * `cues.DEJAR_FORMS` / "ya no" -> CESSATION.
#: Todas se ejercitan con el sujeto LARGO, que es donde el defecto vivia.
VARIANTES_DECLARADAS: tuple[str, ...] = (
    "Daiki Oharu Kensei no lidera la Casa del Ciervo.",
    "Ni siquiera Daiki Oharu Kensei lidera la Casa del Ciervo.",
    "Tampoco Daiki Oharu Kensei lidera la Casa del Ciervo.",
    "Daiki Oharu Kensei nunca lidera la Casa del Ciervo.",
    "Daiki Oharu Kensei jamas lidera la Casa del Ciervo.",
    "Daiki Oharu Kensei ya no lidera la Casa del Ciervo.",
    "Daiki Oharu Kensei todavia no lidera la Casa del Ciervo.",
)


@pytest.mark.parametrize("texto", VARIANTES_DECLARADAS)
def test_las_variantes_declaradas_salen_negadas_y_pidiendo_revision(texto):
    claim, _ = claim_de(texto)
    assert claim.negated is True, (
        f"EL MOTOR DECLARA SOPORTAR ESTA FORMA NEGATIVA Y NO LA LEE: {texto!r} "
        f"salio negated=False. O la lee, o la documentacion y el codigo "
        f"divergen y esta frase puede materializarse del reves."
    )
    assert claim.review_required is True, (
        f"NEGADO SIN REVISION: {texto!r}."
    )


#: CONTROLES POSITIVOS — el riesgo simetrico. Ninguna puede salir negada.
#: "siquiera" suelto (sin "ni") NO es negacion; y el ultimo es el que vigila
#: el ARREGLO PEREZOSO: abrir la ventana a la frase entera SIN acotarla a la
#: clausula (`clause_scoped=False`) hace que ese "Nunca" de la primera
#: clausula niegue una relacion de la segunda. Medido: con esa mutacion puesta
#: sale `negated=True`.
CONTROLES_AFIRMATIVOS: tuple[str, ...] = (
    "Daiki Oharu Kensei lidera la Casa del Ciervo.",
    "Kael siquiera vive en Valdor.",
    "Daiki Oharu lidera la Casa del Ciervo.",
    "Kael vive en Valdor.",
    "Nunca hubo dudas: Daiki Oharu Kensei lidera la Casa del Ciervo.",
)


@pytest.mark.parametrize("texto", CONTROLES_AFIRMATIVOS)
def test_ninguna_frase_afirmativa_empieza_a_marcarse_como_negada(texto):
    claim, _ = claim_de(texto)
    assert claim.negated is False, (
        f"SE INVENTO UNA NEGACION SOBRE UNA FRASE AFIRMATIVA: {texto!r} salio "
        f"negated=True. Ampliar la ventana de negacion hacia la izquierda sin "
        f"acotarla a la clausula produce exactamente esto."
    )
    assert claim.review_required is False, (
        f"UNA AFIRMACION PLANA PIDIENDO REVISION: {texto!r}. No es peligroso, "
        f"pero indica que el contexto se esta leyendo mal."
    )


# ==========================================================================
# 3. LA PRUEBA DECISIVA: propuesta -> decision -> plan
# ==========================================================================
# Que el claim salga `negated=True` no basta. Lo que el operador pide
# demostrar es que una forma negativa NO PUEDE convertirse en una afirmacion
# positiva MATERIALIZABLE. Aqui entra texto crudo (bytes) por el normalizador
# real y se mira el PLAN: sobre `origin/main@d0a0962` esta misma entrada
# producia un plan APROBADO con CREATE_ASSERTION(status=ASSERTED,
# negated=False) y PROJECT_RELATION sobre `entity:leyenda:ilaria`.
NEGATIVA_CRUDA = "Ni siquiera Ilaria Vandreth dirige la Casa del Ciervo."
AFIRMATIVA_CRUDA = "Ilaria Vandreth dirige la Casa del Ciervo."


@pytest.fixture(scope="module")
def gold():
    return gold_dev()


def _correr(gold, texto: str):
    """Bytes -> normalizador -> extractor -> resolutor -> motor -> plan."""
    p = pipeline(gold)
    caso = SourceCase(
        source_id="raw:negacion",
        source=SourceInput(
            data=texto.encode("utf-8"),
            original_name="nota.md",
            original_location="memoria://nota.md",
            mime_type="text/markdown",
            source_kind="MARKDOWN",
        ),
        ingest_options=IngestOptions(
            workspace=WORKSPACE,
            collection_id="collection:pruebas",
            ingested_at=NOW,
            game_profile="generic",
        ),
    )
    resultado = p.run([caso], catalog_entities=snapshot_entities(gold))
    assert len(resultado.runs) == 1
    return resultado.runs[0]


def _operaciones(run) -> list[dict]:
    if run.plan is None:
        return []
    return [dict(op) for op in run.plan.mutation_operations]


def test_la_forma_negativa_no_llega_a_una_operacion_de_afirmacion(gold):
    """EL CORAZON DEL CORTE. Lo mide en el punto peligroso, no antes."""
    run = _correr(gold, NEGATIVA_CRUDA)

    claims = [c for c in (run.claims or []) if not c.abstained]
    assert claims, (
        "LA CADENA NO PRODUJO NINGUNA PROPUESTA de la frase negativa: sin "
        "propuesta este caso no puede demostrar que la negacion se respeta. "
        "Es un instrumento que no alcanza, no un verde."
    )
    assert all(c.negated for c in claims), (
        f"LA PROPUESTA DE UNA FRASE NEGATIVA SALIO SIN NEGAR: "
        f"{[(c.best_predicate(), c.negated) for c in claims]} para "
        f"{NEGATIVA_CRUDA!r}."
    )

    decisiones = list(run.decisions or [])
    assert decisiones, "LA CADENA NO DECIDIO NADA: no hay decision que mirar."
    aceptadas_en_positivo = [
        d for d in decisiones if d.decision == "ACCEPT" and not d.negated
    ]
    assert aceptadas_en_positivo == [], (
        f"UNA FRASE NEGATIVA ACABO EN UNA DECISION ACCEPT AFIRMATIVA: "
        f"{[(d.decision, d.negated) for d in decisiones]} para "
        f"{NEGATIVA_CRUDA!r}. Esto es el defecto entero: negacion clara, "
        f"afirmacion materializable."
    )

    materializan_en_positivo = [
        op
        for op in _operaciones(run)
        if op.get("operation_type") in ("CREATE_ASSERTION", "PROJECT_RELATION")
        and (op.get("payload") or {}).get("negated") is False
    ]
    assert materializan_en_positivo == [], (
        f"EL PLAN MATERIALIZA UNA AFIRMACION QUE EL TEXTO NIEGA: "
        f"{[op['operation_type'] for op in materializan_en_positivo]} con "
        f"negated=False para {NEGATIVA_CRUDA!r}. Esto es exactamente lo que "
        f"se medio sobre origin/main@d0a0962: CREATE_ASSERTION "
        f"(status=ASSERTED) + PROJECT_RELATION en un plan APROBADO."
    )


def test_la_misma_frase_en_afirmativo_SI_llega_al_plan(gold):
    """CONTROL POSITIVO DEL INSTRUMENTO.

    Sin esto, el verde de arriba se explicaria igual de bien porque la cadena
    no llega nunca al plan con esta fuente. Aqui se demuestra que SI llega: el
    unico cambio entre las dos entradas es "Ni siquiera".
    """
    run = _correr(gold, AFIRMATIVA_CRUDA)
    tipos = [op.get("operation_type") for op in _operaciones(run)]
    assert "CREATE_ASSERTION" in tipos, (
        f"LA CADENA NO MATERIALIZA NI SIQUIERA LA FRASE AFIRMATIVA "
        f"({AFIRMATIVA_CRUDA!r}, operaciones={tipos}, "
        f"plan={run.plan is not None}). Entonces el caso negativo de arriba "
        f"no demuestra nada: estaria verde porque el instrumento no alcanza "
        f"el punto peligroso, no porque la negacion se respete."
    )
    assert run.plan is not None and run.plan.approved, (
        "EL PLAN AFIRMATIVO NO SALE APROBADO: el control positivo no llega "
        "hasta donde dice llegar."
    )


def test_el_unico_cambio_entre_las_dos_entradas_es_la_marca_de_negacion(gold):
    """Mismo sujeto, mismo predicado, mismo objeto: cambia el signo, no el resto.

    Cierra la escapatoria de arreglar la negativa haciendo que la cadena deje
    de reconocer la relacion (abstenerse tambien evitaria materializarla, y
    seria una perdida disfrazada de arreglo).
    """
    negativa = _correr(gold, NEGATIVA_CRUDA)
    afirmativa = _correr(gold, AFIRMATIVA_CRUDA)

    def relaciones(run):
        """(predicado, entidad sujeto, entidad objeto) de cada DECISION.

        Se lee de la decision, no del claim: los identificadores de mencion
        son hash del texto y cambiarian solo por llevar "Ni siquiera" delante,
        mientras que las ENTIDADES resueltas tienen que ser las mismas.
        """
        return sorted(
            (d.predicate, d.subject_entity_id, d.object_entity_id)
            for d in (run.decisions or [])
        )

    assert relaciones(negativa) == relaciones(afirmativa) != [], (
        f"LA FRASE NEGATIVA YA NO PROPONE LA MISMA RELACION QUE LA "
        f"AFIRMATIVA: negativa={relaciones(negativa)} vs "
        f"afirmativa={relaciones(afirmativa)}. Lo negado SI se propone (03-"
        f"extractor.md §3.1.1): callarse no es leer bien el texto, es dejar "
        f"de leerlo."
    )
