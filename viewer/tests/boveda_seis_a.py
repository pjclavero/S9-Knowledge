"""Helper de bóveda para las pruebas del Corte 6A (módulo propio, NO conftest:
hay un `conftest.py` distinto en `tests/browser/`, y un `from conftest import`
en una recolección conjunta resuelve al que gane la carrera de import, no al de
este directorio)."""
from __future__ import annotations

from pathlib import Path


def crear_boveda_minima(raiz: Path, workspace: str, partida_id: str,
                         carpeta_juego: str = "juego-de-prueba") -> Path:
    """Una bóveda real, mínima, con UNA partida discutible por su nombre real.

    CORTE 6A: `sources_catalog.partidas_descubiertas_en_boveda` (la enumeración
    autorizada que ahora valida `/admin/partidas/grant`, en el servidor, tanto
    para pintar el `<select>` como para rechazar un POST manipulado) sólo
    conoce partidas que existen de VERDAD en el árbol. Cualquier test que
    conceda una partida por HTTP después de este corte necesita que esa
    partida esté aquí, o el panel la rechaza con 400 — que es exactamente la
    propiedad que el corte cierra, no un efecto colateral a evitar.

    Se usa un `carpeta_juego` NEUTRO (no el `workspace`): el nombre externo de
    la carpeta y el workspace son ejes distintos (`vault_scope.py`), y el
    workspace real lo declara el `perfil-operador.json`, no el nombre de la
    carpeta.
    """
    import json as _json

    ejemplos = Path(__file__).resolve().parents[2] / "examples" / "ingesta-v3"
    plantilla = _json.loads((ejemplos / "perfil-operador.json").read_text(encoding="utf-8"))
    perfil = dict(plantilla)
    perfil["workspace"] = workspace
    perfil["source_asset_id"] = f"profile:{workspace}"

    base = raiz / carpeta_juego
    (base).mkdir(parents=True, exist_ok=True)
    (base / "perfil-operador.json").write_text(
        _json.dumps(perfil, ensure_ascii=False), encoding="utf-8",
    )
    cuerpo = (ejemplos / "nota-cofradia-de-ambar.md").read_text(encoding="utf-8")
    destino = base / "partidas" / partida_id / "material-jugadores" / "nota.md"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(cuerpo, encoding="utf-8")
    return raiz
