# -*- coding: utf-8 -*-
"""Testigo de la plantilla del vhost TLS (PR-3, USABLE-V1): observacion O3
del PR #266.

POR QUE EXISTE
----------------
`deploy/ansible/roles/tls/templates/s9-knowledge.nginx.conf.j2` hace lo
correcto a mano: el bloque del puerto 80 solo `return 308 https://...`, y
toda la aplicacion vive en el bloque TLS. El PR lo explica por que importa
-si el 80 sirviera la aplicacion, se llegaria a `/setup/admin` sobre HTTP
plano y reapareceria el bucle de 403 de la cookie `Secure`-, pero NADA
vigilaba esa propiedad: el preflight tiene prohibido mirar HTTP (D3), el rol
y la plantilla no tienen mutaciones, y CI solo pasa `yamllint`/`shellcheck`
sobre este arbol, no sobre una plantilla Jinja de nginx.

QUE SI AUTORIZA ESTO Y QUE NO (D3)
------------------------------------
D3 prohibe USAR HTTP para hacer pasar la instalacion -por eso el preflight
de `deploy/scripts/preflight_https.py` no sondea HTTP, ni este testigo lo
hace-. D3 NO prohibe comprobar que HTTP se NIEGA a servir la aplicacion: un
negativo (verificar que la plantilla no abre una puerta) no es un fallback a
HTTP para "pasar". Por eso este testigo es puramente ESTATICO: renderiza la
plantilla con `jinja2` (la misma libreria que Ansible usa para `template`) y
PARSEA la estructura resultante del fichero nginx -bloques y directivas, no
grep sobre texto-. Contar apariciones de una subcadena da falsos negativos
(un comentario que mencione "proxy_pass" sin que exista la directiva pasaria
igual un grep positivo o negativo segun donde se mire); por eso se tokeniza
y se construye un arbol de bloques/directivas de verdad.

LO QUE ESTO NO DEMUESTRA
--------------------------
Que nginx interprete el fichero exactamente asi en una maquina real -eso es
el ensayo RC, PENDIENTE- ni que `nginx -t` acepte la sintaxis -tampoco hay
`nginx` en este entorno; eso lo comprueba la tarea
`TLS | comprobar la sintaxis de nginx ANTES de recargar` del rol, no
ejercida aqui-. Lo que SI demuestra es que, para los valores que la
plantilla puede tomar, el bloque del puerto 80 nunca contiene una directiva
que sirva la aplicacion (`proxy_pass`, `location` con contenido propio,
`try_files`, etc.): solo `listen`, `server_name` y un `return` hacia
`https://`.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import jinja2
import pytest

_TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "ansible" / "roles" / "tls" / "templates" / "s9-knowledge.nginx.conf.j2"
)

_CONTEXTO_POR_DEFECTO = {
    "s9k_public_host": "knowledge.example.net",
    "s9k_tls_port": 443,
    "s9k_tls_cert_file": "/etc/s9-knowledge/tls/fullchain.pem",
    "s9k_tls_key_file": "/etc/s9-knowledge/tls/privkey.pem",
    "s9k_viewer_port": 8088,
}


def _renderizar(contexto: Optional[dict] = None) -> str:
    texto = _TEMPLATE.read_text(encoding="utf-8")
    plantilla = jinja2.Environment(
        # `undefined=StrictUndefined`: una variable que la plantilla usa y
        # el contexto no declara tiene que FALLAR al renderizar, no colarse
        # como cadena vacia -eso seria exactamente el tipo de verde que no
        # mide nada contra el que avisan las notas de memoria del proyecto.
        undefined=jinja2.StrictUndefined,
    ).from_string(texto)
    return plantilla.render(**{**_CONTEXTO_POR_DEFECTO, **(contexto or {})})


# ---------------------------------------------------------------------------
# Parser ESTRUCTURAL minimo de nginx.conf: bloques y directivas, no texto.
# ---------------------------------------------------------------------------

def _tokenizar(texto: str) -> list:
    """Quita comentarios `#...` y separa en palabras, `{`, `}`, `;`."""
    sin_comentarios = re.sub(r"#.*", "", texto)
    return re.findall(r"\{|\}|;|[^\s{};]+", sin_comentarios)


def _parsear_bloque(tokens: list, pos: int) -> tuple:
    """Devuelve (lista_de_items, nueva_posicion). Un item es un dict con
    `nombre`, `args` (lista) y `hijos` (lista de items, o `None` si es una
    directiva simple terminada en `;`).
    """
    items = []
    while pos < len(tokens) and tokens[pos] != "}":
        palabras = []
        while tokens[pos] not in ("{", ";"):
            palabras.append(tokens[pos])
            pos += 1
        if not palabras:
            # `;` o `{` suelto (no deberia pasar en una plantilla valida).
            pos += 1
            continue
        if tokens[pos] == "{":
            pos += 1
            hijos, pos = _parsear_bloque(tokens, pos)
            assert tokens[pos] == "}", "bloque sin cerrar en la plantilla"
            pos += 1
            items.append({"nombre": palabras[0], "args": palabras[1:], "hijos": hijos})
        else:  # ';'
            pos += 1
            items.append({"nombre": palabras[0], "args": palabras[1:], "hijos": None})
    return items, pos


def parsear_nginx(texto: str) -> list:
    tokens = _tokenizar(texto)
    items, pos = _parsear_bloque(tokens, 0)
    assert pos == len(tokens), "tokens sobrantes tras parsear: plantilla mal formada"
    return items


def _bloques_de(items: list, nombre: str) -> list:
    return [it for it in items if it["nombre"] == nombre and it["hijos"] is not None]


def _directivas_recursivas(items: list, nombre: str) -> list:
    """Todas las directivas/bloques de nombre dado, bajando por los hijos."""
    hallados = []
    for it in items:
        if it["nombre"] == nombre:
            hallados.append(it)
        if it["hijos"] is not None:
            hallados.extend(_directivas_recursivas(it["hijos"], nombre))
    return hallados


def _escucha_en_puerto(bloque_server: dict, puerto: int) -> bool:
    listens = [d for d in bloque_server["hijos"] if d["nombre"] == "listen"]
    for listen in listens:
        for arg in listen["args"]:
            # formas: "80", "[::]:80", "443" (con "ssl" como arg separado)
            if re.search(r"(?<!\d)%d\b" % puerto, arg):
                return True
    return False


# ---------------------------------------------------------------------------
# El parser se cree primero a si mismo: control positivo sobre el bloque TLS.
# ---------------------------------------------------------------------------

def test_el_parser_encuentra_proxy_pass_en_el_bloque_tls():
    """Si el parser no viera proxy_pass donde SI esta, el negativo de abajo
    no demostraria nada -estaria ciego igual en los dos bloques."""
    items = parsear_nginx(_renderizar())
    servidores = _bloques_de(items, "server")
    tls = [s for s in servidores if _escucha_en_puerto(s, 443)]
    assert len(tls) == 1, "se esperaba exactamente un server block TLS"
    proxy_pass = _directivas_recursivas(tls[0]["hijos"], "proxy_pass")
    assert len(proxy_pass) == 1
    assert proxy_pass[0]["args"][0].startswith("http://127.0.0.1:")


# ---------------------------------------------------------------------------
# La propiedad real: el bloque del puerto 80 SOLO redirige.
# ---------------------------------------------------------------------------

def test_el_bloque_del_puerto_80_solo_redirige_a_https():
    items = parsear_nginx(_renderizar())
    servidores = _bloques_de(items, "server")
    puerto_80 = [s for s in servidores if _escucha_en_puerto(s, 80)]
    assert len(puerto_80) == 1, "se esperaba exactamente un server block en 80"
    bloque = puerto_80[0]

    # Nada que sirva la aplicacion: ni proxy_pass, ni location con contenido,
    # ni try_files, ni root/alias (cualquiera de estas seria "servir algo").
    for prohibida in ("proxy_pass", "location", "try_files", "root", "alias",
                       "fastcgi_pass", "uwsgi_pass"):
        encontradas = _directivas_recursivas(bloque["hijos"], prohibida)
        assert not encontradas, (
            "el bloque del puerto 80 contiene %r: ya no es un redirector "
            "puro, y D3 exige que el 80 nunca sirva la aplicacion (si lo "
            "hiciera, se llegaria a /setup/admin sobre HTTP plano y "
            "reapareceria el bucle de 403)." % prohibida
        )

    # Lo unico que hace de verdad, aparte de listen/server_name, es `return`.
    directivas_propias = [
        it["nombre"] for it in bloque["hijos"]
        if it["nombre"] not in ("listen", "server_name")
    ]
    assert directivas_propias == ["return"], (
        "el bloque del puerto 80 tiene directivas ademas de listen/"
        "server_name/return: %r" % directivas_propias
    )

    retorno = _directivas_recursivas(bloque["hijos"], "return")
    assert len(retorno) == 1
    codigo, destino = retorno[0]["args"][0], retorno[0]["args"][1]
    assert codigo in ("301", "302", "307", "308"), (
        "codigo de redireccion inesperado: %r" % codigo
    )
    assert destino.startswith("https://"), (
        "el redirector del puerto 80 no apunta a https://: %r" % destino
    )


@pytest.mark.parametrize("host", ["knowledge.example.net", "otro.ejemplo.org"])
def test_la_propiedad_se_mantiene_para_distintos_nombres_publicos(host):
    """La propiedad no depende del valor de `s9k_public_host`: no es un
    accidente del contexto de prueba por defecto."""
    items = parsear_nginx(_renderizar({"s9k_public_host": host}))
    servidores = _bloques_de(items, "server")
    puerto_80 = [s for s in servidores if _escucha_en_puerto(s, 80)]
    assert len(puerto_80) == 1
    assert not _directivas_recursivas(puerto_80[0]["hijos"], "proxy_pass")
