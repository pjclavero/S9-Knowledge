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
``deploy.sh --mode fresh`` lo REINICIA: una primera release nueva no hereda la
evidencia de otra.

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


def linea_de_estado(evidencia: dict) -> str:
    """La linea que se imprime y se puede buscar en un log."""
    return "ESTADO_INSTALACION=%s" % (estado_alcanzado(evidencia),)


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
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
