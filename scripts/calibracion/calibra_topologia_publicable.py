#!/usr/bin/env python3
"""Calibracion de `check_no_topologia_publicable.py` (EXP-1).

Regla del operador: una afirmacion de seguridad no cuenta hasta que hay una
prueba capaz de ponerse roja. Este arnes introduce, DE VERDAD, sobre el arbol
de trabajo real, cada caso de la tabla, ejecuta el gate, lee su veredicto real,
y restaura por EFECTO (bytes identicos, comprobado por SHA-256 y por
`git status`).

Tabla:
  1. Una `10.x` metida en `viewer/.env.example`          -> ROJO, con causa.
  2. `192.0.2.x` (RFC 5737) en la misma superficie        -> VERDE.
  3. Un fixture legitimo con IP privada                   -> VERDE, con control
     positivo y con prueba anti-vacuidad (el motor SI lo reporta cuando se le
     retira la proteccion).
  4. Ablacion de la categoria `test-o-fixture` LLAMANDO AL MOTOR REAL -> sin
     ella el mismo fixture SI se reporta (0 -> N). Prueba que la exclusion hace
     trabajo DENTRO del gate, no que un regex case fuera de el.
  5. Excepcion declarada explicita                        -> VERDE, y sin el
     marcador vuelve a ROJO.
  6. Marcador de excepcion SIN motivo                     -> ROJO; con motivo,
     VERDE (control positivo del caso).
  7. **DOCX**: una IP privada inyectada DENTRO de `word/document.xml` del .docx
     real -> ROJO nombrando la parte; al retirarla, VERDE. Sin este caso el
     gate no podria DECLARAR cobertura de OOXML, solo prometerla.
  8. **AUTOCOBERTURA**: el propio gate y este calibrador son superficie
     publicable, y una IP metida en el fuente del gate lo pone ROJO contra si
     mismo. La ronda 1 de EXP-1 publico tres IP reales en el guardarrail
     precisamente porque el guardarrail no se miraba.
  9. **FRONTERA**: las tres categorias son disjuntas y totales, y ninguna de
     las tres esta vacia. Una frontera que clasifica todo en un solo cubo no
     es una frontera.

Ninguno de los casos reimplementa la deteccion: todos pasan por
`encuentra_violaciones()` o por `clasifica()`. Un motor destripado pone rojos
1, 3, 4, 5, 6, 7 y 8.

Ninguna IP REAL de la instalacion aparece aqui. Las `10.x` de abajo son
sinteticas -documentacion RFC1918 que no corresponde a ninguna maquina de esta
red- y existen para que el gate tenga algo que detectar; van con su excepcion
declarada porque este fichero ES superficie publicable y el gate se mira a si
mismo.

Uso: python3 scripts/calibracion/calibra_topologia_publicable.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GATE_PATH = REPO / ".github" / "scripts" / "check_no_topologia_publicable.py"
ENV_EXAMPLE = REPO / "viewer" / ".env.example"
FIXTURE_LEGITIMO = REPO / "viewer" / "tests" / "test_neo4j_default_fail_closed.py"
DOCX_TESTIGO = REPO / "S9_Knowledge_diseno_estado_fases_v2.docx"

ANCLA_ENV = "S9K_NEO4J_URI=bolt://192.0.2.10:7687"

# Valores SINTETICOS de calibracion. No son de esta red; existen para que el
# gate tenga algo que detectar.
# topologia: excepcion declarada valor sintetico de calibracion, no es una maquina de esta red
IP_SINTETICA_1 = "10.9.0.5"
# topologia: excepcion declarada valor sintetico de calibracion, no es una maquina de esta red
IP_SINTETICA_2 = "10.7.0.9"


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _arbol_tracked_limpio() -> bool:
    r = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=REPO, capture_output=True, text=True,
    )
    return r.returncode == 0 and r.stdout.strip() == ""


def _cargar_gate():
    spec = importlib.util.spec_from_file_location(
        "check_no_topologia_publicable", GATE_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _correr_gate() -> tuple[int, list[tuple[str, int, str]]]:
    mod = _cargar_gate()
    violaciones = mod.encuentra_violaciones()
    return (1 if violaciones else 0), violaciones


def _motor(mod, *, clases=None, tests=None, historicas=None):
    """Ejecuta `encuentra_violaciones()` -EL MOTOR REAL- con la configuracion
    ablacionada que se le pase.

    Ablacionar configuracion y volver a llamar al motor es lo unico que prueba
    que una regla hace trabajo DENTRO del gate. Reimplementar el regex aqui
    fuera probaria que el patron casa, no que el gate lo use: si alguien
    destripa `encuentra_violaciones()`, un arnes asi seguiria verde (fue
    exactamente el defecto de la ronda 1).
    """
    prev = (mod.CLASES_PUBLICABLES, mod.PATRONES_TEST_O_FIXTURE,
            mod.EXCEPCIONES_HISTORICAS)
    try:
        if clases is not None:
            mod.CLASES_PUBLICABLES = clases
        if tests is not None:
            mod.PATRONES_TEST_O_FIXTURE = tests
        if historicas is not None:
            mod.EXCEPCIONES_HISTORICAS = historicas
        return mod.encuentra_violaciones()
    finally:
        (mod.CLASES_PUBLICABLES, mod.PATRONES_TEST_O_FIXTURE,
         mod.EXCEPCIONES_HISTORICAS) = prev


class Fallo(Exception):
    pass


def _verifica(nombre: str, condicion: bool, detalle: str) -> None:
    if not condicion:
        raise Fallo(f"[{nombre}] {detalle}")
    print(f"  OK  {nombre}")


# --------------------------------------------------------------------------


def caso_1_ip_privada_nueva_se_pone_rojo() -> None:
    """Una IP privada metida en viewer/.env.example -> ROJO, con causa."""
    original = ENV_EXAMPLE.read_bytes()
    h0 = _sha256(ENV_EXAMPLE)
    texto = original.decode("utf-8")
    mutado = texto.replace(ANCLA_ENV, f"S9K_NEO4J_URI=bolt://{IP_SINTETICA_1}:7687")
    if mutado == texto:
        raise Fallo("caso-1: el ancla a mutar no aparece; el fuente se movio")
    try:
        ENV_EXAMPLE.write_text(mutado, encoding="utf-8")
        rc, violaciones = _correr_gate()
        _verifica("caso-1: se pone ROJO", rc == 1, f"esperaba rc=1, obtuve rc={rc}")
        rutas = [v[0] for v in violaciones]
        _verifica(
            "caso-1: la causa senala viewer/.env.example",
            "viewer/.env.example" in rutas, f"violaciones={violaciones}",
        )
        ips = [v[2] for v in violaciones if v[0] == "viewer/.env.example"]
        _verifica(
            "caso-1: la causa nombra la IP inyectada (no otra)",
            IP_SINTETICA_1 in ips, f"ips detectadas: {ips}",
        )
    finally:
        ENV_EXAMPLE.write_bytes(original)
        _verifica("caso-1: restauracion por hash",
                  _sha256(ENV_EXAMPLE) == h0, "el fichero no volvio a su original")


def caso_2_valor_ficticio_da_verde() -> None:
    """192.0.2.x (RFC 5737) ya presente en la plantilla -> VERDE."""
    texto = ENV_EXAMPLE.read_text(encoding="utf-8")
    if "192.0.2.10" not in texto:
        raise Fallo("caso-2: la plantilla ya no trae el valor RFC 5737 esperado")
    rc, violaciones = _correr_gate()
    rutas = [v[0] for v in violaciones]
    _verifica(
        "caso-2: el rango de documentacion no dispara el gate",
        "viewer/.env.example" not in rutas, f"violaciones: {violaciones}",
    )
    _verifica("caso-2: gate global VERDE", rc == 0, f"rc={rc}, violaciones={violaciones}")


def caso_3_fixture_legitimo_sigue_verde() -> None:
    """Un fixture con IP privada real sigue VERDE, y el verde no es vacuo."""
    if not FIXTURE_LEGITIMO.is_file():
        raise Fallo(f"caso-3: no existe {FIXTURE_LEGITIMO}, elige otro testigo")
    mod = _cargar_gate()
    rel = str(FIXTURE_LEGITIMO.relative_to(REPO))
    contenido = FIXTURE_LEGITIMO.read_text(encoding="utf-8", errors="ignore")

    # Control positivo SIN publicar el valor: se le pregunta al patron del gate.
    _verifica(
        "caso-3: el fixture SI contiene una IP privada (control positivo via "
        "IP_PRIVADA_RE, sin transcribir el valor)",
        mod.IP_PRIVADA_RE.search(contenido) is not None,
        "el fixture elegido ya no es un control positivo valido",
    )
    _verifica(
        "caso-3: el gate lo clasifica como test-o-fixture, no como publicable",
        mod.clasifica(rel)[0] == "test-o-fixture", f"clasifica()={mod.clasifica(rel)}",
    )
    rc, violaciones = _correr_gate()
    _verifica("caso-3: el motor real NO lo reporta",
              rel not in [v[0] for v in violaciones], f"violaciones: {violaciones}")
    _verifica("caso-3: gate global VERDE", rc == 0, f"rc={rc}")

    ablacionado = _motor(mod, tests=())
    _verifica(
        "caso-3 (anti-vacuidad): sin la categoria test-o-fixture el motor SI "
        "lo reporta -> el verde es una decision del gate, no un motor ciego",
        any(v[0] == rel for v in ablacionado),
        "con la categoria ablacionada el motor sigue sin reportarlo: o no "
        "ejecuta, o el testigo ya no sirve",
    )


def caso_4_ablacion_categoria_tests() -> None:
    """Ablacion diferencial POR EL MOTOR REAL. Tres llamadas, cambiando solo
    la configuracion:

      (a) configuracion real                      -> 0 para el fixture
      (b) sin la categoria test-o-fixture         -> N>0
      (c) sin test-o-fixture y sin la clase de codigo -> N>0 igualmente
          (el fixture entra por `*/tests/*`... no: entra por `*.py`, asi que
          (c) mide que quien lo salvaba era la categoria, no la clase)
    """
    mod = _cargar_gate()
    rel = str(FIXTURE_LEGITIMO.relative_to(REPO))

    def n(vs):
        return sum(1 for v in vs if v[0] == rel)

    a = n(_motor(mod))
    b = n(_motor(mod, tests=()))
    clases_sin_codigo = {k: v for k, v in mod.CLASES_PUBLICABLES.items()
                         if k != "codigo-no-test"}
    c = n(_motor(mod, clases=clases_sin_codigo))

    _verifica("caso-4a: con la configuracion real, 0 violaciones del fixture",
              a == 0, f"obtuve {a}")
    _verifica(
        "caso-4b: quitando SOLO la categoria test-o-fixture, el motor real SI "
        "lo reporta -> la categoria hace trabajo dentro del gate",
        b > 0, f"esperaba >0, obtuve {b}; si es 0, el motor no esta ejecutando",
    )
    _verifica(
        "caso-4c: quitando SOLO la clase `codigo-no-test` (con la categoria "
        "puesta) sigue en 0 -> lo que lo salva es la categoria, no la clase",
        c == 0, f"esperaba 0, obtuve {c}",
    )
    _verifica(f"caso-4: el diferencial 0 -> {b} lo produce SOLO la categoria",
              a == 0 and b > 0, f"a={a}, b={b}, c={c}")


def caso_5_excepcion_declarada() -> None:
    """IP privada con marcador -> VERDE; la misma linea sin el -> ROJO."""
    original = ENV_EXAMPLE.read_bytes()
    h0 = _sha256(ENV_EXAMPLE)
    texto = original.decode("utf-8")
    if ANCLA_ENV not in texto:
        raise Fallo("caso-5: el ancla a mutar no aparece; el fuente se movio")
    sin = texto.replace(ANCLA_ENV, f"S9K_NEO4J_URI=bolt://{IP_SINTETICA_2}:7687")
    con = texto.replace(
        ANCLA_ENV,
        "# topologia: excepcion declarada (calibracion EXP-1, valor sintetico)\n"
        f"S9K_NEO4J_URI=bolt://{IP_SINTETICA_2}:7687",
    )
    try:
        ENV_EXAMPLE.write_text(sin, encoding="utf-8")
        rc, v = _correr_gate()
        _verifica("caso-5a: SIN marcador -> ROJO",
                  rc == 1 and any(x[0] == "viewer/.env.example" for x in v),
                  f"rc={rc}, violaciones={v}")
        ENV_EXAMPLE.write_text(con, encoding="utf-8")
        rc, v = _correr_gate()
        _verifica("caso-5b: la MISMA IP CON marcador -> VERDE",
                  rc == 0 and not any(x[0] == "viewer/.env.example" for x in v),
                  f"rc={rc}, violaciones={v}")
    finally:
        ENV_EXAMPLE.write_bytes(original)
        _verifica("caso-5: restauracion por hash",
                  _sha256(ENV_EXAMPLE) == h0, "el fichero no volvio a su original")


def caso_6_marcador_sin_motivo_no_exime() -> None:
    """El marcador SIN motivo no exime; con motivo, si."""
    original = ENV_EXAMPLE.read_bytes()
    h0 = _sha256(ENV_EXAMPLE)
    texto = original.decode("utf-8")
    if ANCLA_ENV not in texto:
        raise Fallo("caso-6: el ancla a mutar no aparece; el fuente se movio")
    sin_motivo = texto.replace(
        ANCLA_ENV,
        "# topologia: excepcion declarada\n"
        f"S9K_NEO4J_URI=bolt://{IP_SINTETICA_2}:7687",
    )
    con_motivo = texto.replace(
        ANCLA_ENV,
        "# topologia: excepcion declarada (calibracion EXP-1, valor sintetico)\n"
        f"S9K_NEO4J_URI=bolt://{IP_SINTETICA_2}:7687",
    )
    try:
        ENV_EXAMPLE.write_text(sin_motivo, encoding="utf-8")
        rc, v = _correr_gate()
        _verifica("caso-6a: marcador SIN motivo -> sigue ROJO",
                  rc == 1 and any(x[0] == "viewer/.env.example" for x in v),
                  f"un marcador mudo eximio la linea: rc={rc}, violaciones={v}")
        ENV_EXAMPLE.write_text(con_motivo, encoding="utf-8")
        rc, v = _correr_gate()
        _verifica("caso-6b (control positivo): CON motivo -> VERDE",
                  rc == 0 and not any(x[0] == "viewer/.env.example" for x in v),
                  f"rc={rc}, violaciones={v}")
    finally:
        ENV_EXAMPLE.write_bytes(original)
        _verifica("caso-6: restauracion por hash",
                  _sha256(ENV_EXAMPLE) == h0, "el fichero no volvio a su original")


def _reescribe_docx(origen: bytes, viejo: str, nuevo: str) -> bytes:
    """Devuelve el .docx con `viejo` -> `nuevo` dentro de word/document.xml."""
    salida = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(origen)) as zin, \
            zipfile.ZipFile(salida, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "word/document.xml":
                data = data.decode("utf-8").replace(viejo, nuevo).encode("utf-8")
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zout.writestr(zi, data)
    return salida.getvalue()


def caso_7_docx_cobertura_real() -> None:
    """Un conocido negativo DENTRO de `word/document.xml`.

    El gate declara cobertura de OOXML. Declararla sin ejercerla seria
    exactamente la clase de promesa que este programa corta: la prueba es
    inyectar la direccion en el XML de dentro del ZIP, exigir el ROJO con la
    parte nombrada, y verla volver a VERDE al retirarla.
    """
    if not DOCX_TESTIGO.is_file():
        raise Fallo(f"caso-7: no existe {DOCX_TESTIGO}")
    original = DOCX_TESTIGO.read_bytes()
    h0 = _sha256(DOCX_TESTIGO)
    rel = str(DOCX_TESTIGO.relative_to(REPO))
    mod = _cargar_gate()

    _verifica(
        "caso-7 (frontera): el .docx esta en la superficie publicable",
        mod.clasifica(rel)[0] == "publicable", f"clasifica()={mod.clasifica(rel)}",
    )
    partes = mod._texto_ooxml(DOCX_TESTIGO)
    _verifica(
        "caso-7 (control positivo del instrumento): el gate SI abre el ZIP y "
        "lee word/document.xml",
        any(n == "word/document.xml" and len(t) > 0 for n, t in partes),
        f"partes leidas: {[n for n, _ in partes]}",
    )

    ancla = "IP-VM105-REDACTADA"
    if ancla not in dict(partes).get("word/document.xml", ""):
        raise Fallo(
            "caso-7: no encuentro el marcador saneado en word/document.xml; "
            "el documento cambio y este testigo ya no sirve"
        )
    try:
        DOCX_TESTIGO.write_bytes(_reescribe_docx(original, ancla, IP_SINTETICA_1))
        rc, v = _correr_gate()
        culpables = [x for x in v if x[0].startswith(rel)]
        _verifica(
            "caso-7: con la IP dentro del XML, el gate se pone ROJO",
            rc == 1 and bool(culpables), f"rc={rc}, violaciones={v}",
        )
        _verifica(
            "caso-7: la causa NOMBRA la parte del ZIP, no solo el fichero",
            all("!word/document.xml" in x[0] for x in culpables),
            f"causas: {[x[0] for x in culpables]}",
        )
        _verifica(
            "caso-7: la causa nombra la IP inyectada",
            all(x[2] == IP_SINTETICA_1 for x in culpables),
            f"ips: {[x[2] for x in culpables]}",
        )
    finally:
        DOCX_TESTIGO.write_bytes(original)
        _verifica("caso-7: restauracion por hash",
                  _sha256(DOCX_TESTIGO) == h0, "el .docx no volvio a su original")

    rc, v = _correr_gate()
    _verifica("caso-7: retirada la inyeccion, VERDE otra vez",
              rc == 0 and not any(x[0].startswith(rel) for x in v),
              f"rc={rc}, violaciones={v}")


def caso_8_autocobertura_del_guardarrail() -> None:
    """El gate se mira A SI MISMO.

    En la ronda 1 de EXP-1 el propio guardarrail publico tres veces la IP real
    y era ciego a su reincidencia porque sus ficheros no estaban en su zona.
    Aqui se exige lo contrario: el fuente del gate y el de este calibrador son
    superficie publicable, y una IP metida en el gate lo pone ROJO contra si
    mismo.
    """
    mod = _cargar_gate()
    rel_gate = str(GATE_PATH.relative_to(REPO))
    rel_cal = str(Path(__file__).resolve().relative_to(REPO))
    for etiqueta, rel in (("el gate", rel_gate), ("este calibrador", rel_cal)):
        cat, clase = mod.clasifica(rel)
        _verifica(
            f"caso-8: {etiqueta} es superficie publicable ({clase})",
            cat == "publicable", f"clasifica({rel})=({cat}, {clase})",
        )

    original = GATE_PATH.read_bytes()
    h0 = _sha256(GATE_PATH)
    ancla = "REPO = Path(__file__).resolve().parents[2]"
    texto = original.decode("utf-8")
    if ancla not in texto:
        raise Fallo("caso-8: el ancla de inyeccion no aparece en el gate")
    try:
        GATE_PATH.write_text(
            texto.replace(
                ancla,
                f'_REINCIDENCIA = "http://{IP_SINTETICA_2}:7687"\n{ancla}',
            ),
            encoding="utf-8",
        )
        rc, v = _correr_gate()
        _verifica(
            "caso-8: una IP nueva EN EL PROPIO GATE lo pone ROJO",
            rc == 1 and any(x[0] == rel_gate for x in v), f"rc={rc}, violaciones={v}",
        )
    finally:
        GATE_PATH.write_bytes(original)
        _verifica("caso-8: restauracion por hash",
                  _sha256(GATE_PATH) == h0, "el gate no volvio a su original")


def caso_9_frontera_decidible() -> None:
    """Las tres categorias son disjuntas, totales y ninguna esta vacia."""
    mod = _cargar_gate()
    ficheros = mod._ficheros_versionados()
    cuenta = {"publicable": 0, "test-o-fixture": 0, "fuera-de-superficie": 0}
    for r in ficheros:
        cat, _ = mod.clasifica(r)
        if cat not in cuenta:
            raise Fallo(f"caso-9: categoria desconocida {cat!r} para {r}")
        cuenta[cat] += 1
    _verifica("caso-9: toda ruta cae en una de las tres categorias",
              sum(cuenta.values()) == len(ficheros), f"{cuenta} vs {len(ficheros)}")
    for cat, n in cuenta.items():
        _verifica(
            f"caso-9: la categoria '{cat}' no esta vacia ({n} ficheros)",
            n > 0,
            "una frontera que mete todo en un cubo no distingue nada",
        )
    _verifica(
        "caso-9: la superficie publicable es sustancialmente mas ancha que la "
        f"lista de nueve ficheros de la ronda 1 ({cuenta['publicable']})",
        cuenta["publicable"] > 100,
        "si la clase solo cubre lo ya arreglado, no puede encontrar nada nuevo",
    )


CASOS = [
    caso_1_ip_privada_nueva_se_pone_rojo,
    caso_2_valor_ficticio_da_verde,
    caso_3_fixture_legitimo_sigue_verde,
    caso_4_ablacion_categoria_tests,
    caso_5_excepcion_declarada,
    caso_6_marcador_sin_motivo_no_exime,
    caso_7_docx_cobertura_real,
    caso_8_autocobertura_del_guardarrail,
    caso_9_frontera_decidible,
]


def main() -> int:
    if not _arbol_tracked_limpio():
        print("ERROR: el arbol tracked no esta limpio antes de calibrar; "
              "commitea o revierte antes de correr este arnes.", file=sys.stderr)
        return 2

    fallos = []
    for caso in CASOS:
        print(f"-- {caso.__name__} --")
        try:
            caso()
        except Fallo as e:
            print(f"  FALLO: {e}", file=sys.stderr)
            fallos.append(str(e))

    if not _arbol_tracked_limpio():
        print("ERROR: el arbol tracked quedo sucio tras la calibracion "
              "(alguna restauracion fallo).", file=sys.stderr)
        return 2

    if fallos:
        print(f"\n{len(fallos)} caso(s) fallaron:", file=sys.stderr)
        for f in fallos:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print(f"\nOK: {len(CASOS)}/{len(CASOS)} casos dieron el veredicto esperado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
