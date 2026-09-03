# -*- coding: utf-8 -*-
"""DEUDA DECLARADA del carril 5 (V3.1). No es documentacion suelta: este modulo
lo importa `test_carril5_exception_codes.py`, asi que mentir aqui pone rojo.

Cifra total sobre la base del carril (`aaf9695`, ambito `data-engine/app/tests`,
ejecucion completa del detector entregado en
`data-engine/tools/carril5_inventario.py`, no muestra): **177** comprobaciones
por subcadena con el detector ESTRICTO (`match=` en `pytest.raises`: 127;
`"lit" in str(...)`: 50). Cota superior con el detector AMPLIO: 345.

Convertidas en este carril: **52** — que son EXACTAMENTE todas las que viven
en los 5 ficheros que sostienen garantias RC (medido: 52 de 52, no una muestra),
sobre **6** modulos de producto y **71** puntos de `raise` sellados con codigo.

NINGUNA de estas cifras esta escrita a mano: todas se vuelven a medir en
`test_carril5_exception_codes.py`. La entrega anterior solo fijaba por censo
`SITIOS_SELLADOS`; el resto eran parametros libres y se pudo demostrar que
declarar `SIN_ANCLA_MEDIDA = 0` dejaba la suite verde.

Criterio de INCLUSION (regla del operador: si una mutacion puede destruir una
propiedad declarada para el RC y todos los instrumentos siguen verdes, es
bloqueante):
  - ledger: unicidad, identidad logica, append-only, cadena de custodia,
    monotonia del tiempo de transaccion, supersesion y transiciones legales;
  - writer seguro: NO-ESCRITURA (guardas de entorno, dry-run, preflight,
    anti-TOCTOU, procedencia, idempotencia);
  - supersesion revisada: fail-closed (checksums, esquema, traversal, symlink,
    Unicode peligroso, segunda supersesion conflictiva).

Criterio de EXCLUSION (las 125 ESTRICTAS que quedan vivas, mas las que solo ve
la cota AMPLIA): NO sostienen una garantia RC. Por familias, con el motivo --y
con el recuento DERIVADO, no escrito a mano (`deuda_por_familia()`).

OCHO GUARDAS ANCLADAS DESPUES DE LA REVISION. La revision independiente
neutralizo el `raise` de ocho guardas de garantia RC (envolviendolo en
`if False:`, que preserva el censo AST) y los 5255 tests siguieron VERDES. Las
ocho caen dentro del criterio de INCLUSION de arriba, asi que --regla del
operador-- eran bloqueantes aunque ya estuviesen indefensas en `aaf9695`. Sus
anclas de conducta viven en `tests/test_carril5_anclas_rc.py` y el control
negativo que las mide, en `tools/carril5_negative_controls.py guards --full`.
"""
from __future__ import annotations

#: Familias de deuda: `(familia, patrones de fichero, por que NO se convierte)`.
#:
#: NO llevan numero escrito a mano. El recuento de cada familia lo DERIVA
#: `deuda_por_familia()` del censo del detector entregado
#: (`data-engine/tools/carril5_inventario.py`), y la prueba comprueba que la
#: suma cuadra con el censo total. Antes eran cuatro enteros libres: se podia
#: cambiar cualquiera y ninguna prueba se enteraba mientras la suma siguiera
#: cuadrando con otro entero igual de libre.
#:
#: El orden IMPORTA: gana el primer patron que casa, de modo que las familias
#: forman una particion (ningun fichero cuenta dos veces, ninguno se queda
#: fuera). La ultima es un cajon de sastre explicito, no un olvido.
DEUDA_FUERA_DE_ALCANCE = [
    (
        "guardas del propio carril 5",
        ("test_carril5_*.py",),
        "Comprueban el INSTRUMENTO, y lo hacen sobre el mensaje que produce el "
        "propio instrumento ('codigo de excepcion inesperado'), no sobre el de "
        "ningun modulo de producto. Aqui la redaccion SI es la garantia.",
    ),
    (
        "benchmarks de relaciones (bloque 7, rondas 1-4)",
        ("test_relation_benchmark_block7*.py",),
        "Miden CALIDAD de un benchmark (mensajes de informe, texto de dictamen). "
        "Reescribir un mensaje ahi no destruye ninguna propiedad del RC: destruye "
        "la legibilidad de un informe, que es justo lo que esas pruebas cuidan.",
    ),
    (
        "proveedores externos (NVIDIA, Ollama, hardening, robustez)",
        ("test_knowledge_v3_providers_*.py",),
        "Corren en SOMBRA: su fallo no puede escribir en el grafo. Ninguna "
        "garantia RC depende de ellos hoy. Candidatos naturales cuando la "
        "revision externa deje la sombra.",
    ),
    (
        "contratos de relacion: candidato, prompts, parser v2, pipeline",
        ("test_relation_*.py",),
        "Contratos ya validados por JSON Schema y por `V3ContractError`; el "
        "mensaje es superficie de diagnostico, no la garantia. Sellar aqui "
        "duplicaria una defensa que ya existe aguas arriba --y esa defensa se "
        "verifico: existe y muerde.",
    ),
    (
        "motor V3, adaptadores, extraccion, glosario, multimodal, jobs, CLI",
        ("*.py",),
        "Errores de uso y de datos de entrada, no invariantes del RC. Convertirlos "
        "a ciegas cambiaria decenas de pruebas sin mover una sola garantia.",
    ),
]

#: Puntos SELLADOS con codigo estable y puntos SIN ancla de conducta.
#:
#: ESTAS TRES CIFRAS YA NO SE DECLARAN: se comparan contra `censo_anclas()`
#: (mas abajo), que las MIDE por AST. Antes solo `SITIOS_SELLADOS` estaba fijado
#: por censo: se podia poner `SITIOS_CON_ANCLA = 71` y `SIN_ANCLA_MEDIDA = 0`
#: --borrando la deuda entera-- y la suite seguia verde. Ahora eso enrojece.
#:
#: MATIZ que hay que honrar y no vender de mas: `SITIOS_CON_ANCLA` es el censo
#: ESTATICO (existe una prueba que exige ese codigo), es decir una COTA
#: SUPERIOR. La medida fuerte, por mutacion, la da
#: `tools/carril5_negative_controls.py`.
SIN_ANCLA_MEDIDA = 22
SITIOS_SELLADOS = 71
SITIOS_CON_ANCLA = 49

# --------------------------------------------------------------------------
# INVENTARIO. Todas las cifras que siguen las produce el detector ENTREGADO,
# `data-engine/tools/carril5_inventario.py`, y la prueba las vuelve a medir.
#
# CORRECCION DE LA ENTREGA ANTERIOR. Aqui habia una tabla de reconciliacion
# (185 / 226 / 337 y un reparto 130+129) atribuida a "dos detectores", y a
# continuacion la frase «quien quiera reproducirlo tiene aqui el detector y el
# ref exactos». No lo tenia: habia PROSA describiendo un detector que nunca se
# entrego. Escrito ya el detector, esto es lo que se sostiene y lo que no:
#
#   - Reproduce EXACTO la unica familia sin ambiguedad, `match=`:
#       data-engine @ aaf9695 -> 127 estricto / 130 amplio   (coincide)
#       repo        @ aaf9695 -> 153 amplio                  (coincide)
#     Y reproduce exacta la comprobacion cruzada de la conversion:
#       127 (`match=` base) - 52 (convertidas) + 2 (guardas nuevas) = 77 hoy.
#   - NO reproduce el reparto de la familia `in <mensaje>` (58 / 129 / 73 / 181).
#     Esa familia depende por completo de donde se ponga la frontera de "esto es
#     un mensaje", y la frontera nunca se escribio. Con la frontera que ahora SI
#     esta escrita en el detector salen otros numeros. No se "corrige" la cifra
#     vieja: se retira, porque no era reproducible.
#   - Por eso el ESTRICTO es la MEDIDA (`str(...)`, sin interpretacion) y el
#     AMPLIO es una COTA SUPERIOR declarada (heuristica sobre nombres tipo
#     msg/err/detail/stdout), util para acotar, no para afirmar.
#
# Todas se miden sobre el ambito `data-engine` salvo donde diga lo contrario.
# --------------------------------------------------------------------------

#: `aaf9695`, la base del carril. Detector ESTRICTO.
INVENTARIO_BASE_ESTRICTO = 177
INVENTARIO_BASE_ESTRICTO_MATCH = 127
INVENTARIO_BASE_ESTRICTO_IN_STR = 50

#: Arbol actual (esta rama). Detector ESTRICTO. La caida es la conversion.
INVENTARIO_ACTUAL_ESTRICTO = 127
INVENTARIO_ACTUAL_ESTRICTO_MATCH = 77
INVENTARIO_ACTUAL_ESTRICTO_IN_STR = 50

#: Cota superior (detector AMPLIO), base y actual.
INVENTARIO_BASE_AMPLIO = 345
INVENTARIO_ACTUAL_AMPLIO = 295

#: Guardas `match=` NUEVAS que introduce el carril: las dos de
#: `test_carril5_exception_codes.py` que protegen al propio instrumento.
GUARDAS_NUEVAS = 2

#: Convertidas. NO es un dato independiente: es la diferencia medida.
#:   177 (base) - 127 (actual) + 2 (guardas nuevas) = 52
CONVERTIDAS = 52

#: Nombres antiguos, conservados para no romper a quien los importe. Apuntan a
#: la medida ESTRICTA de la base, que es la unica que un detector reproduce.
INVENTARIO_TOTAL = INVENTARIO_BASE_ESTRICTO
INVENTARIO_MATCH = INVENTARIO_BASE_ESTRICTO_MATCH
INVENTARIO_IN_STR = INVENTARIO_BASE_ESTRICTO_IN_STR

#: Unificacion pendiente con el carril 3: cuando `viewer/tests/exception_codes.py`
#: (PR #198) este en `main`, los dos modulos comparten contrato y pueden fundirse.
#: No se hace ahora porque ese fichero NO existe en `aaf9695`.
DEUDA_UNIFICACION_CARRIL3 = True

# --------------------------------------------------------------------------
# CENSO DERIVADO. Lo que sigue NO son numeros escritos a mano: se MIDEN por AST
# sobre el arbol, y `test_carril5_exception_codes.py` compara lo declarado
# arriba con lo medido aqui. Mentir en una cifra pone rojo.
# --------------------------------------------------------------------------
import ast as _ast  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

_APP_DIR = _Path(__file__).resolve().parents[1]

#: Modulos de producto sellados por el carril. Fuente unica: la prueba y el
#: arnes leen ESTA lista, para que no puedan divergir.
MODULOS_SELLADOS = (
    "knowledge_v3/ledger/assertions.py",
    "knowledge_v3/ledger/supersession.py",
    "knowledge_v3/ledger/store.py",
    "knowledge_v3/ledger/entries.py",
    "review/ingest_approved.py",
    "review/supersede_review.py",
)


def _arbol(path: _Path):
    return _ast.parse(path.read_text(encoding="utf-8"), str(path))


def sitios_sellados() -> list:
    """Todo `raise coded(Exc(...), Registro.CODIGO)` de los modulos sellados.

    Devuelve `[(modulo, linea, "Registro.CODIGO"), ...]`, ordenado.
    """
    out = []
    for rel in MODULOS_SELLADOS:
        for n in _ast.walk(_arbol(_APP_DIR / rel)):
            if (isinstance(n, _ast.Raise) and isinstance(n.exc, _ast.Call)
                    and isinstance(n.exc.func, _ast.Name)
                    and n.exc.func.id == "coded" and len(n.exc.args) == 2):
                out.append((rel, n.lineno, _ast.unparse(n.exc.args[1])))
    return sorted(out)


def codigos_exigidos_por_pruebas() -> dict:
    """Codigos que ALGUNA prueba exige por conducta, y donde lo exige.

    Cuenta `raises_code(Tipo, Registro.CODIGO)` y `assert_code(exc,
    Registro.CODIGO)` en cualquier fichero de `app/tests/`. Devuelve
    `{"Registro.CODIGO": ["fichero:linea", ...]}`.

    LIMITE DECLARADO, y conviene no venderlo de mas: esto es un censo ESTATICO.
    Dice que EXISTE una prueba que exige ese codigo; no demuestra que esa prueba
    enrojezca al neutralizar la guarda (podria cubrir otro camino que levante el
    mismo codigo). La demostracion fuerte es el control negativo por mutacion
    --`tools/carril5_negative_controls.py`, modos `code` y `guards`--, que es lo
    que se ejecuta y se publica. El censo estatico es la COTA SUPERIOR: un sitio
    que ni siquiera aparece aqui no puede estar anclado de ninguna manera.
    """
    out: dict = {}
    for path in sorted((_APP_DIR / "tests").rglob("*.py")):
        try:
            tree = _arbol(path)
        except SyntaxError:
            continue
        rel = str(path.relative_to(_APP_DIR))
        for n in _ast.walk(tree):
            if not (isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name)
                    and n.func.id in ("raises_code", "assert_code")
                    and len(n.args) == 2):
                continue
            arg = n.args[1]
            if isinstance(arg, _ast.Attribute):
                out.setdefault(_ast.unparse(arg), []).append(f"{rel}:{n.lineno}")
    return out


def censo_anclas() -> dict:
    """Reparto MEDIDO entre sitios con ancla y sitios sin ella, CON NOMBRES.

    Un numero no es una declaracion: la entrega anterior decia "31 sin ancla" y
    la lista de cuales no existia en ningun sitio del repo. Aqui esta, nominal.
    """
    sitios = sitios_sellados()
    exigidos = codigos_exigidos_por_pruebas()
    con, sin = [], []
    for rel, linea, codigo in sitios:
        (con if codigo in exigidos else sin).append(f"{rel}:{linea} {codigo}")
    return {
        "sellados": len(sitios),
        "con_ancla": len(con),
        "sin_ancla": len(sin),
        "nominal_con_ancla": con,
        "nominal_sin_ancla": sin,
    }


import functools as _functools  # noqa: E402


@_functools.lru_cache(maxsize=None)
def censo_inventario(scope: str = "data-engine", ref=None) -> dict:
    """Inventario de comprobaciones por subcadena, MEDIDO por el detector
    entregado en `data-engine/tools/carril5_inventario.py`.

    Se importa el detector real en vez de reimplementarlo: dos copias del mismo
    censo acabarian divergiendo y una de las dos mentiria sin enrojecer.
    """
    import importlib.util
    ruta = _APP_DIR.parent / "tools" / "carril5_inventario.py"
    spec = importlib.util.spec_from_file_location("_carril5_inventario", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.censar(scope, ref)


def deuda_por_familia(censo=None) -> dict:
    """Reparto de la deuda ESTRICTA viva, derivado del censo. `{familia: n}`.

    Primer patron que casa, gana: las familias particionan los ficheros, asi que
    la suma es exactamente el censo total y no puede haber ni doble conteo ni
    ficheros huerfanos. Si manana aparece un fichero de prueba nuevo que mide
    redaccion, cae en el cajon de sastre y la suma sube: la cifra se mueve sola.
    """
    import fnmatch
    censo = censo or censo_inventario("data-engine")
    conteo = {familia: 0 for familia, _, _ in DEUDA_FUERA_DE_ALCANCE}
    for rel, v in censo["por_fichero"].items():
        n = len(v["estricto_match"]) + len(v["estricto_in_str"])
        if not n:
            continue
        base = _Path(rel).name
        for familia, patrones, _ in DEUDA_FUERA_DE_ALCANCE:
            if any(fnmatch.fnmatch(base, p) for p in patrones):
                conteo[familia] += n
                break
        else:  # pragma: no cover - el cajon de sastre es `*.py`
            raise AssertionError(f"{rel} no cae en ninguna familia declarada")
    return conteo


#: Sitios sellados que HOY no tiene ancla ninguna prueba. Se declara la LISTA,
#: no solo el numero: la entrega anterior decia "31" y ese 31 no se podia
#: convertir en una lista de sitios porque la lista no existia en el repo. Un
#: numero no es una declaracion. La prueba compara esta lista con la medida.
SIN_ANCLA_NOMINAL = (
    "knowledge_v3/ledger/assertions.py:95 LedgerCodes.BAD_ASSERTION_TYPE",
    "knowledge_v3/ledger/assertions.py:236 LedgerCodes.WORKSPACE_LEAK",
    "knowledge_v3/ledger/assertions.py:303 LedgerCodes.WORKSPACE_LEAK",
    "knowledge_v3/ledger/assertions.py:310 LedgerCodes.RECORDED_AT_INVALID",
    "knowledge_v3/ledger/assertions.py:374 LedgerCodes.RECORDED_AT_INVALID",
    "knowledge_v3/ledger/assertions.py:388 LedgerCodes.BIRTH_STATUS_INVALID",
    "knowledge_v3/ledger/assertions.py:393 LedgerCodes.BORN_SUPERSEDED",
    "knowledge_v3/ledger/assertions.py:505 LedgerCodes.RECORDED_AT_INVALID",
    "knowledge_v3/ledger/entries.py:116 LedgerCodes.ENTRY_MISSING_FIELDS",
    "knowledge_v3/ledger/supersession.py:128 LedgerCodes.UNKNOWN_STATUS",
    "knowledge_v3/ledger/supersession.py:143 LedgerCodes.UNKNOWN_SOURCE_STATUS",
    "knowledge_v3/ledger/supersession.py:146 LedgerCodes.ILLEGAL_TRANSITION",
    "review/ingest_approved.py:288 WriterCodes.LABEL_NOT_ALLOWED",
    "review/ingest_approved.py:385 WriterCodes.USE_EXISTING_AMBIGUOUS",
    "review/ingest_approved.py:429 WriterCodes.RELATION_SOURCE_KIND_MISSING",
    "review/ingest_approved.py:432 WriterCodes.RELATION_REVIEW_STATUS_MISSING",
    "review/ingest_approved.py:578 WriterCodes.REPORT_NOT_FOUND",
    "review/ingest_approved.py:610 WriterCodes.PACKAGE_REJECTED",
    "review/ingest_approved.py:665 WriterCodes.NEO4J_UNAVAILABLE",
    "review/supersede_review.py:284 SupersedeCodes.INPUT_NOT_FOUND",
    "review/supersede_review.py:286 SupersedeCodes.IN_OUT_SAME_FILE",
    "review/supersede_review.py:336 SupersedeCodes.SCHEMA_INVALID_OUTPUT",
)


__all__ = [
    "CONVERTIDAS", "DEUDA_FUERA_DE_ALCANCE", "DEUDA_UNIFICACION_CARRIL3",
    "SIN_ANCLA_NOMINAL", "deuda_por_familia",
    "INVENTARIO_IN_STR", "INVENTARIO_MATCH", "INVENTARIO_TOTAL",
    "MODULOS_SELLADOS", "SIN_ANCLA_MEDIDA", "SITIOS_CON_ANCLA",
    "SITIOS_SELLADOS", "censo_anclas", "censo_inventario",
    "codigos_exigidos_por_pruebas", "sitios_sellados",
]
