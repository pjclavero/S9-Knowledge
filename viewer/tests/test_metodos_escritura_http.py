"""Los endpoints de ESCRITURA no se sirven por GET. Comprobado por HTTP.

Contexto: `POST /admin/users/{id}/unlock` —una ruta de escritura— no tenía
NINGUNA prueba HTTP, y cambiarla a `GET` sobre el árbol congelado `aaf9695` no
puso rojo a ningún instrumento del repositorio. El censo de rutas comparaba el
método montado consigo mismo (con el decorador que pretendía vigilar), así que
un cambio de método era invisible por construcción.

Esta suite ejecuta la especificación independiente
(`scripts/route_map/write_spec.py`) y afirma sobre su resultado. La
especificación clasifica cada endpoint por su FIRMA y su CUERPO (parámetros
`Form`/`Body`/`File` —también en la forma `Annotated[str, Form()]` y con alias
de importación—, lectura del cuerpo, verificación de CSRF y llamadas que
escriben estado durable, derivadas del código del invocable), no por su
decorador, y termina cada afirmación en una petición real contra `app.main.app`.

QUÉ GARANTIZA Y QUÉ NO, dicho con precisión —la versión anterior de este
docstring afirmaba de más—:

  - Que un endpoint de escritura NUEVO quede cubierto depende de que la
    clasificación lo reconozca. Por eso existe además una red que NO depende de
    ella: `metodo-de-escritura-sin-evidencia` marca toda ruta montada con
    POST/PUT/PATCH/DELETE que la clasificación no supo explicar. Hoy ese
    conjunto está VACÍO, así que cubre a todos los endpoints de escritura
    montados, acierten o no las señales.
  - Un endpoint que no se pueda clasificar por falta de fuente sale ROJO
    (`endpoint-sin-fuente`); uno clasificado SIN evidencia cae en «lectura», y
    es la red anterior —no la clasificación— la que impide que eso pase mudo.
  - Formas que la clasificación NO ve, medidas: anotación escrita como CADENA
    (`x: "Annotated[str, Form()]"`), alias de tipo reutilizado
    (`Formulario = Annotated[str, Form()]`), `*args`/`**kwargs`, y las
    escrituras que pasan por un helper del MISMO módulo (la derivación de
    durabilidad sigue un salto **a símbolos importados** de `app.*`). Todas
    quedan cubiertas por la red anterior EN CUANTO el endpoint va montado con
    método de escritura; sobre un `GET`, no las ve nadie.
  - **Esta suite NO comprueba `rc == 0`**, y es deliberado: sobre esta base la
    especificación sale `rc=1` por dos `lectura-que-escribe` reales del producto
    (ver el registro de abajo). Se afirma sobre las CLASES de hallazgo. Quien
    exige `rc == 0` es el job `metodos-de-escritura`, que NO es exigido; hoy
    ningún check exigido comprueba ese código de salida.

Se ejecuta en un SUBPROCESO a propósito: `app.main` y `route_map` son
singletons en `sys.modules` y la especificación necesita la app arrancada con
auth ACTIVADA (sin ella, el panel de administración ni se monta y la suite
mediría una app que no es la que se despliega).
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

#: LECTURAS QUE ESCRIBEN ya presentes en el producto, con evidencia y fecha.
#:
#: 2026-08-18 — `GET /admin/health` y `GET /api/admin/health` ejecutan los
#: healthchecks y llaman a `app.health.storage.save_report` DENTRO del propio
#: GET (`viewer/app/routers/health_admin.py:28,40`), que hace `mkdir` +
#: `write_text` + `os.replace` + `chmod 0600`. El propio repositorio ya lo
#: admite por escrito en `viewer/app/routers/chassis_operations.py:9-17`.
#:
#: NO es una exención: la especificación los declara ROJOS y el job
#: `metodos-de-escritura` sale ROJO por ellos. Lo que hace este registro es
#: impedir que un check EXIGIDO (la suite del visor) se ponga rojo por un
#: defecto que este carril no está autorizado a arreglar —tocar ese router
#: cambia el comportamiento del panel de operaciones, y esa decisión es del
#: operador—. Cualquier lectura-que-escribe NUEVA rompe esta suite.
LECTURAS_QUE_ESCRIBEN_REGISTRADAS = {
    "app.routers.health_admin.api_admin_health",
    "app.routers.health_admin.admin_health_panel",
}

#: Hallazgos que NUNCA pueden aparecer aquí.
HALLAZGOS_DUROS = (
    "metodo-seguro-en-endpoint-de-escritura",
    "escritura-servida-por-get",
    "escritura-sin-metodo",
    "metodo-de-escritura-sin-evidencia",
    "contrato-de-cliente-roto",
    "endpoint-sin-fuente",
    "espec-vacia",
    "espec-no-inspecciono-la-app-real",
)


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
    """`POST -> GET` o un alias `GET` en una ruta de escritura: ROJO.

    Incluye la red que no depende de la clasificación
    (`metodo-de-escritura-sin-evidencia`) y el contrato de cliente.
    """
    hallazgos = {k: v for k, v in (informe.get("hallazgos") or {}).items()
                 if k in HALLAZGOS_DUROS and v}
    assert not hallazgos, json.dumps(hallazgos, indent=2, ensure_ascii=False)


def test_ninguna_lectura_que_escribe_nueva(informe):
    """Un `GET` que escribe es escritura. Los conocidos están registrados."""
    entradas = (informe.get("hallazgos") or {}).get("lectura-que-escribe") or []
    nuevas = [e for e in entradas
              if e.get("endpoint") not in LECTURAS_QUE_ESCRIBEN_REGISTRADAS]
    assert not nuevas, (
        "hay lecturas que escriben SIN registrar:\n"
        + json.dumps(nuevas, indent=2, ensure_ascii=False))


def test_no_hay_hallazgos_de_clase_desconocida(informe):
    """Un hallazgo que esta suite no clasifica no puede pasar en silencio."""
    conocidos = set(HALLAZGOS_DUROS) | {"lectura-que-escribe"}
    desconocidos = {k: v for k, v in (informe.get("hallazgos") or {}).items()
                    if k not in conocidos and v}
    assert not desconocidos, json.dumps(desconocidos, indent=2, ensure_ascii=False)
