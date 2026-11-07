import os
import glob
import shutil
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
OUT = "/mnt/d/deepseek/qoder-2026/qoder/labmemory/docs/video"
os.makedirs(OUT, exist_ok=True)
for f in glob.glob(OUT + "/*.webm"):
    os.remove(f)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1280, "height": 800},
        record_video_dir=OUT,
        record_video_size={"width": 1280, "height": 800},
    )
    page = context.new_page()
    page.goto(BASE + "/", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1600)
    page.locator("#history-list").scroll_into_view_if_needed()
    page.wait_for_timeout(1500)
    page.locator("#history-list .question").last.click()
    page.wait_for_selector(".answer-card", timeout=40000)
    page.wait_for_timeout(1800)
    page.mouse.wheel(0, 520)
    page.wait_for_timeout(1800)
    page.mouse.wheel(0, 520)
    page.wait_for_timeout(1500)
    page.click('a[data-route="conflicts"]')
    page.wait_for_selector(".conflict-card", timeout=15000)
    page.wait_for_timeout(2200)
    page.click('a[data-route="memory"]')
    page.wait_for_selector("#memory-list .memory-card", timeout=15000)
    page.wait_for_timeout(1800)
    page.click('a[data-route="library"]')
    page.wait_for_selector(".paper-grid", timeout=15000)
    page.wait_for_timeout(1200)
    context.close()
    browser.close()

videos = sorted(glob.glob(OUT + "/*.webm"), key=os.path.getmtime)
if not videos:
    raise SystemExit("no video")
target = OUT + "/demo2.webm"
shutil.copyfile(videos[-1], target)
print("VIDEO", target, os.path.getsize(target))
