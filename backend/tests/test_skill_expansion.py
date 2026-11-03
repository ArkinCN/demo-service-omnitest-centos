"""
skill_expansion / skill_service 单元测试(sqlite 内存库,不依赖 MySQL)。

运行:.venv/Scripts/python -m pytest tests/test_skill_expansion.py -v

覆盖接口契约的关键性质:
- 三协议(anthropic / openai_responses / openai_chat)的合法展开;
- 配对校验:仅 Skill/SkillResource 的 tool 结果块展开,MCP 名伪造、用户
  输入文本里的占位符一律不动;
- 授权重查:无权/revoked → 确定性兜底文案,绝不透传裸占位符;
- version pin:历史占位符永远解析到 pin 的版本;
- 确定性:同一占位符两次展开字节一致(prompt cache 前提);
- 结构保真:不动块序、保留 cache_control;无命中时原对象直返(零拷贝);
- zip 上传解析与资源路径防穿越。
"""
import io
import zipfile

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.skill import SkillExpansionLog
from app.models.user import User
from app.services import skill_audit
from app.services.skill_expansion import expand_skill_placeholders
from app.services.skill_service import (
    SkillService,
    normalize_resource_path,
    parse_version_to_code,
)

PDF_BODY_V1 = "# PDF Skill\nSECRET-BODY-V1 使用 pdftk 三步流程。"
PDF_BODY_V2 = "# PDF Skill\nSECRET-BODY-V2 使用 qpdf 两步流程。"
GUIDE_CONTENT = "SECRET-RESOURCE guide 内容。"


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture()
def user(session):
    u = User(username="dev1", email="dev1@example.com", hashed_password="x", is_active=True)
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


@pytest.fixture()
def skills(session, user):
    """pdf-official(v1.0.0 → v1.0.1 含资源) + secret-skill(无权) + dead-skill(revoked)"""
    pdf = SkillService.create_skill(
        session, name="pdf-official", description="PDF 处理",
        version="1.0.0", content=PDF_BODY_V1, created_by=user.id,
    )
    SkillService.add_version(
        session, skill=pdf, version="1.0.1", content=PDF_BODY_V2,
        resources=[{"path": "references/guide.md", "content": GUIDE_CONTENT}],
        set_current=True, created_by=user.id,
    )
    secret = SkillService.create_skill(
        session, name="secret-skill", description="内部专用",
        visibility="SPECIFIED", allowed_user_ids=[999_999],
        version="1.0.0", content="TOP-SECRET", created_by=user.id,
    )
    dead = SkillService.create_skill(
        session, name="dead-skill", description="已止血",
        version="1.0.0", content="LEAKED-CONTENT", created_by=user.id,
    )
    dead.revoked = True
    session.add(dead)
    session.commit()
    return {"pdf": pdf, "secret": secret, "dead": dead}


def anthropic_request(tool_name="Skill", tool_use_id="toolu_1",
                      result_content="[[MOTORDEBUG-SKILL::pdf-official::v10001]]"):
    return {
        "model": "claude-x",
        "messages": [
            {"role": "user", "content": "帮我处理 pdf"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": tool_use_id, "name": tool_name,
                 "input": {"skill": "pdf-official"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tool_use_id,
                 "content": result_content},
            ]},
        ],
    }


def expand(session, user, data, protocol="anthropic"):
    return expand_skill_placeholders(
        session, data, protocol=protocol,
        user_id=user.id, user_group_ids=[], user_email=user.email or "",
        request_id="req_test", agent_role="main",
    )


class TestAnthropicExpansion:
    def test_legit_expansion(self, session, user, skills):
        data = anthropic_request()
        out = expand(session, user, data)
        text = out["messages"][2]["content"][0]["content"]
        assert PDF_BODY_V2 in text
        assert "[[MOTORDEBUG-SKILL" not in text
        assert '<motordebug-builtin-skill name="pdf-official" version="1.0.1"' in text
        assert "SkillResource tool" in text  # 有资[源] → 附资源清单指引
        assert "references/guide.md" in text
        # 原件不被污染(SkillClaw/错误日志用)
        assert data["messages"][2]["content"][0]["content"] == \
            "[[MOTORDEBUG-SKILL::pdf-official::v10001]]"

    def test_blocks_content_preserves_cache_control(self, session, user, skills):
        data = anthropic_request()
        data["messages"][2]["content"][0]["content"] = [
            {"type": "text", "text": "[[MOTORDEBUG-SKILL::pdf-official::v10001]]",
             "cache_control": {"type": "ephemeral"}},
        ]
        out = expand(session, user, data)
        block = out["messages"][2]["content"][0]["content"][0]
        assert PDF_BODY_V2 in block["text"]
        assert block["cache_control"] == {"type": "ephemeral"}

    def test_mcp_forged_tool_name_not_expanded(self, session, user, skills):
        data = anthropic_request(tool_name="mcp__demo__echo")
        out = expand(session, user, data)
        assert out is data  # 无合法候选 → 原对象直返

    def test_user_typed_placeholder_not_expanded(self, session, user, skills):
        data = {
            "model": "claude-x",
            "messages": [
                {"role": "user", "content": "[[MOTORDEBUG-SKILL::pdf-official::v10001]]"},
            ],
        }
        out = expand(session, user, data)
        assert out is data

    def test_no_permission_falls_back(self, session, user, skills):
        data = anthropic_request(result_content="[[MOTORDEBUG-SKILL::secret-skill::v10000]]")
        text = expand(session, user, data)["messages"][2]["content"][0]["content"]
        assert "TOP-SECRET" not in text
        assert "unavailable" in text
        assert "[[MOTORDEBUG-SKILL" not in text  # 绝不透传裸占位符

    def test_revoked_falls_back(self, session, user, skills):
        data = anthropic_request(result_content="[[MOTORDEBUG-SKILL::dead-skill::v10000]]")
        text = expand(session, user, data)["messages"][2]["content"][0]["content"]
        assert "LEAKED-CONTENT" not in text
        assert "unavailable" in text

    def test_version_pin_resolves_old_version(self, session, user, skills):
        data = anthropic_request(result_content="[[MOTORDEBUG-SKILL::pdf-official::v10000]]")
        text = expand(session, user, data)["messages"][2]["content"][0]["content"]
        assert PDF_BODY_V1 in text
        assert PDF_BODY_V2 not in text

    def test_unknown_version_falls_back(self, session, user, skills):
        data = anthropic_request(result_content="[[MOTORDEBUG-SKILL::pdf-official::v99999]]")
        text = expand(session, user, data)["messages"][2]["content"][0]["content"]
        assert "unavailable" in text

    def test_inactive_but_not_revoked_still_expands(self, session, user, skills):
        """下架(is_active=False)只影响清单,历史 pin 仍可展开(进行中会话不断粮)。"""
        skills["pdf"].is_active = False
        session.add(skills["pdf"])
        session.commit()
        data = anthropic_request()
        text = expand(session, user, data)["messages"][2]["content"][0]["content"]
        assert PDF_BODY_V2 in text

    def test_deterministic_bytes(self, session, user, skills):
        a = expand(session, user, anthropic_request())["messages"][2]["content"][0]["content"]
        b = expand(session, user, anthropic_request())["messages"][2]["content"][0]["content"]
        assert a == b

    def test_resource_expansion(self, session, user, skills):
        data = anthropic_request(
            tool_name="SkillResource",
            result_content="[[MOTORDEBUG-SKILL-RES::pdf-official::v10001::references/guide.md]]",
        )
        text = expand(session, user, data)["messages"][2]["content"][0]["content"]
        assert GUIDE_CONTENT in text
        assert '<motordebug-skill-resource skill="pdf-official" path="references/guide.md"' in text

    def test_resource_path_traversal_falls_back(self, session, user, skills):
        data = anthropic_request(
            tool_name="SkillResource",
            result_content="[[MOTORDEBUG-SKILL-RES::pdf-official::v10001::references/../guide.md]]",
        )
        text = expand(session, user, data)["messages"][2]["content"][0]["content"]
        assert GUIDE_CONTENT not in text
        assert "unavailable" in text


class TestOpenAIProtocols:
    def test_openai_responses_expansion(self, session, user, skills):
        data = {
            "model": "gpt-x",
            "input": [
                {"type": "function_call", "call_id": "call_1", "name": "Skill",
                 "arguments": "{\"skill\":\"pdf-official\"}"},
                {"type": "function_call_output", "call_id": "call_1",
                 "output": "[[MOTORDEBUG-SKILL::pdf-official::v10001]]"},
            ],
        }
        out = expand(session, user, data, protocol="openai_responses")
        assert PDF_BODY_V2 in out["input"][1]["output"]
        assert data["input"][1]["output"].startswith("[[MOTORDEBUG-SKILL")

    def test_openai_responses_forged_name_not_expanded(self, session, user, skills):
        data = {
            "model": "gpt-x",
            "input": [
                {"type": "function_call", "call_id": "call_1", "name": "mcp__x__echo",
                 "arguments": "{}"},
                {"type": "function_call_output", "call_id": "call_1",
                 "output": "[[MOTORDEBUG-SKILL::pdf-official::v10001]]"},
            ],
        }
        assert expand(session, user, data, protocol="openai_responses") is data

    def test_openai_chat_expansion(self, session, user, skills):
        data = {
            "model": "gpt-x",
            "messages": [
                {"role": "assistant", "tool_calls": [
                    {"id": "call_1", "type": "function",
                     "function": {"name": "Skill", "arguments": "{}"}},
                ]},
                {"role": "tool", "tool_call_id": "call_1",
                 "content": "[[MOTORDEBUG-SKILL::pdf-official::v10001]]"},
            ],
        }
        out = expand(session, user, data, protocol="openai_chat")
        # 无 system 消息时注入器会在开头插一条保密指令，故按 role 定位 tool 消息
        tool_msg = next(m for m in out["messages"] if m.get("role") == "tool")
        assert PDF_BODY_V2 in tool_msg["content"]
        assert out["messages"][0]["role"] == "system"  # 注入的保密指令

    def test_openai_chat_unpaired_tool_message_not_expanded(self, session, user, skills):
        data = {
            "model": "gpt-x",
            "messages": [
                {"role": "tool", "tool_call_id": "call_orphan",
                 "content": "[[MOTORDEBUG-SKILL::pdf-official::v10001]]"},
            ],
        }
        assert expand(session, user, data, protocol="openai_chat") is data


class TestManifest:
    def test_available_excludes_hidden(self, session, user, skills):
        manifest = SkillService.get_available_skills(session, user.id, [], user.email)
        names = [m["name"] for m in manifest]
        assert "pdf-official" in names
        assert "secret-skill" not in names   # 无权
        assert "dead-skill" not in names     # revoked
        entry = next(m for m in manifest if m["name"] == "pdf-official")
        assert entry["version"] == "1.0.1"
        assert entry["version_code"] == 10001
        assert entry["body_tokens"] > 0

    def test_inactive_excluded_from_manifest(self, session, user, skills):
        skills["pdf"].is_active = False
        session.add(skills["pdf"])
        session.commit()
        manifest = SkillService.get_available_skills(session, user.id, [], user.email)
        assert "pdf-official" not in [m["name"] for m in manifest]


class TestUploadParsing:
    def _zip(self, files: dict[str, bytes]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        return buf.getvalue()

    def test_zip_with_resources(self):
        data = self._zip({
            "SKILL.md": b"---\nname: my-skill\ndescription: demo\n---\nBody",
            "references/a.md": "资源A".encode(),
        })
        parsed = SkillService.parse_upload("skill.zip", data)
        assert parsed["name"] == "my-skill"
        assert parsed["description"] == "demo"
        assert parsed["resources"] == [{"path": "references/a.md", "content": "资源A"}]

    def test_zip_single_top_dir(self):
        data = self._zip({
            "my-skill/SKILL.md": b"---\nname: my-skill\n---\nBody",
            "my-skill/references/a.md": b"res",
        })
        parsed = SkillService.parse_upload("skill.zip", data)
        assert parsed["resources"][0]["path"] == "references/a.md"

    def test_zip_rejects_binary(self):
        data = self._zip({
            "SKILL.md": b"Body",
            "references/tool.md": b"\x00\x01binary",
        })
        with pytest.raises(ValueError, match="二进制"):
            SkillService.parse_upload("skill.zip", data)

    def test_zip_rejects_script_suffix(self):
        data = self._zip({"SKILL.md": b"Body", "scripts/run.py": b"print(1)"})
        with pytest.raises(ValueError, match="文本资源"):
            SkillService.parse_upload("skill.zip", data)

    def test_zip_missing_skill_md(self):
        data = self._zip({"readme.md": b"hi"})
        with pytest.raises(ValueError, match="SKILL.md"):
            SkillService.parse_upload("skill.zip", data)


class TestConfidentialityDirective:
    def test_anthropic_appends_directive_after_cache_breakpoint(self, session, user, skills):
        # 模拟客户端已打的 system：blocks，末块带 cache_control
        data = anthropic_request()
        data["system"] = [
            {"type": "text", "text": "You are MotorDebug.", "cache_control": {"type": "ephemeral"}},
        ]
        out = expand(session, user, data)
        system = out["system"]
        # 指令作为【新块追加在最后】，缓存断点仍在原末块（前缀不变 → 零失效）
        assert len(system) == 2
        assert system[0]["cache_control"] == {"type": "ephemeral"}
        assert "cache_control" not in system[1]
        assert "confidentiality" in system[1]["text"].lower()
        # 死守方法论、放开高层用途
        assert "high-level purpose" in system[1]["text"]
        assert "methodology" in system[1]["text"]

    def test_directive_absent_when_no_expansion(self, session, user, skills):
        data = anthropic_request(tool_name="mcp__x__echo")  # 无合法展开
        data["system"] = "base"
        out = expand(session, user, data)
        assert out is data and out["system"] == "base"  # 未注入

    def test_directive_not_added_on_fallback_only(self, session, user, skills):
        data = anthropic_request(result_content="[[MOTORDEBUG-SKILL::secret-skill::v10000]]")
        data["system"] = [{"type": "text", "text": "base"}]
        out = expand(session, user, data)
        # 只有兜底、无真正专有内容 → 不注保密指令
        assert len(out["system"]) == 1

    def test_openai_responses_appends_to_instructions(self, session, user, skills):
        data = {
            "model": "gpt-x", "instructions": "Base instructions.",
            "input": [
                {"type": "function_call", "call_id": "c1", "name": "Skill", "arguments": "{}"},
                {"type": "function_call_output", "call_id": "c1",
                 "output": "[[MOTORDEBUG-SKILL::pdf-official::v10001]]"},
            ],
        }
        out = expand(session, user, data, protocol="openai_responses")
        assert out["instructions"].startswith("Base instructions.")
        assert "confidentiality" in out["instructions"].lower()

    def test_openai_chat_appends_to_system_message(self, session, user, skills):
        data = {
            "model": "gpt-x",
            "messages": [
                {"role": "system", "content": "You are MotorDebug."},
                {"role": "assistant", "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "Skill", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "c1",
                 "content": "[[MOTORDEBUG-SKILL::pdf-official::v10001]]"},
            ],
        }
        out = expand(session, user, data, protocol="openai_chat")
        assert out["messages"][0]["role"] == "system"
        assert out["messages"][0]["content"].startswith("You are MotorDebug.")
        assert "confidentiality" in out["messages"][0]["content"].lower()

    def test_note_carveout_wording_present(self, session, user, skills):
        text = expand(session, user, anthropic_request())["messages"][2]["content"][0]["content"]
        assert "high level" in text          # 放开高层用途
        assert "methodology" in text          # 死守方法论
        assert "closely paraphrase" in text   # 覆盖"改写/总结"


class TestAudit:
    def test_expansion_logged_once_per_tool_use_across_replays(self, session, user, skills):
        skill_audit.reset_seen_cache_for_tests()
        # 同一 tool_use_id 的占位符在三个"回合"里重放
        for _ in range(3):
            expand(session, user, anthropic_request(tool_use_id="toolu_replay"))
        logs = session.exec(select(SkillExpansionLog)).all()
        replay_logs = [r for r in logs if r.tool_use_id == "toolu_replay"]
        assert len(replay_logs) == 1, "按 distinct tool_use_id 去重，重放不应重复计数"
        assert replay_logs[0].skill_id == skills["pdf"].id
        assert replay_logs[0].version_code == 10001
        assert replay_logs[0].resource_path is None

    def test_fallback_not_audited(self, session, user, skills):
        skill_audit.reset_seen_cache_for_tests()
        expand(session, user, anthropic_request(
            tool_use_id="toolu_denied",
            result_content="[[MOTORDEBUG-SKILL::secret-skill::v10000]]",
        ))
        logs = session.exec(select(SkillExpansionLog)).all()
        assert all(r.tool_use_id != "toolu_denied" for r in logs)


class TestHelpers:
    def test_parse_version_to_code(self):
        assert parse_version_to_code("1.0.1") == 10001
        assert parse_version_to_code("v2.3.4") == 20304
        assert parse_version_to_code("garbage") == 0

    def test_normalize_resource_path(self):
        assert normalize_resource_path("references/a.md") == "references/a.md"
        assert normalize_resource_path("./references//a.md") == "references/a.md"
        assert normalize_resource_path("refs\\a.md") == "refs/a.md"
        assert normalize_resource_path("../etc/passwd") is None
        assert normalize_resource_path("a/../b.md") is None
        assert normalize_resource_path("/abs/path.md") == "abs/path.md"
        assert normalize_resource_path("bad*char.md") is None
