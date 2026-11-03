"""用 Playwright 驱动 chrome，对 Demo 页做实机演示截图（1600x900）。"""
import asyncio, glob, pathlib
from playwright.async_api import async_playwright

CHROME = sorted(glob.glob("[源] chrome-linux64/chrome"))[-1]
OUT = pathlib.Path(__file__).parent
CMDS = ["hostname", "tasklist | findstr /i motordebug", "dir C:\\fc_pull"]

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        pg = await b.new_page(viewport={"width": 1600, "height": 900})
        pg.on("console", lambda m: print("[console]", m.type, m.text[:160]))
        await pg.goto("http://localhost:5173", wait_until="networkidle")
        await pg.wait_for_timeout(6000)
        await pg.screenshot(path=OUT / "01-demo-overview.png")
        print("01 ok")

        # 在终端里逐条敲三条真实命令
        await pg.click(".rt-screen")
        for c in CMDS:
            await pg.keyboard.type(c)
            await pg.keyboard.press("Enter")
            await pg.wait_for_timeout(4500)
        await pg.screenshot(path=OUT / "02-terminal-live-commands.png")
        print("02 ok")

        # 远程截图：点第一张卡的"远程截图"
        btns = pg.locator(".app-col:last-of-type .rd-card .rt-btn", has_text="远程截图")
        await btns.first.click()
        await pg.wait_for_timeout(25000)
        await pg.screenshot(path=OUT / "03-remote-screenshot.png")
        print("03 ok")

        # 放大遮罩
        await pg.locator(".app-col:last-of-type .rd-thumb").first.click()
        await pg.wait_for_timeout(1200)
        await pg.screenshot(path=OUT / "04-screenshot-zoom.png")
        print("04 ok")
        await b.close()

asyncio.run(main())
