"""M5b-1 -- estampado de visibilidad en el escritor.

Traduce un `KnowledgeVisibilityV1` validado a las propiedades planas que
acepta Neo4j, y las marca como reservadas para que ningun payload pueda
imponerlas.

Por que aqui y no en el motor de politicas: el motor DECIDE con lo que hay
escrito; si lo escrito viene de un payload sin validar, la decision es
correcta sobre un dato falso. El estampado es el unico punto donde el valor
entra al grafo, asi que es el unico sitio donde puede garantizarse.

Regla a prueba de fallos, decidida por el operador: una visibilidad ausente,
vacia, desconocida o invalida NUNCA puede acabar en algo visible. En lectura
eso se traduce en DENY (M5b-2). En escritura no puede traducirse en DENY --
seria escribir un hecho que nadie podra ver jamas, incluido su autor-- asi
que se traduce en el nivel legitimo mas restrictivo, `secret`, y se deja
constancia de que fue un valor por defecto y no una decision.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

_MODULE_NAME = "s9k_knowledge_visibility_v1"

_CONTRACT_PATH = (
    Path(__file__).resolve().parents[4] / "contracts" / "knowledge-visibility" / "v1" / "model.py"
)


def _load_contract() -> Any:
    """El directorio lleva guiones, asi que no es un paquete importable."""
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, _CONTRACT_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - fallo de instalacion
        raise RuntimeError(f"no se pudo cargar el contrato en {_CONTRACT_PATH}")
    module = importlib.util.module_from_spec(spec)
    # Registrar ANTES de ejecutar: `@dataclass` resuelve las anotaciones
    # buscando el modulo en `sys.modules`, y si no esta falla con un
    # AttributeError sobre None que no dice nada de la causa real.
    sys.modules[_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception:  # pragma: no cover - no dejar un modulo a medias registrado
        del sys.modules[_MODULE_NAME]
        raise
    return module


_contract = _load_contract()

KnowledgeVisibilityV1 = _contract.KnowledgeVisibilityV1
VisibilityLevel = _contract.VisibilityLevel
ContractVisibilityError = _contract.ContractVisibilityError

#: Propiedades que este modulo estampa y que un payload no puede sobrescribir.
VISIBILITY_PROPS = frozenset({"visibility", "known_by", "visibility_contract", "visibility_source"})

#: Nivel usado cuando quien escribe no declara visibilidad. El mas restrictivo
#: que sigue siendo un nivel legitimo: `deny` es terminal y haria el hecho
#: irrecuperable incluso para el narrador.
DEFAULT_LEVEL = VisibilityLevel.SECRET

SOURCE_EXPLICIT = "explicit"
SOURCE_DEFAULT = "default_fail_closed"


class VisibilityStampError(ValueError):
    """El payload intento imponer la visibilidad, o el contrato no valida."""


def normalize(visibility: Any) -> KnowledgeVisibilityV1:
    """Devuelve un contrato validado a partir de lo que traiga quien escribe.

    Acepta un `KnowledgeVisibilityV1` ya construido, un dict conforme al
    contrato, o `None` (se aplica el defecto restrictivo). Cualquier otra cosa
    --incluida una cadena suelta como `"player"`-- se rechaza: aceptar cadenas
    sueltas es exactamente como se cuela un valor sin validar.
    """
    if visibility is None:
        return KnowledgeVisibilityV1(visibility=DEFAULT_LEVEL)
    if isinstance(visibility, KnowledgeVisibilityV1):
        return visibility
    if isinstance(visibility, dict):
        try:
            return KnowledgeVisibilityV1.from_dict(visibility)
        except ContractVisibilityError as exc:
            raise VisibilityStampError(f"visibilidad no conforme al contrato: {exc}") from exc
    raise VisibilityStampError(
        "visibility debe ser KnowledgeVisibilityV1, dict conforme o None; "
        f"recibido {type(visibility).__name__}"
    )


def to_props(contract: KnowledgeVisibilityV1, *, explicit: bool) -> dict[str, Any]:
    """Propiedades planas para Neo4j. `known_by` va como lista de cadenas.

    Se escribe SIEMPRE, tambien cuando la lista esta vacia: la ausencia de la
    propiedad es indistinguible de un fallo de escritura, y el motor no debe
    tener que adivinar cual de las dos ocurrio.
    """
    return {
        "visibility": contract.visibility.value,
        "known_by": list(contract.known_by),
        "visibility_contract": contract.contract_version,
        "visibility_source": SOURCE_EXPLICIT if explicit else SOURCE_DEFAULT,
    }


def stamp(props: dict[str, Any], visibility: Any = None) -> dict[str, Any]:
    """Devuelve `props` con la visibilidad estampada. No muta la entrada.

    Rechaza que el payload traiga cualquiera de las propiedades reservadas:
    quien escribe declara su intencion en `visibility`, no colandola entre las
    propiedades del nodo.
    """
    intruso = VISIBILITY_PROPS.intersection(props)
    if intruso:
        raise VisibilityStampError(
            "el payload no puede fijar propiedades de visibilidad: "
            f"{sorted(intruso)}; declaralo en el argumento `visibility`"
        )
    contract = normalize(visibility)
    return {**props, **to_props(contract, explicit=visibility is not None)}
