"""Screenshot the built demo page with Playwright + the local puppeteer Chrome."""
import glob, http.server, os, socketserver, sys, threading, time
from playwright.sync_api import sync_playwright

ROOT = os.path.expanduser("c/components/timeseries")
DIST = os.path.join(ROOT, "dist")
SHOTS = os.path.join(ROOT, "shots")
PORT = 8731

CHROME = sorted(glob.glob(os.path.expanduser(
    "[源] chrome-linux64/chrome")))[-1]


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=DIST, **kw)
    def log_message(self, *a):
        pass


def serve():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main():
    os.makedirs(SHOTS, exist_ok=True)
    httpd = serve()
    time.sleep(0.4)
    print("chrome:", CHROME)
    errors = []

    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        pg = b.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=2)
        pg.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

        pg.goto(f"http://127.0.0.1:{PORT}/", wait_until="networkidle")
        # Wait until every section has rendered its charts.
        pg.wait_for_selector(".ts-card", timeout=20000)
        pg.wait_for_function("document.querySelectorAll('canvas').length >= 4", timeout=20000)
        pg.wait_for_timeout(1200)

        shots = [
            ("01_top_startup", "#startup"),
            ("02_fullrun", "#fullrun"),
            ("03_baseline", "#baseline"),
            ("04_perf", "#perf"),
        ]
        # Viewport shot of the top of the page first.
        pg.evaluate("window.scrollTo(0,0)")
        pg.wait_for_timeout(400)
        pg.screenshot(path=os.path.join(SHOTS, "00_page_top.png"))
        print("saved 00_page_top.png")

        for name, sel in shots:
            pg.eval_on_selector(sel, "el => el.scrollIntoView({block:'start'})")
            pg.wait_for_timeout(700)
            pg.screenshot(path=os.path.join(SHOTS, f"{name}.png"))
            print("saved", name)

        # Cursor readout: hover the middle of the full-run plot.
        pg.eval_on_selector("#fullrun", "el => el.scrollIntoView({block:'start'})")
        pg.wait_for_timeout(500)
        box = pg.query_selector("#fullrun canvas").bounding_box()
        pg.mouse.move(box["x"] + box["width"] * 0.42, box["y"] + box["height"] * 0.5)
        pg.wait_for_timeout(500)
        pg.screenshot(path=os.path.join(SHOTS, "05_cursor_readout.png"))
        print("saved 05_cursor_readout.png")

        # Expanded card modal.
        pg.evaluate("window.scrollTo(0,0)")
        pg.wait_for_timeout(300)
        pg.click(".ts-card--clickable:nth-of-type(2)")
        pg.wait_for_selector(".modal", timeout=8000)
        pg.wait_for_timeout(900)
        pg.screenshot(path=os.path.join(SHOTS, "06_modal_fail_expanded.png"))
        print("saved 06_modal_fail_expanded.png")

        # Drag-zoom inside the modal chart to prove box selection works.
        mbox = pg.query_selector(".modal canvas").bounding_box()
        y = mbox["y"] + mbox["height"] * 0.5
        pg.mouse.move(mbox["x"] + mbox["width"] * 0.48, y)
        pg.mouse.down()
        pg.mouse.move(mbox["x"] + mbox["width"] * 0.75, y, steps=18)
        pg.mouse.up()
        pg.wait_for_timeout(800)
        pg.mouse.move(mbox["x"] + mbox["width"] * 0.5, y)
        pg.wait_for_timeout(400)
        pg.screenshot(path=os.path.join(SHOTS, "07_modal_zoomed.png"))
        print("saved 07_modal_zoomed.png")

        b.close()
    httpd.shutdown()

    if errors:
        print("\n=== CONSOLE ERRORS ===")
        for e in errors:
            print(" ", e)
        return 1
    print("\nno console errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
