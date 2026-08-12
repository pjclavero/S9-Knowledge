"""Carril J -- calidad de datos v2: derivacion, vocabulario unico, fail-closed.

Tres afirmaciones, y cada una tiene su forma de ponerse ROJA declarada en
`mutaciones_calidad_datos.py`:

  1. Los campos de autorizacion que este carril comprueba se DERIVAN del
     registro ejecutable `viewer/app/policies/registry.py`. No hay segunda
     lista. Quitar o cambiar una dimension alli se propaga, y --lo que no es
     gratis-- se DETECTA, porque el codigo del motor es un testigo
     independiente de la derivacion.
  2. `review_status` tiene UN vocabulario canonico de dominio
     (`contracts/review-status/v1`) y adaptadores en las fronteras legacy. Un
     valor fuera del canonico se rechaza.
  3. Un dato de autorizacion ausente es un FALLO, nunca un permiso. Ni el mas
     amplio, ni el mas estrecho por accidente: el que el registro DECLARA.

Sobre el punto 1 conviene ser explicito, porque es el defecto que este carril
venia a corregir en si mismo: derivar una lista de un registro NO es, por si
solo, una comprobacion. Si la lista se deriva y alguien borra una dimension del
registro, la lista se acorta y todo sigue verde con menos casos. Una derivacion
sin testigo independiente convierte un borrado en un silencio. Por eso las
aserciones de abajo no miran la lista derivada contra si misma: la miran contra
el codigo del motor, contra el serializador del provider y contra el
comportamiento real de `POLICY.can_view`.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from app.labels import REVIEW_STATUS_LABELS_ES, review_status_label
from app.policies.engine import POLICY
from app.policies.models import NO_APLICA, ViewerContext
from app.policies.registry import DENY, MINIMO, NEUTRO, TODOS
from tests.test_provider_authz_fields_contract import (
    CAMPOS_AUTORIZACION_NODO,
    DIMENSIONES_DEL_CONTEXTO,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _cargar_review_status():
    ruta = REPO_ROOT / "contracts" / "review-status" / "v1" / "model.py"
    nombre = "s9k_review_status_v1_model"
    if nombre in sys.modules:
        return sys.modules[nombre]
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    assert spec and spec.loader, f"no se pudo cargar {ruta}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = mod
    spec.loader.exec_module(mod)
    return mod


RS = _cargar_review_status()


# ===========================================================================
# 1. DERIVACION: el registro es la unica fuente
# ===========================================================================

def test_la_lista_de_campos_de_autorizacion_no_se_declara_a_mano():
    """Meta-prueba: el comprobador no puede tener su propia lista.

    Si alguien vuelve a escribir la tupla a mano, este test lo ve: el fichero
    del contrato no puede contener literales de nombres de dimension fuera del
    puñado de excepciones documentadas (valores de ejemplo y estructurales).
    """
    fuente = (
        Path(__file__).resolve().parent / "test_provider_authz_fields_contract.py"
    ).read_text(encoding="utf-8")
    codigo = "\n".join(
        ln for ln in fuente.splitlines()
        if not ln.lstrip().startswith("#") and not ln.lstrip().startswith("*")
    )
    # `known_by` e `is_public`/`session_index` aparecen como VALORES de ejemplo
    # o dentro de RETIRADAS, no como declaracion de la lista. Los demas nombres
    # de dimension no deben aparecer en absoluto.
    permitidos_en_codigo = {"known_by", "is_public", "session_index"}
    literales = {
        c.name for c in TODOS
        if c.name not in permitidos_en_codigo
        and (f'"{c.name}"' in codigo or f"'{c.name}'" in codigo)
    }
    # `admin_full`, `can_view_reference` y `character_knowledge` SI pueden
    # aparecer: son la cuarentena de dimensiones no declaradas, y por
    # definicion no salen del registro.
    literales -= {"admin_full", "can_view_reference", "character_knowledge"}
    assert not literales, (
        f"el comprobador vuelve a nombrar dimensiones a mano: {sorted(literales)}. "
        f"La fuente de verdad es app/policies/registry.py."
    )


def test_la_derivacion_cubre_las_trece_dimensiones_del_registro():
    """Ninguna dimension declarada puede quedar fuera de las dos categorias."""
    cubiertas = set(CAMPOS_AUTORIZACION_NODO) | set(DIMENSIONES_DEL_CONTEXTO)
    declaradas = {c.stored_as or c.name for c in TODOS if c.in_projection}
    declaradas |= {c.name for c in TODOS if not c.in_projection}
    assert declaradas == cubiertas, (
        f"la derivacion no cubre {sorted(declaradas ^ cubiertas)}"
    )
    assert len(TODOS) == len(cubiertas)


def test_toda_dimension_declara_su_respuesta_a_la_ausencia():
    """`missing`/`malformed` son obligatorios y de un vocabulario cerrado.

    Una dimension sin respuesta declarada a "y si falta" es la forma exacta de
    H-B: el dato ilegible degradado a `None`, y `None` leido como "sin tope".
    """
    validos = {DENY, MINIMO, NEUTRO}
    for c in TODOS:
        assert c.missing in validos, f"{c.name}: missing={c.missing!r} no declarado"
        assert c.malformed in validos, f"{c.name}: malformed={c.malformed!r}"
        assert c.producer, f"{c.name}: sin productor declarado"
        assert c.consumer, f"{c.name}: sin consumidor declarado"
        assert c.prueba_negativa, f"{c.name}: sin prueba negativa declarada"
        assert c.prueba_http, f"{c.name}: sin prueba de extremo a extremo declarada"


# ===========================================================================
# 2. AUSENCIA DE DATO != PERMISO
# ===========================================================================

def _ctx_permisivo() -> ViewerContext:
    """Contexto lo mas ABIERTO posible sin ser admin.

    A proposito: si un nodo incompleto se deniega incluso con un contexto
    generoso, la denegacion viene del DATO ausente y no de que el lector no
    tuviera permisos. Con un contexto pobre, el test pasaria por el motivo
    equivocado y no mediria nada.
    """
    return ViewerContext(
        role="reviewer",
        allowed_workspaces=frozenset({"leyenda"}),
        active_partida="p1",
        allowed_partida_ids=frozenset({"p1"}),
        active_character="pc:ana",
        max_visible_session=999,
        can_view_secret=True,
        can_view_future=True,
        can_view_reference=True,
    )


def _nodo_completo() -> dict:
    return {
        "id": "n1",
        "workspace": "leyenda",
        "scope": "partida",
        "partida_id": "p1",
        "visibility": "player",
        "known_by": ["pc:ana"],
        "known_from_session": 1,
    }


def test_el_nodo_de_referencia_es_visible_para_el_contexto_permisivo():
    """Control POSITIVO. Sin el, los tests de abajo podrian pasar porque el
    motor deniega SIEMPRE, y un instrumento que siempre dice que no tampoco
    mide nada."""
    decision = POLICY.can_view(_nodo_completo(), _ctx_permisivo())
    assert decision.visible, f"el control positivo no pasa: {decision.reason}"


@pytest.mark.parametrize(
    "campo",
    [c.name for c in TODOS if c.in_projection and c.missing == DENY],
)
def test_un_campo_declarado_DENY_deniega_cuando_falta(campo):
    """La lista de casos se DERIVA de `missing == DENY` en el registro.

    Cambiar `missing` de `DENY` a `NEUTRO` en el registro cambia lo que este
    test exige: esa es la propagacion. Y si el motor no respeta la nueva
    declaracion, la prueba negativa del propio registro se pone roja.
    """
    nodo = _nodo_completo()
    nodo.pop(campo)
    decision = POLICY.can_view(nodo, _ctx_permisivo())
    assert not decision.visible, (
        f"'{campo}' esta declarado missing=DENY en el registro y el motor deja "
        f"pasar el nodo sin el. La ausencia de un dato de autorizacion se esta "
        f"tratando como permiso."
    )


@pytest.mark.parametrize(
    "campo",
    [c.name for c in TODOS if c.in_projection and c.missing == DENY],
)
def test_un_campo_declarado_DENY_deniega_cuando_es_None(campo):
    """Ausente y `None` deben comportarse igual.

    La clave presente con valor `None` es justo lo que produce la proyeccion
    del provider cuando Neo4j no tiene la propiedad: si el motor distinguiera
    los dos casos, la barrera estaria apagada precisamente en el que ocurre de
    verdad.
    """
    nodo = _nodo_completo()
    nodo[campo] = None
    decision = POLICY.can_view(nodo, _ctx_permisivo())
    assert not decision.visible, f"'{campo}'=None se trata como permiso"


def test_un_tope_de_sesion_ilegible_no_significa_sin_tope():
    """H-B, la forma canonica del defecto: dato ilegible que ABRE la barrera."""
    nodo = _nodo_completo()
    nodo["known_from_session"] = 5
    ctx_roto = ViewerContext(
        role="viewer",
        allowed_workspaces=frozenset({"leyenda"}),
        active_partida="p1",
        allowed_partida_ids=frozenset({"p1"}),
        active_character="pc:ana",
        max_visible_session=None,  # ausente/ilegible, NO "sin tope"
    )
    assert not POLICY.can_view(nodo, ctx_roto).visible

    ctx_no_aplica = ViewerContext(
        role="viewer",
        allowed_workspaces=frozenset({"leyenda"}),
        active_partida="p1",
        allowed_partida_ids=frozenset({"p1"}),
        active_character="pc:ana",
        max_visible_session=NO_APLICA,
    )
    assert not POLICY.can_view(nodo, ctx_no_aplica).visible


def test_un_contexto_vacio_no_ve_nada():
    """La ausencia total de datos de contexto no puede ser permiso maximo."""
    decision = POLICY.can_view(_nodo_completo(), ViewerContext())
    assert not decision.visible, (
        "un contexto sin ninguna dimension poblada ve contenido: la ausencia "
        "de dato de autorizacion se esta leyendo como permiso"
    )


# ===========================================================================
# 3. `review_status`: un unico vocabulario canonico + adaptadores
# ===========================================================================

def test_el_vocabulario_canonico_no_esta_vacio_y_es_cerrado():
    assert RS.CANONICAL_VALUES
    assert RS.HUMAN_REVIEWED <= RS.CANONICAL_VALUES
    assert RS.LEGACY_MACHINE_APPROVED not in RS.CANONICAL_VALUES


@pytest.mark.parametrize("valor", sorted(RS.CANONICAL_VALUES))
def test_todo_valor_canonico_se_normaliza(valor):
    assert RS.normalize(valor).value == valor


@pytest.mark.parametrize(
    "valor",
    [
        None, "", "   ", "APPROVED", "approved", "auto_approved", "revisado",
        3, True, ["reviewed"],
        # Estos MIDEN la frase "no hay `lower()` ni `strip()` salvatodo". Sin
        # ellos la parametrizacion solo tenia `APPROVED`, que no es canonico ni
        # en minusculas: ningun caso ejercitaba el trato de mayusculas y
        # espacios. Un canonico DISFRAZADO es el unico dato capaz de distinguir
        # un comparador estricto de uno indulgente.
        "REVIEWED", "Reviewed", " reviewed ", "AUTO_EXTRACTED", "\treviewed",
    ],
)
def test_un_valor_fuera_del_vocabulario_canonico_se_rechaza(valor):
    """Fail-closed literal: no hay default, no hay reparacion, no hay `lower()`
    ni `strip()` salvatodo. `approved` esta aqui a proposito: era el valor que la
    via de revision humana escribia en el grafo y que este conjunto cerrado
    nunca contuvo."""
    with pytest.raises(RS.ReviewStatusError):
        RS.normalize(valor)
    assert not RS.is_canonical(valor)
    assert not RS.is_human_reviewed(valor)


def test_las_etiquetas_del_visor_se_derivan_del_vocabulario_canonico():
    """Sin lista paralela: la cobertura es exacta, no 'al menos'."""
    assert set(REVIEW_STATUS_LABELS_ES) == set(RS.CANONICAL_VALUES)


def test_el_conjunto_cerrado_del_motor_es_el_mismo_objeto_canonico():
    """`rpg_schema.ALLOWED_REVIEW_STATUS` deja de ser una segunda declaracion."""
    sys.path.insert(0, str(REPO_ROOT / "data-engine" / "app"))
    try:
        from schemas.rpg_schema import ALLOWED_REVIEW_STATUS
    finally:
        sys.path.pop(0)
    assert ALLOWED_REVIEW_STATUS == RS.CANONICAL_VALUES


def test_una_etiqueta_de_estado_no_canonico_no_se_muestra_como_estado_legitimo():
    assert review_status_label("approved").startswith("no reconocido")
    assert review_status_label("reviewed") == "Revisado"
    assert review_status_label(None) == ""


# --- adaptadores de frontera ----------------------------------------------

def test_el_adaptador_del_contrato_de_candidatos_es_TOTAL():
    """El adaptador debe cubrir el enum COMPLETO de `review-ingest/v1`.

    Se lee del JSON Schema, no de una copia: si el contrato gana un estado y el
    adaptador no lo traduce, esto se pone rojo aqui en vez de levantar en
    produccion la primera vez que aparezca ese estado.
    """
    import json

    schema = json.loads(
        (REPO_ROOT / "contracts" / "review-ingest" / "v1" / "_common-v1.schema.json")
        .read_text(encoding="utf-8")
    )
    del_contrato = set(schema["$defs"]["candidate_status"]["enum"])
    assert del_contrato, "no se pudo leer el enum candidate_status del contrato"
    assert del_contrato <= RS.candidate_statuses_cubiertos(), (
        f"el adaptador no traduce {sorted(del_contrato - RS.candidate_statuses_cubiertos())}"
    )


@pytest.mark.parametrize("estado", sorted(RS.candidate_statuses_cubiertos()))
def test_el_adaptador_de_candidatos_devuelve_siempre_un_valor_canonico(estado):
    assert RS.from_candidate_status(estado).value in RS.CANONICAL_VALUES


def test_el_adaptador_de_candidatos_es_conservador():
    """`AUTO_APPROVABLE` no es `reviewed`.

    "Podria aprobarse sin humano" y "un humano lo aprobo" son afirmaciones
    distintas. Traducir la primera a `reviewed` inventaria una revision que no
    ocurrio, y esa afirmacion se persiste en el grafo.
    """
    assert RS.from_candidate_status("AUTO_APPROVABLE").value == "needs_review"
    assert RS.from_candidate_status("APPROVED").value not in ("auto_extracted",)
    assert RS.is_human_reviewed(RS.from_candidate_status("APPROVED").value)
    assert not RS.is_human_reviewed(RS.from_candidate_status("PENDING").value)


def test_el_adaptador_del_pipeline_no_convierte_automatico_en_revisado():
    assert RS.from_pipeline_decision("auto_approve").value == "auto_extracted"
    assert not RS.is_human_reviewed("auto_extracted")
    assert RS.from_pipeline_decision("needs_review").value == "needs_review"
    assert RS.from_pipeline_decision("auto_reject").value == "rejected"


def test_el_adaptador_de_revision_manual_traduce_la_via_humana():
    assert RS.from_review_manual_status("approved").value == "reviewed"
    assert RS.from_review_manual_status("pending").value == "needs_review"
    assert RS.is_human_reviewed(RS.from_review_manual_status("approved").value)
    assert not RS.is_human_reviewed(RS.from_review_manual_status("pending").value)


@pytest.mark.parametrize(
    "adaptador,disfrazado",
    [
        ("from_candidate_status", "approved"),        # el contrato usa MAYUSCULAS
        ("from_candidate_status", " APPROVED "),
        ("from_pipeline_decision", "AUTO_APPROVE"),
        ("from_pipeline_decision", " auto_approve "),
        ("from_review_manual_status", "APPROVED"),
        ("from_review_manual_status", " approved "),
        ("from_review_manual_status", "Approved"),
    ],
)
def test_los_TRES_adaptadores_son_igual_de_estrictos(adaptador, disfrazado):
    """Simetria entre fronteras.

    `from_review_manual_status` hacia `.strip().lower()` mientras los otros dos
    exigian el valor exacto, y esa asimetria no estaba razonada. Su efecto es
    que `" Approved "` se acepta por una frontera y se rechaza por las otras:
    "que idioma habla este dato" pasaba a depender de por donde entro. Ahora las
    tres son estrictas, y quien deba tolerar formato lo hace antes de llamar, a
    la vista.
    """
    with pytest.raises(RS.ReviewStatusError):
        getattr(RS, adaptador)(disfrazado)


@pytest.mark.parametrize(
    "adaptador",
    ["from_candidate_status", "from_pipeline_decision", "from_review_manual_status"],
)
@pytest.mark.parametrize("basura", [None, "", "MAGIC", "auto_approved", 7])
def test_ningun_adaptador_adivina(adaptador, basura):
    """Un adaptador que devuelve un default ante lo desconocido es peor que no
    tenerlo: convierte un dato ilegible en un estado del sistema."""
    if adaptador == "from_review_manual_status" and basura == "auto_approved":
        pass  # tambien debe levantar: no esta en el vocabulario de esa via
    with pytest.raises(RS.ReviewStatusError):
        getattr(RS, adaptador)(basura)


def test_la_via_de_escritura_humana_solo_admite_estados_que_acrediten_revision():
    """La frontera de escritura traduce; no deja pasar el idioma ajeno."""
    sys.path.insert(0, str(REPO_ROOT / "data-engine" / "app"))
    try:
        from review.ingest_approved import _build_create_entity
    finally:
        sys.path.pop(0)

    item = {
        "name": "X", "entity_type": "Character", "source_id": "s1",
        "source_kind": "audio", "source_document": "s1", "workspace": "leyenda",
        "knowledge_layer": "transcript", "visibility": "player",
        "review_status": "approved", "reviewed_by": "manual-cli:ana",
        "reviewed_at": "2026-01-01T00:00:00Z", "review_action": "approve",
        "confidence": 0.9, "evidence": "e",
    }
    _, props = _build_create_entity(item)
    assert props["review_status"] == "reviewed"
    assert RS.is_canonical(props["review_status"])

    item_roto = dict(item, review_status="auto_approved")
    with pytest.raises(RS.ReviewStatusError):
        _build_create_entity(item_roto)


@pytest.mark.parametrize(
    "estado,motivo",
    [
        ("pending", "traducible pero NO acredita revision humana"),
        ("deferred", "aplazado: nadie ha decidido todavia"),
        ("rejected", "decidido, pero en contra"),
        ("auto_approved", "token legacy del pipeline automatico"),
        ("MAGIC", "no pertenece a ningun vocabulario"),
        ("", "ausente"),
    ],
)
def test_la_validacion_de_procedencia_rechaza_todo_lo_que_no_acredite_revision(estado, motivo):
    """Este test existe porque la CALIBRACION lo exigio.

    La mutacion J15 --neutralizar la comprobacion de pertenencia a
    `HUMAN_REVIEWED` en `_validate_write_provenance`-- salia VERDE: la suite
    existente solo ejercitaba `approved` (valido) y `auto_approved` (atrapado
    por la rama anterior), asi que la comprobacion que de verdad decide sobre
    `pending`, `deferred` y `rejected` no la medía nadie. Un guardian que nunca
    se ha visto rojo no guarda nada; estos son los casos que lo ponen rojo.
    """
    sys.path.insert(0, str(REPO_ROOT / "data-engine" / "app"))
    try:
        from review.ingest_approved import _validate_write_provenance
    finally:
        sys.path.pop(0)

    item = {
        "kind": "entity", "name": "X", "entity_type": "Character",
        "source_id": "s1", "source_kind": "audio", "source_document": "s1",
        "workspace": "leyenda", "knowledge_layer": "transcript",
        "visibility": "player", "review_status": estado,
        "reviewed_by": "manual-cli:ana", "reviewed_at": "2026-01-01T00:00:00Z",
        "review_action": "approve", "confidence": 0.9, "evidence": "e",
    }
    errores = _validate_write_provenance({"approved": [item]})
    assert any("review_status" in e for e in errores), (
        f"review_status={estado!r} ({motivo}) NO fue rechazado por la "
        f"validacion de procedencia de escritura"
    )


def test_la_rama_de_RELACIONES_tambien_adapta_en_la_frontera():
    """Testigo de `_build_merge_relation_query`, que no tenia ninguno.

    Esa rama esta HOY INALCANZABLE en produccion: la ingesta controlada corre
    con `allow_relationships=False` y rechaza cualquier relacion antes de
    llegar aqui. Pero es codigo de escritura, sigue en el arbol "mantenido para
    uso futuro", y sin prueba su adaptacion seria una afirmacion sin medir: el
    dia que se habiliten las relaciones, una arista podria entrar al grafo
    hablando un idioma distinto del de un nodo y nadie se enteraria.
    """
    sys.path.insert(0, str(REPO_ROOT / "data-engine" / "app"))
    try:
        from review.ingest_approved import _build_merge_relation_query
    finally:
        sys.path.pop(0)

    item = {
        "relation_type": "KNOWS", "from_entity": "A", "to_entity": "B",
        "source_id": "s1", "source_kind": "audio", "workspace": "leyenda",
        "review_status": "approved", "confidence": 0.9, "evidence": "e",
    }
    _, params = _build_merge_relation_query(item)
    assert params["props"]["review_status"] == "reviewed", (
        "la arista se escribiria con 'approved' mientras un nodo equivalente se "
        "escribe con 'reviewed': dos idiomas para la misma propiedad"
    )
    assert RS.is_canonical(params["props"]["review_status"])

    with pytest.raises(RS.ReviewStatusError):
        _build_merge_relation_query(dict(item, review_status="auto_approved"))


def test_los_dos_modulos_frontera_exponen_EL_MISMO_objeto_Enum():
    """Invariante N3: dos modulos frontera, UN solo `Enum`.

    Hasta ahora esto estaba unicamente en PROSA --el docstring de
    `viewer/app/review_status_contract.py` y la nota final de
    `docs/66-calidad-de-datos-v2.md` afirman que ambos comparten la entrada de
    `sys.modules` y por tanto el mismo objeto de clase-- y una afirmacion en
    prosa no es una medida: se puede volver falsa sin que nada se ponga rojo.

    Basta con que alguien cambie `_MODULE_NAME` en uno de los dos ficheros (por
    ejemplo al mover el modulo, o "para evitar colisiones") y el contrato se
    cargaria DOS veces, produciendo dos clases `ReviewStatus` distintas. Todo
    seguiria pasando: los valores son iguales y `ReviewStatus` hereda de `str`,
    asi que las comparaciones por `==` seguirian dando `True`. Lo que se
    romperia son las comparaciones por IDENTIDAD (`is`, `isinstance`,
    pertenencia a un `set` de miembros del enum) --y lo harian lejos de aqui,
    en el consumidor, con un mensaje incomprensible del tipo
    "ReviewStatus.REVIEWED is not ReviewStatus.REVIEWED".

    Por eso el testigo es `is`, no `==`: `==` sobrevive a la duplicacion y no
    mide nada.
    """
    import app.review_status_contract as frontera_visor

    sys.path.insert(0, str(REPO_ROOT / "data-engine" / "app"))
    try:
        import review_status_contract as frontera_motor
    finally:
        sys.path.pop(0)

    assert frontera_visor.ReviewStatus is frontera_motor.ReviewStatus, (
        "el visor y el motor exponen DOS clases `ReviewStatus` distintas: el "
        "contrato review-status/v1 se ha cargado dos veces. Comprobar que "
        "`_MODULE_NAME` es identico en los dos modulos frontera"
    )
    # Y el mismo objeto que el que carga esta suite por su cuenta.
    assert frontera_visor.ReviewStatus is RS.ReviewStatus

    # Identidad tambien a nivel de MIEMBRO: es lo que rompe de verdad en el
    # consumidor cuando hay dos enums.
    assert frontera_visor.ReviewStatus.REVIEWED is frontera_motor.ReviewStatus.REVIEWED
    assert frontera_visor.HUMAN_REVIEWED == frontera_motor.HUMAN_REVIEWED
