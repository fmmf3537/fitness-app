"""V2-2 报告导出：Markdown / PDF。

PDF 用 reportlab + UnicodeCIDFont('STSong-Light')（Adobe CJK CID 字体，
无需外部字体文件，中文渲染正常）；Markdown 仅做轻量结构化（标题/列表/代码块/段落）。
"""
from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape

from app.models import AIReport

_TYPE_LABELS = {"weekly": "周复盘", "monthly": "月复盘",
                "session_review": "单次点评", "next_advice": "下次建议"}

_CJK_FONT = "STSong-Light"
_font_registered = False


def _ensure_font() -> None:
    global _font_registered
    if not _font_registered:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont

        pdfmetrics.registerFont(UnicodeCIDFont(_CJK_FONT))
        _font_registered = True


def report_title(report: AIReport) -> str:
    label = _TYPE_LABELS.get(report.type, report.type or "报告")
    if report.period_start and report.period_end:
        return f"{label}（{report.period_start.isoformat()} ~ {report.period_end.isoformat()}）"
    if report.period_start:
        return f"{label}（{report.period_start.isoformat()}）"
    return label


def report_filename(report: AIReport, fmt: str) -> str:
    start = report.period_start.isoformat() if report.period_start else "unknown"
    end = report.period_end.isoformat() if report.period_end else start
    return f"{report.type}_{start}_{end}.{fmt}"


def render_markdown(report: AIReport) -> str:
    """导出 Markdown：标题 + 元信息 + 报告正文。"""
    lines = [
        f"# {report_title(report)}",
        "",
        f"- 类型：{_TYPE_LABELS.get(report.type, report.type)}",
        f"- 模型：{report.model or '-'}",
        f"- tokens：{report.prompt_tokens or 0} / {report.completion_tokens or 0}",
        f"- 生成时间：{report.created_at.isoformat() if report.created_at else '-'}",
        "",
        "---",
        "",
        report.content_md or "（无内容）",
        "",
    ]
    return "\n".join(lines)


def _md_to_flowables(text: str, styles: dict):
    """轻量 Markdown → reportlab flowables（# / ## / - / 代码块 / 段落）。"""
    from reportlab.platypus import Paragraph, Preformatted, Spacer

    story = []
    in_code = False
    code_lines: list[str] = []
    for raw in (text or "").split("\n"):
        line = raw.rstrip()
        if line.strip().startswith("```"):
            if in_code:
                story.append(Preformatted("\n".join(code_lines) or " ", styles["code"]))
                code_lines = []
            in_code = not in_code
            continue
        if in_code:
            code_lines.append(line)
            continue
        if line.startswith("## "):
            story.append(Paragraph(escape(line[3:]), styles["h2"]))
        elif line.startswith("# "):
            story.append(Paragraph(escape(line[2:]), styles["h1"]))
        elif line.startswith("- "):
            story.append(Paragraph("• " + escape(line[2:]), styles["bullet"]))
        elif line.strip() == "":
            story.append(Spacer(1, 6))
        else:
            story.append(Paragraph(escape(line), styles["body"]))
    if code_lines:  # 未闭合代码块兜底
        from reportlab.platypus import Preformatted

        story.append(Preformatted("\n".join(code_lines), styles["code"]))
    return story


def render_pdf(report: AIReport) -> bytes:
    """导出 PDF 字节流（CJK 字体，中文正常显示）。"""
    _ensure_font()
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate

    styles = {
        "h1": ParagraphStyle("h1", fontName=_CJK_FONT, fontSize=18, leading=24,
                             spaceBefore=10, spaceAfter=6),
        "h2": ParagraphStyle("h2", fontName=_CJK_FONT, fontSize=14, leading=20,
                             spaceBefore=8, spaceAfter=4),
        "body": ParagraphStyle("body", fontName=_CJK_FONT, fontSize=10.5, leading=16),
        "bullet": ParagraphStyle("bullet", fontName=_CJK_FONT, fontSize=10.5,
                                 leading=16, leftIndent=12),
        "code": ParagraphStyle("code", fontName=_CJK_FONT, fontSize=9, leading=12,
                               leftIndent=8),
    }

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
        title=report_title(report),
    )
    story = _md_to_flowables(render_markdown(report), styles)
    doc.build(story)
    return buffer.getvalue()
