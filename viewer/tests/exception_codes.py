"""Ayuda de pruebas: comprobar EXCEPCIÓN POR TIPO + CÓDIGO, no por texto.

V3.1, carril 3. Una comprobación `pytest.raises(X, match="algún texto")` mide
la REDACCIÓN del mensaje: se pone roja si se reescribe el texto sin tocar la
conducta, y se queda verde si otra rama del código lanza el mismo tipo con un
mensaje parecido. Donde la excepción sostiene una garantía del RC, la prueba
usa `raises_code`, que exige tipo y código estable.

ALCANCE CONVERTIDO en este carril (sostienen garantías declaradas del RC):

* `app.auth.security` — fail-closed de arranque (secreto CSRF, backend de
  contraseñas, ruta de la auth DB): `AuthSecurityError.codes`.
* `app.auth.schema_compat` — REFUSE TO START por esquema fuera de rango:
  `SchemaCompatibilityError.code` + `.schema_version`.
* `app.services.v3_review` — identidad durable de la historia append-only
  (cadena de hashes), unicidad de `request_id`, obsolescencia (STALE_REVIEW) y
  rechazo de paquetes corruptos: `ReviewError.code`.

DEUDA EXPLÍCITA, NO convertida (se declara, no se arregla en silencio):

* `data-engine/app/tests/**` (~190 de las ~222 comprobaciones por subcadena del
  repo): ledger V3, safe writer, supersede_review, proveedores externos y
  benchmarks. Varias SÍ sostienen garantías del RC (unicidad e identidad
  durable en el ledger, no-escritura del writer en dry-run); quedan fuera
  porque pertenecen a otra superficie que este carril no posee y su conversión
  necesita códigos propios en `LedgerError` y en el writer. Es deuda
  BLOQUEANTE por el criterio del operador y pide carril propio.
* `viewer/tests/test_parcialidad_declarada.py` y
  `viewer/tests/test_saturacion_grafo_caracterizacion.py`: el `match=` cae
  sobre `AssertionError` de HELPERS DE PRUEBA, no sobre excepciones del
  producto; la garantía (el bloque `view` y sus cifras) ya se comprueba de
  forma estructural sobre la respuesta. Deuda de calidad, no de garantía.
* `contracts/**`: mensajes del validador de esquemas, sin conducta detrás.

EXCEPCIÓN DELIBERADA: `test_schema_mas_nuevo_que_el_codigo_rehusa_arrancar`
sigue comprobando texto además del código, porque ese mensaje ES el runbook
del operador. Está declarado dentro del propio test.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest


@contextmanager
def raises_code(exc_type, code: str):
    """Como `pytest.raises(exc_type)`, pero además exige `exc.code == code`."""
    with pytest.raises(exc_type) as excinfo:
        yield excinfo
    actual = getattr(excinfo.value, "code", None)
    assert actual == code, (
        f"se esperaba {exc_type.__name__} con code={code!r} y llegó code={actual!r} "
        f"({excinfo.value!r}). El código es el contrato; el mensaje no."
    )
