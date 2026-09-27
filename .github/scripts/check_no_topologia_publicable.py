#!/usr/bin/env python3
"""Gate: ninguna IP privada real en zona PUBLICABLE sin excepcion declarada.

Contexto (EXP-1): este repositorio es PUBLICO. `.env.example` de la raiz lo
dice con todas las letras: una IP privada publicada describe gratis la
topologia de la red interna a quien la lea. `viewer/.env.example` la violaba
(un `bolt://<IP privada real de VM105>:7687` escrito literalmente).

Este gate NO es una busqueda ciega de RFC1918 en todo el arbol: eso llena de
falsos positivos los fixtures y tests que legitimamente usan direcciones
privadas para probar exactamente este tipo de deteccion (p.ej.
`viewer/tests/test_neo4j_default_fail_closed.py`,
`tests/support/prod_block.py`), y un gate que los tumba se acaba
desactivando. La semantica es ZONA + VALOR + EXCEPCION:

  * ZONA_PUBLICABLE: ficheros que un operador copia o lee para instalar o
    desplegar (plantillas `.env.example`, ficheros `*.example`, la config de
    ejemplo empaquetada de `data-engine`, `deploy/README.md`). Deliberadamente
    NO incluye `tests/`, `**/fixtures/**` ni `docs/**` (la auditoria
    documental de `docs/**` es un carril aparte: ver
    `docs/coordination/risk-register.md`, RK-19).
  * VALOR: una IP RFC1918 (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16) dentro
    de esa zona.
  * EXCEPCION: una linea puede declararse exenta, de forma explicita y
    localizada, con el marcador `# topologia: excepcion declarada <motivo>`
    en la misma linea o en la linea inmediatamente anterior. El <motivo> es
    OBLIGATORIO y no puede estar vacio: el marcador a secas no exime nada.
    Documentar SIN ese marcador tampoco exime nada (ver mandato del
    operador: "estar documentada no la hace aceptable").

    PENDIENTE ANOTADO (no implementado aqui): el marcador no deja registro de
    QUIEN declaro la excepcion ni cuando. Exigir autoria/fecha verificable
    requiere una fuente de autoridad (CODEOWNERS, firma de commit o un
    registro aparte) y es un carril propio, no un retoque de este regex.

TECHO DECLARADO: este gate mira contenido de texto plano por ruta y linea. No
seria un motor semantico (no interpreta AST, ni resuelve que un valor llega
por interpolacion o `include`); para el caso que cubre -una IP escrita
literalmente en una plantilla o fichero de configuracion versionado- basta.
No sustituye a una auditoria de `docs/**` (fuera de su zona a proposito) ni a
una revision de los defaults de codigo ya cubiertos por tests explicitos
(p.ej. `DEFAULT_OLLAMA_URL`), que son un carril de decision aparte.

Uso:  python3 .github/scripts/check_no_topologia_publicable.py
Sale 0 si la zona publicable esta limpia; 1 y describe cada violacion si no.
"""
from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Zona publicable: patrones de ruta (relativos a la raiz del repo, estilo
# fnmatch) que SI se consideran alcance de este gate.
ZONA_PUBLICABLE = (
    ".env.example",
    "*.env.example",
    "*/.env.example",
    "*.example",
    "*/*.example",
    "*/*/*.example",
    "data-engine/config/settings.yaml",
    "deploy/README.md",
)

# Techo declarado: fuera de alcance aunque el patron de arriba encajase.
EXCLUSIONES = (
    "docs/*",
    "docs/**",
    "*/tests/*",
    "tests/*",
    "*/fixtures/*",
    # `*.bak` NO cubre `fichero.bak.<timestamp>` ni `fichero.bak-<fecha>`:
    # ese fue el agujero medido en la ronda 1 (mismo fallo que el .gitignore).
    "*.bak*",
)

IP_PRIVADA_RE = re.compile(
    r"\b(?:"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r")\b"
)

# El marcador EXIGE motivo: `# topologia: excepcion declarada` a secas no
# exime nada (una excepcion sin razon escrita no es una decision, es un
# silenciamiento). El motivo es todo lo que siga al marcador y debe
# contener al menos un caracter no blanco.
MARCADOR_EXCEPCION = re.compile(r"#\s*topologia:\s*excepcion declarada\s+(?P<motivo>\S.*)")


def _coincide_zona(ruta: str) -> bool:
    return any(fnmatch.fnmatch(ruta, patron) for patron in ZONA_PUBLICABLE)


def _coincide_exclusion(ruta: str) -> bool:
    return any(fnmatch.fnmatch(ruta, patron) for patron in EXCLUSIONES)


def _ficheros_versionados() -> list[str]:
    salida = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    return [linea for linea in salida.stdout.splitlines() if linea]


def _tiene_excepcion_declarada(lineas: list[str], idx: int) -> bool:
    if MARCADOR_EXCEPCION.search(lineas[idx]):
        return True
    if idx > 0 and MARCADOR_EXCEPCION.search(lineas[idx - 1]):
        return True
    return False


def encuentra_violaciones() -> list[tuple[str, int, str]]:
    """Devuelve (ruta, num_linea_1indexado, texto_ip) por cada violacion."""
    violaciones: list[tuple[str, int, str]] = []
    for ruta in _ficheros_versionados():
        if not _coincide_zona(ruta):
            continue
        if _coincide_exclusion(ruta):
            continue
        f = REPO / ruta
        if not f.is_file():
            continue
        try:
            texto = f.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            continue
        lineas = texto.splitlines()
        for idx, linea in enumerate(lineas):
            for m in IP_PRIVADA_RE.finditer(linea):
                if _tiene_excepcion_declarada(lineas, idx):
                    continue
                violaciones.append((ruta, idx + 1, m.group(0)))
    return violaciones


def main() -> int:
    violaciones = encuentra_violaciones()
    if not violaciones:
        print("OK: zona publicable sin IPs privadas sin excepcion declarada.")
        return 0
    print("::error::TOPOLOGIA REAL EN ZONA PUBLICABLE (repositorio PUBLICO):")
    for ruta, num, ip in violaciones:
        print(
            f"::error file={ruta},line={num}::"
            f"{ruta}:{num} publica una IP privada ({ip}) sin "
            f"'# topologia: excepcion declarada <motivo>'. Sustituyela por un "
            f"valor RFC 5737 (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24) "
            f"o declara la excepcion explicitamente si esta justificada."
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
