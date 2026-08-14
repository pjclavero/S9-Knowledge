"""Motor de política de visibilidad: decisión deny-by-default por nodo.

Reglas (en orden; la primera denegación gana):

  1. admin_full            -> visible siempre (bypass total).
  2. workspace             -> el nodo debe declarar un workspace legible y estar
                              en allowed_workspaces. Sin workspace -> denegado.
  2b. ámbito (M5a/M5c)     -> el nodo debe DECLARAR `scope`: `partida` exige un
                              `partida_id` en allowed_partida_ids; `juego` es
                              lore compartido y no puede llevar `partida_id`.
                              Sin `scope` válido -> denegado. La ausencia nunca
                              se interpreta como el ámbito más amplio.
  2b-bis. capa juego       -> `scope=juego` exige `can_view_lore`. La AUSENCIA
                              de partida no concede visibilidad: el lore
                              compartido tiene llave propia y el contexto
                              anónimo no la recibe. Barrera de ÁMBITO, así que
                              `known_by` no la salta.
  2c. known_by (M5c)       -> si está presente debe ser lista de cadenas no
                              vacías; malformado -> denegado.
  3. nivel de visibilidad  -> reference exige can_view_reference; secret y narrator
                              (capa GM) exigen can_view_secret.
  4. sesión de revelación  -> bajo `scope=partida`, `known_from_session` es
                              OBLIGATORIA: ausente o inválida -> denegado; y el
                              tope debe ser un valor legible -> si no, denegado.
                              Visible sólo si known_from_session <=
                              max_visible_session o can_view_future. Bajo
                              `scope=juego` su AUSENCIA no aplica (el lore no
                              está sujeto a la progresión de una partida), pero
                              si el dato la declara se aplica igual: declararla
                              es someterse a ella.
                              NO es `session_index` (a qué episodio pertenece),
                              sino desde cuándo puede revelarse. `known_by` NO
                              la salta.
  5. (RETIRADA) pertenencia a party. Era una ACL dinámica: pertenecer al
                              grupo daba acceso a todo lo que ese grupo supo
                              alguna vez, y quien entra en la sesión 20 no
                              conoce el secreto de la 3. La party ahora sólo
                              CREA concesiones, materializadas en `known_by`.

`character_knowledge` (el personaje activo conoce el nodo) concede acceso a ESE
nodo aunque falle la regla 3: el personaje ya lo vivió. NUNCA salta la barrera de
workspace (regla 2), ni el ámbito (2b), ni la sesión de revelación (4) --que es
histórica y `known_by` no tiene dimensión temporal--, ni el bypass de admin (1).

Todos los métodos son puros: no escriben en ninguna fuente de datos.
"""
from __future__ import annotations

from typing import Any, Iterable

from app.policies.models import (
    ALL_SCOPES,
    ALL_STORED_LEVELS,
    AUSENTE_O_INVALIDO,
    DENY,
    NO_APLICABLE,
    VALOR,
    estado_de_entero_no_negativo,
    NARRATOR,
    REFERENCE,
    SCOPE_PARTIDA,
    SECRET,
    VisibilityDecision,
    ViewerContext,
    known_by_of,
)

_ALLOW = VisibilityDecision(True, "admin_full")


class VisibilityPolicy:
    """Evalúa un ``ViewerContext`` contra nodos/relaciones del grafo."""

    def can_view(self, node: dict[str, Any], ctx: ViewerContext) -> VisibilityDecision:
        # 0. M5b-2: la visibilidad debe ser un valor del vocabulario cerrado.
        #
        # Va ANTES del bypass de administrador, y no es un detalle: si fuera
        # despues, `admin_full` haria visible tanto un `deny` --que es terminal
        # por definicion-- como un nodo con la propiedad corrupta. Un bypass
        # solo puede saltarse reglas de permiso; no puede convertir un dato
        # invalido en un dato valido.
        raw = node.get("visibility")
        level = raw.strip().lower() if isinstance(raw, str) else None
        if level not in ALL_STORED_LEVELS:
            # Ausente, vacia, de otro tipo, o un nivel que este motor no
            # conoce (p.ej. escrito por una version futura). Ninguno de esos
            # casos puede resolverse "hacia lo permisivo" sin adivinar.
            return VisibilityDecision(False, "visibility_invalid")
        if level == DENY:
            return VisibilityDecision(False, "deny_absolute")

        # 1. Bypass total de administrador.
        if ctx.admin_full:
            return _ALLOW

        # 2. Aislamiento por workspace (nunca se salta, ni por conocimiento).
        #
        # M5c: fail-closed. Antes era `if ws is not None and ws not in ...`, es
        # decir, un nodo SIN workspace legible pasaba la barrera. Ese es el
        # mismo defecto permisivo que M5b-2 cerró para `visibility`, y no tenía
        # por qué sobrevivir aquí: si no se puede leer a qué workspace pertenece
        # un dato, no se puede afirmar que el lector tenga derecho a verlo.
        ws = node.get("workspace")
        if not isinstance(ws, str) or not ws.strip():
            return VisibilityDecision(False, "workspace_invalid")
        if ws not in ctx.allowed_workspaces:
            return VisibilityDecision(False, "workspace_not_allowed")

        # 2b. Aislamiento entre partidas (M5a, docs/v3/49 §2.6), con ámbito
        # DECLARADO (M5c). Antes se infería del propio hueco: "sin `partida_id`
        # = capa juego, visible desde cualquier partida". Esa inferencia hacía
        # indistinguible un lore deliberadamente compartido de un dato que
        # perdió su ámbito por el camino —y el segundo caso se resolvía hacia lo
        # más abierto—. Ahora el ámbito se declara y, si no se declara, se
        # deniega.
        #
        # Como el aislamiento de workspace, esta barrera NUNCA se salta por
        # conocimiento de personaje ni por pertenencia a party.
        scope = node.get("scope")
        if scope not in ALL_SCOPES:
            return VisibilityDecision(False, "scope_invalid")

        pid = node.get("partida_id")
        if scope == SCOPE_PARTIDA:
            # Ámbito de partida sin partida legible: contradicción interna del
            # dato. No se degrada a capa juego, que sería lo permisivo.
            if not isinstance(pid, str) or not pid.strip():
                return VisibilityDecision(False, "partida_id_blank")
            if pid not in ctx.allowed_partida_ids:
                return VisibilityDecision(False, "partida_not_allowed")
        else:
            # Capa juego: compartida entre partidas del workspace. Pero no puede
            # arrastrar un `partida_id`: sería un dato que dice ser de todos y
            # de una a la vez, y la vía "de todos" es la más abierta.
            if pid is not None:
                return VisibilityDecision(False, "scope_contradictorio")

            # 2b-bis. LORE-ANÓNIMO-DENEGADO: la capa juego exige llave PROPIA.
            #
            # "Compartida entre partidas del workspace" nunca quiso decir
            # "compartida con quien no es nadie". Hasta aquí la capa juego era
            # la única rama del ámbito sin ninguna condición sobre el LECTOR:
            # bastaba superar la barrera de workspace, y un contexto anónimo la
            # supera porque el workspace por defecto del despliegue está en
            # `allowed_workspaces`. El resultado medido era que la AUSENCIA de
            # partida concedía visibilidad -- exactamente la inferencia
            # permisiva que M5c arrancó del propio dato, sobreviviendo un nivel
            # más arriba, en el lector.
            #
            # Va aquí, con el ámbito y no con el nivel de contenido, porque es
            # una barrera de ÁMBITO: como workspace y como partida, NO la salta
            # el conocimiento de personaje. Por eso está antes de `ctx.knows` y
            # fuera del `if not knows` de la regla 3: `known_by` dice que un PJ
            # conoce un dato, no que quien lee sea ese PJ.
            if not ctx.can_view_lore:
                return VisibilityDecision(False, "lore_not_allowed")

        # 2c. M5c: `known_by` malformado deniega el nodo entero, no solo el
        # conocimiento. Es un campo de autorización: si no se puede interpretar,
        # no se puede decidir. Además evita el 500 que producía un tipo
        # inesperado al evaluar la pertenencia.
        _, known_by_valido = known_by_of(node)
        if not known_by_valido:
            return VisibilityDecision(False, "known_by_invalid")

        knows = ctx.knows(node)

        # 3. Nivel de visibilidad del contenido. `level` ya viene validado
        # desde la regla 0: aqui no se vuelve a leer del nodo.
        if not knows:
            if level == REFERENCE and not ctx.can_view_reference:
                return VisibilityDecision(False, "reference_not_allowed")
            if level == SECRET and not ctx.can_view_secret:
                return VisibilityDecision(False, "secret_not_allowed")
            if level == NARRATOR and not ctx.can_view_secret:
                # La capa del narrador/GM se trata como contenido elevado.
                return VisibilityDecision(False, "narrator_only")

        # 4. Sesión de REVELACIÓN (progresión de campaña).
        #
        # Se lee `known_from_session`: "desde qué sesión puede revelarse este
        # conocimiento". NO es `session_index` ("a qué episodio pertenece"), y
        # confundirlos es un error de producto, no de tipos: si en la sesión 12
        # se descubre un asesinato ocurrido cinco años antes, la barrera del
        # visor es 12 --el episodio en que se reveló--, no la cronología del
        # hecho. El motor leía `session_index`, que ningún escritor produce.
        #
        # `0` es una declaración POSITIVA ("conocido desde el inicio"), no una
        # ausencia. Se tipa como todo lo demás: malformado deniega, nunca lanza.
        # 7ª ronda -- aquí vivía el defecto: `if ctx.max_visible_session is not
        # None:` seguido de `if desde is not None:`. Dos guardas construidas
        # sobre un `None` que significaba tres cosas distintas, y el efecto neto
        # era que un nodo `scope=partida` SIN `known_from_session` se saltaba la
        # regla entera y era visible con cualquier tope --mientras el registro y
        # docs/58 declaraban `missing=DENY`--. El único guardián era un `raise`
        # del writer, que sólo cubre el contenido escrito POR el writer.
        #
        # Ahora la regla se decide por ÁMBITO, con estados distinguibles.
        desde = node.get("known_from_session")

        # Bajo `scope=partida` la revelación es OBLIGATORIA (el registro lo
        # declara con `required_for_scopes={"partida"}`). Ausente e inválido
        # deniegan igual, y por el mismo motivo que el ámbito: un dato de
        # partida sin sesión de revelación es indistinguible de uno que la
        # perdió, y la única lectura que no adivina es no mostrarlo.
        # Bajo `scope=juego` su ausencia es NO APLICABLE y está declarada: el
        # lore compartido no está sujeto a la progresión de una partida.
        if scope == SCOPE_PARTIDA and desde is None:
            return VisibilityDecision(False, "known_from_session_missing")

        if desde is not None:
            if estado_de_entero_no_negativo(desde) != VALOR:
                return VisibilityDecision(False, "known_from_session_invalid")
            if not ctx.can_view_future:
                # El tope también en tri-estado. Antes, cualquier `None` --y
                # `None` significaba tres cosas-- saltaba la regla entera.
                estado_tope = estado_de_entero_no_negativo(ctx.max_visible_session)
                if estado_tope == NO_APLICABLE:
                    # El lector no tiene partida activa, luego no hay progresión
                    # contra la que medir un dato que SÍ declara sesión de
                    # revelación. Denegar mantiene la monotonía: menos contexto
                    # nunca puede dar más acceso (H6-9).
                    return VisibilityDecision(False, "session_cap_not_applicable")
                if estado_tope == AUSENTE_O_INVALIDO:
                    # No se pudo determinar el tope. No conceder.
                    return VisibilityDecision(False, "session_cap_missing")
                if desde > ctx.max_visible_session:
                    return VisibilityDecision(False, "future_session")

        # La barrera histórica NO la salta `knows`.
        #
        # `known_by` es la proyección del estado ACTUAL de conocimiento, sin
        # dimensión temporal: dice que el PJ lo sabe, no desde cuándo. Si
        # bastara para saltarse el tope, pedir "ver como PJ hasta la sesión 5"
        # revelaría lo que ese mismo PJ descubrió en la 12 -- un spoiler
        # producido por la propia función que existe para evitarlo. Solo la
        # saltan `can_view_future` explícito o, cuando exista el ledger
        # temporal, un `knowledge_grant` con `valid_from_session` en rango.
        # Por eso esta regla va ANTES y fuera del `if not knows`.

        # 5. (retirada) Contenido acotado a un grupo (party).
        #
        # `party` + `party_membership` era una ACL dinámica: pertenecer al grupo
        # daba acceso automático a todo lo que el grupo hubiera conocido alguna
        # vez. En una campaña eso es semánticamente falso -- un personaje que se
        # incorpora en la sesión 20 no conoce el secreto que el grupo descubrió
        # en la 3. La party pasa a ser FUENTE DE CONCESIÓN (evento -> miembros
        # presentes -> grants individuales -> `known_by` materializado), no una
        # frontera evaluada en cada petición. `party` e `is_public` dejan de ser
        # vocabulario autoritativo, y `party_membership` no concede nada aquí.

        return VisibilityDecision(True, "visible")

    def partida_in_scope(self, partida_id: Any, ctx: ViewerContext) -> bool:
        """¿Cae esta partida dentro del ámbito del lector?

        Pregunta de ÁMBITO, no de contenido, y por eso vive aquí y no se
        responde fabricando un nodo sintético para pasarlo por ``can_view``:
        ese truco es lo que hizo que una sonda acabara evaluada como contenido.
        La usan los registros operativos (cola de revisión, trabajos), que
        tienen partida pero no visibilidad ni ámbito declarado.

        ``None`` significa "este registro no tiene dimensión de partida", no
        "es de todas": no es un dato del grafo al que se le haya perdido el
        ámbito, sino una fila que nunca lo tuvo.

        LORE-ANÓNIMO-DENEGADO: y "no tiene dimensión de partida" tampoco puede
        significar "lo ve cualquiera". Este ``return True`` incondicional era la
        SEGUNDA vía de la misma concesión implícita --la del corpus que no vive
        en el grafo: propuestas V3, contratos de revisión, cola de trabajos--,
        acotado con ``scope.partida_only()``. Un registro sin partida es
        material de capa juego, así que pide la misma llave que la capa juego
        pide en ``can_view``. Un lector legítimo la tiene y no pierde nada; el
        anónimo no la tiene y deja de recibir por aquí lo que ya no recibe por
        el grafo.
        """
        if ctx.admin_full:
            return True
        if partida_id is None:
            return ctx.can_view_lore
        if not isinstance(partida_id, str) or not partida_id.strip():
            return False
        return partida_id in ctx.allowed_partida_ids

    # ------------------------------------------------------------------
    # Helpers de conjunto: la aplicación real (provider) los usa para que
    # LISTADOS, CONTEOS y BÚSQUEDAS filtren igual que el acceso por ID.
    # ------------------------------------------------------------------

    def filter_nodes(
        self, nodes: Iterable[dict[str, Any]], ctx: ViewerContext
    ) -> list[dict[str, Any]]:
        return [n for n in nodes if self.can_view(n, ctx).visible]

    def visible_ids(
        self, nodes: Iterable[dict[str, Any]], ctx: ViewerContext
    ) -> set[str]:
        return {n["id"] for n in nodes if "id" in n and self.can_view(n, ctx).visible}

    def filter_edges(
        self,
        edges: Iterable[dict[str, Any]],
        visible_node_ids: set[str],
        ctx: ViewerContext,
    ) -> list[dict[str, Any]]:
        """Una relación sólo es visible si AMBOS extremos lo son y ella misma
        supera la política (una relación puede ser secreta aunque sus nodos no).
        """
        out = []
        for e in edges:
            if e.get("from") not in visible_node_ids or e.get("to") not in visible_node_ids:
                continue
            if not self.can_view(e, ctx).visible:
                continue
            out.append(e)
        return out


# Instancia compartida sin estado.
POLICY = VisibilityPolicy()
