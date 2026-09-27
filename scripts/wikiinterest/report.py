"""One-page A4 PDF: title, KPI table, overview chart, recommendation, trust notes,
caveats. Numbers come from results.json; words come from the agent's narrative
(narrative.json) or from short auto-generated sentences when no narrative is given.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import List, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle, KeepInFrame)

from .i18n import labels

ASSETS = Path(__file__).resolve().parents[2] / "assets" / "fonts"
_FONTS_READY = False


def _register_fonts():
    global _FONTS_READY
    if _FONTS_READY:
        return
    reg = ASSETS / "DejaVuSans.ttf"
    bold = ASSETS / "DejaVuSans-Bold.ttf"
    if not reg.exists():  # fall back to matplotlib's copy of the same font
        import matplotlib
        d = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        reg, bold = d / "DejaVuSans.ttf", d / "DejaVuSans-Bold.ttf"
    pdfmetrics.registerFont(TTFont("DejaVu", str(reg)))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(bold)))
    pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold",
                                  italic="DejaVu", boldItalic="DejaVu-Bold")
    _FONTS_READY = True


def _fmt_pct(v: Optional[float], na: str) -> str:
    return na if v is None else f"{v:+.0f}%"


def _fmt_num(v: Optional[float], na: str) -> str:
    if v is None:
        return na
    return f"{v:,.0f}" if v >= 100 else f"{v:,.1f}"


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def auto_trust_lines(results: List[dict], L: dict, max_lines: int = 8) -> List[str]:
    lines = []
    for r in results:
        issues = r["trust"]["issues"]
        v = L.get(r["trust"]["verdict"], r["trust"]["verdict"])
        if issues:
            lines.append(f"<b>{r['lang']}</b> ({v}): " + "; ".join(i["detail"] for i in issues[:3]))
        else:
            lines.append(f"<b>{r['lang']}</b> ({v}): all checks passed")
    return lines[:max_lines]


def build_pdf(results: List[dict], comparison: dict, chart_png: Path, out: Path,
              lang: str = "en", topic: str = "", narrative: Optional[dict] = None) -> Path:
    _register_fonts()
    L = labels(lang)
    narrative = narrative or {}
    na = L["na"]

    body = ParagraphStyle("body", fontName="DejaVu", fontSize=8.3, leading=10.6, alignment=TA_LEFT)
    small = ParagraphStyle("small", parent=body, fontSize=7, leading=8.6, textColor=colors.HexColor("#555555"))
    h1 = ParagraphStyle("h1", parent=body, fontName="DejaVu-Bold", fontSize=15, leading=18)
    h2 = ParagraphStyle("h2", parent=body, fontName="DejaVu-Bold", fontSize=9.5, leading=12,
                        spaceBefore=4, spaceAfter=2)
    cell = ParagraphStyle("cell", parent=body, fontSize=7.6, leading=9.2)
    cellb = ParagraphStyle("cellb", parent=cell, fontName="DejaVu-Bold")

    start = min(r["window"]["start"] for r in results)
    end = max(r["window"]["end"] for r in results)
    langs = ", ".join(r["lang"] for r in results)
    title = narrative.get("title") or L["title"].format(topic=topic or results[0]["title"])

    story = [Paragraph(_esc(title), h1),
             Paragraph(_esc(L["subtitle"].format(langs=langs, start=start, end=end)), small),
             Spacer(1, 4 * mm)]

    # KPI table
    hdr = [Paragraph(h, cellb) for h in L["kpi_header"]]
    rows = [hdr]
    for r in results:
        t = r["title"] if len(r["title"]) <= 30 else r["title"][:28] + "…"
        rows.append([
            Paragraph(r["lang"], cellb), Paragraph(_esc(t), cell),
            Paragraph(_fmt_num(r["avg_daily_views"], na), cell),
            Paragraph(_fmt_pct(r["yoy_pct"], na), cell),
            Paragraph(_fmt_pct(r["yoy_despiked_pct"], na), cell),
            Paragraph(_fmt_num(r["share_per_million_last12"], na), cell),
            Paragraph(_fmt_pct(r["trend_annualised_pct"], na), cell),
            Paragraph(L.get(r["trust"]["verdict"], r["trust"]["verdict"]), cell),
        ])
    widths = [14 * mm, 42 * mm, 24 * mm, 18 * mm, 24 * mm, 24 * mm, 19 * mm, 17 * mm]
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#9aa5b1")),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#d8dee6")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story += [table, Spacer(1, 3 * mm)]

    # Chart
    if chart_png and Path(chart_png).exists():
        img = Image(str(chart_png))
        ratio = img.imageHeight / float(img.imageWidth)
        w = 181 * mm
        h = w * ratio
        max_h = 108 * mm if len(results) <= 4 else 96 * mm
        if h > max_h:
            h, w = max_h, max_h / ratio
        img.drawWidth, img.drawHeight = w, h
        story += [img, Spacer(1, 2 * mm)]

    # Recommendation
    rec = narrative.get("recommendation")
    if not rec:
        top = comparison["table"][0] if comparison and comparison.get("table") else None
        rec = (f"Auto-summary: {top['lang']} ranks first by '{comparison['rank_by']}' "
               f"({comparison['formula']}). Replace this with the agent's recommendation.") if top else ""
    if rec:
        story += [Paragraph(_esc(L["recommendation"]), h2), Paragraph(_esc(rec), body)]

    # Trust
    trust_lines = narrative.get("trust") or auto_trust_lines(results, L)
    story += [Paragraph(_esc(L["trust"]), h2)]
    for line in trust_lines[:8]:
        story.append(Paragraph("• " + line, body))

    # Caveats
    cav = narrative.get("caveats") or L["default_caveats"]
    story += [Paragraph(_esc(L["caveats"]), h2)]
    for c in cav[:4]:
        story.append(Paragraph("• " + _esc(c), small))
    story += [Spacer(1, 2 * mm),
              Paragraph(_esc(L["generated"].format(date=dt.date.today().isoformat())), small)]

    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=12 * mm, bottomMargin=10 * mm, title=title)
    frame_w = A4[0] - 28 * mm
    frame_h = A4[1] - 22 * mm
    # KeepInFrame shrinks content if it would spill to a second page: the report
    # is meant to be one page that people can share, never two.
    doc.build([KeepInFrame(frame_w, frame_h, story, mode="shrink")])
    return out
