"""把 .env 的大模型配置同步到数据库里的渠道记录。

为什么需要它：网关是**数据库驱动路由**——请求最终打哪个上游，取决于
`gateway_channels.base_url` / `api_key`，而不是 `.env`。`.env` 只在
应用**启动时的 seed** 里被读一次、写进 DB。所以改了 `.env` 却不想重启，
或者 seed 因 `AUTH_DISABLED=false` 被跳过时，用这个脚本把值同步过去。

用法：
    python scripts/sync_llm_channel.py

只更新 base_url / api_key，不动 protocol、enabled、model_pricing 绑定。

⚠️ base_url 不要带 /v1：网关的 PROTOCOL_PATHS 已自带 /v1/chat/completions
（见 app/services/gateway_service.py），带 /v1 会拼成 /api/v1/v1/... → 404。
OpenRouter 文档给的是带 /v1 的形式，本工程要的是去掉 /v1 的前缀。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, select  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.models.gateway import GatewayChannel  # noqa: E402
from app.models.vibe_coding import VibeCodingChannel  # noqa: E402


def main() -> None:
    url = settings.MOTORDEBUG_LLM_BASE_URL.strip().rstrip("/")
    key = settings.MOTORDEBUG_LLM_API_KEY.strip()

    if not key:
        print("MOTORDEBUG_LLM_API_KEY 为空，跳过（保持管理面板手工配置的老行为）")
        return

    changed = 0
    with Session(engine) as s:
        for ch in s.exec(select(GatewayChannel)).all():
            if ch.base_url != url or ch.api_key != key:
                print(f"网关渠道 #{ch.id} {ch.name}: {ch.base_url} -> {url}")
                ch.base_url, ch.api_key = url, key
                s.add(ch)
                changed += 1
        for ch in s.exec(select(VibeCodingChannel)).all():
            if ch.base_url != url or ch.api_key != key:
                print(f"编码助手渠道 #{ch.id} {ch.name}: {ch.base_url} -> {url}")
                ch.base_url, ch.api_key = url, key
                s.add(ch)
                changed += 1
        s.commit()

    print(f"完成，更新 {changed} 条。拼接后的请求地址：{url}/v1/chat/completions")

    with Session(engine) as s:
        for ch in s.exec(select(GatewayChannel)).all():
            print("  当前：", ch.id, ch.name, ch.base_url, ch.protocol, "enabled=", ch.enabled)


if __name__ == "__main__":
    main()
