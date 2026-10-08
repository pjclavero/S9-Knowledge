#!/usr/bin/env python3
"""CALIBRACIÓN — PR-2 USABLE-V1: «proveedor no configurado -> estado vacío».

Mismo motor que `mutaciones_corte6b2_editar_labels.py`: cada mutación
reintroduce UN defecto real sobre el código del árbol COMMITEADO, corre el
testigo (`viewer/tests/test_proveedor_no_configurado.py`), y comprueba que
(1) cae ROJO, (2) con el mensaje que nombra la causa, y luego restaura y
comprueba la restauración por EFECTO (árbol tracked limpio y testigo verde
otra vez).

Cubre CINCO formas de romper la propiedad. Las tres últimas se añadieron
porque la revisión del PR las probó a mano y enrojecían con los testigos
existentes SIN estar declaradas: un arnés que da 2/2 CALIBRADA mientras
≥5 propiedades están en juego mide menos de lo que dice.

  M1 — el fallback vuelve a ser `mock` tanto cuando no hay declaración como
       cuando el valor es una errata de tecleo: la falsa confirmación
       original (11 entidades inventadas en una instalación de fábrica) y su
       variante por fail-open ante un valor desconocido.
  M2 — la marca DEMO deja de pintarse: el modo de demostración vuelve a ser
       indistinguible de datos reales.
  M3 — LA AUTORIDAD. `classify_provider_declaration` vuelve a leer de
       `settings.S9K_GRAPH_PROVIDER` en vez de `effective_env_value`. Es la
       mutación más importante del arnés: ese atributo SIEMPRE trae una
       cadena (el default de pydantic), no puede distinguir "no declarado"
       de "declarado = mock", y reintroduce TODA la clase de defecto de
       golpe.
  M4 — `NotConfiguredGraphProvider.list_entities` LANZA en vez de devolver
       vacío. El proveedor no configurado existe para garantizar vacío, NO
       excepción: una instalación sin configurar no está rota, está sin
       configurar.
  M5 — el aviso declara `configurado = False` siempre: el cartel de "no
       configurada" se pinta encima de una instalación que SÍ está sirviendo
       datos (reales o DEMO). Es la falsa confirmación simétrica.

Cada mutación exige un fragmento DISCRIMINANTE en la salida —el texto del
`assert` que nombra la causa—, no un `AssertionError` genérico: un rojo por
la razón equivocada se lee igual que uno legítimo.

Uso: python3 scripts/calibracion/mutaciones_proveedor_no_configurado.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localizadores import mutar_en_funcion, mutar_unico  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
TESTIGO = "viewer/tests/test_proveedor_no_configurado.py"


def _arbol_limpio_tracked() -> bool:
    r = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                        cwd=RAIZ, capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == ""


def _purgar_pycache() -> None:
    for d in RAIZ.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def _correr_testigo() -> tuple[int, str]:
    _purgar_pycache()
    r = subprocess.run(
        [sys.executable, "-m", "pytest", TESTIGO, "-q", "--no-header",
         "--color=no", "-p", "no:randomly"],
        cwd=RAIZ, capture_output=True, text=True,
    )
    return r.returncode, r.stdout + r.stderr


def _fallos(salida: str) -> list[str]:
    return sorted({
        linea.split("::")[-1].split(" ")[0]
        for linea in salida.splitlines()
        if linea.startswith("FAILED") or "FAILED " in linea
    })


def _cubre(esperadas: list[str], fallos: list[str]) -> bool:
    rojos = set(fallos)
    base_de_rojos = {f.split("[")[0] for f in fallos}
    for esperada in esperadas:
        if "[" in esperada:
            if esperada not in rojos:
                return False
        elif esperada not in base_de_rojos:
            return False
    return True


MUTACIONES = [
    (
        "M1 — el fallback sin declarar vuelve a ser mock",
        "viewer/app/providers/__init__.py",
        lambda texto: mutar_en_funcion(
            texto,
            "classify_provider_declaration",
            "    return PROVIDER_NOT_CONFIGURED",
            "    return PROVIDER_MOCK_DEMO",
        ),
        None,
        [
            "test_sin_declarar_clasifica_como_no_configurado",
            "test_valor_desconocido_tambien_es_no_configurado",
            "test_build_provider_sin_declarar_no_es_mock",
            "test_sin_proveedor_ninguna_entidad_inventada[/entities]",
            "test_api_entities_sin_proveedor_no_trae_entidades",
            "test_api_sources_sin_proveedor_no_trae_fuentes",
            "test_sin_proveedor_api_status_dice_la_causa",
            "test_sin_proveedor_mensaje_honesto_sin_nombrar_variables_s9k",
            "test_sin_proveedor_no_se_marca_como_demo",
        ],
        "caer en mock es la falsa confirmación original",
    ),
    (
        "M2 — la marca DEMO deja de pintarse en la pantalla",
        "viewer/app/provider_banner.py",
        '        "demo": estado == PROVIDER_MOCK_DEMO,',
        '        "demo": False,',
        [
            "test_demo_explicito_se_marca_en_la_pantalla",
            "test_demo_explicito_admin_ve_la_muestra_marcada_demo",
        ],
        "el modo DEMO debe marcarse en la propia pantalla",
    ),
    (
        "M3 — LA AUTORIDAD pasa a settings.S9K_GRAPH_PROVIDER",
        "viewer/app/providers/__init__.py",
        lambda texto: mutar_en_funcion(
            texto,
            "classify_provider_declaration",
            '        raw = effective_env_value("S9K_GRAPH_PROVIDER")',
            "        from app.config import get_settings\n"
            "        raw = get_settings().S9K_GRAPH_PROVIDER",
        ),
        None,
        [
            "test_sin_declarar_clasifica_como_no_configurado",
            "test_la_autoridad_de_la_declaracion_es_la_efectiva_no_el_default_de_settings",
            "test_build_provider_sin_declarar_no_es_mock",
            "test_api_entities_sin_proveedor_no_trae_entidades",
            "test_sin_proveedor_api_status_dice_la_causa",
        ],
        "la autoridad debe ser la declaración EFECTIVA",
    ),
    (
        "M4 — list_entities LANZA en vez de devolver vacío",
        "viewer/app/providers/not_configured_provider.py",
        lambda texto: mutar_en_funcion(
            texto,
            "list_entities",
            "        return [], 0",
            '        raise RuntimeError("proveedor no configurado")',
        ),
        None,
        [
            "test_los_13_metodos_del_contrato_no_lanzan_y_devuelven_vacio",
        ],
        "NINGUN METODO DEL CONTRATO PUEDE LANZAR",
    ),
    (
        "M5 — el aviso declara `configurado` False siempre",
        "viewer/app/provider_banner.py",
        '        "configurado": estado != PROVIDER_NOT_CONFIGURED,',
        '        "configurado": False,',
        [
            "test_neo4j_no_configurado_no_se_marca_ni_como_demo_ni_como_no_configurado",
        ],
        "ningún cartel cuando no hace falta ninguno",
    ),
]


def main() -> int:
    if not _arbol_limpio_tracked():
        print("ABORTA: el árbol tracked no está limpio. Commitea antes de "
              "calibrar — el checkout del arnés borra lo no commiteado.")
        return 2

    rc, salida = _correr_testigo()
    if rc != 0:
        print(f"ABORTA: el testigo no está verde en la base (PYTEST_RC={rc})")
        print(salida[-3000:])
        return 2
    print(f"BASE: testigo verde, PYTEST_RC={rc}\n")

    veredictos = []
    for nombre, rel, viejo, nuevo, esperadas, fragmento in MUTACIONES:
        f = RAIZ / rel
        original = f.read_text(encoding="utf-8")

        if callable(viejo):
            mutado = viejo(original)
            motivo_estructural = (
                "el localizador estructural no pudo acotar el sitio "
                "(función ausente, duplicada, o ancla no única dentro de ella)"
            )
        else:
            mutado = mutar_unico(original, viejo, nuevo)
            motivo_estructural = None

        if mutado is None:
            if motivo_estructural is not None:
                motivo = motivo_estructural
            else:
                veces = original.count(viejo)
                motivo = ("el texto a mutar no está" if veces == 0 else
                          f"el ancla aparece {veces} veces (AMBIGUA: no identifica un sitio)")
            print(f"### {nombre}\n  DETECTOR ROTO: {motivo} en {rel}. "
                  f"La mutación no se aplicó: un verde aquí sería FALSO.\n")
            veredictos.append((nombre, "DETECTOR ROTO"))
            continue

        f.write_text(mutado, encoding="utf-8")
        rc_mut, salida_mut = _correr_testigo()
        fallos = _fallos(salida_mut)
        mensaje_ok = fragmento in salida_mut

        f.write_text(original, encoding="utf-8")
        _purgar_pycache()
        limpio = _arbol_limpio_tracked()
        rc_post, _ = _correr_testigo()

        print(f"### {nombre}")
        print(f"  fichero            : {rel}")
        print(f"  PYTEST_RC mutado   : {rc_mut}  (esperado != 0)")
        print(f"  pruebas en rojo    : {fallos}")
        print(f"  esperadas          : {sorted(esperadas)}")
        print(f"  MENSAJE contiene   : {fragmento!r} -> {mensaje_ok}")
        print(f"  restaurado (tracked limpio): {limpio}")
        print(f"  restaurado (PYTEST_RC post): {rc_post}  (esperado 0)")

        ok = (
            rc_mut != 0
            and _cubre(esperadas, fallos)
            and mensaje_ok
            and limpio
            and rc_post == 0
        )
        print(f"  VEREDICTO          : {'CALIBRADA' if ok else 'NO CALIBRADA'}\n")
        veredictos.append((nombre, "CALIBRADA" if ok else "NO CALIBRADA"))

    print("=" * 70)
    for nombre, v in veredictos:
        print(f"  {v:<14} {nombre}")
    return 0 if all(v == "CALIBRADA" for _, v in veredictos) else 1


if __name__ == "__main__":
    sys.exit(main())
