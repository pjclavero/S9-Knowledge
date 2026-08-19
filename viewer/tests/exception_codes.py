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
  excepción. Queda corregida.

  DISCREPANCIA CERRADA a favor de 153 + 55: un revisor independiente reprodujo
  el comando de arriba sobre `aaf9695` y obtuvo exactamente esas cifras (y
  127 + 49 acotado a `data-engine/app/tests/`). Su propio recuento previo por
  AST daba 175, pero PERDÍA 27 LLAMADAS REALES —tipos escritos con punto
  (`V.ContractV3Error`, `sqlite3.ProgrammingError`) y tuplas de tipos—, así que
  175 era un SUELO, no una cifra rival. No hay dos hechos: hay una cifra y la
  cota inferior de un recuento incompleto.) Cubre ledger V3, safe writer, supersede_review,
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
* FRAGILIDAD EN EL PRODUCTO (hallazgo nuevo, FUERA DEL ALCANCE de este
  carril; se ANOTA, no se arregla aquí): de las 55 líneas `in str(exc…)` de
  `aaf9695`, TRES no son pruebas sino CÓDIGO DE PRODUCTO que ramifica sobre el
  texto de un mensaje de sqlite::

      viewer/app/auth/db.py:259   -> "duplicate column" not in str(exc).lower()
      viewer/app/auth/db.py:270   -> "duplicate column" not in str(exc).lower()
      viewer/app/services/v3_review_store.py:75 -> "locked" not in str(exc).lower()

  Motivo: la decisión de control de flujo (tragar el error de migración,
  reintentar ante el bloqueo) depende de la REDACCIÓN de una biblioteca de
  terceros, que puede cambiar entre versiones de SQLite o de CPython sin aviso
  ni rojo. Es el mismo vicio que este carril erradica en las pruebas, pero en
  el producto. Las dos direcciones NO son simétricas:

  - La peligrosa es el FALSO POSITIVO de subcadena, y es la SILENCIOSA: un
    `OperationalError` ajeno cuyo texto contenga por casualidad
    "duplicate column" se TRAGA y el ALTER no se aplica, sin rojo ni aviso
    (y `schema_version` se marca igualmente como migrada). Igual con "locked":
    otro error consume los 60 reintentos en vez de propagarse.
  - Si SQLite REESCRIBE el mensaje, en cambio, ambos sitios fallan
    RUIDOSAMENTE: `raise` en db.py:259/270 y fin de reintentos en
    v3_review_store.py:75. Eso se ve.

  Su conversión pide códigos nativos (`sqlite3.Error.sqlite_errorname`) y
  carril propio con negativos.
  Con esto, el desglose real de las 55 es 52 EN PRUEBAS + 3 EN PRODUCTO, y el
  total de comprobaciones por subcadena EN PRUEBAS es 205 (153 + 52).
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

    La rama de PERTENENCIA exige además que `codes` sea una SECUENCIA, no una
    cadena: sobre una cadena, `code in codes` no comprueba pertenencia sino
    SUBCADENA, y `raises_code(X, "CSRF")` aprobaría contra
    `codes="CSRF_SECRET_TOO_SHORT_Y_MAS"` —aprobar por parecido, el vicio
    exacto que este carril erradica—. Hoy no hay superviviente en el producto
    (`AuthSecurityError.codes` se construye siempre con `tuple(...)` y es la
    única forma `codes` que existe): la puerta se cierra antes de que alguien
    la abra. Negativo que lo mide:
    `test_negativo_codes_como_cadena_enrojece`.
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
        assert not isinstance(varios, (str, bytes)), (
            f"{type(exc).__name__}.codes es una cadena ({varios!r}), no una "
            f"secuencia de códigos: `code in codes` degeneraría en una "
            f"comprobación de SUBCADENA y aprobaría {code!r} por parecido. "
            f"El contrato exige una secuencia (tupla) de códigos."
        )
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
