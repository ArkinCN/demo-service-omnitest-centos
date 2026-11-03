"""
AI 绘图服务（从 FastGPT 插件迁移）

两种模式，直连上游 timebackward.com，**不再上传 MinIO**——生成的图片以 base64
经 SSE 推给前端，由前端 Tauri 落盘到用户电脑本地：
- 模式一 gemini：gemini-3.1-flash-image-preview，鉴权 URL ?key=，返回 inlineData base64。
- 模式二 gpt   ：gpt-image-2，文生图 /images/generations、图生图 /images/edits，
                 鉴权 Bearer，返回 data[].b64_json（或 url 则下载转 b64）。

`run_image_gen` 是 async generator，逐步 yield 过程事件（dict），由 SSE 端点转发：
  {"type": "progress", "text": "..."}                  # 进度/日志
  {"type": "image", "index": N, "total": M,
   "b64": "...", "ext": "png"}                          # 单张图片（base64，不含 data: 前缀）
  {"type": "done", "generated": N, "expected": M}
  {"type": "error", "message": "..."}
"""
import asyncio
import base64
import re
from typing import AsyncGenerator, Optional

import httpx

from app.core.config import settings
from app.core.logger import logger


# ── 工具：参考图（data URL 或 http URL）→ (mime, base64) ──

_DATA_URL_RE = re.compile(r"^data:(?P<mime>[^;]+);base64,(?P<data>.+)$", re.S)


def _detect_mime(buf: bytes) -> str:
    if buf[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if buf[:4] == b"\x89PNG":
        return "image/png"
    if buf[:3] == b"GIF":
        return "image/gif"
    if buf[:4] == b"RIFF":
        return "image/webp"
    return "image/png"


async def _ref_to_mime_b64(client: httpx.AsyncClient, url: str) -> tuple[str, str]:
    """参考图统一转 (mime_type, base64_no_prefix)。兼容 data URL 与 http(s) URL。"""
    m = _DATA_URL_RE.match(url)
    if m:
        return m.group("mime"), m.group("data")
    resp = await client.get(url, timeout=60.0)
    resp.raise_for_status()
    buf = resp.content
    return _detect_mime(buf), base64.b64encode(buf).decode()


def _ext_from_mime(mime: str) -> str:
    return (mime.split("/", 1)[-1] or "png").lower().replace("jpeg", "jpg")


def _friendly_error(e: Exception) -> str:
    """把上游异常转成给用户看的简短中文原因。"""
    import httpx as _httpx
    if isinstance(e, _httpx.HTTPStatusError):
        code = e.response.status_code
        if code == 429:
            return "上游绘图服务繁忙（限流），请稍后重试"
        if code in (401, 403):
            return "绘图服务鉴权失败"
        if code >= 500:
            return f"上游绘图服务错误（{code}），请稍后重试"
        return f"绘图请求失败（{code}）"
    if isinstance(e, (_httpx.ConnectError, _httpx.ConnectTimeout)):
        return "无法连接绘图服务，请检查网络"
    if isinstance(e, _httpx.TimeoutException):
        return "绘图超时，请稍后重试"
    msg = str(e)
    if "getaddrinfo failed" in msg or "Name or service" in msg:
        return "无法解析绘图服务地址（网络/DNS 问题）"
    return f"绘图失败：{msg[:80]}"


# ── 模式一：Gemini ──

async def _gemini_one(
    client: httpx.AsyncClient, prompt: str, aspect_ratio: str, image_size: str,
    api_key: str, ref_parts: list[dict],
) -> Optional[tuple[str, str]]:
    """生成单张 Gemini 图片，返回 (b64, ext) 或 None。"""
    url = (
        f"{settings.GEMINI_IMAGE_BASE_URL.rstrip('/')}"
        f"/models/{settings.GEMINI_IMAGE_MODEL}:generateContent?key={api_key}"
    )
    parts = list(ref_parts) + [{"text": f"{prompt}\n\n仅生成一张图片"}]
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": aspect_ratio, "imageSize": image_size},
        },
    }
    resp = await client.post(
        url, json=payload, headers={"Content-Type": "application/json"},
        timeout=settings.GEMINI_IMAGE_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    for cand in data.get("candidates") or []:
        for part in (cand.get("content") or {}).get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                ext = _ext_from_mime(inline.get("mimeType") or inline.get("mime_type") or "image/png")
                return inline["data"], ext
    return None


async def _run_gemini(
    client: httpx.AsyncClient, prompt: str, image_urls: list[str], params: dict,
) -> AsyncGenerator[dict, None]:
    aspect_ratio = params.get("aspectRatio") or params.get("image_size") or "16:9"
    # 前端 image_size 传的是比例（1:1 等）时当 aspectRatio；分辨率单独用 imageResolution
    image_size = params.get("imageResolution") or params.get("resolution") or "2K"
    route = params.get("route") or "normal"
    max_images = int(params.get("maxImages") or 1)
    api_key = settings.GEMINI_IMAGE_KEY_FAST if route == "fast" else settings.GEMINI_IMAGE_KEY_NORMAL

    ref_parts: list[dict] = []
    if image_urls:
        yield {"type": "progress", "text": f"转换 {len(image_urls)} 张参考图片…"}
        for u in image_urls:
            mime, b64 = await _ref_to_mime_b64(client, u)
            ref_parts.append({"inlineData": {"mimeType": mime, "data": b64}})

    yield {"type": "progress", "text": f"开始生成 {max_images} 张图片…"}
    tasks = [
        _gemini_one(client, prompt, aspect_ratio, image_size, api_key, ref_parts)
        for _ in range(max_images)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    idx = 0
    errors: list[str] = []
    for r in results:
        if isinstance(r, Exception):
            logger.error(f"gemini image gen failed: {r}")
            errors.append(_friendly_error(r))
            continue
        if r is None:
            errors.append("绘图服务未返回图片")
            continue
        idx += 1
        b64, ext = r
        yield {"type": "image", "index": idx, "total": max_images, "b64": b64, "ext": ext}
    yield {"type": "done", "generated": idx, "expected": max_images,
           "failed": len(errors), "errors": errors[:3]}


# ── 模式二：GPT Image 2 ──

async def _gpt_generate_one(
    client: httpx.AsyncClient, prompt: str, size: str, quality: str, api_key: str,
) -> Optional[tuple[str, str]]:
    url = f"{settings.GPT_IMAGE_BASE_URL.rstrip('/')}/images/generations"
    payload = {"model": settings.GPT_IMAGE_MODEL, "prompt": prompt, "n": 1, "size": size, "quality": quality}
    resp = await client.post(
        url, json=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        timeout=settings.GPT_IMAGE_TIMEOUT,
    )
    resp.raise_for_status()
    return await _gpt_extract(client, resp.json())


async def _gpt_edit_one(
    client: httpx.AsyncClient, prompt: str, size: str, quality: str, api_key: str,
    ref_mime: str, ref_b64: str,
) -> Optional[tuple[str, str]]:
    url = f"{settings.GPT_IMAGE_BASE_URL.rstrip('/')}/images/edits"
    ext = _ext_from_mime(ref_mime)
    files = {"image": (f"ref.{ext}", base64.b64decode(ref_b64), ref_mime)}
    form = {"prompt": prompt, "model": settings.GPT_IMAGE_MODEL, "n": "1", "size": size, "quality": quality}
    resp = await client.post(
        url, data=form, files=files,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=settings.GPT_IMAGE_TIMEOUT,
    )
    resp.raise_for_status()
    return await _gpt_extract(client, resp.json())


async def _gpt_extract(client: httpx.AsyncClient, data: dict) -> Optional[tuple[str, str]]:
    """从 GPT Image 2 响应取第一张图，统一返回 (b64, 'png')。"""
    for item in data.get("data") or []:
        if item.get("b64_json"):
            return item["b64_json"], "png"
        if item.get("url"):
            resp = await client.get(item["url"], timeout=60.0)
            if resp.is_success:
                return base64.b64encode(resp.content).decode(), "png"
    return None


async def _run_gpt(
    client: httpx.AsyncClient, prompt: str, image_urls: list[str], params: dict,
) -> AsyncGenerator[dict, None]:
    size = params.get("size") or params.get("image_size") or "2048x1152"
    quality = params.get("quality") or "auto"
    max_images = int(params.get("maxImages") or 1)
    api_key = settings.GPT_IMAGE_KEY

    if image_urls:
        yield {"type": "progress", "text": f"下载 {len(image_urls)} 张参考图片…"}
        refs = [await _ref_to_mime_b64(client, u) for u in image_urls]
        yield {"type": "progress", "text": "开始编辑生成…"}
        # 每张参考图 × maxImages
        tasks = [
            _gpt_edit_one(client, prompt, size, quality, api_key, mime, b64)
            for (mime, b64) in refs
            for _ in range(max_images)
        ]
        total = len(refs) * max_images
    else:
        yield {"type": "progress", "text": f"开始生成 {max_images} 张图片…"}
        tasks = [_gpt_generate_one(client, prompt, size, quality, api_key) for _ in range(max_images)]
        total = max_images

    results = await asyncio.gather(*tasks, return_exceptions=True)
    idx = 0
    errors: list[str] = []
    for r in results:
        if isinstance(r, Exception):
            logger.error(f"gpt image gen failed: {r}")
            errors.append(_friendly_error(r))
            continue
        if r is None:
            errors.append("绘图服务未返回图片")
            continue
        idx += 1
        b64, ext = r
        yield {"type": "image", "index": idx, "total": total, "b64": b64, "ext": ext}
    yield {"type": "done", "generated": idx, "expected": total,
           "failed": len(errors), "errors": errors[:3]}


# ── 入口 ──

async def run_image_gen(
    client: httpx.AsyncClient,
    mode: str,
    prompt: str,
    image_urls: Optional[list[str]] = None,
    params: Optional[dict] = None,
) -> AsyncGenerator[dict, None]:
    """运行一次绘图任务，逐步 yield 过程事件。mode: 'gemini' | 'gpt'。"""
    prompt = (prompt or "").strip()
    if not prompt:
        yield {"type": "error", "message": "提示词不能为空"}
        return
    image_urls = image_urls or []
    params = params or {}

    try:
        if mode == "gpt":
            async for ev in _run_gpt(client, prompt, image_urls, params):
                yield ev
        else:
            async for ev in _run_gemini(client, prompt, image_urls, params):
                yield ev
    except httpx.HTTPStatusError as e:
        yield {"type": "error", "message": f"绘图上游错误: {e.response.status_code}"}
    except Exception as e:
        logger.error(f"image gen failed: {e}")
        yield {"type": "error", "message": f"绘图失败: {e}"}
