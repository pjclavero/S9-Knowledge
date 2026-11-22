#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Enganche con el ejecutor de una RC-E2E: un paso del contrato por invocación.

    <python del venv de la batería> tests/rc_navegador/rc_paso.py --paso <id>

Ejecuta las pruebas cuyo marcador ``cubre(...)`` nombra ese paso (``7.M1``,
``8.M6a``, ``10.M2``…) y sale con:

    0    PASS     todas las pruebas del paso se ejecutaron y pasaron
    75   BLOCKED  el paso no pudo ejecutarse entero: ninguna prueba lo cubre,
                  o alguna quedó PENDING (falta Neo4j) o BLOCKED (falta
                  configuración o no es su fase), o falta la parametrización
    otro FAIL     alguna prueba del paso falló (o la evidencia llevaba un secreto)

Un paso con parte en verde y parte sin ejecutar sale 75, no 0: lo que no se
ejecutó no se da por bueno.

Qué recibe del ejecutor (entorno ``RC_NAV_*``; se invoca con ``env -i``):

    RC_NAV_BASE_URL, RC_NAV_CA_FILE     instalación y CA
    RC_NAV_EVIDENCIA                    directorio donde dejar la evidencia
    RC_NAV_WORKSPACE, RC_NAV_WORKSPACE_AJENO, RC_NAV_SUJETO
    RC_NAV_CRED_FILE                    credencial del administrador de la instalación

Qué pone la batería: sus cuentas de prueba y lo que la instalación tiene. Como
el ejecutor limpia el entorno, eso se lee de un fichero local NO versionado,
``tests/rc_navegador/.entorno-local`` (líneas ``CLAVE=valor``, sólo rutas y
declaraciones, ningún secreto), por ejemplo::

    S9K_RC_NAV_CREDENCIALES=<ruta 0600 fuera del repo>
    S9K_RC_NAV_CAPACIDADES=panel_b,panel_c,boveda
    S9K_RC_NAV_IDLE_MINUTOS=60
    PLAYWRIGHT_BROWSERS_PATH=<directorio donde se instaló Chromium>

(la última hace falta porque el ejecutor cambia ``HOME`` y Playwright busca el
navegador bajo el ``HOME`` de quien lo instaló).

Las cuentas de prueba son las de ``herramientas/usuarios_de_prueba.py``; la
credencial del administrador de la instalación NO se usa salvo que el fichero
local diga ``S9K_RC_NAV_ADMIN_DEL_EJECUTOR=1`` (necesario en 7.B1, donde aún
no existe ninguna cuenta): entonces la cuenta ``admin`` de la batería pasa a
ser ésa, en una copia 0600 que se borra al terminar.

Qué deja en ``RC_NAV_EVIDENCIA``:

    <id>.resultado.json   {"paso", "estado", "criterio", "detalle", "pruebas"}
    <id>.png              última captura del paso
    <id>.txt              texto: cada prueba, su estado y sus pasos
    bateria/              capturas y HTML por prueba (sin trazas de Playwright)

Todo redactado; si el repaso final encuentra un secreto, el paso sale FAIL.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RC_BLOQUEADO = 75
PREFIJO = "S9K_RC_NAV_"


def _entorno_local() -> dict:
    datos = {}
    ruta = AQUI / ".entorno-local"
    if ruta.is_file():
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                clave, _, valor = linea.partition("=")
                datos[clave.strip()] = valor.strip()
    return datos


def _terminar(evidencia: Path, paso: str, estado: str, detalle: str, pruebas=None, rc: int = 1) -> int:
    evidencia.mkdir(parents=True, exist_ok=True)
    (evidencia / f"{paso}.resultado.json").write_text(json.dumps({
        "paso": paso,
        "estado": estado,
        "criterio": "todas las pruebas de tests/rc_navegador que cubren el paso, ejecutadas y en verde",
        "detalle": detalle,
        "sujeto": os.environ.get("RC_NAV_SUJETO", ""),
        "pruebas": pruebas or [],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"NAVEGADOR paso={paso} estado={estado} rc={rc} :: {detalle}")
    return rc


def main() -> int:
    analizador = argparse.ArgumentParser(description="un paso NAVEGADOR del contrato de la RC-E2E")
    analizador.add_argument("--paso", required=True)
    paso = analizador.parse_args().paso
    evidencia = Path(os.environ.get("RC_NAV_EVIDENCIA") or tempfile.mkdtemp(prefix="rc-nav-"))

    entorno = dict(os.environ)
    entorno.update(_entorno_local())
    for origen, destino in (("RC_NAV_BASE_URL", "BASE_URL"), ("RC_NAV_CA_FILE", "CA_FILE"),
                            ("RC_NAV_WORKSPACE", "WORKSPACE"), ("RC_NAV_WORKSPACE_AJENO", "OTRO_WORKSPACE")):
        if os.environ.get(origen):
            entorno[PREFIJO + destino] = os.environ[origen]
    entorno[PREFIJO + "SALIDA"] = str(evidencia / "bateria")
    entorno[PREFIJO + "SIN_TRAZA"] = "1"

    temporal = None
    if not entorno.get(PREFIJO + "CREDENCIALES"):
        return _terminar(evidencia, paso, "BLOCKED",
                         "falta S9K_RC_NAV_CREDENCIALES (en el entorno o en tests/rc_navegador/.entorno-local)",
                         rc=RC_BLOQUEADO)
    if entorno.get(PREFIJO + "ADMIN_DEL_EJECUTOR") == "1" and os.environ.get("RC_NAV_CRED_FILE"):
        # La cuenta «admin» pasa a ser la del ejecutor, en una copia privada.
        cuentas = json.loads(Path(entorno[PREFIJO + "CREDENCIALES"]).read_text(encoding="utf-8"))
        dada = json.loads(Path(os.environ["RC_NAV_CRED_FILE"]).read_text(encoding="utf-8"))
        usuario = dada.get("username") or dada.get("usuario") or dada.get("user")
        clave = dada.get("password") or dada.get("clave")
        if not usuario or not clave:
            return _terminar(evidencia, paso, "BLOCKED",
                             "RC_NAV_CRED_FILE no trae usuario y contraseña reconocibles", rc=RC_BLOQUEADO)
        cuentas.setdefault("cuentas", {})["admin"] = {"username": usuario, "password": clave, "role": "admin"}
        descriptor, nombre = tempfile.mkstemp(prefix="rc-nav-cred-", suffix=".json")
        with os.fdopen(descriptor, "w", encoding="utf-8") as f:
            json.dump(cuentas, f)
        os.chmod(nombre, 0o600)
        temporal = nombre
        entorno[PREFIJO + "CREDENCIALES"] = nombre

    try:
        proceso = subprocess.run(
            [sys.executable, "-m", "pytest", str(AQUI), "--paso", paso, "-p", "no:randomly", "-q", "--color=no"],
            cwd=str(AQUI.parents[1]), env=entorno, capture_output=True, text=True,
        )
    finally:
        if temporal:
            os.unlink(temporal)
    (evidencia / f"{paso}.pytest.txt").write_text(
        f"PYTEST_RC={proceso.returncode}\n" + proceso.stdout[-20000:] + proceso.stderr[-4000:], encoding="utf-8"
    )

    resultado = evidencia / "bateria" / "resultado.json"
    if not resultado.is_file():
        ultima = (proceso.stderr.strip() or proceso.stdout.strip() or "sin salida").splitlines()[-1]
        # Sin parametrización la batería no arranca: no es un fallo del producto.
        estado, rc = ("BLOCKED", RC_BLOQUEADO) if proceso.returncode == 4 else ("FAIL", 1)
        return _terminar(evidencia, paso, estado, f"la batería no llegó a ejecutar (pytest rc {proceso.returncode}): {ultima[:300]}", rc=rc)
    datos = json.loads(resultado.read_text(encoding="utf-8"))
    pruebas = [{"prueba": p["prueba"], "estado": p["estado"], "motivo": p["motivo"]} for p in datos["pruebas"]]

    # Texto y última captura del paso.
    lineas, ultima_captura = [], None
    for p in datos["pruebas"]:
        lineas.append(f"== {p['prueba']} :: {p['estado']} {p['motivo']}")
        directorio = Path(p["evidencia"]) if p.get("evidencia") else None
        if directorio and (directorio / "pasos.json").is_file():
            for registro in json.loads((directorio / "pasos.json").read_text(encoding="utf-8")):
                if "paso" in registro:
                    lineas.append(f"   {registro['n']:02d} {registro['paso']} · {registro.get('url', '')} · "
                                  f"HTTP {registro.get('estado_http')} · {registro.get('titulo', '')}")
                    if registro.get("captura"):
                        ultima_captura = directorio / registro["captura"]
                else:
                    lineas.append(f"   {registro['n']:02d} DATO {registro['dato']}: "
                                  f"{json.dumps(registro['valor'], ensure_ascii=False)[:600]}")
    (evidencia / f"{paso}.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    if ultima_captura and ultima_captura.is_file():
        shutil.copyfile(ultima_captura, evidencia / f"{paso}.png")

    estados = [p["estado"] for p in pruebas]
    if datos.get("fugas_de_secretos"):
        return _terminar(evidencia, paso, "FAIL", "la evidencia contenía un secreto conocido", pruebas, rc=1)
    if not estados:
        return _terminar(evidencia, paso, "BLOCKED", "ninguna prueba de la batería cubre este paso", pruebas, rc=RC_BLOQUEADO)
    if any(e not in ("PASS", "PENDING", "BLOCKED") for e in estados):
        fallidas = [p["prueba"].split("::")[-1] for p in pruebas if p["estado"] not in ("PASS", "PENDING", "BLOCKED")]
        return _terminar(evidencia, paso, "FAIL", "fallan: " + ", ".join(fallidas), pruebas, rc=1)
    if any(e != "PASS" for e in estados):
        motivos = sorted({p["motivo"][:160] for p in pruebas if p["estado"] != "PASS"})
        return _terminar(evidencia, paso, "BLOCKED",
                         f"{estados.count('PASS')} en verde y {len(estados) - estados.count('PASS')} sin ejecutar: "
                         + " | ".join(motivos), pruebas, rc=RC_BLOQUEADO)
    return _terminar(evidencia, paso, "PASS", f"{len(estados)} pruebas en verde", pruebas, rc=0)


if __name__ == "__main__":
    raise SystemExit(main())
