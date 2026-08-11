"""Calibracion por MUTACION del carril J (calidad de datos v2).

Un test verde no es evidencia. La evidencia aparece cuando se sabe QUE
comportamiento se afirma, se introduce la violacion de ese comportamiento, el
sistema se pone ROJO, se revierte y vuelve a VERDE. Un instrumento que nunca se
ha visto rojo no mide nada.

Este fichero existe porque el comprobador de este carril ya estuvo ciego
exactamente donde apuntaba su propio CRITICAL: su docstring advertia de que una
proyeccion parcial apaga una barrera en silencio, y su red inversa solo miraba
`node.get("...")`, de modo que era estructuralmente incapaz de ver una sola
dimension del CONTEXTO sin declarar. Sabia decir la leccion y no sabia aplicarla
a si mismo.

    python3 mutaciones_calidad_datos.py

Cada mutacion revierte siempre lo que toca, aun si pytest falla o se
interrumpe. Los objetivos van acotados a proposito: lo que se mide es que EXISTE
un test concreto que se pone rojo, no que la suite entera se entere.
"""
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
V = RAIZ / "viewer"
D = RAIZ / "data-engine"

CAL = "tests/test_calidad_de_datos_v2.py"
CONTRATO = "tests/test_provider_authz_fields_contract.py"
SPEC = "tests/test_registro_es_especificacion_ejecutable.py"
REGISTRO = "tests/test_registro_de_autorizacion.py"
PRODUCTOR = "tests/test_productor_de_cada_campo_de_autorizacion.py"
SAFE = "app/tests/test_safe_writer.py"
FULL = "app/tests/test_full_human_review.py"

# (etiqueta, fichero, original, mutado, cwd, objetivos)
MUTACIONES = [

    # --- 1. El registro es la fuente: quitar una dimension se PROPAGA y se DETECTA
    ("J1 se BORRA la dimension `known_from_session` del registro ejecutable "
     "(el motor la sigue consultando)",
     V / "app/policies/registry.py",
     '    PolicyField(\n        name="known_from_session",',
     '    PolicyField(\n        name="known_from_session_BORRADA",',
     V, [CONTRATO, CAL]),

    ("J2 se BORRA la dimension de CONTEXTO `max_visible_session` del registro "
     "(el motor la sigue consultando como atributo, no como campo de nodo)",
     V / "app/policies/registry.py",
     '    PolicyField(\n        name="max_visible_session",',
     '    PolicyField(\n        name="max_visible_session_BORRADA",',
     V, [CONTRATO, CAL]),

    ("J3 una dimension proyectada deja de aplicar a RELACIONES "
     "(la barrera se apaga solo para aristas, en verde)",
     V / "app/policies/registry.py",
     '        name="visibility",',
     '        name="visibility",\n        applies_to=frozenset({"node"}),',
     V, [CONTRATO]),

    ("J4 una dimension del DATO deja de viajar en la proyeccion "
     "(H1: el dato existe, se pierde al proyectarlo)",
     V / "app/policies/registry.py",
     '        name="partida_id",',
     '        name="partida_id",\n        in_projection=False,',
     V, [CONTRATO, CAL]),

    ("J5 una dimension del registro afloja su respuesta a la ausencia "
     "(`missing=DENY` -> `NEUTRO`): la ausencia pasaria a ser permiso",
     V / "app/policies/registry.py",
     '        producer="data-engine/app/knowledge_v3/writer/visibility.py (scope_props)",\n'
     '        storage="Neo4j",\n        consumer="policies/engine.py",\n'
     '        missing=DENY,\n        malformed=DENY,\n'
     '        required_for_scopes=frozenset({"partida"}),',
     '        producer="data-engine/app/knowledge_v3/writer/visibility.py (scope_props)",\n'
     '        storage="Neo4j",\n        consumer="policies/engine.py",\n'
     '        missing=NEUTRO,\n        malformed=DENY,\n'
     '        required_for_scopes=frozenset({"partida"}),',
     V, [CAL, SPEC]),

    # --- 2. Ausencia de dato != permiso
    ("J6 el motor deja de denegar un `scope` ausente "
     "(el dato sin ambito declarado se resolveria hacia lo mas abierto)",
     V / "app/policies/engine.py",
     '        if scope not in ALL_SCOPES:\n            return VisibilityDecision(False, "scope_invalid")',
     '        if scope not in ALL_SCOPES:\n            return VisibilityDecision(True, "visible")',
     V, [CAL]),

    # Ojo al puntero: la primera version de esta mutacion apuntaba a
    # `if ws not in ctx.allowed_workspaces:`, que es la regla de PERTENENCIA, no
    # la de dato ausente. Salio VERDE y parecia un comprobador ciego; lo que
    # estaba mal era la mutacion. El guardian fail-closed del workspace ausente
    # es el `isinstance` de la linea anterior, y es el que hay que romper para
    # afirmar que la ausencia no se lee como permiso. Calibrar tambien sirve
    # para descubrir que uno estaba midiendo el sitio equivocado.
    ("J7 el motor deja de denegar un `workspace` ausente o ilegible "
     "(vuelve el `ws is not None` que M5c cerro)",
     V / "app/policies/engine.py",
     '        if not isinstance(ws, str) or not ws.strip():\n'
     '            return VisibilityDecision(False, "workspace_invalid")\n'
     '        if ws not in ctx.allowed_workspaces:\n'
     '            return VisibilityDecision(False, "workspace_not_allowed")',
     '        if ws is not None and ws not in ctx.allowed_workspaces:\n'
     '            return VisibilityDecision(False, "workspace_not_allowed")',
     V, [CAL]),

    ("J8 un tope de sesion ilegible vuelve a significar 'sin tope' "
     "(H-B: el dato ilegible ABRE la barrera)",
     V / "app/policies/engine.py",
     '                if estado_tope == AUSENTE_O_INVALIDO:\n'
     '                    # No se pudo determinar el tope. No conceder.\n'
     '                    return VisibilityDecision(False, "session_cap_missing")',
     '                if estado_tope == AUSENTE_O_INVALIDO:\n'
     '                    return VisibilityDecision(True, "visible")',
     V, [CAL]),

    # --- 3. ReviewStatus: un unico vocabulario canonico
    ("J9 se cuela un QUINTO valor en el vocabulario canonico de review_status",
     RAIZ / "contracts/review-status/v1/model.py",
     '    CORRECTED = "corrected"',
     '    CORRECTED = "corrected"\n    MACHINE_APPROVED = "auto_approved"',
     V, [CAL]),

    ("J10 el vocabulario canonico pierde un valor y las etiquetas del visor "
     "NO se enteran (deriva entre las dos listas)",
     RAIZ / "contracts/review-status/v1/model.py",
     '    CORRECTED = "corrected"',
     '    CORRECTED_RENOMBRADO = "corrected_renombrado"',
     V, [CAL]),

    ("J11 `normalize` acepta un valor fuera del vocabulario en vez de levantar "
     "(default permisivo)",
     RAIZ / "contracts/review-status/v1/model.py",
     '    if value not in CANONICAL_VALUES:\n        raise ReviewStatusError(',
     '    if False:\n        raise ReviewStatusError(',
     V, [CAL]),

    ("J12 el adaptador del pipeline convierte lo automatico en 'revisado' "
     "(inventa una revision humana que no ocurrio)",
     RAIZ / "contracts/review-status/v1/model.py",
     '    "auto_approve": ReviewStatus.AUTO_EXTRACTED,',
     '    "auto_approve": ReviewStatus.REVIEWED,',
     V, [CAL]),

    ("J13 el adaptador de candidatos deja de ser TOTAL sobre el contrato "
     "review-ingest/v1",
     RAIZ / "contracts/review-status/v1/model.py",
     '    "DEFERRED": ReviewStatus.NEEDS_REVIEW,\n',
     '',
     V, [CAL]),

    ("J14 la frontera de escritura deja de adaptar y escribe el idioma ajeno "
     "('approved') en el grafo",
     D / "app/review/ingest_approved.py",
     '        "review_status": review_status_contract.from_review_manual_status(\n'
     '            item["review_status"]\n        ).value,',
     '        "review_status": item["review_status"],',
     D, [SAFE]),

    ("J15b la via humana deja de exigir pertenencia al conjunto permitido "
     "(la prueba que esta calibracion obligo a escribir)",
     D / "app/review/ingest_approved.py",
     '        if canonico.value not in review_status_contract.HUMAN_REVIEWED:',
     '        if False:',
     V, [CAL]),
]

#: SUPERVIVIENTES DOCUMENTADOS. Mutaciones que se sabe que NO ponen roja a la
#: suite indicada, con el motivo. No se ocultan: se declaran, porque un
#: superviviente sin explicacion es un agujero y un superviviente explicado es
#: un limite conocido del instrumento.
SUPERVIVIENTES = [
    ("J15 la misma mutacion que J15b, mirada desde la suite de data-engine",
     D / "app/review/ingest_approved.py",
     '        if canonico.value not in review_status_contract.HUMAN_REVIEWED:',
     '        if False:',
     D, [SAFE, FULL],
     "La suite de data-engine solo ejercita `approved` (valido) y "
     "`auto_approved` (atrapado por la rama anterior). Ningun test de "
     "data-engine hace llegar `pending`/`deferred`/`rejected` a "
     "_validate_write_provenance, asi que alli la comprobacion no la mide "
     "nadie. La cobertura real esta en J15b (viewer/tests/"
     "test_calidad_de_datos_v2.py). Se deja declarado porque describe una "
     "carencia de la suite de data-engine, no del guardian."),
]


def _pytest(cwd, objetivos):
    return subprocess.run(
        [sys.executable, "-m", "pytest", *objetivos, "-q", "--no-header", "-x"],
        cwd=cwd, capture_output=True, text=True,
    )


def main() -> int:
    print("=" * 78)
    print("CALIBRACION DEL CARRIL J -- cada afirmacion debe poder ponerse ROJA")
    print("=" * 78)

    base = {}
    for _, _, _, _, cwd, objetivos in MUTACIONES + [m[:6] for m in SUPERVIVIENTES]:
        clave = (str(cwd), tuple(objetivos))
        if clave not in base:
            r = _pytest(cwd, objetivos)
            base[clave] = r.returncode
            if r.returncode != 0:
                print(f"\n!! LINEA BASE YA ROJA para {objetivos} en {cwd.name}")
                print(r.stdout[-3000:])
                return 2
    print(f"\nLinea base VERDE en {len(base)} combinaciones de objetivos.\n")

    fallos = []
    for etiqueta, fichero, original, mutado, cwd, objetivos in MUTACIONES:
        texto = fichero.read_text(encoding="utf-8")
        if original not in texto:
            print(f"[SALTADA] {etiqueta}\n           patron no encontrado en {fichero}")
            fallos.append(etiqueta + "  (patron no encontrado)")
            continue
        if texto.count(original) != 1:
            print(f"[SALTADA] {etiqueta}\n           patron ambiguo ({texto.count(original)}x)")
            fallos.append(etiqueta + "  (patron ambiguo)")
            continue

        fichero.write_text(texto.replace(original, mutado, 1), encoding="utf-8")
        try:
            r = _pytest(cwd, objetivos)
        finally:
            fichero.write_text(texto, encoding="utf-8")

        rojo = r.returncode != 0
        print(f"[{'ROJO  ' if rojo else 'VERDE!'}] {etiqueta}")
        if rojo:
            linea = [ln for ln in r.stdout.splitlines() if "FAILED" in ln or " Error" in ln]
            for ln in linea[:2]:
                print(f"           {ln.strip()[:150]}")
            if not linea:
                print(f"           {r.stdout.strip().splitlines()[-1][:150]}")
        else:
            fallos.append(etiqueta)
            print("           NO SE PUSO ROJO: esta afirmacion no esta medida.")

        # Verificacion de reversion: verde otra vez.
        r2 = _pytest(cwd, objetivos)
        if r2.returncode != 0:
            print("           !! NO VUELVE A VERDE tras revertir")
            fallos.append(etiqueta + "  (no revierte)")

    print("\n" + "-" * 78)
    print("SUPERVIVIENTES DECLARADOS (se comprueba que siguen siendo verdes por")
    print("el motivo documentado; si uno se pone rojo, la explicacion caduco)")
    print("-" * 78)
    for etiqueta, fichero, original, mutado, cwd, objetivos, motivo in SUPERVIVIENTES:
        texto = fichero.read_text(encoding="utf-8")
        assert texto.count(original) == 1, f"patron ambiguo/ausente en {fichero}"
        fichero.write_text(texto.replace(original, mutado, 1), encoding="utf-8")
        try:
            r = _pytest(cwd, objetivos)
        finally:
            fichero.write_text(texto, encoding="utf-8")
        estado = "ROJO (la explicacion ya no vale)" if r.returncode else "VERDE, como se documenta"
        print(f"[{estado}] {etiqueta}\n           motivo: {motivo}")

    print("\n" + "=" * 78)
    if fallos:
        print(f"CALIBRACION INCOMPLETA: {len(fallos)} de {len(MUTACIONES)} sin medir")
        for f in fallos:
            print(f"  - {f}")
        return 1
    print(f"CALIBRACION COMPLETA: {len(MUTACIONES)}/{len(MUTACIONES)} rojo -> revert -> verde")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
