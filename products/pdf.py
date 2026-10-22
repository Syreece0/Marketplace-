"""PDF "product information sheet" generation (ReportLab).

The built-in PDF fonts only cover Latin characters, so the currency is printed
as its ISO code (e.g. "NGN 1,500.00") rather than a symbol.
"""
import io
from xml.sax.saxutils import escape

from django.conf import settings
from django.utils import timezone
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

NAVY = colors.HexColor("#172554")
SLATE = colors.HexColor("#334155")
MUTED = colors.HexColor("#64748B")
BORDER = colors.HexColor("#E2E8F0")


def _product_image(product, max_size_mm=80):
    if not product.image:
        return None
    try:
        with product.image.open("rb") as handle:
            with Image.open(handle) as img:
                img = img.convert("RGB")
                img.thumbnail((1000, 1000))
                buffer = io.BytesIO()
                img.save(buffer, format="JPEG", quality=85)
                width_px, height_px = img.size
    except (OSError, ValueError):
        return None
    buffer.seek(0)
    scale = min(max_size_mm * mm / width_px, max_size_mm * mm / height_px)
    return RLImage(buffer, width=width_px * scale, height=height_px * scale)


def build_product_pdf(product):
    """Return the PDF bytes for ``product``."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"{product.name} - product information",
        author=settings.SITE_NAME,
    )
    styles = getSampleStyleSheet()
    brand = ParagraphStyle("Brand", parent=styles["Normal"], textColor=MUTED, fontSize=9)
    title = ParagraphStyle(
        "ProductTitle", parent=styles["Title"], textColor=NAVY, fontSize=22, leading=26, alignment=0
    )
    heading = ParagraphStyle(
        "Section", parent=styles["Heading2"], textColor=SLATE, fontSize=12, spaceBefore=14
    )
    body = ParagraphStyle("Body", parent=styles["BodyText"], textColor=colors.HexColor("#0F172A"), leading=14)

    story = [
        Paragraph(escape(settings.SITE_NAME).upper() + " &middot; PRODUCT INFORMATION", brand),
        Spacer(1, 4 * mm),
        Paragraph(escape(product.name), title),
        Spacer(1, 3 * mm),
    ]

    image = _product_image(product)
    if image is not None:
        story += [image, Spacer(1, 5 * mm)]

    rows = [
        ["Price", f"{settings.CURRENCY_CODE} {product.price:,.2f}"],
        ["Category", product.category.name],
        ["Condition", product.get_condition_display()],
        ["Availability", "In stock" if product.in_stock else "Currently unavailable"],
        ["Seller", product.seller.shop_name],
    ]
    table = Table(
        [[Paragraph(f"<b>{escape(label)}</b>", body), Paragraph(escape(str(value)), body)] for label, value in rows],
        colWidths=[35 * mm, 125 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story += [table, Paragraph("Description", heading)]
    for block in product.description.splitlines() or [""]:
        story.append(Paragraph(escape(block) or "&nbsp;", body))

    story += [
        Spacer(1, 8 * mm),
        Paragraph(
            f"Generated on {timezone.localtime().strftime('%d %B %Y')}. "
            "Prices and availability may change; please check the listing for current details.",
            brand,
        ),
    ]
    doc.build(story)
    return buffer.getvalue()
