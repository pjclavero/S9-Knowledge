# -*- coding: utf-8 -*-
"""Suite del Bloque 4 (Temporalidad): clasificacion temporal determinista.

Prueba la API publica de ``relations.temporality`` sin mocks: se importa el
modulo REAL y se afirma sobre su salida. Cubre las seis clases temporales, la
modalidad potencial, fechas/intervalos, la traduccion `temporal_scope -> clase`
(`temporal_status_of`), version/trazabilidad, determinismo y ausencia de falsos
positivos por subcadena o por adverbios ambiguos.

Los tests marcados ``@pytest.mark.mutation`` MATAN mutantes concretos del modulo
(ver el motivo en cada uno); no usan mocks ni skip/xfail.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from relations.temporality import (  # noqa: E402
    TEMPORAL_CLASSES,
    TEMPORALITY_VERSION,
    TemporalClassification,
    classify_temporality,
    temporal_status_of,
)


# ---------------------------------------------------------------------------
# 1. PASADO
# ---------------------------------------------------------------------------
def test_pasado_goberno_con_fecha():
    r = classify_temporality("gobernó en el 843")
    assert r.temporal_class == "PAST"
    assert "843" in r.dates


def test_pasado_fue_aliado():
    assert classify_temporality("fue aliado").temporal_class == "PAST"


# ---------------------------------------------------------------------------
# 2. PRESENTE
# ---------------------------------------------------------------------------
def test_presente_es_miembro():
    r = classify_temporality("es miembro de la casa")
    assert r.temporal_class == "PRESENT"
    assert r.is_ended is False
    assert r.is_potential is False


# ---------------------------------------------------------------------------
# 3. FUTURO
# ---------------------------------------------------------------------------
@pytest.mark.mutation  # "futuro->presente": si FUTURE se clasificara PRESENT, falla.
def test_futuro_sera_nombrado():
    assert classify_temporality("será nombrado heredero").temporal_class == "FUTURE"


@pytest.mark.mutation  # "futuro->presente": planea es intencion de futuro, no presente.
def test_futuro_planea_aliarse():
    assert classify_temporality("planea aliarse").temporal_class == "FUTURE"


# ---------------------------------------------------------------------------
# 4. POTENCIAL
# ---------------------------------------------------------------------------
@pytest.mark.mutation  # "potencial perdido": is_potential debe seguir True (clase FUTURE).
def test_potencial_podria_aliarse():
    r = classify_temporality("podría aliarse")
    assert r.is_potential is True
    assert r.temporal_class == "FUTURE"


# ---------------------------------------------------------------------------
# 5. INICIO / ONGOING
# ---------------------------------------------------------------------------
def test_ongoing_desde_anho():
    r = classify_temporality("desde el año 1200")
    assert r.temporal_class == "ONGOING"
    assert "1200" in r.dates


# ---------------------------------------------------------------------------
# 6. FIN / ENDED
# ---------------------------------------------------------------------------
@pytest.mark.mutation  # "terminada tratada como vigente": ya no -> ENDED, no ONGOING/PRESENT.
def test_ended_ya_no_pertenece():
    r = classify_temporality("ya no pertenece")
    assert r.temporal_class == "ENDED"
    assert r.is_ended is True


def test_ended_dejo_de_servir():
    r = classify_temporality("dejó de servir")
    assert r.temporal_class == "ENDED"
    assert r.is_ended is True


# ---------------------------------------------------------------------------
# 7. INTERVALO
# ---------------------------------------------------------------------------
def test_intervalo_entre_x_y_y():
    r = classify_temporality("entre 1200 y 1250")
    assert r.interval == ("1200", "1250") or r.dates == ["1200", "1250"]


def test_intervalo_con_guion():
    r = classify_temporality("1200-1250")
    assert r.interval == ("1200", "1250") or r.dates == ["1200", "1250"]


def test_intervalo_con_raya():
    r = classify_temporality("1200–1250")
    assert r.interval == ("1200", "1250") or r.dates == ["1200", "1250"]


# ---------------------------------------------------------------------------
# 8. ANTES / DESPUES (marcadores) y adverbio ambiguo "antes"
# ---------------------------------------------------------------------------
def test_marcador_tras_batalla_presente():
    r = classify_temporality("tras la batalla")
    assert "tras" in r.markers


def test_marcador_despues_de_caida_presente():
    r = classify_temporality("después de la caída")
    assert any("despues" in m for m in r.markers)


@pytest.mark.mutation  # "match temporal laxo": "antes" solo (adverbio ambiguo) NO fuerza PAST.
def test_antes_solo_no_clasifica():
    # Documenta ausencia de falso positivo: "antes" aislado no es senal temporal.
    assert temporal_status_of("antes") is None


# ---------------------------------------------------------------------------
# 9. FECHAS EXPLICITAS
# ---------------------------------------------------------------------------
@pytest.mark.mutation  # "fecha ignorada": el año literal debe aparecer en .dates.
def test_fecha_explicita_anho_843():
    assert classify_temporality("en el año 843").dates


def test_siglo_iii_no_falla_si_no_soportado():
    # El modulo no reconoce numerales romanos de siglo: no debe fallar, solo no
    # detectar fecha. Si en el futuro lo soporta, este test sigue siendo valido.
    r = classify_temporality("siglo III")
    assert isinstance(r, TemporalClassification)
    assert r.temporal_class in TEMPORAL_CLASSES


# ---------------------------------------------------------------------------
# 10. temporal_status_of: None y round-trip de las 6 clases
# ---------------------------------------------------------------------------
@pytest.mark.mutation  # "match temporal laxo": None -> None (nunca casa con una clase).
def test_temporal_status_of_none():
    assert temporal_status_of(None) is None


def test_round_trip_seis_clases():
    representativos = {
        "PAST": "gobernó en el 843",
        "PRESENT": "es miembro de la casa",
        "FUTURE": "será nombrado heredero",
        "ONGOING": "desde el año 1200",
        "ENDED": "ya no pertenece",
        "ATEMPORAL": "",
    }
    for clase, txt in representativos.items():
        clf = classify_temporality(txt)
        assert clf.temporal_class == clase
        # to_scope_string -> temporal_status_of debe devolver la MISMA clase.
        assert temporal_status_of(clf.to_scope_string()) == clf.temporal_class


# ---------------------------------------------------------------------------
# 11. VERSION / TRAZABILIDAD y determinismo
# ---------------------------------------------------------------------------
def test_version_presente_y_propagada():
    assert TEMPORALITY_VERSION == "relation-temporality-1.0.0"
    r = classify_temporality("fue aliado")
    assert r.temporality_version == TEMPORALITY_VERSION


def test_determinismo_misma_entrada_misma_salida():
    a = classify_temporality("gobernó en el 843 y dejó de servir")
    b = classify_temporality("gobernó en el 843 y dejó de servir")
    assert a == b


# ---------------------------------------------------------------------------
# 12. Frontera de palabra: sin falsos positivos por subcadena
# ---------------------------------------------------------------------------
@pytest.mark.mutation  # "falso positivo por subcadena": 'era' dentro de 'cualquiera' NO -> PAST.
def test_subcadena_era_en_cualquiera_no_es_pasado():
    r = classify_temporality("cualquiera puede entrar")
    assert r.temporal_class != "PAST"
