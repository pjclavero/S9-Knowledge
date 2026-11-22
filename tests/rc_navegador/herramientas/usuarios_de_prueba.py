#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Crea y retira las cuentas de prueba de la batería de navegador.

Las cuentas se crean por la vía CANÓNICA del producto: la CLI de
administración del visor a través de su envoltorio de despliegue
(``s9k-cli.sh auth ...``), que es la que cambia al usuario de servicio. Este
guion NO abre la base de autenticación ni importa código del producto.

Secretos: las contraseñas se generan aquí, se guardan en un fichero 0600 fuera
del repositorio y se entregan a la CLI por la ENTRADA ESTÁNDAR. Nunca van en
la línea de comandos ni se imprimen.

Uso (en la máquina de la instalación, con permiso de sudo sin contraseña):

    export S9K_RC_NAV_CREDENCIALES=<ruta fuera del repo>/credenciales.json
    export S9K_RC_NAV_CLI=<release activa>/deploy/scripts/s9k-cli.sh
    python3 usuarios_de_prueba.py crear      # idempotente
    python3 usuarios_de_prueba.py listar     # nombres y roles, sin secretos
    python3 usuarios_de_prueba.py retirar    # desactiva las cuentas creadas

``crear`` deja cada cuenta lista para entrar (sin cambio de contraseña
obligatorio), salvo ``cambio`` —que conserva la obligación, porque esa pantalla
es lo que prueba— e ``inactivo`` —que queda desactivada—.

``retirar`` DESACTIVA (la CLI no borra usuarios): las cuentas quedan en la base
como inactivas y sin sesiones. Se listan para que quien administre la
instalación sepa qué dejó esta batería.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from soporte import CUENTAS, PREFIJO, _dentro_del_repo  # noqa: E402

PREFIJO_USUARIO = "rc3nav_"


def _ruta_credenciales() -> Path:
    valor = os.environ.get(PREFIJO + "CREDENCIALES", "").strip()
    if not valor:
        sys.exit(f"falta {PREFIJO}CREDENCIALES (ruta del fichero 0600, fuera del repositorio)")
    ruta = Path(valor)
    if _dentro_del_repo(ruta):
        sys.exit("el fichero de credenciales no puede estar dentro del repositorio")
    return ruta


def _cli() -> list[str]:
    valor = os.environ.get(PREFIJO + "CLI", "").strip()
    if not valor:
        sys.exit(f"falta {PREFIJO}CLI (ruta del envoltorio s9k-cli.sh de la release activa)")
    return ["sudo", "-n", valor, "auth"]


def _auth(args: list[str], entrada: str = "") -> subprocess.CompletedProcess:
    """Ejecuta la CLI de auth. La contraseña, si la hay, va por stdin."""
    return subprocess.run(_cli() + args, input=entrada, capture_output=True, text=True, timeout=120)


def _cargar(ruta: Path) -> dict:
    if ruta.exists():
        return json.loads(ruta.read_text(encoding="utf-8"))
    return {"cuentas": {}}


def _guardar(ruta: Path, datos: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(ruta.parent, 0o700)
    descriptor = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    os.chmod(ruta, 0o600)


def _sin_secreto(texto: str, clave: str) -> str:
    return texto.replace(clave, "<redactado>") if clave else texto


def crear() -> int:
    ruta = _ruta_credenciales()
    datos = _cargar(ruta)
    cuentas = datos.setdefault("cuentas", {})
    rc = 0
    for clave, rol in CUENTAS.items():
        cuenta = cuentas.setdefault(clave, {})
        cuenta.setdefault("username", PREFIJO_USUARIO + clave)
        cuenta.setdefault("role", rol)
        # token_urlsafe: sólo [A-Za-z0-9_-], así la forma codificada en un
        # formulario coincide con la literal y la redacción no se deja nada.
        cuenta.setdefault("password", secrets.token_urlsafe(18))
        _guardar(ruta, datos)
        usuario, pw = cuenta["username"], cuenta["password"]

        alta = _auth(["create-user"], f"{usuario}\nBatería navegador · {clave}\n{rol}\n{pw}\n{pw}\n")
        if alta.returncode == 0:
            print(f"creada   {usuario} ({rol})")
        elif "ya existe" in (alta.stderr + alta.stdout):
            print(f"existía  {usuario} ({rol})")
        else:
            print(f"ERROR al crear {usuario}: rc={alta.returncode} "
                  f"{_sin_secreto(alta.stderr.strip()[-300:], pw)}", file=sys.stderr)
            rc = 1
            continue

        if clave == "cambio":
            # Conserva «debe cambiar la contraseña»: se fija con la bandera.
            fijar = _auth(["set-password", "--username", usuario, "--must-change"], f"{pw}\n{pw}\n")
        else:
            fijar = _auth(["set-password", "--username", usuario], f"{pw}\n{pw}\n")
        if fijar.returncode != 0:
            print(f"ERROR al fijar la contraseña de {usuario}: rc={fijar.returncode} "
                  f"{_sin_secreto(fijar.stderr.strip()[-300:], pw)}", file=sys.stderr)
            rc = 1
            continue

        if clave == "inactivo":
            baja = _auth(["disable-user", "--username", usuario])
        else:
            baja = _auth(["enable-user", "--username", usuario])
        if baja.returncode != 0:
            print(f"ERROR al fijar el estado de {usuario}: rc={baja.returncode}", file=sys.stderr)
            rc = 1
    print(f"credenciales en {ruta} (0600); {len(cuentas)} cuentas")
    return rc


def listar() -> int:
    datos = _cargar(_ruta_credenciales())
    for clave, cuenta in sorted(datos.get("cuentas", {}).items()):
        print(f"{clave:10s} {cuenta.get('username', '?'):24s} {cuenta.get('role', '?')}")
    return 0


def retirar() -> int:
    datos = _cargar(_ruta_credenciales())
    rc = 0
    for clave, cuenta in sorted(datos.get("cuentas", {}).items()):
        usuario = cuenta.get("username", "")
        if not usuario.startswith(PREFIJO_USUARIO):
            print(f"omitida  {usuario}: no es una cuenta de esta batería")
            continue
        baja = _auth(["disable-user", "--username", usuario])
        if baja.returncode == 0:
            print(f"desactivada {usuario}")
        else:
            print(f"ERROR al desactivar {usuario}: rc={baja.returncode} {baja.stderr.strip()[-200:]}",
                  file=sys.stderr)
            rc = 1
    return rc


def main() -> int:
    ordenes = {"crear": crear, "listar": listar, "retirar": retirar}
    if len(sys.argv) != 2 or sys.argv[1] not in ordenes:
        sys.exit(f"uso: {sys.argv[0]} " + "|".join(ordenes))
    return ordenes[sys.argv[1]]()


if __name__ == "__main__":
    raise SystemExit(main())
