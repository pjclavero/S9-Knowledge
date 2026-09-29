# -*- coding: utf-8 -*-
"""CORTE 6B-2(a) — escritor del nombre humano de un WORKSPACE.

Testigos del contrato de `app.vault_writer`:

  1. C1 — los TRES estados: conforme (editable), legible_no_conforme (con
     causa), inválido (fail-closed).
  2. El escritor NUNCA usa `GameProfile.to_json()`: no reordena claves como
     ese método sí haría. Ojo (R1, segunda ronda): esto NO es lo mismo que
     "el diff en disco es mínimo" -- ese diff mínimo sólo se observa cuando
     el perfil en disco YA estaba en el formato de salida (`indent=2`); ver
     el punto 9 para el caso real (compacto).
  3. El escritor muta el dict ORIGINAL: el resto de claves SOBREVIVEN
     SEMÁNTICAMENTE y en el mismo orden dentro del `dict`, no
     necesariamente byte a byte en el fichero final (eso depende del
     formato de entrada, ver punto 9).
  4. Concurrencia optimista: huella distinta -> 409 (`ConflictoEscrituraError`)
     y lo que escribió "el otro" sigue en disco. Control negativo: sin
     interferencia, ningún conflicto.
  5. El predicado de destino seguro se ejerce de verdad, y puede decir que NO
     (directorio de solo lectura).
  6. symlink rechazado, nunca se crea el directorio, nunca se sale de la
     bóveda.
  7. Los canarios de la sonda no aparecen en el catálogo de fuentes.
  8. (revisión independiente de PR #258) D2 — label vacío/sólo-espacios
     BORRA `metadata.label`, nunca escribe cadena vacía. D3 — contrato de
     entrada en el SERVIDOR: tope de longitud y caracteres de control
     rechazados, con su negativo (entrada válida en el límite).
  9. (segunda ronda de revisión) R1 — NO-OP = NO ESCRIBE, medido sobre un
     perfil REAL (compacto, una sola línea): ni reformatea el documento
     entero, ni crea `metadata` de la nada en un borrado sin label previo.
 10. R3 — el filtro de control se amplía de C0+DEL a categoría Unicode
     (C1, formato invisible, separadores de línea/párrafo), con control
     negativo de Unicode legítimo multiidioma.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from app import sources_catalog, vault_writer as vw

_PERFIL_CONFORME = json.loads(
    (Path(__file__).resolve().parents[2] / "examples" / "ingesta-v3" / "perfil-operador.json")
    .read_text(encoding="utf-8")
)


def _escribir_perfil(carpeta: Path, datos: dict) -> None:
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / sources_catalog.NOMBRE_PERFIL).write_text(
        json.dumps(datos, indent=2), encoding="utf-8"
    )


def _escribir_perfil_compacto(carpeta: Path, datos: dict) -> None:
    """R1 (revisión independiente de PR #258, segunda ronda): el perfil REAL
    de la bóveda está en UNA SOLA LÍNEA compacta, no en el formato
    `indent=2` que produce el propio escritor. `_escribir_perfil` (arriba)
    fabrica su fixture ya con el formato de SALIDA del escritor -- por eso
    ningún testigo que la use puede ver un reflow: coincide por construcción.
    Este helper escribe el formato de un perfil real."""
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / sources_catalog.NOMBRE_PERFIL).write_text(
        json.dumps(datos, separators=(",", ":")), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# 1. C1 — los tres estados
# ---------------------------------------------------------------------------

def test_c1_perfil_conforme_es_editable(tmp_path):
    carpeta = tmp_path / "l5r"
    _escribir_perfil(carpeta, _PERFIL_CONFORME)
    lectura = vw.leer_estado_perfil(carpeta / sources_catalog.NOMBRE_PERFIL)
    assert lectura.estado == vw.EstadoPerfil.CONFORME
    assert lectura.causa is None


def test_c1_perfil_legible_no_conforme_tiene_causa_visible(tmp_path):
    carpeta = tmp_path / "l5r"
    # Una clave desconocida basta: `from_dict` de V3Document rechaza contratos
    # cerrados por campos extra en el primer nivel.
    sucio = {**_PERFIL_CONFORME, "campo_no_declarado_por_el_contrato": True}
    _escribir_perfil(carpeta, sucio)
    lectura = vw.leer_estado_perfil(carpeta / sources_catalog.NOMBRE_PERFIL)
    assert lectura.estado == vw.EstadoPerfil.LEGIBLE_NO_CONFORME
    assert lectura.causa == vw.CAUSA_NO_CONFORME


def test_c1_perfil_invalido_es_el_fail_closed_actual(tmp_path):
    carpeta = tmp_path / "l5r"
    carpeta.mkdir(parents=True)
    (carpeta / sources_catalog.NOMBRE_PERFIL).write_text("{no es json", encoding="utf-8")
    lectura = vw.leer_estado_perfil(carpeta / sources_catalog.NOMBRE_PERFIL)
    assert lectura.estado == vw.EstadoPerfil.INVALIDO


def test_c1_escritor_rechaza_editar_un_perfil_no_conforme(tmp_path):
    carpeta = tmp_path / "l5r"
    sucio = {**_PERFIL_CONFORME, "campo_no_declarado_por_el_contrato": True}
    _escribir_perfil(carpeta, sucio)
    huella = vw.huella_de(carpeta / sources_catalog.NOMBRE_PERFIL)
    with pytest.raises(vw.EscrituraRechazadaError) as exc:
        vw.escribir_label_workspace(carpeta, "Nuevo Nombre", huella)
    assert exc.value.estado == vw.EstadoPerfil.LEGIBLE_NO_CONFORME
    # Y el escritor NO normalizó ni borró la clave extra para "arreglarlo".
    en_disco = json.loads((carpeta / sources_catalog.NOMBRE_PERFIL).read_text())
    assert en_disco["campo_no_declarado_por_el_contrato"] is True


def test_c1_escritor_rechaza_editar_un_perfil_invalido(tmp_path):
    carpeta = tmp_path / "l5r"
    carpeta.mkdir(parents=True)
    (carpeta / sources_catalog.NOMBRE_PERFIL).write_text("{no es json", encoding="utf-8")
    with pytest.raises(vw.EscrituraRechazadaError) as exc:
        vw.escribir_label_workspace(
            carpeta, "Nuevo Nombre",
            vw.Huella(sha256="x" * 64, st_size=0, st_dev=0, st_ino=0),
        )
    assert exc.value.estado == vw.EstadoPerfil.INVALIDO


# ---------------------------------------------------------------------------
# 2 y 3 — nunca `to_json()`, muta el dict original, diff mínimo
# ---------------------------------------------------------------------------

def test_la_escritura_no_reflowea_el_documento_muta_una_sola_clave(tmp_path):
    carpeta = tmp_path / "l5r"
    _escribir_perfil(carpeta, _PERFIL_CONFORME)
    ruta = carpeta / sources_catalog.NOMBRE_PERFIL
    antes = ruta.read_text(encoding="utf-8")
    huella = vw.huella_de(ruta)

    vw.escribir_label_workspace(carpeta, "La Cofradía de Ámbar", huella)

    despues = ruta.read_text(encoding="utf-8")
    antes_lineas = antes.splitlines()
    despues_lineas = despues.splitlines()

    # Round-trip casi exacto: la ÚNICA clave que se añade es `metadata` (el
    # fixture no la traía), insertada al final del objeto -- lo que cambia en
    # el texto es (a) la coma de la línea que pasa a no-ser-la-última y (b)
    # las líneas nuevas de `metadata`. NINGUNA otra línea del documento se
    # reordena ni cambia de contenido -- lo que sí haría `to_json()`.
    assert len(despues_lineas) >= len(antes_lineas)
    assert antes_lineas[:-2] == despues_lineas[: len(antes_lineas) - 2], (
        "el documento se reordenó más allá de la única clave añadida: "
        "esto sería la firma de un `to_json()` reflow"
    )

    datos = json.loads(despues)
    assert datos["metadata"]["label"] == "La Cofradía de Ámbar"
    # La comprobación FUERTE, y la que no depende del formato de entrada: el
    # documento reconstruido sin `metadata` es SEMÁNTICAMENTE idéntico al
    # original (mismas claves, mismos valores). Auditoría acotada (segunda
    # ronda de revisión): este fixture se fabrica con `indent=2` -- el mismo
    # formato que produce el escritor -- así que la comparación de LÍNEAS de
    # arriba (`antes_lineas[:-2] == despues_lineas[...]`) sólo prueba algo
    # sobre ESTE formato. Lo que SÍ generaliza a cualquier formato de
    # entrada (incluido el real, compacto) es esta igualdad de diccionarios:
    # si `to_json()` reordenara u omitiera una clave, esta comparación lo
    # vería igual sobre un fixture compacto que sobre uno indentado.
    sin_metadata = dict(datos)
    sin_metadata.pop("metadata")
    assert sin_metadata == _PERFIL_CONFORME


def test_la_lectura_de_salida_tras_escribir_sigue_conforme(tmp_path):
    carpeta = tmp_path / "l5r"
    _escribir_perfil(carpeta, _PERFIL_CONFORME)
    ruta = carpeta / sources_catalog.NOMBRE_PERFIL
    huella = vw.huella_de(ruta)
    resultado = vw.escribir_label_workspace(carpeta, "Nuevo Nombre", huella)
    assert resultado.estado == vw.EstadoPerfil.CONFORME
    assert resultado.label_actual == "Nuevo Nombre"


# ---------------------------------------------------------------------------
# 4 — concurrencia optimista: 409 con huella distinta, y su control negativo
# ---------------------------------------------------------------------------

def test_409_si_el_perfil_cambio_desde_que_se_leyo(tmp_path):
    carpeta = tmp_path / "l5r"
    _escribir_perfil(carpeta, _PERFIL_CONFORME)
    ruta = carpeta / sources_catalog.NOMBRE_PERFIL
    huella_vieja = vw.huella_de(ruta)

    # "Otro" editor escribe primero.
    otro = {**_PERFIL_CONFORME, "metadata": {"label": "Lo que puso el otro"}}
    ruta.write_text(json.dumps(otro, indent=2), encoding="utf-8")

    with pytest.raises(vw.ConflictoEscrituraError):
        vw.escribir_label_workspace(carpeta, "Lo que intento yo", huella_vieja)

    # LO QUE ESCRIBIÓ EL OTRO SIGUE EN DISCO. Nunca last-write-wins.
    en_disco = json.loads(ruta.read_text())
    assert en_disco["metadata"]["label"] == "Lo que puso el otro"


def test_control_negativo_sin_interferencia_ningun_409(tmp_path):
    carpeta = tmp_path / "l5r"
    _escribir_perfil(carpeta, _PERFIL_CONFORME)
    ruta = carpeta / sources_catalog.NOMBRE_PERFIL
    huella = vw.huella_de(ruta)
    # Sin que nada más toque el fichero, la escritura tiene que pasar limpia.
    resultado = vw.escribir_label_workspace(carpeta, "Sin Interferencia", huella)
    assert resultado.estado == vw.EstadoPerfil.CONFORME
    assert resultado.label_actual == "Sin Interferencia"


def test_revalidacion_justo_antes_de_escribir_tambien_detecta_el_cambio(tmp_path, monkeypatch):
    """La ventana de TOCTOU: el cambio ocurre DESPUÉS del primer chequeo,
    justo antes de `os.replace`. La segunda huella (`huella_de` llamada
    dentro de `escribir_label_workspace` inmediatamente antes de escribir)
    tiene que detectarlo también."""
    carpeta = tmp_path / "l5r"
    _escribir_perfil(carpeta, _PERFIL_CONFORME)
    ruta = carpeta / sources_catalog.NOMBRE_PERFIL
    huella_capturada = vw.huella_de(ruta)

    original_destino = vw.destino_admite_escritura_segura

    def _destino_que_cambia_el_fichero_a_mitad(directorio, **kwargs):
        # Simula a "otro" escribiendo justo entre el primer chequeo de huella
        # y la comprobación final antes de `os.replace`.
        otro = {**_PERFIL_CONFORME, "metadata": {"label": "Carrera ganada por el otro"}}
        ruta.write_text(json.dumps(otro, indent=2), encoding="utf-8")
        return original_destino(directorio, **kwargs)

    monkeypatch.setattr(vw, "destino_admite_escritura_segura", _destino_que_cambia_el_fichero_a_mitad)

    with pytest.raises(vw.ConflictoEscrituraError):
        vw.escribir_label_workspace(carpeta, "Lo que intento yo", huella_capturada)

    en_disco = json.loads(ruta.read_text())
    assert en_disco["metadata"]["label"] == "Carrera ganada por el otro"


# ---------------------------------------------------------------------------
# 5 — el predicado de destino seguro se ejerce, y puede decir que NO
# ---------------------------------------------------------------------------

def test_destino_admite_escritura_segura_en_un_directorio_normal(tmp_path):
    carpeta = tmp_path / "l5r"
    carpeta.mkdir()
    ok, motivo = vw.destino_admite_escritura_segura(carpeta, forzar=True)
    assert ok is True
    assert motivo == ""


def test_predicado_de_destino_dice_que_no_en_un_directorio_de_solo_lectura(tmp_path):
    if os.name != "posix" or os.geteuid() == 0:  # pragma: no cover
        pytest.skip("la sonda de permisos exige un usuario no-root en POSIX")
    carpeta = tmp_path / "l5r"
    carpeta.mkdir()
    modo_original = carpeta.stat().st_mode
    carpeta.chmod(stat.S_IREAD | stat.S_IEXEC)
    try:
        ok, motivo = vw.destino_admite_escritura_segura(carpeta, forzar=True)
        assert ok is False
        assert motivo
    finally:
        carpeta.chmod(modo_original)


def test_escritura_rechazada_si_el_destino_no_es_seguro(tmp_path, monkeypatch):
    carpeta = tmp_path / "l5r"
    _escribir_perfil(carpeta, _PERFIL_CONFORME)
    huella = vw.huella_de(carpeta / sources_catalog.NOMBRE_PERFIL)
    monkeypatch.setattr(
        vw, "destino_admite_escritura_segura",
        lambda directorio, **kw: (False, "el disco simulado rechaza el reemplazo atómico"),
    )
    with pytest.raises(vw.DestinoNoSeguroError):
        vw.escribir_label_workspace(carpeta, "Nuevo Nombre", huella)


# ---------------------------------------------------------------------------
# 6 — symlink, nunca mkdir, nunca fuera de bóveda
# ---------------------------------------------------------------------------

def test_symlink_del_perfil_es_rechazado(tmp_path):
    real = tmp_path / "real"
    _escribir_perfil(real, _PERFIL_CONFORME)
    carpeta = tmp_path / "l5r"
    carpeta.mkdir()
    (carpeta / sources_catalog.NOMBRE_PERFIL).symlink_to(real / sources_catalog.NOMBRE_PERFIL)
    huella = vw.huella_de(real / sources_catalog.NOMBRE_PERFIL)
    with pytest.raises(vw.RutaNoSeguraError):
        vw.escribir_label_workspace(carpeta, "Nuevo Nombre", huella)


def test_carpeta_symlink_es_rechazada(tmp_path):
    real = tmp_path / "real"
    _escribir_perfil(real, _PERFIL_CONFORME)
    enlace = tmp_path / "l5r"
    enlace.symlink_to(real)
    huella = vw.huella_de(real / sources_catalog.NOMBRE_PERFIL)
    with pytest.raises(vw.RutaNoSeguraError):
        vw.escribir_label_workspace(enlace, "Nuevo Nombre", huella)


def test_nunca_crea_el_directorio_del_juego(tmp_path):
    carpeta = tmp_path / "no-existe-todavia"
    huella = vw.Huella(sha256="x" * 64, st_size=0, st_dev=0, st_ino=0)
    with pytest.raises(vw.EscrituraRechazadaError):
        vw.escribir_label_workspace(carpeta, "Nuevo Nombre", huella)
    assert not carpeta.exists()


def test_rechaza_una_ruta_que_resuelve_fuera_de_la_boveda_declarada(tmp_path, monkeypatch):
    raiz = tmp_path / "boveda"
    raiz.mkdir()
    monkeypatch.setenv("S9K_VAULT_ROOT", str(raiz))
    fuera = tmp_path / "fuera-de-la-boveda"
    _escribir_perfil(fuera, _PERFIL_CONFORME)
    huella = vw.huella_de(fuera / sources_catalog.NOMBRE_PERFIL)
    with pytest.raises(vw.RutaNoSeguraError):
        vw.escribir_label_workspace(fuera, "Nuevo Nombre", huella)


# ---------------------------------------------------------------------------
# 7 — los canarios de la sonda no ensucian el catálogo de fuentes
# ---------------------------------------------------------------------------

def test_los_canarios_de_la_sonda_no_dejan_residuo(tmp_path):
    carpeta = tmp_path / "l5r"
    carpeta.mkdir()
    vw.destino_admite_escritura_segura(carpeta, forzar=True)
    residuos = [p for p in carpeta.iterdir() if p.name.startswith(vw.PREFIJO_EFIMERO)]
    assert residuos == []


def test_un_residuo_de_sonda_interrumpida_se_excluye_de_la_enumeracion(tmp_path):
    raiz = tmp_path / "boveda"
    juego = raiz / "l5r"
    _escribir_perfil(juego, _PERFIL_CONFORME)
    # Simula una sonda interrumpida a mitad: un canario que NO se limpió.
    (juego / f"{vw.PREFIJO_EFIMERO}residuo").write_text("basura", encoding="utf-8")
    env = {"S9K_VAULT_ROOT": str(raiz), "S9K_VAULT_REQUIRE_MOUNT": "0"}
    fuentes, rechazos = sources_catalog.listar_fuentes_boveda(env)
    nombres = {f.titulo for f in fuentes} | {r["ruta"] for r in rechazos}
    assert not any("residuo" in n or vw.PREFIJO_EFIMERO in n for n in nombres)


# ---------------------------------------------------------------------------
# Huella: sha256 decide, mtime nunca aparece
# ---------------------------------------------------------------------------

def test_huella_ida_y_vuelta_por_texto(tmp_path):
    carpeta = tmp_path / "l5r"
    _escribir_perfil(carpeta, _PERFIL_CONFORME)
    huella = vw.huella_de(carpeta / sources_catalog.NOMBRE_PERFIL)
    reconstruida = vw.Huella.desde_texto(huella.a_texto())
    assert reconstruida == huella


def test_la_huella_no_expone_ni_usa_mtime():
    campos = {f for f in vw.Huella.__dataclass_fields__}
    assert "mtime" not in campos and "mtime_ns" not in campos


# ---------------------------------------------------------------------------
# 8 — D2: borrado del label. D3: contrato de entrada en el servidor.
# (revisión independiente de PR #258)
# ---------------------------------------------------------------------------

def test_label_vacio_borra_metadata_label_en_vez_de_escribir_cadena_vacia(tmp_path):
    carpeta = tmp_path / "l5r"
    con_label = {**_PERFIL_CONFORME, "metadata": {"label": "Nombre previo"}}
    _escribir_perfil(carpeta, con_label)
    ruta = carpeta / sources_catalog.NOMBRE_PERFIL
    huella = vw.huella_de(ruta)

    resultado = vw.escribir_label_workspace(carpeta, "", huella)

    assert resultado.label_actual == ""
    en_disco = json.loads(ruta.read_text())
    assert "label" not in en_disco.get("metadata", {})


def test_label_de_solo_espacios_tambien_borra(tmp_path):
    carpeta = tmp_path / "l5r"
    con_label = {**_PERFIL_CONFORME, "metadata": {"label": "Nombre previo"}}
    _escribir_perfil(carpeta, con_label)
    ruta = carpeta / sources_catalog.NOMBRE_PERFIL
    huella = vw.huella_de(ruta)

    vw.escribir_label_workspace(carpeta, "   ", huella)

    en_disco = json.loads(ruta.read_text())
    assert "label" not in en_disco.get("metadata", {})


def test_borrar_el_label_no_toca_ninguna_otra_clave_de_metadata(tmp_path):
    carpeta = tmp_path / "l5r"
    con_metadata = {**_PERFIL_CONFORME, "metadata": {"label": "Nombre previo", "otra_clave": "sobrevive"}}
    _escribir_perfil(carpeta, con_metadata)
    ruta = carpeta / sources_catalog.NOMBRE_PERFIL
    huella = vw.huella_de(ruta)

    vw.escribir_label_workspace(carpeta, "", huella)

    en_disco = json.loads(ruta.read_text())
    assert en_disco["metadata"]["otra_clave"] == "sobrevive"
    assert "label" not in en_disco["metadata"]


def test_servidor_rechaza_label_que_excede_el_tope_de_longitud(tmp_path):
    carpeta = tmp_path / "l5r"
    _escribir_perfil(carpeta, _PERFIL_CONFORME)
    ruta = carpeta / sources_catalog.NOMBRE_PERFIL
    huella = vw.huella_de(ruta)

    with pytest.raises(vw.EntradaInvalidaError):
        vw.escribir_label_workspace(carpeta, "x" * (vw.LONGITUD_MAXIMA_LABEL + 1), huella)

    en_disco = json.loads(ruta.read_text())
    assert "metadata" not in en_disco


def test_control_negativo_un_label_justo_en_el_tope_se_acepta(tmp_path):
    carpeta = tmp_path / "l5r"
    _escribir_perfil(carpeta, _PERFIL_CONFORME)
    ruta = carpeta / sources_catalog.NOMBRE_PERFIL
    huella = vw.huella_de(ruta)

    resultado = vw.escribir_label_workspace(carpeta, "x" * vw.LONGITUD_MAXIMA_LABEL, huella)
    assert resultado.label_actual == "x" * vw.LONGITUD_MAXIMA_LABEL


@pytest.mark.parametrize("caracter", ["\x00", "\n", "\r", "\t", "\x7f", "\x01"])
def test_servidor_rechaza_caracteres_de_control(tmp_path, caracter):
    carpeta = tmp_path / "l5r"
    _escribir_perfil(carpeta, _PERFIL_CONFORME)
    ruta = carpeta / sources_catalog.NOMBRE_PERFIL
    huella = vw.huella_de(ruta)

    with pytest.raises(vw.EntradaInvalidaError):
        vw.escribir_label_workspace(carpeta, f"nombre{caracter}sucio", huella)

    en_disco = json.loads(ruta.read_text())
    assert "metadata" not in en_disco


def test_control_negativo_acentos_y_simbolos_normales_se_aceptan(tmp_path):
    """El rechazo es de CARACTERES DE CONTROL, no de todo lo no-ASCII: un
    nombre con acentos, eñes o símbolos de puntuación normales tiene que
    seguir pasando."""
    carpeta = tmp_path / "l5r"
    _escribir_perfil(carpeta, _PERFIL_CONFORME)
    ruta = carpeta / sources_catalog.NOMBRE_PERFIL
    huella = vw.huella_de(ruta)

    resultado = vw.escribir_label_workspace(carpeta, "La Cofradía Peña — Año 26", huella)
    assert resultado.label_actual == "La Cofradía Peña — Año 26"


# ---------------------------------------------------------------------------
# 9 — R1 (revisión independiente de PR #258, segunda ronda): NO-OP = NO
# ESCRIBE, medido sobre el formato REAL de un perfil (compacto, una sola
# línea), no sobre el formato `indent=2` que produce el propio escritor.
# ---------------------------------------------------------------------------

def test_no_op_de_borrado_sobre_perfil_compacto_no_reescribe_nada(tmp_path):
    """El escenario exacto que midió el revisor: perfil real compacto, sin
    label, y se guarda con el campo vacío. Antes: 3786->5477 bytes, 1->287
    líneas, `metadata` aparecía de la nada. Ahora: cero bytes tocados."""
    carpeta = tmp_path / "l5r"
    _escribir_perfil_compacto(carpeta, _PERFIL_CONFORME)
    ruta = carpeta / sources_catalog.NOMBRE_PERFIL
    antes_bytes = ruta.read_bytes()
    antes_lineas = antes_bytes.count(b"\n") + 1
    huella = vw.huella_de(ruta)

    resultado = vw.escribir_label_workspace(carpeta, "", huella)

    despues_bytes = ruta.read_bytes()
    despues_lineas = despues_bytes.count(b"\n") + 1
    assert despues_bytes == antes_bytes, (
        f"un no-op reescribió el fichero: {len(antes_bytes)} -> "
        f"{len(despues_bytes)} bytes, {antes_lineas} -> {despues_lineas} líneas"
    )
    assert "metadata" not in json.loads(despues_bytes), (
        "el no-op de borrado CREÓ `metadata` en un perfil que no la tenía"
    )
    assert resultado.label_actual == ""


def test_no_op_guardando_el_mismo_label_sobre_perfil_compacto_no_reescribe_nada(tmp_path):
    """El otro no-op: guardar el MISMO label que ya está, sobre el formato
    real. Tampoco puede reformatear el documento."""
    con_label = {**_PERFIL_CONFORME, "metadata": {"label": "Nombre estable"}}
    carpeta = tmp_path / "l5r"
    _escribir_perfil_compacto(carpeta, con_label)
    ruta = carpeta / sources_catalog.NOMBRE_PERFIL
    antes_bytes = ruta.read_bytes()
    huella = vw.huella_de(ruta)

    resultado = vw.escribir_label_workspace(carpeta, "Nombre estable", huella)

    despues_bytes = ruta.read_bytes()
    assert despues_bytes == antes_bytes, (
        f"un no-op reescribió el fichero: {len(antes_bytes)} -> {len(despues_bytes)} bytes"
    )
    assert resultado.label_actual == "Nombre estable"


def test_control_negativo_un_cambio_real_sobre_perfil_compacto_si_escribe(tmp_path):
    """Control positivo del propio no-op: si el label SÍ cambia, la
    escritura tiene que ocurrir de verdad (el no-op no se disparó por
    error para un caso que no lo es)."""
    carpeta = tmp_path / "l5r"
    _escribir_perfil_compacto(carpeta, _PERFIL_CONFORME)
    ruta = carpeta / sources_catalog.NOMBRE_PERFIL
    antes_bytes = ruta.read_bytes()
    huella = vw.huella_de(ruta)

    resultado = vw.escribir_label_workspace(carpeta, "Nombre Nuevo De Verdad", huella)

    despues_bytes = ruta.read_bytes()
    assert despues_bytes != antes_bytes
    assert resultado.label_actual == "Nombre Nuevo De Verdad"


# ---------------------------------------------------------------------------
# 10 — R3 (revisión independiente de PR #258, segunda ronda): el filtro de
# control amplía de C0+DEL a control por CATEGORÍA Unicode (C1, formato
# invisible, separadores de línea/párrafo).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("caracter,nombre", [
    ("\u0080", "C1 U+0080"),
    ("\u009f", "C1 U+009F"),
    ("\u2028", "separador de línea U+2028"),
    ("\u2029", "separador de párrafo U+2029"),
    ("\u0085", "NEL U+0085"),
    ("\u200b", "cero-ancho U+200B"),
    ("\u202e", "override bidi RLO U+202E"),
    ("\u2066", "override bidi LRI U+2066"),
    ("\u2069", "override bidi PDI U+2069"),
], ids=[
    "c1_u0080", "c1_u009f", "sep_linea_u2028", "sep_parrafo_u2029",
    "nel_u0085", "cero_ancho_u200b", "bidi_rlo_u202e", "bidi_lri_u2066",
    "bidi_pdi_u2069",
])
def test_servidor_rechaza_controles_ampliados(tmp_path, caracter, nombre):
    carpeta = tmp_path / "l5r"
    _escribir_perfil(carpeta, _PERFIL_CONFORME)
    ruta = carpeta / sources_catalog.NOMBRE_PERFIL
    huella = vw.huella_de(ruta)

    with pytest.raises(vw.EntradaInvalidaError):
        vw.escribir_label_workspace(carpeta, f"nombre{caracter}sucio", huella)

    en_disco = json.loads(ruta.read_text())
    assert "metadata" not in en_disco, nombre


def test_control_negativo_unicode_legitimo_multiidioma_se_acepta(tmp_path):
    """R3 NO puede romper Unicode legítimo: ideogramas, diacríticos y
    puntuación normal de cualquier idioma siguen pasando."""
    carpeta = tmp_path / "l5r"
    _escribir_perfil(carpeta, _PERFIL_CONFORME)
    ruta = carpeta / sources_catalog.NOMBRE_PERFIL
    huella = vw.huella_de(ruta)

    nombre = "La Cofradía de Ámbar — 参 ñ ü"
    resultado = vw.escribir_label_workspace(carpeta, nombre, huella)
    assert resultado.label_actual == nombre
