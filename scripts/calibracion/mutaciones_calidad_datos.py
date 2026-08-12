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

    python3 scripts/calibracion/mutaciones_calidad_datos.py

Lo ejecuta el job `Calibracion de gates` de CI, al lado de
`.github/scripts/calibra_gate_integrity.py`. Vivia en la raiz del repositorio
--donde hay precedente, `mutaciones.py`-- pero alli NINGUN job lo ejecutaba, y
un arnes de calibracion que nadie corre se pudre en silencio: la calibracion
pasa a ser la foto de un dia en vez de una propiedad del arbol.

Cada mutacion revierte siempre lo que toca, aun si pytest falla o se
interrumpe. Los objetivos van acotados a proposito: lo que se mide es que EXISTE
un test concreto que se pone rojo, no que la suite entera se entere.
"""
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
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

    # --- 4. N3: dos modulos frontera, UN solo objeto Enum
    ("J16 los dos modulos frontera dejan de compartir la entrada de "
     "`sys.modules` (el contrato se carga DOS veces: dos clases ReviewStatus)",
     V / "app/review_status_contract.py",
     '_MODULE_NAME = "s9k_review_status_v1_model"',
     '_MODULE_NAME = "s9k_review_status_v1_model_visor"',
     # Objetivo acotado AL TESTIGO. Con el fichero entero y `-x`, el primer
     # rojo que aparece es otro: `pytest.raises(RS.ReviewStatusError)` deja de
     # atrapar la excepcion porque hay DOS clases de error --precisamente el
     # "revienta lejos de aqui, en el consumidor" que anuncia el docstring del
     # testigo--. Es un rojo legitimo, pero no es la razon declarada de J16, y
     # el arnes ya no acepta rojos ajenos.
     V, [CAL + "::test_los_dos_modulos_frontera_exponen_EL_MISMO_objeto_Enum"]),

    # --- 5. La SEGUNDA VIA a la potestad de bypass total (docs/66 §1)
    #
    # `authz/scope.py:131` es un productor de la misma potestad que
    # `admin_full`, en un modulo que la red inversa no barre. La revision
    # independiente lo midio con el metodo de este mismo arnes --mutar de forma
    # transitoria y revertir-- y encontro que era un SUPERVIVIENTE REAL: los
    # 1091 tests del visor seguian VERDES con la linea mutada, mientras que sus
    # dos hermanos (`context.py:88` y `context.py:100`) SI estan medidos.
    #
    # Yo habia declarado que medir los tres productores exigia tocar `authz/**`,
    # zona prohibida, y por eso no los media. Eran DOS VARAS: este arnes ya muta
    # `policies/**`, prohibida por el mismo criterio, y revierte. El testigo que
    # cierra esta via se ha escrito FUERA de la zona prohibida (un test), que es
    # lo unico que este carril tiene permitido anadir.
    ("J18 el detalle operativo se concede a CUALQUIERA "
     "(segunda via a la potestad de bypass total, fuera del barrido)",
     V / "app/authz/scope.py",
     '        return bool(self.ctx.admin_full) or self.ctx.role == "admin"',
     '        return True',
     V, [CAL]),

    ("J19 el detalle operativo deja de leer `admin_full` "
     "(la via equivalente sobrevive al campo, y en la direccion contraria)",
     V / "app/authz/scope.py",
     '        return bool(self.ctx.admin_full) or self.ctx.role == "admin"',
     '        return self.ctx.role == "admin"',
     V, [CAL]),
]

#: Mutaciones que tocan VARIOS ficheros a la vez.
MUTACIONES_COORDINADAS = [

    # R8. El escenario exacto que el revisor uso para demostrar que la
    # cuarentena NO frenaba: se anade al motor una dimension de bypass total
    # NUEVA y se mete su nombre en la cuarentena en el mismo commit. Con la
    # comprobacion anterior --`CUARENTENA - sin_declarar`, que solo caza
    # entradas rancias-- esto daba 92 passed en verde. Es la calibracion mas
    # importante del fichero: mide el freno, no la barrera.
    ("R8 se anade al motor una dimension de bypass total NUEVA y se mete en la "
     "cuarentena en el mismo commit (el escenario que salia verde)",
     [
         (V / "app/policies/models.py",
          "    simulated: bool = False",
          "    simulated: bool = False\n    superpoder_nuevo: bool = False"),
         (V / "app/policies/engine.py",
          "        # 1. Bypass total de administrador.\n        if ctx.admin_full:",
          "        # 1. Bypass total de administrador.\n        if ctx.admin_full or ctx.superpoder_nuevo:"),
         (V / "tests/test_provider_authz_fields_contract.py",
          '    "character_knowledge",\n})\n\n#: CONGELADO.',
          '    "character_knowledge",\n    "superpoder_nuevo",\n})\n\n#: CONGELADO.'),
     ],
     V, [CONTRATO]),

    # Control: la misma dimension nueva SIN meterla en la cuarentena tiene que
    # ponerse roja tambien (esa parte ya funcionaba, y debe seguir haciendolo).
    ("R8-control una dimension de bypass total nueva SIN meterla en la "
     "cuarentena",
     [
         (V / "app/policies/models.py",
          "    simulated: bool = False",
          "    simulated: bool = False\n    superpoder_nuevo: bool = False"),
         (V / "app/policies/engine.py",
          "        # 1. Bypass total de administrador.\n        if ctx.admin_full:",
          "        # 1. Bypass total de administrador.\n        if ctx.admin_full or ctx.superpoder_nuevo:"),
     ],
     V, [CONTRATO]),

    # J17. DOS ediciones sobre el MISMO fichero. Existe por dos razones: la
    # afirmacion que mide (un quinto valor que ademas se autoconcede credito de
    # revision humana no puede pasar) y, sobre todo, porque es el caso que el
    # arnes NO SABIA EJECUTAR: hasta el arreglo de encadenado, cada edicion se
    # escribia desde el texto pristino y la segunda BORRABA a la primera, de
    # modo que aqui solo habria llegado a existir la ampliacion de
    # `HUMAN_REVIEWED` --que sin el miembro nuevo revienta con un AttributeError
    # al importar--. El rojo habria sido real y por una razon completamente
    # distinta de la declarada; con las ediciones al reves, habria sido VERDE.
    ("J17 se anade un QUINTO valor al vocabulario Y se le concede credito de "
     "revision humana en el mismo commit (dos ediciones, un solo fichero)",
     [
         (RAIZ / "contracts/review-status/v1/model.py",
          '    CORRECTED = "corrected"',
          '    CORRECTED = "corrected"\n    MACHINE_APPROVED = "auto_approved"'),
         (RAIZ / "contracts/review-status/v1/model.py",
          "    {ReviewStatus.REVIEWED.value, ReviewStatus.CORRECTED.value}",
          "    {ReviewStatus.REVIEWED.value, ReviewStatus.CORRECTED.value,\n"
          "     ReviewStatus.MACHINE_APPROVED.value}"),
     ],
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


#: RAZON DECLARADA DE CADA MUTACION. Sin esto el arnes acepta como ROJO
#: legitimo CUALQUIER rc != 0, y eso no es lo mismo que "el guardian declarado
#: se ha puesto rojo". Medido: una mutacion que solo rompe la SINTAXIS del
#: fichero (`CORRECTED = ((("corrected"`) --que no viola ningun invariante de
#: este carril-- salia [ROJO] y la corrida entera "CALIBRACION COMPLETA", con
#: firma indistinguible (`1 error`) de la de J9/J10/J17.
#:
#: Cada entrada es un fragmento que TIENE que aparecer en la salida de pytest
#: (sin codigos ANSI) para que el rojo cuente. Toda mutacion debe declarar la
#: suya: la que no la declare detiene el arnes.
RAZONES = {
    "J1": "ha dejado de transportar 'known_from_session_BORRADA'",
    "J2": "el motor decide con ['max_visible_session'] y el registro ejecutable "
          "no las declara",
    "J3": "aplican solo a nodo o solo a relacion",
    "J4": "el motor consulta ['partida_id'] y el registro ejecutable NO lo declara",
    "J5": "declara su ausencia como NEUTRA y el motor deniega",
    "J6": "'scope' esta declarado missing=DENY en el registro y el motor deja pasar",
    "J7": "'workspace' esta declarado missing=DENY en el registro y el motor deja pasar",
    "J8": "test_un_tope_de_sesion_ilegible_no_significa_sin_tope",
    "J9": "RuntimeError: review-status/v1 declara estados sin traducci",
    "J10": "AttributeError: type object 'ReviewStatus' has no attribute 'CORRECTED'",
    "J11": "test_un_valor_fuera_del_vocabulario_canonico_se_rechaza",
    "J12": "assert 'reviewed' == 'auto_extracted'",
    "J13": "el adaptador no traduce ['DEFERRED']",
    "J14": "assert ('approved' == 'reviewed'",
    "J15b": "NO fue rechazado por la validacion de procedencia de escritura",
    "J16": "exponen DOS clases `ReviewStatus` distintas",
    # J18/J19: el testigo de `sees_operational_detail`, la SEGUNDA VIA a la
    # potestad de bypass total (ver docs/66 §1). El testigo vive fuera de
    # `authz/**`, que es zona prohibida para este carril.
    "J18": "concede el detalle operativo a quien NO es admin",
    "J19": "deja de conceder el detalle operativo a `admin_full`",
    "R8": "la cuarentena ha CRECIDO con ['superpoder_nuevo'] sin autorizacion",
    "R8-control": "el motor decide con ['superpoder_nuevo'] y el registro "
                  "ejecutable no las declara",
    # OJO: J17 comparte razon con J9 a proposito, y eso es un LIMITE, no un
    # descuido. Su afirmacion propia --un quinto valor que ademas se autoconcede
    # credito de revision humana-- no llega a evaluarse: el fichero ni siquiera
    # colecciona, porque el guardian de traducciones de J9 salta antes. J17
    # existe sobre todo por el encadenado de ediciones (ver su comentario).
    "J17": "RuntimeError: review-status/v1 declara estados sin traducci",
}

#: SUELO DE AFIRMACIONES DISTINTAS. Sin esto el arnes PASA EN VACIO: si alguien
#: vacia `MUTACIONES`, `fallos` queda vacio, se imprime "CALIBRACION COMPLETA:
#: 0/0" y CI da rc=0. Un instrumento que se pone verde cuando se le quitan todas
#: las mediciones no mide nada: mide su propio silencio.
#:
#: El suelo cuenta AFIRMACIONES DISTINTAS --identidad = el conjunto de ediciones
#: que introduce la mutacion--, no elementos de lista. Contar entradas era la
#: misma confusion FILAS/IDENTIDADES que inflaba el recuento de checks de CI:
#: medido, `MUTACIONES = [J11] * 19` daba "CALIBRACION COMPLETA: 19/19" y rc=0
#: con UNA sola afirmacion medida diecinueve veces.
#:
#: Subirlo al anadir mutaciones es deliberado; bajarlo exige justificarlo en la
#: revision.
MINIMO_MUTACIONES = 21


def _normalizadas():
    """Unifica mutaciones de UN fichero y de VARIOS en una sola forma.

    `(etiqueta, [(fichero, original, mutado), ...], cwd, objetivos)`. Hacen
    falta las de varios ficheros porque el escenario que descubrio el revisor
    --anadir una dimension al motor Y meterla en la cuarentena en el mismo
    commit-- es, por definicion, un cambio coordinado: mutar un solo fichero no
    lo reproduce.
    """
    for etiqueta, fichero, original, mutado, cwd, objetivos in MUTACIONES:
        yield etiqueta, [(fichero, original, mutado)], cwd, objetivos
    for etiqueta, ediciones, cwd, objetivos in MUTACIONES_COORDINADAS:
        yield etiqueta, ediciones, cwd, objetivos


def _identidad(ediciones):
    """AFIRMACION distinta: el conjunto de ediciones que introduce la mutacion.

    No la etiqueta (se puede copiar y retocar) ni la posicion en la lista (son
    filas). Dos entradas con las mismas ediciones miden lo mismo dos veces.
    """
    return tuple(sorted((str(f), o, mu) for f, o, mu in ediciones))


def _codigo(etiqueta):
    """`J15b la via humana...` -> `J15b`. Es la clave de `RAZONES`."""
    return etiqueta.split()[0]


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _salida(r):
    return _ANSI.sub("", r.stdout + r.stderr)


def _pytest(cwd, objetivos):
    return subprocess.run(
        [sys.executable, "-m", "pytest", *objetivos, "-q", "--no-header", "-x"],
        cwd=cwd, capture_output=True, text=True,
    )


def main() -> int:
    print("=" * 78)
    print("CALIBRACION DEL CARRIL J -- cada afirmacion debe poder ponerse ROJA")
    print("=" * 78)

    _filas = [(e, ed) for e, ed, _, _ in _normalizadas()]
    _total = len(_filas)
    _identidades = {_identidad(ed) for _, ed in _filas}

    # Antes de gastar minutos en la linea base: el arnes no puede pasar en
    # vacio ni por repeticion. Ver `MINIMO_MUTACIONES`.
    #
    # `raise SystemExit`, no `assert`: con `python -O` (o `PYTHONOPTIMIZE=1`)
    # los `assert` se compilan a nada y el suelo desaparecia. Medido: el arnes
    # anterior con `python3 -O` y las listas vacias imprimia "CALIBRACION
    # COMPLETA: 0/0" y devolvia rc=0. Hoy el unico invocador es `ci.yml` con
    # `python3` plano, asi que el riesgo estaba acotado; el arreglo es de una
    # linea y no depende de que ese invocador no cambie nunca.
    if len(_identidades) < MINIMO_MUTACIONES:
        raise SystemExit(
            f"el arnes declara {_total} filas / {len(_identidades)} afirmaciones "
            f"DISTINTAS y el suelo son {MINIMO_MUTACIONES}: vaciar la bateria, "
            f"adelgazarla o rellenarla con copias de la misma mutacion NO puede "
            f"salir en verde"
        )
    _sin_razon = sorted({_codigo(e) for e, _ in _filas} - set(RAZONES))
    if _sin_razon:
        raise SystemExit(
            f"mutaciones sin razon declarada en RAZONES: {_sin_razon}. Sin razon "
            f"declarada, cualquier rc != 0 pasaria por rojo legitimo"
        )
    if _total != len(_identidades):
        print(f"\n!! {_total} filas para {len(_identidades)} afirmaciones distintas")
    print(
        f"\nAfirmaciones distintas: {len(_identidades)} "
        f"(filas: {_total}; suelo: {MINIMO_MUTACIONES})."
    )

    base = {}
    _combis = [(c, o) for _, _, c, o in _normalizadas()]
    _combis += [(m[4], m[5]) for m in SUPERVIVIENTES]
    for cwd, objetivos in _combis:
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
    for etiqueta, ediciones, cwd, objetivos in _normalizadas():
        # `originales` guarda el texto PRISTINO (para revertir) y `acumulado`
        # el texto que se va construyendo edicion a edicion. Antes ambas cosas
        # eran la misma: cada edicion se escribia como
        # `pristino.replace(...)`, de modo que DOS ediciones sobre el MISMO
        # fichero se pisaban y solo sobrevivia la ultima. La mutacion
        # coordinada parecia aplicarse entera y en realidad se aplicaba a
        # medias: si el resultado salia rojo, lo hacia por una razon distinta
        # de la declarada, y si salia verde no se sabia si era porque la
        # afirmacion no esta medida o porque la mutacion nunca llego a existir.
        # Ahora cada edicion parte del estado acumulado y todas sobreviven.
        originales = {}
        acumulado = {}
        problema = None
        for fichero, original, mutado in ediciones:
            if fichero not in originales:
                originales[fichero] = fichero.read_text(encoding="utf-8")
                acumulado[fichero] = originales[fichero]
            texto = acumulado[fichero]
            if texto.count(original) != 1:
                problema = (
                    f"patron {'ausente' if original not in texto else 'ambiguo'} "
                    f"en {fichero.name}"
                )
                break
            # Encadenado: la siguiente edicion vera esta ya aplicada. Ademas,
            # el patron de la segunda edicion se busca sobre el texto ya
            # mutado, que es lo unico que permite encadenar ediciones que
            # dependen del resultado de la anterior.
            acumulado[fichero] = texto.replace(original, mutado, 1)

        if problema:
            print(f"[SALTADA] {etiqueta}\n           {problema}")
            fallos.append(f"{etiqueta}  ({problema})")
            continue

        try:
            for fichero, texto in acumulado.items():
                fichero.write_text(texto, encoding="utf-8")
            r = _pytest(cwd, objetivos)
        finally:
            for fichero, texto in originales.items():
                fichero.write_text(texto, encoding="utf-8")

        # Rojo POR LA RAZON DECLARADA, no rojo por cualquier motivo. `rc != 0`
        # a secas cuenta como medida un fallo que no tiene nada que ver con la
        # afirmacion: una mutacion que solo rompa la sintaxis del fichero
        # tumbaba la coleccion de pytest y se anotaba como ROJO legitimo, con
        # firma indistinguible (`1 error`) de la de J9/J10/J17.
        razon = RAZONES[_codigo(etiqueta)]
        salida = _salida(r)
        rojo = r.returncode != 0 and razon in salida
        rojo_ajeno = r.returncode != 0 and razon not in salida

        print(f"[{'ROJO  ' if rojo else 'VERDE!'}] {etiqueta}")
        if rojo:
            linea = [ln for ln in r.stdout.splitlines() if "FAILED" in ln or " Error" in ln]
            for ln in linea[:2]:
                print(f"           {ln.strip()[:150]}")
            if not linea:
                print(f"           {r.stdout.strip().splitlines()[-1][:150]}")
        elif rojo_ajeno:
            fallos.append(etiqueta + "  (rojo por un motivo AJENO al declarado)")
            print("           ROJO, PERO NO POR LA RAZON DECLARADA. Esperaba")
            print(f"           encontrar: {razon[:120]}")
            for ln in salida.strip().splitlines()[-3:]:
                print(f"           | {ln.strip()[:140]}")
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
        if texto.count(original) != 1:
            # `raise SystemExit`, no `assert`: ver el comentario del suelo.
            raise SystemExit(f"patron ambiguo/ausente en {fichero}")
        fichero.write_text(texto.replace(original, mutado, 1), encoding="utf-8")
        try:
            r = _pytest(cwd, objetivos)
        finally:
            fichero.write_text(texto, encoding="utf-8")
        if r.returncode:
            # Y AHORA SE PONE ROJA LA CORRIDA. Antes esto se imprimia y se
            # seguia con rc=0: un superviviente que deja de sobrevivir es una
            # explicacion CADUCADA en el arbol, y CI la daba por buena.
            estado = "ROJO (la explicacion ya no vale)"
            fallos.append(
                etiqueta + "  (superviviente declarado que YA NO sobrevive: "
                "la explicacion ha caducado y hay que reescribirla)"
            )
        else:
            estado = "VERDE, como se documenta"
        print(f"[{estado}] {etiqueta}\n           motivo: {motivo}")

    print("\n" + "=" * 78)
    if fallos:
        print(f"CALIBRACION INCOMPLETA: {len(fallos)} problema(s) sobre "
              f"{_total} filas / {len(_identidades)} afirmaciones distintas")
        for f in fallos:
            print(f"  - {f}")
        return 1
    print(
        f"CALIBRACION COMPLETA: {len(_identidades)}/{len(_identidades)} "
        f"afirmaciones distintas, rojo por la razon declarada -> revert -> verde"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
