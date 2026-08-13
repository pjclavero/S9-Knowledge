"""Modulo FRONTERA del visor hacia `contracts/review-status/v1`.

Mismo patron y misma razon que `app/authz/visibility_contract.py`: el contrato
vive fuera de todo arbol de paquetes (para que visor y motor lo compartan sin
duplicarlo), asi que hay que cargarlo por RUTA de fichero. Esa carga es seis
lineas de `importlib`, y estuvo COPIADA cuatro veces --una por consumidor--,
cada copia con su propio `parents[N]`.

Cuatro copias de la misma carga en un carril cuyo encargo era eliminar segundas
declaraciones es exactamente la ironia que hay que evitar: cada copia es un
sitio donde el `parents[N]` puede quedarse desfasado si el fichero se mueve, y
el fallo seria un `ImportError` en produccion, no en la copia que alguien
recordo actualizar.

Hay DOS modulos frontera, no uno, y no por descuido: `viewer/` y
`data-engine/app/` son dos arboles de `sys.path` distintos que no pueden
importarse entre si (ver el docstring del `conftest.py` de la raiz). Uno por
arbol es el minimo posible; el equivalente del motor es
`data-engine/app/review_status_contract.py`.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

#: `viewer/app/review_status_contract.py` -> `viewer/app` -> `viewer` -> raiz.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MODEL_PATH = _REPO_ROOT / "contracts" / "review-status" / "v1" / "model.py"

#: Nombre COMPARTIDO con el modulo frontera del motor: en la corrida combinada
#: los dos arboles cargan el mismo fichero, y compartir la entrada de
#: `sys.modules` garantiza que tambien comparten el mismo objeto `Enum`. Con dos
#: nombres distintos habria dos clases `ReviewStatus` no identicas entre si, y
#: una comparacion `is` entre ellas fallaria sin motivo aparente.
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
etiquetar = contrato.etiquetar
is_canonical = contrato.is_canonical
is_human_reviewed = contrato.is_human_reviewed
normalize = contrato.normalize
