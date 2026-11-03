"""
非致命报错判定清单落盘器（汇报模式 · 编号 1）。

复用既有日志体系（对照 `app/core/error_logger.py` 的 JSONL + RotatingFileHandler
模式，**不引入任何新的日志框架**），把前端每轮上报的「逐条判定」写成**中文可读**
的文本行，落到 `logs/error_judge.log`，供用户跑一轮后打开核对。

为什么单独一个文件而不是写 app.log：
  · app.log 是运行日志（INFO 级混杂一切），判定清单要能「一眼逐条核对」，
    单独文件 + 一行一条的紧凑格式最直观；
  · 同时仍经 app.log 留一条摘要（见 record_judge_report），两边可按轮次对照。

行格式（中文可读）：
  [时间] 轮次=… 终态=… 候选=N（可隐藏=x / 保留=y）
  [时间]   隐藏 | 环节(run,最终成功) | 依据 | 原文
  [时间]   保留 | 环节(report,最终失败) | 依据 | 原文
"""
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logger import logger

# 专用 logger：独立文件、独立格式（只写 message，格式在写入前拼好）
_judge_logger = logging.getLogger("automation_judge")
_judge_logger.setLevel(logging.INFO)
_judge_logger.propagate = False

if not _judge_logger.handlers:
    _log_dir = Path(settings.LOG_DIR)
    _log_dir.mkdir(parents=True, exist_ok=True)
    _handler = RotatingFileHandler(
        _log_dir / "error_judge.log",
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8",
    )
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _judge_logger.addHandler(_handler)


def _fmt_ts(ms: Any) -> str:
    """把毫秒时间戳转成可读本地时间；非法输入原样透出，不编造。"""
    try:
        return datetime.fromtimestamp(float(ms) / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return str(ms)


def _stage_line(stage_id: str, stage_name: str | None, stage_final: str | None) -> str:
    """环节描述：名称优先，状态用中文，取不到如实写「—」。"""
    name = stage_name or stage_id or "—"
    final_zh = {
        "success": "最终成功",
        "failed": "最终失败",
        "skipped": "被跳过",
        "running": "未收口",
        "pending": "未开始",
    }.get(str(stage_final), str(stage_final) if stage_final else "—")
    return f"{name}（{stage_id},{final_zh}）"


def record_judge_report(body: dict) -> dict:
    """
    把一份判定清单写入 logs/error_judge.log。

    Args:
        body: 前端上报的请求体（已通过 pydantic 校验与上限保护）。

    Returns:
        {"file": 落盘文件路径, "lines": 写入行数}
    """
    run_id = str(body.get("run_id", "")) or "—"
    run_id_short = run_id if len(run_id) <= 16 else run_id[:8] + "…" + run_id[-6:]
    scene_id = str(body.get("scene_id", "—"))
    terminal = str(body.get("terminal_status", "—"))
    counts = body.get("counts", {}) or {}
    entries = body.get("entries", []) or []
    uploaded_at = str(body.get("uploaded_at", "—"))

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = []

    # 轮次汇总行（同时打出完整与短号：短号便于一眼对齐，完整号便于按轮次检索）
    lines.append(
        f"[{now}] ===== 轮次 {run_id_short}（完整 {run_id}）场景 {scene_id} 终态 {terminal} "
        f"| 候选 {counts.get('candidates', 0)} 条（可隐藏 {counts.get('hide', 0)} / 保留 {counts.get('keep', 0)}）"
        f"| 前端上报时刻 {uploaded_at} ====="
    )

    if not entries:
        lines.append(f"[{now}] 本轮无候选报错（无 warn/error 级日志），无需隐藏判定")
    else:
        # 逐条：判定 | 环节 | 依据 | 原文（原文压成单行，避免多行破坏「一条一行」）
        for e in entries:
            verdict_zh = "隐藏" if e.get("verdict") == "hide" else "保留"
            stage = _stage_line(
                str(e.get("stage_id", "")),
                e.get("stage_name"),
                e.get("stage_final"),
            )
            reason = str(e.get("reason", "")).replace("\n", " ")
            message = str(e.get("message", "")).replace("\n", " ")
            lines.append(
                f"[{_fmt_ts(e.get('at_ms'))}] {verdict_zh} | {stage} | {reason} | 原文：{message}"
            )

    for line in lines:
        _judge_logger.info(line)

    # 摘要也写进 app.log（两边可按轮次对照；含文件路径）
    file_path = str(Path(settings.LOG_DIR) / "error_judge.log")
    logger.info(
        f"非致命报错判定清单已落盘 run={run_id} 候选={counts.get('candidates', 0)} "
        f"可隐藏={counts.get('hide', 0)} 保留={counts.get('keep', 0)} file={file_path}"
    )
    return {"file": file_path, "lines": len(lines)}
