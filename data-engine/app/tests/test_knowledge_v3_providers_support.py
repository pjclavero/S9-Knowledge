# -*- coding: utf-8 -*-
"""Utillaje compartido de los tests de la capa de proveedores V3.

No contiene tests: solo dobles de transporte y fixtures de datos. Vive junto a
los tests (y no en `conftest.py`) porque `conftest.py` no es propiedad de este
bloque y no debe tocarse.
"""
from __future__ import annotations

import json
import urllib.error
from typing import Any, Optional

WORKSPACE = "leyenda"
SOURCE_ASSET_ID = "asset:manual-001"
SOURCE_HASH = {
    "algorithm": "sha256",
    "value": "a900b2ece307794d62690e1ffbe35853112ebbdef8fe18061b62f896d38f23a2",
}
EPISODE_ID = "episode:manual-001:p12"
EPISODE_TEXT = (
    "Daiki jamas juro lealtad al Consejo de Umbra, pero si a la Casa del Ciervo."
)


class FakeResponse:
    """Doble de la respuesta de `urlopen`: context manager con `read(n)`."""

    def __init__(self, payload: Any, *, raw: Optional[bytes] = None) -> None:
        if raw is not None:
            self._raw = raw
        else:
            self._raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def read(self, amount: Optional[int] = None) -> bytes:
        return self._raw if amount is None else self._raw[:amount]

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False


class FakeTransport:
    """`urlopen` falso: guarda las peticiones y devuelve respuestas guionizadas.

    `script` es una lista de respuestas o excepciones. Si se agota, repite la
    ultima. Cualquier excepcion de la lista se LANZA en lugar de devolverse.
    """

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.requests: list = []
        self.calls = 0

    def __call__(self, req, timeout=None):  # noqa: D102
        self.calls += 1
        body = None
        if getattr(req, "data", None):
            body = json.loads(req.data.decode("utf-8"))
        self.requests.append(
            {
                "url": req.full_url,
                "method": req.get_method(),
                "headers": dict(req.headers),
                "body": body,
                "timeout": timeout,
            }
        )
        item = self.script[min(self.calls - 1, len(self.script) - 1)]
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, FakeResponse):
            return item
        return FakeResponse(item)


def http_error(code: int, headers: Optional[dict] = None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://example.invalid/v1/chat/completions",
        code=code,
        msg="error",
        hdrs=headers or {},  # type: ignore[arg-type]
        fp=None,
    )


def ollama_chat_response(content: Any, *, model: str = "qwen2.5:7b") -> dict:
    """Respuesta con la forma REAL de `/api/chat` de Ollama (verificada en vivo)."""
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    return {
        "model": model,
        "created_at": "2026-07-27T17:17:14.393786143Z",
        "message": {"role": "assistant", "content": content},
        "done": True,
        "done_reason": "stop",
        "total_duration": 8639756554,
        "load_duration": 252030550,
        "prompt_eval_count": 59,
        "eval_count": 43,
    }


def nvidia_chat_response(content: Any, *, model: str = "meta/llama-3.3-70b-instruct") -> dict:
    """Respuesta con la forma del contrato OpenAI-compatible."""
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    return {
        "id": "chatcmpl-test",
        "model": model,
        "choices": [
            {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}
        ],
        "usage": {"prompt_tokens": 42, "completion_tokens": 17, "total_tokens": 59},
    }


def make_anchor(text: str = EPISODE_TEXT, **overrides):
    from knowledge_v3.providers import LocalAnchor

    kwargs = dict(
        workspace=WORKSPACE,
        source_asset_id=SOURCE_ASSET_ID,
        source_hash=dict(SOURCE_HASH),
        episode_id=EPISODE_ID,
        episode_text=text,
        page=12,
    )
    kwargs.update(overrides)
    return LocalAnchor(**kwargs)


def make_attribution(**overrides):
    from knowledge_v3.providers import ProviderAttribution, Tier

    kwargs = dict(
        tier=Tier.OLLAMA,
        name="s9k.extractor.ollama",
        version="3.0.0",
        step="extraction.ollama",
        model="qwen2.5:7b",
    )
    kwargs.update(overrides)
    return ProviderAttribution(**kwargs)
