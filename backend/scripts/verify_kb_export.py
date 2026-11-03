"""知识库整包导出验收（接口级）。

覆盖：端点可达、附件头正确、条目数齐全、文档产物不漏、插图齐全、清单文件齐、
边界如实（README 写明非原件 / 插图截断）、负路径（空 owner / 不存在归属）。

用法（先起后端 8011）：
    cd c/backend && <ra python> scripts/verify_kb_export.py
"""
from __future__ import annotations

import io
import json
import sys
import urllib.parse
import urllib.request
import zipfile

BASE = "http://127.0.0.1:8011"
OWNER = "FU6832 散热风扇驱动板"
SCENE = "motor.cooling-fan.fortior-fu6832"

# 数据侧 index.json 登记的本产品全部文档（13 份）
EXPECTED_DOCS = {
    "foc-debug-manual", "coolingfan-single-hall-appnote", "smo-pll-estimator",
    "ao-estimator", "foc-exec-logic", "omega-startup-logic",
    "tailwind-startup-training", "smo-angle-register-note", "runtime-logic",
    "bug-fix-summary-8080", "foc-exam-questions", "fu6832-datasheet",
    "customer-h-fu6832",
}

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> bool:
    results.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))
    return bool(cond)


def get(url: str) -> tuple[int, bytes, dict]:
    req = urllib.request.Request(url, headers={"Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.status, resp.read(), dict(resp.headers)


def hget(heads: dict, key: str) -> str:
    """HTTP 头大小写不敏感取值（urllib 保留服务器原始大小写，直接 get 会取空）。"""
    for k, v in heads.items():
        if k.lower() == key.lower():
            return v
    return ""


def main() -> int:
    # ① 正路径：带 scene（精确匹配 taxonomy）
    qs = urllib.parse.urlencode({"owner": OWNER, "scene": SCENE})
    print(f"GET /api/kb/documents/export?{qs}\n")
    try:
        code, body, heads = get(f"{BASE}/api/kb/documents/export?{qs}")
    except Exception as exc:  # noqa: BLE001
        print(f"请求失败：{exc}")
        return 1

    check("端点返回 200", code == 200, f"HTTP {code}")
    cd = hget(heads, "Content-Disposition")
    check("带附件头 Content-Disposition", "attachment" in cd, cd[:90])
    check("文件名含 UTF-8 中文名（RFC5987）", "filename*=UTF-8''" in cd)
    ct = hget(heads, "Content-Type")
    check("Content-Type 为 application/zip", "application/zip" in ct, ct)

    try:
        zf = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile as exc:
        check("是合法 zip", False, str(exc))
        return 1
    check("是合法 zip", True, f"{len(body)} 字节")

    names = zf.namelist()

    # ② 清单层：134 条一条不少
    rows = json.loads(zf.read("entries.json").decode("utf-8"))
    check("entries.json 条目数 = 134", len(rows) == 134, f"{len(rows)} 条")
    for fn in ("README.md", "entries.csv", "entries.md"):
        check(f"清单文件 {fn} 存在", fn in names)
    # BOM 要看原始字节：decode("utf-8-sig") 会把 BOM 吃掉，那样永远验不出来
    csv_raw = zf.read("entries.csv")
    check("entries.csv 带 BOM（Excel 中文不乱码）", csv_raw.startswith(b"\xef\xbb\xbf"))
    csv_text = csv_raw.decode("utf-8-sig")
    check("entries.csv 行数 = 135（表头+134）",
          len([l for l in csv_text.splitlines() if l.strip()]) == 135,
          f"{len([l for l in csv_text.splitlines() if l.strip()])} 行")

    # ③ 文件层：文档不漏 + 插图齐全
    docs = {n.split("/")[1] for n in names if n.startswith("documents/")}
    missing = EXPECTED_DOCS - docs
    check("13 份文档全部打包（不漏）", not missing, f"缺 {sorted(missing)}" if missing else f"{len(docs)} 份")
    figs = [n for n in names if "/figures/" in n]
    check("插图 174 张全部打包", len(figs) == 174, f"{len(figs)} 张")
    combined = [n for n in names if "/combined/" in n]
    check("合成图文稿已打包", len(combined) > 0, f"{len(combined)} 个文件")
    check("正文 content.md 已打包",
          sum(1 for n in names if n.endswith("/content.md")) >= 12,
          f"{sum(1 for n in names if n.endswith('/content.md'))} 份")

    # ④ 路径安全：zip 内不应出现绝对路径或 ..
    bad = [n for n in names if n.startswith("/") or ".." in n.split("/")]
    check("zip 内无路径穿越（无绝对路径/..）", not bad, str(bad[:3]))

    # ⑤ 诚实边界写进 README
    readme = zf.read("README.md").decode("utf-8")
    check("README 写明「条目数≠文件数」", "不等于" in readme or "条目数" in readme)
    check("README 写明不是客户原件", "原件" in readme)
    check("README 写明插图受上限截断", "截断" in readme or "最多" in readme)

    # ⑥ 负路径
    try:
        code2, _, _ = get(f"{BASE}/api/kb/documents/export?owner=")
        check("空 owner 返回 4xx", 400 <= code2 < 500, f"HTTP {code2}")
    except urllib.error.HTTPError as exc:
        check("空 owner 返回 4xx", 400 <= exc.code < 500, f"HTTP {exc.code}")
    try:
        q = urllib.parse.urlencode({"owner": "不存在的产品XYZ"})
        code3, _, _ = get(f"{BASE}/api/kb/documents/export?{q}")
        check("不存在归属返回 404", code3 == 404, f"HTTP {code3}")
    except urllib.error.HTTPError as exc:
        check("不存在归属返回 404", exc.code == 404, f"HTTP {exc.code}")

    ok = sum(1 for _, c, _ in results if c)
    print("\n" + "=" * 60)
    print(f"知识库整包导出: {ok}/{len(results)} passed")
    print("=" * 60)
    for n, c, d in results:
        if not c:
            print(f"  FAILED: {n} -> {d}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
