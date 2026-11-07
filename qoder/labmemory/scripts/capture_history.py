from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.goto("http://127.0.0.1:8000/", wait_until="networkidle", timeout=30000)
    page.wait_for_selector("#history-list .question", timeout=15000)
    page.locator("#history-list").scroll_into_view_if_needed()
    page.wait_for_timeout(500)
    box = page.locator("#history-list").bounding_box()
    clip = {"x": max(0, box["x"] - 20), "y": max(0, box["y"] - 70), "width": min(1400, box["width"] + 40), "height": min(700, box["height"] + 100)}
    page.screenshot(path="/mnt/d/deepseek/qoder-2026/qoder/labmemory/docs/screenshots/history.png", clip=clip)
    print("HISTORY_ITEMS", page.locator("#history-list .question").count())
    print("BOX", box)
    browser.close()
