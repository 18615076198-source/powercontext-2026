from playwright.sync_api import sync_playwright
import os

BASE = "http://127.0.0.1:8000"
OUT = "/mnt/d/deepseek/qoder-2026/qoder/labmemory/docs/screenshots"
os.makedirs(OUT, exist_ok=True)
errors = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
    page.on("pageerror", lambda exc: errors.append("PAGEERROR: " + str(exc)[:300]))
    page.on("console", lambda msg: errors.append("CONSOLE " + msg.type + ": " + msg.text[:300]) if msg.type == "error" else None)

    page.goto(BASE + "/", wait_until="networkidle", timeout=30000)
    page.screenshot(path=OUT + "/dashboard.png", full_page=False)
    print("dashboard", page.inner_text("#status"))

    page.click("#hero-ask")
    page.wait_for_selector("#ask-input", timeout=10000)
    page.fill("#ask-input", "我们为什么放弃 Self-RAG 的全量自反思？")
    page.click("#ask-form button[type=submit]")
    page.wait_for_selector(".answer-card", timeout=40000)
    page.wait_for_timeout(700)
    page.screenshot(path=OUT + "/ask.png", full_page=False)
    print("ask", page.inner_text(".answer-card .answer-text")[:120].replace("\n", " "))

    page.click('a[data-route="library"]')
    page.wait_for_selector(".paper-grid", timeout=15000)
    page.screenshot(path=OUT + "/library.png", full_page=False)
    print("library cards", page.locator(".paper-card").count())

    page.click('a[data-route="memory"]')
    page.wait_for_selector("#memory-list .memory-card", timeout=15000)
    page.screenshot(path=OUT + "/memory.png", full_page=False)
    print("memory cards", page.locator("#memory-list .memory-card").count())

    page.click('a[data-route="conflicts"]')
    page.wait_for_selector(".conflict-card", timeout=15000)
    page.screenshot(path=OUT + "/conflicts.png", full_page=False)
    print("conflicts", page.locator(".conflict-card").count())

    mobile = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
    mobile.goto(BASE + "/", wait_until="networkidle", timeout=30000)
    mobile.screenshot(path=OUT + "/mobile.png", full_page=False)
    mobile.close()

    browser.close()

print("ERRORS", len(errors))
for e in errors[:20]:
    print(e)
