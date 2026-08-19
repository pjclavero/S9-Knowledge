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

* `data-engine/app/tests/**` — 176 de las 208 comprobaciones por subcadena que
  hay en la base `aaf9695`. Cifras medidas, no estimadas::

      git grep -n "pytest.raises(" aaf9695 -- "*.py" | grep -c "match="   ->  153
      git grep -n "in str(exc"     aaf9695 -- "*.py" | wc -l              ->   55
      ... acotado a data-engine/app/tests/                                ->  127 + 49

  (La cifra «~222» que circuló antes salía de un grep más laxo, que contaba
  cualquier línea con `match=` incluidas las que no son comprobaciones de
  excepción. Queda corregida. Una segunda medición por AST, contando LLAMADAS
  en vez de líneas y sólo en directorios de test, da 175 (126 + 49): la
  diferencia es de método de recuento, no de hecho; el comando de arriba es el
  reproducible.) Cubre ledger V3, safe writer, supersede_review,
  proveedores externos y benchmarks. Varias SÍ sostienen garantías del RC (unicidad e identidad
  durable en el ledger, no-escritura del writer en dry-run); quedan fuera
  porque pertenecen a otra superficie que este carril no posee y su conversión
  necesita códigos propios en `LedgerError` y en el writer. Es deuda
  BLOQUEANTE por el criterio del operador y pide carril propio.
* `viewer/tests/test_parcialidad_declarada.py` y
  `viewer/tests/test_saturacion_grafo_caracterizacion.py`: el `match=` cae
  sobre `AssertionError` de HELPERS DE PRUEBA, no sobre excepciones del
  producto; la garantía (el bloque `view` y sus cifras) ya se comprueba de
  forma estructural sobre la respuesta. Deuda de calidad, no de garantía.
* `contracts/**`: NO por «no hay conducta detrás» — era inexacto. En al menos
  un caso («versión mayor no soportada») sí respalda conducta. Quedan fuera
  porque ahí no hay falso verde posible: una mutación de conducta cambia de
  rama del validador y enrojece igual. Es FRAGILIDAD (el texto puede
  reescribirse y romper la prueba sin que cambie nada), no un instrumento
  ciego, y por eso no es bloqueante para el RC.

EXCEPCIÓN DELIBERADA: `test_schema_mas_nuevo_que_el_codigo_rehusa_arrancar`
sigue comprobando texto además del código, porque ese mensaje ES el runbook
del operador. Está declarado dentro del propio test.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest


_SIN_CODIGO = object()


@contextmanager
def raises_code(exc_type, code: str):
    """Como `pytest.raises(exc_type)`, pero además exige el código estable.

    Cubre las DOS formas del contrato, para que no haya dos maneras de
    comprobar lo mismo:

    * excepción con ``code`` (una causa): se exige igualdad;
    * excepción con ``codes`` (varias causas a la vez, p. ej.
      `AuthSecurityError`): se exige PERTENENCIA.

    Y falla de entrada si se le pasa `code=None`: un verificador que puede
    aprobar sin comprobar nada es justo lo que este carril erradica
    (`getattr(exc, "code", None) == None` habría pasado en silencio contra
    cualquier excepción sin código).
    """
    assert code is not None, (
        "raises_code exige un código estable: `None` convertiría el "
        "verificador en un sello de goma."
    )
    with pytest.raises(exc_type) as excinfo:
        yield excinfo
    exc = excinfo.value
    actual = getattr(exc, "code", _SIN_CODIGO)
    varios = getattr(exc, "codes", _SIN_CODIGO)
    if actual is not _SIN_CODIGO and actual is not None:
        assert actual == code, (
            f"se esperaba {exc_type.__name__} con code={code!r} y llegó "
            f"code={actual!r} ({exc!r}). El código es el contrato; el mensaje no."
        )
    elif varios is not _SIN_CODIGO:
        assert code in varios, (
            f"se esperaba {exc_type.__name__} declarando {code!r} y llegó "
            f"codes={tuple(varios)!r} ({exc!r})."
        )
    else:
        raise AssertionError(
            f"{type(exc).__name__} no expone `code` ni `codes`: no se puede "
            f"sostener una garantía sobre ella por código. Dáselo antes de "
            f"usarla aquí (o no la uses para sostener la garantía)."
        )
