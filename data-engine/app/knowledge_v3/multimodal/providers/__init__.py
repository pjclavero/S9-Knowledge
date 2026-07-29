"""Concrete local providers for multimodal normalization."""

from .tesseract import TesseractNotAvailable, TesseractVisualProvider

__all__ = ["TesseractNotAvailable", "TesseractVisualProvider"]
