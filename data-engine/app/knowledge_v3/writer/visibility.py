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
VISIBILITY_PROPS = frozenset(
    {"visibility", "known_by", "visibility_contract", "visibility_source", "scope"}
)

#: Ambitos validos. Deben coincidir con `app.policies.models.ALL_SCOPES` del
#: visor: son los dos extremos del mismo contrato, escritura y lectura.
SCOPE_GAME = "juego"
SCOPE_PARTIDA = "partida"


class _SinDeclarar:
    """Centinela: distingue "no me dijeron el ambito" de "me dijeron ninguno"."""

    def __repr__(self) -> str:  # pragma: no cover - solo para mensajes de error
        return "<sin declarar>"


SIN_DECLARAR = _SinDeclarar()

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


def scope_props(partida_id: Any) -> dict[str, Any]:
    """Propiedades de AMBITO. `partida_id` debe declararse siempre (M5c).

    El ambito se escribe como un valor positivo (`scope`), no como la ausencia
    de `partida_id`. La razon es que en lectura la ausencia era ambigua: un dato
    deliberadamente compartido entre partidas y un dato al que se le perdio el
    ambito eran indistinguibles, y la ambiguedad se resolvia hacia lo mas
    abierto. Aqui se corta en origen.

    Declarar `None` es una decision valida y explicita: "esto es lore de juego".
    No declarar nada no lo es.
    """
    if isinstance(partida_id, _SinDeclarar):
        raise VisibilityStampError(
            "hay que declarar el ambito: pasa `partida_id=None` para lore de "
            "juego compartido, o el identificador de la partida. La ausencia de "
            "declaracion no se interpreta como el ambito mas amplio."
        )
    if partida_id is None:
        return {"scope": SCOPE_GAME, "partida_id": None}
    if not isinstance(partida_id, str) or not partida_id.strip():
        raise VisibilityStampError(
            f"partida_id invalido: {partida_id!r}. Un ambito de partida exige un "
            "identificador legible; no se degrada a capa juego."
        )
    return {"scope": SCOPE_PARTIDA, "partida_id": partida_id}


def stamp(
    props: dict[str, Any],
    visibility: Any = None,
    *,
    partida_id: Any = SIN_DECLARAR,
) -> dict[str, Any]:
    """Devuelve `props` con visibilidad y ambito estampados. No muta la entrada.

    Rechaza que el payload traiga cualquiera de las propiedades reservadas:
    quien escribe declara su intencion en `visibility` y `partida_id`, no
    colandolas entre las propiedades del nodo.

    Regla del operador para datos nuevos: lo que no pueda declarar su ambito y
    su visibilidad **no se escribe**. El fail-closed de lectura protege al
    lector, pero no es excusa para meter datos incompletos nuevos: el legacy
    incompleto se conserva como legacy, el dato nuevo incompleto se rechaza.
    """
    intruso = VISIBILITY_PROPS.intersection(props)
    if intruso:
        raise VisibilityStampError(
            "el payload no puede fijar propiedades de visibilidad: "
            f"{sorted(intruso)}; declaralo en el argumento `visibility`"
        )
    ambito = scope_props(partida_id)
    contract = normalize(visibility)
    return {**props, **to_props(contract, explicit=visibility is not None), **ambito}
