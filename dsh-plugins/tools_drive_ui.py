#!/usr/bin/env python3
"""Drive the dsh Web UI with Playwright: send one prompt, wait, screenshot.

Handles the two first-run gates this build shows before the composer accepts
input: the "Internal Testing Notice" modal, and the workspace picker.

Usage: tools_drive_ui.py <url-with-token> <prompt> <shot-prefix> [wait_s]
"""
import sys, time, pathlib
from playwright.sync_api import sync_playwright

CHROME = sorted(pathlib.Path.home().glob(".cache/puppeteer/chrome/*/chrome-linux64/chrome"))[-1]
ROOT = pathlib.Path.home() / "lab/dsh-plugins"
SHOTS = ROOT / "shots"
SHOTS.mkdir(parents=True, exist_ok=True)

url, prompt, prefix = sys.argv[1], sys.argv[2], sys.argv[3]
wait_s = float(sys.argv[4]) if len(sys.argv) > 4 else 120.0

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=str(CHROME), args=["--no-sandbox"])
    pg = b.new_page(viewport={"width": 1440, "height": 950})
    pg.goto(url, wait_until="domcontentloaded", timeout=90000)
    pg.wait_for_timeout(9000)
    pg.screenshot(path=str(SHOTS / f"{prefix}-01-loaded.png"))

    # Gate 1: the developer-preview notice modal.
    cont = pg.get_by_role("button", name="Continue")
    if cont.count() and cont.first.is_visible():
        cont.first.click()
        pg.wait_for_timeout(1500)
        print("dismissed: Internal Testing Notice")

    # Gate 2: the composer stays inert until a workspace is chosen. On a fresh
    # $DSH_HOME the app opens its own "Select Workspace Directory" browser; on a
    # returning one the choice is behind the composer's "Choose workspace" menu.
    # Both are driven here.
    def gated():
        return "Choose a workspace to start" in pg.inner_text("body")

    for attempt in range(3):
        if not gated():
            break
        if pg.get_by_text("Select Workspace Directory").count() == 0:
            pg.get_by_text("Choose workspace", exact=False).first.click()
            pg.wait_for_timeout(1500)
            # A returning profile offers the workspace directly in a menu.
            mi = pg.get_by_role("menuitem", name="dsh-plugins")
            if mi.count():
                bb = mi.first.bounding_box()
                pg.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
                pg.wait_for_timeout(4000)
                continue
            add = pg.get_by_role("menuitem", name="Add workspace…")
            if add.count():
                bb = add.first.bounding_box()
                pg.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
                pg.wait_for_timeout(2500)
        # The directory browser: descend lab -> dsh-plugins, then Open.
        pg.screenshot(path=str(SHOTS / f"{prefix}-02a-dirpicker-{attempt}.png"))
        for segment in ("lab", "dsh-plugins"):
            row = pg.get_by_text(segment, exact=True)
            if row.count():
                bb = row.first.bounding_box()
                pg.mouse.dblclick(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
                pg.wait_for_timeout(2000)
        pg.screenshot(path=str(SHOTS / f"{prefix}-02b-dirpicked-{attempt}.png"))
        op = pg.get_by_role("button", name="Open")
        if op.count():
            op.first.click()
            pg.wait_for_timeout(5000)

    print("workspace ready:", not gated())
    pg.screenshot(path=str(SHOTS / f"{prefix}-02-ready.png"))

    box = pg.locator("div[role='textbox'][contenteditable='true']").first
    if not box.count():
        box = pg.locator("div[role='textbox'], textarea").first
    box.click(timeout=20000)
    pg.keyboard.insert_text(prompt)
    pg.wait_for_timeout(800)
    pg.screenshot(path=str(SHOTS / f"{prefix}-03-typed.png"))
    pg.keyboard.press("Enter")

    deadline = time.time() + wait_s
    n = 0
    while time.time() < deadline:
        pg.wait_for_timeout(15000)
        n += 1
        pg.screenshot(path=str(SHOTS / f"{prefix}-04-progress-{n:02d}.png"))
    pg.screenshot(path=str(SHOTS / f"{prefix}-05-final.png"), full_page=True)
    txt = pg.inner_text("body")
    (ROOT / f"logs/{prefix}-ui-text.txt").write_text(txt, encoding="utf-8")
    print("---- UI TEXT (tail) ----")
    print(txt[-5000:])
    b.close()
