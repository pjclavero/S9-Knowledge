# -*- coding: utf-8 -*-
"""Tests de cache idempotente (Fase B1).

Tests 9-11: idempotencia, cache hit, invalidacion.
"""
import pytest
from pathlib import Path
import sys

_APP = Path(__file__).resolve().parent.parent.parent
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from external_processing.cache import ProcessingCache, build_cache_key


# ── Test 9: misma clave -> mismo job reutilizado ─────────────────────────────

def test_cache_misma_clave_reutiliza(tmp_path):
    """Misma clave de cache devuelve el mismo resultado."""
    cache = ProcessingCache(tmp_path, enabled=True)
    key = build_cache_key("src_hash", "external_transcribe", "audio:0.0-60.0", "mock", "mock-asr")

    result = {"text": "Transcripcion de prueba", "source_hash": "src_hash"}
    cache.put(key, result)

    retrieved = cache.get(key)
    assert retrieved is not None
    assert retrieved["result"]["text"] == "Transcripcion de prueba"


def test_cache_clave_determinista():
    """La misma entrada siempre genera la misma clave."""
    k1 = build_cache_key("h1", "external_ocr", "pdf:1-20", "mock", "mock-ocr")
    k2 = build_cache_key("h1", "external_ocr", "pdf:1-20", "mock", "mock-ocr")
    assert k1 == k2


# ── Test 10: cache hit no crea nuevo job ─────────────────────────────────────

def test_cache_hit_no_duplica(tmp_path):
    """Si existe cache, no se crea un segundo job con el mismo resultado."""
    cache = ProcessingCache(tmp_path, enabled=True)
    key = build_cache_key("src", "external_transcribe", "audio:0-120", "mock", "model-v1")

    # No existe aun
    assert cache.get(key) is None
    assert not cache.exists(key)

    # Almacenar
    cache.put(key, {"text": "Texto", "source_hash": "src"})

    # Ahora existe
    assert cache.exists(key)
    hit = cache.get(key)
    assert hit is not None
    assert hit["result"]["text"] == "Texto"


# ── Test 11: cambio de modelo invalida cache ──────────────────────────────────

def test_cache_invalida_al_cambiar_modelo():
    """Claves con diferentes modelos son distintas (cache no comparte)."""
    k_model_a = build_cache_key("src", "external_transcribe", "audio:0-60", "mock", "model-v1")
    k_model_b = build_cache_key("src", "external_transcribe", "audio:0-60", "mock", "model-v2")
    assert k_model_a != k_model_b


def test_cache_invalida_con_parametros_distintos():
    """Parametros diferentes -> claves distintas."""
    k1 = build_cache_key("src", "external_transcribe", "audio:0-60", "mock", "m", parameters={"lang": "es"})
    k2 = build_cache_key("src", "external_transcribe", "audio:0-60", "mock", "m", parameters={"lang": "en"})
    assert k1 != k2


def test_cache_invalidar_entrada(tmp_path):
    """invalidate() elimina la entrada."""
    cache = ProcessingCache(tmp_path, enabled=True)
    key = build_cache_key("s", "t", "r", "p", "m")
    cache.put(key, {"data": "x"})
    assert cache.exists(key)
    removed = cache.invalidate(key)
    assert removed is True
    assert not cache.exists(key)


def test_cache_deshabilitada_no_devuelve_nada(tmp_path):
    """Cache deshabilitada siempre devuelve None."""
    cache = ProcessingCache(tmp_path, enabled=False)
    key = build_cache_key("s", "t", "r", "p", "m")
    cache.put(key, {"data": "x"})
    assert cache.get(key) is None


def test_cache_clear_all(tmp_path):
    """clear_all() elimina todas las entradas."""
    cache = ProcessingCache(tmp_path, enabled=True)
    for i in range(5):
        k = build_cache_key(f"s{i}", "t", "r", "p", "m")
        cache.put(k, {"i": i})
    count = cache.clear_all()
    assert count == 5
