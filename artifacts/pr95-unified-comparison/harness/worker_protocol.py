# -*- coding: utf-8 -*-
"""Worker de la PISTA PROTOCOLO PROVEEDOR para la comparativa PR#95.

Se ejecuta DENTRO del worktree de una version (base/V2/V3), con SU
`relations.external_ai_shadow` en sys.path. Evalua un BANCO SINTETICO COMUN de
respuestas de un "modelo de competencia fija" contra el protocolo de la version.

OFFLINE por construccion: se inyecta un proveedor MOCK con `_post_chat` que
devuelve la respuesta pre-generada del banco. NUNCA se construye un proveedor real
ni se abre red. El mock cuenta las llamadas (para trazabilidad), pero jamas hace IO.

Contrato de entrada (stdin JSON):
  {
    "config": { "realignment_enabled"? , "fragment_protocol_enabled"?, "max_fragments"? },
    "cases": [
      {
        "case_id": str,
        "candidate": { ...campos de RelationCandidate... },
        "document_text": str,
        "response_content": str   # JSON string que emite el modelo (por protocolo)
      }, ...
    ]
  }

Contrato de salida (stdout JSON):
  {
    "results": [ { case_id, state, shadow_recommendation, validation_errors,
                   verdict, latency_ms, provider } ],
    "network_attempts": 0,          # el mock jamas abre socket
    "post_chat_calls": int,
    "shadow_mode": true
  }
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from relations.contracts import RelationCandidate  # noqa: E402
from relations.external_ai_shadow import (  # noqa: E402
    RelationExternalConfig,
    evaluate_relation_external,
)

# Contador global de intentos de red: cualquier acceso real incrementaria esto.
_NETWORK_ATTEMPTS = 0


class MockProvider:
    """Proveedor en memoria: devuelve la respuesta del banco. Cero IO, cero red."""

    provider_name = "synthetic-fixed-competence"

    def __init__(self, response_content: str, latency_ms: float = 12.0):
        self._content = response_content
        self._latency = latency_ms
        self.calls = 0

    def _post_chat(self, model, messages):
        # Se cuenta la llamada; NO se abre socket (banco pre-generado en memoria).
        self.calls = self.calls + 1
        response_json = {"choices": [{"message": {"content": self._content}}]}
        return response_json, self._latency


def main() -> None:
    job = json.loads(sys.stdin.read())
    cfg_in = job.get("config", {})
    cases = job["cases"]

    results = []
    post_chat_calls = 0

    for case in cases:
        cand_fields = dict(case["candidate"])
        document_text = case["document_text"]
        response_content = case["response_content"]
        latency = float(case.get("latency_ms", 12.0))

        mock = MockProvider(response_content, latency_ms=latency)
        config = RelationExternalConfig(
            model="synthetic-fixed-competence",
            provider=mock,
            shadow_mode=True,
            **cfg_in,
        )
        try:
            cand = RelationCandidate(**cand_fields).validate()
            evals = evaluate_relation_external(
                cand, config=config, document_text=document_text
            )
            ev = evals[0]
            d = ev.to_dict() if hasattr(ev, "to_dict") else {
                "candidate_id": ev.candidate_id,
                "state": ev.state,
                "shadow_recommendation": ev.shadow_recommendation,
                "verdict": ev.verdict,
                "validation_errors": ev.validation_errors,
                "latency_ms": ev.latency_ms,
                "provider": ev.provider,
            }
            d["case_id"] = case["case_id"]
            results.append(d)
        except Exception as exc:  # aislado por caso: el fallo no aborta el lote
            results.append({
                "case_id": case["case_id"],
                "state": "WORKER_ERROR",
                "shadow_recommendation": "human",
                "verdict": None,
                "validation_errors": [f"{type(exc).__name__}: {str(exc)[:180]}"],
                "latency_ms": None,
                "provider": "synthetic-fixed-competence",
            })
        post_chat_calls += mock.calls

    out = {
        "results": results,
        "network_attempts": _NETWORK_ATTEMPTS,  # siempre 0: mock puro
        "post_chat_calls": post_chat_calls,
        "shadow_mode": True,
    }
    sys.stdout.write(json.dumps(out, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
