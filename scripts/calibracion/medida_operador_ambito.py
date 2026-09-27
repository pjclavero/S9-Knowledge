#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mide el corte COMO EL OPERADOR: uvicorn real, `.env` de la plantilla,
bootstrap web del primer admin, login real y un usuario NORMAL ademas del admin.

POR QUE NO BASTA LA SUITE
-------------------------
La suite usa `TestClient`, que atraviesa la app pero no el servidor. Este
arnes levanta `uvicorn` de verdad contra un `.env` COPIADO DE LA PLANTILLA SIN
SUSTITUIR NINGUNA LINEA -- en particular `S9K_DEFAULT_WORKSPACE=leyenda`, que
es justo la declaracion del entorno que este corte dice que NO gobierna el
ambito de una consulta. Lo unico que se ANADE al fichero (nunca sustituir) es
lo que la plantilla no trae y sin lo cual no hay instalacion: encender la
autenticacion, donde vive la base de auth y que grafo de ejemplo cargar.

EL GRAFO TIENE CONTENIDO DE DOS WORKSPACES
------------------------------------------
Sin eso no se distingue "no accede" de "no hay nada".

    leyenda      -> 2 nodos   (el ambito que la autoridad resuelve)
    juego:ajeno  -> 2 nodos   (el que el cliente pedira por parametro)

Uso:  python3 scripts/calibracion/medida_operador_ambito.py [--puerto 8791]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PLANTILLA = REPO / ".env.example"
VIEWER = REPO / "viewer"

WS = "leyenda"          # lo que declara la plantilla; lo que resuelve la autoridad
OTRO_WS = "juego:ajeno"  # el que pedira el cliente por parametro

CLAVE_ADMIN = "Operador_2026_S9K!xyz"
CLAVE_ANA = "Jugadora_2026_S9K!xyz"

GRAFO = {
    "nodes": [
        {"id": "lore_propio", "label": "Lore de leyenda", "type": "Regla",
         "workspace": WS, "scope": "juego", "visibility": "player",
         "description": "Del workspace canonico.", "confidence": 0.9,
         "review_status": "reviewed", "source_document": "fuente_propia"},
        {"id": "npc_propio", "label": "Tabernero", "type": "Character",
         "workspace": WS, "scope": "juego", "visibility": "player",
         "description": "Del workspace canonico.", "confidence": 0.9,
         "review_status": "reviewed", "source_document": "fuente_propia"},
        {"id": "lore_ajeno", "label": "Lore de otra casa", "type": "Regla",
         "workspace": OTRO_WS, "scope": "juego", "visibility": "player",
         "description": "Del workspace AJENO.", "confidence": 0.9,
         "review_status": "reviewed", "source_document": "fuente_ajena"},
        {"id": "npc_ajeno", "label": "Herrero ajeno", "type": "Character",
         "workspace": OTRO_WS, "scope": "juego", "visibility": "player",
         "description": "Del workspace AJENO.", "confidence": 0.9,
         "review_status": "reviewed", "source_document": "fuente_ajena"},
    ],
    "edges": [
        {"id": "e1", "from": "lore_propio", "to": "npc_propio", "type": "MENTIONS",
         "workspace": WS, "scope": "juego", "visibility": "player"},
        {"id": "e2", "from": "lore_ajeno", "to": "npc_ajeno", "type": "MENTIONS",
         "workspace": OTRO_WS, "scope": "juego", "visibility": "player"},
    ],
}

HUELLAS_AJENAS = ("lore_ajeno", "npc_ajeno", "fuente_ajena", OTRO_WS)
HUELLA_PROPIA = "lore_propio"


def _csrf(texto: str) -> str:
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', texto)
    if not m:
        m = re.search(r'value="([^"]+)"\s+name="csrf_token"', texto)
    assert m, "no se encuentra el csrf_token en el formulario"
    return m.group(1)


def preparar(tmp: Path, sin_autoridad: bool) -> Path:
    """Copia la plantilla TAL CUAL y anade (no sustituye) lo imprescindible."""
    destino = tmp / ".env"
    shutil.copyfile(PLANTILLA, destino)
    grafo = tmp / "grafo.json"
    grafo.write_text(json.dumps(GRAFO), encoding="utf-8")
    anadido = [
        "",
        "# --- anadido por el arnes (ninguna linea de la plantilla se toca) ---",
        "S9K_AUTH_ENABLED=true",
        f"S9K_AUTH_DB_PATH={tmp / 'auth.db'}",
        f"S9K_SAMPLE_GRAPH_PATH={grafo}",
        "S9K_SESSION_SECURE=false",
    ]
    if sin_autoridad:
        # La forma DECLARADA de que el entorno deje de declarar workspace
        # (docs/v3/65): la cadena vacia. Aqui SI se re-declara la clave, y se
        # dice: es la segunda columna del experimento, no la instalacion.
        anadido.append("S9K_DEFAULT_WORKSPACE=")
    with destino.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(anadido) + "\n")
    return destino


def arrancar(tmp: Path, puerto: int):
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(puerto), "--log-level", "warning"],
        cwd=str(tmp), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        env={**_entorno_limpio(), "PYTHONPATH": str(VIEWER)},
    )
    return proc


def _entorno_limpio() -> dict:
    import os
    # Ninguna S9K_* del shell: el `.env` es la unica autoridad de configuracion
    # de esta medida. Si una variable heredada gobernase, se estaria midiendo
    # otro despliegue.
    return {k: v for k, v in os.environ.items() if not k.startswith("S9K_")}


def esperar(cliente, base: str, proc, intentos: int = 60) -> None:
    for _ in range(intentos):
        if proc.poll() is not None:
            raise SystemExit("uvicorn murio al arrancar:\n" + (proc.stdout.read() or ""))
        try:
            cliente.get(base + "/login", timeout=2.0)
            return
        except Exception:
            time.sleep(0.5)
    raise SystemExit("uvicorn no respondio a tiempo")


def bootstrap_y_login(httpx, base: str):
    """Bootstrap web del primer admin + login REAL. Devuelve (admin, ana)."""
    admin = httpx.Client(base_url=base, follow_redirects=False, timeout=15.0)
    r = admin.get("/setup/admin")
    assert r.status_code == 200, f"/setup/admin -> {r.status_code}"
    r = admin.post("/setup/admin", data={
        "username": "operador", "display_name": "Operador",
        "password": CLAVE_ADMIN, "password_confirm": CLAVE_ADMIN,
        "csrf_token": _csrf(r.text),
    })
    assert r.status_code in (200, 303), f"bootstrap -> {r.status_code} {r.text[:300]}"

    r = admin.get("/login")
    r = admin.post("/login", data={"username": "operador", "password": CLAVE_ADMIN,
                                   "csrf_token": _csrf(r.text)})
    assert r.status_code in (200, 302, 303), f"login admin -> {r.status_code}"
    assert admin.cookies.get("s9k_session"), "el login del admin no dejo sesion"

    # Usuario NORMAL, creado por el admin desde la pantalla real.
    r = admin.get("/admin/users/new")
    assert r.status_code == 200, f"/admin/users/new -> {r.status_code}"
    r = admin.post("/admin/users/new", data={
        "username": "ana", "display_name": "Ana", "role": "reviewer",
        "password": CLAVE_ANA, "csrf_token": _csrf(r.text),
    })
    assert r.status_code in (200, 302, 303), f"alta de ana -> {r.status_code} {r.text[:300]}"

    ana = httpx.Client(base_url=base, follow_redirects=False, timeout=15.0)
    r = ana.get("/login")
    r = ana.post("/login", data={"username": "ana", "password": CLAVE_ANA,
                                 "csrf_token": _csrf(r.text)})
    assert ana.cookies.get("s9k_session"), f"el login de ana no dejo sesion: {r.status_code}"
    return admin, ana


# (ruta, donde viaja el workspace en la respuesta, HUELLA de contenido propio)
#
# La huella no puede ser la misma para todas: los endpoints agregados no
# devuelven nodos, devuelven recuentos y fuentes. Si se buscara un id de nodo
# en `/api/quality` el control positivo diria "ciego" siempre y no mediria
# nada. Cada ruta declara por que se le reconoce que SI esta viendo lo suyo.
RUTAS = [
    ("/api/graph", "workspace", r"lore_propio"),
    ("/api/search", "workspace", r"lore_propio"),
    ("/api/entity-types", "workspace", r'"count":\s*[1-9]'),
    ("/api/entities", "filters.workspace", r"lore_propio"),
    ("/api/workspaces", None, r"leyenda"),
    ("/api/sources", "workspace", r"fuente_propia"),
    ("/api/quality", "workspace", r'"total_entities":\s*[1-9]'),
    ("/entities", "HTML", r"Lore de leyenda"),
    ("/sources", "HTML", r"fuente_propia"),
    ("/quality", "HTML", r"Regla"),
]


def _ws_de(cuerpo, camino):
    if camino in (None, "HTML"):
        return "-"
    cur = cuerpo
    for k in camino.split("."):
        cur = cur.get(k, {}) if isinstance(cur, dict) else None
    return cur if isinstance(cur, str) else "-"


def medir(cliente, base_ruta_params) -> list[tuple]:
    filas = []
    for ruta, camino, huella in RUTAS:
        params = dict(base_ruta_params)
        r = cliente.get(ruta, params=params)
        ws = "-"
        if r.status_code == 200 and camino not in (None, "HTML"):
            try:
                ws = _ws_de(r.json(), camino)
            except Exception:
                ws = "?"
        fuga = [h for h in HUELLAS_AJENAS if h in r.text]
        propio = re.search(huella, r.text) is not None
        filas.append((ruta, r.status_code, ws, "SI" if fuga else "no", "si" if propio else "NO"))
    return filas


def imprimir(titulo: str, filas) -> None:
    print(f"\n### {titulo}")
    print(f"{'ruta':<20}{'status':>7}  {'workspace servido':<20}{'fuga ajena':<12}{'ve lo suyo'}")
    for ruta, code, ws, fuga, propio in filas:
        print(f"{ruta:<20}{code:>7}  {str(ws):<20}{fuga:<12}{propio}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--puerto", type=int, default=8791)
    args = ap.parse_args()

    try:
        import httpx
    except ImportError:
        print("falta httpx"); return 2

    veredicto = []
    for etiqueta, sin_autoridad in (("AUTORIDAD RESUELTA", False),
                                    ("AUTORIDAD SIN RESOLVER", True)):
        tmp = Path(tempfile.mkdtemp(prefix="op254-"))
        preparar(tmp, sin_autoridad)
        puerto = args.puerto + (1 if sin_autoridad else 0)
        base = f"http://127.0.0.1:{puerto}"
        proc = arrancar(tmp, puerto)
        try:
            with httpx.Client(timeout=5.0) as sonda:
                esperar(sonda, base, proc)
            if sin_autoridad:
                admin, ana = bootstrap_y_login(httpx, base)
                filas = medir(ana, {"q": "Lore"})
                imprimir(f"{etiqueta} · usuario normal (ana)", filas)
                malas = [f for f in filas if f[1] == 200]
                veredicto.append((etiqueta, "TODOS 409" if not malas else
                                  f"{len(malas)} endpoints responden 200: "
                                  + ", ".join(f[0] for f in malas)))
                filas_admin = medir(admin, {"q": "Lore"})
                imprimir(f"{etiqueta} · admin_full", filas_admin)
            else:
                admin, ana = bootstrap_y_login(httpx, base)
                filas = medir(ana, {"q": "Lore", "workspace": OTRO_WS})
                imprimir(f"{etiqueta} · usuario normal pide el AJENO", filas)
                fugas = [f for f in filas if f[3] == "SI" or f[2] == OTRO_WS]
                veredicto.append((etiqueta + " / parametro ajeno",
                                  "sin fuga" if not fugas else
                                  "FUGA en " + ", ".join(f[0] for f in fugas)))

                filas = medir(ana, {"q": "Lore", "workspace": WS})
                imprimir(f"{etiqueta} · CONTROL POSITIVO (pide el suyo)", filas)
                ciegos = [f for f in filas if f[4] == "NO"]
                veredicto.append((etiqueta + " / control positivo",
                                  "ve lo suyo" if not ciegos else
                                  "CIEGO en " + ", ".join(f[0] for f in ciegos)))

                filas = medir(admin, {"q": "Lore", "workspace": OTRO_WS})
                imprimir(f"{etiqueta} · admin_full pide el AJENO (selector declarado)", filas)
                veredicto.append((etiqueta + " / admin_full",
                                  "conserva el selector" if any(f[2] == OTRO_WS for f in filas)
                                  else "el admin PERDIO el selector"))
        finally:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    print("\n" + "=" * 74)
    for etiqueta, resultado in veredicto:
        print(f"  {etiqueta:<45} {resultado}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
