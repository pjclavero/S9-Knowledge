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
SUITE = "tests/test_panel_review_console.py"


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
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def correr(tests: tuple[str, ...]) -> tuple[bool, list[str], str]:
    """Ejecuta EXACTAMENTE esos tests. Cero recolectados = fallo, no éxito.

    Devuelve ``(verde, tests_en_rojo, ultima_linea)``. Los nombres en rojo se
    devuelven para poder exigir que el fallo case con la RAZÓN declarada: un
    rojo por el motivo equivocado es más peligroso que un verde.
    """
    import re

    expr = " or ".join(tests)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", SUITE, "-k", expr, "-q", "--no-header",
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

        base_verde, _, _ = correr(caso.tests)

        if caso.de not in original:
            fallos.append(f"{caso.id}: el ancla de la mutación ya no existe en {caso.fichero.name}")
            print(f"{caso.id:<5} {'?':<8} {'ANCLA':<8} {'-':<11} {caso.garantia}")
            continue
        if original.count(caso.de) != 1:
            fallos.append(f"{caso.id}: el ancla aparece {original.count(caso.de)} veces (ambigua)")
            continue

        caso.fichero.write_text(original.replace(caso.de, caso.a), encoding="utf-8")
        try:
            mutado_verde, rojos, detalle = correr(caso.tests)
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
