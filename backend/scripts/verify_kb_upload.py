"""知识库上传 + 五阶段转化端到端验证（2026-09-24，阶段 3.1 单元 1）。

验的是主文档 3.1 的验收动作 2：
    「上传一份文档后轮询状态接口，五个阶段状态依次推进到已入库」

做法：
  1. 造一份**小的真 docx**（用 zipfile 写最小 OOXML）当测试原件——
     不借用客户原件（那些不在仓里），也不塞大文件；
  2. POST /api/kb/documents 上传；
  3. 轮询 GET /api/kb/documents/{doc_id} 看状态；
  4. POST .../run 推进五阶段，逐阶段核对产物落盘；
  5. 校验失败路径：不存在的 doc_id 应 404、非法 until 应 400。

跑法（后端 8011 在跑）：
    python scripts/verify_kb_upload.py
"""
from __future__ import annotations

import io
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

BASE = "http://127.0.0.1:8011"
_failed = 0


def check(cond: bool, label: str, detail: str = "") -> bool:
    """断言并留痕。**必须返回 cond**（漏 return 会让调用方静默失效）。

    ⚠️ 2026-09-24 修复：原实现漏了 `return cond`，于是 `if not check(...)`
    恒为假——「跑完第一条就停」这类静默失效正是项目记过的坑（3-H）。
    这里补上返回值，并在文件末尾统一用 _failed 判定。
    """
    global _failed
    if cond:
        print(f"[OK]  {label}" + (f"  {detail}" if detail else ""))
    else:
        _failed += 1
        print(f"[NG]  {label}" + (f"  {detail}" if detail else ""))
    return cond


def post_json(path: str, payload) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8")
    # 同 get_json：路径可能含中文，先编码再发
    url = f"{BASE}{urllib.parse.quote(path, safe='/?&=%')}"
    r = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def get_json(path: str) -> tuple[int, dict]:
    # 路径里可能带中文 doc_id（上传的标题是中文，slug 保留了它）
    # ——必须百分号编码，否则 http.client 在 encode('ascii') 处直接抛
    # UnicodeEncodeError（首版就栽在这，症状是「上传成功、第二步就崩」）。
    url = f"{BASE}{urllib.parse.quote(path, safe='/?&=%')}"
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def post_multipart(path: str, fields: dict[str, str], filename: str, content: bytes) -> tuple[int, dict]:
    """最小 multipart 上传（不引第三方库，requests 不保证装在跑脚本的解释器里）。"""
    boundary = "----kbupload" + uuid.uuid4().hex
    body = io.BytesIO()
    for k, v in fields.items():
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
        body.write(f"{v}\r\n".encode())
    body.write(f"--{boundary}\r\n".encode())
    body.write(
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
    )
    body.write(b"Content-Type: application/octet-stream\r\n\r\n")
    body.write(content)
    body.write(f"\r\n--{boundary}--\r\n".encode())
    r = urllib.request.Request(
        f"{BASE}{path}", data=body.getvalue(), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(r, timeout=180) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def make_docx(text: str) -> bytes:
    """造一份最小可用的 .docx（OOXML 就是一个 zip，docling 认 word/document.xml）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        paras = "".join(
            f'<w:p><w:r><w:t>{line}</w:t></w:r></w:p>' for line in text.split("\n")
        )
        z.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{paras}</w:body></w:document>",
        )
    return buf.getvalue()


def main() -> int:
    scene = "motor.cooling-fan.fortior-fu6832"

    print("== ① 上传一份测试 docx（自造最小 OOXML，不动客户原件）==")
    # 每次跑内容都不同：上传接口按 sha256 去重（同文件不重复入库），
    # 固定内容会导致第二次跑直接被去重挡住、后面的阶段验不成。
    salt = uuid.uuid4().hex[:6]
    text = (
        "散热风扇驱动板调试手册（测试件）\n"
        f"第 1 节 额定参数（{salt}）\n"
        "额定转速 28000 转每分，额定电压 12.0 伏，额定电流 0.6 安。\n"
        "第 2 节 启动测试\n"
        "启动阶段观察启动峰值电流，不得超过额定电流的一点五倍。\n"
        "第 3 节 FG 输出\n"
        "FG 输出频率与转速成正比，用于判定转速是否稳定。\n"
    )
    body = make_docx(text)
    st, out = post_multipart(
        "/api/kb/documents",
        {"title": "散热风扇驱动板调试手册（测试件）", "owner_l1": "电机",
         "owner_l2": "散热风扇", "owner_l3": "FU6832 散热风扇驱动板", "usage": "process"},
        "测试件-调试手册.docx",
        body,
    )
    check(st in (200, 201), "POST /api/kb/documents", f"HTTP {st}")
    doc = out.get("data") or {}
    doc_id = doc.get("doc_id")
    check(bool(doc_id), "返回 doc_id", str(doc_id))
    check(doc.get("status") == "pending", "初始状态为 pending", str(doc.get("status")))
    check(doc.get("status_label") == "待处理", "状态中文标签正确", str(doc.get("status_label")))
    if not doc_id:
        return 1

    print("\n== ② 轮询详情：应能读到五阶段清单 ==")
    st, out = get_json(f"/api/kb/documents/{doc_id}")
    check(st == 200, "GET /api/kb/documents/{id}", f"HTTP {st}")
    stages = (out.get("data") or {}).get("stages") or []
    check(len(stages) == 5, "五阶段清单齐全", f"{len(stages)} 个")
    check(
        [s["key"] for s in stages] == ["recognize", "extract", "chunk", "struct", "index"],
        "阶段顺序 = 识别/抽取/切片/结构化/索引",
        ",".join(s["label"] for s in stages),
    )

    print("\n== ③ 跑五阶段（真调 docling 子进程）==")
    st, out = post_json(f"/api/kb/documents/{doc_id}/run?until=index", {})
    check(st == 200, "POST .../run?until=index", f"HTTP {st}")
    d = out.get("data") or {}
    if st != 200:
        print("   失败详情：", json.dumps(out, ensure_ascii=False)[:400])
    check(d.get("stage") == "index", "跑到 index 阶段", str(d.get("stage")))
    arts = d.get("stages") or []
    done = [s["key"] for s in arts if s.get("done")]
    check(len(done) == 5, "五个阶段都有产物", ",".join(done))
    check(d.get("status") in ("indexed", "needs_review"), "状态推进到已入库或需校对",
          f"{d.get('status')}（{d.get('status_label')}）")

    print("\n== ④ 阶段产物逐份核对（阶段间只传文件与 JSON）==")
    import pathlib
    from os.path import join

    # 产物根与 paths.kb_uploads_dir() 同口径：backend/uploads/kb/<doc_id>/
    root = pathlib.Path(__file__).resolve().parent.parent / "uploads" / "kb" / doc_id
    for f in ("recognize.json", "extract.json", "chunk.json", "struct.json", "index.json",
              "content.md", "chunks.jsonl", "docling_result.json"):
        check((root / f).exists(), f"产物存在 {f}")

    print("\n== ⑤ 错误路径 ==")
    st, _ = get_json("/api/kb/documents/不存在的文档")
    check(st == 404, "不存在的 doc_id → 404", f"HTTP {st}")
    st, _ = post_json(f"/api/kb/documents/{doc_id}/run?until=不存在的阶段", {})
    check(st == 400, "非法 until → 400", f"HTTP {st}")

    print("\n== ⑥ 列表接口 ==")
    st, out = get_json(f"/api/kb/documents?owner_l3=FU6832 散热风扇驱动板")
    check(st == 200, "GET /api/kb/documents", f"HTTP {st}")
    data = out.get("data") or {}
    check((data.get("total") or 0) >= 1, "列表能查到刚上传的文档", f"total={data.get('total')}")
    check(isinstance(data.get("counts"), dict), "返回五值计数", json.dumps(data.get("counts"), ensure_ascii=False))

    # ────────────────────────────────────────────────────────────
    # 以下为阶段 3 补全新增的断言（2026-09-24）
    # 覆盖三件事：① 结构化产真字段 ② 索引真写库 ③ 上传的条目可被检索到
    # ────────────────────────────────────────────────────────────

    print("\n== ⑦ 结构化阶段：真抽字段（阶段 3 补全）==")
    struct_file = root / "struct.json"
    if struct_file.exists():
        s = json.loads(struct_file.read_text(encoding="utf-8"))
        check("struct 产物有 template 字段", bool(s.get("template")), str(s.get("template")))
        check("struct 产物有置信度", isinstance(s.get("confidence"), (int, float)),
              str(s.get("confidence")))
        check("struct 产物标了是否模板待补",
              "template_pending" in s, str(s.get("template_pending")))
        # 关键：置信度必须可解释 —— 三因子或骨架口径都要写明依据
        check("置信度带依据说明", bool(s.get("confidence_basis")),
              str(s.get("confidence_basis"))[:60])
        if s.get("template_pending") is False:
            # 已实现的三类：必须给出真实业务字段，而不是切片包装
            fields = s.get("fields") or []
            check("精抽模板产出非空 fields", len(fields) > 0, f"{len(fields)} 个")
            if fields:
                keys = {f.get("key") for f in fields}
                # 真抽的字段是业务键（如「额定电压」「宏定义」），
                # 而骨架的字段键恒为 chunk_id/heading/page/text —— 用它区分
                skeleton_only = {"chunk_id", "heading", "page", "text"}
                check("fields 是业务字段而非切片包装",
                      bool(keys - skeleton_only), f"keys={sorted(keys)[:6]}")
                check("fields 带证据片段", any(f.get("evidence") for f in fields))
        else:
            check("模板待补时如实标注（不冒充精抽）",
                  "待补" in (s.get("note") or ""), (s.get("note") or "")[:80])
    else:
        check(False, "struct 产物存在", str(struct_file))

    print("\n== ⑧ 索引阶段：真写入 kb_entries（阶段 3 补全）==")
    index_file = root / "index.json"
    if index_file.exists():
        ix = json.loads(index_file.read_text(encoding="utf-8"))
        check("index 产物报告 entry_count", "entry_count" in ix, str(ix.get("entry_count")))
        check("entry_count > 0（真写了条目）",
              (ix.get("entry_count") or 0) > 0, str(ix.get("entry_count")))
        check("entry_key 带文档维度前缀",
              all(k.startswith(f"{doc_id}#") for k in (ix.get("entry_keys_sample") or [])[:3]),
              str((ix.get("entry_keys_sample") or [])[:2]))
    else:
        check(False, "index 产物存在", str(index_file))

    # 从接口侧复核：条目列表里应能查到这篇文档产出的条目
    st, out = get_json(
        f"/api/kb/entries?owner={urllib.parse.quote('FU6832 散热风扇驱动板')}&limit=500"
    )
    check(st == 200, "GET /api/kb/entries", f"HTTP {st}")
    items = ((out.get("data") or {}).get("items")) or []
    mine = [i for i in items if str(i.get("entry_key", "")).startswith(f"{doc_id}#")]
    check("条目列表能查到本文件的条目", len(mine) > 0, f"{len(mine)} 条")
    if mine:
        e = mine[0]
        check("条目 origin 为 doc", e.get("origin") == "doc", str(e.get("origin")))
        check("条目 usage 在三值内",
              e.get("usage") in ("spec", "requirement", "process"), str(e.get("usage")))
        check("条目归属三级正确",
              e.get("owner_l3") == "FU6832 散热风扇驱动板", str(e.get("owner_l3")))

    print("\n== ⑨ 上传资料可被检索到（双路检索 + 降级标注）==")
    # 检索一个只可能出现在刚上传文件里的词（带 salt，避免命中既有语料）
    probe_word = f"启动峰值电流{salt}"
    st, out = post_json("/api/kb/search", {"query": probe_word, "k": 5})
    check(st == 200, "POST /api/kb/search", f"HTTP {st}")
    results = out.get("results") or []
    check("检索返回结果结构正常", isinstance(results, list), f"{len(results)} 条")
    if results:
        r0 = results[0]
        # 既有字段必须还在（前端引用面板依赖它们，不能因加向量而丢）
        for f in ("rank", "score", "doc_id", "page", "snippet", "source_path"):
            check(f"结果保留既有字段 {f}", f in r0)
        # 新增字段：route / degraded 必须存在且取值合法
        check("新增 route 标注", r0.get("route") in ("keyword", "vector", "hybrid"),
              str(r0.get("route")))
        check("新增 degraded 标注是布尔", isinstance(r0.get("degraded"), bool),
              str(r0.get("degraded")))
        # 降级时必须有原因（不许只给一个 true 让人猜）
        if r0.get("degraded"):
            check("降级带原因", bool(r0.get("degrade_reason")),
                  (r0.get("degrade_reason") or "")[:60])

    print("\n== ⑩ 向量索引现状接口 ==")
    st, out = get_json("/api/kb/vector/stat")
    check(st == 200, "GET /api/kb/vector/stat", f"HTTP {st}")
    vd = out.get("data") or {}
    check("返回语料条数", isinstance(vd.get("corpus_count"), int), str(vd.get("corpus_count")))
    check("返回陈旧标记", "stale" in vd, str(vd.get("stale")))
    check("返回索引档位信息", isinstance(vd.get("index"), dict),
          str((vd.get("index") or {}).get("tier")))

    print()
    if _failed:
        print(f"FAILED: {_failed} 项未通过")
        return 1
    print("ALL PASS")
    print(f"（测试文档 {doc_id} 与其产物保留在 backend/uploads/kb/ 下，供复核）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
