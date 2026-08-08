"""Regresiones del tercer dictamen NO CONFORME (T3, T4, T5).

Tercera ronda de revision adversarial, tercer NO CONFORME. Estos tres son los
hallazgos contenidos; T1 y T2 --las reglas de party y sesion futura no estan
cableadas de extremo a extremo-- son una decision de producto, no un arreglo, y
van aparte.

El hilo comun con G1 sigue siendo el mismo: un dato de forma inesperada debe
comportarse como dato ausente, nunca como error. Un 500 no es fail-closed.
"""
from __future__ import annotations

import pytest

from app.policies.models import ViewerContext


# --- T3: `id` era el unico campo que el motor consumia sin tipar -------------

@pytest.mark.parametrize("valor", [[], {}, set(), 7, None])
def test_un_id_no_textual_no_revienta_knows(valor):
    """`nid in frozenset` daba `TypeError: unhashable type` con una lista.

    Era el unico campo sin tipar, y precisamente el que la red inversa del test
    de contrato descartaba a mano por considerarlo "identidad, no autorizacion".
    Se consume dentro de una decision de autorizacion.
    """
    ctx = ViewerContext(active_character="pc:ana", character_knowledge=frozenset({"n1"}))
    assert ctx.knows({"id": valor}) is False


def test_un_id_textual_sigue_concediendo_conocimiento():
    ctx = ViewerContext(active_character="pc:ana", character_knowledge=frozenset({"n1"}))
    assert ctx.knows({"id": "n1"}) is True


# --- T4: los agregadores tampoco pueden reventar -----------------------------

def test_quality_metrics_sobrevive_a_un_nodo_con_confianza_ilegible():
    """Un solo nodo VISIBLE con `confidence` textual convertia en 500
    `/quality` y `/api/quality` de todo el workspace."""
    from app.authz.filtered_provider import PolicyFilteredProvider

    nodos = [
        {"id": "a", "workspace": "ws", "scope": "juego", "visibility": "player",
         "confidence": 0.9, "type": "npc"},
        {"id": "b", "workspace": "ws", "scope": "juego", "visibility": "player",
         "confidence": "muy alta", "type": ["lista"]},
        {"id": "c", "workspace": "ws", "scope": "juego", "visibility": "player",
         "confidence": None, "type": "npc"},
    ]

    class _Prov:
        name = "fake"

        def workspaces(self):
            return ["ws"]

        def graph(self, workspace=None, **kw):
            return nodos, []

    ctx = ViewerContext(role="admin", admin_full=True,
                        allowed_workspaces=frozenset({"ws"}))
    prov = PolicyFilteredProvider(_Prov(), ctx)
    m = prov.quality_metrics("ws")
    assert m["total_entities"] == 3
    # La confianza ilegible se cuenta como ausente, no rompe ni miente.
    assert m["confidence_distribution"]["no_value"] == 2
    assert m["confidence_distribution"]["high_gte_0_8"] == 1
    # Y el `type` no textual no rompe la agrupacion por clave.
    assert m["by_entity_type"].get("npc") == 2


# --- T5: la ruta en disco es detalle operativo -------------------------------

def test_reviews_no_entrega_rutas_absolutas_a_un_reviewer(tmp_path, monkeypatch):
    """`redact_job` ya ocultaba el detalle operativo; este camino no.

    Un revisor necesita saber QUE hay en la cola, no donde vive el fichero en
    el disco del servidor.
    """
    from fastapi.testclient import TestClient

    import app.main as main_module
    from app.authz.scope import VisibilityScope

    fake_root = tmp_path / "repo"
    (fake_root / "output" / "reviews" / "leyenda" / "mi_fuente").mkdir(parents=True)
    monkeypatch.setattr(main_module, "REPO_ROOT", fake_root)
    revisor = VisibilityScope(ViewerContext(
        role="reviewer", allowed_workspaces=frozenset({"leyenda"})
    ))
    monkeypatch.setattr(main_module, "get_visibility_scope", lambda _r: revisor)

    r = TestClient(main_module.app).get("/reviews/mi_fuente?workspace=leyenda")
    assert r.status_code == 200
    assert str(fake_root) not in r.text
