#!/usr/bin/env python3
"""Calibración del hueco F (Panel de Fuentes): ¿puede ponerse ROJA cada garantía?

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
    python3 scripts/calibrar_panel_sources.py

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
ROUTER = VIEWER / "app" / "routers" / "chassis_sources.py"
PLANTILLA = VIEWER / "app" / "templates" / "chassis" / "sources.html"
MAIN = VIEWER / "app" / "main.py"
SUITE = "tests/test_panel_sources.py"
FICHERO_SUITE = VIEWER / SUITE


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
        "F1", "El interruptor del hueco apaga el panel",
        ROUTER,
        "    if not slot_enabled(SLOT):\n"
        "        raise HTTPException(status_code=404, detail=f\"El panel {SLOT.title} está apagado\")\n",
        "    if False:\n"
        "        raise HTTPException(status_code=404, detail=f\"El panel {SLOT.title} está apagado\")\n",
        ("test_sin_el_interruptor_el_panel_no_se_sirve",
         "test_solo_true_y_1_encienden_el_panel"),
    ),
    Caso(
        "F2", "El interruptor se evalúa DESPUÉS de la guarda",
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
        # EL defecto de este carril: volver al proveedor SIN filtrar. Es
        # exactamente lo que haría alguien que quisiera "arreglar" el panel
        # vacío de un banco sin autenticación, y es la vía que el P0 de
        # autoridad (docs/75) cerró.
        "F3", "Los datos salen del proveedor FILTRADO, no del crudo (P0: sin "
              "auth no se ve todo)",
        ROUTER,
        "    provider: GraphProvider = Depends(get_filtered_provider),\n"
        "):\n"
        "    \"\"\"Listado de fuentes visibles del workspace elegido.\"\"\"",
        "    provider: GraphProvider = Depends(get_filtered_provider),\n"
        "):\n"
        "    \"\"\"Listado de fuentes visibles del workspace elegido.\"\"\"\n"
        "    from app.deps import get_provider as _crudo\n"
        "    provider = _crudo()",
        ("test_sin_auth_no_reaparece_el_comportamiento_permisivo",
         "test_los_contadores_no_incluyen_lo_que_el_espectador_no_ve",
         "test_la_sustitucion_del_proveedor_muerde",
         "test_tabla_medida_del_anonimo_con_auth_desactivada"),
    ),
    Caso(
        "F4", "La pantalla NO publica la ruta de origen de una fuente",
        ROUTER,
        "    normalizado = source_id.replace(\"\\\\\", \"/\")\n"
        "    nombre = normalizado.rsplit(\"/\", 1)[-1].strip()",
        "    normalizado = source_id\n"
        "    nombre = normalizado",
        ("test_la_ruta_de_origen_no_aparece_nunca_en_el_html",
         "test_la_etiqueta_es_el_ultimo_segmento_con_los_dos_separadores",
         "test_la_fila_publicada_no_contiene_el_identificador_crudo"),
    ),
    Caso(
        # FALSO POSITIVO, no falso negativo: si el marcador se pusiera siempre,
        # F4 seguiría verde y el aviso "(ruta oculta)" dejaría de significar
        # nada. Un rojo por el motivo equivocado es más peligroso que un verde.
        "F5", "El marcador de redacción no se pone cuando no hay ruta que ocultar",
        ROUTER,
        "    recortado = nombre != source_id",
        "    recortado = True",
        ("test_una_fuente_sin_ruta_no_se_marca_como_redactada",
         "test_la_etiqueta_es_el_ultimo_segmento_con_los_dos_separadores"),
    ),
    Caso(
        "F6", "El asa de la URL es opaca: el identificador no viaja en la URL",
        ROUTER,
        "    return hashlib.sha256(source_id.encode(\"utf-8\")).hexdigest()[:LONGITUD_ASA]",
        "    return source_id",
        ("test_la_url_de_la_ficha_no_lleva_la_ruta",
         "test_el_asa_no_es_reversible_ni_contiene_el_identificador",
         "test_la_ruta_de_origen_no_aparece_nunca_en_el_html"),
    ),
    Caso(
        "F7", "Un estado de revisión que el visor no reconoce NO se declara bueno",
        ROUTER,
        "            conocido = bool(review_status_contract.is_canonical(clave))",
        "            conocido = True",
        ("test_un_estado_desconocido_no_se_declara_conocido",
         "test_un_estado_desconocido_se_marca_en_la_pantalla"),
    ),
    Caso(
        "F8", "Ausencia ≠ cero: las entidades sin fuente se declaran, no se pierden",
        ROUTER,
        "    return SIN_FUENTE\n",
        "    return \"\"\n",
        ("test_las_entidades_sin_fuente_se_declaran_no_se_pierden",
         "test_un_identificador_de_fuente_que_no_es_texto_va_al_cubo_de_ausencia"),
    ),
    Caso(
        "F9", "Un `source_document` que no es texto no inventa una fuente",
        ROUTER,
        "    return valor if isinstance(valor, str) and valor.strip() else None",
        "    return valor if valor else None",
        ("test_un_identificador_de_fuente_que_no_es_texto_va_al_cubo_de_ausencia",),
    ),
    Caso(
        "F10", "Recurso no autorizado INDISTINGUIBLE de inexistente",
        ROUTER,
        "    fila = next((f for f in filas if f[\"handle\"] == handle), None)\n"
        "    if fila is None:",
        "    fila = next((f for f in filas if f[\"handle\"] == handle), None)\n"
        "    if fila is None and handle == \"0\" * 16:\n"
        "        raise HTTPException(status_code=404, detail=\"No existe\")\n"
        "    if fila is None:",
        ("test_asa_inexistente_y_fuera_de_ambito_dan_el_mismo_404",),
    ),
    Caso(
        "F11", "Un fallo del proveedor da 503 SIN volcar rutas ni URIs",
        ROUTER,
        "            error_detail=type(exc).__name__,",
        "            error_detail=str(exc),",
        ("test_un_fallo_del_proveedor_da_503_sin_filtrar_rutas",
         "test_un_fallo_del_proveedor_en_la_ficha_tampoco_filtra"),
    ),
    Caso(
        "F12", "SOLO LECTURA: el MÓDULO no monta ninguna ruta de escritura",
        ROUTER,
        "@router.get(\"/ficha/{handle}\", response_class=HTMLResponse, name=ITEM_ROUTE_NAME)",
        "@router.post(\"/reingestar\")\ndef _mutante_de_escritura():\n    return {\"ok\": True}\n\n\n"
        "@router.get(\"/ficha/{handle}\", response_class=HTMLResponse, name=ITEM_ROUTE_NAME)",
        ("test_el_panel_no_monta_ningun_metodo_de_escritura",
         "test_ninguna_ruta_del_espacio_del_panel_acepta_escritura",
         "test_los_metodos_de_escritura_son_rechazados_por_http"),
    ),
    Caso(
        # El defecto se inyecta DESDE FUERA del carril, que es como aparecería
        # de verdad: otro carril monta escritura bajo `/panel/sources` sin tocar
        # `chassis_sources.py`. Es el caso que en el hueco C dejaba la suite
        # entera en verde con la ruta respondiendo 200.
        "F13", "La frontera de solo lectura es del ESPACIO DE URL, no del módulo",
        MAIN,
        "\n\n_mount_feature_slots()\n",
        "\n\n_mount_feature_slots()\n\n\n"
        "@app.post(\"/panel/sources/subir\")\n"
        "def _mutante_de_escritura_externo():\n"
        "    return {\"ok\": True}\n",
        ("test_ninguna_ruta_del_espacio_del_panel_acepta_escritura",),
    ),
    Caso(
        # Calibración DEL INSTRUMENTO, no del sistema. Un barrido de primer
        # nivel sobre `app.routes` ve CERO rutas de este prefijo, y entonces F13
        # saldría verde por no mirar. El suelo tiene que cazarlo, y F13 no.
        "F14", "La enumeración del espacio del panel no puede quedarse vacía",
        FICHERO_SUITE,
        "    return [r for r in iter_mounted_routes(app) if route_in_prefix(r, SLOT.prefix)]",
        "    return [r for r in app.routes if route_in_prefix(r, SLOT.prefix)]",
        ("test_la_enumeracion_del_espacio_del_panel_no_puede_salir_vacia",),
    ),
    Caso(
        # FALSO POSITIVO del gate (clase M-E), no falso negativo: la calibración
        # tiene que exigir también que el gate NO acuse a quien no es suyo.
        # `/panel/sources-legacy` no es `/panel/sources`.
        "F15", "El gate de F no acusa a un vecino de prefijo",
        FICHERO_SUITE,
        "    return [r for r in iter_mounted_routes(app) if route_in_prefix(r, SLOT.prefix)]",
        "    return [r for r in iter_mounted_routes(app)\n"
        "            if str(getattr(r, \"path\", \"\")).startswith(SLOT.prefix)]",
        ("test_el_gate_no_acusa_a_un_vecino_de_prefijo",),
    ),
    Caso(
        "F16", "Las plantillas resuelven por NOMBRE de ruta, no por URL literal",
        PLANTILLA,
        "action=\"{{ url_for('chassis_sources') }}\"",
        "action=\"/panel/sources\"",
        ("test_las_plantillas_no_llevan_urls_escritas_a_mano",),
    ),
    Caso(
        "F17", "El router no declara vocabulario propio de autorización",
        ROUTER,
        "LONGITUD_ASA = 16",
        "LONGITUD_ASA = 16\n\n"
        "# Segunda tabla de rangos, exactamente el defecto que la garantía prohíbe.\n"
        "_RANGOS = {\"admin\": 3, \"reviewer\": 2, \"viewer\": 1}",
        ("test_el_panel_no_declara_vocabulario_propio_de_autorizacion",),
    ),
    Caso(
        # La frontera por debajo del HTTP. Un GET que llama a un método de
        # escritura del proveedor no lo caza ninguna enumeración de métodos.
        "F18", "El panel no invoca métodos del proveedor fuera de la lectura",
        ROUTER,
        "    entidades, _total = provider.list_entities(elegido, limit=SIN_TOPE, offset=0)",
        "    provider.quality_metrics(elegido)\n"
        "    entidades, _total = provider.list_entities(elegido, limit=SIN_TOPE, offset=0)",
        ("test_el_panel_solo_invoca_metodos_de_LECTURA_del_proveedor",),
    ),
    Caso(
        # CONTROL DEL CONTROL NEGATIVO. El test de inercia afirma algo NEGATIVO
        # ("sustituir `get_visibility_context` no cambia nada"), y un test así
        # pasa por accidente con facilidad. Aquí se hace que el punto de
        # inyección SÍ muerda —el router pasa a recibirlo por `Depends`— y se
        # exige que el test lo note. Si no lo notara, la afirmación de inercia
        # sería palabrería y el siguiente carril podría fabricar un arnés que no
        # muerde creyéndose protegido.
        "F19", "El test de inercia de `get_visibility_context` detecta que "
               "dejara de ser inerte",
        ROUTER,
        "    provider: GraphProvider = Depends(get_filtered_provider),\n"
        "):\n"
        "    \"\"\"Listado de fuentes visibles del workspace elegido.\"\"\"",
        "    provider: GraphProvider = Depends(get_filtered_provider),\n"
        "    _ctx=Depends(__import__(\"app.authz.dependencies\", fromlist=[\"x\"])"
        ".get_visibility_context),\n"
        "):\n"
        "    \"\"\"Listado de fuentes visibles del workspace elegido.\"\"\"\n"
        "    from app.authz.filtered_provider import PolicyFilteredProvider\n"
        "    from app.deps import get_provider as _base\n"
        "    provider = PolicyFilteredProvider(_base(), _ctx)",
        ("test_sustituir_get_visibility_context_es_inerte",),
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
