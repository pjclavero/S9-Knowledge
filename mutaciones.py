"""Prueba por MUTACION de la 7a ronda de M5b-C.

Por cada hallazgo del sexto dictamen, reintroduce el defecto y comprueba que hay
un test ROJO concreto donde antes habia verde. Revierte siempre lo que toca, aun
si pytest falla o se interrumpe.

    python3 mutaciones.py

Los objetivos van ACOTADOS a proposito: correr la suite entera arrastraba un
fallo preexistente y dependiente del orden (`test_auth_core.py::
test_login_unknown_user_generic_message`, un 403 del limitador de intentos) que
ensuciaba la lectura sin tener nada que ver con la mutacion.
"""
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
V = RAIZ / "viewer"
D = RAIZ / "data-engine"

SPEC = "tests/test_registro_es_especificacion_ejecutable.py"
E2E7 = "tests/test_autorizacion_e2e_http_septima_ronda.py"
T1 = "tests/test_t1_party_t2_revelacion.py"
DEP = "tests/test_dependencias_fail_closed.py"
PANEL = "tests/test_admin_panel_concesiones.py"
CYPHER = "tests/test_acotado_por_workspace_en_cypher.py"
RESERV = "app/tests/test_props_reservadas_de_autorizacion.py"

# (etiqueta, fichero, original, mutado, cwd, objetivos)
MUTACIONES = [
    ("H6-1 el motor vuelve a dejar pasar la ausencia de known_from_session "
     "(el REGISTRO sigue declarando missing=DENY)",
     V / "app/policies/engine.py",
     'if scope == SCOPE_PARTIDA and desde is None:\n            return VisibilityDecision(False, "known_from_session_missing")',
     'if False:\n            return VisibilityDecision(False, "known_from_session_missing")',
     V, [SPEC, T1, E2E7]),
    ("H6-1bis un tope ilegible vuelve a no aplicar la barrera",
     V / "app/policies/engine.py",
     '                if estado_tope == AUSENTE_O_INVALIDO:\n                    # No se pudo determinar el tope. No conceder.\n                    return VisibilityDecision(False, "session_cap_missing")',
     '                if estado_tope == AUSENTE_O_INVALIDO:\n                    return VisibilityDecision(True, "visible")',
     V, [SPEC, T1]),
    ("H6-2 un partida_id en blanco vuelve a degradarse a lore compartido",
     V / "app/policies/engine.py",
     '            if not isinstance(pid, str) or not pid.strip():\n                return VisibilityDecision(False, "partida_id_blank")',
     '            if not isinstance(pid, str) or not pid.strip():\n                return VisibilityDecision(True, "visible")',
     V, [SPEC, E2E7]),
    ("H6-3 known_by_characters sale del guardado reservado del writer",
     D / "app/knowledge_v3/writer/cypher.py",
     '        "known_by_characters",\n        "known_from_session",',
     '        "known_from_session",',
     D, [RESERV]),
    ("H6-4 known_from_session sale del guardado reservado del writer",
     D / "app/knowledge_v3/writer/cypher.py",
     '        "known_by_characters",\n        "known_from_session",',
     '        "known_by_characters",',
     D, [RESERV]),
    ("H6-5 active_character deja de poblarse en dependencies.py",
     V / "app/authz/dependencies.py",
     "            return auth_db.partida_progress(conn, user.id, workspace, partida_id)",
     "            return auth_db.partida_progress(conn, user.id, workspace, partida_id)[0], None",
     V, [E2E7]),
    ("H6-6 _progresion_de_campana deja de ser fail-closed sin usuario",
     V / "app/authz/dependencies.py",
     '    if user is None or getattr(user, "id", None) is None:\n        return 0, None',
     '    if user is None or getattr(user, "id", None) is None:\n        return None, None',
     V, [DEP]),
    ("H6-7 _still_has_access deja de ser fail-closed sin workspace",
     V / "app/authz/dependencies.py",
     "        # Fail-closed: sin workspace efectivo determinable, no se concede acceso.\n        return False",
     "        return True",
     V, [DEP]),
    ("H6-8 el panel ignora el tope tecleado y concede 9999",
     V / "app/routers/admin.py",
     "        tope = int(tope)",
     "        tope = 9999",
     V, [PANEL]),
    ("H6-9 sin partida activa se vuelve a devolver None (= sin tope)",
     V / "app/authz/dependencies.py",
     "        return NO_APLICA, None",
     "        return None, None",
     V, [E2E7, DEP]),
    ("H6-10 el formulario vuelve a prometer 'vacio = sin tope'",
     V / "app/templates/auth/admin/partidas.html",
     'placeholder="vacío = 0 (nada revelado)"',
     'placeholder="vacío = sin tope"',
     V, [PANEL]),
    ("H6-11 el acceso por ID deja de acotar el workspace en el Cypher",
     V / "app/providers/neo4j_provider.py",
     '                "AND n.workspace IN $workspaces RETURN n"',
     '                "RETURN n"',
     V, [CYPHER]),
    ("REGISTRO: se borra la prueba HTTP declarada de active_character",
     V / "app/policies/registry.py",
     '            "tests/test_autorizacion_e2e_http_septima_ronda.py::test_la_concesion_de_personaje_abre_su_secreto_por_HTTP"',
     '            "tests/test_autorizacion_e2e_http_septima_ronda.py::test_que_no_existe"',
     V, [SPEC]),
]


def main() -> int:
    verdes = []
    for etiqueta, fichero, viejo, nuevo, cwd, objetivos in MUTACIONES:
        texto = fichero.read_text(encoding="utf-8")
        if viejo not in texto:
            print(f"### {etiqueta}\n    -> NO SE PUDO MUTAR (patron no encontrado)")
            verdes.append(etiqueta)
            continue
        fichero.write_text(texto.replace(viejo, nuevo, 1), encoding="utf-8")
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "--no-header", "-p",
                 "no:randomly", *objetivos],
                cwd=cwd, capture_output=True, text=True)
        finally:
            fichero.write_text(texto, encoding="utf-8")
        rojos = [ln for ln in r.stdout.splitlines() if "FAILED" in ln]
        estado = "ROJO" if r.returncode else "VERDE (!!)"
        if r.returncode == 0:
            verdes.append(etiqueta)
        print(f"\n### {etiqueta}\n    -> {estado}  ({len(rojos)} rojos)")
        for ln in rojos[:5]:
            limpio = (ln.replace("\x1b[31m", "").replace("\x1b[0m", "")
                        .replace("\x1b[1m", "").strip())
            print("      " + limpio[:150])

    if verdes:
        print("\nMUTACIONES NO DETECTADAS:\n  " + "\n  ".join(verdes))
        return 1
    print("\nTodas las mutaciones producen al menos un test rojo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
