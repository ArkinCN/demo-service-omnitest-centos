"""端到端验证：模拟前端的路径拼接，确认改造后波形/工作流仍可加载。

为什么需要它：`file_path` 改成 `./assets/...` 后，**光看字符串对不够**——
必须按前端的真实算法拼一遍 URL，再实际发请求，才能证明「波形加载没断」。

对齐的消费逻辑（两处，见源码）：
  features/waveforms/index.ts:150
      const rel = d.file_path.split('/assets/')[1]
      url = `${pack.base}assets/${rel}`
  features/scene/workflows.ts:84
      assetPath = file_path.split('/assets/')[1] ? `assets/${...}` : ''

用法：
    python scripts/e2e_verify.py            # 默认打前端 5173
    python scripts/e2e_verify.py 8011       # 换端口
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCENES = REPO / "c" / "web" / "public" / "scenes"


def head_ok(url: str) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200, str(r.status)
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    port = sys.argv[1] if len(sys.argv) > 1 else "5173"
    base = f"http://localhost:{port}"
    # 前端 pack.base 的形态：`/scenes/<sceneId>/`
    problems: list[str] = []
    checked = 0

    print(f"前端基址：{base}")
    print("=" * 72)

    for scene_dir in sorted(p for p in SCENES.iterdir() if p.is_dir()):
        scene_id = scene_dir.name
        pack_base = f"/scenes/{scene_id}/"

        ds = scene_dir / "datasets.json"
        if not ds.is_file():
            continue
        data = json.loads(ds.read_text(encoding="utf-8"))

        print(f"\n场景包：{scene_id}")
        for d in data.get("datasets", []):
            mode = d.get("mode", "")
            fp = d.get("file_path", "")
            did = d.get("id", "?")

            if mode not in ("copied_into_pack", "generated_into_pack"):
                print(f"  [{did}] mode={mode} → 前端跳过，不加载（已脱敏为 {fp[:40]}）")
                continue

            # 复刻前端逻辑
            rel = fp.split("/assets/")[1]
            if not rel:
                problems.append(f"{scene_id}/{did}: split('/assets/') 取不到相对路径 → 波形加载会断")
                print(f"  [{did}] ✗ split 失败：{fp}")
                continue

            url = f"{base}{pack_base}assets/{rel}"
            ok, note = head_ok(url)
            checked += 1
            mark = "OK " if ok else "FAIL"
            print(f"  [{did}] {mark} {rel}  ({note})")
            if not ok:
                problems.append(f"{scene_id}/{did}: 取不到 {url}（{note}）")

        # workflows：包内的要能取到，包外的应为脱敏标记
        wf = scene_dir / "workflows.json"
        if wf.is_file():
            wdata = json.loads(wf.read_text(encoding="utf-8"))
            inpack = outpack = 0
            for w in wdata.get("workflows", []):
                fp = w.get("file_path", "")
                if not fp:
                    continue
                if fp.startswith("[源] "):
                    outpack += 1
                    continue
                rel = fp.split("/assets/")[1]
                if not rel:
                    problems.append(f"{scene_id}/{w.get('id')}: workflows.file_path 形态异常 {fp!r}")
                    continue
                ok, note = head_ok(f"{base}{pack_base}assets/{rel}")
                checked += 1
                inpack += 1
                if not ok:
                    problems.append(f"{scene_id}/{w.get('id')}: 取不到工作流 {rel}（{note}）")
            print(f"  工作流：包内 {inpack} 条（已逐一请求）、包外登记 {outpack} 条（前端容错跳过）")

    print("\n" + "=" * 72)
    print(f"共实际请求 {checked} 个资源")
    if problems:
        print(f"发现 {len(problems)} 个问题：")
        for x in problems:
            print("  -", x)
        return 1
    print("端到端资源可达性验证通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
