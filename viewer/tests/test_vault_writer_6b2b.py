# -*- coding: utf-8 -*-
"""CORTE 6B-2(b) — escritor del nombre humano de UNA PARTIDA.

Testigos del contrato de `app.vault_writer.escribir_label_partida` y del
contrato mínimo `app.partida_manifest_contract.ManifiestoPartida`:

  1. El contrato mínimo: CONFORME (`{}` o `{"metadata": {...}}`),
     LEGIBLE_NO_CONFORME (clave de primer nivel fuera de `metadata`),
     INVALIDO (JSON roto), y el caso AUSENTE (fichero que no existe todavía)
     colapsado a CONFORME con `datos={}`.
  2. El escritor NUNCA crea el `manifiesto-partida.json` para un no-op: un
     label vacío sobre una partida sin manifiesto no fabrica un fichero de
     la nada.
  3. Un cambio REAL sí crea el fichero cuando no existía, y lo actualiza sin
     perder claves de `metadata` desconocidas cuando ya existía.
  4. Concurrencia optimista: huella que no coincide (incluida la huella
     "ausente" contra un fichero que ya existe) -> 409, y lo que escribió el
     otro sigue en disco.
  5. El escritor rechaza editar un manifiesto LEGIBLE_NO_CONFORME o INVALIDO,
     sin normalizarlo.
  6. D2/D3 (mismas reglas que el workspace, reutilizadas sin reimplementar):
     vacío borra, longitud/control se rechazan.
  7. Almacenamiento VERBATIM: el label se guarda exactamente como llegó, sin
     pasar por ninguna normalización de comparación (NFKC/casefold son solo
     comparador en el router, nunca transforman lo almacenado).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import sources_catalog, vault_writer as vw
from app.partida_manifest_contract import ManifiestoPartida, ManifiestoPartidaInvalidoError


def _carpeta_partida(tmp_path) -> Path:
    return tmp_path / "l5r" / "partidas" / "mesa1"


def _escribir_manifiesto(carpeta_partida: Path, datos: dict) -> None:
    carpeta_partida.mkdir(parents=True, exist_ok=True)
    (carpeta_partida / sources_catalog.NOMBRE_MANIFIESTO_PARTIDA).write_text(
        json.dumps(datos), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# 1. El contrato mínimo
# ---------------------------------------------------------------------------

def test_contrato_acepta_documento_vacio():
    ManifiestoPartida.from_dict({}, validate=True)


def test_contrato_acepta_metadata_con_label():
    m = ManifiestoPartida.from_dict({"metadata": {"label": "Mesa A"}}, validate=True)
    assert m.metadata == {"label": "Mesa A"}


def test_contrato_rechaza_clave_de_primer_nivel_fuera_del_contrato():
    with pytest.raises(ManifiestoPartidaInvalidoError):
        ManifiestoPartida.from_dict({"partida_id": "mesa1"}, validate=True)


def test_contrato_rechaza_metadata_que_no_es_objeto():
    with pytest.raises(ManifiestoPartidaInvalidoError):
        ManifiestoPartida.from_dict({"metadata": "no es un objeto"}, validate=True)


def test_contrato_rechaza_documento_que_no_es_objeto():
    with pytest.raises(ManifiestoPartidaInvalidoError):
        ManifiestoPartida.from_dict(["no", "es", "un", "objeto"], validate=True)


def test_c1_manifiesto_conforme_es_editable(tmp_path):
    carpeta = _carpeta_partida(tmp_path)
    _escribir_manifiesto(carpeta, {"metadata": {"label": "Mesa A"}})
    lectura = vw.leer_estado_manifiesto_partida(
        carpeta / sources_catalog.NOMBRE_MANIFIESTO_PARTIDA
    )
    assert lectura.estado == vw.EstadoPerfil.CONFORME
    assert lectura.label_actual == "Mesa A"


def test_c1_manifiesto_legible_no_conforme_tiene_causa_visible(tmp_path):
    carpeta = _carpeta_partida(tmp_path)
    _escribir_manifiesto(carpeta, {"partida_id": "mesa1", "metadata": {"label": "Mesa A"}})
    lectura = vw.leer_estado_manifiesto_partida(
        carpeta / sources_catalog.NOMBRE_MANIFIESTO_PARTIDA
    )
    assert lectura.estado == vw.EstadoPerfil.LEGIBLE_NO_CONFORME
    assert lectura.causa == vw.CAUSA_NO_CONFORME_PARTIDA
    # Igual y todo, el label SE LEE (misma doctrina que `leer_estado_perfil`).
    assert lectura.label_actual == "Mesa A"


def test_c1_manifiesto_invalido_es_fail_closed(tmp_path):
    carpeta = _carpeta_partida(tmp_path)
    carpeta.mkdir(parents=True)
    (carpeta / sources_catalog.NOMBRE_MANIFIESTO_PARTIDA).write_text(
        "{no es json", encoding="utf-8"
    )
    lectura = vw.leer_estado_manifiesto_partida(
        carpeta / sources_catalog.NOMBRE_MANIFIESTO_PARTIDA
    )
    assert lectura.estado == vw.EstadoPerfil.INVALIDO


def test_c1_manifiesto_ausente_colapsa_a_conforme_vacio(tmp_path):
    carpeta = _carpeta_partida(tmp_path)
    carpeta.mkdir(parents=True)
    lectura = vw.leer_estado_manifiesto_partida(
        carpeta / sources_catalog.NOMBRE_MANIFIESTO_PARTIDA
    )
    assert lectura.estado == vw.EstadoPerfil.CONFORME
    assert lectura.datos == {}
    assert lectura.label_actual == ""
    assert lectura.huella == vw.huella_ausente()


# ---------------------------------------------------------------------------
# 2/3 — El escritor NUNCA crea un fichero para un no-op, pero SÍ para un
# cambio real, y preserva claves de `metadata` desconocidas.
# ---------------------------------------------------------------------------

def test_no_op_sobre_manifiesto_ausente_no_crea_el_fichero(tmp_path):
    carpeta = _carpeta_partida(tmp_path)
    carpeta.mkdir(parents=True)
    ruta = carpeta / sources_catalog.NOMBRE_MANIFIESTO_PARTIDA
    resultado = vw.escribir_label_partida(carpeta, "", vw.huella_ausente())
    assert not ruta.exists(), "un no-op creó un manifiesto que no existía"
    assert resultado.label_actual == ""


def test_cambio_real_sobre_manifiesto_ausente_crea_el_fichero(tmp_path):
    carpeta = _carpeta_partida(tmp_path)
    carpeta.mkdir(parents=True)
    ruta = carpeta / sources_catalog.NOMBRE_MANIFIESTO_PARTIDA
    resultado = vw.escribir_label_partida(carpeta, "Mesa de los Jueves", vw.huella_ausente())
    assert ruta.exists(), "un cambio real no creó el manifiesto"
    assert resultado.label_actual == "Mesa de los Jueves"
    en_disco = json.loads(ruta.read_text())
    assert en_disco["metadata"]["label"] == "Mesa de los Jueves"


def test_cambio_real_preserva_claves_de_metadata_desconocidas(tmp_path):
    carpeta = _carpeta_partida(tmp_path)
    _escribir_manifiesto(carpeta, {"metadata": {"nota_interna": "no tocar", "label": "Vieja"}})
    ruta = carpeta / sources_catalog.NOMBRE_MANIFIESTO_PARTIDA
    huella = vw.huella_de(ruta)

    vw.escribir_label_partida(carpeta, "Nueva", huella)

    en_disco = json.loads(ruta.read_text())
    assert en_disco["metadata"]["label"] == "Nueva"
    assert en_disco["metadata"]["nota_interna"] == "no tocar"


def test_borrado_sobre_manifiesto_existente_quita_la_clave_no_el_fichero(tmp_path):
    carpeta = _carpeta_partida(tmp_path)
    _escribir_manifiesto(carpeta, {"metadata": {"nota_interna": "no tocar", "label": "Vieja"}})
    ruta = carpeta / sources_catalog.NOMBRE_MANIFIESTO_PARTIDA
    huella = vw.huella_de(ruta)

    resultado = vw.escribir_label_partida(carpeta, "", huella)

    assert ruta.exists()
    assert resultado.label_actual == ""
    en_disco = json.loads(ruta.read_text())
    assert "label" not in en_disco.get("metadata", {})
    assert en_disco["metadata"]["nota_interna"] == "no tocar"


# ---------------------------------------------------------------------------
# 4 — Concurrencia optimista
# ---------------------------------------------------------------------------

def test_409_si_la_huella_ausente_ya_no_coincide_con_un_fichero_creado_mientras_tanto(tmp_path):
    carpeta = _carpeta_partida(tmp_path)
    carpeta.mkdir(parents=True)
    # Alguien más ya escribió el manifiesto entre el GET (que vio "ausente")
    # y este POST.
    _escribir_manifiesto(carpeta, {"metadata": {"label": "Ya escrita por otro"}})

    with pytest.raises(vw.ConflictoEscrituraError):
        vw.escribir_label_partida(carpeta, "Mi Nombre", vw.huella_ausente())

    en_disco = json.loads((carpeta / sources_catalog.NOMBRE_MANIFIESTO_PARTIDA).read_text())
    assert en_disco["metadata"]["label"] == "Ya escrita por otro"


def test_409_si_la_huella_de_un_manifiesto_existente_no_coincide(tmp_path):
    carpeta = _carpeta_partida(tmp_path)
    _escribir_manifiesto(carpeta, {"metadata": {"label": "Original"}})
    huella_vieja = vw.huella_de(carpeta / sources_catalog.NOMBRE_MANIFIESTO_PARTIDA)
    # Cambia el fichero por debajo (otro escritor).
    _escribir_manifiesto(carpeta, {"metadata": {"label": "Cambiada por otro"}})

    with pytest.raises(vw.ConflictoEscrituraError):
        vw.escribir_label_partida(carpeta, "Mi Nombre", huella_vieja)

    en_disco = json.loads((carpeta / sources_catalog.NOMBRE_MANIFIESTO_PARTIDA).read_text())
    assert en_disco["metadata"]["label"] == "Cambiada por otro"


# ---------------------------------------------------------------------------
# 5 — No editable
# ---------------------------------------------------------------------------

def test_escritor_rechaza_editar_un_manifiesto_no_conforme(tmp_path):
    carpeta = _carpeta_partida(tmp_path)
    _escribir_manifiesto(carpeta, {"partida_id": "mesa1"})
    huella = vw.huella_de(carpeta / sources_catalog.NOMBRE_MANIFIESTO_PARTIDA)
    with pytest.raises(vw.EscrituraRechazadaError) as exc:
        vw.escribir_label_partida(carpeta, "Nuevo Nombre", huella)
    assert exc.value.estado == vw.EstadoPerfil.LEGIBLE_NO_CONFORME
    en_disco = json.loads((carpeta / sources_catalog.NOMBRE_MANIFIESTO_PARTIDA).read_text())
    assert en_disco == {"partida_id": "mesa1"}


def test_escritor_rechaza_editar_un_manifiesto_invalido(tmp_path):
    carpeta = _carpeta_partida(tmp_path)
    carpeta.mkdir(parents=True)
    (carpeta / sources_catalog.NOMBRE_MANIFIESTO_PARTIDA).write_text(
        "{no es json", encoding="utf-8"
    )
    with pytest.raises(vw.EscrituraRechazadaError) as exc:
        vw.escribir_label_partida(carpeta, "Nuevo Nombre", vw.huella_ausente())
    assert exc.value.estado == vw.EstadoPerfil.INVALIDO


# ---------------------------------------------------------------------------
# 6 — D2/D3 reutilizados
# ---------------------------------------------------------------------------

def test_entrada_invalida_por_longitud_se_rechaza(tmp_path):
    carpeta = _carpeta_partida(tmp_path)
    carpeta.mkdir(parents=True)
    with pytest.raises(vw.EntradaInvalidaError):
        vw.escribir_label_partida(carpeta, "x" * 500, vw.huella_ausente())
    assert not (carpeta / sources_catalog.NOMBRE_MANIFIESTO_PARTIDA).exists()


def test_entrada_invalida_por_caracter_de_control_se_rechaza(tmp_path):
    carpeta = _carpeta_partida(tmp_path)
    carpeta.mkdir(parents=True)
    with pytest.raises(vw.EntradaInvalidaError):
        vw.escribir_label_partida(carpeta, "mesa\u0000sucia", vw.huella_ausente())
    assert not (carpeta / sources_catalog.NOMBRE_MANIFIESTO_PARTIDA).exists()


# ---------------------------------------------------------------------------
# 7 — Almacenamiento VERBATIM
# ---------------------------------------------------------------------------

def test_el_label_almacenado_es_verbatim_no_normalizado(tmp_path):
    carpeta = _carpeta_partida(tmp_path)
    carpeta.mkdir(parents=True)
    nombre = "Mesa  Ｄé Los　Jueves"  # espacios dobles + fullwidth + tilde
    resultado = vw.escribir_label_partida(carpeta, nombre, vw.huella_ausente())
    assert resultado.label_actual == nombre
    en_disco = json.loads((carpeta / sources_catalog.NOMBRE_MANIFIESTO_PARTIDA).read_text())
    assert en_disco["metadata"]["label"] == nombre
