"""Identificadores de revisión: workspace dentro, ":" fuera (carril I).

Dos defectos REALES encontrados al revisar `/reviews` y el caso del workspace
con ":" en el identificador (`viewer/app/services/review_console.py`):

1. `_stable_suffix` unía los campos con ``":".join(parts)``. El ":" no es un
   separador seguro aquí: es un carácter idiomático DENTRO de los
   identificadores de este repositorio (`partida:uno`, `pc:ana`, `human:<uuid>`,
   `ledger:<ws>:<seq>`). ``("a:b", "c")`` y ``("a", "b:c")`` daban el mismo
   hash.

2. Ningún llamador metía el `workspace` en el identificador, y el almacén de
   laboratorio es UNO y compartido (`lab_store_dir()`, un JSONL append-only).
   Dos workspaces con el mismo `candidate_id` producían `decision_id`,
   `event_id` y `document_id` IDÉNTICOS en el mismo fichero: la decisión de una
   partida era indistinguible de la de otra.

Lo que NO era un fallo, comprobado y anotado para que nadie lo re-audite: el
confinamiento de `/reviews` en disco (`_WORKSPACE_ID_RE` es una lista blanca sin
":" aplicada con `fullmatch`), la pertenencia al ámbito (comparación exacta de
cadenas contra un conjunto) y el aislamiento en SQLite/Neo4j (columnas y
parámetros, no claves de texto).
"""
from __future__ import annotations

import pytest

from app.services import review_console as rc

_HASH = {"algorithm": "sha256", "value": "b" * 64}
_TS = "2026-01-01T00:00:00Z"


def _candidato(workspace: str, candidate_id: str = "cand_1") -> dict:
    return {
        "workspace": workspace,
        "candidate_id": candidate_id,
        "source_id": "src1",
        "source_hash": {"algorithm": "sha256", "value": "a" * 64},
        "review_generation": 1,
        "canonical_name": "Ana",
    }


# ---------------------------------------------------------------------------
# 1. El separador ":" no puede desplazar el límite entre campos
# ---------------------------------------------------------------------------

def test_el_sufijo_estable_no_es_ambiguo_con_dos_puntos():
    assert rc._stable_suffix("a:b", "c") != rc._stable_suffix("a", "b:c")


def test_el_sufijo_estable_sigue_siendo_determinista():
    """Control positivo: la prueba anterior no pasa por ser aleatorio."""
    assert rc._stable_suffix("a", "b", "c") == rc._stable_suffix("a", "b", "c")
    assert len(rc._stable_suffix("a")) == 16


@pytest.mark.parametrize(
    "izq,der",
    [
        (("ws", "cand:1"), ("ws:cand", "1")),
        (("", "a"), ("", "", "a")),
        (("a", "b", "c"), ("a:b", "c")),
    ],
)
def test_ninguna_reagrupacion_de_campos_colisiona(izq, der):
    assert rc._stable_suffix(*izq) != rc._stable_suffix(*der)


# ---------------------------------------------------------------------------
# 2. El workspace entra en el identificador
# ---------------------------------------------------------------------------

def test_dos_workspaces_no_generan_el_mismo_decision_id():
    d1 = rc.build_decision(_candidato("leyenda"), "APPROVE", "ana", _HASH, decided_at=_TS)
    d2 = rc.build_decision(_candidato("otra"), "APPROVE", "ana", _HASH, decided_at=_TS)
    assert d1["decision_id"] != d2["decision_id"]
    assert d1["document_id"] != d2["document_id"]


def test_dos_workspaces_no_generan_el_mismo_event_id():
    e1 = rc.build_audit_event(_candidato("leyenda"), "DECISION_RECORDED", "ana", timestamp=_TS)
    e2 = rc.build_audit_event(_candidato("otra"), "DECISION_RECORDED", "ana", timestamp=_TS)
    assert e1["event_id"] != e2["event_id"]


def test_un_workspace_con_dos_puntos_no_se_confunde_con_otro():
    """El caso del enunciado: ":" dentro del nombre del workspace."""
    d1 = rc.build_decision(_candidato("partida:uno"), "APPROVE", "ana", _HASH, decided_at=_TS)
    d2 = rc.build_decision(_candidato("partida", "uno:cand_1"), "APPROVE", "ana",
                           _HASH, decided_at=_TS)
    assert d1["decision_id"] != d2["decision_id"]


def test_un_revisor_con_dos_puntos_no_se_confunde_con_el_timestamp():
    """El ":" del `reviewer_id` no puede fundirse con el campo anterior.

    Se ataca `_stable_suffix` directamente: por el ":" del final del timestamp,
    los dos vectores producían el mismo hash y por tanto el mismo
    `decision_id`. Con `build_decision` no se puede llegar aquí porque el
    esquema rechaza un `decided_at` malformado — pero el hash es el mecanismo,
    y el mecanismo no debe depender de que otro valide por él.
    """
    ws, cand, accion = "ws", "cand_1", "APPROVE"
    assert (
        rc._stable_suffix(ws, cand, accion, "2026-01-01T00:00:00Z", "pc:ana")
        != rc._stable_suffix(ws, cand, accion, "2026-01-01T00:00:00Z:pc", "ana")
    )


def test_el_mismo_workspace_y_los_mismos_campos_siguen_siendo_estables():
    """Control positivo: el id sigue siendo reproducible, no un uuid."""
    d1 = rc.build_decision(_candidato("leyenda"), "APPROVE", "ana", _HASH, decided_at=_TS)
    d2 = rc.build_decision(_candidato("leyenda"), "APPROVE", "ana", _HASH, decided_at=_TS)
    assert d1["decision_id"] == d2["decision_id"]


def test_cambiar_solo_la_accion_cambia_el_id():
    d1 = rc.build_decision(_candidato("ws"), "APPROVE", "ana", _HASH, decided_at=_TS)
    d2 = rc.build_decision(_candidato("ws"), "REJECT", "ana", _HASH, decided_at=_TS)
    assert d1["decision_id"] != d2["decision_id"]


# ---------------------------------------------------------------------------
# 3. El almacén compartido: dos partidas, un JSONL, sin ids repetidos
# ---------------------------------------------------------------------------

def test_el_almacen_compartido_no_mezcla_dos_partidas(tmp_path):
    """Escenario completo: el fichero es uno solo, los ids deben distinguirse."""
    decisiones = [
        rc.build_decision(_candidato(ws), "APPROVE", "ana", _HASH, decided_at=_TS)
        for ws in ("leyenda", "otra")
    ]
    ids = {d["decision_id"] for d in decisiones}
    assert len(ids) == 2, "dos partidas distintas comparten identificador de decisión"
    workspaces = {d["workspace"] for d in decisiones}
    assert workspaces == {"leyenda", "otra"}


def test_el_confinamiento_en_disco_sigue_rechazando_los_dos_puntos():
    """No era el fallo, pero se fija: ":" no es forma válida de un workspace-ruta."""
    from app import main as app_main

    assert app_main._WORKSPACE_ID_RE.fullmatch("partida:uno") is None
    assert app_main._WORKSPACE_ID_RE.fullmatch("leyenda") is not None
