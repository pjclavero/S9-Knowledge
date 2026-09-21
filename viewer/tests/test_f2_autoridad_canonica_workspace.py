# -*- coding: utf-8 -*-
"""CORTE F-2 — La autoridad canonica del workspace, y sus CINCO negativos.

Cada prueba de aqui esta escrita para poder ponerse ROJA **por su causa**, no
solo para salir verde. Por eso ninguna comprueba solo el valor: comprueban el
CODIGO y, donde importa, el MENSAJE. Un rojo con un valor pelado
(`assert x == 'leyenda'`) se lee igual que un rojo sin causa, y ya nos ha
costado una ronda.

LOS CINCO NEGATIVOS EXIGIDOS Y DONDE VIVEN

  N1  perfil=A / env=A                  -> verde        `test_n1_*`
  N2  perfil=A / env=B                  -> ROJO por divergencia   `test_n2_*`
  N3  perfil=A / env ausente            -> fallback solo si el contrato lo
                                           permite (aqui NO: manda el perfil)
                                                         `test_n3_*`
  N4  workspace ajeno/inexistente en env -> NO se vuelve autoridad
                                                         `test_n4_*`
  N5  quitar la comparacion del perfil  -> el gate se pone ROJO
                                           (arnes de mutacion:
                                            `scripts/calibracion/f2_autoridad_workspace.py`,
                                            mas `test_n5_*` aqui, que comprueba
                                            que la comparacion EXISTE y de que
                                            depende)

  SIMETRICO  una configuracion legitima NO se bloquea     `test_simetrico_*`

EL TECHO DE ESTAS PRUEBAS: se ejercita `resolver()` sobre un entorno que se le
pasa y sobre arboles de fichero REALES en `tmp_path`. No hay dobles del perfil:
lo que se lee es un `perfil-operador.json` de verdad, por el mismo codigo del
producto (`sources_catalog._workspace_declarado`). Lo que estas pruebas NO
alcanzan es el camino que materializa en Neo4j: eso lo mide
`viewer/tests/test_f2_vault_workspace_hasta_neo4j.py`, que exige Docker.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.authz import autoridad_workspace as autoridad

WS_PERFIL = "ws-perfil-a"
WS_OTRO = "ws-entorno-b"


# ---------------------------------------------------------------------------
# Utillaje: bovedas de verdad en disco. Sin dobles.
# ---------------------------------------------------------------------------
def _escribir_perfil(destino: Path, workspace: str) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps({"workspace": workspace}, ensure_ascii=False), encoding="utf-8"
    )


@pytest.fixture
def boveda_plana(tmp_path: Path):
    """Directorio de fuentes PLANO con su perfil. Devuelve el entorno base."""
    raiz = tmp_path / "fuentes"
    _escribir_perfil(raiz / "perfil-operador.json", WS_PERFIL)
    return {"S9K_INGEST_SOURCES_DIR": str(raiz)}


@pytest.fixture
def sin_perfil(tmp_path: Path):
    """Directorio de fuentes que existe pero NO declara nada."""
    raiz = tmp_path / "fuentes-mudas"
    raiz.mkdir(parents=True)
    (raiz / "una-nota.md").write_text("texto", encoding="utf-8")
    return {"S9K_INGEST_SOURCES_DIR": str(raiz)}


# ---------------------------------------------------------------------------
# CONTROL POSITIVO DE LA PROPIA TABLA
# ---------------------------------------------------------------------------
# Todo arnes que mida una AUSENCIA lleva dentro un control de resultado
# conocido. Aqui el instrumento es `_escribir_perfil` + `resolver`: si el
# instrumento no pudiera LEER un perfil, todos los casos de «no hay perfil»
# saldrian verdes por la razon equivocada y esta tabla certificaria nada.
def test_control_positivo_el_instrumento_lee_un_perfil_de_verdad(boveda_plana):
    """Si esto falla, NINGUN otro resultado de este fichero vale."""
    declaradas = autoridad.declaraciones_de_perfil(boveda_plana)
    assert declaradas == [WS_PERFIL], (
        "el instrumento no sabe leer un perfil de boveda escrito por el propio "
        "arnes: cualquier caso de AUSENCIA de este fichero seria un falso verde"
    )


def test_control_positivo_el_instrumento_distingue_ausencia_de_valor(sin_perfil):
    """El otro lado del mismo control: sabe decir que NO hay declaracion."""
    assert autoridad.declaraciones_de_perfil(sin_perfil) == [], (
        "el instrumento devuelve una declaracion donde no hay perfil: estaria "
        "inventando la autoridad que este corte existe para fijar"
    )


# ---------------------------------------------------------------------------
# N1 — perfil=A / env=A -> verde
# ---------------------------------------------------------------------------
def test_n1_perfil_y_entorno_de_acuerdo_resuelven_y_lo_dicen(boveda_plana):
    env = {**boveda_plana, "S9K_DEFAULT_WORKSPACE": WS_PERFIL}
    resultado = autoridad.resolver(env)

    assert resultado.codigo == autoridad.COD_PERFIL_CONFIRMADO, resultado.diagnostico()
    assert resultado.valor == WS_PERFIL
    # LA PROCEDENCIA ES LA MITAD DEL RESULTADO: coincidir no convierte al
    # entorno en autoridad. Si esto se relaja, el entorno vuelve a competir.
    assert resultado.procedencia == autoridad.PROCEDENCIA_PERFIL, (
        "con perfil y entorno de acuerdo la autoridad sigue siendo el PERFIL; "
        f"se sello '{resultado.procedencia}'"
    )


# ---------------------------------------------------------------------------
# N2 — perfil=A / env=B -> ROJO por divergencia
# ---------------------------------------------------------------------------
def test_n2_divergencia_no_resuelve_y_nombra_las_dos_declaraciones(boveda_plana):
    env = {**boveda_plana, "S9K_DEFAULT_WORKSPACE": WS_OTRO}
    resultado = autoridad.resolver(env)

    assert resultado.codigo == autoridad.COD_DIVERGENTE
    assert resultado.valor == "", (
        "con las dos autoridades hablando y diciendo cosas distintas se eligio "
        f"'{resultado.valor}': eso es escoger en silencio, que es el defecto"
    )
    assert resultado.procedencia == autoridad.PROCEDENCIA_NINGUNA

    mensaje = resultado.diagnostico()
    # EL MENSAJE ES LA PRUEBA. Un fail-closed sin diagnostico es exactamente lo
    # que ya habia (400 sin aviso). Tiene que decir QUE declara cada una.
    assert autoridad.COD_DIVERGENTE in mensaje
    assert WS_PERFIL in mensaje and WS_OTRO in mensaje, (
        "el diagnostico no nombra las dos declaraciones; el operador no puede "
        f"saber que corregir: {mensaje!r}"
    )
    assert "S9K_DEFAULT_WORKSPACE" in mensaje
    # NO SE FABRICA CAUSALIDAD: el modulo no sabe cual esta mal y no lo dice.
    assert "no se elige por ti" in mensaje


def test_n2_exigir_levanta_con_el_codigo_antes_de_operar(boveda_plana):
    env = {**boveda_plana, "S9K_DEFAULT_WORKSPACE": WS_OTRO}
    with pytest.raises(autoridad.WorkspaceSinAutoridad) as fallo:
        autoridad.exigir(env)
    assert fallo.value.codigo == autoridad.COD_DIVERGENTE
    # Ni rutas ni secretos en el texto que puede acabar en un log o en pantalla.
    assert str(fallo.value).count("/") == 0, (
        f"el diagnostico publica una ruta interna: {fallo.value}"
    )


# ---------------------------------------------------------------------------
# N3 — perfil=A / env ausente -> fallback SOLO si el contrato lo permite
# ---------------------------------------------------------------------------
def test_n3_con_perfil_y_sin_entorno_manda_el_perfil_no_el_fallback(boveda_plana):
    """AUSENCIA != CERO en la otra direccion: falta el entorno, no la autoridad."""
    resultado = autoridad.resolver(dict(boveda_plana))

    assert resultado.codigo == autoridad.COD_PERFIL, resultado.diagnostico()
    assert resultado.valor == WS_PERFIL
    assert resultado.procedencia == autoridad.PROCEDENCIA_PERFIL
    assert resultado.declarado_por_entorno == ""


def test_n3_el_fallback_solo_se_usa_cuando_NO_hay_perfil_y_se_sella(sin_perfil):
    """La unica rama en la que el contrato PERMITE el entorno, y lo declara."""
    env = {**sin_perfil, "S9K_DEFAULT_WORKSPACE": WS_OTRO}
    resultado = autoridad.resolver(env)

    assert resultado.codigo == autoridad.COD_FALLBACK, resultado.diagnostico()
    assert resultado.valor == WS_OTRO
    assert resultado.procedencia == autoridad.PROCEDENCIA_FALLBACK, (
        "el fallback se sello como si fuera autoridad de perfil: quien lea el "
        "resultado no podria distinguir una declaracion de una herencia"
    )
    assert autoridad.COD_FALLBACK in resultado.diagnostico()


def test_n3_sin_perfil_y_sin_entorno_no_hay_workspace_y_se_dice(sin_perfil):
    """«No hay perfil» NO es «el workspace por defecto»."""
    resultado = autoridad.resolver(dict(sin_perfil))

    assert resultado.codigo == autoridad.COD_INDETERMINADO
    assert resultado.valor == ""
    assert resultado.codigo in autoridad.CODIGOS_FAIL_CLOSED


# ---------------------------------------------------------------------------
# N4 — un workspace ajeno/inexistente NO se vuelve autoridad por estar en env
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "intruso",
    ["ws-que-no-existe", "leyenda", "juego:ws-perfil-a", " ws-perfil-a-x ", "../etc"],
)
def test_n4_el_entorno_no_puede_imponer_un_workspace_ajeno(boveda_plana, intruso):
    """Da igual lo que diga el entorno: con perfil presente, no manda.

    Incluye `juego:ws-perfil-a` y ` ws-perfil-a-x ` a proposito: son los casos
    en los que una normalizacion demasiado amable convertiria un ambito ajeno
    en «el mismo». No hay tal normalizacion, y esta prueba lo fija.
    """
    env = {**boveda_plana, "S9K_DEFAULT_WORKSPACE": intruso}
    resultado = autoridad.resolver(env)

    assert resultado.valor != intruso, (
        f"'{intruso}' se convirtio en el workspace efectivo por aparecer en el "
        "entorno: el entorno volvio a ser autoridad"
    )
    assert resultado.codigo == autoridad.COD_DIVERGENTE
    assert resultado.valor == ""


def test_n4_dos_bovedas_con_workspaces_distintos_no_eligen_una(tmp_path):
    """Y tampoco se inventa autoridad cuando hay VARIAS declaraciones.

    Elegir una en silencio seria fabricar el modelo usuario -> varios
    workspaces, que esta expresamente diferido. Se NOMBRA el caso.
    """
    raiz = tmp_path / "bovedas"
    _escribir_perfil(raiz / "juego-uno" / "perfil-operador.json", WS_PERFIL)
    _escribir_perfil(raiz / "juego-dos" / "perfil-operador.json", WS_OTRO)
    env = {"S9K_VAULT_ROOT": str(raiz), "S9K_DEFAULT_WORKSPACE": WS_PERFIL}

    resultado = autoridad.resolver(env)

    assert resultado.codigo == autoridad.COD_VARIOS_PERFILES, resultado.diagnostico()
    assert resultado.valor == ""
    assert resultado.perfiles_legibles == 2
    assert "2" in resultado.diagnostico()


def test_n4_una_sola_boveda_en_el_arbol_si_resuelve(tmp_path):
    """Control positivo del caso anterior: el modo boveda NO es rojo por serlo.

    Sin esto, `test_n4_dos_bovedas...` saldria verde aunque el recorrido del
    arbol estuviera roto y no encontrara NINGUN perfil.
    """
    raiz = tmp_path / "bovedas"
    _escribir_perfil(raiz / "juego-uno" / "perfil-operador.json", WS_PERFIL)
    resultado = autoridad.resolver({"S9K_VAULT_ROOT": str(raiz)})

    assert resultado.valor == WS_PERFIL, resultado.diagnostico()
    assert resultado.procedencia == autoridad.PROCEDENCIA_PERFIL


# ---------------------------------------------------------------------------
# N5 — quitar la comparacion del perfil tiene que poner el gate en ROJO
# ---------------------------------------------------------------------------
# La mutacion de verdad (borrar la comparacion del codigo y ver el rojo) la
# ejecuta `scripts/calibracion/f2_autoridad_workspace.py`, que ademas se
# calibra a si mismo. Aqui se fija lo que esa mutacion tiene que poder romper:
# que la comparacion EXISTE y que el resultado DEPENDE de ella.
def test_n5_el_resultado_depende_de_la_declaracion_del_perfil(tmp_path):
    """Mismo entorno, perfiles distintos -> resultados distintos.

    Si alguien sustituyera el perfil por una constante o dejara de compararlo,
    estas dos llamadas darian lo mismo y esta prueba se pondria roja diciendo
    exactamente eso.
    """
    uno = tmp_path / "a"
    otro = tmp_path / "b"
    _escribir_perfil(uno / "perfil-operador.json", WS_PERFIL)
    _escribir_perfil(otro / "perfil-operador.json", WS_OTRO)

    env_comun = {"S9K_DEFAULT_WORKSPACE": WS_PERFIL}
    a = autoridad.resolver({**env_comun, "S9K_INGEST_SOURCES_DIR": str(uno)})
    b = autoridad.resolver({**env_comun, "S9K_INGEST_SOURCES_DIR": str(otro)})

    # EL DESENLACE COMPLETO EN UNA SOLA AFIRMACION, Y CON SU CAUSA.
    #
    # Aqui habia dos `assert` y el PRIMERO era mudo. La mutacion 1 del arnes
    # (`scripts/calibracion/f2_autoridad_workspace.py`) —quitar la comparacion
    # del perfil— hacia saltar el mudo antes que el que lleva el mensaje, y la
    # prueba se ponia roja sin decir por que. Lo encontro la autocalibracion
    # del arnes, no una lectura del codigo: por eso se deja escrito.
    assert (a.valor, b.valor) == (WS_PERFIL, ""), (
        "cambiar el workspace DECLARADO por el perfil no cambio el desenlace: "
        "el perfil no se esta comparando, y la divergencia no se detectaria. "
        f"Medido: perfil='{WS_PERFIL}' -> {a.codigo}/{a.valor!r}; "
        f"perfil='{WS_OTRO}' -> {b.codigo}/{b.valor!r}"
    )
    assert a.codigo == autoridad.COD_PERFIL_CONFIRMADO, (
        "con perfil y entorno diciendo lo mismo el resolvedor no lo reconocio "
        f"como confirmacion: {a.diagnostico()}"
    )
    assert b.codigo == autoridad.COD_DIVERGENTE, (
        "el perfil declara otra cosa que el entorno y no se llamo divergencia: "
        f"{b.diagnostico()}"
    )


# ---------------------------------------------------------------------------
# SIMETRICO — la deteccion no bloquea una configuracion legitima
# ---------------------------------------------------------------------------
# Un gate que se pone rojo siempre no guarda, molesta. Estas tres son las
# formas legitimas de configurar el despliegue, y las tres tienen que RESOLVER.
@pytest.mark.parametrize(
    "nombre, hacer_env",
    [
        ("solo perfil", lambda base: dict(base)),
        (
            "perfil y entorno de acuerdo",
            lambda base: {**base, "S9K_DEFAULT_WORKSPACE": WS_PERFIL},
        ),
        (
            "entorno con espacios sobrantes",
            lambda base: {**base, "S9K_DEFAULT_WORKSPACE": f"  {WS_PERFIL}  "},
        ),
    ],
)
def test_simetrico_las_configuraciones_legitimas_resuelven(
    boveda_plana, nombre, hacer_env
):
    resultado = autoridad.resolver(hacer_env(boveda_plana))
    assert resultado.resuelto, (
        f"configuracion legitima ({nombre}) bloqueada: {resultado.diagnostico()}"
    )
    assert resultado.valor == WS_PERFIL
    assert resultado.codigo not in autoridad.CODIGOS_FAIL_CLOSED


def test_simetrico_el_fallback_puro_tambien_es_legitimo(sin_perfil):
    """Un despliegue sin bovedas (solo entorno) sigue arrancando."""
    resultado = autoridad.resolver(
        {**sin_perfil, "S9K_DEFAULT_WORKSPACE": "un-despliegue-sin-boveda"}
    )
    assert resultado.resuelto and resultado.valor == "un-despliegue-sin-boveda"
    assert resultado.procedencia == autoridad.PROCEDENCIA_FALLBACK
