"""Los endpoints de ESCRITURA no se sirven por GET. Comprobado por HTTP.

Contexto: `POST /admin/users/{id}/unlock` —una ruta de escritura— no tenía
NINGUNA prueba HTTP, y cambiarla a `GET` sobre el árbol congelado `aaf9695` no
puso rojo a ningún instrumento del repositorio. El censo de rutas comparaba el
método montado consigo mismo (con el decorador que pretendía vigilar), así que
un cambio de método era invisible por construcción.

Esta suite ejecuta la especificación independiente
(`scripts/route_map/write_spec.py`) y afirma sobre su resultado. La
especificación clasifica cada endpoint por su FIRMA y su CUERPO (parámetros
`Form`/`Body`/`File`, lectura del cuerpo, verificación de CSRF, mutadores de
estado durable), no por su decorador, y termina cada afirmación en una petición
real contra `app.main.app`.

Se ejecuta en un SUBPROCESO a propósito: `app.main` y `route_map` son
singletons en `sys.modules` y la especificación necesita la app arrancada con
auth ACTIVADA (sin ella, el panel de administración ni se monta y la suite
mediría una app que no es la que se despliega).

NO hay lista de endpoints en este fichero. Si mañana aparece un endpoint de
escritura nuevo, queda cubierto solo; y si alguno no se puede clasificar, la
especificación se pone roja (`endpoint-sin-fuente`) en vez de callarse.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WRITE_SPEC = REPO / "scripts" / "route_map" / "write_spec.py"

#: Suelo de plausibilidad: una especificación que clasifica cero (o casi cero)
#: endpoints de escritura no está protegiendo nada, y saldría "verde".
MINIMO_ENDPOINTS_DE_ESCRITURA = 10


@pytest.fixture(scope="module")
def informe() -> dict:
    if not WRITE_SPEC.exists():  # pragma: no cover
        pytest.fail(f"falta la especificación ejecutable: {WRITE_SPEC}")
    with tempfile.TemporaryDirectory(prefix="s9k-writespec-test-") as td:
        salida = Path(td) / "write_spec.json"
        env = {k: v for k, v in os.environ.items() if not k.startswith("S9K_")}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = str(REPO / "scripts")
        proc = subprocess.run(
            [sys.executable, str(WRITE_SPEC), "--repo", str(REPO), "--out", str(salida)],
            env=env, capture_output=True, text=True, timeout=900)
        if not salida.exists():  # la espec que no se ejecuta NO da verde
            pytest.fail("la especificación no produjo artefacto:\n"
                        f"rc={proc.returncode}\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
        datos = json.loads(salida.read_text(encoding="utf-8"))
        datos["_rc"] = proc.returncode
        datos["_stderr"] = proc.stderr[-2000:]
        return datos


def test_la_especificacion_inspecciono_la_app_real(informe):
    """Sin sondeo no hay medida: un artefacto vacío no es un aprobado."""
    sondas = informe.get("sondas") or {}
    assert sondas, "la especificación no emitió ni una petición"
    atendidas = [k for k, v in sondas.items() if v.get("atendido_por")]
    assert atendidas, ("ninguna petición atravesó un manejador de la app real: "
                       "la especificación no midió la app que se despliega")


def test_hay_endpoints_de_escritura_clasificados(informe):
    escritura = informe.get("endpoints_de_escritura") or []
    assert len(escritura) >= MINIMO_ENDPOINTS_DE_ESCRITURA, (
        f"sólo {len(escritura)} endpoints de escritura clasificados; el suelo es "
        f"{MINIMO_ENDPOINTS_DE_ESCRITURA}. Una espec que no ve escrituras no las protege")
    for e in escritura:
        assert e["evidencias"], f"{e['path']} clasificado sin evidencia"


def test_ninguna_escritura_admite_metodo_seguro(informe):
    """`POST -> GET` o un alias `GET` en una ruta de escritura: ROJO."""
    duros = ["metodo-seguro-en-endpoint-de-escritura", "escritura-servida-por-get",
             "escritura-sin-metodo"]
    hallazgos = {k: v for k, v in (informe.get("hallazgos") or {}).items() if k in duros}
    assert not hallazgos, json.dumps(hallazgos, indent=2, ensure_ascii=False)


def test_el_contrato_de_cliente_se_puede_ejecutar(informe):
    """Todo formulario/fetch que la app sirve tiene que poder enviarse.

    Es la fuente que caza un cambio de método que sigue siendo *inseguro*
    (`POST -> PUT`), donde la comprobación de método seguro calla.
    """
    rotos = (informe.get("hallazgos") or {}).get("contrato-de-cliente-roto")
    assert not rotos, json.dumps(rotos, indent=2, ensure_ascii=False)


def test_todos_los_endpoints_se_pudieron_clasificar(informe):
    sin_fuente = (informe.get("hallazgos") or {}).get("endpoint-sin-fuente")
    assert not sin_fuente, json.dumps(sin_fuente, indent=2, ensure_ascii=False)


def test_la_especificacion_sale_conforme(informe):
    assert informe["_rc"] == 0, (
        f"rc={informe['_rc']}\n"
        + json.dumps(informe.get("hallazgos"), indent=2, ensure_ascii=False)
        + "\n" + informe["_stderr"])
