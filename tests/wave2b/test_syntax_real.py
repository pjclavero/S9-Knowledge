# -*- coding: utf-8 -*-
"""Q — adaptador sintactico REAL (`relations.syntax`).

Punto 1 de la matriz: "proveedor sintactico descarga modelo". Se verifica que el
proveedor por DEFECTO (`heuristic`) NO descarga ni carga modelos al importar ni
al analizar (sin red), y que un proveedor pesado ausente (spaCy/Stanza) FALLA
CERRADO (`SyntaxProviderUnavailable`) en lugar de descargar nada.

Importa el modulo REAL: no se reimplementa el analizador.
"""
from __future__ import annotations

import socket

import pytest

from relations import syntax as mod
from relations.syntax import (
    HeuristicSyntaxAnalyzer,
    ExternalModelSyntaxAnalyzer,
    SyntaxAdapterError,
    SyntaxProviderUnavailable,
    analyze,
    get_analyzer,
)

TEXT = "Akodo lidera el Clan del Leon con honor."


# ---------------------------------------------------------------------------
# Comportamiento real basico
# ---------------------------------------------------------------------------
def test_default_provider_is_heuristic_and_offline():
    an = get_analyzer()
    assert isinstance(an, HeuristicSyntaxAnalyzer)
    assert an.name == "heuristic"
    assert an.available() is True
    res = analyze(TEXT)
    assert res.provider == "heuristic"
    # Offsets compatibles con el texto original.
    for sent in res.sentences:
        for tok in sent.tokens:
            assert TEXT[tok.start:tok.end] == tok.text


def test_external_provider_fails_closed_not_download():
    ext = ExternalModelSyntaxAnalyzer("spacy")
    assert ext.available() is False
    with pytest.raises(SyntaxProviderUnavailable):
        ext.analyze(TEXT)
    # La fabrica tambien falla cerrado para proveedores pesados no instalados.
    with pytest.raises(SyntaxProviderUnavailable):
        get_analyzer("spacy")
    with pytest.raises(SyntaxProviderUnavailable):
        get_analyzer("stanza")


def test_unknown_provider_is_rejected():
    with pytest.raises(SyntaxAdapterError):
        get_analyzer("no_existe")


# ---------------------------------------------------------------------------
# MUTATION 1 (punto 1): el proveedor por defecto NO abre red ni descarga modelo;
# el proveedor pesado ausente falla cerrado en vez de descargar.
# ---------------------------------------------------------------------------
@pytest.mark.mutation
def test_mutation_default_syntax_never_opens_socket_or_downloads(monkeypatch):
    """La ruta por defecto (heuristic) es load-bearing: 100% offline.

    Mutacion: si el proveedor por defecto cargara/descargara un modelo, abriria
    un socket -> aqui `socket.socket` esta minado y cualquier apertura ABORTA el
    test. El proveedor real analiza sin tocar red. Ademas, pedir spaCy/Stanza
    (no instalados) debe fallar CERRADO, nunca descargar: si se relajara a
    "descarga bajo demanda", esta comprobacion lo detectaria.
    """
    def _boom(*a, **k):  # pragma: no cover - solo se ejecuta si algo abre red
        raise AssertionError("el proveedor sintactico por defecto NO debe abrir red")

    monkeypatch.setattr(socket, "socket", _boom)

    # Control: el proveedor real funciona 100% offline (la regla se cumple).
    res = analyze(TEXT)
    assert res.provider == "heuristic"
    assert res.sentences  # produjo estructura sin red

    # Rechazo real: proveedor pesado ausente falla cerrado (no descarga nada).
    with pytest.raises(SyntaxProviderUnavailable):
        get_analyzer("spacy").analyze(TEXT)
