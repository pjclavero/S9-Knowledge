# -*- coding: utf-8 -*-
"""Tests de chunking de audio, PDF, imagenes y texto (Fase B1).

Tests 6-8.
"""
import pytest
from pathlib import Path
import sys

_APP = Path(__file__).resolve().parent.parent.parent
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from external_processing.chunking import chunk_audio, chunk_pdf, chunk_images, chunk_text, chunk_range_key


# ── Test 6: audio chunking ───────────────────────────────────────────────────

def test_audio_chunk_unico_duracion_corta():
    """Audio corto (< max) -> un solo chunk."""
    chunks = chunk_audio("src_hash", 300.0, max_chunk_seconds=600.0)  # 5 min < 10 min
    assert len(chunks) == 1
    assert chunks[0].chunk_start == 0.0
    assert chunks[0].chunk_end == 300.0
    assert chunks[0].overlap_start == 0.0
    assert chunks[0].overlap_end == 0.0


def test_audio_chunk_multiple_con_overlap():
    """Audio largo -> multiples chunks con solapamiento correcto."""
    # 1200s con chunks de 600s y overlap de 2s
    chunks = chunk_audio("hash", 1200.0, max_chunk_seconds=600.0, overlap_seconds=2.0)
    assert len(chunks) >= 2

    # Primer chunk: sin overlap al inicio
    assert chunks[0].overlap_start == 0.0
    # Ultimo chunk: sin overlap al final
    assert chunks[-1].overlap_end == 0.0
    # Chunks del medio: tienen overlap
    if len(chunks) > 2:
        assert chunks[1].overlap_start > 0.0

    # El rango cubre toda la duracion
    assert chunks[0].chunk_start == 0.0
    assert chunks[-1].chunk_end == pytest.approx(1200.0, abs=1.0)


def test_audio_chunk_vacio():
    """Audio de duracion cero -> lista vacia."""
    chunks = chunk_audio("h", 0.0)
    assert chunks == []


def test_audio_chunk_indices_consecutivos():
    """Los indices de chunk son consecutivos desde 0."""
    chunks = chunk_audio("h", 900.0, max_chunk_seconds=300.0)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_audio_chunk_preserva_source_hash():
    """Todos los chunks preservan el source_hash."""
    source_hash = "abc123" * 10
    chunks = chunk_audio(source_hash, 1200.0, max_chunk_seconds=300.0)
    for c in chunks:
        assert c.source_hash == source_hash


# ── Test 7: PDF chunking ──────────────────────────────────────────────────────

def test_pdf_chunk_pocas_paginas():
    """PDF con pocas paginas -> un solo chunk."""
    chunks = chunk_pdf("doc_hash", 10, max_pages_per_chunk=20)
    assert len(chunks) == 1
    assert chunks[0].page_start == 1
    assert chunks[0].page_end == 10


def test_pdf_chunk_muchas_paginas():
    """PDF con muchas paginas -> multiples chunks."""
    chunks = chunk_pdf("doc_hash", 60, max_pages_per_chunk=20)
    assert len(chunks) == 3
    assert chunks[0].page_start == 1
    assert chunks[0].page_end == 20
    assert chunks[1].page_start == 21
    assert chunks[1].page_end == 40
    assert chunks[2].page_start == 41
    assert chunks[2].page_end == 60


def test_pdf_chunk_preserva_document_hash():
    """Todos los chunks PDF preservan document_hash."""
    chunks = chunk_pdf("doc_hash", 100, max_pages_per_chunk=30)
    for c in chunks:
        assert c.document_hash == "doc_hash"


def test_pdf_chunk_no_superpone_paginas():
    """Los chunks de PDF no se superponen."""
    chunks = chunk_pdf("h", 100, max_pages_per_chunk=20)
    for i in range(len(chunks) - 1):
        assert chunks[i].page_end + 1 == chunks[i + 1].page_start


def test_pdf_chunk_vacio():
    """PDF sin paginas -> lista vacia."""
    assert chunk_pdf("h", 0) == []


# ── Test 8: imagen: un job por imagen ────────────────────────────────────────

def test_imagen_un_task_por_imagen():
    """Cada imagen genera exactamente un ImageTask."""
    paths = ["img_0.jpg", "img_1.jpg", "img_2.jpg"]
    tasks = chunk_images("src_hash", paths)
    assert len(tasks) == 3
    for i, t in enumerate(tasks):
        assert t.image_index == i
        assert t.source_hash == "src_hash"


def test_imagen_hashes_distintos():
    """Imagenes distintas generan image_hashes distintos."""
    tasks = chunk_images("src", ["img_a.jpg", "img_b.jpg"])
    assert tasks[0].image_hash != tasks[1].image_hash


def test_imagen_lista_vacia():
    """Sin imagenes -> lista vacia."""
    assert chunk_images("src", []) == []


# ── Tests de texto ────────────────────────────────────────────────────────────

def test_texto_chunk_corto():
    """Texto corto -> un solo chunk."""
    text = "Texto de prueba"
    chunks = chunk_text("src", text, max_chars=100)
    assert len(chunks) == 1
    assert chunks[0].offset_start == 0
    assert chunks[0].offset_end == len(text)


def test_texto_chunk_largo():
    """Texto largo -> multiples chunks sin solapamiento."""
    text = "a" * 200
    chunks = chunk_text("src", text, max_chars=50)
    assert len(chunks) >= 4
    # Cubren todo el texto
    reconstructed = "".join(text[c.offset_start:c.offset_end] for c in chunks)
    assert reconstructed == text


def test_chunk_range_key_audio():
    """chunk_range_key para AudioChunk devuelve formato correcto."""
    chunks = chunk_audio("h", 120.0, max_chunk_seconds=600.0)
    key = chunk_range_key(chunks[0])
    assert key.startswith("audio:")
