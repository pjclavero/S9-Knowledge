# -*- coding: utf-8 -*-
"""Anclas de conducta de OCHO guardas de garantia RC (carril 5, V3.1).

Por que existe este fichero
---------------------------
El revisor independiente del carril no cambio el codigo: DESTRUYO la guarda
--envolvio cada `raise` en `if False:`, preservando el censo AST de 71 sitios
sellados para no contaminar la medida-- y los 5255 tests siguieron VERDES. Ocho
guardas resultaron indefensas:

    assertions.py    CHAIN_SEQ_GAP               append-only / cadena de custodia
    assertions.py    SUPERSEDE_TARGET_EXISTS     supersesion
    supersession.py  VALIDITY_INVERTED           supersesion
    supersession.py  SUPERSESSION_CYCLE          supersesion
    ingest_approved  WRITE_PROVENANCE_INCOMPLETE procedencia
    supersede_review SOURCE_MODIFIED_DURING      anti-TOCTOU
    supersede_review WRITTEN_SHA_MISMATCH        anti-TOCTOU
    supersede_review SOURCE_MODIFIED_AFTER       anti-TOCTOU

Las ocho caen dentro de las propiedades que el propio criterio de INCLUSION del
carril nombra como garantias RC (`tests/carril5_deuda.py`). Regla del operador:
si una mutacion puede destruir una propiedad declarada para el RC y todos los
instrumentos siguen verdes, es bloqueante. Da igual que ya estuviesen indefensas
en `aaf9695` y que el carril no las introdujera: hoy estan NOMBRADAS.

Cada prueba de aqui es un ANCLA UNICA: neutralizar su guarda pone roja esta
prueba y ninguna otra (medido con `tools/carril5_negative_controls.py guards`,
control negativo una guarda por vez, reversion por SHA-256).

Un noveno caso que NO se ancla, y por que
-----------------------------------------
`review/ingest_approved.py:829::REAL_INGEST_NOT_AUTHORIZED` --la comprobacion de
`S9K_ALLOW_REAL_INGEST` dentro de `run()`, el punto de entrada del CLI-- NO
rompe la no-escritura al neutralizarse: es una capa redundante. `run()` no
escribe nada por si mismo; delega en `ingest()`, y la guarda EQUIVALENTE de
`ingest()` (linea 574, mismo codigo, misma variable de entorno) SI esta anclada
y enrojece --`test_use_existing.py:324` y `:339`,
`raises_code(RuntimeError, WriterCodes.REAL_INGEST_NOT_AUTHORIZED)`--. Quitar la
de `run()` deja la de `ingest()` cerrando el paso. Se deja tal cual: declarado,
no anclado, y no se vende como si lo estuviera.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1]
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from tests.exception_codes import raises_code  # noqa: E402

pytest.importorskip("jsonschema")

from knowledge_v3.ledger.codes import LedgerCodes  # noqa: E402
from review.codes import SupersedeCodes, WriterCodes  # noqa: E402


# ==========================================================================
# 1-2. Ledger: cadena de custodia y supersesion (assertions.py)
# ==========================================================================
from knowledge_v3.ledger import (  # noqa: E402
    InMemoryLedgerStore,
    JsonlLedgerStore,
    LedgerError,
    LedgerIntegrityError,
    TemporalLedger,
)
from knowledge_v3.ledger.supersession import chain_from, close_validity  # noqa: E402
from test_knowledge_v3_ledger import WORKSPACE, _successor, make_assertion  # noqa: E402


def test_ancla_chain_seq_gap_una_entrada_desaparecida_rompe_la_verificacion(tmp_path):
    """APPEND-ONLY. Arrancar una linea del JSONL deja la numeracion con hueco.

    Sin esta guarda, un ledger al que le falta una entrada intermedia se lee
    como valido: exactamente la forma de borrar historia que el append-only
    promete detectar.
    """
    path = tmp_path / "ledger.jsonl"
    led = TemporalLedger(WORKSPACE, JsonlLedgerStore(path))
    led.assert_fact(make_assertion())
    led.confirm("assertion:0001", recorded_at="2026-02-01T09:00:00Z",
                evidence_fragment_ids=["fragment:p20:1"], confidence=0.9)
    led.supersede("assertion:0001", _successor())
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) >= 3
    del rows[1]  # queda seq 0, 2, 3...: hueco
    path.write_text("".join(
        json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
        for r in rows), encoding="utf-8")
    with raises_code(LedgerIntegrityError, LedgerCodes.CHAIN_SEQ_GAP):
        TemporalLedger(WORKSPACE, JsonlLedgerStore(path)).verify_chain()


def test_ancla_supersede_target_exists_la_version_nueva_no_puede_ya_existir():
    """SUPERSESION. Una supersesion CREA un registro nuevo.

    Sin esta guarda, superceder hacia un `assertion_id` que ya vive en el ledger
    dejaria dos historias distintas colgando de la misma identidad logica.
    """
    led = TemporalLedger(WORKSPACE, InMemoryLedgerStore())
    led.assert_fact(make_assertion())
    led.assert_fact(make_assertion("assertion:0002", subject="entity:hantei"))
    colision = _successor()
    colision["assertion_id"] = "assertion:0002"
    with raises_code(LedgerError, LedgerCodes.SUPERSEDE_TARGET_EXISTS):
        led.supersede("assertion:0001", colision)


# ==========================================================================
# 3-4. Supersesion pura (supersession.py)
# ==========================================================================
def test_ancla_validity_inverted_no_se_puede_cerrar_antes_de_empezar():
    """SUPERSESION. `valid_to` anterior a `valid_from` es un hecho imposible.

    Sin esta guarda, el ledger aceptaria vigencias invertidas y cualquier
    consulta as-of sobre ese tramo devolveria basura silenciosa.
    """
    previo = {
        "assertion_id": "assertion:0001",
        "valid_from": "1041-06-01T00:00:00Z",
        "valid_to": None,
        "state": "ACTIVE",
    }
    with raises_code(LedgerError, LedgerCodes.VALIDITY_INVERTED):
        close_validity(previo, successor_id="assertion:0002",
                       valid_to="1041-01-01T00:00:00Z")


class _plazo:
    """Convierte un cuelgue en un ROJO atribuible.

    Existe por una medida, y conviene contarla EXACTA porque la primera version
    de este comentario la conto mal.

    En el arbol de la revision, neutralizar `SUPERSESSION_CYCLE` daba un VERDE
    de verdad, no un cuelgue: ninguna prueba ejercitaba un ciclo, asi que el
    bucle no llegaba a recorrerse. Es decir, era una guarda genuinamente
    indefensa, como las otras siete.

    El `rc=-9` aparece en ESTE arbol, y aparece PRECISAMENTE porque el ancla de
    abajo si ejercita un ciclo. O sea: anadir el ancla no descubrio un cuelgue
    preexistente; convirtio aquel verde en un cuelgue. Las dos medidas son
    correctas sobre arboles distintos.

    Que la guarda sea lo UNICO que acota el bucle esta verificado aparte por la
    revision: neutralizada, `chain_from` sobre `a -> b -> a` bajo `RLIMIT_AS`
    levanta `MemoryError`. De ahi este plazo: un proceso muerto no es un rojo
    --no se atribuye a ninguna prueba y, en CI, se parece demasiado a "todavia
    esta corriendo"--, y con el plazo la ausencia de la guarda falla esta prueba
    y solo esta.
    """

    def __init__(self, segundos: float) -> None:
        self._segundos = segundos

    def __enter__(self):
        import signal

        def _vencido(signum, frame):
            raise AssertionError(
                "la llamada no termino en %s s: sin la guarda de ciclo, "
                "`chain_from` recorre la cadena para siempre" % self._segundos)

        self._previo = signal.signal(signal.SIGALRM, _vencido)
        signal.setitimer(signal.ITIMER_REAL, self._segundos)
        return self

    def __exit__(self, *exc):
        import signal
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, self._previo)
        return False


def test_ancla_supersession_cycle_una_cadena_que_se_muerde_la_cola_es_corrupcion():
    """SUPERSESION. Un ciclo no es un caso raro: es un ledger corrupto.

    Sin esta guarda `chain_from` no devuelve nunca: la guarda es lo UNICO que
    acota el recorrido (verificado por la revision: neutralizada, un ciclo
    `a -> b -> a` bajo `RLIMIT_AS` levanta `MemoryError`).

    Y por eso ESTA prueba es la que convierte aquella guarda de indefendida en
    anclada: antes de existir, ninguna prueba entraba en el bucle, asi que
    neutralizar la guarda daba un verde limpio. Al ejercitar el ciclo, la
    ausencia de la guarda pasa a matar el proceso; el plazo (ver `_plazo`) la
    convierte en un rojo atribuible.
    """
    docs = {
        "assertion:0001": {"superseded_by": "assertion:0002"},
        "assertion:0002": {"superseded_by": "assertion:0001"},
    }
    with _plazo(2.0):
        with raises_code(LedgerError, LedgerCodes.SUPERSESSION_CYCLE):
            chain_from(docs, "assertion:0001")


# ==========================================================================
# 5. Procedencia del writer (review/ingest_approved.py)
# ==========================================================================
from review.ingest_approved import ingest  # noqa: E402
from test_safe_writer import _ent, _write  # noqa: E402


def test_ancla_write_provenance_incomplete_sin_procedencia_no_se_escribe(tmp_path):
    """PROCEDENCIA. Bajo `full_human_review` una entidad nueva sin procedencia
    explicita hace ABORTAR el lote entero, tambien en dry-run.

    Sin esta guarda el paquete pasaria a la fase de escritura y crearia nodos
    cuya procedencia nadie podria reconstruir. La regla de §6 es "sin defaults
    silenciosos": si falta, se rechaza; no se rellena.
    """
    previa = os.environ.get("S9K_REVIEW_POLICY")
    os.environ["S9K_REVIEW_POLICY"] = "full_human_review"
    try:
        sin_procedencia = _ent(knowledge_layer="")
        with raises_code(ValueError, WriterCodes.WRITE_PROVENANCE_INCOMPLETE):
            ingest(_write(tmp_path, [sin_procedencia]), dry_run=True, neo4j_password="x")
    finally:
        if previa is None:
            os.environ.pop("S9K_REVIEW_POLICY", None)
        else:
            os.environ["S9K_REVIEW_POLICY"] = previa


# ==========================================================================
# 6-8. Anti-TOCTOU de la supersesion revisada (review/supersede_review.py)
# ==========================================================================
from review import supersede_review as sr  # noqa: E402
from test_supersede_review import (  # noqa: E402
    _CORRECTION_REASON,
    _FIXTURE,
    _REVIEWED_BY,
)


def _copia_escribible(tmp_path):
    """Copia local del fixture: el original del repo NO se toca jamas."""
    dst = tmp_path / "original.json"
    shutil.copy2(_FIXTURE, dst)
    return dst, hashlib.sha256(dst.read_bytes()).hexdigest()


def test_ancla_source_modified_during_el_original_cambia_a_mitad_de_ejecucion(tmp_path, monkeypatch):
    """ANTI-TOCTOU. Entre la verificacion inicial del SHA y la escritura, algo
    reescribe el original. La ejecucion debe abortar SIN escribir.

    El escenario se provoca de verdad --un efecto lateral real toca el fichero
    de entrada durante la transformacion-- no falseando el hash.
    """
    inp, sha = _copia_escribible(tmp_path)
    out = tmp_path / "v2.json"
    supersede_real = sr.supersede

    def supersede_que_ensucia_la_entrada(*a, **kw):
        resultado = supersede_real(*a, **kw)
        inp.write_bytes(inp.read_bytes() + b"\n")  # TOCTOU real
        return resultado

    monkeypatch.setattr(sr, "supersede", supersede_que_ensucia_la_entrada)
    with raises_code(SystemExit, SupersedeCodes.SOURCE_MODIFIED_DURING):
        sr.run(inp_path=str(inp), supersedes_sha256=sha, out_path=str(out),
               reviewed_by=_REVIEWED_BY, correction_reason=_CORRECTION_REASON)
    assert not out.exists(), "abortar significa NO dejar salida escrita"


def test_ancla_written_sha_mismatch_una_escritura_corrupta_no_se_da_por_buena(tmp_path, monkeypatch):
    """ANTI-TOCTOU. El SHA de lo escrito debe coincidir con el de lo calculado.

    Sin esta guarda, una escritura atomica que devolviese contenido distinto del
    verificado se reportaria como `status: OK` con un `new_sha256` que no
    corresponde a ningun archivo real.
    """
    inp, sha = _copia_escribible(tmp_path)
    out = tmp_path / "v2.json"
    escritura_real = sr.write_atomic

    def escritura_corrupta(path, data):
        escritura_real(path, data)
        return "f" * 64  # el disco no quedo como creiamos

    monkeypatch.setattr(sr, "write_atomic", escritura_corrupta)
    with raises_code(SystemExit, SupersedeCodes.WRITTEN_SHA_MISMATCH):
        sr.run(inp_path=str(inp), supersedes_sha256=sha, out_path=str(out),
               reviewed_by=_REVIEWED_BY, correction_reason=_CORRECTION_REASON)


def test_ancla_source_modified_after_carrera_detectada_tras_escribir(tmp_path, monkeypatch):
    """ANTI-TOCTOU. Si el original cambio DESPUES de escribir, hay una carrera:
    el resultado se genero desde una entrada que ya no existe.

    Sin esta guarda el informe diria `original_modified: False` sobre un
    original que si fue modificado.
    """
    inp, sha = _copia_escribible(tmp_path)
    out = tmp_path / "v2.json"
    escritura_real = sr.write_atomic

    def escribe_y_hay_carrera(path, data):
        escrito = escritura_real(path, data)
        inp.write_bytes(inp.read_bytes() + b"\n")  # carrera despues de escribir
        return escrito

    monkeypatch.setattr(sr, "write_atomic", escribe_y_hay_carrera)
    with raises_code(SystemExit, SupersedeCodes.SOURCE_MODIFIED_AFTER):
        sr.run(inp_path=str(inp), supersedes_sha256=sha, out_path=str(out),
               reviewed_by=_REVIEWED_BY, correction_reason=_CORRECTION_REASON)
