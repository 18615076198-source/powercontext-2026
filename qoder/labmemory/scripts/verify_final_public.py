from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)[:200]))
    page.on("console", lambda msg: errors.append(msg.text[:200]) if msg.type == "error" else None)
    page.goto("https://labmemory-lasfpz26o0f.qoder.website", wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(1200)
    print("TITLE", page.title())
    print("VIDEO", page.locator("video").evaluate("v => v.duration"))
    print("HISTORY_IMG", page.locator(".qoder-shot img").evaluate("el => el.naturalWidth + 'x' + el.naturalHeight"))
    print("USAGE", page.locator("#usage").inner_text()[:180].replace("\n", " | "))
    page.locator("#usage").scroll_into_view_if_needed()
    page.wait_for_timeout(500)
    page.screenshot(path="/mnt/d/deepseek/qoder-2026/qoder/labmemory/docs/screenshots/final-public-usage.png", full_page=False)
    print("ERRORS", errors)
    browser.close()
