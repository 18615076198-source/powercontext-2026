from playwright.sync_api import sync_playwright

errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.on("pageerror", lambda exc: errors.append("PAGEERROR " + str(exc)[:200]))
    page.on("console", lambda msg: errors.append("CONSOLE " + msg.text[:200]) if msg.type == "error" else None)
    page.goto("http://127.0.0.1:8080/", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(800)
    page.screenshot(path="/mnt/d/deepseek/qoder-2026/qoder/labmemory/docs/screenshots/site-hero.png", full_page=False)
    page.screenshot(path="/mnt/d/deepseek/qoder-2026/qoder/labmemory/docs/screenshots/site-full.png", full_page=True)
    print("TITLE", page.title())
    print("H1", page.inner_text("h1")[:120].replace("\n", " "))
    print("SECTIONS", page.locator("section").count())
    browser.close()
print("ERRORS", len(errors))
for e in errors[:10]:
    print(e)
