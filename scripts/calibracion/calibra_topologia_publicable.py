#!/usr/bin/env python3
"""Calibracion de `check_no_topologia_publicable.py` (EXP-1).

Regla del operador: una afirmacion de seguridad no cuenta hasta que hay una
prueba capaz de ponerse roja. Este arnes introduce, DE VERDAD, sobre el
arbol de trabajo real (`viewer/.env.example`), cada caso de la tabla exigida
por el mandato de EXP-1, ejecuta el gate y lee su codigo de retorno real, y
restaura el fichero por EFECTO (bytes identicos, comprobado por hash y por
`git status`).

Tabla fijada por el operador:
  1. Una `10.x.x.x` metida en `viewer/.env.example`      -> ROJO, con causa.
  2. `192.0.2.x` (RFC 5737) en la misma zona              -> VERDE.
  3. Un fixture legitimo con IP privada (fuera de zona)   -> sigue VERDE,
     con control positivo y con prueba anti-vacuidad (el motor SI lo
     reporta cuando se le retira la proteccion).
  4. Ablacion de `EXCLUSIONES` LLAMANDO AL MOTOR REAL     -> sin ellas, el
     mismo fixture SI se reporta (0 -> N). Prueba que la exclusion hace
     trabajo DENTRO del gate, no que un regex case fuera de el.
  5. Excepcion declarada explicita sobre una IP privada   -> VERDE, y sin la
     excepcion (la misma linea sin el marcador) vuelve a ROJO.
  6. Marcador de excepcion SIN motivo                     -> ROJO; el mismo
     marcador CON motivo -> VERDE (control positivo del caso).

Ninguno de los casos reimplementa la deteccion: todos pasan por
`encuentra_violaciones()`. Un motor destripado pone rojos 1, 3, 4, 5 y 6.
Ningun caso transcribe una IP privada real: cuando hace falta afirmar que un
fichero contiene una, se le pregunta al propio `IP_PRIVADA_RE` del gate.

Uso: python3 scripts/calibracion/calibra_topologia_publicable.py
Sale 0 si las seis filas dan el veredicto esperado.
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


def _motor(mod, *, zona=None, exclusiones=None) -> list[tuple[str, int, str]]:
    """Ejecuta `encuentra_violaciones()` -EL MOTOR REAL DEL GATE- con la
    configuracion ablacionada que se le pase.

    Ablacionar configuracion y volver a llamar al motor es lo unico que
    prueba que una exclusion hace trabajo DENTRO del gate. Reimplementar el
    regex aqui fuera probaria que el patron casa, no que el gate lo use: si
    alguien destripa `encuentra_violaciones()`, un arnes asi seguiria verde
    (fue exactamente el defecto de la ronda 1).
    """
    zona_prev, excl_prev = mod.ZONA_PUBLICABLE, mod.EXCLUSIONES
    try:
        if zona is not None:
            mod.ZONA_PUBLICABLE = zona
        if exclusiones is not None:
            mod.EXCLUSIONES = exclusiones
        return mod.encuentra_violaciones()
    finally:
        mod.ZONA_PUBLICABLE, mod.EXCLUSIONES = zona_prev, excl_prev


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
    """Un fixture de `viewer/tests/` con una IP privada real sigue VERDE:
    esta fuera de la zona publicable a proposito (declarado en la cabecera
    del gate). Y el verde NO es vacuo: se comprueba, con el mismo motor, que
    ese fichero SI es alcanzable y detectable cuando se le retira la
    proteccion (si no, un motor destripado daria este verde igual)."""
    if not FIXTURE_LEGITIMO.is_file():
        raise Fallo(f"caso-3: no existe {FIXTURE_LEGITIMO}, elige otro testigo")
    mod = _cargar_gate()
    ruta_relativa = str(FIXTURE_LEGITIMO.relative_to(REPO))
    contenido = FIXTURE_LEGITIMO.read_text(encoding="utf-8", errors="ignore")

    # Control positivo SIN publicar el valor: se le pregunta al propio patron
    # del gate si ahi dentro hay una IP privada, no se escribe cual.
    _verifica(
        "caso-3: el fixture SI contiene una IP privada (control positivo, "
        "via IP_PRIVADA_RE del gate, sin transcribir el valor)",
        mod.IP_PRIVADA_RE.search(contenido) is not None,
        "el fixture elegido ya no es un control positivo valido",
    )

    rc, violaciones = _correr_gate()
    rutas = [v[0] for v in violaciones]
    _verifica(
        "caso-3: el motor real NO reporta el fixture",
        ruta_relativa not in rutas,
        f"violaciones inesperadas: {violaciones}",
    )
    _verifica("caso-3: gate global VERDE", rc == 0, f"rc={rc}, violaciones={violaciones}")

    # Anti-vacuidad: el MISMO motor, con el fixture dentro de zona y sin
    # exclusiones, SI lo reporta. Si `encuentra_violaciones()` estuviera
    # destripado esto daria 0 y el caso 3 se pondria rojo.
    ablacionado = _motor(
        mod,
        zona=mod.ZONA_PUBLICABLE + ("viewer/tests/*",),
        exclusiones=(),
    )
    _verifica(
        "caso-3 (anti-vacuidad): el motor real SI sabe reportar ese fichero "
        "cuando se le quita la proteccion -> el verde de arriba es una "
        "decision del gate, no un motor que no mira nada",
        any(v[0] == ruta_relativa for v in ablacionado),
        "con zona ampliada y exclusiones vacias el motor sigue sin reportar "
        "el fixture: o el motor no ejecuta, o el testigo ya no sirve",
    )


def caso_4_ablacion_exclusion_tests() -> None:
    """Ablacion diferencial POR EL MOTOR REAL: se llama tres veces a
    `encuentra_violaciones()` cambiando solo la configuracion, y se exige que
    la unica variable que mueve el veredicto sea `EXCLUSIONES`.

      (a) zona ampliada + EXCLUSIONES reales -> 0  (la exclusion protege)
      (b) zona ampliada + EXCLUSIONES = ()   -> N>0 (sin ella, salta)
      (c) zona real     + EXCLUSIONES = ()   -> 0  (la zona tampoco lo alcanza)

    (b) frente a (a) es la prueba de que la exclusion hace trabajo dentro del
    gate; (c) descarta que el verde venga solo del patron de zona.
    """
    mod = _cargar_gate()
    ruta_relativa = str(FIXTURE_LEGITIMO.relative_to(REPO))
    zona_ampliada = mod.ZONA_PUBLICABLE + ("viewer/tests/*",)

    def _n(violaciones) -> int:
        return sum(1 for v in violaciones if v[0] == ruta_relativa)

    a = _n(_motor(mod, zona=zona_ampliada))
    b = _n(_motor(mod, zona=zona_ampliada, exclusiones=()))
    c = _n(_motor(mod, exclusiones=()))

    _verifica(
        "caso-4a: con el fixture DENTRO de zona, EXCLUSIONES lo salva "
        "(motor real, 0 violaciones)",
        a == 0,
        f"esperaba 0 violaciones del fixture, obtuve {a}",
    )
    _verifica(
        "caso-4b: con la MISMA zona y EXCLUSIONES=(), el motor real SI lo "
        "reporta -> la exclusion hace trabajo dentro del gate",
        b > 0,
        f"esperaba >0 violaciones del fixture al ablacionar EXCLUSIONES, "
        f"obtuve {b}; si es 0, el motor no esta ejecutando",
    )
    _verifica(
        "caso-4c: sin exclusiones pero con la zona REAL, el fixture sigue "
        "sin reportarse -> el verde no viene solo del patron de zona",
        c == 0,
        f"esperaba 0 con la zona real, obtuve {c}",
    )
    _verifica(
        f"caso-4: el diferencial 0 -> {b} lo produce SOLO quitar EXCLUSIONES",
        a == 0 and b > 0,
        f"a={a}, b={b}, c={c}",
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


def caso_6_marcador_sin_motivo_no_exime() -> None:
    """El marcador de excepcion SIN motivo no exime: la misma IP con
    `# topologia: excepcion declarada` a secas sigue en ROJO, y con un motivo
    escrito pasa a VERDE. Sin este caso, una excepcion muda silencia el gate
    sin dejar razon (medido en la ronda 1: sin motivo, verde)."""
    original = ENV_EXAMPLE.read_bytes()
    hash_antes = _sha256(ENV_EXAMPLE)
    texto = original.decode("utf-8")
    ancla = "S9K_NEO4J_URI=bolt://192.0.2.10:7687"
    if ancla not in texto:
        raise Fallo("caso-6: el ancla a mutar no aparece; el fuente se movio")

    sin_motivo = texto.replace(
        ancla,
        "# topologia: excepcion declarada\n"
        "S9K_NEO4J_URI=bolt://10.7.0.9:7687",
    )
    con_motivo = texto.replace(
        ancla,
        "# topologia: excepcion declarada (calibracion EXP-1, no real)\n"
        "S9K_NEO4J_URI=bolt://10.7.0.9:7687",
    )
    try:
        ENV_EXAMPLE.write_text(sin_motivo, encoding="utf-8")
        rc, violaciones = _correr_gate()
        _verifica(
            "caso-6a: marcador SIN motivo -> sigue ROJO",
            rc == 1 and any(v[0] == "viewer/.env.example" for v in violaciones),
            f"un marcador mudo eximio la linea: rc={rc}, violaciones={violaciones}",
        )
        # Control positivo del propio caso: con motivo, el mismo texto es VERDE.
        ENV_EXAMPLE.write_text(con_motivo, encoding="utf-8")
        rc, violaciones = _correr_gate()
        _verifica(
            "caso-6b (control positivo): el MISMO marcador CON motivo -> VERDE",
            rc == 0 and not any(v[0] == "viewer/.env.example" for v in violaciones),
            f"rc={rc}, violaciones={violaciones}",
        )
    finally:
        ENV_EXAMPLE.write_bytes(original)
        _verifica(
            "caso-6: restauracion por hash",
            _sha256(ENV_EXAMPLE) == hash_antes,
            "el fichero no volvio a su contenido original",
        )


CASOS = [
    caso_1_ip_privada_nueva_se_pone_rojo,
    caso_2_valor_ficticio_da_verde,
    caso_3_fixture_legitimo_sigue_verde,
    caso_4_ablacion_exclusion_tests,
    caso_5_excepcion_declarada,
    caso_6_marcador_sin_motivo_no_exime,
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
