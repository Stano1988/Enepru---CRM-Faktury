"""Bundled Czech glyph coverage, independent of fonts installed on Windows."""

from pathlib import Path
from threading import Lock

_LOCK = Lock()


def register():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    with _LOCK:
        if "CRMUnicode" not in pdfmetrics.getRegisteredFontNames():
            font = (
                Path(__file__).resolve().parents[1]
                / "assets"
                / "fonts"
                / "DejaVuSans.ttf"
            )
            pdfmetrics.registerFont(TTFont("CRMUnicode", str(font)))
    return "CRMUnicode"
