#!/usr/bin/env python3
"""Calibración del hueco G (Panel de Entidades): ¿puede ponerse ROJA cada garantía?

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

Además de cada mutación se comprueba el DIFERENCIAL: los mismos tests tienen que
estar VERDES sobre el árbol sin mutar. Un rojo permanente (por entorno, por una
fixture rota) no demuestra que la comprobación muerda.

USO
---
    python3 scripts/calibrar_panel_entities.py

Salida: una tabla por caso con VERDE base / ROJO mutado / reversión idéntica, y
código de salida 1 si algún caso no se pudo poner rojo.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
VIEWER = RAIZ / "viewer"
ROUTER = VIEWER / "app" / "routers" / "chassis_entities.py"
PLANTILLA = VIEWER / "app" / "templates" / "chassis" / "entities.html"
MAIN = VIEWER / "app" / "main.py"
SUITE = "tests/test_panel_entities.py"
FICHERO_SUITE = VIEWER / SUITE
SUITE_CHASIS = "tests/test_chassis_mount_contract.py"
FICHERO_SUITE_CHASIS = VIEWER / SUITE_CHASIS


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
    suite: str = SUITE


CASOS: tuple[Caso, ...] = (
    Caso(
        "G1", "El interruptor del hueco apaga el panel",
        ROUTER,
        "    if not slot_enabled(SLOT):\n"
        "        raise HTTPException(status_code=404, detail=f\"El panel {SLOT.title} está apagado\")\n",
        "    if False:\n"
        "        raise HTTPException(status_code=404, detail=f\"El panel {SLOT.title} está apagado\")\n",
        ("test_sin_el_interruptor_el_panel_no_se_sirve",
         "test_solo_true_y_1_encienden_el_panel"),
    ),
    Caso(
        "G2", "El interruptor se evalúa DESPUÉS de la guarda "
              "(si no, un anónimo enumera qué paneles están encendidos)",
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
        "G3", "El panel lee por el proveedor FILTRADO y no por el crudo "
              "(P0: sin auth NO se vuelve a ver todo)",
        ROUTER,
        "from app.authz.dependencies import get_filtered_provider",
        "from app.deps import get_provider as get_filtered_provider",
        ("test_sin_auth_no_reaparece_el_comportamiento_permisivo",
         "test_tabla_de_lo_que_ve_un_anonimo_con_auth_desactivada",
         "test_los_contadores_son_del_conjunto_autorizado",
         "test_el_control_de_autorizacion_COLAPSA",
         "test_el_panel_usa_el_proveedor_filtrado_y_no_el_crudo"),
    ),
    Caso(
        "G4", "Los contadores son del conjunto AUTORIZADO, no del crudo "
              "(un total pre-política filtra POR DIFERENCIA lo que se acaba de ocultar)",
        ROUTER,
        "        _, autorizadas = provider.list_entities(ws, limit=1, offset=0)",
        "        autorizadas = getattr(provider, \"_base\").list_entities(ws, limit=1, offset=0)[1]",
        ("test_los_contadores_son_del_conjunto_autorizado",
         "test_barrer_el_tope_de_pagina_no_mueve_el_total",
         "test_un_panel_vacio_para_un_anonimo_es_correcto"),
    ),
    Caso(
        "G5", "Un fallo del proveedor NO se publica como «cero entidades» "
              "(ausencia ≠ cero)",
        ROUTER,
        "            error=\"No se pudieron leer las entidades: la fuente de datos no respondió.\",\n"
        "            error_detail=type(exc).__name__,\n"
        "            listado=None, **extra,",
        "            listado={\"limit\": 0, \"offset\": 0, \"total\": 0, \"autorizadas\": 0,\n"
        "                     \"mostradas\": 0, \"has_next\": False, \"has_previous\": False,\n"
        "                     \"primera\": 0, \"ultima\": 0},\n"
        "            items=[], q=\"\", sort=\"\", order=\"\", entity_type=\"\",\n"
        "            review_status=\"\", tipos=[], **extra,",
        ("test_la_ausencia_de_datos_no_se_publica_como_cero",
         "test_un_proveedor_caido_da_503_sin_filtrar_rutas"),
    ),
    Caso(
        "G6", "El 503 publica el NOMBRE DEL TIPO, nunca `str(exc)` "
              "(que puede traer una URI con credenciales)",
        ROUTER,
        "            error_detail=type(exc).__name__,",
        "            error_detail=str(exc),",
        ("test_un_proveedor_caido_da_503_sin_filtrar_rutas",),
    ),
    Caso(
        "G7", "Recurso no autorizado INDISTINGUIBLE de inexistente "
              "(el cuerpo del 404 no puede variar con la petición)",
        ROUTER,
        "        raise HTTPException(status_code=404, detail=FICHA_NO_ENCONTRADA)",
        "        raise HTTPException(status_code=404, detail=f\"{FICHA_NO_ENCONTRADA}: {entity_id}\")",
        ("test_no_autorizado_e_inexistente_dan_EL_MISMO_404",
         "test_el_cuerpo_del_404_no_nombra_la_entidad_pedida"),
    ),
    Caso(
        "G8", "SOLO LECTURA: ninguna ruta de escritura montada por ESTE módulo",
        ROUTER,
        "@router.get(\"/item/{entity_id}\", response_class=HTMLResponse, name=ITEM_ROUTE_NAME)",
        "@router.post(\"/fusionar\")\ndef _mutante_de_escritura():\n    return {\"ok\": True}\n\n\n"
        "@router.get(\"/item/{entity_id}\", response_class=HTMLResponse, name=ITEM_ROUTE_NAME)",
        # `test_los_metodos_de_escritura_son_rechazados_por_http` NO entra: se
        # midió y sigue VERDE con este POST colgado en una subruta, porque sólo
        # sondea el prefijo raíz. Es redundancia inofensiva, no garantía, y así
        # está anotado en el propio test y en docs/77 §6.
        ("test_el_panel_no_monta_ningun_metodo_de_escritura",
         "test_ninguna_ruta_del_espacio_del_panel_acepta_escritura"),
    ),
    Caso(
        # EL caso que el hueco C midió y que este hereda: la frontera es del
        # ESPACIO DE URL, no del módulo. La escritura se cuelga desde `main.py`,
        # que es como aparecería de verdad: otro carril en tu prefijo.
        "G9", "SOLO LECTURA del ESPACIO DE URL: un POST colgado bajo "
              "`/panel/entities` DESDE OTRO FICHERO también se ve",
        MAIN,
        "\n\n_mount_feature_slots()\n",
        "\n\n_mount_feature_slots()\n\n\n"
        "@app.post(\"/panel/entities/fusionar\")\n"
        "def _mutante_fusionar():\n"
        "    return {\"ok\": True}\n",
        ("test_ninguna_ruta_del_espacio_del_panel_acepta_escritura",),
    ),
    Caso(
        "G10", "Sub-app montada bajo el prefijo: el censo compone el prefijo "
               "del `Mount` y no la pierde tras un path relativo",
        MAIN,
        "\n\n_mount_feature_slots()\n",
        "\n\n_mount_feature_slots()\n\n\n"
        "_sub_mutante_g = FastAPI()\n\n\n"
        "@_sub_mutante_g.post(\"/fusionar\")\n"
        "def _mutante_subapp_g():\n"
        "    return {\"ok\": True}\n\n\n"
        "app.mount(\"/panel/entities/admin\", _sub_mutante_g)\n",
        ("test_ninguna_ruta_del_espacio_del_panel_acepta_escritura",),
    ),
    Caso(
        "G11", "MODO DE FALLO DEL INSTRUMENTO: si la enumeración deja de "
               "aplanar, ve CERO rutas y «demostraría» cualquier cosa",
        FICHERO_SUITE,
        "    return [r for r in iter_mounted_routes(app) if route_in_prefix(r, SLOT.prefix)]",
        "    return [r for r in app.routes if route_in_prefix(r, SLOT.prefix)]",
        ("test_la_enumeracion_del_espacio_del_panel_no_puede_salir_vacia",),
    ),
    Caso(
        # FALSO POSITIVO, no falso negativo: la calibración tiene que exigir
        # también que el gate NO acuse a quien no es suyo. Un rojo por el motivo
        # equivocado entrena a ignorar el gate.
        "G12", "El gate no acusa a un vecino de prefijo "
               "(`/panel/entitiesXYZ` no es `/panel/entities`)",
        FICHERO_SUITE,
        "    return [r for r in iter_mounted_routes(app) if route_in_prefix(r, SLOT.prefix)]",
        "    return [r for r in iter_mounted_routes(app)\n"
        "            if str(getattr(r, \"path\", \"\")).startswith(SLOT.prefix)]",
        ("test_el_gate_no_acusa_a_un_vecino_de_prefijo",),
    ),
    Caso(
        "G13", "Ningún efecto lateral desde un GET: el panel sólo invoca "
               "lecturas del proveedor",
        ROUTER,
        "    filas = [serialize_node(n) for n in items]",
        "    getattr(getattr(provider, \"_base\", None), \"escribir\", lambda: None)()\n"
        "    filas = [serialize_node(n) for n in items]",
        ("test_recorrer_el_panel_solo_invoca_lecturas_del_proveedor",),
    ),
    Caso(
        "G14", "La plantilla no escribe URLs a mano",
        PLANTILLA,
        "action=\"{{ url_for('chassis_entities') }}\"",
        "action=\"/panel/entities\"",
        ("test_las_plantillas_no_llevan_urls_escritas_a_mano",),
    ),
    Caso(
        "G15", "El panel no declara vocabulario propio de autorización",
        ROUTER,
        "def _authorize(user):",
        "_RANK = {\"admin\": 3, \"reviewer\": 2, \"viewer\": 1}\n\n\n"
        "def _authorize(user):",
        ("test_el_panel_no_declara_vocabulario_propio_de_autorizacion",),
    ),
    Caso(
        "G16", "La plantilla no ofrece acciones que el panel no puede cumplir",
        PLANTILLA,
        "      <button type=\"submit\">Filtrar</button>",
        "      <button type=\"submit\">Filtrar</button>\n"
        "      <button type=\"submit\" formmethod=\"post\">Fusionar seleccionadas</button>",
        ("test_las_plantillas_no_ofrecen_ninguna_accion_de_escritura",),
    ),
    Caso(
        # El test compartido del chasis decía «sin datos» y no lo montaba: se
        # apoyaba en que los cuatro huecos estaban vacíos. Con la premisa puesta
        # de verdad, quitarla vuelve a hacerlo depender del azar.
        "G17", "La premisa «sin datos» del contrato del chasis está MONTADA, "
               "no supuesta",
        FICHERO_SUITE_CHASIS,
        "    real_app.dependency_overrides[deps.get_provider] = lambda: _ProveedorVacio()",
        "    pass",
        ("test_slot_renders_empty_state_instead_of_exploding",),
        SUITE_CHASIS,
    ),
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def correr(tests: tuple[str, ...], suite: str = SUITE) -> tuple[bool, list[str], str]:
    """Ejecuta EXACTAMENTE esos tests. Cero recolectados = fallo, no éxito."""
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
    print(f"{'caso':<6} {'base':<8} {'mutado':<8} {'reversión':<11} garantía")
    print("-" * 110)
    for caso in CASOS:
        antes = sha(caso.fichero)
        original = caso.fichero.read_text(encoding="utf-8")

        base_verde, _, detalle_base = correr(caso.tests, caso.suite)

        if caso.de not in original:
            fallos.append(f"{caso.id}: el ancla ya no existe en {caso.fichero.name}")
            print(f"{caso.id:<6} {'?':<8} {'ANCLA':<8} {'-':<11} {caso.garantia}")
            continue
        if original.count(caso.de) != 1:
            fallos.append(f"{caso.id}: el ancla aparece {original.count(caso.de)} veces (ambigua)")
            print(f"{caso.id:<6} {'?':<8} {'ANCLA':<8} {'-':<11} {caso.garantia}")
            continue

        caso.fichero.write_text(original.replace(caso.de, caso.a), encoding="utf-8")
        try:
            mutado_verde, rojos, detalle = correr(caso.tests, caso.suite)
        finally:
            caso.fichero.write_text(original, encoding="utf-8")
        despues = sha(caso.fichero)

        reversion = antes == despues
        print(f"{caso.id:<6} {('VERDE' if base_verde else 'ROJO'):<8} "
              f"{('ROJO' if not mutado_verde else 'VERDE'):<8} "
              f"{('idéntica' if reversion else 'DISTINTA'):<11} {caso.garantia}")
        if not mutado_verde:
            print(f"{'':<6} rojos: {', '.join(sorted({r.split('[')[0] for r in rojos}))}")
        ajenos = sorted({r.split('[')[0] for r in rojos} - set(caso.tests))
        if ajenos:
            fallos.append(f"{caso.id}: rojo por el motivo equivocado, en {ajenos}")
        if not base_verde:
            fallos.append(f"{caso.id}: rojo YA sin mutar ({detalle_base})")
        if mutado_verde:
            fallos.append(f"{caso.id}: la mutación NO se detecta — la garantía no muerde")
        if not reversion:
            fallos.append(f"{caso.id}: la reversión no es byte a byte")

    print("-" * 110)
    if fallos:
        for f in fallos:
            print(f"  FALLO: {f}")
        return 1
    print(f"{len(CASOS)}/{len(CASOS)} garantías calibradas: verdes sin mutar, "
          "rojas con el defecto, reversión idéntica por hash.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
