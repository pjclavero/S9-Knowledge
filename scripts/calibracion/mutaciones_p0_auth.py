"""Calibracion por MUTACION de la autoridad unica sobre `admin_full` (P0-AUTH).

    python3 scripts/calibracion/mutaciones_p0_auth.py

Cada mutacion reintroduce un defecto REAL y se mide DOS VECES, porque un test
verde no es evidencia de nada por si solo:

  ABLACION (necesidad)  se corre la suite SIN los controles de este carril. Se
                        espera VERDE: es el falso negativo, la demostracion de
                        que nadie mas veia el defecto. Si sale ROJO, el control
                        NO es necesario y no puede cobrarse como defensa; el
                        arnes lo dice con esas palabras.
  COMPLETO (suficiencia) se corre la suite entera. Se espera ROJO, con el
                        nombre de los tests que se ponen rojos.

Y despues se revierte siempre --tambien si pytest revienta o se interrumpe-- y
se comprueba que el arbol vuelve a estar verde.

Un arnes que pasa con 0 casos esta roto: aqui se exige que pytest haya
RECOGIDO tests (`collected N`) en las dos fases, y una fase que no recoja nada
se declara ERROR, no exito. Igualmente, una mutacion cuyo patron no aparezca en
el fichero se declara ERROR: "no se pudo mutar" no es "no hay defecto".
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
V = RAIZ / "viewer"

CONTRATO = "tests/test_provider_authz_fields_contract.py"
REGISTRO = "tests/test_registro_de_autorizacion.py"
SPEC = "tests/test_registro_es_especificacion_ejecutable.py"
P0 = "tests/test_p0_autoridad_admin_full.py"
P0HTTP = "tests/test_p0_autoridad_admin_full_http.py"
CALIDAD = "tests/test_calidad_de_datos_v2.py"
API = "tests/test_api.py"

#: OJO: `--ignore` es relativo al cwd (`viewer/`), pero `--deselect` toma el
#: nodeid relativo al ROOTDIR (la raiz del repo, que es donde esta pytest.ini).
#: La primera version de este arnes uso `tests/...` para los dos y pytest
#: IGNORO EN SILENCIO los `--deselect`: la fase de ablacion de M2, M3 y M8 corria
#: con el control puesto y salia roja, y yo lo estaba leyendo como "el defecto lo
#: ve tambien otro control". Un instrumento desconectado que no se queja es
#: exactamente el defecto que este carril persigue, cometido por el arnes que lo
#: persigue. Ahora hay ademas una comprobacion mecanica: si la ablacion no
#: recoge MENOS tests que la corrida completa, no ha quitado nada y se declara
#: ERROR.
_R = "viewer/"
VIA_LATERAL = _R + CALIDAD + "::test_la_segunda_via_al_bypass_total_tiene_testigo"
ACOTADO = _R + CALIDAD + "::test_el_acotado_por_workspace_de_la_consulta_solo_se_levanta_para_admin_full"
BUSQUEDA = _R + API + "::test_api_search_sin_autenticacion_no_entrega_material_de_referencia"

# Red inversa: la que declara que ninguna dimension decide sin cadena.
RED_INVERSA = {"ignorar": [CONTRATO, REGISTRO, SPEC], "deseleccionar": []}
CADENA_HTTP = {"ignorar": [P0, P0HTTP], "deseleccionar": []}


def _mut(fichero, viejo, nuevo):
    return (V / fichero, viejo, nuevo)


MUTACIONES = [
    (
        "M1 se BORRA `admin_full` del registro (el motor la sigue consumiendo)",
        [_mut("app/policies/registry.py", 'name="admin_full",', 'name="admin_full_retirada",')],
        RED_INVERSA,
    ),
    (
        "M2 vuelve la via lateral `role == 'admin'` en authz/scope.py",
        [_mut("app/authz/scope.py",
              "        return bool(self.ctx.admin_full)\n",
              '        return bool(self.ctx.admin_full) or self.ctx.role == "admin"\n')],
        {"ignorar": [], "deseleccionar": [VIA_LATERAL]},
    ),
    (
        "M3 vuelve `S9K_AUTH_ENABLED=false` => admin_full=True",
        [_mut("app/authz/context.py",
              "    if not auth_enabled and not simulated:\n        role = \"anonymous\"\n",
              "    if not auth_enabled and not simulated:\n"
              "        return ViewerContext(role=\"public\", allowed_workspaces=workspaces,\n"
              "                             admin_full=True, session_public=True)\n")],
        {"ignorar": [P0, P0HTTP], "deseleccionar": [BUSQUEDA]},
    ),
    (
        "M4 se quita la REVOCACION: el rol se cachea y no se relee de auth.db",
        [_mut("app/authz/dependencies.py",
              '    role = getattr(user, "role", None) if user is not None else None\n',
              '    role = (globals().setdefault("_ROL_CACHE", {}).setdefault(\n'
              '        getattr(user, "id", None), getattr(user, "role", None))\n'
              '        if user is not None else None)\n')],
        CADENA_HTTP,
    ),
    (
        "M5 `admin_full` supera un `deny` (el bypass pasa por delante del terminal)",
        [_mut("app/policies/engine.py",
              '        if level == DENY:\n',
              '        if level == DENY and not ctx.admin_full:\n')],
        CADENA_HTTP,
    ),
    (
        "M6 dimension NUEVA no registrada, con su nombre en la cuarentena en el mismo commit",
        [
            _mut("app/policies/models.py",
                 "    simulated: bool = False\n",
                 "    simulated: bool = False\n    puerta_trasera: bool = False\n"),
            _mut("app/policies/engine.py",
                 "        # 1. Bypass total de administrador.\n        if ctx.admin_full:\n",
                 "        # 1. Bypass total de administrador.\n"
                 "        if ctx.puerta_trasera:\n            return _ALLOW\n"
                 "        if ctx.admin_full:\n"),
            # El movimiento que ANTES dejaba la suite verde: apuntar el nombre
            # en la lista de exentas del propio fichero de la red inversa.
            _mut("tests/test_provider_authz_fields_contract.py",
                 "def test_ninguna_dimension_del_contexto_que_el_motor_consulta_queda_sin_declarar_AST():",
                 "CONTEXTO_SIN_DECLARAR_EN_EL_REGISTRO = frozenset({\"puerta_trasera\"})\n\n\n"
                 "def test_ninguna_dimension_del_contexto_que_el_motor_consulta_queda_sin_declarar_AST():"),
        ],
        RED_INVERSA,
    ),
    (
        "M7 se fabrica un ViewerContext a mano, esquivando el productor",
        [_mut("app/authz/scope.py",
              "UNRESTRICTED = VisibilityScope(\n"
              "    build_internal_context(motivo=\"llamador interno sin usuario (CLI/servicios)\")\n"
              ")",
              "UNRESTRICTED = VisibilityScope(ViewerContext(role=\"admin\", admin_full=True))")],
        {"ignorar": [P0], "deseleccionar": []},
    ),
    (
        "M8 `_scope_workspaces()` ABIERTO: la consulta deja de acotarse para todos "
        "(superviviente medido del carril J)",
        [_mut("app/authz/filtered_provider.py",
              "        if self._ctx.admin_full:\n            return None\n        return self._ctx.allowed_workspaces\n",
              "        if True:\n            return None\n        return self._ctx.allowed_workspaces\n")],
        {"ignorar": [], "deseleccionar": [ACOTADO]},
    ),
    (
        "M9 bypass por ALIAS LOCAL (`_c = ctx; if _c.puerta_trasera: return _ALLOW`)",
        [
            _mut("app/policies/models.py",
                 "    simulated: bool = False\n",
                 "    simulated: bool = False\n    puerta_trasera: bool = False\n"),
            _mut("app/policies/engine.py",
                 "        # 1. Bypass total de administrador.\n        if ctx.admin_full:\n",
                 "        # 1. Bypass total de administrador.\n"
                 "        _c = ctx\n        if _c.puerta_trasera:\n            return _ALLOW\n"
                 "        if ctx.admin_full:\n"),
        ],
        RED_INVERSA,
    ),
]


def _corre(ignorar=(), deseleccionar=()):
    """Corre la suite del visor. Devuelve (returncode, recogidos, rojos)."""
    cmd = [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:randomly", "tests"]
    for f in ignorar:
        cmd += ["--ignore", f]
    for t in deseleccionar:
        cmd += ["--deselect", t]
    r = subprocess.run(cmd, cwd=V, capture_output=True, text=True)
    # Sin esto, `ln.startswith("FAILED")` no casaba NUNCA --pytest colorea la
    # linea-- y el arnes informaba "0 rojos" en todas las mutaciones, incluidas
    # las que estaban rojas. Un arnes que no sabe decir QUE se ha puesto rojo no
    # entrega evidencia, entrega un semaforo.
    salida = re.sub(r"\x1b\[[0-9;]*m", "", r.stdout + r.stderr)
    # Del ULTIMO resumen, no de la suma de todas las apariciones (la cuenta
    # aparece tambien en la linea de progreso y se contaba dos veces).
    pas = re.findall(r"(\d+) passed", salida)
    fal = re.findall(r"(\d+) failed", salida)
    recogidos = (int(pas[-1]) if pas else 0) + (int(fal[-1]) if fal else 0)
    rojos = sorted({
        ln.strip().split(" - ")[0].replace("FAILED ", "")
        for ln in salida.splitlines() if ln.strip().startswith("FAILED")
    })
    return r.returncode, recogidos, rojos


def main() -> int:
    problemas: list[str] = []

    print("== estado de partida ==")
    rc, n, _ = _corre()
    print(f"   suite del visor: {'VERDE' if rc == 0 else 'ROJA'} ({n} tests)")
    if rc != 0:
        print("   el arbol no esta verde: no se puede calibrar nada sobre el")
        return 1

    for etiqueta, edits, ablacion in MUTACIONES:
        print(f"\n### {etiqueta}")
        originales = {}
        aplicables = True
        for fichero, viejo, _ in edits:
            texto = fichero.read_text(encoding="utf-8")
            originales.setdefault(fichero, texto)
            if viejo not in texto:
                print(f"    ERROR: patron no encontrado en {fichero.name}")
                aplicables = False
        if not aplicables:
            problemas.append(f"{etiqueta}: NO SE PUDO MUTAR")
            continue

        try:
            for fichero, viejo, nuevo in edits:
                t = fichero.read_text(encoding="utf-8")
                fichero.write_text(t.replace(viejo, nuevo, 1), encoding="utf-8")

            rc_a, n_a, rojos_a = _corre(ablacion["ignorar"], ablacion["deseleccionar"])
            rc_c, n_c, rojos_c = _corre()
        finally:
            for fichero, texto in originales.items():
                fichero.write_text(texto, encoding="utf-8")

        if n_a == 0 or n_c == 0:
            problemas.append(f"{etiqueta}: una fase recogio 0 tests (arnes roto)")
            print(f"    ERROR: 0 tests recogidos (ablacion={n_a}, completo={n_c})")
            continue
        # El instrumento tiene que MORDER: si la ablacion no ha quitado ni un
        # test, no ha ablacionado nada y su VERDE/ROJO no significa nada.
        if n_a >= n_c:
            problemas.append(
                f"{etiqueta}: la ablacion no quito ningun test "
                f"({n_a} >= {n_c}): el --ignore/--deselect no ha mordido"
            )
            print(f"    ERROR: ablacion no efectiva ({n_a} >= {n_c} tests)")
            continue

        estado_a = "VERDE" if rc_a == 0 else "ROJO"
        estado_c = "ROJO" if rc_c else "VERDE"
        print(f"    ablacion  (sin los controles de este carril): {estado_a}  "
              f"({n_a} tests, {len(rojos_a)} rojos)")
        print(f"    completo  (con los controles):                {estado_c}  "
              f"({n_c} tests, {len(rojos_c)} rojos)")
        for ln in rojos_c[:8]:
            print("        rojo: " + ln[:140])

        if rc_c == 0:
            problemas.append(f"{etiqueta}: SUPERVIVIENTE (la suite completa sigue verde)")
        if rc_a != 0:
            print("        NOTA: la ablacion tambien esta roja -> el defecto lo "
                  "detecta ademas otro control preexistente; el de este carril "
                  "no puede cobrarse como la UNICA defensa.")
            for ln in rojos_a[:6]:
                print("        (ablacion) " + ln[:130])

    print("\n== estado tras revertir ==")
    rc, n, rojos = _corre()
    print(f"   suite del visor: {'VERDE' if rc == 0 else 'ROJA'} ({n} tests)")
    if rc != 0:
        problemas.append(f"el arbol NO vuelve a verde tras revertir: {rojos[:5]}")

    if problemas:
        print("\nPROBLEMAS:\n  " + "\n  ".join(problemas))
        return 1
    print("\nLas 9 mutaciones producen ROJO con los controles, y VERDE sin ellos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
