"""M5b-0 — el contrato `knowledge-visibility/v1` debe poder importarse SIN las
dependencias del visor.

Mismo problema y misma solucion que
`test_authz_scope_import_ligero.py` (M5a): un consumidor que solo necesita el
vocabulario de visibilidad (data-engine, el writer, un script de migracion)
no debe verse obligado a instalar `pydantic_settings` ni ningun otro paquete
que solo instale `viewer/`. Se comprueba en un interprete aparte, bloqueando
esa dependencia, para que el resultado no dependa del entorno de quien
ejecute el test.

Se comprueba ademas que el modulo NO importa nada de `viewer.app` (ni siquiera
transitivamente): se bloquea tambien ese paquete completo, no solo
`pydantic_settings`, porque `app.policies.engine` es ligero HOY pero el
contrato en si (`contracts/knowledge-visibility/v1/model.py`) no debe
depender de esa ligereza accidental para poder importarse -- el contrato vive
fuera de `app/` precisamente para que esto no dependa de que nadie mantenga
esa propiedad en el futuro.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

_GUION = textwrap.dedent(
    """
    import sys

    class _Bloqueo:
        def find_spec(self, name, path=None, target=None):
            if name == "pydantic_settings" or name == "app" or name.startswith("app."):
                raise ImportError("dependencia del visor no disponible")
            return None

    sys.meta_path.insert(0, _Bloqueo())

    sys.path.insert(0, "contracts/knowledge-visibility/v1")

    import model as kv_model  # noqa: F401

    # Construccion y validacion minima, para demostrar que el modulo no solo
    # importa sino que FUNCIONA sin las dependencias del visor.
    doc = {
        "contract_id": "knowledge-visibility/v1",
        "contract_version": "1.0.0",
        "visibility": "secret",
        "known_by": ["personaje.prueba"],
    }
    parsed = kv_model.KnowledgeVisibilityV1.from_dict(doc)
    assert parsed.visibility.value == "secret"
    assert parsed.known_by == ("personaje.prueba",)
    assert kv_model.is_valid(doc)

    deny_doc = {
        "contract_id": "knowledge-visibility/v1",
        "contract_version": "1.0.0",
        "visibility": "deny",
        "known_by": [],
    }
    assert kv_model.is_valid(deny_doc)

    print("OK")
    """
)


def test_el_contrato_de_visibilidad_se_importa_sin_las_dependencias_del_visor() -> None:
    resultado = subprocess.run(
        [sys.executable, "-c", _GUION],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert resultado.returncode == 0, (
        "contracts/knowledge-visibility/v1/model.py arrastra una importacion "
        f"que exige dependencias del visor:\n{resultado.stderr}"
    )
    assert "OK" in resultado.stdout
