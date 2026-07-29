"""Local Tesseract OCR provider using its positional TSV output."""
from __future__ import annotations

import csv
import io
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from ..adapters.visual import (
    MODE_OCR,
    VisualRequest,
    VisualResult,
    VisualTextSpan,
)


class TesseractNotAvailable(RuntimeError):
    """The configured local Tesseract executable cannot be found."""


class _UnreadableImage(ValueError):
    pass


def find_tesseract(configured: str | os.PathLike[str] | None = None) -> str | None:
    candidates = [
        str(configured) if configured else None,
        os.environ.get("S9K_TESSERACT_CMD"),
        shutil.which("tesseract"),
        str(Path.cwd() / ".tools" / "Tesseract-OCR" / "tesseract.exe"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate))
    return None


def _normalized_bbox(
    row: dict[str, str],
    width: int,
    height: int,
    region_bbox: dict[str, Any],
) -> dict[str, float]:
    local_x = int(row["left"]) / width
    local_y = int(row["top"]) / height
    local_width = int(row["width"]) / width
    local_height = int(row["height"]) / height
    region_x = float(region_bbox["x"])
    region_y = float(region_bbox["y"])
    region_width = float(region_bbox["width"])
    region_height = float(region_bbox["height"])
    return {
        "x": region_x + local_x * region_width,
        "y": region_y + local_y * region_height,
        "width": local_width * region_width,
        "height": local_height * region_height,
    }


@dataclass(frozen=True)
class _Token:
    text: str
    confidence: float
    bbox: dict[str, float]
    line_key: tuple[int, int, int, int]


def _tokens_from_tsv(
    tsv: str,
    *,
    image_width: int,
    image_height: int,
    region_bbox: dict[str, Any],
) -> list[_Token]:
    tokens: list[_Token] = []
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t")
    for row in reader:
        if row.get("level") != "5":
            continue
        text = (row.get("text") or "").strip()
        if not text:
            continue
        try:
            raw_confidence = float(row["conf"])
            bbox = _normalized_bbox(row, image_width, image_height, region_bbox)
            line_key = tuple(
                int(row[key]) for key in ("page_num", "block_num", "par_num", "line_num")
            )
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
        if raw_confidence < 0:
            continue
        confidence = raw_confidence / 100.0
        tokens.append(_Token(text, confidence, bbox, line_key))
    return tokens


def _result_from_tokens(tokens: list[_Token], *, region_id: str, version: str) -> VisualResult:
    if not tokens:
        return VisualResult(
            mode=MODE_OCR,
            region_id=region_id,
            confidence=0.0,
            text="",
            provider="local",
            name="tesseract",
            version=version,
            model="tesseract-lstm",
            metadata={"diagnostic": "OCR_NO_TEXT_DETECTED", "word_count": 0},
        )
    grouped: list[list[_Token]] = []
    for token in tokens:
        if not grouped or grouped[-1][0].line_key != token.line_key:
            grouped.append([token])
        else:
            grouped[-1].append(token)

    chunks: list[str] = []
    spans: list[VisualTextSpan] = []
    cursor = 0
    for line_tokens in grouped:
        separator = "" if not chunks else "\n"
        chunks.append(separator)
        cursor += len(separator)
        start = cursor
        line_text = " ".join(token.text for token in line_tokens)
        chunks.append(line_text)
        cursor += len(line_text)
        left = min(token.bbox["x"] for token in line_tokens)
        top = min(token.bbox["y"] for token in line_tokens)
        right = max(token.bbox["x"] + token.bbox["width"] for token in line_tokens)
        bottom = max(token.bbox["y"] + token.bbox["height"] for token in line_tokens)
        spans.append(
            VisualTextSpan(
                text=line_text,
                start=start,
                end=cursor,
                bbox={
                    "x": left,
                    "y": top,
                    "width": right - left,
                    "height": bottom - top,
                },
                confidence=sum(token.confidence for token in line_tokens) / len(line_tokens),
            )
        )
    return VisualResult(
        mode=MODE_OCR,
        region_id=region_id,
        confidence=sum(token.confidence for token in tokens) / len(tokens),
        text="".join(chunks),
        provider="local",
        name="tesseract",
        version=version,
        model="tesseract-lstm",
        spans=tuple(spans),
        metadata={
            "word_count": len(tokens),
            "line_count": len(grouped),
            "position_source": "tesseract-tsv",
        },
    )


class TesseractVisualProvider:
    """Literal OCR only; visual description and HTR remain unsupported."""

    provider_kind = "local"
    name = "tesseract"
    LANGUAGE_CODES = {
        "de": "deu",
        "en": "eng",
        "es": "spa",
        "fr": "fra",
        "it": "ita",
        "pt": "por",
    }

    def __init__(
        self,
        executable: str | os.PathLike[str] | None = None,
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        resolved = find_tesseract(executable)
        if not resolved:
            raise TesseractNotAvailable(
                "Tesseract no está instalado; configura S9K_TESSERACT_CMD"
            )
        self.executable = resolved
        self.timeout_seconds = timeout_seconds
        self.version = self._version()

    def _version(self) -> str:
        completed = subprocess.run(
            [self.executable, "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
        )
        first_line = (completed.stdout or completed.stderr).splitlines()[0]
        return first_line.removeprefix("tesseract ").strip() or "unknown"

    @staticmethod
    def _cropped_png(request: VisualRequest) -> tuple[bytes, int, int]:
        try:
            with Image.open(io.BytesIO(request.data)) as image:
                image.load()
                width, height = image.size
                bbox = request.region.bbox
                left = round(float(bbox["x"]) * width)
                top = round(float(bbox["y"]) * height)
                right = round((float(bbox["x"]) + float(bbox["width"])) * width)
                bottom = round((float(bbox["y"]) + float(bbox["height"])) * height)
                if not (0 <= left < right <= width and 0 <= top < bottom <= height):
                    raise ValueError("bbox de región fuera de la imagen")
                cropped = image.crop((left, top, right, bottom)).convert("RGB")
                output = io.BytesIO()
                cropped.save(output, format="PNG")
                return output.getvalue(), cropped.width, cropped.height
        except (UnidentifiedImageError, OSError) as exc:
            raise _UnreadableImage("fuente visual ilegible") from exc

    def recognize(self, request: VisualRequest) -> VisualResult | None:
        if request.mode != MODE_OCR:
            return None
        try:
            png, width, height = self._cropped_png(request)
        except _UnreadableImage:
            return VisualResult(
                mode=MODE_OCR,
                region_id=request.region.region_id,
                confidence=0.0,
                text="",
                provider="local",
                name="tesseract",
                version=self.version,
                model="tesseract-lstm",
                metadata={"diagnostic": "OCR_UNREADABLE_IMAGE", "word_count": 0},
            )
        language_hint = (request.language_hint or "en").split("-", 1)[0].lower()
        language = self.LANGUAGE_CODES.get(language_hint, language_hint)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            handle.write(png)
            input_path = Path(handle.name)
        try:
            completed = subprocess.run(
                [
                    self.executable,
                    str(input_path),
                    "stdout",
                    "-l",
                    language,
                    "--psm",
                    "6",
                    "tsv",
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
            )
        finally:
            input_path.unlink(missing_ok=True)
        tokens = _tokens_from_tsv(
            completed.stdout,
            image_width=width,
            image_height=height,
            region_bbox=request.region.bbox,
        )
        return _result_from_tokens(
            tokens,
            region_id=request.region.region_id,
            version=self.version,
        )
