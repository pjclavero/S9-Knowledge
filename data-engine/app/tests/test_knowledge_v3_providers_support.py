# -*- coding: utf-8 -*-
"""Utillaje compartido de los tests de la capa de proveedores V3.

No contiene tests: solo dobles de transporte y fixtures de datos. Vive junto a
los tests (y no en `conftest.py`) porque `conftest.py` no es propiedad de este
bloque y no debe tocarse.
"""
from __future__ import annotations

import json
import time
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
    """Doble de la respuesta de `urlopen`: un FLUJO con cursor, no un buffer.

    Devolver siempre el mismo prefijo en cada `read(n)` convertia al doble en
    algo que ningun servidor real hace, y ocultaba si el codigo bajo prueba
    consume el flujo correctamente.
    """

    def __init__(self, payload: Any, *, raw: Optional[bytes] = None) -> None:
        if raw is not None:
            self._raw = raw
        else:
            self._raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._pos = 0
        self.reads: list = []

    def read(self, amount: Optional[int] = None) -> bytes:
        self.reads.append(amount)
        if amount is None:
            chunk = self._raw[self._pos:]
            self._pos = len(self._raw)
            return chunk
        chunk = self._raw[self._pos:self._pos + amount]
        self._pos += len(chunk)
        return chunk

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False


class UnboundedReadResponse(FakeResponse):
    """Estalla si alguien llama a `read()` SIN limite.

    Sirve para fijar la propiedad "se corta antes de cargar en memoria": si el
    codigo vuelve a `resp.read()` a pelo, este doble lo delata en vez de
    tragarselo. Sin el, un mutante que leyese la respuesta entera sobrevivia.
    """

    def read(self, amount: Optional[int] = None) -> bytes:
        if amount is None:
            raise AssertionError(
                "se ha llamado a read() sin limite: la respuesta se estaria "
                "cargando entera en memoria antes de comprobar su tamano"
            )
        return super().read(amount)


class DrippingResponse:
    """Servidor que gotea: un byte por lectura, eternamente.

    Cada lectura individual cumple cualquier `timeout` de socket; sin plazo de
    pared, la llamada no termina nunca.
    """

    def __init__(self, byte: bytes = b"x", delay: float = 0.0) -> None:
        self._byte = byte
        self._delay = delay
        self.calls = 0

    def read(self, amount: Optional[int] = None) -> bytes:
        self.calls += 1
        if self._delay:
            time.sleep(self._delay)
        return self._byte

    def __enter__(self) -> "DrippingResponse":
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
        # Cualquier doble que sepa `read()` se devuelve tal cual; solo los
        # payloads planos se envuelven.
        if hasattr(item, "read"):
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


def make_outcome(tier=None, provider_name="ollama", model="qwen2.5:7b", **overrides):
    """`ProviderOutcome` sintetico y CORRECTO, como lo devolveria el router."""
    from knowledge_v3.providers import ProviderOutcome, Tier, V3Capability

    kwargs = dict(
        capability=V3Capability.EXTRACTION,
        ok=True,
        provider_name=provider_name,
        tier=tier or Tier.OLLAMA,
        model=model,
        result={"provider": provider_name, "model": model, "payload": {}},
    )
    kwargs.update(overrides)
    return ProviderOutcome(**kwargs)


def make_attribution(**overrides):
    """Atribucion VERIFICADA, por la unica via sancionada.

    Deliberadamente no construye `ProviderAttribution` a mano: los mapeadores
    rechazan las atribuciones sin verificar, y el utillaje de test no debe ser
    la puerta trasera que las cuele.
    """
    from knowledge_v3.providers import ProviderAttribution, Tier

    tier = overrides.pop("tier", Tier.OLLAMA)
    step = overrides.pop("step", None)
    model = overrides.pop("model", "qwen2.5:7b")
    name = overrides.pop("name", "s9k.extractor.ollama")
    version = overrides.pop("version", "3.0.0")

    if tier is Tier.LOCAL:
        attribution = ProviderAttribution.local(
            name=name, version=version, step=step or "extraction.local", model=model
        )
    else:
        outcome = make_outcome(tier=tier, provider_name=tier.value, model=model)
        attribution = outcome.attribution(name=name, version=version)
        if step is not None:
            from dataclasses import replace

            attribution = replace(attribution, step=step)
    return attribution
