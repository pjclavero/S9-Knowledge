"""UNA SOLA AUTORIDAD: comprobaciones estructurales y de motor (P0-AUTH).

El testigo de la cadena completa esta en
`test_p0_autoridad_admin_full_http.py`, que atraviesa HTTP y no fabrica ningun
contexto. Aqui viven las dos cosas que HTTP no puede demostrar:

  * que no exista NINGUN otro productor de `ViewerContext` --una potestad total
    fabricada a mano no se ve pidiendo por HTTP, se ve leyendo el arbol--, y
  * el orden interno del motor: `deny` es terminal ANTES del bypass.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.policies.engine import POLICY
from app.policies.models import ViewerContext

APP = Path(__file__).resolve().parents[1] / "app"

#: UNICO fichero autorizado a construir un `ViewerContext`. No es una lista de
#: exentas: es la definicion de "productor unico", y tiene exactamente un
#: elemento a proposito. Anadir un segundo nombre aqui es partir la autoridad en
#: dos, que es el defecto que este carril cierra.
PRODUCTOR = "app/authz/context.py"


def _construcciones_de_contexto() -> dict[str, int]:
    """`{ruta relativa: nº de veces que construye un ViewerContext}`, por AST.

    Por AST y no por `grep`: `grep` cuenta tambien la palabra en un comentario,
    en un docstring o en una anotacion de tipo, y esta comprobacion tiene que
    distinguir CONSTRUIR de MENCIONAR. El registro entero existe porque alguien
    conto una mencion como si fuera un escritor real (T1).
    """
    encontrados: dict[str, int] = {}
    for py in sorted(APP.rglob("*.py")):
        arbol = ast.parse(py.read_text(encoding="utf-8"))
        n = sum(
            1 for nodo in ast.walk(arbol)
            if isinstance(nodo, ast.Call)
            and isinstance(nodo.func, ast.Name)
            and nodo.func.id == "ViewerContext"
        )
        if n:
            encontrados[str(py.relative_to(APP.parent))] = n
    return encontrados


def test_el_constructor_de_contexto_es_el_unico_productor():
    """`principal -> constructor -> admin_full -> consumidores`, sin atajos.

    `authz/scope.py` tenia `UNRESTRICTED = VisibilityScope(ViewerContext(
    role="admin", admin_full=True))`: un contexto de potestad total fabricado a
    mano, fuera del productor, y por tanto invisible para cualquiera que fuese a
    buscar "quien concede admin_full" al sitio donde se concede. Ahora pasa por
    `build_internal_context()`, que es parte del mismo productor.
    """
    productores = _construcciones_de_contexto()
    assert productores, (
        "nadie construye un ViewerContext en app/: el barrido esta roto y este "
        "test estaria pasando con CERO casos"
    )
    intrusos = {r: n for r, n in productores.items() if r != PRODUCTOR}
    assert not intrusos, (
        f"{sorted(intrusos)} fabrican un ViewerContext esquivando el productor "
        f"({PRODUCTOR}). Un contexto construido a mano puede concederse a si "
        f"mismo `admin_full` sin pasar por la autoridad, y ninguna revocacion "
        f"en el constructor lo alcanzaria."
    )


def test_el_productor_construye_de_verdad_mas_de_un_contexto():
    """Contraveneno del test anterior: si el productor dejase de construir
    contextos, `intrusos` seguiria vacio y el test pasaria sin sostener nada."""
    assert _construcciones_de_contexto().get(PRODUCTOR, 0) >= 2


# --- `deny` es terminal, tambien para la potestad total ---------------------

def _nodo(**over):
    n = {"id": "n1", "workspace": "ws", "scope": "juego", "visibility": "player"}
    n.update(over)
    return n


ADMIN = ViewerContext(
    role="admin", allowed_workspaces=frozenset({"ws"}), admin_full=True,
    can_view_secret=True, can_view_future=True, can_view_reference=True,
)


def test_la_potestad_total_es_real_sobre_lo_que_si_puede_abrir():
    """Contraveneno: sin esto, `deny` podria estar denegando por otra razon."""
    assert POLICY.can_view(_nodo(workspace="otro", visibility="secret"), ADMIN).visible


@pytest.mark.parametrize("nivel", ["deny", "DENY", " deny "])
def test_deny_mas_admin_full_es_DENY(nivel):
    d = POLICY.can_view(_nodo(visibility=nivel), ADMIN)
    assert not d.visible, "FUGA: `deny` abierto por la potestad total"
    assert d.reason == "deny_absolute"


@pytest.mark.parametrize("nivel", ["publico", "", None, 7, {"x": 1}])
def test_una_visibilidad_invalida_tampoco_la_abre_admin_full(nivel):
    """Un bypass se salta reglas de PERMISO; no convierte un dato invalido en
    valido. Por eso la regla 0 va antes que la regla 1 en el motor."""
    d = POLICY.can_view(_nodo(visibility=nivel), ADMIN)
    assert not d.visible and d.reason == "visibility_invalid"


# --- el constructor: sin principal no hay potestad --------------------------

def test_desactivar_la_autenticacion_no_concede_potestad():
    from app.authz.context import build_viewer_context

    for rol in (None, "admin", "reviewer", "cualquier_cosa"):
        ctx = build_viewer_context(
            role=rol, auth_enabled=False, default_workspace="ws"
        )
        assert not ctx.admin_full, (
            f"`S9K_AUTH_ENABLED=false` concede `admin_full` (role={rol!r}): un "
            f"flag de despliegue vuelve a ser autoridad sobre la dimension mas "
            f"potente del sistema"
        )
        assert not ctx.can_view_secret and not ctx.can_view_reference, (
            f"sin autenticacion se conceden llaves de nivel (role={rol!r})"
        )
        assert ctx.role == "anonymous", (
            f"sin autenticacion el rol {rol!r} se sigue tomando por bueno, y no "
            f"lo ha verificado nadie"
        )


def test_el_valor_POR_DEFECTO_de_S9K_AUTH_ENABLED_no_concede_nada():
    """El caso que mas dano hizo, y que no era hipotetico.

    `AuthSettings.S9K_AUTH_ENABLED` vale **False por defecto**
    (`app/auth/config.py`). Combinado con el bypass que habia en el constructor,
    eso significaba que TODO proceso que no fijara la variable --un test, un
    banco de medida, un script, un despliegue recien montado-- corria con la
    potestad de bypass total puesta. Y ocurrio: el carril de saturacion
    descubrio que dos de sus bancos estaban midiendo con `admin_full` sin
    saberlo, es decir, midiendo el sistema sin ninguna barrera activa y
    creyendo que median el sistema.

    Que la barrera este apagada por defecto es una decision de despliegue
    discutible; que apagarla CONCEDA LA POTESTAD MAXIMA no lo es. Aqui se fija
    lo segundo: sin fijar la variable, minimo privilegio.
    """
    from app.auth.config import AuthSettings
    from app.authz.context import build_viewer_context

    por_defecto = AuthSettings(_env_file=None).S9K_AUTH_ENABLED
    assert por_defecto is False, (
        "ha cambiado el valor por defecto de S9K_AUTH_ENABLED; este test "
        "documenta el efecto de ese valor y hay que revisarlo"
    )

    ctx = build_viewer_context(
        role=None, auth_enabled=por_defecto, default_workspace="ws"
    )
    assert not ctx.admin_full, (
        "quien no fija S9K_AUTH_ENABLED vuelve a medir --o a servir-- con el "
        "bypass total puesto"
    )
    assert ctx.role == "anonymous"
    assert not ctx.can_view_secret and not ctx.can_view_reference
    assert not ctx.allowed_partida_ids
    assert ctx.max_visible_session == 0, (
        "sin autenticacion el tope de sesion deja de ser el minimo"
    )


def test_el_rol_admin_autenticado_SI_concede_potestad():
    """Ablacion inversa: la degradacion de arriba no puede ser un apagon."""
    from app.authz.context import build_viewer_context

    ctx = build_viewer_context(role="admin", auth_enabled=True, default_workspace="ws")
    assert ctx.admin_full


def test_el_contexto_interno_exige_un_motivo_declarado():
    from app.authz.context import build_internal_context

    for malo in ("", "   ", None):
        with pytest.raises(ValueError):
            build_internal_context(motivo=malo)
    assert build_internal_context(motivo="CLI de mantenimiento").admin_full
