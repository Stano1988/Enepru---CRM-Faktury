"""Render the owner's cell geometry, styles and borders, without running XLSM macros."""

import io
import json
import math
import os
import re
from functools import lru_cache
from pathlib import Path
from threading import Lock
from xml.sax.saxutils import escape

from django.core.exceptions import ValidationError
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

ROOT = Path(__file__).resolve().parents[1]
FONT_LOCK = Lock()


@lru_cache(maxsize=1)
def template():
    return json.loads(
        (ROOT / "assets" / "invoice" / "template.json").read_text(encoding="utf-8")
    )


def fonts():
    with FONT_LOCK:
        if "InvoiceArial" not in pdfmetrics.getRegisteredFontNames():
            # Windows uses the same installed Arial as the original Excel workbook.
            directory = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
            regular = directory / "arial.ttf"
            bold = directory / "arialbd.ttf"
            if not regular.is_file() or not bold.is_file():
                regular = ROOT / "assets" / "fonts" / "InvoiceSans.ttf"
                bold = regular.with_name("InvoiceSans-Bold.ttf")
            pdfmetrics.registerFont(TTFont("InvoiceArial", str(regular)))
            pdfmetrics.registerFont(TTFont("InvoiceArialBold", str(bold)))


def coordinates(ref):
    letters, row = re.fullmatch(r"([A-Z]+)(\d+)", ref).groups()
    col = 0
    for char in letters:
        col = col * 26 + ord(char) - 64
    return col, int(row)


def render(invoice):
    from .services import qr_png

    fonts()
    spec = template()
    # Excel character widths use the Arial/Calibri 7-pixel digit convention.
    widths = {
        int(k): math.floor(float(v) * 7 + 5) * 0.75 for k, v in spec["columns"].items()
    }
    heights = {int(k): v for k, v in spec["rows"].items()}
    xs = {1: 0.0}
    for col in range(1, 10):
        xs[col + 1] = xs[col] + widths[col]
    ys = {3: 0.0}
    for row in range(3, 50):
        ys[row + 1] = ys[row] + heights.get(row, 12.75)

    def box(ref):
        col, row = coordinates(ref)
        return xs[col], ys[row], widths[col], heights.get(row, 12.75)

    merged = {}
    suppressed = set()
    for area in spec["merges"]:
        first, last = area.split(":")
        c1, r1 = coordinates(first)
        c2, r2 = coordinates(last)
        merged[first] = (xs[c1], ys[r1], xs[c2 + 1] - xs[c1], ys[r2 + 1] - ys[r1])
        for row in range(r1, r2 + 1):
            for col in range(c1, c2 + 1):
                if (col, row) != (c1, r1):
                    suppressed.add((col, row))

    def money(amount):
        return f"{amount:,.2f}".replace(",", " ").replace(".", ",")

    supplier = invoice.supplier
    recipient = invoice.recipient

    def address_parts(address):
        parts = address.splitlines()
        return (parts[0] if parts else "", ", ".join(parts[1:]))

    street, city = address_parts(supplier["address"])
    buyer_street, buyer_city = address_parts(recipient["address"])

    def company_id(value):
        digits = value.replace(" ", "")
        return (
            f"{digits[:3]} {digits[3:5]} {digits[5:]}"
            if len(digits) == 8 and digits.isdigit()
            else value
        )

    values = {
        "B3": "Zálohová výzva" if invoice.kind == "advance" else "Faktura    ",
        "H3": " číslo: " + invoice.number,
        "C7": supplier["name"],
        "C8": street,
        "C9": city,
        "C11": "IČ: " + company_id(supplier["company_id"]),
        "C12": "Dodavatel neni plátce DPH",
        "G7": recipient["name"],
        "G8": buyer_street,
        "G9": buyer_city,
        "G11": ("IČ: " + company_id(recipient.get("company_id", "")))
        if recipient.get("company_id")
        else "",
        "G12": ("DIČ: " + recipient.get("tax_id", ""))
        if recipient.get("tax_id")
        else "",
        "D19": "Převodem",
        "D20": supplier["bank_name"],
        "D21": supplier["bank_account"],
        "D22": invoice.variable_symbol,
        "I18": invoice.issue_date.strftime("%d.%m.%Y"),
        "I19": invoice.issue_date.strftime("%d.%m.%Y"),
        "I21": invoice.due_date.strftime("%d.%m.%Y"),
        "B44": "Vystavil: " + supplier["name"],
        "F45": money(invoice.subtotal),
        "G45": "0",
        "H45": "0",
        "I45": money(invoice.subtotal),
        "G48": money(invoice.total),
    }
    if supplier["company_id"].replace(" ", "") != "21639108":
        values.update(B14="", B15="")
    line_objects = list(invoice.lines.all())
    if len(line_objects) > (12 if invoice.advance_id else 14):
        raise ValidationError(
            "Předloha umožňuje nejvýše 14 řádků. Spojte texty do jednoho popisu faktury."
        )
    for index, line in enumerate(line_objects):
        row = 30 + index
        values.update(
            {
                f"B{row}": line.description,
                f"D{row}": money(line.unit_price),
                f"E{row}": str(line.quantity.normalize()),
                f"F{row}": money(line.total),
                f"G{row}": "0",
                f"H{row}": "0",
                f"I{row}": money(line.total),
            }
        )
    if invoice.advance_id:
        values["B42"] = "Odečet zálohy " + invoice.advance.number
        values["I42"] = "−" + money(invoice.advance_amount)
    out = io.BytesIO()
    page = canvas.Canvas(out, pagesize=(595.276, 841.89))
    page.setTitle(invoice.number)
    page.setAuthor(supplier["name"])
    # Original page margins: 6 mm left/right, 9 mm top, 16 mm bottom.
    scale = min(1, (595.276 - 34.016) / xs[10], (841.89 - 25.512 - 45.354) / ys[50])
    page.translate(17.008, 841.89 - 25.512)
    page.scale(scale, scale)
    # Keep every individual edge from the source cells, including merged outlines.
    for cell in spec["cells"]:
        x, y, w, h = box(cell["ref"])
        style = spec["styles"][cell["style"]]
        for side, weight in spec["borders"][style["border"]].items():
            page.setLineWidth(1.4 if weight == "medium" else 0.6)
            points = {
                "left": (x, -y, x, -y - h),
                "right": (x + w, -y, x + w, -y - h),
                "top": (x, -y, x + w, -y),
                "bottom": (x, -y - h, x + w, -y - h),
            }
            page.line(*points[side])
    cells_by_ref = {cell["ref"]: cell for cell in spec["cells"]}
    for cell in spec["cells"]:
        ref = cell["ref"]
        col, row = coordinates(ref)
        if (col, row) in suppressed:
            continue
        text = str(values.get(ref, cell["text"]))
        if not text.strip():
            continue
        x, y, w, h = merged.get(ref, box(ref))
        style = spec["styles"][cell["style"]]
        font = spec["fonts"][style["font"]]
        # Excel text may spill into an adjacent empty cell (e.g. name in G7:I7).
        if ref not in merged and col < 9 and ref not in ("G48",):
            for next_col in range(col + 1, 10):
                next_ref = chr(64 + next_col) + str(row)
                next_text = values.get(
                    next_ref, cells_by_ref.get(next_ref, {}).get("text", "")
                )
                if str(next_text).strip():
                    break
                w += widths[next_col]
        if col == 2 and 30 <= row <= 43:
            w = xs[4] - xs[2]
            if len(line_objects) == 1:
                h = ys[44] - y
        name = "InvoiceArialBold" if font["bold"] else "InvoiceArial"
        alignment = style["alignment"]
        align = {"center": 1, "right": 2}.get(alignment.get("horizontal"), 0)
        if (
            ref in values
            and ref[0] in "DEFGHI"
            and 30 <= row <= 49
            and ref not in ("D48", "H28")
        ):
            align = 2
        indent = int(alignment.get("indent", "0")) * font["size"] * 0.8
        size = font["size"]
        available = max(6, w - 4 - indent)
        for _ in range(24):
            paragraph = Paragraph(
                escape(text).replace("\n", "<br/>"),
                ParagraphStyle(
                    "cell",
                    fontName=name,
                    fontSize=size,
                    leading=size * 1.12,
                    alignment=align,
                ),
            )
            _, text_height = paragraph.wrap(available, 10000)
            if text_height <= h + 1 or size <= 5:
                break
            size -= 0.35
        # Bottom alignment matches Excel's default, with a 1pt cell inset.
        top = y + (
            max(0, (h - text_height) / 2)
            if alignment.get("vertical") == "center"
            else 1
            if alignment.get("vertical") == "top"
            else max(0, h - text_height - 1)
        )
        if col == 2 and 30 <= row <= 43:
            top = y + 1
        paragraph.drawOn(page, x + 2 + indent, -top - text_height)
    if invoice.total > 0:
        qx = xs[7] + 455613 / 12700
        qy = ys[23] + 1
        page.drawImage(
            ImageReader(io.BytesIO(qr_png(invoice))), qx, -qy - 97, 97, 97, mask="auto"
        )
    page.showPage()
    page.save()
    return out.getvalue()
