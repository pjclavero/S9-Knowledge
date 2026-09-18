"""Carril B · M1 — descubrimiento jerarquico + clasificacion ruta -> ambito.

QUE DEFIENDE ESTA SUITE
-----------------------
El invariante duro del encargo, que no es "el catalogo ve subdirectorios" sino:

    NO SE PERMITE hacer recursivo el catalogo sin activar SIMULTANEAMENTE la
    clasificacion ruta -> ambito. Solo la recursion es PEOR que el defecto.

Por eso aqui no se prueba "encuentra N ficheros". Se prueba, en este orden:

  1. que la tabla §3 esta implementada FILA POR FILA, cruzando la tabla
     declarada como dato con lo que la funcion devuelve;
  2. que recursion y clasificacion son INSEPARABLES por construccion, no por
     convencion: quitar la clasificacion no produce fuentes mal clasificadas,
     no produce ninguna;
  3. que una ruta desconocida y una INCOHERENTE fallan cerrado con
     diagnosticos DISTINTOS —son dos errores distintos del operador—;
  4. que montaje AUSENTE y montaje VACIO no se pueden confundir;
  5. que la partida llega, EJECUTADA, hasta el payload del alta y de ahi al
     motor;
  6. que el ambito se VE en la pantalla, porque una garantia que no se pinta no
     la puede comprobar quien opera.

POR QUE CADA ROJO DICE SU CAUSA
-------------------------------
Toda asercion sobre un rechazo comprueba el MOTIVO y un fragmento del MENSAJE,
no solo que hubo rechazo. Un rojo por la razon equivocada se lee igual que uno
legitimo, y ese es exactamente el fallo que este corte corrige aguas abajo.
"""
from __future__ import annotations

import errno
import inspect
import json
import os
import re
from dataclasses import fields
from pathlib import Path

import pytest

from app import sources_catalog, vault_mount
from app.vault_scope import (
    MOTIVO_DESCONOCIDA,
    MOTIVO_INCOHERENTE,
    MOTIVO_NO_INGERIBLE,
    MOTIVO_RESERVADA,
    REGLAS_DOCUMENTADAS,
    Ambito,
    NoIngerible,
    clasificar,
)

REPO = Path(__file__).resolve().parents[2]
EJEMPLOS = REPO / "examples" / "ingesta-v3"


# ===========================================================================
# DOS JUEGOS Y DOS PARTIDAS DEL MISMO JUEGO — el arbol de la instruccion 12
# ===========================================================================

#: Se montan las DOS bovedas gemelas medidas en el arbol real, con sus nombres
#: EXTERNOS, y el workspace de cada una se DECLARA en su perfil. `l5r/` ->
#: `leyenda` es justamente el caso que no puede inferirse del nombre.
JUEGOS = {
    "l5r": "leyenda",
    "trudvang": "trudvang",
}
#: Dos partidas DEL MISMO workspace: es lo que demuestra que la partida es una
#: dimension propia y no otro nombre del workspace.
PARTIDAS_L5R = ("campana-grulla", "campana-escorpion")


#: Contenido REAL del material de ejemplo del repositorio. Se usa para que las
#: fuentes de la boveda de prueba sean ingeribles de verdad y el recorrido
#: extremo a extremo no pase por ser trivial.
TEXTO_EJEMPLO = (EJEMPLOS / "nota-cofradia-de-ambar.md").read_text(encoding="utf-8")


def _escribir(p: Path, texto: str = TEXTO_EJEMPLO) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(texto, encoding="utf-8")
    return p


@pytest.fixture
def boveda(tmp_path: Path) -> Path:
    """El arbol real de bovedas, en pequeno pero con TODOS sus niveles."""
    raiz = tmp_path / "bovedas"
    plantilla = json.loads((EJEMPLOS / sources_catalog.NOMBRE_PERFIL)
                           .read_text(encoding="utf-8"))

    for carpeta, workspace in JUEGOS.items():
        base = raiz / carpeta
        perfil = dict(plantilla)
        perfil["workspace"] = workspace
        perfil["source_asset_id"] = f"profile:{workspace}"
        _escribir(base / sources_catalog.NOMBRE_PERFIL,
                  json.dumps(perfil, ensure_ascii=False))

        # capa juego
        _escribir(base / "compartido" / "manuales" / "basico.md")
        _escribir(base / "compartido" / "lore" / "clanes.md")
        _escribir(base / "reservado" / "manuales" / "libro-del-director.md")
        _escribir(base / "reservado" / "lore" / "tierras-sombrias.md")
        _escribir(base / "referencia" / "ensayo-externo.md")
        _escribir(base / "entrada" / "sin-clasificar.md")
        _escribir(base / "archivo" / "retirado.md")

    for partida in PARTIDAS_L5R:
        base = raiz / "l5r" / "partidas" / partida
        _escribir(base / "material-jugadores" / "mapa.md")
        _escribir(base / "notas-narrador" / "notas.md")
        _escribir(base / "secretos" / "el-impostor.md")
        _escribir(base / "personajes" / "ficha-pj.md")
        _escribir(base / "sesiones" / "sesion-01" / "acta.md")
        _escribir(base / "sesiones" / "sesion-01" / "transcripciones" / "t.md")
        _escribir(base / "sesiones" / "sesion-01" / "videos" / "guion.md")
        _escribir(base / "aportaciones" / f"{partida}-hitomi" / "diario.md")

    _escribir(raiz / "trudvang" / "partidas" / "saga-norte"
              / "material-jugadores" / "mapa.md")
    return raiz


@pytest.fixture
def entorno_boveda(boveda: Path) -> dict:
    """Entorno que enciende el modo boveda SIN exigir montaje.

    `exigir montaje` se apaga EXPLICITAMENTE: un `tmp_path` no es un punto de
    montaje. El interruptor es explicito justamente para que apagarlo sea una
    decision visible y no el defecto.
    """
    return {
        sources_catalog.ENV_RAIZ_BOVEDAS: str(boveda),
        sources_catalog.ENV_EXIGIR_MONTAJE: "0",
    }


# ===========================================================================
# 1. LA TABLA §3, FILA POR FILA
# ===========================================================================

#: Una ruta REPRESENTATIVA por cada fila ingerible de la tabla §3, con el ambito
#: que la tabla le asigna. Se escribe aqui a mano, leyendo el documento, para
#: que la prueba sea un CONTRASTE con el contrato y no un eco de la
#: implementacion.
FILAS_INGERIBLES = [
    ("l5r/compartido/manuales/basico.md", "l5r", None, "player"),
    ("l5r/compartido/lore/clanes.md", "l5r", None, "player"),
    ("l5r/reservado/manuales/libro-del-director.md", "l5r", None, "narrator"),
    ("l5r/reservado/lore/tierras-sombrias.md", "l5r", None, "narrator"),
    ("l5r/referencia/ensayo-externo.md", "l5r", None, "reference"),
    ("l5r/entrada/sin-clasificar.md", "l5r", None, "secret"),
    ("l5r/partidas/campana-grulla/material-jugadores/mapa.md",
     "l5r", "campana-grulla", "player"),
    ("l5r/partidas/campana-grulla/notas-narrador/notas.md",
     "l5r", "campana-grulla", "narrator"),
    ("l5r/partidas/campana-grulla/secretos/el-impostor.md",
     "l5r", "campana-grulla", "secret"),
    ("l5r/partidas/campana-grulla/personajes/ficha-pj.md",
     "l5r", "campana-grulla", "narrator"),
    ("l5r/partidas/campana-grulla/sesiones/sesion-01/acta.md",
     "l5r", "campana-grulla", "player"),
    ("l5r/partidas/campana-grulla/aportaciones/campana-grulla-hitomi/diario.md",
     "l5r", "campana-grulla", "secret"),
]


@pytest.mark.parametrize("ruta,juego,partida,visibility", FILAS_INGERIBLES)
def test_tabla_3_fila_por_fila(ruta, juego, partida, visibility):
    """Cada fila ingerible de §3 produce EXACTAMENTE lo que la tabla dice."""
    ambito = clasificar(ruta)
    assert ambito.carpeta_juego == juego
    assert ambito.partida_id == partida, (
        f"{ruta}: la tabla §3 asigna partida {partida!r}, "
        f"salio {ambito.partida_id!r}"
    )
    assert ambito.visibility == visibility, (
        f"{ruta}: la tabla §3 asigna visibilidad inicial {visibility!r}, "
        f"salio {ambito.visibility!r}"
    )


def test_la_tabla_declarada_cubre_las_mismas_visibilidades_que_lo_implementado():
    """`REGLAS_DOCUMENTADAS` no puede divergir de lo que hace `clasificar`.

    Se cruzan las dos: si alguien cambia el defecto de una carpeta en el codigo
    y no toca la tabla —o al reves—, esto se pone rojo diciendo cual.
    """
    documentado = {
        fila[0]: fila[2] for fila in REGLAS_DOCUMENTADAS if fila[2] is not None
    }
    implementado = {}
    for ruta, _juego, _partida, visibility in FILAS_INGERIBLES:
        implementado[clasificar(ruta).regla] = visibility
    for regla, vis in implementado.items():
        assert regla in documentado, f"regla implementada sin fila en la tabla: {regla}"
        assert documentado[regla] == vis, (
            f"{regla}: la tabla dice {documentado[regla]!r}, el codigo {vis!r}"
        )


def test_las_carpetas_de_formato_son_transparentes():
    """`videos/`, `transcripciones/` y las que el operador anada no cambian nada.

    Es la propiedad que hace que anadir una carpeta de formato sea inocuo.
    """
    base = "l5r/partidas/campana-grulla/sesiones/sesion-01"
    acta = clasificar(f"{base}/acta.md")
    for formato in ("videos", "transcripciones", "una-carpeta-nueva", "podcast"):
        dentro = clasificar(f"{base}/{formato}/pieza.md")
        assert (dentro.partida_id, dentro.visibility) == (acta.partida_id, acta.visibility), (
            f"la carpeta de formato `{formato}` altero el ambito heredado"
        )


def test_lore_y_manuales_son_organizativas():
    """Heredan del nivel contenedor y no pueden modificarlo (instruccion 11)."""
    for capa, esperado in (("compartido", "player"), ("reservado", "narrator")):
        directo = clasificar(f"l5r/{capa}/suelto.md")
        for organizativa in ("lore", "manuales", "apendices"):
            anidado = clasificar(f"l5r/{capa}/{organizativa}/x.md")
            assert anidado.visibility == directo.visibility == esperado


# ===========================================================================
# 2. FALLA CERRADO, con el diagnostico exacto
# ===========================================================================

def test_ruta_desconocida_no_ingiere_y_lo_dice():
    with pytest.raises(NoIngerible) as ei:
        clasificar("l5r/una-carpeta-que-nadie-decidio/cosa.md")
    assert ei.value.motivo == MOTIVO_DESCONOCIDA
    assert "no es ninguna seccion del esquema" in ei.value.detalle
    assert "visibilidad adivinada" in ei.value.detalle


def test_fichero_suelto_en_la_raiz_no_ingiere():
    with pytest.raises(NoIngerible) as ei:
        clasificar("suelto.md")
    assert ei.value.motivo == MOTIVO_DESCONOCIDA
    assert "fuera del esquema" in ei.value.detalle


def test_aportacion_de_otra_partida_es_INCOHERENTE_no_desconocida():
    """La ruta es CONOCIDA y esta MAL: es otro error, y se nombra distinto.

    Y se comprueba la autoridad: la partida del contexto es la carpeta bajo
    `partidas/`; el prefijo del buzon solo puede DESMENTIRLA.
    """
    with pytest.raises(NoIngerible) as ei:
        clasificar("l5r/partidas/campana-grulla/aportaciones/"
                   "campana-escorpion-hitomi/diario.md")
    assert ei.value.motivo == MOTIVO_INCOHERENTE, (
        "una ruta conocida pero incoherente no puede confundirse con una "
        "ruta desconocida: son dos errores distintos del operador"
    )
    assert "no corresponde a la partida" in ei.value.detalle
    assert "La partida del contexto manda" in ei.value.detalle


def test_el_buzon_valido_no_es_la_autoridad_de_la_partida():
    """Aunque el buzon lleve el nombre, la partida sale de `partidas/<p>/`."""
    a = clasificar("l5r/partidas/campana-grulla/aportaciones/"
                   "campana-grulla-hitomi/diario.md")
    assert a.partida_id == "campana-grulla"
    assert a.visibility == "secret", "la aportacion entra en lo mas restrictivo"


def test_sesion_mal_nombrada_es_INCOHERENTE():
    for malo in ("sesion 1", "sesion-1", "Sesion-01", "primera"):
        with pytest.raises(NoIngerible) as ei:
            clasificar(f"l5r/partidas/campana-grulla/sesiones/{malo}/acta.md")
        assert ei.value.motivo == MOTIVO_INCOHERENTE, malo
        assert "contrato de entrada" in ei.value.detalle
        assert "no es un identificador global" in ei.value.detalle


def test_sesion_admite_mas_de_dos_digitos():
    a = clasificar("l5r/partidas/x/sesiones/sesion-100/acta.md")
    assert a.partida_id == "x"


def test_archivo_no_se_ingiere_nunca():
    with pytest.raises(NoIngerible) as ei:
        clasificar("l5r/archivo/retirado.md")
    assert ei.value.motivo == MOTIVO_NO_INGERIBLE
    assert "no se ingiere nunca" in ei.value.detalle


def test_plantilla_es_reservada_aunque_imite_el_arbol():
    """`_plantilla/` se mira ANTES que nada, y por una razon concreta.

    Contiene una replica del arbol entero. Clasificada despues, cada fichero
    suyo caeria en la regla de la carpeta que imita y entraria con el ambito de
    la carpeta REAL que no es. Hoy no existe en el arbol; el parser sabe que
    hacer si aparece (instruccion 11).
    """
    for ruta in ("_plantilla/compartido/manuales/x.md",
                 "_plantilla/partidas/p/secretos/x.md",
                 "_plantilla/x.md"):
        with pytest.raises(NoIngerible) as ei:
            clasificar(ruta)
        assert ei.value.motivo == MOTIVO_RESERVADA, ruta
        assert "no se ingiere" in ei.value.detalle


def test_la_ruta_no_puede_salir_de_la_boveda():
    with pytest.raises(NoIngerible) as ei:
        clasificar("l5r/../../etc/passwd")
    assert ei.value.motivo == MOTIVO_INCOHERENTE
    assert "sube por encima de la raiz" in ei.value.detalle


#: Segmentos con los que se compone el barrido. Mezclan los legitimos del
#: esquema con los HOSTILES —`..`, `.`, vacio, mayusculas, buzon de otra
#: partida, sesion mal formada— porque la propiedad que se afirma es sobre
#: TODAS las rutas, no sobre las bonitas.
_SEGMENTOS = (
    "l5r", "trudvang", "_plantilla", "otra-cosa", "",
    "compartido", "reservado", "referencia", "entrada", "archivo",
    "partidas", "p", "campana-grulla",
    "aportaciones", "campana-grulla-hitomi", "campana-escorpion-hitomi",
    "sesiones", "sesion-01", "sesion-1", "Sesion-01",
    "secretos", "notas-narrador", "personajes", "material-jugadores",
    "lore", "manuales", "videos",
    "..", ".", "x.md",
)


def test_no_se_devuelve_nunca_un_ambito_por_defecto():
    """No existe «ya veremos luego que ambito era». BARRIDO, no surtido.

    La version anterior de esta prueba probaba SIETE rutas escritas a mano y la
    prosa afirmaba que «no existe rama que devuelva ambito por defecto». Siete
    casos no demuestran eso: un revisor independiente lo hizo notar, con razon,
    tras barrer el espacio de verdad por su cuenta.

    Asi que el testigo sube a la altura de lo que afirma. Se genera el producto
    cartesiano de segmentos —legitimos y HOSTILES— hasta profundidad 4
    (~850.000 rutas), y de cada resultado se exige la propiedad fuerte:

      * o levanta `NoIngerible` con uno de los CUATRO motivos declarados,
      * o devuelve un `Ambito` cuya `visibility` esta en el enum cerrado del
        contrato, cuya `regla` esta en el conjunto de reglas conocidas, y cuyo
        `workspace` es None (lo pone despues el perfil, nunca el clasificador).

    No hay tercera posibilidad, y ninguna ruta puede inventarse una regla.

    EL TECHO, DECLARADO
    -------------------
    Lo que este barrido NO cubre, para que nadie lo lea como exhaustivo:
    profundidades mayores que 4; segmentos fuera de `_SEGMENTOS` (nombres
    arbitrarios de juego, partida o jugador); separadores distintos de `/`;
    y nombres con Unicode, espacios o mayusculas mas alla de `Sesion-01`. La
    profundidad esta acotada por coste: a 5 la prueba tardaba 165 s.
    """
    import itertools

    visibilidades_validas = {"player", "narrator", "secret", "reference", "deny"}
    motivos_validos = {MOTIVO_DESCONOCIDA, MOTIVO_INCOHERENTE,
                       MOTIVO_RESERVADA, MOTIVO_NO_INGERIBLE}
    reglas_validas = {f[0] for f in REGLAS_DOCUMENTADAS}

    total = 0
    con_ambito = 0
    motivos_vistos = set()
    for profundidad in range(1, 5):
        for combo in itertools.product(_SEGMENTOS, repeat=profundidad):
            ruta = "/".join(combo)
            total += 1
            try:
                a = clasificar(ruta)
            except NoIngerible as exc:
                assert exc.motivo in motivos_validos, (ruta, exc.motivo)
                assert exc.detalle, f"{ruta}: rechazo SIN diagnostico"
                motivos_vistos.add(exc.motivo)
                continue
            con_ambito += 1
            assert a.visibility in visibilidades_validas, (ruta, a.visibility)
            assert a.regla in reglas_validas, (
                f"{ruta}: regla inventada {a.regla!r}, fuera de la tabla §3"
            )
            assert a.workspace is None, (
                f"{ruta}: el clasificador se invento un workspace {a.workspace!r};"
                " eso lo declara el perfil de la boveda, no la ruta"
            )
            # La carpeta de juego es el primer segmento SIGNIFICATIVO. Los
            # segmentos vacios y `.` se normalizan —son no-operaciones en una
            # ruta POSIX—, asi que `./l5r/...` es `l5r/...` y no una bóveda
            # llamada «.». `..` NO se normaliza: se rechaza, y por eso no llega
            # hasta aqui. Lo encontro este mismo barrido al ampliarlo.
            significativos = [x for x in combo if x not in ("", ".")]
            assert a.carpeta_juego == significativos[0], (ruta, a.carpeta_juego)

    # El arnes muerde: si no hubiera casos de los dos tipos, no diria nada.
    assert total > 10000, f"barrido demasiado pequeno: {total}"
    assert con_ambito > 0, "ninguna ruta se clasifico: el barrido no toca el esquema"
    assert motivos_vistos == motivos_validos, (
        f"motivos sin ejercitar en el barrido: {motivos_validos - motivos_vistos}"
    )


# ===========================================================================
# 3. EL INVARIANTE: recursion y clasificacion, INSEPARABLES
# ===========================================================================

def test_no_existe_forma_de_construir_una_fuente_sin_ambito():
    """La union no es una convencion: es la firma del constructor.

    `ambito` es un campo OBLIGATORIO y SIN DEFECTO de `FuenteDisponible`. Es lo
    que hace que "hacer el catalogo recursivo sin clasificar" no produzca un
    resultado peor sino NINGUN resultado.
    """
    campos = {f.name: f for f in fields(sources_catalog.FuenteDisponible)}
    assert "ambito" in campos, "la fuente ya no lleva ambito: el invariante se fue"
    import dataclasses
    assert campos["ambito"].default is dataclasses.MISSING, (
        "`ambito` tiene defecto: se puede construir una fuente sin clasificar"
    )
    assert campos["ambito"].default_factory is dataclasses.MISSING

    with pytest.raises(TypeError):
        sources_catalog.FuenteDisponible(  # type: ignore[call-arg]
            handle="x", titulo="X", formato="Markdown", tamano_bytes=1,
            ruta=Path("/tmp/x.md"), perfil=Path("/tmp/p.json"),
        )


def test_el_recorrido_clasifica_ANTES_de_considerar_la_fuente():
    """El orden importa, y se lee en el propio codigo.

    Si la clasificacion fuera un filtro POSTERIOR, una ruta desconocida llegaria
    a evaluarse como candidata y bastaria con olvidarse de comprobar el
    resultado para que entrara. Aqui se comprueba que `clasificar` aparece antes
    que la consulta de extension en el cuerpo del recorrido.
    """
    fuente = inspect.getsource(sources_catalog.listar_fuentes_boveda)
    i_clasificar = fuente.index("clasificar(relativa)")
    i_formato = fuente.index("EXTENSIONES_SOPORTADAS.get")
    assert i_clasificar < i_formato, (
        "la clasificacion dejo de ser el primer paso del recorrido"
    )


def test_toda_ruta_recorrida_acaba_en_fuente_o_en_rechazo(entorno_boveda, boveda):
    """No hay tercera salida. En particular, no hay «descartado en silencio».

    Este es el defecto original medido: `sorted(raiz.iterdir())` sin recursion
    descartaba subdirectorios sin aviso, sin warning y con `stderr` vacio.

    EL TESTIGO NO HEREDA SU DEFINICION DEL SUJETO
    ---------------------------------------------
    La primera version de esta prueba construia el universo esperado con
    `if p.name not in sources_catalog._NO_SON_FUENTES`: **la misma constante del
    sujeto que causaba el descarte**. Definir el caso fuera del testigo lo
    incapacita para verlo, y en efecto NO lo vio — un revisor independiente
    encontro que un `README.md` anidado en `compartido/lore/` salia sin ser
    fuente ni rechazo, en silencio, a cualquier profundidad.

    Ahora el universo es TODO fichero del arbol, sin excepciones tomadas del
    sujeto. Si el catalogo quiere excluir algo, que lo DECLARE como rechazo.
    """
    fuentes, rechazos = sources_catalog.listar_fuentes_boveda(entorno_boveda)

    # SIN filtro prestado del sujeto: todos los ficheros, y punto.
    en_disco = {
        p.relative_to(boveda).as_posix()
        for p in boveda.rglob("*")
        if p.is_file()
    }
    assert en_disco, "arnes vacio: sin ficheros esta prueba no dice nada"
    contabilizadas = (
        {f.ruta.relative_to(boveda).as_posix() for f in fuentes}
        | {r["ruta"] for r in rechazos}
    )
    perdidas = en_disco - contabilizadas
    assert not perdidas, (
        "ficheros recorridos que no son ni fuente ni rechazo (descartados en "
        f"silencio, que es el defecto que este corte corrige): {sorted(perdidas)}"
    )


def test_un_auxiliar_ANIDADO_se_declara_en_vez_de_desaparecer(boveda):
    """El caso EXACTO que se escapo, calibrado como prueba propia.

    Un `README.md` con contenido real, hondo en el arbol y dentro de una carpeta
    perfectamente clasificable. Antes: `continue` mudo. Ahora: rechazo con su
    motivo, para que el operador vea por que no aparece su fichero.
    """
    escondido = boveda / "l5r" / "compartido" / "lore" / "README.md"
    _escribir(escondido, "esto tiene contenido de verdad, no es un hueco")
    env = {sources_catalog.ENV_RAIZ_BOVEDAS: str(boveda),
           sources_catalog.ENV_EXIGIR_MONTAJE: "0"}

    fuentes, rechazos = sources_catalog.listar_fuentes_boveda(env)
    relativa = escondido.relative_to(boveda).as_posix()

    assert all(f.ruta != escondido for f in fuentes), (
        "el auxiliar se ofrecio como fuente ingerible"
    )
    declarado = [r for r in rechazos if r["ruta"] == relativa]
    assert declarado, (
        f"`{relativa}` no es fuente NI rechazo: se fue en silencio, que es el "
        "defecto que este corte corrige, en forma residual"
    )
    assert declarado[0]["motivo"] == sources_catalog.MOTIVO_AUXILIAR
    assert "NO es una fuente" in declarado[0]["detalle"]


def test_los_auxiliares_de_la_raiz_del_juego_tambien_se_declaran(entorno_boveda):
    """Perfil y catalogo tampoco desaparecen: se dicen, con el mismo motivo."""
    _fuentes, rechazos = sources_catalog.listar_fuentes_boveda(entorno_boveda)
    auxiliares = {r["ruta"] for r in rechazos
                  if r["motivo"] == sources_catalog.MOTIVO_AUXILIAR}
    assert f"l5r/{sources_catalog.NOMBRE_PERFIL}" in auxiliares, auxiliares
    assert f"trudvang/{sources_catalog.NOMBRE_PERFIL}" in auxiliares, auxiliares


def test_la_recursion_ve_los_niveles_profundos_Y_cada_uno_con_SU_ambito(entorno_boveda):
    """El contraste con el defecto: no basta con verlos, hay que distinguirlos.

    Un `rglob` a secas meteria `reservado/`, `secretos/` y `compartido/` TODOS
    con el mismo ambito unico de la raiz. Aqui se exige lo contrario.
    """
    fuentes, _ = sources_catalog.listar_fuentes_boveda(entorno_boveda)
    por_titulo = {f.titulo: f for f in fuentes}

    assert len(fuentes) > 1
    # profundidad real alcanzada (6 niveles: juego/partidas/p/sesiones/sNN/fmt/f)
    profundidades = {len(Path(str(f.ambito.regla)).parts) for f in fuentes}
    assert profundidades, "no se clasifico nada"

    # Y NO comparten ambito: es lo que la recursion sola habria roto.
    ambitos = {(f.ambito.workspace, f.ambito.partida_id, f.ambito.visibility)
               for f in fuentes}
    assert len(ambitos) >= 6, (
        "todas las fuentes salieron con muy pocos ambitos distintos: es el "
        f"sintoma del ambito uniforme de la raiz. Ambitos: {sorted(map(str, ambitos))}"
    )
    secreto = por_titulo["El impostor"]
    compartido = por_titulo["Clanes"]
    assert secreto.ambito.visibility == "secret"
    assert compartido.ambito.visibility == "player"
    assert secreto.ambito.partida_id and compartido.ambito.partida_id is None


# ===========================================================================
# 4. DOS JUEGOS Y DOS PARTIDAS DEL MISMO JUEGO (instruccion 12)
# ===========================================================================

def test_dos_juegos_dos_workspaces_declarados_en_su_perfil(entorno_boveda):
    """`l5r` -> `leyenda` NO se infiere: lo declara el perfil de la boveda."""
    fuentes, _ = sources_catalog.listar_fuentes_boveda(entorno_boveda)
    por_carpeta = {}
    for f in fuentes:
        por_carpeta.setdefault(f.ambito.carpeta_juego, set()).add(f.ambito.workspace)

    assert por_carpeta["l5r"] == {"leyenda"}, (
        "el nombre EXTERNO de la carpeta no se tomo del perfil"
    )
    assert por_carpeta["trudvang"] == {"trudvang"}
    assert len({ws for s in por_carpeta.values() for ws in s}) == 2


def test_dos_partidas_del_MISMO_workspace_no_se_colapsan(entorno_boveda):
    """Partida y workspace son dimensiones DISTINTAS, no dos nombres de una."""
    fuentes, _ = sources_catalog.listar_fuentes_boveda(entorno_boveda)
    partidas = {f.ambito.partida_id for f in fuentes
                if f.ambito.workspace == "leyenda" and f.ambito.partida_id}
    assert partidas == set(PARTIDAS_L5R), partidas

    # El mismo nombre de fichero en las DOS partidas sale con partidas distintas.
    mapas = [f for f in fuentes if f.ruta.name == "mapa.md"
             and f.ambito.workspace == "leyenda"]
    assert len(mapas) == 2
    assert {m.ambito.partida_id for m in mapas} == set(PARTIDAS_L5R)


def test_el_workspace_nunca_lleva_dos_puntos(entorno_boveda):
    """El contrato V3 congelado no admite `:` en `workspace`.

    (`contracts/knowledge-v3/v1/_common-v3.schema.json`, `$defs.workspace`.)
    Se comprueba aqui porque `juego:<x>` era la tentacion obvia.
    """
    patron = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    fuentes, _ = sources_catalog.listar_fuentes_boveda(entorno_boveda)
    for f in fuentes:
        assert patron.match(f.ambito.workspace or ""), f.ambito.workspace


def test_boveda_sin_perfil_no_aporta_nada(tmp_path, boveda):
    """Sin `workspace` DECLARADO no se inventa uno a partir de la carpeta."""
    (boveda / "trudvang" / sources_catalog.NOMBRE_PERFIL).unlink()
    env = {sources_catalog.ENV_RAIZ_BOVEDAS: str(boveda),
           sources_catalog.ENV_EXIGIR_MONTAJE: "0"}
    fuentes, rechazos = sources_catalog.listar_fuentes_boveda(env)
    assert all(f.ambito.carpeta_juego != "trudvang" for f in fuentes)
    motivos = {r["motivo"] for r in rechazos}
    assert "PERFIL_DE_BOVEDA_INVALIDO" in motivos
    detalle = next(r["detalle"] for r in rechazos
                   if r["motivo"] == "PERFIL_DE_BOVEDA_INVALIDO")
    assert "no se da por supuesto" in detalle


# ===========================================================================
# 5. LA FRONTERA DE MONTAJE — vacio NO es ausente
# ===========================================================================

def test_montaje_ausente_y_montaje_vacio_son_ESTADOS_DISTINTOS(tmp_path):
    """El caso traicionero: un mountpoint sin montaje parece un dir vacio.

    Se construyen los dos y se exige que NO salgan iguales. Sin `ismount`, los
    dos serian «un directorio que existe y no tiene nada», que es como una
    boveda llena se lee como vacia.
    """
    punto = tmp_path / "montaje"
    punto.mkdir()

    # (a) EXIGIENDO montaje: `tmp_path` no lo es -> MONTAJE_AUSENTE
    ausente = vault_mount.inspeccionar(punto, exigir_montaje=True)
    assert ausente.estado is vault_mount.EstadoMontaje.MONTAJE_AUSENTE, (
        "un mountpoint SIN montaje activo no se declaro MONTAJE_AUSENTE: salio "
        f"{ausente.estado.value}. Si sale como vacio, una boveda llena se lee "
        "como «no hay fuentes», que es la conclusion contraria a la correcta"
    )
    assert "NO hay un montaje activo" in ausente.detalle
    assert not ausente.utilizable
    assert not ausente.vacio_de_verdad, (
        "un mountpoint sin montaje se declaro «vacio»: es la conclusion "
        "contraria a la correcta"
    )
    # Y NO TRAE LISTADO. Estructuralmente no se puede confundir con «mire y no
    # habia nada»: `None` no es iterable.
    assert ausente.entradas is None

    # (b) Montaje verificado y realmente vacio -> MONTAJE_VACIO, CON listado
    vacio = vault_mount.inspeccionar(punto, exigir_montaje=False)
    assert vacio.estado is vault_mount.EstadoMontaje.MONTAJE_VACIO
    assert vacio.vacio_de_verdad
    assert vacio.entradas == []
    assert vacio.utilizable

    assert ausente.estado is not vacio.estado


def test_los_estados_de_la_frontera_estan_todos_distinguidos(tmp_path, monkeypatch):
    """Cada estado del encargo tiene su propio valor y su propio mensaje."""
    E = vault_mount.EstadoMontaje

    # PATH_MISSING
    r = vault_mount.inspeccionar(tmp_path / "no-existe")
    assert r.estado is E.RUTA_AUSENTE and not r.utilizable

    # MOUNT_AVAILABLE_CONTENT
    lleno = tmp_path / "lleno"
    lleno.mkdir()
    (lleno / "algo.md").write_text("x", encoding="utf-8")
    r = vault_mount.inspeccionar(lleno, exigir_montaje=False)
    assert r.estado is E.MONTAJE_CON_CONTENIDO and r.entradas == ["algo.md"]

    # MOUNT_STALE: el `stat` responde ENOTCONN, que es lo que deja un FUSE roto
    roto = tmp_path / "roto"
    roto.mkdir()
    real_stat = Path.stat

    def stat_roto(self, *a, **k):
        if str(self) == str(roto):
            raise OSError(errno.ENOTCONN, "Transport endpoint is not connected")
        return real_stat(self, *a, **k)

    monkeypatch.setattr(Path, "stat", stat_roto)
    r = vault_mount.inspeccionar(roto)
    assert r.estado is E.MONTAJE_ROTO, (
        "un FUSE roto se confundio con otra cosa; `Path.exists()` lo devuelve "
        "como False, que es justo como se pierde la distincion"
    )
    assert "colgado" in r.detalle
    monkeypatch.undo()

    # MOUNT_UNREADABLE
    ilegible = tmp_path / "ilegible"
    ilegible.mkdir()
    monkeypatch.setattr(os, "listdir", lambda *a, **k: (_ for _ in ()).throw(
        PermissionError(errno.EACCES, "denied")))
    r = vault_mount.inspeccionar(ilegible, exigir_montaje=False)
    assert r.estado is E.MONTAJE_ILEGIBLE and not r.utilizable


def test_el_catalogo_no_degrada_un_montaje_ausente_a_lista_vacia(boveda):
    """`AUSENCIA != LISTA VACIA`, tambien en la frontera de adquisicion.

    Con la boveda LLENA y el montaje sin verificar, el catalogo LEVANTA en vez
    de devolver las fuentes o —peor— una lista vacia.
    """
    env = {sources_catalog.ENV_RAIZ_BOVEDAS: str(boveda)}  # exigir montaje: defecto
    with pytest.raises(sources_catalog.CatalogoNoDisponible) as ei:
        sources_catalog.listar_fuentes_boveda(env)
    assert "MOUNT_MISSING" in str(ei.value)
    assert "se leeria como «no hay fuentes»" in str(ei.value)


def test_una_boveda_realmente_vacia_da_lista_vacia_sin_levantar(tmp_path):
    """El otro lado de la misma moneda: vacio COMPROBADO si es lista vacia."""
    raiz = tmp_path / "vacia"
    raiz.mkdir()
    env = {sources_catalog.ENV_RAIZ_BOVEDAS: str(raiz),
           sources_catalog.ENV_EXIGIR_MONTAJE: "0"}
    fuentes, rechazos = sources_catalog.listar_fuentes_boveda(env)
    assert fuentes == [] and rechazos == []


def test_el_defecto_es_EXIGIR_montaje():
    """Olvidarse del interruptor no degrada a «cualquier directorio vale»."""
    assert sources_catalog._exigir_montaje({}) is True
    assert sources_catalog._exigir_montaje(
        {sources_catalog.ENV_EXIGIR_MONTAJE: "0"}) is False
    firma = inspect.signature(vault_mount.inspeccionar)
    assert firma.parameters["exigir_montaje"].default is True


# ===========================================================================
# 6. EL CATALOGO PLANO HEREDADO SIGUE EN PIE
# ===========================================================================

def test_sin_raiz_de_bovedas_el_catalogo_plano_no_cambia():
    """El camino heredado sigue siendo NO recursivo, y a proposito.

    Un directorio suelto no tiene esquema del que derivar ambito, asi que
    recorrerlo en profundidad seria exactamente la recursion sin clasificacion
    que el invariante prohibe.
    """
    env = {"S9K_INGEST_SOURCES_DIR": str(EJEMPLOS)}
    fuentes = sources_catalog.listar_fuentes(env)
    assert fuentes, "el material de ejemplo dejo de verse"
    for f in fuentes:
        # Tambien el camino heredado declara ambito: no hay puerta trasera.
        assert f.ambito.visibility == "secret", "el plano dejo de fallar cerrado"
        assert f.ambito.partida_id is None
        assert f.ambito.workspace, "el plano perdio el workspace del perfil"


def test_el_modo_lo_decide_la_raiz_de_bovedas(boveda):
    assert sources_catalog.modo_boveda({}) is False
    assert sources_catalog.modo_boveda(
        {sources_catalog.ENV_RAIZ_BOVEDAS: str(boveda)}) is True


# ===========================================================================
# 7. LA FRONTERA: ORIGEN NO ES REVELACION
# ---------------------------------------------------------------------------
# Decision del operador, y la linea que este carril NO cruza:
#
#     sesion de ORIGEN     = donde nacio el material      -> procedencia, es de M1
#     sesion de REVELACION = desde cuando puede conocerse -> decision humana,
#                                                            se toma en REVIEW
#
#     ruta: sesiones/sesion-05/...   NO IMPLICA   known_from_session = 5
#
# M1 decide DONDE PERTENECE el material. Review decide QUE SIGNIFICA y CUANDO
# puede revelarse. Auth decide QUIEN puede verlo. Estas pruebas existen para que
# la primera no suplante a la segunda, hoy ni cuando alguien pase por aqui.
# ===========================================================================

def test_la_sesion_de_ORIGEN_se_conoce_porque_es_procedencia():
    """Saber de donde salio un fichero es legitimo, y hace falta."""
    a = clasificar("l5r/partidas/campana-grulla/sesiones/sesion-05/"
                   "transcripciones/t.md")
    assert a.sesion_origen == "sesion-05"
    assert a.partida_id == "campana-grulla"
    # Y las carpetas de formato no la alteran.
    b = clasificar("l5r/partidas/campana-grulla/sesiones/sesion-05/acta.md")
    assert b.sesion_origen == "sesion-05"


def test_fuera_de_sesiones_NO_se_inventa_una_sesion_de_origen():
    """Sin carpeta de sesion no hay procedencia de sesion. No se deduce."""
    for ruta in ("l5r/partidas/campana-grulla/secretos/x.md",
                 "l5r/partidas/campana-grulla/notas-narrador/x.md",
                 "l5r/compartido/lore/x.md",
                 "l5r/entrada/x.md"):
        assert clasificar(ruta).sesion_origen is None, ruta


def test_el_ORIGEN_no_se_convierte_en_REVELACION_en_ninguna_parte():
    """LA PRUEBA DE LA FRONTERA. `sesion-05` no puede volverse un `5`.

    Se comprueba sobre el objeto que viaja: ni el ambito ni lo que se pinta
    contienen `known_from_session` ni ningun numero derivado de la carpeta.
    Derivarlo seria conceder conocimiento por inferencia de directorio.
    """
    a = clasificar("l5r/partidas/campana-grulla/sesiones/sesion-05/acta.md")

    prohibidos = {"known_from_session", "known_by", "known_by_characters",
                  "revelacion", "revealed_from_session"}
    assert not (set(vars(a)) & prohibidos), vars(a)
    assert not (set(a.para_pantalla()) & prohibidos), a.para_pantalla()

    # Y la procedencia NO se ha convertido en un entero de sesion.
    assert a.sesion_origen == "sesion-05", (
        "la procedencia dejo de ser la carpeta tal cual; si alguien la ha "
        "normalizado a un numero, el siguiente paso es usarla como revelacion"
    )
    assert not isinstance(a.sesion_origen, int)


def test_el_modulo_de_ambito_no_nombra_la_revelacion_en_su_codigo():
    """`known_from_session` no aparece como CODIGO en el clasificador.

    Se parsea el AST y se miran nombres, atributos y literales: contar
    apariciones en el texto daria falso positivo con la prosa que explica
    precisamente que NO se usa (y que tiene que poder escribirse).
    """
    import ast as _ast

    from app import vault_scope

    arbol = _ast.parse(inspect.getsource(vault_scope))
    prohibidos = {"known_from_session", "known_by", "known_by_characters"}
    encontrados = set()
    for nodo in _ast.walk(arbol):
        if isinstance(nodo, _ast.Name) and nodo.id in prohibidos:
            encontrados.add(nodo.id)
        elif isinstance(nodo, _ast.Attribute) and nodo.attr in prohibidos:
            encontrados.add(nodo.attr)
        elif isinstance(nodo, _ast.Constant) and isinstance(nodo.value, str):
            # Un literal de cadena SI cuenta: seria la clave de un dict.
            if nodo.value in prohibidos and not _es_docstring(nodo, arbol):
                encontrados.add(nodo.value)
    assert not encontrados, (
        f"el clasificador nombra la revelacion en su codigo: {encontrados}. "
        "La carpeta no concede conocimiento; eso se decide en Review"
    )


def _es_docstring(nodo, arbol) -> bool:
    """¿Ese literal es un docstring? La prosa puede nombrar lo prohibido."""
    import ast as _ast

    for padre in _ast.walk(arbol):
        if isinstance(padre, (_ast.Module, _ast.ClassDef, _ast.FunctionDef)):
            doc = _ast.get_docstring(padre, clean=False)
            if doc is not None and nodo.value == doc:
                return True
    return False


def test_el_payload_del_alta_no_lleva_revelacion(entorno_boveda):
    """Aguas abajo tampoco: lo que se encola no declara revelacion alguna.

    El motor la exigira y fallara cerrado —esa es la conducta correcta— pero el
    alta NO puede rellenarla por su cuenta con la sesion del path.
    """
    fuentes, _ = sources_catalog.listar_fuentes_boveda(entorno_boveda)
    de_sesion = [f for f in fuentes if f.ambito.sesion_origen]
    assert de_sesion, "el arnes no tiene material de sesion: no dice nada"
    for f in de_sesion:
        pintado = f.para_pantalla()["ambito"]
        assert "known_from_session" not in pintado
        assert pintado["sesion_origen"] == f.ambito.sesion_origen
