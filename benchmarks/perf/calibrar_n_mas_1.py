"""CALIBRACIÓN del arnés: ¿detecta un N+1 que sabemos que está ahí?

Un medidor que no distingue lo malo de lo bueno no mide nada. Este guion:

  1. Mide ``/api/entities`` (listado paginado) tal cual está: debe hacer un
     número CONSTANTE de llamadas a la fuente de datos, no dependa del tamaño.
  2. Inyecta un N+1 evidente EN TIEMPO DE EJECUCIÓN, en el camino que recorre
     esa petición: por cada entidad de la página, una llamada extra
     ``entity(id)`` a la fuente de datos. Es exactamente la forma del N+1 real
     que ya vive en ``/api/entities/{id}`` y en
     ``PolicyFilteredProvider.relations_for_entity``.

     El parche va sobre ``PolicyFilteredProvider.list_entities`` y no sobre la
     función del endpoint por una razón mecánica: la versión de Starlette de
     este repositorio precompila el manejador al montar la ruta, así que
     sustituir ``dependant.call`` después no tiene ningún efecto (se comprobó:
     el endpoint parcheado nunca llegaba a ejecutarse). La capa elegida está
     igualmente dentro de la petición HTTP real y es donde de verdad aparecen
     estos defectos.
  3. Vuelve a medir y comprueba que el detector lo marca.
  4. Deshace el parche y confirma que el endpoint vuelve a la línea base.

Nada de esto queda aplicado: el parche vive en memoria y se revierte en el
mismo proceso. Sale 0 si el arnés distingue los dos mundos, 1 si no.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "viewer"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dataset  # noqa: E402
import run_bench  # noqa: E402

TAMANOS = [100, 1000]


def _llamadas(cliente, contador, url: str) -> int:
    cliente.get(url)  # calentamiento
    contador.reset()
    r = cliente.get(url)
    assert r.status_code == 200, (url, r.status_code)
    return contador.snapshot().total_llamadas


def main() -> int:
    from app.authz.filtered_provider import PolicyFilteredProvider

    original = PolicyFilteredProvider.list_entities

    def list_entities_con_n_mas_1(self, *args, **kwargs):
        """El listado, más una consulta por elemento devuelto."""
        page, total = original(self, *args, **kwargs)
        for item in page:
            self._base.entity(item.get("id"))  # <-- una consulta por elemento
        return page, total

    medidas: dict[str, dict[str, int]] = {"sano": {}, "con_n_mas_1": {}}
    por_pagina: dict[str, dict[str, list]] = {"sano": {}, "con_n_mas_1": {}}

    for n in TAMANOS:
        ruta = run_bench.TMP / f"grafo_{n}.json"
        if not ruta.exists():
            dataset.write(n, ruta)
        run_bench._preparar_entorno(ruta)
        cliente, contador, app = run_bench._construir_cliente(ruta)
        url = "/api/entities?limit=50&offset=0"

        medidas["sano"][str(n)] = _llamadas(cliente, contador, url)
        pagina_sano = run_bench.detectar_n_mas_1_por_pagina(cliente, contador)

        PolicyFilteredProvider.list_entities = list_entities_con_n_mas_1
        medidas["con_n_mas_1"][str(n)] = _llamadas(cliente, contador, url)
        pagina_malo = run_bench.detectar_n_mas_1_por_pagina(cliente, contador)

        por_pagina["sano"][str(n)] = pagina_sano
        por_pagina["con_n_mas_1"][str(n)] = pagina_malo

        # Revertir
        PolicyFilteredProvider.list_entities = original
        vuelta = _llamadas(cliente, contador, url)
        assert vuelta == medidas["sano"][str(n)], (
            f"el parche no se revirtió limpiamente: {vuelta} != {medidas['sano'][str(n)]}"
        )
        app.dependency_overrides.clear()

    resultados = {
        "sano": {t: {"llamadas_fuente": v} for t, v in medidas["sano"].items()},
        "con_n_mas_1": {t: {"llamadas_fuente": v} for t, v in medidas["con_n_mas_1"].items()},
    }
    veredicto_sano = run_bench.detectar_n_mas_1(
        {t: {"api_entities": {"llamadas_fuente": v}} for t, v in medidas["sano"].items()}, TAMANOS
    )
    veredicto_malo = run_bench.detectar_n_mas_1(
        {t: {"api_entities": {"llamadas_fuente": v}} for t, v in medidas["con_n_mas_1"].items()},
        TAMANOS,
    )

    print("Llamadas a la fuente en /api/entities?limit=50")
    print(f"  sin parche : {medidas['sano']}  -> {veredicto_sano[0]['veredicto']}")
    print(f"  con N+1    : {medidas['con_n_mas_1']}  -> {veredicto_malo[0]['veredicto']}")
    print(json.dumps({"sano": veredicto_sano, "con_n_mas_1": veredicto_malo}, indent=2, ensure_ascii=False))

    # Eje 1 (crecimiento con el dataset): el N+1 inyectado es POR PÁGINA, así
    # que este eje NO debe marcarlo — y no lo marca. Se deja registrado porque
    # es exactamente la ceguera que obligó a añadir el eje 2.
    def _dictamen(por_pagina_lista: list) -> str:
        for h in por_pagina_lista:
            if h["escenario"] == "api_entities":
                return h["veredicto"]
        return "?"

    eje2_sano = _dictamen(por_pagina["sano"]["1000"])
    eje2_malo = _dictamen(por_pagina["con_n_mas_1"]["1000"])
    print(f"  eje 2 (tamaño de página) sin parche: {eje2_sano} / con parche: {eje2_malo}")

    ok = eje2_sano == "constante" and eje2_malo == "N+1"
    # El N+1 inyectado añade una llamada por elemento de la página: con 50
    # elementos, 50 llamadas extra frente a la línea base.
    delta = medidas["con_n_mas_1"]["1000"] - medidas["sano"]["1000"]
    print(f"\nLlamadas extra introducidas por el parche (dataset 1000): {delta} (esperado 50)")
    ok = ok and delta == 50

    salida = RAIZ / "benchmarks" / "perf" / "resultados" / "calibracion_n_mas_1.json"
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(
        json.dumps(
            {
                "medidas": resultados,
                "eje1_dataset_sin_parche": veredicto_sano,
                "eje1_dataset_con_parche": veredicto_malo,
                "eje2_pagina_sin_parche": por_pagina["sano"],
                "eje2_pagina_con_parche": por_pagina["con_n_mas_1"],
                "llamadas_extra_por_pagina": delta,
                "arnes_calibrado": ok,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nArnés calibrado: {'SÍ' if ok else 'NO'}  ->  {salida}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
