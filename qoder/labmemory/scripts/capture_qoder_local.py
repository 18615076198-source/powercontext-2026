from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1100})
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)[:200]))
    page.on("console", lambda msg: errors.append(msg.text[:200]) if msg.type == "error" else None)
    page.goto("http://127.0.0.1:8080/", wait_until="networkidle", timeout=30000)
    page.locator("#qoder").scroll_into_view_if_needed()
    page.wait_for_timeout(600)
    page.screenshot(path="/mnt/d/deepseek/qoder-2026/qoder/labmemory/docs/screenshots/qoder-section-new.png", full_page=False)
    print("HISTORY_IMG", page.locator(".qoder-shot img").evaluate("el => el.naturalWidth + 'x' + el.naturalHeight"))
    print("ERRORS", errors)
    browser.close()
