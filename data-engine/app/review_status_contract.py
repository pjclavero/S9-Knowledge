"""Modulo FRONTERA del motor hacia `contracts/review-status/v1`.

Gemelo de `viewer/app/review_status_contract.py`. Ver alli el porque de que
haya dos y no uno: `viewer/` y `data-engine/app/` son arboles de `sys.path`
distintos que no se importan entre si, asi que uno por arbol es el minimo.

Vive en la RAIZ de `data-engine/app/` --no dentro de `review/` ni de
`schemas/`-- porque lo consumen modulos de las dos carpetas, y ese directorio
es el que ya esta en `sys.path` para todos ellos.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

#: `data-engine/app/review_status_contract.py` -> `app` -> `data-engine` -> raiz.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MODEL_PATH = _REPO_ROOT / "contracts" / "review-status" / "v1" / "model.py"

#: Mismo nombre que usa el modulo frontera del visor, a proposito: en la
#: corrida combinada los dos comparten la entrada de `sys.modules` y, con ella,
#: el mismo objeto `Enum`.
_MODULE_NAME = "s9k_review_status_v1_model"

if _MODULE_NAME in sys.modules:  # pragma: no cover - cache entre imports
    contrato = sys.modules[_MODULE_NAME]
else:
    _spec = importlib.util.spec_from_file_location(_MODULE_NAME, _MODEL_PATH)
    if _spec is None or _spec.loader is None:  # pragma: no cover
        raise ImportError(f"no se pudo cargar review-status/v1 en {_MODEL_PATH}")
    contrato = importlib.util.module_from_spec(_spec)
    sys.modules[_MODULE_NAME] = contrato
    _spec.loader.exec_module(contrato)

CANONICAL_VALUES = contrato.CANONICAL_VALUES
HUMAN_REVIEWED = contrato.HUMAN_REVIEWED
LEGACY_MACHINE_APPROVED = contrato.LEGACY_MACHINE_APPROVED
ReviewStatus = contrato.ReviewStatus
ReviewStatusError = contrato.ReviewStatusError
from_candidate_status = contrato.from_candidate_status
from_pipeline_decision = contrato.from_pipeline_decision
from_review_manual_status = contrato.from_review_manual_status
is_canonical = contrato.is_canonical
is_human_reviewed = contrato.is_human_reviewed
normalize = contrato.normalize
