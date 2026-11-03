"""向量化 worker（供后端以子进程调用）。

职责：把一批文本编码成向量，输出 JSON。**建索引期与查询期共用这一个入口**，
保证两侧用的是同一个模型、同一套归一化口径——否则查询向量与库里的向量
不在同一空间，检索结果会「看起来有分但全是噪声」。

两级编码器（**这是本文件最重要的设计**）
---------------------------------------
交付形态是**单机 Windows 离线版**。实测本机 HuggingFace 不可达
（`WinError 10054`，且 `hf-mirror.com` 同样不通），所以**不能把向量一路
建立在「运行时联网下模型」之上**——那会让整个双路检索在客户现场直接失效。

因此这里实现两级，且**把实际用的是哪一级如实写进产物**：

  tier = "transformer"
      真的 transformers 模型（`MOTORDEBUG_EMBED_MODEL` 指定且本地能加载）。
      精度最好，但需要模型已经在本机（离线现场应预置好模型目录）。

  tier = "hashing"
      本地确定性哈希编码回退（**无依赖、无网络、纯 CPU**）。
      做法：字 unigram/bigram + 词元哈希到固定维度、按 TF 加权、L2 归一化。
      这是经典的 hashing trick / random-projection 思路，**不是语义模型**，
      但它能提供真实的「字面相近即向量相近」能力，对
      「宏名、参数名、术语」这类工业语料命中效果可用。

⚠️ 为什么不一味失败、也不假装是语义模型：
  - 一味失败：双路检索在离线现场完全不可用，等于这项功能白做。
  - 假装语义：把哈希向量当语义向量，检索质量的真实边界就没人知道了。
  所以**降级要用，但必须标出来**——`tier` 字段一路透传到检索结果的
  `degraded` 标记上，人和模型都能看到「这一路是字面回退」。

用法：
    <venv>/python.exe _embed_worker.py --texts-file <文本JSON> --out <向量JSON>
    <venv>/python.exe _embed_worker.py --probe            # 探测可用档位

退出码：0 成功；2 参数错；3 表示**连回退都不可用**（正常不该出现）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

# ⚠️ Windows 上 stdout 默认 GBK，而本脚本的 --probe 输出含中文说明；
# 父进程按 UTF-8 读会乱码。统一强制 UTF-8（与后端读取口径对齐）。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

# 与 _vector_worker.py / kb_embed_service.py 共用的模型名。
# 留空表示「不尝试 transformer，直接用 hashing 回退」——离线现场的默认姿态。
DEFAULT_MODEL = ""

# hashing 回退的向量维度。384 与常见小模型同量级：
# 换档重建索引时维度接近，便于比对；也让距离分布落在合理区间。
HASH_DIM = 384

EXIT_MODEL_UNAVAILABLE = 3

_RE_ASCII = re.compile(r"[a-z0-9_]+")
_RE_CJK = re.compile(r"[\u4e00-\u9fff]")

# 与 kb_search.py 的 tokenize 同口径（中文 unigram+bigram，ASCII 词元保留下划线）。
# ⚠️ 刻意保持一致：两路检索若切词口径不同，融合排序的分数量纲会打架。
_STOP = {"怎么", "如何", "什么", "的", "了", "是", "在", "和", "与", "选", "配置"}


def tokenize(text: str) -> list[str]:
    """与 kb_search.tokenize 一致：ASCII 词元（含下划线拆分）+ 中文 unigram/bigram。"""
    low = (text or "").lower()
    toks = _RE_ASCII.findall(low)
    toks += [p for t in toks if "_" in t for p in t.split("_") if p]
    cjk = _RE_CJK.findall(text or "")
    toks += cjk
    toks += ["".join(pair) for pair in zip(cjk, cjk[1:])]
    return toks


def _hash_index(token: str, dim: int) -> int:
    """token → 维度下标。用 md5 而非内置 hash：内置 hash 有进程随机盐，
    跨进程（建索引的进程 vs 查询的进程）会算出不同下标 → 向量空间错位。
    这是一个**极易踩且症状隐蔽**的坑，所以在这里写明原因。
    """
    h = hashlib.md5(token.encode("utf-8")).digest()
    return int.from_bytes(h[:4], "big") % dim


def embed_hashing(texts: list[str], dim: int = HASH_DIM) -> list[list[float]]:
    """本地确定性哈希编码。返回 L2 归一化后的向量。

    加权：TF 的平方根（次线性，避免长文档被高频词主导）+ 符号哈希
    （同一 token 固定同号，减少哈希碰撞造成的系统性偏置）。
    """
    import math

    out: list[list[float]] = []
    for t in texts:
        vec = [0.0] * dim
        counts: dict[str, int] = {}
        for tok in tokenize(t or ""):
            if tok in _STOP or not tok.strip():
                continue
            counts[tok] = counts.get(tok, 0) + 1
        for tok, c in counts.items():
            idx = _hash_index(tok, dim)
            # 符号位取另一段哈希，与 idx 独立
            sign = 1.0 if hashlib.md5(("s" + tok).encode("utf-8")).digest()[0] & 1 else -1.0
            vec[idx] += sign * math.sqrt(c)
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        out.append([v / norm for v in vec])
    return out


def _load_transformer(model_name: str):
    """加载 transformers 模型。任何「环境不具备」的情况都返回 None（不抛出）。"""
    if not model_name:
        return None
    try:
        import torch  # noqa: F401
        from transformers import AutoModel, AutoTokenizer
    except Exception:
        return None
    try:
        tok = AutoTokenizer.from_pretrained(model_name, local_files_only=True)
        mdl = AutoModel.from_pretrained(model_name, local_files_only=True)
        mdl.eval()
        return tok, mdl
    except Exception:
        # 模型未下载 / 名字不对 / 无网络，都归到这里。
        # **刻意用 local_files_only=True**：离线现场不该在请求期偷偷联网，
        # 那会让「第一次检索」变成一次不可预期的长阻塞甚至失败。
        return None


def embed_transformer(texts: list[str], model_name: str) -> list[list[float]] | None:
    """mean-pooling 句向量。返回 None 表示该档不可用。"""
    loaded = _load_transformer(model_name)
    if loaded is None:
        return None
    tok, mdl = loaded
    import torch

    out: list[list[float]] = []
    BATCH = 32  # CPU 上的稳妥档；一次全塞进去在长文档上会爆内存
    for i in range(0, len(texts), BATCH):
        batch = [t or " " for t in texts[i:i + BATCH]]
        enc = tok(batch, padding=True, truncation=True, max_length=512, return_tensors="pt")
        with torch.no_grad():
            res = mdl(**enc)
        # mean pooling：按 attention_mask 加权，忽略 padding
        mask = enc["attention_mask"].unsqueeze(-1).float()
        summed = (res.last_hidden_state.float() * mask).sum(dim=1)
        counts = mask.sum(dim=1).clamp(min=1e-9)
        vecs = torch.nn.functional.normalize(summed / counts, p=2, dim=1)
        out.extend(v.tolist() for v in vecs)
    return out


def embed(texts: list[str], model_name: str) -> tuple[list[list[float]], str]:
    """按档位编码。返回 (向量, tier)。tier ∈ {"transformer","hashing"}。

    先试 transformer；不可用就落到 hashing。**绝不抛异常**——
    调用方拿到的 tier 就是「这次用的是什么」的如实答案。
    """
    if model_name:
        v = embed_transformer(texts, model_name)
        if v is not None:
            return v, "transformer"
    return embed_hashing(texts), "hashing"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--texts-file", help="JSON 文件，内容为字符串数组")
    ap.add_argument("--out", help="输出 JSON（向量数组）")
    ap.add_argument("--model", default=os.environ.get("MOTORDEBUG_EMBED_MODEL", DEFAULT_MODEL))
    ap.add_argument("--probe", action="store_true", help="只探测可用档位")
    args = ap.parse_args()

    if args.probe:
        tier = "transformer" if _load_transformer(args.model) else "hashing"
        print(json.dumps({
            "model": args.model,
            "tier": tier,
            "dim": HASH_DIM,
            # 探测结果里必须写清 transformer 为什么没用上，否则现场排查要猜
            "transformer_available": tier == "transformer",
            "note": (
                "transformer 模型可用（local_files_only）"
                if tier == "transformer"
                else "transformer 模型不可用（未预置或依赖缺失），将使用本地 hashing 回退；"
                     "如需语义向量，请把模型预置到本机并设 MOTORDEBUG_EMBED_MODEL"
            ),
        }, ensure_ascii=False))
        return 0

    if not args.texts_file or not args.out:
        print(json.dumps({"error": "需要 --texts-file 与 --out"}, ensure_ascii=False))
        return 2

    try:
        texts = json.loads(Path(args.texts_file).read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": f"读 texts-file 失败：{e}"}, ensure_ascii=False))
        return 2
    if not isinstance(texts, list):
        print(json.dumps({"error": "texts-file 内容必须是数组"}, ensure_ascii=False))
        return 2

    vecs, tier = embed([str(t) for t in texts], args.model)
    Path(args.out).write_text(
        json.dumps({
            "model": args.model,
            "tier": tier,
            "dim": len(vecs[0]) if vecs else 0,
            "vectors": vecs,
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[ok] embedded {len(vecs)} texts tier={tier} "
          f"dim={len(vecs[0]) if vecs else 0}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
