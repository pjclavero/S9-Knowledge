# -*- coding: utf-8 -*-
"""Fixtures compartidas de los tests del normalizador multimodal V3.

No contiene tests: son las fuentes de prueba. Se generan en codigo, no se
versionan como binarios, para que cualquiera pueda ver EXACTAMENTE que contiene
cada fixture y por que un test espera lo que espera.

El PDF se construye con sintaxis PDF cruda (catalogo, paginas, stream de texto
`BT ... Tj ... ET`). Es un PDF real, lo lee `pypdf` de verdad, y permite generar
tanto una pagina con texto nativo como una pagina SIN texto extraible, que es el
caso que enruta a OCR.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from knowledge_v3.multimodal import IngestOptions  # noqa: E402

#: Instante de ingesta fijo. Los tests NO usan el reloj: el determinismo del
#: normalizador se comprueba, no se supone.
INGESTED_AT = "2026-07-27T10:00:00Z"
CREATED_AT = "2026-07-01T08:30:00Z"


def options(**overrides) -> IngestOptions:
    """Opciones de ingesta por defecto de los tests."""
    base = {
        "workspace": "pruebas",
        "collection_id": "col-multimodal",
        "ingested_at": INGESTED_AT,
        "created_at": CREATED_AT,
        "language_hint": "es",
    }
    base.update(overrides)
    return IngestOptions(**base)


# ── Texto ─────────────────────────────────────────────────────────────────────
TEXT_FIXTURE = (
    "Elara Vane llego a Nortala en el invierno del ano 812. La ciudad estaba "
    "sitiada.\n"
    "\n"
    "El Gremio de la Sal la contrato para cruzar el paso de Kerdan. Nadie mas "
    "acepto el encargo.\n"
)

MARKDOWN_FIXTURE = """# Cronica de Nortala

Elara Vane llego a Nortala en el invierno del ano 812.

## Inventario del convoy

| Objeto | Cantidad | Duenno |
|---|---|---|
| Espada corta | 1 | Elara |
| Pocion de vigor | 3 | Borin |

El convoy partio al amanecer. Nadie volvio a verlo.
"""

CSV_FIXTURE = (
    "nombre,faccion,ciudad\n"
    "Elara Vane,Gremio de la Sal,Nortala\n"
    "Borin Hald,Corona de Kerdan,Kerdan\n"
)

#: Markdown con una tabla DENTRO de un bloque cercado: es documentacion de un
#: formato, no datos. No debe salir como episodio TABLE.
MARKDOWN_FENCED_FIXTURE = """# Manual del formato

Asi se escribe una tabla en Markdown:

```markdown
| Columna | Otra |
|---|---|
| valor | otro |
# Esto tampoco es un encabezado: va dentro del bloque cercado.
```

Y esta si es una tabla de datos:

| Objeto | Cantidad |
|---|---|
| Espada | 1 |
"""


def crlf(text: str) -> bytes:
    """Mismo contenido con finales de linea de Windows."""
    return text.replace("\n", "\r\n").encode("utf-8")


# ── PDF minimo generado ───────────────────────────────────────────────────────
def make_pdf(pages: Sequence[Sequence[str]]) -> bytes:
    """PDF valido con una pagina por elemento de `pages`.

    Una pagina con lista de lineas vacia queda SIN texto extraible: es la
    fixture del caso "pagina escaneada" que debe enrutarse a reconocimiento.
    """
    objects: dict[int, bytes] = {}
    count = len(pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(count))
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Count {count} /Kids [{kids}] >>".encode()
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    for index, lines in enumerate(pages):
        page_obj = 4 + 2 * index
        content_obj = 5 + 2 * index
        content = "BT /F1 12 Tf 72 720 Td 14 TL\n"
        for line in lines:
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            content += f"({escaped}) Tj T*\n"
        content += "ET"
        data = content.encode("latin-1")
        objects[page_obj] = (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            "/Resources << /Font << /F1 3 0 R >> >> "
            f"/Contents {content_obj} 0 R >>"
        ).encode()
        objects[content_obj] = (
            f"<< /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode() + objects[number] + b"\nendobj\n"
    xref = len(out)
    size = max(objects) + 1
    out += f"xref\n0 {size}\n".encode() + b"0000000000 65535 f \n"
    for number in range(1, size):
        out += f"{offsets[number]:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


PDF_PAGES = [
    ["Elara Vane llego a Nortala en el invierno del ano 812.", "La ciudad estaba sitiada."],
    ["El Gremio de la Sal pago el rescate de Borin Hald."],
]


def pdf_with_text() -> bytes:
    return make_pdf(PDF_PAGES)


def pdf_without_text() -> bytes:
    """PDF de dos paginas donde la segunda no tiene texto extraible."""
    return make_pdf([PDF_PAGES[0], []])


# ── Transcripciones (fixture, NUNCA audio real) ───────────────────────────────
def diarized_transcript() -> dict:
    """Transcripcion con diarizacion: turnos de hablante y timecodes reales."""
    return {
        "language": "es",
        "engine": "faster-whisper",
        "model": "small",
        "duration_seconds": 24.0,
        "segments": [
            {"start": 0.0, "end": 5.0, "text": "Elara entra en la sala del consejo.",
             "speaker": "SPEAKER_00", "confidence": 0.94},
            {"start": 5.0, "end": 11.0, "text": "Traigo el sello del Gremio de la Sal.",
             "speaker": "SPEAKER_00", "confidence": 0.91},
            {"start": 11.0, "end": 17.5, "text": "Ese sello no vale nada en Kerdan.",
             "speaker": "SPEAKER_01", "confidence": 0.88},
            {"start": 17.5, "end": 24.0, "text": "Entonces hablaremos con la Corona.",
             "speaker": "SPEAKER_00", "confidence": 0.9},
        ],
    }


def plain_transcript() -> dict:
    """Transcripcion sin diarizacion pero CON timecodes."""
    data = diarized_transcript()
    for segment in data["segments"]:
        segment.pop("speaker")
    data["engine"] = "stub"
    data["model"] = ""
    return data


def untimed_transcript(source_method: str = "subtitles") -> dict:
    """Salida real de `youtube/fetch_youtube.py`: texto plano, sin timecodes."""
    return {
        "language": "es",
        "engine": "whisper",
        "source_method": source_method,
        "text": (
            "Elara entra en la sala del consejo. Traigo el sello del Gremio de la Sal."
        ),
    }


class TranscriptResultLike:
    """Duplicado minimo de `media.models.TranscriptResult` (misma forma).

    Se usa para comprobar que el adaptador envuelve la salida real del pipeline
    `media/` por FORMA y no por import: si `media/` cambia de sitio, el
    normalizador sigue funcionando.
    """

    def __init__(self, data: dict) -> None:
        self.text = " ".join(s["text"] for s in data["segments"])
        self.segments = [_Segment(s) for s in data["segments"]]
        self.language = data["language"]
        self.engine = data["engine"]
        self.model = data["model"]
        self.duration_seconds = data["duration_seconds"]


class _Segment:
    def __init__(self, data: dict) -> None:
        self.start = data["start"]
        self.end = data["end"]
        self.text = data["text"]
        self.speaker = data.get("speaker")
        self.confidence = data.get("confidence")


class MultimediaArtifactLike:
    """Forma de `media.multimedia_contract.MultimediaArtifact` (`ASR_TEXT`)."""

    def __init__(self, data: dict) -> None:
        self.contract = "multimedia-artifact/internal-v1"
        self.media_type = "ASR_TEXT"
        self.extraction_method = f"asr:{data['engine']}"
        self.model = data["model"]
        self.language = data["language"]
        self.text = " ".join(s["text"] for s in data["segments"])
        self.structured_data = {
            "segments": [
                {"start": s["start"], "end": s["end"], "text": s["text"]}
                for s in data["segments"]
            ],
            "duration_seconds": data["duration_seconds"],
        }


# ── Proveedor visual de prueba ────────────────────────────────────────────────
class FakeVisualProvider:
    """Proveedor visual de prueba: NO es OCR, es un doble del puerto.

    Sirve para probar la ruta "con proveedor" del adaptador visual sin fingir
    que existe reconocimiento real en el repositorio. Devuelve exactamente lo
    que se le configura.
    """

    #: Clase de proveedor declarada POR ADELANTADO. El adaptador la consulta
    #: antes de mandarle nada, para no exponer los bytes a un proveedor que la
    #: politica del asset no admite.
    provider_kind = "local"

    def __init__(self, responses: dict[str, tuple[str, float]], *, provider: str = "local"):
        self.responses = responses
        self.provider = provider
        self.provider_kind = provider
        self.calls: list = []

    def recognize(self, request):
        from knowledge_v3.multimodal.adapters.visual import LITERAL_MODES, VisualResult

        self.calls.append(request)
        if request.mode not in self.responses:
            return None
        content, confidence = self.responses[request.mode]
        literal = request.mode in LITERAL_MODES
        return VisualResult(
            mode=request.mode,
            region_id=request.region.region_id,
            confidence=confidence,
            text=content if literal else None,
            description=None if literal else content,
            provider=self.provider,
            name="fake-visual",
            version="0.0-test",
            model="fake-model",
        )
