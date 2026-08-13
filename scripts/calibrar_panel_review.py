#!/usr/bin/env python3
"""Calibración del hueco C (Review Console): ¿puede ponerse ROJA cada garantía?

MOTIVO
------
Un verde no es evidencia. Una comprobación que no puede fallar es decorativa, y
en este repo ya se ha cobrado más de una como defensa. Este guion introduce una
MUTACIÓN EFÍMERA por garantía —el defecto que la garantía dice impedir—, ejecuta
los tests que deberían cazarla y exige que se pongan rojos POR EL MOTIVO
DECLARADO, no por cualquier motivo.

MÉTODO
------
Para cada caso: se mide el sha256 del fichero, se aplica la sustitución, se
ejecuta el subconjunto de tests, se restaura el fichero y se vuelve a medir el
sha256. Si el hash de vuelta no es idéntico al de ida, el caso se declara
INVÁLIDO: una medición sobre un árbol que no volvió a su sitio no vale nada.

Además de cada mutación, se comprueba el DIFERENCIAL: los mismos tests tienen
que estar VERDES sobre el árbol sin mutar. Un rojo permanente (por entorno,
por una fixture rota) no demuestra que la comprobación muerda.

USO
---
    python3 scripts/calibrar_panel_review.py

Salida: una tabla por caso con VERDE base / ROJO mutado / reversión idéntica, y
código de salida 1 si algún caso no se pudo poner rojo.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
VIEWER = RAIZ / "viewer"
ROUTER = VIEWER / "app" / "routers" / "chassis_review.py"
SERVICIO = VIEWER / "app" / "services" / "review_console_v2.py"
PLANTILLA = VIEWER / "app" / "templates" / "chassis" / "review.html"
MAIN = VIEWER / "app" / "main.py"
SUITE = "tests/test_panel_review_console.py"
FICHERO_SUITE = VIEWER / SUITE
SUITE_CHASIS = "tests/test_chassis_mount_contract.py"
CHASSIS = VIEWER / "app" / "chassis.py"


@dataclass(frozen=True)
class Caso:
    id: str
    garantia: str
    fichero: Path
    de: str
    a: str
    #: Tests que DEBEN ponerse rojos. Se nombran uno a uno: "la suite entera se
    #: pone roja" no dice qué comprobación mordió.
    tests: tuple[str, ...]
    #: Fichero de tests donde viven. Por defecto el del hueco C; los casos del
    #: censo compartido caen además en el contrato del chasis.
    suite: str = SUITE


CASOS: tuple[Caso, ...] = (
    Caso(
        "M1", "El interruptor del hueco apaga el panel",
        ROUTER,
        "    if not slot_enabled(SLOT):\n"
        "        raise HTTPException(status_code=404, detail=f\"El panel {SLOT.title} está apagado\")\n",
        "    if False:\n"
        "        raise HTTPException(status_code=404, detail=f\"El panel {SLOT.title} está apagado\")\n",
        ("test_sin_el_interruptor_el_panel_no_se_sirve",
         "test_solo_true_y_1_encienden_el_panel"),
    ),
    Caso(
        "M2", "El interruptor se evalúa DESPUÉS de la guarda",
        ROUTER,
        "    if isinstance(user, (RedirectResponse, HTMLResponse)):\n"
        "        return user\n"
        "    if not slot_enabled(SLOT):\n",
        "    if not slot_enabled(SLOT):\n"
        "        raise HTTPException(status_code=404, detail=\"apagado\")\n"
        "    if isinstance(user, (RedirectResponse, HTMLResponse)):\n"
        "        return user\n"
        "    if not slot_enabled(SLOT):\n",
        ("test_un_anonimo_no_puede_enumerar_si_el_panel_esta_encendido",),
    ),
    Caso(
        "M3", "El ámbito de visibilidad acota los datos (P0: sin auth no se ve todo)",
        ROUTER,
        "    workspaces = service.workspaces(scope=scope)",
        "    from app.authz.scope import UNRESTRICTED\n"
        "    scope = UNRESTRICTED\n"
        "    workspaces = service.workspaces(scope=scope)",
        ("test_sin_auth_no_reaparece_el_comportamiento_permisivo",
         "test_el_material_de_otra_partida_no_aparece_ni_en_los_contadores",
         "test_la_sustitucion_de_ambito_muerde"),
    ),
    Caso(
        "M4", "Se filtra ANTES de paginar",
        SERVICIO,
        "    filtered = sort_rows(apply_filters(rows, spec), sort)\n"
        "    return ConsoleView(\n"
        "        page=paginate(filtered, page, page_size),",
        "    filtered = sort_rows(rows, sort)\n"
        "    return ConsoleView(\n"
        "        page=Page(\n"
        "            rows=apply_filters(paginate(filtered, page, page_size).rows, spec),\n"
        "            page=page, page_size=page_size, total=len(filtered),\n"
        "            pages=max(1, -(-len(filtered) // page_size)),\n"
        "            has_previous=page > 1, has_next=False, first_index=1, last_index=1),",
        ("test_los_contadores_son_del_conjunto_filtrado_no_de_la_pagina",),
    ),
    Caso(
        "M5", "Un estado que el visor no reconoce NO se declara bueno",
        SERVICIO,
        "    return bool(decision) and decision in VALID_ENGINE_DECISIONS",
        "    return bool(decision)",
        ("test_un_estado_desconocido_no_se_declara_conocido",
         "test_un_estado_desconocido_se_marca_en_la_pantalla",
         "test_un_acuerdo_entre_estados_desconocidos_no_es_acuerdo"),
    ),
    Caso(
        "M6", "`not_available` es AUSENCIA, no un valor a pintar",
        SERVICIO,
        "    if not text or text in {\"not_available\", \"UNKNOWN\", \"None\"}:",
        "    if not text:",
        ("test_not_available_es_ausencia_no_un_valor",
         "test_not_available_no_se_pinta_en_la_pantalla"),
    ),
    Caso(
        "M7", "Sin sombra NO hay acuerdo (piezas de las dos partes)",
        SERVICIO,
        "    if effective and shadow and decision_is_known(effective) and decision_is_known(shadow):\n"
        "        agreement = \"AGREE\" if effective == shadow else \"DISAGREE\"",
        "    if effective:\n"
        "        agreement = \"AGREE\" if effective == shadow else \"DISAGREE\"",
        ("test_sin_sombra_no_hay_acuerdo",),
    ),
    Caso(
        "M8", "Recurso no autorizado INDISTINGUIBLE de inexistente",
        ROUTER,
        "    if current is None:",
        "    if any(r.get(\"proposal_id\") == proposal_id for r in items) and current is None:\n"
        "        raise HTTPException(status_code=403, detail=\"No es tuya\")\n"
        "    if current is None:",
        ("test_fuera_de_ambito_inexistente_y_filtrado_dan_el_mismo_404",),
    ),
    Caso(
        "M9", "Un paquete ilegible da 503 SIN volcar rutas ni trazas",
        ROUTER,
        "                error_detail=type(exc).__name__,\n"
        "                workspaces=[], workspace=None, view=None, spec=spec, sort=sort,\n"
        "                page_sizes=console.PAGE_SIZES, sorts=tuple(console.SORTS),\n"
        "            ),\n"
        "            status_code=503,\n"
        "        )\n"
        "    # build_view FILTRA",
        "                error_detail=str(exc),\n"
        "                workspaces=[], workspace=None, view=None, spec=spec, sort=sort,\n"
        "                page_sizes=console.PAGE_SIZES, sorts=tuple(console.SORTS),\n"
        "            ),\n"
        "            status_code=503,\n"
        "        )\n"
        "    # build_view FILTRA",
        ("test_paquete_ilegible_da_503_sin_filtrar_rutas",),
    ),
    Caso(
        "M10", "SOLO LECTURA: ninguna ruta de escritura montada",
        ROUTER,
        "@router.get(\"/item/{proposal_id}\", response_class=HTMLResponse, name=ITEM_ROUTE_NAME)",
        "@router.post(\"/aprobar\")\ndef _mutante_de_escritura():\n    return {\"ok\": True}\n\n\n"
        "@router.get(\"/item/{proposal_id}\", response_class=HTMLResponse, name=ITEM_ROUTE_NAME)",
        ("test_el_panel_no_monta_ningun_metodo_de_escritura",
         "test_los_metodos_de_escritura_son_rechazados_por_http"),
    ),
    Caso(
        "M11", "La ficha es la de la FILA que se abrió",
        SERVICIO,
        "    for index, row in enumerate(rows):\n"
        "        if row.get(\"proposal_id\") == proposal_id:",
        "    for index, row in enumerate(rows):\n"
        "        if True:",
        ("test_la_ficha_es_la_de_la_fila_que_se_abrio",
         "test_los_vecinos_siguen_el_orden_filtrado"),
    ),
    Caso(
        "M12", "Las plantillas resuelven por NOMBRE de ruta, no por URL literal",
        PLANTILLA,
        "action=\"{{ url_for('chassis_review') }}\"",
        "action=\"/panel/review\"",
        ("test_las_plantillas_no_llevan_urls_escritas_a_mano",),
    ),
    Caso(
        "M13", "El router no declara vocabulario propio de autorización",
        ROUTER,
        "MAX_PAGE_SIZE = 200",
        "MAX_PAGE_SIZE = 200\n\n"
        "# Segunda tabla de rangos, exactamente el defecto que la garantía prohíbe.\n"
        "_RANK = {\"admin\": 3, \"reviewer\": 2, \"viewer\": 1}",
        ("test_el_panel_no_declara_vocabulario_propio_de_autorizacion",),
    ),
    # -- Añadidos tras la revisión independiente ---------------------------
    Caso(
        "R5", "La frontera de solo lectura es del ESPACIO DE URL, no del módulo",
        # El defecto se inyecta DESDE FUERA del carril, que es como aparecería
        # de verdad: otro carril monta escritura bajo `/panel/review` sin tocar
        # `chassis_review.py`. Antes de este caso, la suite entera salía
        # 45/45 VERDE mientras la ruta respondía 200 sin autenticar.
        MAIN,
        "\n\n_mount_feature_slots()\n",
        "\n\n_mount_feature_slots()\n\n\n"
        "@app.post(\"/panel/review/aprobar\")\n"
        "def _mutante_de_escritura_externo():\n"
        "    return {\"ok\": True}\n",
        ("test_ninguna_ruta_del_espacio_del_panel_acepta_escritura",),
    ),
    Caso(
        "R6", "La enumeración del espacio del panel no puede quedarse vacía",
        # Calibración DEL INSTRUMENTO, no del sistema. Un barrido de primer
        # nivel sobre `app.routes` ve CERO rutas de este prefijo (FastAPI mete
        # los routers incluidos en envoltorios `_IncludedRouter`), y entonces
        # R5 saldría verde por no mirar. El suelo tiene que cazarlo, y R5 no.
        FICHERO_SUITE,
        "for r in iter_mounted_routes(app) if route_in_prefix",
        "for r in app.routes if route_in_prefix",
        ("test_la_enumeracion_del_espacio_del_panel_no_puede_salir_vacia",),
    ),
    Caso(
        "R7", "Pieza 4: orden por prioridad de revisión",
        SERVICIO,
        "_DECISION_PRIORITY = {\n"
        "    \"REVIEW\": 0,\n"
        "    \"ABSTAIN\": 1,\n"
        "    \"REJECT_INVALID\": 2,\n"
        "}",
        "_DECISION_PRIORITY = {\n"
        "    \"REVIEW\": 2,\n"
        "    \"ABSTAIN\": 1,\n"
        "    \"REJECT_INVALID\": 0,\n"
        "}",
        ("test_los_vecinos_siguen_el_orden_filtrado",),
    ),
    Caso(
        "R8", "Pieza 8: el umbral de baja confianza es el criterio que APLICA",
        SERVICIO,
        "        if confidence is None or confidence >= spec.low_confidence_threshold:\n"
        "            return False",
        "        if confidence is None:\n"
        "            return False",
        ("test_el_umbral_de_baja_confianza_es_criterio_de_presentacion",),
    ),
    # -- Puntos ciegos del CENSO COMPARTIDO (carril chasis-censo) ----------
    # Los seis se inyectan DESDE `main.py`, que es como aparecen de verdad:
    # otro carril cuelga algo bajo `/panel/review` sin tocar el hueco C. Los
    # dos primeros salían VERDES antes de este carril.
    Caso(
        "R9", "El censo compone el prefijo del `Mount`: una sub-app montada "
              "bajo el prefijo NO se esconde tras un path relativo",
        MAIN,
        "\n\n_mount_feature_slots()\n",
        "\n\n_mount_feature_slots()\n\n\n"
        "_sub_mutante = FastAPI()\n\n\n"
        "@_sub_mutante.post(\"/aprobar\")\n"
        "def _mutante_subapp():\n"
        "    return {\"ok\": True}\n\n\n"
        "app.mount(\"/panel/review/admin\", _sub_mutante)\n",
        ("test_ninguna_ruta_del_espacio_del_panel_acepta_escritura",),
    ),
    Caso(
        "R10", "Ausencia de `methods` NO es ausencia de escritura: un WebSocket "
               "bajo el prefijo se ve",
        MAIN,
        "\n\n_mount_feature_slots()\n",
        "\n\n_mount_feature_slots()\n\n\n"
        "@app.websocket(\"/panel/review/ws\")\n"
        "async def _mutante_websocket(websocket):\n"
        "    await websocket.accept()\n",
        ("test_ninguna_ruta_del_espacio_del_panel_acepta_escritura",),
    ),
    Caso(
        "R11", "El prefijo se compone a CUALQUIER profundidad (`Mount` anidado "
               "a dos niveles)",
        MAIN,
        "\n\n_mount_feature_slots()\n",
        "\n\n_mount_feature_slots()\n\n\n"
        "_n1_mutante = FastAPI()\n"
        "_n2_mutante = FastAPI()\n\n\n"
        "@_n2_mutante.post(\"/z\")\n"
        "def _mutante_anidado():\n"
        "    return {\"ok\": True}\n\n\n"
        "_n1_mutante.mount(\"/y\", _n2_mutante)\n"
        "app.mount(\"/panel/review/x\", _n1_mutante)\n",
        ("test_ninguna_ruta_del_espacio_del_panel_acepta_escritura",),
    ),
    Caso(
        # CONTROL NEGATIVO, Y ACOTADO. Ojo con generalizarlo: `include_router`
        # anidado no era punto ciego **cuando lo que anida son `APIRoute`s**,
        # porque FastAPI resuelve esos prefijos dentro del `path` de cada una.
        # NO vale para un `Mount` dentro de un router incluido: ese caso SI
        # estaba abierto y es R16. Un control negativo mal generalizado es peor
        # que ninguno, porque desactiva la sospecha justo donde hacia falta.
        "R12", "`include_router` con prefijo dentro de otro router no esconde "
               "escritura SI lo anidado son APIRoutes (control negativo acotado; "
               "con un `Mount` dentro, ver R16)",
        MAIN,
        "\n\n_mount_feature_slots()\n",
        "\n\n_mount_feature_slots()\n\n\n"
        "from fastapi import APIRouter as _APIRouterMutante\n"
        "_hijo_mutante = _APIRouterMutante()\n\n\n"
        "@_hijo_mutante.post(\"/borrar\")\n"
        "def _mutante_router_anidado():\n"
        "    return {\"ok\": True}\n\n\n"
        "_padre_mutante = _APIRouterMutante()\n"
        "_padre_mutante.include_router(_hijo_mutante, prefix=\"/interno\")\n"
        "app.include_router(_padre_mutante, prefix=\"/panel/review/anidado\")\n",
        ("test_ninguna_ruta_del_espacio_del_panel_acepta_escritura",),
    ),
    Caso(
        # ¿Debe ser lícito un `Mount` de estáticos bajo el prefijo? NO. Un
        # `Mount` es una app ASGI opaca: el censo no puede enumerar sus métodos
        # y por tanto no puede DEMOSTRAR que sea de solo lectura. `StaticFiles`
        # hoy sirve GET/HEAD, pero eso es una propiedad de la clase que el censo
        # no ve y que un cambio de clase invalida en silencio. Se declara y se
        # falla cerrado; eximirlo exige una decisión escrita a mano.
        "R13", "Un `Mount` opaco (estáticos) bajo el prefijo NO se da por bueno",
        MAIN,
        "\n\n_mount_feature_slots()\n",
        "\n\n_mount_feature_slots()\n\n\n"
        "app.mount(\"/panel/review/activos\", StaticFiles(directory=BASE_DIR / \"static\"),\n"
        "          name=\"_mutante_estaticos\")\n",
        ("test_ninguna_ruta_del_espacio_del_panel_acepta_escritura",),
    ),
    Caso(
        "R14", "El barrido de AUTORIZACIÓN del chasis tampoco absuelve a una "
               "ruta sin métodos enumerables",
        MAIN,
        "\n\n_mount_feature_slots()\n",
        "\n\n_mount_feature_slots()\n\n\n"
        "@app.websocket(\"/canal-mutante\")\n"
        "async def _mutante_websocket_global(websocket):\n"
        "    await websocket.accept()\n",
        ("test_no_mounted_route_serves_200_to_anonymous",),
        SUITE_CHASIS,
    ),
    Caso(
        "R15", "Calibración DEL INSTRUMENTO: si `_walk` deja de componer el "
               "prefijo, el censo del espacio del panel encoge",
        # Ablación del criterio 1 sobre el propio helper: sin composición, R9
        # vuelve a colarse. Se comprueba con el test de composición, no con la
        # frontera, para que el rojo case con la razón.
        CHASSIS,
        "    if not prefix:\n        return path\n    return prefix.rstrip(\"/\") + path",
        "    return path",
        ("test_el_censo_compone_el_prefijo_de_los_mount",),
        SUITE_CHASIS,
    ),
    Caso(
        # La misma clase que R9, por otra via: FastAPI solo rellena el
        # `_EffectiveRouteContext` para las `APIRoute`. Si envuelve un `Mount`,
        # llega con `path=''`, el filtro lo descarta y el barrido de
        # autorizacion lo salta. Medido: 200 y escritura.
        "R16", "Un `Mount` DENTRO de un `APIRouter` incluido con prefijo tampoco "
               "esconde escritura (path indeterminable)",
        MAIN,
        "\n\n_mount_feature_slots()\n",
        "\n\n_mount_feature_slots()\n\n\n"
        "from fastapi import APIRouter as _APIRouterMG\n"
        "_router_mg = _APIRouterMG()\n"
        "_sub_mg = FastAPI()\n\n\n"
        "@_sub_mg.post(\"/aprobar\")\n"
        "def _mutante_mount_en_router_incluido():\n"
        "    return {\"ok\": True}\n\n\n"
        "_router_mg.mount(\"/m\", _sub_mg)\n"
        "app.include_router(_router_mg, prefix=\"/panel/review/inc\")\n",
        ("test_ninguna_ruta_del_espacio_del_panel_acepta_escritura",),
    ),
    Caso(
        "R17", "Capa (a) de M-G: sin resolver la `starlette_route` subyacente, "
               "el censo vuelve a emitir la ruta con path indeterminable",
        # Calibracion DEL INSTRUMENTO. Ojo con lo que NO dice: quitar esta capa
        # NO deja pasar M-G por el gate, porque la capa (b) —el tri-estado del
        # path— lo atrapa igualmente (medido). Lo que esta capa aporta es
        # NOMBRAR la ruta con su URL real en vez de reportar un anonimo
        # "<PATH-NO-RESOLUBLE>". Las dos capas juntas son las necesarias: con
        # ambas quitadas, M-G vuelve a colarse en VERDE (medido).
        CHASSIS,
        "            if real is not None and getattr(real, \"path\", None):\n"
        "                route = real",
        "            pass",
        ("test_un_mount_dentro_de_un_router_incluido_no_pierde_el_path",),
        SUITE_CHASIS,
    ),
    Caso(
        # FALSO POSITIVO (M-E), no falso negativo: la calibracion tiene que
        # exigir tambien que el gate NO acuse a quien no es suyo.
        "R18", "El gate de C no acusa a un vecino de prefijo "
               "(`/panel/reviewXYZ` no es `/panel/review`)",
        FICHERO_SUITE,
        "    return [r for r in iter_mounted_routes(app) if route_in_prefix(r, SLOT.prefix)]",
        "    return [r for r in iter_mounted_routes(app)\n"
        "            if str(getattr(r, \"path\", \"\")).startswith(SLOT.prefix)]",
        ("test_el_gate_no_acusa_a_un_vecino_de_prefijo",),
    ),
    Caso(
        "R19", "Capa (b) de M-G: una ruta con path irresoluble cae DENTRO de "
               "cualquier prefijo, no fuera de todos",
        # El suelo que queda si un tipo de ruta futuro vuelve a llegar sin path
        # resoluble. Hoy no hay ninguna en la app real, asi que se calibra sobre
        # el helper, que es donde vive la doctrina.
        CHASSIS,
        "    path = effective_path(route)\n"
        "    if path is None:\n"
        "        return True\n"
        "    return path_in_prefix(path, prefix)",
        "    return path_in_prefix(str(getattr(route, \"path\", \"\") or \"\"), prefix)",
        ("test_una_ruta_con_path_irresoluble_cae_DENTRO_de_cualquier_prefijo",),
        SUITE_CHASIS,
    ),
    Caso(
        "R20", "El barrido de AUTORIZACION declara las rutas cuyo path no sabe "
               "resolver en vez de saltarselas",
        VIEWER / "tests" / "test_chassis_mount_contract.py",
        "        if path is None:\n"
        "            # Antes esto era `if not path: continue`",
        "        if path is None and False:\n"
        "            # Antes esto era `if not path: continue`",
        ("test_el_barrido_de_autorizacion_no_se_salta_un_path_irresoluble",),
        SUITE_CHASIS,
    ),
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def correr(tests: tuple[str, ...], suite: str = SUITE) -> tuple[bool, list[str], str]:
    """Ejecuta EXACTAMENTE esos tests. Cero recolectados = fallo, no éxito.

    Devuelve ``(verde, tests_en_rojo, ultima_linea)``. Los nombres en rojo se
    devuelven para poder exigir que el fallo case con la RAZÓN declarada: un
    rojo por el motivo equivocado es más peligroso que un verde.
    """
    import re

    expr = " or ".join(tests)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", suite, "-k", expr, "-q", "--no-header",
         "-p", "no:cacheprovider", "--tb=no", "-rf", "--color=no"],
        cwd=VIEWER, capture_output=True, text=True,
    )
    salida = proc.stdout + proc.stderr
    if " no tests ran" in salida or "collected 0 items" in salida:
        return False, ["0 TESTS RECOLECTADOS (arnés roto)"], "0 recolectados"
    rojos = sorted(set(re.findall(r"^FAILED [^:]+::([\w\[\]\-.]+)", salida, re.M)))
    ultima = salida.strip().splitlines()[-1] if salida.strip() else ""
    return proc.returncode == 0, rojos, ultima


def main() -> int:
    fallos: list[str] = []
    print(f"{'caso':<5} {'base':<8} {'mutado':<8} {'reversión':<11} garantía")
    print("-" * 100)
    for caso in CASOS:
        antes = sha(caso.fichero)
        original = caso.fichero.read_text(encoding="utf-8")

        base_verde, _, _ = correr(caso.tests, caso.suite)

        if caso.de not in original:
            fallos.append(f"{caso.id}: el ancla de la mutación ya no existe en {caso.fichero.name}")
            print(f"{caso.id:<5} {'?':<8} {'ANCLA':<8} {'-':<11} {caso.garantia}")
            continue
        if original.count(caso.de) != 1:
            fallos.append(f"{caso.id}: el ancla aparece {original.count(caso.de)} veces (ambigua)")
            continue

        caso.fichero.write_text(original.replace(caso.de, caso.a), encoding="utf-8")
        try:
            mutado_verde, rojos, detalle = correr(caso.tests, caso.suite)
        finally:
            caso.fichero.write_text(original, encoding="utf-8")
        despues = sha(caso.fichero)

        reversion = antes == despues
        estado_base = "VERDE" if base_verde else "ROJO"
        estado_mut = "ROJO" if not mutado_verde else "VERDE"
        print(f"{caso.id:<5} {estado_base:<8} {estado_mut:<8} "
              f"{('idéntica' if reversion else 'DISTINTA'):<11} {caso.garantia}")
        if not mutado_verde:
            print(f"{'':<5} rojos: {', '.join(r.split('[')[0] for r in rojos)}")
        # El rojo tiene que caer en la comprobación DECLARADA, no en otra.
        ajenos = sorted({r.split('[')[0] for r in rojos} - set(caso.tests))
        if ajenos:
            fallos.append(f"{caso.id}: rojo por el motivo equivocado, en {ajenos}")
        if not base_verde:
            fallos.append(f"{caso.id}: rojo YA sin mutar ({detalle})")
        if mutado_verde:
            fallos.append(f"{caso.id}: la mutación NO se detecta — la garantía no muerde")
        if not reversion:
            fallos.append(f"{caso.id}: la reversión no es byte a byte")

    print("-" * 100)
    if fallos:
        for f in fallos:
            print(f"  FALLO: {f}")
        return 1
    print(f"{len(CASOS)}/{len(CASOS)} garantías calibradas: verdes sin mutar, "
          "rojas con el defecto, reversión idéntica por hash.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
