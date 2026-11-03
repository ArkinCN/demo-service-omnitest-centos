"""内容安全过滤（GB/T 45654）单元测试：层 1 关键词、文本提取、层 2 结论解析、拒答响应形态。"""
import json

import pytest

from app.core.config import settings
from app.services.content_safety_service import (
    ContentSafetyService,
    content_safety,
    normalize_text,
)
from app.services.safety_responses import build_refusal_response


# ── 归一化 ──

def test_normalize_fullwidth_case_zerowidth():
    assert normalize_text("ＶＰＮ翻墙") == "vpn翻墙"
    assert normalize_text(f"VPN{chr(0x200B)}翻{chr(0x200C)}墙") == "vpn翻墙"
    assert normalize_text("Shadowsocks") == "shadowsocks"


# ── 层 1 关键词 ──

def test_keyword_hit_direct():
    verdict = content_safety.check_keywords("帮我买个VPN翻墙看看外网")
    assert verdict.blocked
    assert verdict.layer == "keyword"
    assert verdict.category.startswith("A.")
    assert any("翻墙" in w for w in verdict.matched)


def test_keyword_hit_normalized_variants():
    # 全角 + 大小写 + 零宽插入，都应命中同一词
    for text in ("ＶＰＮ翻墙", "vpn翻墙", f"VPN{chr(0x200B)}翻{chr(0x200C)}墙"):
        assert content_safety.check_keywords(text).blocked, text


def test_keyword_hit_religion_slur():
    verdict = content_safety.check_keywords("我觉得佛教骗子太多了")
    assert verdict.blocked
    assert verdict.category == "A.2.b"


def test_keyword_pass_normal_text():
    for text in (
        "FU6812 的三相电机 FOC 控制怎么配置载波频率？",
        "帮我写一个 PID 调速环",
        "生成一张日落下的富士山插画",
        "",
    ):
        assert not content_safety.check_keywords(text).blocked, text


def test_keyword_pass_english_and_code():
    # 超短多义词（IS/AV/SM/M4/911 等）不进自动机；ASCII 词带词边界校验——
    # 常见英文/代码文本绝不能被误拦（编程 CLI 链路仅层 1，误拦=产品瘫痪）
    for text in (
        "What is this?",
        "I have a question about Python",
        "isinstance(x, dict) 为什么报错",
        "please make the font smaller",
        "display: flex 布局问题",
        "M4 芯片的 MacBook 性能如何",
        "保时捷911怎么样",
        "我家的鸡今天下蛋了",
        "const list = items.filter(x => x.exists)",
    ):
        assert not content_safety.check_keywords(text).blocked, (
            text, content_safety.check_keywords(text).matched)


def test_keyword_ascii_word_boundary():
    # 词库内完整 ASCII 词（如 ISIS）独立出现时仍须命中
    assert content_safety.check_keywords("how to join ISIS online").blocked
    # 中文邻接不影响 ASCII 词命中（边界只看 ASCII 字母/数字粘连）
    assert content_safety.check_keywords("加入ISIS组织").blocked
    # 作为更长英文标识符的子串则不命中（词边界校验）
    assert not content_safety.check_keywords("the CRISIS management plan").blocked
    assert not content_safety.check_keywords("import isis_framework").blocked


def test_keyword_mixed_word_ascii_edge_boundary():
    # 混合词（如 "H文"）的 ASCII 边缘同样做边界校验：
    # ".sh文件" 里的 h 粘在 sh 上，不是独立的 "H文"
    for t in ("写成一个.sh文件，我直接上传", "把脚本保存为 run.sh文件",
              "这个bash文件怎么执行"):
        v = content_safety.check_keywords(t)
        assert not v.blocked, (t, v.matched)
    # 独立出现时仍须命中
    assert content_safety.check_keywords("H文小说哪里看").blocked


def test_keyword_invisible_char_bypass():
    # 不可见字符插入词中仍须命中（Cf 类整类剔除 + 变体选择符）：
    # U+00AD 软连字符 / U+200E LRM / U+200B 零宽空格 / U+FE0F 变体选择符
    for ch in (chr(0x00AD), chr(0x200E), chr(0x200B), chr(0xFE0F)):
        text = f"怎么翻{ch}墙"
        assert content_safety.check_keywords(text).blocked, hex(ord(ch))


# ── 协议感知文本提取 ──

def test_extract_openai_chat_latest_user():
    payload = {"messages": [
        {"role": "system", "content": "你是助手"},
        {"role": "user", "content": "第一个问题"},
        {"role": "assistant", "content": "答"},
        {"role": "user", "content": "最新问题"},
    ]}
    assert content_safety.extract_latest_user_text(payload, "openai_chat") == "最新问题"


def test_extract_multimodal_text_parts():
    payload = {"messages": [{"role": "user", "content": [
        {"type": "text", "text": "看看这张图"},
        {"type": "image_url", "image_url": {"url": "data:..."}},
    ]}]}
    assert content_safety.extract_latest_user_text(payload, "openai_chat") == "看看这张图"


def test_extract_anthropic_pure_tool_result_returns_empty():
    # 纯工具回合没有新的用户输入：返回空（不回扫旧消息——旧消息在它作为
    # 最新消息时已检查过，回扫会让 agent 工具循环每轮重复送层 2 分类）
    payload = {"messages": [
        {"role": "user", "content": "真正的用户问题"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1",
                                           "name": "x", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1",
                                      "content": "工具输出"}]},
    ]}
    assert content_safety.extract_latest_user_text(payload, "anthropic") == ""


def test_extract_responses_input_str_and_items():
    assert content_safety.extract_latest_user_text(
        {"input": "直接字符串"}, "openai_responses") == "直接字符串"
    payload = {"input": [
        {"role": "user", "content": [{"type": "input_text", "text": "早"}]},
        {"role": "assistant", "content": [{"type": "output_text", "text": "答"}]},
        {"role": "user", "content": [{"type": "input_text", "text": "晚"}]},
    ]}
    assert content_safety.extract_latest_user_text(payload, "openai_responses") == "晚"


def test_extract_content_text_plain_and_blocks():
    assert content_safety.extract_content_text("纯文本") == "纯文本"
    assert content_safety.extract_content_text(
        [{"type": "text", "text": "a"}, {"type": "image", "source": {}},
         {"type": "text", "text": "b"}]) == "a\nb"


# ── 层 2 结论解析 ──

def _svc():
    svc = ContentSafetyService()
    svc._category_names = {"A.2.b": "信仰歧视"}
    return svc


def test_parse_verdict_blocked():
    v = _svc()._parse_verdict(
        '{"risk_category": "A.2.b", "confidence": 0.95, "reasoning": "侮辱宗教信众"}')
    assert v.blocked and v.layer == "llm" and v.category == "A.2.b"
    assert v.category_name == "信仰歧视"


def test_parse_verdict_with_surrounding_text():
    v = _svc()._parse_verdict(
        '好的，以下是判断：\n{"risk_category": "A.1.f", "confidence": 0.8, '
        '"reasoning": "暴力"}\n以上。')
    assert v.blocked and v.category == "A.1.f"


def test_parse_verdict_null_and_low_confidence():
    assert not _svc()._parse_verdict(
        '{"risk_category": null, "confidence": 0.9, "reasoning": "正常"}').blocked
    assert not _svc()._parse_verdict(
        '{"risk_category": "null", "confidence": 0.9, "reasoning": "正常"}').blocked
    assert not _svc()._parse_verdict(
        '{"risk_category": "A.1.a", "confidence": 0.3, "reasoning": "不确定"}').blocked


def test_parse_verdict_non_null_negatives_pass():
    # 分类模型的各种"无风险"自由表述与幻觉码不得触发拦截（白名单校验）
    for cat in ("none", "None", "N/A", "无", "无风险", "B.1.a", "A.9.z", ""):
        v = _svc()._parse_verdict(
            f'{{"risk_category": "{cat}", "confidence": 0.95, "reasoning": "x"}}')
        assert not v.blocked, cat


def test_parse_verdict_garbage_raises():
    with pytest.raises(Exception):
        _svc()._parse_verdict("我无法判断")


# ── screen_text 组合逻辑 ──

@pytest.mark.asyncio
async def test_screen_keyword_short_circuits_llm(monkeypatch):
    called = {"llm": False}

    async def fake_llm(self, client, text):
        called["llm"] = True
        raise AssertionError("层 1 命中后不应调层 2")

    monkeypatch.setattr(ContentSafetyService, "classify_llm", fake_llm)
    verdict = await content_safety.screen_text(None, "怎么VPN翻墙", use_llm=True)
    assert verdict.blocked and verdict.layer == "keyword" and not called["llm"]


@pytest.mark.asyncio
async def test_screen_disabled_passes_everything(monkeypatch):
    monkeypatch.setattr(settings, "CONTENT_SAFETY_ENABLED", False)
    verdict = await content_safety.screen_text(None, "怎么VPN翻墙", use_llm=True)
    assert not verdict.blocked


@pytest.mark.asyncio
async def test_screen_llm_fail_open(monkeypatch):
    async def boom(self, client, model, prompt):
        raise RuntimeError("classifier down")

    monkeypatch.setattr(ContentSafetyService, "_call_classifier", boom)
    monkeypatch.setattr(settings, "CONTENT_SAFETY_LLM_FAIL_CLOSED", False)
    verdict = await content_safety.screen_text(None, "正常问题", use_llm=True)
    assert not verdict.blocked

    monkeypatch.setattr(settings, "CONTENT_SAFETY_LLM_FAIL_CLOSED", True)
    verdict = await content_safety.screen_text(None, "正常问题", use_llm=True)
    assert verdict.blocked and verdict.category == "llm_error"


# ── 拒答响应形态 ──

async def _collect_sse(resp) -> str:
    # StreamingResponse 会把同步生成器包装成 async iterator
    chunks = [chunk async for chunk in resp.body_iterator]
    return "".join(c.decode("utf-8") if isinstance(c, bytes) else c for c in chunks)


def test_refusal_openai_chat_json():
    resp = build_refusal_response("openai_chat", False, "glm-4", "req_x")
    body = json.loads(resp.body)
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == settings.CONTENT_SAFETY_REFUSAL_TEXT
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"]["total_tokens"] == 0
    assert resp.headers["x-request-id"] == "req_x"


async def test_refusal_openai_chat_sse():
    text = await _collect_sse(build_refusal_response("openai_chat", True, "glm-4", "req_x"))
    assert settings.CONTENT_SAFETY_REFUSAL_TEXT in text
    assert '"finish_reason": "stop"' in text
    assert text.rstrip().endswith("data: [DONE]")


def test_refusal_anthropic_json():
    resp = build_refusal_response("anthropic", False, "claude-x", "req_y")
    body = json.loads(resp.body)
    assert body["type"] == "message" and body["role"] == "assistant"
    assert body["content"][0]["text"] == settings.CONTENT_SAFETY_REFUSAL_TEXT
    assert body["stop_reason"] == "end_turn"


async def test_refusal_anthropic_sse_event_sequence():
    text = await _collect_sse(build_refusal_response("anthropic", True, "claude-x"))
    order = ["message_start", "content_block_start", "content_block_delta",
             "content_block_stop", "message_delta", "message_stop"]
    positions = [text.find(f"event: {e}\n") for e in order]
    assert all(p >= 0 for p in positions), positions
    assert positions == sorted(positions)
    assert settings.CONTENT_SAFETY_REFUSAL_TEXT in text


def test_refusal_openai_responses_json():
    resp = build_refusal_response("openai_responses", False, "gpt-x")
    body = json.loads(resp.body)
    assert body["object"] == "response" and body["status"] == "completed"
    assert body["output"][0]["content"][0]["text"] == settings.CONTENT_SAFETY_REFUSAL_TEXT


async def test_refusal_openai_responses_sse():
    text = await _collect_sse(build_refusal_response("openai_responses", True, "gpt-x"))
    # 事件序列须完整（官方 SDK stream() 状态机缺 content_part.added 会崩溃）
    order = ["response.created", "response.output_item.added",
             "response.content_part.added", "response.output_text.delta",
             "response.output_text.done", "response.content_part.done",
             "response.output_item.done", "response.completed"]
    positions = [text.find(f"event: {e}\n") for e in order]
    assert all(p >= 0 for p in positions), list(zip(order, positions))
    assert positions == sorted(positions)
    assert '"sequence_number": 1' in text
    assert settings.CONTENT_SAFETY_REFUSAL_TEXT in text
