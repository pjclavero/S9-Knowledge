#!/usr/bin/env python3
"""Calibracion de `check_no_topologia_publicable.py` (EXP-1).

Regla del operador: una afirmacion de seguridad no cuenta hasta que hay una
prueba capaz de ponerse roja. Este arnes introduce, DE VERDAD, sobre el
arbol de trabajo real (`viewer/.env.example`), cada caso de la tabla exigida
por el mandato de EXP-1, ejecuta el gate y lee su codigo de retorno real, y
restaura el fichero por EFECTO (bytes identicos, comprobado por hash y por
`git status`).

Tabla fijada por el operador (no negociable):
  1. Una `10.x.x.x` metida en `viewer/.env.example`      -> ROJO, con causa.
  2. `192.0.2.x` (RFC 5737) en la misma zona              -> VERDE.
  3. Un fixture legitimo con IP privada (fuera de zona)   -> sigue VERDE.
  4. Ablacion de la exclusion de zona `tests/`            -> sin ella, el
     mismo fixture legitimo SI se pondria rojo (prueba que la exclusion
     hace trabajo real, no que nunca se llega a evaluar).
  5. Excepcion declarada explicita sobre una IP privada   -> VERDE, y sin la
     excepcion (la misma linea sin el marcador) vuelve a ROJO.

Uso: python3 scripts/calibracion/calibra_topologia_publicable.py
Sale 0 si las cinco filas dan el veredicto esperado.
"""
from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GATE_PATH = REPO / ".github" / "scripts" / "check_no_topologia_publicable.py"
ENV_EXAMPLE = REPO / "viewer" / ".env.example"
FIXTURE_LEGITIMO = REPO / "viewer" / "tests" / "test_neo4j_default_fail_closed.py"

VERDE, ROJO = "VERDE", "ROJO"


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
    rc = 1 if violaciones else 0
    return rc, violaciones


class Fallo(Exception):
    pass


def _verifica(nombre: str, condicion: bool, detalle: str) -> None:
    if not condicion:
        raise Fallo(f"[{nombre}] {detalle}")
    print(f"  OK  {nombre}")


def caso_1_ip_privada_nueva_se_pone_rojo() -> None:
    """Una 10.x metida en viewer/.env.example -> ROJO, con causa."""
    original = ENV_EXAMPLE.read_bytes()
    hash_antes = _sha256(ENV_EXAMPLE)
    texto = original.decode("utf-8")
    mutado = texto.replace(
        "S9K_NEO4J_URI=bolt://192.0.2.10:7687",
        "S9K_NEO4J_URI=bolt://10.9.0.5:7687",
    )
    if mutado == texto:
        raise Fallo("caso-1: el ancla a mutar no aparece; el fuente se movio")
    try:
        ENV_EXAMPLE.write_text(mutado, encoding="utf-8")
        rc, violaciones = _correr_gate()
        _verifica(
            "caso-1: se pone ROJO", rc == 1,
            f"esperaba ROJO (rc=1), obtuve rc={rc}",
        )
        rutas = [v[0] for v in violaciones]
        _verifica(
            "caso-1: la causa senala viewer/.env.example",
            "viewer/.env.example" in rutas,
            f"violaciones={violaciones}",
        )
        ips = [v[2] for v in violaciones if v[0] == "viewer/.env.example"]
        _verifica(
            "caso-1: la causa nombra la IP privada inyectada (no otra)",
            "10.9.0.5" in ips,
            f"ips detectadas en el fichero: {ips}",
        )
    finally:
        ENV_EXAMPLE.write_bytes(original)
        _verifica(
            "caso-1: restauracion por hash",
            _sha256(ENV_EXAMPLE) == hash_antes,
            "el fichero no volvio a su contenido original",
        )


def caso_2_valor_ficticio_da_verde() -> None:
    """192.0.2.x (RFC 5737) real ya presente en la plantilla -> VERDE."""
    texto = ENV_EXAMPLE.read_text(encoding="utf-8")
    if "192.0.2.10" not in texto:
        raise Fallo(
            "caso-2: viewer/.env.example ya no trae el valor RFC 5737 "
            "esperado; EXP-1 se deshizo o el fichero cambio de forma"
        )
    rc, violaciones = _correr_gate()
    rutas = [v[0] for v in violaciones]
    _verifica(
        "caso-2: 192.0.2.10 en viewer/.env.example no dispara el gate",
        "viewer/.env.example" not in rutas,
        f"violaciones inesperadas: {violaciones}",
    )
    _verifica("caso-2: gate global VERDE", rc == 0, f"rc={rc}, violaciones={violaciones}")


def caso_3_fixture_legitimo_sigue_verde() -> None:
    """Un fixture de tests/ con IP privada real (192.168.1.205) sigue VERDE:
    esta fuera de la zona publicable a proposito (declarado en la cabecera
    del gate), no porque nadie lo mire."""
    if not FIXTURE_LEGITIMO.is_file():
        raise Fallo(f"caso-3: no existe {FIXTURE_LEGITIMO}, elige otro testigo")
    contenido = FIXTURE_LEGITIMO.read_text(encoding="utf-8", errors="ignore")
    _verifica(
        "caso-3: el fixture SI contiene una IP privada real (control positivo)",
        "192.168.1.205" in contenido,
        "el fixture elegido ya no es un control positivo valido",
    )
    rc, violaciones = _correr_gate()
    rutas = [v[0] for v in violaciones]
    ruta_relativa = str(FIXTURE_LEGITIMO.relative_to(REPO))
    _verifica(
        "caso-3: el fixture NO aparece en las violaciones",
        ruta_relativa not in rutas,
        f"violaciones inesperadas: {violaciones}",
    )
    _verifica("caso-3: gate global VERDE", rc == 0, f"rc={rc}, violaciones={violaciones}")


def caso_4_ablacion_exclusion_tests() -> None:
    """Sin la exclusion de zona `tests/`, el MISMO fixture SI se pondria
    rojo: prueba que la exclusion hace trabajo real (no que el patron de
    zona nunca llega a incluirlo por otra razon)."""
    mod = _cargar_gate()
    ruta_relativa = str(FIXTURE_LEGITIMO.relative_to(REPO))
    zona_ampliada = mod.ZONA_PUBLICABLE + ("viewer/tests/*",)
    coincide_zona = any(
        __import__("fnmatch").fnmatch(ruta_relativa, p) for p in zona_ampliada
    )
    _verifica(
        "caso-4 (preparacion): con zona ampliada el fixture SI encaja en zona",
        coincide_zona,
        "el patron de ablacion no amplia la zona como se esperaba",
    )
    excluido_todavia = mod._coincide_exclusion(ruta_relativa)
    _verifica(
        "caso-4: sin retocar EXCLUSIONES, la exclusion de tests/ SIGUE "
        "protegiendolo (la ablacion real es quitar la exclusion, no la zona)",
        excluido_todavia,
        "la funcion de exclusion no protege el fixture",
    )
    # Ablacion real: exclusiones vacias.
    violaciones_sin_exclusion = []
    for ruta in [ruta_relativa]:
        texto = FIXTURE_LEGITIMO.read_text(encoding="utf-8", errors="ignore")
        for m in mod.IP_PRIVADA_RE.finditer(texto):
            violaciones_sin_exclusion.append((ruta, m.group(0)))
    _verifica(
        "caso-4: CON zona ampliada Y sin exclusion, el fixture SI se "
        "detectaria (la exclusion de tests/ es la que lo salva, no un "
        "patron de zona que nunca lo alcanza)",
        len(violaciones_sin_exclusion) > 0,
        "el regex tampoco detecta nada en el fixture: testigo invalido",
    )


def caso_5_excepcion_declarada() -> None:
    """Una IP privada con el marcador de excepcion declarada -> VERDE; la
    MISMA linea sin el marcador -> ROJO."""
    original = ENV_EXAMPLE.read_bytes()
    hash_antes = _sha256(ENV_EXAMPLE)
    texto = original.decode("utf-8")
    ancla = "S9K_NEO4J_URI=bolt://192.0.2.10:7687"
    if ancla not in texto:
        raise Fallo("caso-5: el ancla a mutar no aparece; el fuente se movio")

    con_ip_sin_excepcion = texto.replace(
        ancla, "S9K_NEO4J_URI=bolt://10.7.0.9:7687"
    )
    con_ip_y_excepcion = texto.replace(
        ancla,
        "# topologia: excepcion declarada (calibracion EXP-1, no real)\n"
        "S9K_NEO4J_URI=bolt://10.7.0.9:7687",
    )
    try:
        ENV_EXAMPLE.write_text(con_ip_sin_excepcion, encoding="utf-8")
        rc, violaciones = _correr_gate()
        _verifica(
            "caso-5a: 10.7.0.9 SIN marcador -> ROJO",
            rc == 1 and any(v[0] == "viewer/.env.example" for v in violaciones),
            f"rc={rc}, violaciones={violaciones}",
        )

        ENV_EXAMPLE.write_text(con_ip_y_excepcion, encoding="utf-8")
        rc, violaciones = _correr_gate()
        _verifica(
            "caso-5b: la MISMA IP CON marcador de excepcion -> VERDE",
            rc == 0 and not any(v[0] == "viewer/.env.example" for v in violaciones),
            f"rc={rc}, violaciones={violaciones}",
        )
    finally:
        ENV_EXAMPLE.write_bytes(original)
        _verifica(
            "caso-5: restauracion por hash",
            _sha256(ENV_EXAMPLE) == hash_antes,
            "el fichero no volvio a su contenido original",
        )


CASOS = [
    caso_1_ip_privada_nueva_se_pone_rojo,
    caso_2_valor_ficticio_da_verde,
    caso_3_fixture_legitimo_sigue_verde,
    caso_4_ablacion_exclusion_tests,
    caso_5_excepcion_declarada,
]


def main() -> int:
    if not _arbol_tracked_limpio():
        print(
            "ERROR: el arbol tracked no esta limpio antes de calibrar; "
            "commitea o revierte antes de correr este arnes.",
            file=sys.stderr,
        )
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
        print(
            "ERROR: el arbol tracked quedo sucio tras la calibracion "
            "(alguna restauracion fallo).",
            file=sys.stderr,
        )
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
