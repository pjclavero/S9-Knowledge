"""Tests de la retención propuesta para el backup automático.

La retención es la única pieza de la propuesta que BORRA. Se prueba antes de
proponer su activación, no después: un fallo aquí destruye copias de seguridad.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
MODULO = RAIZ / "deploy" / "propuestas" / "backup-automatico" / "retencion.py"


def _cargar():
    spec = importlib.util.spec_from_file_location("s9k_retencion_propuesta", MODULO)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


RET = _cargar()


def _copia(dest: Path, nombre: str, con_manifiesto: bool = True) -> Path:
    d = dest / nombre
    d.mkdir(parents=True)
    if con_manifiesto:
        (d / "MANIFEST.sha256").write_text("hash  1  2026-01-01 00:00:00  ./x\n")
    return d


def test_conserva_siempre_la_copia_mas_reciente_aunque_las_cuotas_sean_cero(tmp_path):
    """Una configuración a cero no puede dejar el sistema sin ninguna copia."""
    reciente = _copia(tmp_path, "auto-20260806-030000")
    _copia(tmp_path, "auto-20260805-030000")
    conservar = RET.seleccionar(RET.copias(tmp_path), 0, 0, 0)
    assert reciente in conservar


def test_ignora_temporales_y_copias_sin_manifiesto(tmp_path):
    """Sin manifiesto no se puede afirmar qué es: no se toca."""
    (tmp_path / ".tmp-auto-20260806-030000").mkdir()
    _copia(tmp_path, "auto-20260804-030000", con_manifiesto=False)
    valida = _copia(tmp_path, "auto-20260806-030000")
    encontradas = [ruta for _, ruta in RET.copias(tmp_path)]
    assert encontradas == [valida]


def test_cuota_diaria_conserva_una_por_dia(tmp_path):
    for dia in range(1, 11):
        _copia(tmp_path, f"auto-202608{dia:02d}-030000")
    conservar = RET.seleccionar(RET.copias(tmp_path), diarias=7, semanales=0, mensuales=0)
    # 7 días distintos, más la más reciente que ya está entre ellos.
    assert len(conservar) == 7
    nombres = sorted(p.name for p in conservar)
    assert nombres[-1] == "auto-20260810-030000"


def test_dos_copias_del_mismo_dia_solo_ocupan_una_cuota(tmp_path):
    _copia(tmp_path, "auto-20260806-030000")
    _copia(tmp_path, "auto-20260806-150000")
    _copia(tmp_path, "auto-20260805-030000")
    conservar = RET.seleccionar(RET.copias(tmp_path), diarias=2, semanales=0, mensuales=0)
    dias = {p.name.split("-")[1] for p in conservar}
    assert dias == {"20260806", "20260805"}


def test_las_cuotas_se_solapan_sin_duplicar(tmp_path):
    """Una misma copia puede ser la diaria y la semanal: se conserva una vez."""
    _copia(tmp_path, "auto-20260806-030000")
    conservar = RET.seleccionar(RET.copias(tmp_path), diarias=7, semanales=4, mensuales=3)
    assert len(conservar) == 1


def test_conserva_copias_manuales_igual_que_las_automaticas(tmp_path):
    manual = _copia(tmp_path, "manual-20260806-181324")
    assert manual in {ruta for _, ruta in RET.copias(tmp_path)}


def test_la_simulacion_no_borra_nada(tmp_path, capsys, monkeypatch):
    for dia in range(1, 6):
        _copia(tmp_path, f"auto-202608{dia:02d}-030000")
    monkeypatch.setattr(
        sys, "argv",
        ["retencion.py", "--dest", str(tmp_path), "--diarias", "1",
         "--semanales", "0", "--mensuales", "0", "--simular"],
    )
    RET.main()
    salida = capsys.readouterr().out
    assert "BORRARIA" in salida
    assert "BORRADA" not in salida
    assert len(list(tmp_path.iterdir())) == 5, "la simulación no puede borrar"


def test_el_borrado_real_respeta_la_seleccion(tmp_path, monkeypatch):
    for dia in range(1, 6):
        _copia(tmp_path, f"auto-202608{dia:02d}-030000")
    monkeypatch.setattr(
        sys, "argv",
        ["retencion.py", "--dest", str(tmp_path), "--diarias", "2",
         "--semanales", "0", "--mensuales", "0"],
    )
    RET.main()
    quedan = sorted(p.name for p in tmp_path.iterdir())
    assert quedan == ["auto-20260804-030000", "auto-20260805-030000"]


def test_nombre_no_reconocido_no_se_borra_jamas(tmp_path):
    """Cualquier cosa que no encaje con el patrón se deja en paz."""
    ajeno = tmp_path / "no-es-un-backup"
    ajeno.mkdir()
    (ajeno / "MANIFEST.sha256").write_text("x\n")
    assert [ruta for _, ruta in RET.copias(tmp_path)] == []
