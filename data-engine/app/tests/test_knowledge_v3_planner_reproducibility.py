# -*- coding: utf-8 -*-
"""Reproducibilidad del PLAN: la firma no puede depender del `PYTHONHASHSEED`.

Hermano de `test_knowledge_v3_reconcile_validation.py`, pero sobre el artefacto
que de verdad llega al grafo. El plan se SELLA: `plan_hash`, `decision_hash` e
`idempotency_key` se derivan de su serializacion, el operador confirma el
`plan_hash` a mano antes de un apply, y la `idempotency_key` es lo que impide
que un plan reaplicado escriba dos veces.

Si el orden de iteracion de un `set` o un `dict` se colase en esa serializacion,
dos procesos con distinta semilla firmarian el MISMO plan con hashes distintos:
la confirmacion del operador dejaria de significar nada y la idempotencia se
romperia entre reinicios del writer. Es exactamente el tipo de fallo que no
aparece nunca en una suite que corre siempre con la misma semilla.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("jsonschema")

#: Semillas del encargo. `PYTHONHASHSEED` se fija al arrancar el interprete, asi
#: que cada una exige un proceso nuevo.
SEEDS = ("1", "7", "42", "123")


def test_el_plan_es_identico_con_cualquier_pythonhashseed():
    """Cuatro semillas, cuatro procesos nuevos, un unico hash.

    Se ejecuta en SUBPROCESOS a proposito: cambiar `PYTHONHASHSEED` dentro del
    proceso en curso no cambia nada, y el test daria un verde vacio.

    La sonda cubre las cuatro ramas del planner —positivo, negativo (sin
    proyeccion), cesacion (con supersesion) y un lote de varios claims— y
    devuelve un sha256 de la serializacion canonica de los planes sellados.
    """
    probe = Path(__file__).with_name("planner_hashseed_probe.py")
    assert probe.exists(), probe

    app_path = str(Path(__file__).resolve().parents[1])
    hashes: dict[str, str] = {}

    for seed in SEEDS:
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        env["PYTHONPATH"] = os.pathsep.join(
            part for part in (app_path, env.get("PYTHONPATH", "")) if part
        )
        completed = subprocess.run(
            [sys.executable, str(probe)],
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
        hashes[seed] = completed.stdout.strip()

    assert len(set(hashes.values())) == 1, f"el plan cambia con la semilla: {hashes}"
    # Que sea un sha256 de verdad y no una cadena vacia repetida cuatro veces:
    # sin esto, una sonda que no imprimiese nada pasaria el test anterior.
    assert len(next(iter(hashes.values()))) == 64, hashes
