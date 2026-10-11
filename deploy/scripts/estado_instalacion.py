# -*- coding: utf-8 -*-
"""Estados de la INSTALACION DE FABRICA (B2 · USABLE-V1). Autoridad unica.

POR QUE EXISTE
--------------
«``deploy.sh`` termino» NO es «instalacion completa». Antes de B2 el guion
imprimia ``DEPLOY completado`` y nada decia si el primer administrador se
podia crear, se habia creado o sobrevivia a un reinicio. Este modulo fija la
cadena de estados y, sobre todo, la regla que impide PROMOCIONAR un estado sin
la evidencia de todos los anteriores::

    DEPLOY_OK
      -> HTTPS_BOOTSTRAP_PATH_VERIFIED
        -> FIRST_ADMIN_PENDING
          -> FIRST_ADMIN_VERIFIED
            -> INSTALLATION_COMPLETE

Cada estado exige la evidencia de TODOS los anteriores. Lo que no se observo
no cuenta a favor (AUSENCIA != CERO).

QUIEN APORTA CADA EVIDENCIA (y por que medio)
----------------------------------------------
============================  =================================================
evidencia                     la observa
============================  =================================================
``deploy_ok``                 ``deploy.sh`` pasos 1-16 (release activa, proceso
                              vivo verificado, healthcheck)
``https_verificado``          ``deploy.sh`` paso 16b -> ``preflight_https.py``
``gate_a``                    ``preflight_setup_admin.py --modo gate-a``: POST
                              invalido con CSRF correcto -> 400 de validacion
``setup_abierto``             el ESTADO DEL PRODUCTO: sin usuarios y sin sello
                              (``detect_state.primer_admin_pendiente``) y el
                              ``GET /setup/admin`` 200 que observa el GATE A
``gate_b_bootstrap``          ``preflight_setup_admin.py --modo bootstrap``
``gate_b_persistencia``       ``preflight_setup_admin.py --modo persistencia``,
                              DESPUES de reiniciar el servicio
============================  =================================================

``deploy.sh`` NUNCA pasa de ``FIRST_ADMIN_PENDING``: no crea administradores
(la contrasena la elige una persona; ver ``deploy/README.md``). Los dos
ultimos estados solo los da el GATE B.

REGISTRO
--------
La evidencia se acumula en un JSON del state root
(``<S9K_STATE_ROOT>/deploy/instalacion.json``), escrito de forma atomica. No
contiene secretos: solo booleanos, el nombre de la evidencia y su hora.
``deploy.sh`` lo REINICIA en CADA despliegue (fresh y upgrade): la evidencia
de un gate pertenece a la release que lo observo, y una release nueva no la
hereda (correccion R2-a de #271).

DOS LINEAS, DOS PREGUNTAS (O-A, revision de #271)
--------------------------------------------------
``ESTADO_OBSERVADO=`` responde «que vio ESTA ejecucion» (la cadena de arriba,
con el registro que se reinicia en cada despliegue). Por eso un upgrade de una
instalacion completa dice ``DEPLOY_OK``: es verdad, y no es toda la verdad.
``ESTADO_DEL_PRODUCTO=`` responde «en que estado esta la instalacion» y se
deriva SOLO del estado del producto que ``detect_state`` ya lee de la auth DB
(sello ``install_state`` y administradores activos), nunca del registro:

==========================================  ===================================
``FRESH``                                   no hay auth DB
``FIRST_ADMIN_PENDING``                     auth DB sin usuarios y sin sello
``BOOTSTRAP_SELLADO``                       sellada, sin ningun admin activo
``INSTALLATION_COMPLETE_SEGUN_PRODUCTO``    sellada (o con usuarios: el producto
                                            infiere el sello) y >= 1 admin activo
``INDETERMINADO``                           la base existe y no es legible
==========================================  ===================================

Ninguna de las dos inventa evidencia de gates: la segunda no es la cadena, es
lo que el producto dice de si mismo.

TECHO DECLARADO
---------------
Que entre ``gate_b_bootstrap`` y ``gate_b_persistencia`` hubo un REINICIO del
servicio lo afirma el operador (o el arnes, que mata el proceso de verdad);
este modulo exige solo que la persistencia se observe DESPUES del bootstrap.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

#: La cadena, en orden. Un estado exige todos los anteriores.
ESTADOS = (
    "DEPLOY_OK",
    "HTTPS_BOOTSTRAP_PATH_VERIFIED",
    "FIRST_ADMIN_PENDING",
    "FIRST_ADMIN_VERIFIED",
    "INSTALLATION_COMPLETE",
)

#: Evidencia que exige cada estado (ademas de la de los anteriores).
EVIDENCIA_POR_ESTADO = {
    "DEPLOY_OK": ("deploy_ok",),
    "HTTPS_BOOTSTRAP_PATH_VERIFIED": ("https_verificado", "gate_a"),
    "FIRST_ADMIN_PENDING": ("setup_abierto",),
    "FIRST_ADMIN_VERIFIED": ("gate_b_bootstrap",),
    "INSTALLATION_COMPLETE": ("gate_b_persistencia",),
}

EVIDENCIAS = tuple(e for estado in ESTADOS for e in EVIDENCIA_POR_ESTADO[estado])

#: Sin ninguna evidencia: ni siquiera DEPLOY_OK.
NINGUNO = "NINGUNO"


def _verdadera(evidencia: dict, clave: str) -> bool:
    valor = evidencia.get(clave)
    if isinstance(valor, dict):
        valor = valor.get("ok")
    return valor is True


def _instante(evidencia: dict, clave: str) -> Optional[float]:
    valor = evidencia.get(clave)
    if isinstance(valor, dict):
        t = valor.get("t")
        return float(t) if isinstance(t, (int, float)) else None
    return None


def estado_alcanzado(evidencia: dict) -> str:
    """El estado MAS ALTO cuya evidencia, y la de todos los anteriores, consta.

    Un ``False`` o una ausencia corta la cadena ahi: no se salta ningun
    eslabon. Y la persistencia solo cuenta si se observo DESPUES del
    bootstrap (si ambos llevan hora): una persistencia anterior al alta no
    demuestra que el alta sobreviviera a nada.
    """
    alcanzado = NINGUNO
    for estado in ESTADOS:
        if not all(_verdadera(evidencia, e) for e in EVIDENCIA_POR_ESTADO[estado]):
            break
        if estado == "INSTALLATION_COMPLETE":
            t_alta = _instante(evidencia, "gate_b_bootstrap")
            t_pers = _instante(evidencia, "gate_b_persistencia")
            if t_alta is not None and t_pers is not None and t_pers <= t_alta:
                break
        alcanzado = estado
    return alcanzado


def leer(ruta: Path) -> dict:
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return datos if isinstance(datos, dict) else {}


def registrar(ruta: Path, reiniciar: bool = False, **evidencia: bool) -> dict:
    """Anade evidencia al registro (atomico). ``reiniciar`` lo vacia antes."""
    for clave in evidencia:
        if clave not in EVIDENCIAS:
            raise ValueError("evidencia desconocida: %r" % (clave,))
    datos = {} if reiniciar else leer(ruta)
    ahora = time.time()
    for clave, valor in evidencia.items():
        datos[clave] = {"ok": bool(valor), "t": ahora}
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".instalacion-", dir=str(ruta.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, ruta)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return datos


def estado_del_producto(auth_db: Optional[str]) -> str:
    """Estado de la instalacion SEGUN EL PRODUCTO. Nunca mira el registro."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import detect_state  # noqa: PLC0415 - mismo directorio
    from migrate_sqlite import inspect_db  # noqa: PLC0415

    if not auth_db or not Path(auth_db).exists():
        return "FRESH"
    info = inspect_db(Path(auth_db), "auth")
    if info["integrity"] != "ok":
        return "INDETERMINADO"
    cuentas = info["counts"]
    usuarios = cuentas.get("users") or 0
    admins = cuentas.get("active_admins") or 0
    # La misma regla que `viewer/app/auth/bootstrap.py::bootstrap_completado`:
    # sello puesto, o ya hay usuarios (el producto infiere y escribe el sello).
    sellada = bool(detect_state.sello_de_instalacion(auth_db)) or usuarios > 0
    if not sellada:
        return "FIRST_ADMIN_PENDING"
    if admins >= 1:
        return "INSTALLATION_COMPLETE_SEGUN_PRODUCTO"
    return "BOOTSTRAP_SELLADO"


def linea_de_estado(evidencia: dict) -> str:
    """La linea que se imprime y se puede buscar en un log."""
    return "ESTADO_OBSERVADO=%s" % (estado_alcanzado(evidencia),)


def _booleano(texto: str) -> bool:
    if texto in ("1", "true"):
        return True
    if texto in ("0", "false"):
        return False
    raise argparse.ArgumentTypeError("se esperaba true|false, no %r" % (texto,))


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Estado de la instalacion de fabrica.")
    ap.add_argument("--registro", required=True, help="JSON de evidencia")
    ap.add_argument("--reiniciar", action="store_true",
                    help="vaciar el registro antes de anotar (primera release)")
    ap.add_argument("--anotar", action="append", default=[], metavar="EVIDENCIA=true|false")
    ap.add_argument("--auth-db", help="ademas, ESTADO_DEL_PRODUCTO= leido de esta auth DB")
    args = ap.parse_args(argv)
    ruta = Path(args.registro)
    nuevas = {}
    for item in args.anotar:
        clave, sep, valor = item.partition("=")
        if not sep:
            ap.error("--anotar exige EVIDENCIA=true|false")
        nuevas[clave] = _booleano(valor)
    try:
        datos = registrar(ruta, reiniciar=args.reiniciar, **nuevas) if (nuevas or args.reiniciar) else leer(ruta)
    except (ValueError, OSError) as exc:
        print("ERROR: %s" % (exc,), file=sys.stderr)
        return 2
    print(linea_de_estado(datos))
    if args.auth_db:
        producto = estado_del_producto(args.auth_db)
        print("ESTADO_DEL_PRODUCTO=%s" % (producto,))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
