#!/usr/bin/env python3
"""Gate: ninguna IP privada real en SUPERFICIE PUBLICABLE sin excepcion declarada.

Contexto (EXP-1): este repositorio es PUBLICO. Una IP privada publicada
describe gratis la topologia de la red interna a quien la lea.

LA FRONTERA
===========
La pregunta no es "cuantas apariciones quedan en el arbol" sino "que parte del
arbol GOBIERNA O EXPLICA el producto hoy". Todo fichero versionado cae en
exactamente UNA de estas tres categorias, y la funcion `clasifica()` lo decide
sin ambiguedad:

  1. PUBLICABLE  -> se exige limpieza. Son cuatro CLASES, no una lista de
     ficheros. Una lista fija se queda pequena el dia siguiente; una clase
     encuentra lo que todavia no existe:

       `configuracion-publicable`  plantillas y configuracion de ejemplo que un
                                   operador copia (`*.example`, `.env.example`,
                                   la config de ejemplo de `data-engine`).
       `codigo-no-test`            codigo que se ejecuta en el producto: `.py`,
                                   `.ts`, `.js`, `.sh`, `.sql`. Es la clase que
                                   hace que el gate pueda encontrar algo NUEVO,
                                   y la que lo obliga a mirarse a si mismo (ver
                                   AUTOCOBERTURA).
       `documentacion-de-operador` lo que alguien lee para desplegar u operar:
                                   `deploy/**`, `deployments/**`, cualquier
                                   `README.md`, y los documentos ofimaticos de
                                   la raiz.
       `documentacion-CURRENT`     `docs/current/**`: lo que el arbol declara
                                   vigente. "Current" y "historico diferido" no
                                   pueden ser verdad a la vez.

  2. TEST-O-FIXTURE -> fuera de alcance, y a proposito. `tests/`, `**/tests/**`,
     `**/fixtures/**` y los ficheros `test_*.py` usan IP privadas reales como
     CONTROL POSITIVO de que el producto falla cerrado contra produccion
     (`viewer/tests/test_neo4j_default_fail_closed.py`, `tests/support/
     prod_block.py`). Un gate que los tumba se desactiva al tercer falso
     positivo, y entonces no protege nada. Es una categoria propia, no un
     parche: el gate los CUENTA y lo dice, para que su exclusion se vea.

  3. FUERA DE SUPERFICIE -> ni publicable ni test. Documentacion historica y
     todo lo demas. El diferimiento de `docs/**` historico NO es de este gate:
     es una decision escrita del operador (RK-19 en
     `docs/coordination/risk-register.md`, P1, ABIERTO), y redactar informes de
     auditoria en masa destruiria su valor probatorio. `EXCEPCIONES_HISTORICAS`
     lo declara patron a patron CON SU MOTIVO, y el gate los imprime al final:
     un diferimiento que no se ve es un diferimiento que se olvida.

EXCEPCION LOCALIZADA
====================
Dentro de la superficie publicable, una linea concreta puede eximirse con
`# topologia: excepcion declarada <motivo>` en la misma linea o en la
inmediatamente anterior. El <motivo> es OBLIGATORIO y no puede estar vacio: el
marcador a secas no exime nada. Estar documentada no hace aceptable una
direccion; declararla, localizada y con razon, si.

PENDIENTE ANOTADO (no implementado): el marcador no deja registro de QUIEN
declaro la excepcion ni cuando. Exigir autoria verificable necesita una fuente
de autoridad (CODEOWNERS, firma de commit, registro aparte); es un carril
propio, no un retoque de este regex.

AUTOCOBERTURA
=============
Este fichero y sus calibradores son `.py` fuera de `tests/`, luego caen en
`codigo-no-test` y el gate SE MIRA A SI MISMO por construccion, sin lista
especial. No es cosmetico: la ronda 1 de EXP-1 introdujo tres publicaciones
nuevas de la IP real en el propio guardarrail y este era ciego a su
reincidencia porque aquellos ficheros no estaban en su zona. Hoy no puede
serlo: para volver a publicarla habria que declarar una excepcion con motivo,
que se lee en el diff.

TECHO DECLARADO (lo que este gate NO ve, medido, no supuesto)
=============================================================
  * Texto plano y XML de OOXML. Interpreta rutas, lineas y las partes XML de
    `.docx`/`.xlsx`/`.pptx` (ver `_texto_ooxml`), pero NO es un motor
    semantico: no resuelve interpolacion, `include`, ni una direccion
    construida por concatenacion en tiempo de ejecucion.
  * PDF, imagenes y cualquier otro binario que no sea OOXML: no se inspeccionan.
  * `docs/**` historico, por decision escrita (RK-19), no por incapacidad.
  * FAMILIAS DE DIRECCIONES QUE `IP_PRIVADA_RE` NO CUBRE. El techo de arriba
    habla del FORMATO que se lee; este habla de QUE SE BUSCA dentro de el, que
    es una omision distinta y mas facil de confundir con cobertura:
      - **CGNAT `100.64.0.0/10`**, que es el rango de Tailscale. Esta
        instalacion USA Tailscale y el propio RK-19 documenta una direccion de
        ese rango, o sea que no es una familia hipotetica. Medido hoy sobre
        este arbol: 12 apariciones CGNAT, 7 en `fuera-de-superficie` y 5 en
        `test-o-fixture`, y **0 en superficie publicable**. No hay exposicion
        que tapar, pero el dia que la haya ESTE GATE NO LA VERA.
      - IPv6 en todas sus formas: ULA `fc00::/7`, link-local `fe80::/10` y
        direcciones globales.
      - Link-local IPv4 `169.254.0.0/16`.
      - Direcciones PUBLICAS, nombres DNS y hostnames MagicDNS. Un
        `host.tailnet.ts.net` o un dominio interno describen la topologia
        igual de bien que una IP, y aqui no los busca nadie.
    Ampliarlo no es anadir alternativas al regex sin mas: cada familia trae
    sus propios falsos positivos (un `fe80::` de ejemplo en un test, un
    dominio publico legitimo en un README) y necesita su calibracion, que es
    lo que hace util a un gate. Queda declarado, no prometido.

Uso:  python3 .github/scripts/check_no_topologia_publicable.py
Sale 0 si la superficie publicable esta limpia; 1 y describe cada violacion.
"""
from __future__ import annotations

import fnmatch
import io
import re
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# --------------------------------------------------------------------------
# Categoria 1: SUPERFICIE PUBLICABLE, por clases.
# --------------------------------------------------------------------------
#: `clase -> patrones fnmatch sobre la ruta relativa`. El orden importa solo
#: para nombrar la clase en el informe; para el veredicto basta con encajar en
#: cualquiera.
CLASES_PUBLICABLES: dict[str, tuple[str, ...]] = {
    "configuracion-publicable": (
        ".env.example",
        "*.env.example",
        "*/.env.example",
        "*.example",
        "*/*.example",
        "*/*/*.example",
        "data-engine/config/settings.yaml",
    ),
    "codigo-no-test": (
        "*.py",
        "*/*.py",
        "*.ts", "*.tsx", "*.js", "*.mjs",
        "*.sh",
        "*.sql",
    ),
    "documentacion-de-operador": (
        "deploy/*",
        "deploy/**",
        "deployments/*",
        "deployments/**",
        "README.md",
        "*/README.md",
        "*/*/README.md",
        "*.docx", "*.xlsx", "*.pptx",
    ),
    "documentacion-CURRENT": (
        "docs/current/*",
        "docs/current/**",
    ),
}

# --------------------------------------------------------------------------
# Categoria 2: TEST-O-FIXTURE. No se exige limpieza, y se dice cuantos son.
# --------------------------------------------------------------------------
PATRONES_TEST_O_FIXTURE: tuple[str, ...] = (
    "tests/*", "tests/**",
    "*/tests/*", "*/tests/**",
    "*/*/tests/*", "*/*/tests/**",
    "*/fixtures/*", "*/fixtures/**",
    "fixtures/*", "fixtures/**",
    "test_*.py", "*/test_*.py", "*/*/test_*.py", "*/*/*/test_*.py",
    "conftest.py", "*/conftest.py", "*/*/conftest.py",
)

# --------------------------------------------------------------------------
# Categoria 3 (parcial): excepciones HISTORICAS, explicitas y con motivo.
# Se aplican DESPUES de las clases publicables: sacan de la superficie algo que
# una clase habria arrastrado. Cada una lleva su razon escrita y el gate las
# imprime, porque un diferimiento silencioso deja de ser una decision.
# --------------------------------------------------------------------------
EXCEPCIONES_HISTORICAS: tuple[tuple[str, str], ...] = (
    (
        "*.bak*",
        "copias de seguridad del utillaje (`fichero.bak.<timestamp>`, "
        "`fichero.bak-<fecha>`). Son historico, no superficie; las cuatro que "
        "publicaban la IP real salieron del indice en EXP-1 y la regla "
        "`*.bak*` del .gitignore impide que vuelvan.",
    ),
    (
        "docs/current/EXTERNAL_SOURCES_DESIGN.md",
        "pese a vivir en `docs/current/`, el documento se declara a si mismo "
        "en su cabecera 'Documento de la era v1/v2 (legacy); la linea vigente "
        "es V3'. La declaracion del documento manda sobre el nombre de la "
        "carpeta; queda bajo RK-19 como historico.",
    ),
    (
        "docs/current/INFORME_ENTREGA.md",
        "idem: se declara 'era v1/v2 (legacy)' en su propia cabecera; "
        "historico bajo RK-19.",
    ),
    (
        "docs/current/RPG_GRAPH_MODEL_UPDATE.md",
        "idem: se declara 'era v1/v2 (legacy)' en su propia cabecera; "
        "historico bajo RK-19.",
    ),
)

IP_PRIVADA_RE = re.compile(
    r"\b(?:"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r")\b"
)

#: El motivo es obligatorio: al menos un caracter no blanco despues del
#: marcador.
MARCADOR_EXCEPCION = re.compile(
    r"#\s*topologia:\s*excepcion declarada\s+(?P<motivo>\S.*)"
)

#: Partes de un OOXML que se inspeccionan. El texto de un .docx vive en el XML
#: de dentro del ZIP: un gate que mira el binario no ve nada y un gate que mira
#: solo el nombre del fichero MIENTE sobre su cobertura.
OOXML_SUFIJOS = (".docx", ".xlsx", ".pptx")
OOXML_PARTES = (".xml", ".rels")


def _coincide(ruta: str, patrones) -> bool:
    return any(fnmatch.fnmatch(ruta, p) for p in patrones)


def clase_publicable(ruta: str) -> str | None:
    """Clase de superficie publicable de `ruta`, o None si no es publicable."""
    for clase, patrones in CLASES_PUBLICABLES.items():
        if _coincide(ruta, patrones):
            return clase
    return None


def es_test_o_fixture(ruta: str) -> bool:
    return _coincide(ruta, PATRONES_TEST_O_FIXTURE)


def excepcion_historica(ruta: str) -> str | None:
    """Motivo de la excepcion historica que cubre `ruta`, o None."""
    for patron, motivo in EXCEPCIONES_HISTORICAS:
        if fnmatch.fnmatch(ruta, patron):
            return motivo
    return None


def clasifica(ruta: str) -> tuple[str, str]:
    """(categoria, detalle). Categoria en {publicable, test-o-fixture,
    fuera-de-superficie}. La frontera es decidible: un fichero cae en una y
    solo una, y este es el unico sitio donde se decide."""
    if es_test_o_fixture(ruta):
        return "test-o-fixture", "control positivo de fail-closed"
    motivo = excepcion_historica(ruta)
    if motivo is not None:
        return "fuera-de-superficie", f"excepcion historica: {motivo}"
    clase = clase_publicable(ruta)
    if clase is not None:
        return "publicable", clase
    return "fuera-de-superficie", "no es superficie publicable"


def _ficheros_versionados() -> list[str]:
    salida = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    )
    return [linea for linea in salida.stdout.splitlines() if linea]


def _tiene_excepcion_declarada(lineas: list[str], idx: int) -> bool:
    if MARCADOR_EXCEPCION.search(lineas[idx]):
        return True
    if idx > 0 and MARCADOR_EXCEPCION.search(lineas[idx - 1]):
        return True
    return False


def _texto_ooxml(f: Path) -> list[tuple[str, str]]:
    """[(nombre_de_parte, texto)] de las partes XML de un OOXML.

    Abre el ZIP de verdad. Si el fichero no es un ZIP valido devuelve [] y el
    gate no inventa cobertura sobre el.
    """
    try:
        datos = f.read_bytes()
    except OSError:
        return []
    try:
        with zipfile.ZipFile(io.BytesIO(datos)) as z:
            partes = []
            for nombre in z.namelist():
                if nombre.endswith(OOXML_PARTES):
                    partes.append(
                        (nombre, z.read(nombre).decode("utf-8", errors="ignore"))
                    )
            return partes
    except (zipfile.BadZipFile, OSError):
        return []


def encuentra_violaciones() -> list[tuple[str, int, str]]:
    """(ruta, num_linea_1indexado, texto_ip) por cada violacion.

    Para un OOXML, `ruta` lleva sufijo `!<parte>` y la linea es la del XML
    dentro de esa parte: sin eso, la causa no seria accionable.
    """
    violaciones: list[tuple[str, int, str]] = []
    for ruta in _ficheros_versionados():
        categoria, _ = clasifica(ruta)
        if categoria != "publicable":
            continue
        f = REPO / ruta
        if not f.is_file():
            continue

        if ruta.endswith(OOXML_SUFIJOS):
            for parte, texto in _texto_ooxml(f):
                for idx, linea in enumerate(texto.splitlines()):
                    for m in IP_PRIVADA_RE.finditer(linea):
                        violaciones.append((f"{ruta}!{parte}", idx + 1, m.group(0)))
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


def censo() -> dict[str, int]:
    """Cuantos ficheros ve el gate en cada categoria. Un gate que no sabe decir
    cuanto mira no puede afirmar que mira algo."""
    cuenta = {"publicable": 0, "test-o-fixture": 0, "fuera-de-superficie": 0}
    for ruta in _ficheros_versionados():
        cuenta[clasifica(ruta)[0]] += 1
    return cuenta


def main() -> int:
    c = censo()
    print(
        "Superficie vigilada: "
        f"{c['publicable']} ficheros publicables | "
        f"{c['test-o-fixture']} tests/fixtures (excluidos a proposito) | "
        f"{c['fuera-de-superficie']} fuera de superficie."
    )
    print("Excepciones historicas declaradas (diferidas, no invisibles):")
    for patron, motivo in EXCEPCIONES_HISTORICAS:
        print(f"  - {patron}: {motivo}")

    violaciones = encuentra_violaciones()
    if not violaciones:
        print("OK: superficie publicable sin IPs privadas sin excepcion declarada.")
        return 0
    print("::error::TOPOLOGIA REAL EN SUPERFICIE PUBLICABLE (repositorio PUBLICO):")
    for ruta, num, ip in violaciones:
        fichero = ruta.split("!", 1)[0]
        print(
            f"::error file={fichero},line={num}::"
            f"{ruta}:{num} publica una IP privada ({ip}) sin "
            f"'# topologia: excepcion declarada <motivo>'. Sustituyela por un "
            f"valor RFC 5737 (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24), "
            f"por un marcador, o declara la excepcion con su motivo."
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
