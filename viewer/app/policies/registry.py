"""Registro DECLARATIVO de las dimensiones de autorización (M5b-C).

Este módulo es la referencia autoritativa del modelo de autorización, y existe
por una razón concreta: cinco dictámenes independientes consecutivos
encontraron la misma forma de fallo, nunca la misma línea de código.

    se implementa una barrera
      → se prueba el componente
        → queda verde
          → otro tramo de la cadena no transporta / no produce / no aplica
            → la barrera es decorativa o falla abierta

Los casos reales, para que no se lea como una abstracción:

  H1  el serializador de Neo4j descartaba `partida_id`: el aislamiento entre
      partidas no se evaluaba NUNCA sobre datos reales, con 675 tests verdes.
  H2  `_rel_to_dict` no llevaba `visibility`: toda relación era inválida.
  T1  el motor leía `party` / `is_public` / `session_index` y NINGÚN escritor
      los producía. Dos reglas enteras evaluándose sobre campos inexistentes.
  H-A `max_visible_session` tenía columna, lector y pruebas, y ningún escritor.
  H-B un valor corrupto se degradaba a `None`, que significaba "sin tope": el
      dato ilegible ABRÍA la barrera.

La conclusión operativa es que **una dimensión de autorización no es un campo:
es una cadena**. Autoridad → productor → persistencia → transporte → contexto →
consumidor, más una respuesta declarada a "¿y si falta?" y "¿y si es inválido?".
Un solo eslabón roto la convierte en decoración, y ninguna prueba de componente
lo detecta porque cada componente, por separado, está bien.

Declarar la cadena aquí permite comprobarla en las DOS direcciones (ver
`tests/test_registro_de_autorizacion.py`):

    el motor consulta un campo  → debe estar declarado, y el provider debe
                                  transportarlo
    el registro declara un campo → deben existir productor, consumidor y prueba
                                  de ausencia/invalidez

Sustituye a la red anterior, que buscaba el nombre del campo por todo el
repositorio con `grep`. Aquella falló dos veces: contaba ficheros de prueba como
"productor real" (el defecto de H1 dentro de la red contra H1) y se conformaba
con una mención en un comentario o en una lista de prohibición.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


#: Qué hacer cuando el dato NO está. Nunca "lo más permisivo": esa fue la
#: inferencia que hubo que arrancar del ámbito (M5c) y del tope de sesión (H-B).
DENY = "DENY"                  # sin el dato no se puede autorizar
MINIMO = "MINIMO_PRIVILEGIO"   # se aplica el valor más restrictivo (p.ej. 0)
NEUTRO = "NEUTRO"              # su ausencia no cambia la decisión, y está razonado


@dataclass(frozen=True)
class PolicyField:
    """Una dimensión de autorización, con su cadena completa declarada."""

    name: str
    #: Quién tiene la ÚLTIMA palabra sobre el valor. "servidor" significa que el
    #: cliente no puede influir en él por ningún camino.
    authority: str
    #: Módulo/ruta que lo ESCRIBE. Nunca un fixture ni un test.
    producer: str
    #: Dónde vive de forma persistente.
    storage: str
    #: Quién lo consume para decidir.
    consumer: str
    #: Qué ocurre si falta, y qué ocurre si está pero es inválido.
    missing: str
    malformed: str
    #: Cómo se retira. `None` = la dimensión no se revoca (es del dato, no de
    #: una concesión).
    revocation: Optional[str] = None
    #: ¿Viaja en la proyección del provider? Las dimensiones del CONTEXTO no
    #: son campos de nodo: esa distinción es justo la que dejó pasar H-A.
    in_projection: bool = True
    applies_to: frozenset[str] = field(default_factory=lambda: frozenset({"node", "relationship"}))
    #: Sólo obligatorio bajo estos ámbitos (vacío = siempre).
    required_for_scopes: frozenset[str] = field(default_factory=frozenset)
    #: Nombre con el que el PRODUCTOR lo escribe, cuando no coincide con el
    #: nombre de la dimensión. Declararlo es obligatorio: un campo que se
    #: escribe con un nombre y se lee con otro es exactamente T1 --el motor leía
    #: `session_index` mientras la ingesta escribía `known_from_session`--, y un
    #: renombrado tácito rompe la cadena sin que nada se ponga rojo.
    stored_as: Optional[str] = None
    #: Prueba NEGATIVA: demuestra el comportamiento REAL del motor ante la
    #: ausencia y ante el dato invalido. Obligatoria, y comprobada: el sexto
    #: dictamen encontro que este registro declaraba `missing=DENY` mientras el
    #: motor dejaba pasar la ausencia (H6-1). Declarar la semantica sin una
    #: prueba que la ejerza es la misma barrera decorativa que el registro
    #: existe para impedir, un nivel mas arriba.
    prueba_negativa: str = ""
    #: Prueba de EXTREMO A EXTREMO por HTTP: peticion real, sesion real,
    #: concesion real en auth.db. Obligatoria para toda dimension: H6-5 fue
    #: exactamente esto -- `active_character=None` en `dependencies.py` dejaba
    #: 806 tests verdes porque la unica prueba de la concesion de personaje
    #: consultaba la tabla en vez de pedir por HTTP.
    prueba_http: str = ""
    notes: str = ""


# ---------------------------------------------------------------------------
# Dimensiones del DATO: viajan en el nodo/relación y las escribe la ingesta.
# ---------------------------------------------------------------------------

CAMPOS_DEL_DATO: tuple[PolicyField, ...] = (
    PolicyField(
        name="workspace",
        prueba_negativa=(
            "tests/test_registro_es_especificacion_ejecutable.py::test_la_ausencia_y_el_dato_invalido_se_comportan_como_declara_el_registro[workspace]"
        ),
        prueba_http=(
            "tests/test_autorizacion_e2e_http_septima_ronda.py::test_el_workspace_ajeno_no_se_lista_por_HTTP"
        ),
        authority="servidor",
        producer="data-engine/app/knowledge_v3/writer/cypher.py",
        storage="Neo4j (propiedad de nodo/relación)",
        consumer="policies/engine.py + acotado en el propio Cypher",
        missing=DENY,
        malformed=DENY,
        revocation="inmediata (se recalcula en cada petición)",
        notes=(
            "El workspace efectivo del LECTOR sale del servidor, nunca de un "
            "parámetro de la petición. Doble barrera: acotado en Cypher y "
            "comprobado después por la política."
        ),
    ),
    PolicyField(
        name="scope",
        prueba_negativa=(
            "tests/test_registro_es_especificacion_ejecutable.py::test_la_ausencia_y_el_dato_invalido_se_comportan_como_declara_el_registro[scope]"
        ),
        prueba_http=(
            "tests/test_autorizacion_e2e_http_septima_ronda.py::test_un_dato_sin_scope_declarado_no_se_lista_por_HTTP"
        ),
        authority="contrato V3",
        producer="data-engine/app/knowledge_v3/writer/visibility.py (scope_props)",
        storage="Neo4j",
        consumer="policies/engine.py",
        missing=DENY,
        malformed=DENY,
        notes=(
            "Declaración POSITIVA (`juego`|`partida`). Antes se infería de la "
            "ausencia de `partida_id`, lo que hacía indistinguible un dato "
            "compartido a propósito de uno que perdió su ámbito."
        ),
    ),
    PolicyField(
        name="partida_id",
        prueba_negativa=(
            "tests/test_registro_es_especificacion_ejecutable.py::test_la_ausencia_y_el_dato_invalido_se_comportan_como_declara_el_registro[partida_id]"
        ),
        prueba_http=(
            "tests/test_autorizacion_e2e_http_septima_ronda.py::test_partida_id_en_blanco_NO_se_degrada_a_lore_compartido"
        ),
        authority="contrato V3",
        producer="data-engine/app/knowledge_v3/writer/visibility.py (scope_props)",
        storage="Neo4j",
        consumer="policies/engine.py",
        missing=DENY,
        malformed=DENY,
        required_for_scopes=frozenset({"partida"}),
        notes=(
            "Obligatorio bajo `scope=partida`; PROHIBIDO bajo `scope=juego` "
            "(un dato que dice ser de todos y de una a la vez se resolvería "
            "hacia lo más abierto)."
        ),
    ),
    PolicyField(
        name="visibility",
        prueba_negativa=(
            "tests/test_registro_es_especificacion_ejecutable.py::test_la_ausencia_y_el_dato_invalido_se_comportan_como_declara_el_registro[visibility]"
        ),
        prueba_http=(
            "tests/test_autorizacion_e2e_http_septima_ronda.py::test_una_visibilidad_corrupta_no_se_lista_por_HTTP"
        ),
        authority="contrato V3",
        producer="data-engine/app/knowledge_v3/writer/visibility.py (stamp)",
        storage="Neo4j",
        consumer="policies/engine.py",
        missing=DENY,
        malformed=DENY,
        revocation="explícita (`deny`, que es terminal incluso para admin)",
        notes="Vocabulario cerrado: player|narrator|secret|reference|deny.",
    ),
    PolicyField(
        name="known_by",
        prueba_negativa=(
            "tests/test_registro_es_especificacion_ejecutable.py::test_la_ausencia_y_el_dato_invalido_se_comportan_como_declara_el_registro[known_by]"
        ),
        prueba_http=(
            "tests/test_autorizacion_e2e_http_septima_ronda.py::test_known_by_malformado_deniega_el_nodo_por_HTTP"
        ),
        authority="concesiones de conocimiento",
        producer="data-engine/app/knowledge_v3/writer/visibility.py (stamp)",
        storage="Neo4j",
        consumer="policies/models.py (known_by_of) + engine.py",
        missing=NEUTRO,
        malformed=DENY,
        revocation="por concesión",
        notes=(
            "Ausente es el estado normal de casi todo el grafo, así que su "
            "ausencia es NEUTRA y está razonada. Malformado deniega el nodo "
            "entero: no se repara solo, porque una reparación que adivina "
            "dentro de una decisión de autorización puede ampliar permisos."
        ),
    ),
    PolicyField(
        name="known_by_characters",
        prueba_negativa=(
            "tests/test_registro_es_especificacion_ejecutable.py::test_la_ausencia_y_el_dato_invalido_se_comportan_como_declara_el_registro[known_by_characters]"
        ),
        prueba_http=(
            "tests/test_autorizacion_e2e_http_septima_ronda.py::test_known_by_characters_tambien_concede_por_HTTP"
        ),
        authority="concesiones de conocimiento",
        producer="data-engine/app/ingest_rpg.py",
        storage="Neo4j",
        consumer="policies/models.py (known_by_of)",
        missing=NEUTRO,
        malformed=DENY,
        revocation="por concesión",
        notes=(
            "Segundo nombre del mismo dato, escrito por la ingesta de rol en "
            "los nodos `:Entity` que el visor lee de verdad. Estuvo leído por "
            "el motor y NO transportado por la proyección (G3)."
        ),
    ),
    PolicyField(
        name="known_from_session",
        prueba_negativa=(
            "tests/test_registro_es_especificacion_ejecutable.py::test_la_ausencia_y_el_dato_invalido_se_comportan_como_declara_el_registro[known_from_session]"
        ),
        prueba_http=(
            "tests/test_autorizacion_e2e_http_septima_ronda.py::test_contenido_de_partida_SIN_revelacion_no_se_lista"
        ),
        authority="concesiones de conocimiento",
        producer="data-engine/app/knowledge_v3/writer/visibility.py (revelacion_props)",
        storage="Neo4j",
        consumer="policies/engine.py",
        missing=DENY,
        malformed=DENY,
        required_for_scopes=frozenset({"partida"}),
        notes=(
            "Desde qué sesión puede REVELARSE, no a qué episodio pertenece "
            "(`session_index`). Bajo `scope=partida` es OBLIGATORIA y su "
            "ausencia DENIEGA EN EL MOTOR (7ª ronda, H6-1): antes el único "
            "guardián era un `raise` del writer, que sólo cubre lo que escribe "
            "el writer -- `ingest_rpg` la escribe como opcional, y un nodo de "
            "partida sin ella se saltaba la regla entera con cualquier tope. "
            "Bajo `scope=juego` su ausencia es NO APLICABLE y está declarada: "
            "el lore compartido no está sujeto a la progresión de una partida. "
            "Si un nodo de juego SÍ la declara, se aplica igual (declararla es "
            "someterse a ella)."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Dimensiones del CONTEXTO: no son campos de nodo. La distinción importa porque
# la primera red anti-reincidencia sólo miraba campos de nodo, y por eso no
# habría detectado H-A (su propio docstring lo admitía).
# ---------------------------------------------------------------------------

CAMPOS_DEL_CONTEXTO: tuple[PolicyField, ...] = (
    PolicyField(
        name="max_visible_session",
        prueba_negativa=(
            "tests/test_registro_es_especificacion_ejecutable.py::test_una_dimension_de_contexto_ausente_nunca_amplia_lo_visible[max_visible_session]"
        ),
        prueba_http=(
            "tests/test_autorizacion_e2e_http.py::test_una_concesion_MIGRADA_sin_tope_no_gana_acceso"
        ),
        authority="servidor (concesión de partida)",
        producer="viewer/app/auth/db.py (grant_partida_access) + routers/admin.py",
        storage="auth.db, tabla partida_access (esquema v3)",
        consumer="policies/engine.py vía authz/dependencies.py",
        missing=MINIMO,
        malformed=MINIMO,
        revocation="inmediata (se relee de la concesión en cada petición)",
        in_projection=False,
        applies_to=frozenset(),
        notes=(
            "TRI-ESTADO (7ª ronda). `int` = tope declarado por la concesión; "
            "`NO_APLICA` = no hay partida activa, declarado explícitamente; "
            "cualquier otra cosa --incluido `None`-- es AUSENTE/INVÁLIDO y "
            "DENIEGA el contenido sujeto a revelación. `None` llegó a significar "
            "esas tres cosas a la vez y el motor las trataba a todas como "
            "permiso máximo (`if ctx.max_visible_session is not None:`). "
            "Sin tope declarado en la concesión el tope es 0: `NULL` NO "
            "significa 'sin tope', esa lectura dejaba la barrera apagada para "
            "toda concesión anterior a la migración. Ver futuro exige "
            "`can_view_future` explícito."
        ),
    ),
    PolicyField(
        name="active_character",
        prueba_negativa=(
            "tests/test_registro_es_especificacion_ejecutable.py::test_una_dimension_de_contexto_ausente_nunca_amplia_lo_visible[active_character]"
        ),
        prueba_http=(
            "tests/test_autorizacion_e2e_http_septima_ronda.py::test_la_concesion_de_personaje_abre_su_secreto_por_HTTP"
        ),
        authority="servidor (concesión de partida)",
        producer="viewer/app/auth/db.py (grant_partida_access) + routers/admin.py",
        storage="auth.db, partida_access.character_id",
        consumer="policies/models.py (ViewerContext.knows)",
        missing=MINIMO,
        malformed=MINIMO,
        revocation="inmediata; reconceder declara el estado completo",
        stored_as="character_id",
        in_projection=False,
        applies_to=frozenset(),
        notes=(
            "Sin personaje no se concede conocimiento individual. Salta la "
            "regla de NIVEL, así que una concesión que no se puede revocar ni "
            "se ve en el panel es un bypass invisible."
        ),
    ),
    PolicyField(
        name="allowed_partida_ids",
        prueba_negativa=(
            "tests/test_registro_es_especificacion_ejecutable.py::test_una_dimension_de_contexto_ausente_nunca_amplia_lo_visible[allowed_partida_ids]"
        ),
        prueba_http=(
            "tests/test_autorizacion_e2e_http_septima_ronda.py::test_el_material_de_otra_partida_no_se_lista_por_HTTP"
        ),
        authority="servidor (partida activa reverificada)",
        producer="viewer/app/routers/partida.py + auth/db.py",
        storage="auth.db (partida_access + sessions.active_partida)",
        consumer="policies/engine.py",
        missing=MINIMO,
        malformed=MINIMO,
        revocation="inmediata: se reverifica contra partida_access en cada petición",
        stored_as="partida_id",
        in_projection=False,
        applies_to=frozenset(),
    ),
    PolicyField(
        name="can_view_future",
        prueba_negativa=(
            "tests/test_registro_es_especificacion_ejecutable.py::test_una_dimension_de_contexto_ausente_nunca_amplia_lo_visible[can_view_future]"
        ),
        prueba_http=(
            "tests/test_autorizacion_e2e_http_septima_ronda.py::test_can_view_future_es_lo_unico_que_salta_el_tope"
        ),
        authority="servidor (rol)",
        producer="viewer/app/authz/context.py",
        storage="derivado del rol, no persistido como dato de contenido",
        consumer="policies/engine.py",
        missing=MINIMO,
        malformed=MINIMO,
        revocation="inmediata (cambio de rol)",
        in_projection=False,
        applies_to=frozenset(),
        notes="Única vía positiva para ver material no revelado.",
    ),
    PolicyField(
        name="can_view_secret",
        prueba_negativa=(
            "tests/test_registro_es_especificacion_ejecutable.py::test_una_dimension_de_contexto_ausente_nunca_amplia_lo_visible[can_view_secret]"
        ),
        prueba_http=(
            "tests/test_autorizacion_e2e_http_septima_ronda.py::test_can_view_secret_es_lo_unico_que_abre_un_secreto_ajeno"
        ),
        authority="servidor (rol)",
        producer="viewer/app/authz/context.py",
        storage="derivado del rol",
        consumer="policies/engine.py",
        missing=MINIMO,
        malformed=MINIMO,
        revocation="inmediata (cambio de rol)",
        in_projection=False,
        applies_to=frozenset(),
    ),
    PolicyField(
        name="allowed_workspaces",
        prueba_negativa=(
            "tests/test_registro_es_especificacion_ejecutable.py::test_una_dimension_de_contexto_ausente_nunca_amplia_lo_visible[allowed_workspaces]"
        ),
        prueba_http=(
            "tests/test_autorizacion_e2e_http_septima_ronda.py::test_el_workspace_ajeno_no_se_lista_por_HTTP"
        ),
        authority="servidor",
        producer="viewer/app/authz/context.py (desde configuración del servidor)",
        storage="configuración del despliegue",
        consumer="policies/engine.py + neo4j_provider (acotado en Cypher)",
        missing=MINIMO,
        malformed=MINIMO,
        revocation="inmediata",
        in_projection=False,
        applies_to=frozenset(),
    ),
    # -----------------------------------------------------------------------
    # P0-AUTH. Las tres dimensiones que el motor consumia y el registro NO
    # declaraba. Estuvieron en una "cuarentena" dentro de un fichero de test:
    # nombradas, no declaradas. Nombrar no es declarar, igual que mencionar no
    # es probar (H6-1) y tener columna no es tener escritor (H-A).
    # -----------------------------------------------------------------------
    PolicyField(
        name="admin_full",
        prueba_negativa=(
            "tests/test_registro_es_especificacion_ejecutable.py::test_una_dimension_de_contexto_ausente_nunca_amplia_lo_visible[admin_full]"
        ),
        prueba_http=(
            "tests/test_p0_autoridad_admin_full_http.py::test_retirar_el_rol_admin_retira_admin_full_en_la_siguiente_peticion"
        ),
        authority="servidor (rol `admin` del principal AUTENTICADO, releido en cada peticion)",
        producer="viewer/app/authz/context.py (build_viewer_context / build_internal_context)",
        storage="derivado del rol en auth.db; no persistido como dato de contenido",
        consumer=(
            "policies/engine.py (can_view regla 1, partida_in_scope) + "
            "authz/scope.py (sees_operational_detail, allows_workspace) + "
            "authz/filtered_provider.py (workspaces, _scope_workspaces)"
        ),
        missing=MINIMO,
        malformed=MINIMO,
        revocation="inmediata: el rol se relee de auth.db en cada peticion (no queda congelado en la sesion)",
        in_projection=False,
        applies_to=frozenset(),
        notes=(
            "NO es una dimension mas: es el BYPASS TOTAL. Se salta workspace, "
            "aislamiento entre partidas, nivel de visibilidad, `known_by` y el "
            "tope de sesion, y en `_scope_workspaces()` quita ademas el acotado "
            "en el propio Cypher (no solo el filtro posterior). Lo unico que NO "
            "salta es una `visibility` invalida y `deny`, que es TERMINAL: la "
            "regla 0 del motor va deliberadamente ANTES del bypass, porque un "
            "bypass puede saltarse reglas de permiso pero no convertir un estado "
            "terminal en permiso ni un dato invalido en valido. "
            "AUTORIDAD UNICA: `role == 'admin'` es ENTRADA del constructor y "
            "nunca se vuelve a evaluar aguas abajo. Se cerraron dos vias "
            "laterales que concedian esta misma potestad sin pasar por aqui: "
            "`authz/scope.py` la reevaluaba por rol, y `S9K_AUTH_ENABLED=false` "
            "la concedia por si mismo --un flag de despliegue como autoridad de "
            "facto sobre la dimension mas potente del sistema--. Sin "
            "autenticacion no hay principal, luego minimo privilegio: contexto "
            "anonimo. Ausente/invalido = False = sin potestad, que es el minimo "
            "por construccion (una dimension booleana de CONCESION no puede "
            "fallar abierta si su valor por defecto es no conceder)."
        ),
    ),
    PolicyField(
        name="can_view_reference",
        prueba_negativa=(
            "tests/test_registro_es_especificacion_ejecutable.py::test_una_dimension_de_contexto_ausente_nunca_amplia_lo_visible[can_view_reference]"
        ),
        prueba_http=(
            "tests/test_p0_autoridad_admin_full_http.py::test_el_material_de_referencia_exige_can_view_reference_por_HTTP"
        ),
        authority="servidor (rol)",
        producer="viewer/app/authz/context.py",
        storage="derivado del rol, no persistido como dato de contenido",
        consumer="policies/engine.py (regla 3, nivel `reference`)",
        missing=MINIMO,
        malformed=MINIMO,
        revocation="inmediata (cambio de rol)",
        in_projection=False,
        applies_to=frozenset(),
        notes=(
            "UNICA llave del nivel `reference` (material de reglas/manual). La "
            "concede el constructor a `viewer` y `reviewer`; el anonimo no la "
            "recibe. Simetrica de `can_view_secret`, que si estaba declarada: "
            "estaban una al lado de la otra en el mismo `if` del motor y solo "
            "una tenia cadena."
        ),
    ),
    # -----------------------------------------------------------------------
    # LORE-ANONIMO-DENEGADO. La capa juego era la unica rama del ambito sin
    # ninguna condicion sobre el LECTOR: su llave era no tener partida, es
    # decir, una AUSENCIA. Aqui se declara la llave positiva que la sustituye.
    # -----------------------------------------------------------------------
    PolicyField(
        name="can_view_lore",
        prueba_negativa=(
            "tests/test_registro_es_especificacion_ejecutable.py::test_una_dimension_de_contexto_ausente_nunca_amplia_lo_visible[can_view_lore]"
        ),
        prueba_http=(
            "tests/test_lore_anonimo_denegado_http.py::test_el_lore_de_capa_juego_exige_can_view_lore_por_HTTP"
        ),
        authority="servidor (rol del principal AUTENTICADO, releido en cada peticion)",
        producer="viewer/app/authz/context.py (build_viewer_context)",
        storage="derivado del rol; no persistido como dato de contenido",
        consumer=(
            "policies/engine.py (can_view regla 2b-bis, `scope=juego`) + "
            "policies/engine.py (partida_in_scope, registro SIN dimension de partida)"
        ),
        missing=MINIMO,
        malformed=MINIMO,
        revocation="inmediata (cambio de rol; el rol se relee de auth.db en cada peticion)",
        in_projection=False,
        applies_to=frozenset(),
        notes=(
            "FAIL-CLOSED, con las DOS mitades probadas por separado (auditoria "
            "independiente). La `prueba_negativa` de arriba mide MONOTONIA -- "
            "que un contexto sin la llave no vea mas que uno con ella-- y esa "
            "es OTRA propiedad: se cumple con cualquier valor por defecto, "
            "porque lo pasa explicitamente. El argumento 'una dimension "
            "booleana de concesion no puede fallar abierta si su defecto es no "
            "conceder' hay que probarlo SOBRE EL CAMPO, y lo hace "
            "`tests/test_lore_anonimo_denegado_invariantes.py::"
            "test_el_defecto_del_campo_es_no_conceder` (invertir el defecto del "
            "dataclass dejaba 1539 pruebas en verde). El defecto y las lineas "
            "explicitas del productor son mutuamente redundantes: cada una "
            "tiene ahora su propia prueba. "
            "LLAVE DE LA CAPA JUEGO (`scope=juego`), y de los registros que no "
            "viven en el grafo y no declaran partida (propuestas V3, contratos "
            "de revision, cola de trabajos), que se acotan con "
            "`VisibilityScope.partida_only()`. "
            "DECISION DEL OPERADOR (V3 RC, 2026-08-14): LORE_ANONIMO = DENEGADO. "
            "Auth desactivada produce contexto anonimo sin privilegios, y la "
            "AUSENCIA DE PARTIDA NO CONCEDE VISIBILIDAD ADICIONAL. Lo medido "
            "antes de esta dimension: con `S9K_AUTH_ENABLED` ausente/false el "
            "lore `player` de capa juego salia en la lista, contaba en los "
            "contadores y su ficha respondia 200 con el texto completo -- 1 de "
            "11 casos visibles, medido por dos carriles independientes sobre "
            "huecos distintos (docs/77 §3 y docs/78 §3). "
            "NO es una dimension de NIVEL como `can_view_reference`: es de "
            "AMBITO, hermana de `allowed_workspaces` y `allowed_partida_ids`, y "
            "por eso NO la salta `known_by` ni `character_knowledge` --que si "
            "saltan la regla de nivel--. Esa distincion tampoco estaba fijada "
            "por nada (mover la comprobacion dentro del bloque `if not knows` "
            "dejaba todo verde) y ahora la fija "
            "`test_el_conocimiento_de_personaje_NO_salta_la_barrera_de_capa_juego`. "
            "Ausente/invalido = False = no conceder, "
            "que es el minimo por construccion. "
            "Exponer lore publicamente en el futuro se hace concediendo ESTA "
            "dimension de forma explicita y con pruebas propias; recuperarlo "
            "como fallback del sistema es justo lo que se cerro."
        ),
    ),
    PolicyField(
        name="character_knowledge",
        prueba_negativa=(
            "tests/test_registro_es_especificacion_ejecutable.py::test_una_dimension_de_contexto_ausente_nunca_amplia_lo_visible[character_knowledge]"
        ),
        prueba_http=(
            "tests/test_p0_autoridad_admin_full_http.py::test_character_knowledge_no_la_puebla_la_cadena_de_peticion"
        ),
        authority="servidor (concesion de conocimiento precomputada)",
        producer="viewer/app/authz/context.py (context_for_simulated_character)",
        storage="derivado en memoria por peticion; NO persistido",
        consumer="policies/models.py (ViewerContext.knows) -> engine.py regla 3",
        missing=MINIMO,
        malformed=MINIMO,
        revocation="inmediata: se recalcula en cada peticion (no hay estado que retirar)",
        in_projection=False,
        applies_to=frozenset(),
        notes=(
            "Concede conocimiento por ID de nodo precomputado, SALTANDOSE "
            "`known_by`. Salta la regla de NIVEL igual que `active_character`, "
            "pero nunca el workspace, ni el ambito, ni el tope de sesion. "
            "LIMITE MEDIDO Y DECLARADO, no una garantia: la cadena de peticion "
            "(`authz/dependencies.py`) NO la puebla, asi que hoy llega SIEMPRE "
            "vacia en produccion y el unico productor que la rellena es "
            "`context_for_simulated_character`, que ninguna ruta invoca todavia. "
            "Es decir: dimension viva en el motor e inerte en la cadena, que es "
            "la forma de H-A. Se declara asi --con su prueba HTTP midiendo "
            "justo esa inercia-- en vez de retirarla, porque el modo "
            "'ver como personaje' la necesita; el dia que se conecte un "
            "productor, esa prueba se pone roja y obliga a declarar autoridad y "
            "revocacion ANTES de estrenarla."
        ),
    ),
)


TODOS: tuple[PolicyField, ...] = CAMPOS_DEL_DATO + CAMPOS_DEL_CONTEXTO

POR_NOMBRE: dict[str, PolicyField] = {c.name: c for c in TODOS}

#: Dimensiones RETIRADAS. Se declaran para que no vuelvan por la puerta de
#: atrás: si alguien las reintroduce en el motor, el registro no las reconoce y
#: la comprobación bidireccional se pone roja.
RETIRADAS: dict[str, str] = {
    "party": (
        "T1: era una ACL dinámica. Pertenecer al grupo daba acceso a todo lo "
        "que ese grupo supo alguna vez, y quien se incorpora en la sesión 20 no "
        "conoce el secreto de la 3. La party pasa a ser fuente de concesiones."
    ),
    "is_public": "T1: acompañaba a la ACL de party; deja de ser autoritativo.",
    "session_index": (
        "T2: sustituido por `known_from_session`. Decía a qué episodio "
        "pertenece algo, no desde cuándo puede revelarse; ningún escritor lo "
        "producía y la regla se evaluaba sobre un campo inexistente."
    ),
}
