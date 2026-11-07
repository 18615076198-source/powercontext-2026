from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)[:200]))
    page.on("console", lambda msg: errors.append(msg.text[:200]) if msg.type == "error" else None)
    page.goto("http://127.0.0.1:8080/", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1000)
    print("VIDEO_DURATION", page.locator("video").evaluate("v => v.duration"))
    print("USAGE", page.locator("#usage").inner_text()[:300].replace("\n", " | "))
    page.locator("#usage").scroll_into_view_if_needed()
    page.wait_for_timeout(500)
    page.screenshot(path="/mnt/d/deepseek/qoder-2026/qoder/labmemory/docs/screenshots/usage.png", full_page=False)
    print("ERRORS", errors)
    browser.close()
