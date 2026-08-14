#!/usr/bin/env python3
"""Calibración del hueco B (Operations): ¿puede ponerse ROJA cada garantía?

MOTIVO
------
Un verde no es evidencia. Una comprobación que no puede fallar es decorativa, y
en este repo ya se ha cobrado más de una como defensa. Este guion introduce una
MUTACIÓN EFÍMERA por garantía —el defecto que la garantía dice impedir—,
ejecuta los tests que deberían cazarla y exige que se pongan rojos POR EL MOTIVO
DECLARADO, no por cualquier motivo.

MÉTODO
------
Para cada caso: se mide el sha256 del fichero, se aplica la sustitución, se
ejecutan los tests nombrados, se restaura el fichero y se vuelve a medir el
sha256. Si el hash de vuelta no es idéntico al de ida, el caso se declara
INVÁLIDO: una medición sobre un árbol que no volvió a su sitio no vale nada.

Además de cada mutación se comprueba el DIFERENCIAL: los mismos tests tienen
que estar VERDES sobre el árbol sin mutar. Un rojo permanente (por entorno, por
una fixture rota) no demuestra que la comprobación muerda.

LO QUE ESTE GUION **NO** DEMUESTRA
----------------------------------
Que la enumeración del espacio de URL cace un `Mount` opaco, un WebSocket o una
sub-app anidada bajo el prefijo. Esas seis clases de punto ciego las resuelve el
CENSO COMPARTIDO (`app.chassis.iter_mounted_routes`) y están calibradas en
`scripts/calibrar_panel_review.py` (casos R9-R20), sobre el mismo instrumento
que usa este hueco. Repetirlas aquí sería medir dos veces lo mismo y sugerir
que este carril las resolvió.

USO
---
    python3 scripts/calibrar_panel_operations.py

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
ROUTER = VIEWER / "app" / "routers" / "chassis_operations.py"
PLANTILLA = VIEWER / "app" / "templates" / "chassis" / "operations.html"
MAIN = VIEWER / "app" / "main.py"
SUITE = "tests/test_panel_operations.py"
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
        "B1", "El interruptor del hueco apaga el panel",
        ROUTER,
        "    if not slot_enabled(SLOT):\n"
        "        raise HTTPException(status_code=404, detail=f\"El panel {SLOT.title} está apagado\")\n",
        "    if False:\n"
        "        raise HTTPException(status_code=404, detail=f\"El panel {SLOT.title} está apagado\")\n",
        ("test_sin_el_interruptor_el_panel_no_se_sirve",
         "test_solo_true_y_1_encienden_el_panel"),
    ),
    Caso(
        "B2", "El interruptor se evalúa DESPUÉS de la guarda",
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
        "B3", "El ámbito de visibilidad acota las FILAS (P0: no se ve lo ajeno)",
        ROUTER,
        "            crudos = _jobs_rows(\n"
        "                scope, workspace=workspace, status=status, job_type=job_type, limit=limit\n"
        "            )",
        "            from app.authz.scope import UNRESTRICTED\n"
        "            crudos = _jobs_rows(\n"
        "                UNRESTRICTED, workspace=workspace, status=status,\n"
        "                job_type=job_type, limit=limit,\n"
        "            )",
        ("test_la_sustitucion_de_ambito_muerde",
         "test_los_contadores_se_calculan_DESPUES_de_la_autorizacion"),
    ),
    Caso(
        "B4", "Los CONTADORES se calculan después de la autorización",
        # El defecto exacto de docs/73: contar sobre la base entera publica por
        # diferencia lo que la política acaba de ocultar.
        ROUTER,
        "            recuento = _jobs_counts(scope, workspace)",
        "            recuento = jobs_client.get_counts_by_status(workspace=workspace)",
        ("test_los_contadores_se_calculan_DESPUES_de_la_autorizacion",
         "test_el_recuento_por_estado_tambien_es_del_conjunto_visible"),
    ),
    Caso(
        "B5", "AUSENCIA != CERO: una cola no disponible no se pinta como 0",
        ROUTER,
        "    disponible = bool(estado_cola.get(\"ok\"))",
        "    disponible = True",
        ("test_una_cola_no_disponible_no_se_pinta_como_cero",),
    ),
    Caso(
        "B6", "Un estado de trabajo que el motor no reconoce NO se declara bueno",
        ROUTER,
        "    if vocabulario is None or not status:\n"
        "        return False\n"
        "    return status in vocabulario",
        "    return bool(status)",
        ("test_un_estado_de_trabajo_desconocido_no_se_declara_conocido",
         "test_sin_vocabulario_no_se_reconoce_ningun_estado"),
    ),
    Caso(
        "B7", "Vocabulario TRI-ESTADO: no poder leerlo no concede",
        ROUTER,
        "    if vocabulario is None or not status:\n"
        "        return False\n",
        "    if vocabulario is None:\n"
        "        return True\n"
        "    if not status:\n"
        "        return False\n",
        ("test_sin_vocabulario_no_se_reconoce_ningun_estado",),
    ),
    Caso(
        "B8", "Un estado de SALUD desconocido tampoco se pinta como bueno",
        ROUTER,
        "    return bool(status) and status in HEALTH_VALUES",
        "    return bool(status)",
        ("test_un_estado_de_salud_desconocido_no_se_pinta_como_bueno",
         "test_los_estados_de_salud_del_subsistema_si_se_reconocen"),
    ),
    Caso(
        "B9", "Un filtro de estado sin contrastar se rechaza (400), no revienta",
        ROUTER,
        "    if status is not None and not job_status_known(status, vocabulario):",
        "    if False:",
        ("test_un_filtro_de_estado_no_reconocido_se_rechaza_con_el_nombre_del_parametro",),
    ),
    Caso(
        "B10", "Un fallo de lectura da 503 SIN volcar rutas ni trazas",
        ROUTER,
        "                    error_detail=type(exc).__name__,",
        "                    error_detail=str(exc),",
        ("test_una_cola_que_revienta_da_503_sin_filtrar_rutas",),
    ),
    Caso(
        "B11", "SOLO LECTURA: el módulo no monta ningún método de escritura",
        ROUTER,
        "@router.get(\"\", response_class=HTMLResponse, name=SLOT.route_name)",
        "@router.post(\"/purgar\")\ndef _mutante_de_escritura():\n    return {\"ok\": True}\n\n\n"
        "@router.get(\"\", response_class=HTMLResponse, name=SLOT.route_name)",
        # OJO A LO QUE NO ESTÁ EN ESTA LISTA:
        # `test_los_metodos_de_escritura_son_rechazados_por_http` NO se pone
        # rojo con esta mutación, MEDIDO. Sondea sólo el prefijo raíz, y el
        # POST mutante cuelga de `/purgar`. Se deja fuera a propósito en vez de
        # apuntárselo: una comprobación que no caza el defecto no puede
        # cobrarse como la defensa que lo impide.
        ("test_el_panel_no_monta_ningun_metodo_de_escritura",
         "test_ninguna_ruta_del_espacio_del_panel_acepta_escritura"),
    ),
    Caso(
        "B12", "La frontera de solo lectura es del ESPACIO DE URL, no del módulo",
        # El defecto se inyecta DESDE FUERA del carril, que es como aparecería
        # de verdad: otro carril monta escritura bajo `/panel/operations` sin
        # tocar `chassis_operations.py`. La enumeración del propio router lo
        # daría por bueno.
        MAIN,
        "\n\n_mount_feature_slots()\n",
        "\n\n_mount_feature_slots()\n\n\n"
        "@app.post(\"/panel/operations/purgar\")\n"
        "def _mutante_de_escritura_externo():\n"
        "    return {\"ok\": True}\n",
        ("test_ninguna_ruta_del_espacio_del_panel_acepta_escritura",),
    ),
    Caso(
        "B13", "El panel LEE la salud, no la EJECUTA ni la escribe",
        ROUTER,
        "def _health_report() -> Optional[dict]:\n"
        "    return health_storage.load_last()",
        "def _health_report() -> Optional[dict]:\n"
        "    from app.health.models import HealthReport\n"
        "    health_storage.save_report(HealthReport())\n"
        "    return health_storage.load_last()",
        ("test_el_panel_no_ejecuta_healthchecks_ni_escribe_el_informe",),
    ),
    Caso(
        "B14", "`_fila` no puede emitir el texto de un error del servidor",
        ROUTER,
        "        \"has_error\": bool(job.get(\"has_error\") or job.get(\"error_code\")),",
        "        \"has_error\": bool(job.get(\"has_error\") or job.get(\"error_code\")),\n"
        "        \"error_message\": job.get(\"error_message\"),",
        ("test_el_detalle_operativo_se_recorta_a_quien_no_es_autoridad_plena",),
    ),
    Caso(
        "B15", "La plantilla resuelve por NOMBRE de ruta, no por URL literal",
        PLANTILLA,
        "action=\"{{ url_for('chassis_operations') }}\"",
        "action=\"/panel/operations\"",
        ("test_la_plantilla_no_lleva_urls_escritas_a_mano",),
    ),
    Caso(
        "B16", "La plantilla no ofrece ninguna acción de escritura",
        PLANTILLA,
        "<form method=\"get\"",
        "<form method=\"post\"",
        ("test_la_plantilla_no_ofrece_ningun_formulario_de_escritura",),
    ),
    Caso(
        "B17", "El techo de filas existe (una página sin techo materializa la cola)",
        ROUTER,
        "    limit: int = Query(default=DEFAULT_ROWS, ge=1, le=MAX_ROWS),",
        "    limit: int = Query(default=DEFAULT_ROWS, ge=1),",
        ("test_el_techo_de_filas_tiene_maximo",),
    ),
    Caso(
        "B18", "Calibración DEL INSTRUMENTO: el suelo caza un censo que no aplana",
        # Un barrido de primer nivel sobre `app.routes` ve CERO rutas de este
        # prefijo (FastAPI mete los routers incluidos en envoltorios
        # `_IncludedRouter`), y entonces B12 saldría verde por no mirar. El
        # suelo tiene que cazarlo, y B12 no puede.
        FICHERO_SUITE,
        "    return [r for r in iter_mounted_routes(app) if route_in_prefix(r, SLOT.prefix)]",
        "    return [r for r in app.routes if route_in_prefix(r, SLOT.prefix)]",
        ("test_la_enumeracion_del_espacio_del_panel_no_puede_salir_vacia",),
    ),
    Caso(
        # FALSO POSITIVO, no falso negativo: la calibración tiene que exigir
        # también que el gate NO acuse a quien no es suyo. B y F/G tienen
        # prefijos vecinos, y un rojo por el motivo equivocado entrena a
        # ignorar el gate.
        "B19", "El gate de B no acusa a un vecino de prefijo",
        FICHERO_SUITE,
        "    return [r for r in iter_mounted_routes(app) if route_in_prefix(r, SLOT.prefix)]",
        "    return [r for r in iter_mounted_routes(app)\n"
        "            if str(getattr(r, \"path\", \"\")).startswith(SLOT.prefix)]",
        ("test_el_gate_no_acusa_a_un_vecino_de_prefijo",),
    ),
    Caso(
        # Contrapeso del anterior: si la pertenencia se apagara del todo, B19
        # seguiría verde mientras el gate deja de mirar.
        "B20", "…y el contrapeso: el gate SÍ reclama lo que es suyo",
        FICHERO_SUITE,
        "    return [r for r in iter_mounted_routes(app) if route_in_prefix(r, SLOT.prefix)]",
        "    return [r for r in iter_mounted_routes(app) if False and route_in_prefix(r, SLOT.prefix)]",
        ("test_el_gate_si_reclama_lo_que_es_suyo",
         "test_la_enumeracion_del_espacio_del_panel_no_puede_salir_vacia"),
    ),
    Caso(
        # O2 de la revisión independiente. FALSO NEGATIVO MEDIDO EN VERDE: con
        # esta mutación —clase CSS fija de "estado bueno", dejando honesto el
        # `data-status-known`— la suite entera salía 48 passed. Los tests
        # miraban el atributo `data-*` y el texto, y nadie calibraba LA CLASE,
        # que es justamente "el aspecto" del que habla la doctrina.
        "B22", "Un estado desconocido tampoco se pinta con el ASPECTO de bueno",
        PLANTILLA,
        "                  class=\"{{ 'status-known' if row.status_known else 'status-unknown' }}\">",
        "                  class=\"status-known\">",
        ("test_un_estado_desconocido_no_se_pinta_con_el_aspecto_de_bueno",),
    ),
    Caso(
        # O3 de la revisión independiente. FALSO NEGATIVO MEDIDO EN VERDE: la
        # doctrina "ausencia != cero" sólo estaba calibrada a nivel de SECCIÓN
        # (B5, cola no disponible), no a nivel de CAMPO de fila.
        "B23", "AUSENCIA != CERO también campo a campo, no sólo por sección",
        ROUTER,
        "        \"attempts\": job.get(\"attempts\"),",
        "        \"attempts\": job.get(\"attempts\") or 0,",
        ("test_un_campo_ausente_no_se_convierte_en_cero",),
    ),
    Caso(
        "B21", "Con la auth desactivada el panel NO se sirve (mitad A del control)",
        ROUTER,
        "    user=Depends(slot_guard(SLOT)),",
        "    user=Depends(__import__(\"app.routers.readonly\", fromlist=[\"x\"])\n"
        "                 .html_role_guard(SLOT.role)),",
        ("test_sin_auth_no_reaparece_el_comportamiento_permisivo",),
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
    rojos = sorted(set(re.findall(r"^(?:FAILED|ERROR) [^:]+::([\w\[\]\-.]+)", salida, re.M)))
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
