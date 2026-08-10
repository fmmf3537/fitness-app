"""V2-2 报告导出：Markdown / PDF（reportlab，CJK 字体）。"""
from datetime import date

from pypdf import PdfReader

from app.models import AIReport
from app.services import export as export_service


def _weekly_report():
    return AIReport(
        type="weekly",
        period_start=date(2026, 8, 3),
        period_end=date(2026, 8, 9),
        model="deepseek-chat",
        content_md="# 本周概览\n本周训练 3 次，总容量 4520 kg。\n"
                   "## 下周建议\n- 卧推加到 62.5kg\n- 保证睡眠",
    )


def _monthly_report():
    return AIReport(
        type="monthly",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        model="deepseek-chat",
        content_md="# 月度概览\n计划完成率 83.3%。",
    )


class TestRenderMarkdown:
    def test_contains_title_period_and_content(self):
        md = export_service.render_markdown(_weekly_report())
        assert "周复盘" in md
        assert "2026-08-03" in md and "2026-08-09" in md
        assert "本周训练 3 次" in md
        assert "deepseek-chat" in md

    def test_monthly_title(self):
        md = export_service.render_markdown(_monthly_report())
        assert "月复盘" in md


class TestRenderPdf:
    def test_pdf_openable_and_contains_chinese(self, tmp_path):
        data = export_service.render_pdf(_weekly_report())
        assert data.startswith(b"%PDF")
        path = tmp_path / "weekly.pdf"
        path.write_bytes(data)

        reader = PdfReader(str(path))
        assert len(reader.pages) >= 1
        text = "".join(page.extract_text() for page in reader.pages)
        assert "周复盘" in text
        assert "本周概览" in text
        assert "卧推加到 62.5kg" in text

    def test_pdf_monthly(self, tmp_path):
        data = export_service.render_pdf(_monthly_report())
        path = tmp_path / "monthly.pdf"
        path.write_bytes(data)
        reader = PdfReader(str(path))
        text = "".join(page.extract_text() for page in reader.pages)
        assert "月复盘" in text
        assert "83.3%" in text


class TestRenderPdfEdgeCases:
    def test_pdf_with_echarts_code_block(self, tmp_path):
        report = _weekly_report()
        report.content_md = ("# 本周概览\n内容\n```echarts\n"
                             '{"series": [{"type": "pie"}]}\n```\n')
        data = export_service.render_pdf(report)
        path = tmp_path / "echarts.pdf"
        path.write_bytes(data)
        reader = PdfReader(str(path))
        text = "".join(page.extract_text() for page in reader.pages)
        assert "本周概览" in text
        assert "series" in text  # 代码块以等宽文本渲染进 PDF

    def test_pdf_with_unclosed_code_block(self, tmp_path):
        report = _weekly_report()
        report.content_md = "# 标题\n```echarts\n{\"a\": 1}"
        data = export_service.render_pdf(report)
        path = tmp_path / "unclosed.pdf"
        path.write_bytes(data)
        reader = PdfReader(str(path))
        assert len(reader.pages) >= 1

    def test_report_without_period(self):
        report = AIReport(type="weekly", content_md="内容")
        assert "周复盘" in export_service.report_title(report)
        assert "unknown" in export_service.report_filename(report, "md")
        md = export_service.render_markdown(report)
        assert "周复盘" in md


class TestReportFilename:
    def test_weekly_filename(self):
        name = export_service.report_filename(_weekly_report(), "md")
        assert name == "weekly_2026-08-03_2026-08-09.md"

    def test_monthly_pdf_filename(self):
        name = export_service.report_filename(_monthly_report(), "pdf")
        assert name == "monthly_2026-08-01_2026-08-31.pdf"
