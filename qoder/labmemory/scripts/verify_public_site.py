from playwright.sync_api import sync_playwright

URL = "https://labmemory-lasfpz26o0f.qoder.website"
errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    page.on("pageerror", lambda exc: errors.append("PAGEERROR " + str(exc)[:200]))
    page.goto(URL, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(800)
    print("STATUS", page.title())
    print("H1", page.inner_text("h1")[:120].replace("\n", " "))
    print("HAS_VIDEO", page.locator("video").count())
    page.screenshot(path="/mnt/d/deepseek/qoder-2026/qoder/labmemory/docs/screenshots/qoder-site.png", full_page=False)
    browser.close()
print("ERRORS", len(errors))
for e in errors[:10]:
    print(e)
