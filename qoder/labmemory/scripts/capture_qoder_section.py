from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.goto("https://labmemory-lasfpz26o0f.qoder.website", wait_until="networkidle", timeout=60000)
    page.locator("#qoder").scroll_into_view_if_needed()
    page.wait_for_timeout(600)
    page.screenshot(path="/mnt/d/deepseek/qoder-2026/qoder/labmemory/docs/screenshots/qoder-section.png", full_page=False)
    print("OK", page.locator("#qoder").inner_text()[:200].replace("\n", " "))
    browser.close()
