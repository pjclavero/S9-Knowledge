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

import atexit
import hashlib
import re
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

#: Ficheros mutados AHORA MISMO, con su contenido original. Existe por un
#: incidente real: este guion se mató a mitad de una ejecución larga y el
#: `finally` de restauración NO llegó a correr, así que la mutación de un caso
#: (la del gate de prefijo, sobre la propia suite) se quedó en el árbol. La
#: siguiente medición se hizo sobre un árbol contaminado y dio un rojo que no
#: era del producto. Una calibración que puede dejar el árbol sucio al morir es
#: una fuente de mediciones falsas, así que la restauración se registra también
#: en `atexit` y en las señales de terminación.
_EN_VUELO: dict[Path, str] = {}


def _restaurar_todo(*_args) -> None:
    for ruta, contenido in list(_EN_VUELO.items()):
        try:
            ruta.write_text(contenido, encoding="utf-8")
        finally:
            _EN_VUELO.pop(ruta, None)


atexit.register(_restaurar_todo)
for _sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    try:
        signal.signal(_sig, lambda s, f: (_restaurar_todo(), sys.exit(128 + s)))
    except (ValueError, OSError):  # pragma: no cover - entorno sin esa señal
        pass

RAIZ = Path(__file__).resolve().parent.parent
VIEWER = RAIZ / "viewer"
ROUTER = VIEWER / "app" / "routers" / "chassis_entities.py"
PLANTILLA = VIEWER / "app" / "templates" / "chassis" / "entities.html"
PLANTILLA_FICHA = VIEWER / "app" / "templates" / "chassis" / "entities_item.html"
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
    #: Rojos COLATERALES medidos: pruebas ajenas al subconjunto declarado que la
    #: mutación también tumba. Se declaran una a una y se exige que la medida
    #: coincida EXACTAMENTE. Ver `medir_colaterales` y la nota de abajo.
    colaterales: tuple[str, ...] = ()


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
        # El contrato del chasis vigila el mismo interruptor para los cuatro
        # huecos: defensa en profundidad, no defecto.
        colaterales=("test_slot_is_off_when_flag_is_absent",),
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
        # La misma propiedad, afirmada por el chasis sobre los cuatro huecos.
        colaterales=("test_disabled_slots_are_not_enumerable_by_an_anonymous",),
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
        # SEIS colaterales, y son la mejor noticia de esta tabla: leer por el
        # proveedor crudo no rompe una comprobación, rompe SEIS más, cada una
        # por su propio motivo (el aislamiento entre partidas, la
        # indistinguibilidad, las relaciones del otro extremo, los contadores).
        # Eso es defensa en profundidad, no un defecto — pero es justo lo que el
        # arnés con `-k` NO podía ver, y por lo que la afirmación anterior
        # («ningún rojo fuera de los declarados») estaba sobrevendida.
        colaterales=(
            "test_barrer_el_tope_de_pagina_no_mueve_el_total",
            "test_el_cuerpo_del_404_no_nombra_la_entidad_pedida",
            "test_la_ficha_no_revela_relaciones_hacia_lo_que_no_se_ve",
            "test_no_autorizado_e_inexistente_dan_EL_MISMO_404",
            "test_un_panel_vacio_para_un_anonimo_es_correcto",
            "test_una_partida_activa_abre_su_material_y_solo_el_suyo",
        ),
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
        # El contador crudo delata material que la política oculta, así que la
        # prueba del P0 también se entera.
        colaterales=("test_sin_auth_no_reaparece_el_comportamiento_permisivo",),
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
        # El barrido de autorización del chasis ve la ruta nueva sin guarda.
        colaterales=("test_no_mounted_route_serves_200_to_anonymous",),
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
        colaterales=("test_no_mounted_route_serves_200_to_anonymous",),
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
        colaterales=("test_no_mounted_route_serves_200_to_anonymous",),
    ),
    Caso(
        "G11", "MODO DE FALLO DEL INSTRUMENTO: si la enumeración deja de "
               "aplanar, ve CERO rutas y «demostraría» cualquier cosa",
        FICHERO_SUITE,
        "    return [r for r in iter_mounted_routes(app) if route_in_prefix(r, SLOT.prefix)]",
        "    return [r for r in app.routes if route_in_prefix(r, SLOT.prefix)]",
        ("test_la_enumeracion_del_espacio_del_panel_no_puede_salir_vacia",),
        # Con el censo ciego, la frontera de escritura tampoco puede afirmarse:
        # se pone roja por no ver nada, que es el modo de fallo correcto.
        colaterales=("test_ninguna_ruta_del_espacio_del_panel_acepta_escritura",),
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
        # HERMANA DEL SUELO AUTOCUMPLIDO, señalada por la revisión independiente.
        # El bucle `for f in formularios` no ejecuta NADA si no hay formularios,
        # y hoy `entities_item.html` tiene cero. Medido antes del arreglo:
        # convirtiendo también el formulario de filtros en un `<div>`, la
        # comprobación entera quedaba vacía y pasaba en VERDE. Este caso inyecta
        # justo eso y exige que el control de ejercicio se entere.
        "G19", "El bucle de formularios ha EJERCIDO algo "
               "(la comprobación no se cumple sola con cero formularios)",
        PLANTILLA,
        "    <form method=\"get\" action=\"{{ url_for('chassis_entities') }}\" class=\"panel\" data-role=\"filtros\">",
        "    <div class=\"panel\" data-role=\"filtros\">",
        ("test_las_plantillas_no_ofrecen_ninguna_accion_de_escritura",),
    ),
    Caso(
        # La otra banda: que el bucle SÍ muerda en la plantilla que hoy no tiene
        # formularios, el día que tenga uno. Sin este caso, el control de
        # ejercicio podría satisfacerse siempre con el formulario de la lista
        # mientras la ficha quedara sin vigilar.
        "G20", "El bucle vigila TAMBIÉN la plantilla de la ficha",
        PLANTILLA_FICHA,
        "    <p><a href=\"{{ url_for('chassis_entities') }}\">Volver al listado</a></p>",
        "    <form method=\"post\" action=\"/x\"><button>Aplicar</button></form>",
        ("test_las_plantillas_no_ofrecen_ninguna_accion_de_escritura",),
    ),
    Caso(
        # CALIBRACIÓN DEL CONTROL POSITIVO, no de una garantía del producto.
        # `test_un_contador_no_aparece_antes_de_autorizar` tiene una mitad que
        # es cierta por construcción —un 302 no tiene cuerpo, luego no tiene
        # contadores— y pasaría con los contadores borrados del producto. Este
        # caso los borra y exige que la prueba se entere: si no se pone roja,
        # ese suelo se estaba cumpliendo solo.
        "G18", "El control positivo de los contadores MUERDE "
               "(la mitad negativa no se cumple sola)",
        PLANTILLA,
        "    <section class=\"panel\" data-role=\"contadores\">\n"
        "      <span data-count=\"visible\">{{ listado.autorizadas }}</span> visibles ·\n"
        "      <span data-count=\"filtered\">{{ listado.total }}</span> tras filtros ·\n"
        "      <span data-count=\"shown\">{{ listado.mostradas }}</span> en esta página\n"
        "    </section>",
        "    <section class=\"panel\" data-role=\"contadores\"></section>",
        ("test_un_contador_no_aparece_antes_de_autorizar",
         "test_los_contadores_son_del_conjunto_autorizado",
         "test_barrer_el_tope_de_pagina_no_mueve_el_total",
         "test_un_panel_vacio_para_un_anonimo_es_correcto",
         "test_sin_auth_no_reaparece_el_comportamiento_permisivo"),
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


def correr_todo() -> tuple[bool, set[str], str]:
    """Ejecuta la suite ENTERA del visor y devuelve TODOS los nombres en rojo.

    POR QUÉ EXISTE, y es una corrección de una afirmación previa. Este guion
    decía «ningún rojo fuera de los tests declarados», y **no podía saberlo**:
    con `-k` sólo ejecuta el subconjunto declarado, así que nunca veía el resto
    de la suite bajo mutación. La frase prometía lo que el instrumento no medía
    — la revisión independiente lo señaló y midió el contraejemplo: **G3
    produce 6 rojos fuera de lo declarado**, todos semánticamente correctos
    (defensa en profundidad), pero invisibles para este arnés.

    Ahora se mide de verdad: cada mutación corre además contra la suite completa
    y los colaterales se declaran caso a caso. Cuesta ~50 s por caso, y ese es
    el precio de poder afirmarlo.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q", "--no-header",
         "-p", "no:cacheprovider", "--tb=no", "-rf", "--color=no"],
        cwd=VIEWER, capture_output=True, text=True,
    )
    salida = proc.stdout + proc.stderr
    if " no tests ran" in salida or "collected 0 items" in salida:
        return False, {"0 TESTS RECOLECTADOS (arnés roto)"}, "0 recolectados"
    rojos = {r.split("[")[0]
             for r in re.findall(r"^FAILED [^:]+::([\w\[\]\-.]+)", salida, re.M)}
    ultima = salida.strip().splitlines()[-1] if salida.strip() else ""
    return proc.returncode == 0, rojos, ultima


def main() -> int:
    fallos: list[str] = []
    #: Con `--sin-colaterales` se salta la medida de la suite completa (rápido,
    #: pero entonces NO se puede afirmar nada sobre los colaterales).
    medir_colaterales = "--sin-colaterales" not in sys.argv

    if medir_colaterales:
        print("Midiendo la línea base de la suite COMPLETA (sin mutar)…")
        base_todo_verde, base_rojos, base_detalle = correr_todo()
        if not base_todo_verde:
            print(f"  FALLO: la suite completa YA está roja sin mutar: "
                  f"{sorted(base_rojos)} ({base_detalle})")
            return 1
        print(f"  línea base VERDE — {base_detalle}\n")

    print(f"{'caso':<6} {'base':<8} {'mutado':<8} {'reversión':<11} "
          f"{'colat.':<7} garantía")
    print("-" * 118)
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

        _EN_VUELO[caso.fichero] = original
        caso.fichero.write_text(original.replace(caso.de, caso.a), encoding="utf-8")
        try:
            mutado_verde, rojos, detalle = correr(caso.tests, caso.suite)
            colaterales_medidos: set[str] = set()
            if medir_colaterales:
                _, todos_los_rojos, _ = correr_todo()
                colaterales_medidos = todos_los_rojos - set(caso.tests)
        finally:
            caso.fichero.write_text(original, encoding="utf-8")
            _EN_VUELO.pop(caso.fichero, None)
        despues = sha(caso.fichero)

        reversion = antes == despues
        col = (str(len(colaterales_medidos)) if medir_colaterales else "—")
        print(f"{caso.id:<6} {('VERDE' if base_verde else 'ROJO'):<8} "
              f"{('ROJO' if not mutado_verde else 'VERDE'):<8} "
              f"{('idéntica' if reversion else 'DISTINTA'):<11} {col:<7} {caso.garantia}")
        if not mutado_verde:
            print(f"{'':<6} rojos: {', '.join(sorted({r.split('[')[0] for r in rojos}))}")
        if medir_colaterales and colaterales_medidos:
            print(f"{'':<6} colaterales: {', '.join(sorted(colaterales_medidos))}")
        ajenos = sorted({r.split('[')[0] for r in rojos} - set(caso.tests))
        if ajenos:
            fallos.append(f"{caso.id}: rojo por el motivo equivocado, en {ajenos}")
        # Los colaterales NO son un defecto —suelen ser defensa en profundidad—
        # pero tienen que estar DECLARADOS: una lista que no coincide con la
        # medida significa que el efecto de la mutación cambió sin que nadie lo
        # note, y eso es exactamente lo que este guion existe para impedir.
        if medir_colaterales and colaterales_medidos != set(caso.colaterales):
            sobran = sorted(colaterales_medidos - set(caso.colaterales))
            faltan = sorted(set(caso.colaterales) - colaterales_medidos)
            fallos.append(
                f"{caso.id}: los colaterales medidos no son los declarados "
                f"(sin declarar: {sobran}; declarados y no observados: {faltan})"
            )
        if not base_verde:
            fallos.append(f"{caso.id}: rojo YA sin mutar ({detalle_base})")
        if mutado_verde:
            fallos.append(f"{caso.id}: la mutación NO se detecta — la garantía no muerde")
        if not reversion:
            fallos.append(f"{caso.id}: la reversión no es byte a byte")

    print("-" * 118)
    if fallos:
        for f in fallos:
            print(f"  FALLO: {f}")
        return 1
    cola = (" y colaterales medidos sobre la suite COMPLETA, uno a uno"
            if medir_colaterales else
            " (colaterales NO medidos: se ejecutó con --sin-colaterales)")
    print(f"{len(CASOS)}/{len(CASOS)} garantías calibradas: verdes sin mutar, "
          f"rojas con el defecto, reversión idéntica por hash{cola}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
