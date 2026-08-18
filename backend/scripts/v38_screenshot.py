"""V3-8 实测截图脚本：登录 → 打开报告 2 → 展开追问对话 → 截图。

用法：.venv\\Scripts\\python.exe scripts\\v38_screenshot.py
前置：后端 :8000、前端 :5173 已启动，且报告 2 已有真实追问对话。
"""
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://localhost:5173"
PASSWORD = "5213537"
OUT = "scripts/v38_report_chat_screenshot.png"


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")  # 复用本机 Edge，免下载 chromium
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(f"{BASE}/login", wait_until="networkidle")
        page.fill('input[type="password"]', PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_url(f"{BASE}/", timeout=10000)

        page.goto(f"{BASE}/ai-reports", wait_until="networkidle")
        page.click('[data-testid="report-card-2"]')
        page.wait_for_selector('[data-testid="report-detail"]')

        page.click('[data-testid="chat-expand-btn"]')
        page.wait_for_selector('[data-testid="chat-thread"]')
        page.wait_for_selector('[data-testid^="chat-msg-assistant-"]', timeout=10000)
        time.sleep(1)  # 等渲染与滚动稳定

        # 线程滚回顶部，保证用户气泡与回复同框
        page.eval_on_selector('[data-testid="chat-thread"]', "el => el.scrollTo(0, 0)")
        section = page.locator('[data-testid="chat-section"]')
        section.scroll_into_view_if_needed()
        time.sleep(0.5)
        section.screenshot(path=OUT)
        browser.close()
    print(f"screenshot saved: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
