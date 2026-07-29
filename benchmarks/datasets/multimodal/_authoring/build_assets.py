"""Rebuild deterministic native-PDF and scanned-image fixtures."""
from __future__ import annotations

import io
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "sources"
TEXT = (SOURCES / "bruma.txt").read_text(encoding="utf-8")


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


def build_scan() -> None:
    image = Image.new("L", (1600, 1050), 242)
    draw = ImageDraw.Draw(image)
    font = _font(34)
    y = 80
    for paragraph in TEXT.split("\n\n"):
        words = paragraph.split()
        line = ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if draw.textlength(candidate, font=font) > 1420:
                draw.text((85, y), line, fill=18, font=font)
                y += 52
                line = word
            else:
                line = candidate
        draw.text((85, y), line, fill=18, font=font)
        y += 82
    image = image.rotate(0.35, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=242)
    pixels = image.load()
    noise = random.Random(20260729)
    for _ in range(9000):
        x = noise.randrange(image.width)
        y = noise.randrange(image.height)
        pixels[x, y] = max(0, min(255, pixels[x, y] + noise.randint(-18, 18)))
    image.filter(ImageFilter.GaussianBlur(radius=0.35)).save(
        SOURCES / "bruma-scan.png",
        format="PNG",
        optimize=True,
    )


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_native_pdf() -> None:
    lines: list[str] = []
    for paragraph in TEXT.split("\n\n"):
        words = paragraph.split()
        line = ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if len(candidate) > 88:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.extend([line, ""])
    commands = ["BT", "/F1 12 Tf", "54 790 Td", "16 TL"]
    for line in lines:
        commands.append(f"({_pdf_escape(line)}) Tj")
        commands.append("T*")
    commands.append("ET")
    stream = "\n".join(commands).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
        + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = io.BytesIO()
    output.write(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(output.tell())
        output.write(f"{number} 0 obj\n".encode("ascii"))
        output.write(obj)
        output.write(b"\nendobj\n")
    xref = output.tell()
    output.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.write(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode("ascii")
    )
    (SOURCES / "bruma-native.pdf").write_bytes(output.getvalue())


if __name__ == "__main__":
    build_scan()
    build_native_pdf()
