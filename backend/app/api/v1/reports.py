"""报告生成与下载（阶段 4.4 引入；2026-09-28 修 G-06 / G-07；2026-10-10 改口径）。

## 口径变更（2026-10-10 用户拍板，先看这段再看代码）

**系统内置模板（`report_workbook.py` 产出）就是客户认可的正式报告模板。**
因此原先的三档（ok / placeholder / blocked）收成两档：

| 情形 | 走哪条路 | status |
|---|---|---|
| 用户**没有**上传客户模板（默认） | 系统内置模板产出报告（`_self_built_report`） | **ok** |
| 用户**已上传**客户模板 + 填充程序齐备 | `write-file-rust` 填充客户模板 | ok |
| 用户已上传客户模板但**缺填充程序** | 不产出，如实报错 | **blocked** |
| 生成过程抛错 | 不产出，如实报错 | blocked |

两条纪律：
  1. **缺填充程序时不静默降级**：用户明确要客户模板，却给一份系统内置版式的报告，
     那是最危险的一种「看起来成功」——所以如实报 blocked 并说明缺什么。
  2. **历史文件不失效**：下载端点仍保留 `*.placeholder.xlsm` / `*.placeholder.json`
     兜底顺序，改版前生成的老报告照样下得到。

## 客户模板通路（保留但不默认走）

writeFile_rust CLI（见 `writeFile_rust/README.md`）：
    write-file-rust --template <xlsm> --images <dir> [--csv <csv>] --output <xlsm>

启用方式：把客户 .xlsm 传进 `report_templates_dir()`（或调 `POST /api/reports/template`），
并把 `write-file-rust.exe` 放到 `WRITE_FILE_RUST` 指向的位置。两者齐备即自动改走该通路。
"""
from __future__ import annotations

import io
import json
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse, Response
from sqlmodel import Session, select

from app.api.deps import get_current_user, get_db
from app.core.exceptions import BadRequestException, NotFoundException
from app.core.logger import logger
from app.core.paths import (
    C_DIR,
    PROJECT_ROOT,
    builtin_report_template,
    report_templates_dir,
    reports_dir,
)
from app.models.run import Artifact, Run
from app.models.user import User
from app.schemas.common import success_response
from app.services import report_charts
from app.services.report_template_fill import ReportFillData, fill_report_template

#: 报告表头里**由上游（流程 2 初始化配置）提供**的字段。
#: 与前端 `c/web/src/features/flow-report/assemble.ts` 的 `UPSTREAM_HEADER_KEYS`
#: **逐字一致**——这是契约（模板字段与来源流程的对应关系），两处必须同改。
UPSTREAM_HEADER_KEYS = [
    "model",
    "project_name",
    "firmware_version",
    "inlet_start_addr",
    "bootloader",
    "outlet_start_addr",
]

router = APIRouter(prefix="/api", tags=["Reports"])

# write-file-rust 可执行文件（源码侧只读目录里的编译产物）。
# **调用不算修改**——它只读模板、写输出，不改源码目录。
WRITE_FILE_RUST = PROJECT_ROOT / "writeFile_rust" / "write-file-rust.exe"

# 报告生成超时。模板不大，但 Excel 写入 + 图片压缩可能慢，给足 120 秒。
GEN_TIMEOUT_S = 120


def _safe_name(s: str) -> str:
    """文件名白名单：run_id 来自 URL，直接拼进路径会有目录穿越风险。"""
    return "".join(c for c in s if c.isalnum() or c in "-_")[:64] or "run"


def _report_path(run_id: str, ext: str) -> Path:
    return reports_dir() / f"report-{_safe_name(run_id)}.{ext}"


def _uploaded_template() -> str:
    """用户上传的客户模板（若存在）。返回路径，不存在返回空串。"""
    d = report_templates_dir()
    if not d.is_dir():
        return ""
    for p in sorted(d.glob("*.xlsm")):
        if p.is_file():
            return str(p)
    return ""


def _read_template_path(session: Session, run_id: str) -> str:
    """找模板路径。

    顺序：① 请求体显式给的 template_path；② **用户上传的模板**（报告页「上传模板文件」，
    backend/uploads/report_templates/*.xlsm）；③ 场景包里 report-template.json 登记的
    `template_file`。**不做路径猜测**——登记值不在本机就如实报缺失。
    """
    # ② 用户上传的模板（优先于场景包登记值：用户显式上传的才是「当前要用的」）
    uploaded = _uploaded_template()
    if uploaded:
        return uploaded
    # ③ 场景包的 report-template.json（前端 public 下，后端按项目根推导）
    p = PROJECT_ROOT / "c" / "web" / "public" / "scenes"
    for scene_dir in sorted(p.glob("*")) if p.is_dir() else []:
        rt = scene_dir / "report-template.json"
        if not rt.exists():
            continue
        try:
            data = json.loads(rt.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        raw = (data.get("template_file") or "").strip()
        if not raw:
            continue
        # 登记值可能是 `[源] ClientSoftware/xxx.xlsm` 这种「未随包提供」的路径，
        # 或一条绝对路径。两种情况都返回它，由调用方判断存在性。
        if raw.startswith("[源]") or raw.startswith("/") or ":" in raw:
            return raw
        return str(scene_dir / raw)
    return ""


def _latest_confirmed_report_instance(
    session: Session,
    scene_id: str,
    *,
    exclude_run_id: str | None = None,
    limit_runs: int = 20,
) -> tuple[dict, str] | None:
    """本场景**最近一份「已确认」的报告实例**（表头）→ `(content, run_id)`；找不到返回 None。

    为什么需要它（2026-10-13 实测的真实缺口）：
    「确认表头」与「生成报告」很容易落在**两个不同的轮次**上 —— 报告页确认时
    写的是「当前轮」，而生成报告取的是「最近一轮」。实测就撞上了：用户在第 5a938d39
    轮确认了 10 项表头（FU6832N / 散热风扇启动测试 / v1.2.3 …），随后又跑了一轮
    e85f3cf4，生成报告取新轮 → 新轮的报告实例还是 `draft` → 报告封面 6 个表头位
    全写「由上游带入（未提供）」。表头取数逻辑没错，错在**只在本轮产物里找**。

    与前端同口径：`web/src/features/flow-report/reportApi.ts` 的
    `loadLatestReportInstance()` 本就是「跨轮找最近一份 confirmed」；后端在这里补齐
    同一口径（不发明新机制）。命中值全部来自**人确认过**的那份产物，不是编的。

    ⚠️ 只按 `Run.created_at` 倒序、最多看 `limit_runs` 轮：确认记录通常都在最近几轮，
    20 轮足够；再多就是给生成路径平白加查询。**查不到就返回 None**（调用方照旧写
    「由上游带入（未提供）」），绝不猜。

    ⚠️ 仓内所有产物查询都是「单 run_id」写法（无 `run_id IN (...)` 批量查询先例），
    故这里按轮逐查；单轮查询很轻，且命中即返回。
    """
    if not scene_id:
        return None
    try:
        runs = session.exec(
            select(Run)
            .where(Run.scene_id == scene_id)
            .order_by(Run.created_at.desc())
            .limit(limit_runs)
        ).all()
    except Exception as exc:  # noqa: BLE001 —— 回退是加分项，查不到不许拖垮生成
        logger.warning(f"report: 查询本场景轮次失败（表头回退跳过）：{exc}")
        return None
    for r in runs:
        if exclude_run_id and r.run_id == exclude_run_id:
            continue
        try:
            arts = session.exec(
                select(Artifact).where(
                    Artifact.run_id == r.run_id,
                    Artifact.artifact_kind == "report-instance",
                )
            ).all()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"report: 读取轮次 {r.run_id[:8]} 的报告实例失败，跳过：{exc}")
            continue
        for a in arts:
            c = a.content
            if (
                isinstance(c, dict)
                and c.get("status") == "confirmed"
                and isinstance(c.get("header"), dict)
                and c["header"]
            ):
                return c, r.run_id
    return None


def _collect_report_data(session: Session, run_id: str, scene_id: str | None = None) -> dict:
    """从轮次产物里取「报告要用的真题数据」。

    ⚠️ **只取真数据，缺的如实空着**——这是本模块最容易写坏的地方：
    为了让报告「看起来完整」而给缺失字段编一个值，比留空危险得多
    （人会照着假值做判断）。所以未取到的字段会进 `missing_header_keys`，
    由 `report_workbook` 显示成「由上游带入（未提供）」。

    各段取法与前端 `flow-report/assemble.ts` **同口径**（两处都要改一起改）：
      - 表头 ← ① **已确认的 `report-instance`**（报告页「确认表头」落的，优先）
                ② `config-snapshot` 的 `product_attributes`（只认**真快照**：
                   必须带 `product_attributes` 数组；`persistRun` 落的那份简化版只记场景与时刻）
      - 判定 ← `verdict-table` 的 `verdicts[].state`
      - 判定明细 ← 同一份 `verdicts[]` 逐条取 `req_id / name / state`
        （2026-10-10 编号 4 美化新增，供报告文件列出「哪几条判了什么」）
      - 产物 ← 该轮实际有的 `artifact_kind`

    ⚠️ 表头两条来源的**优先级是刻意的**（2026-09-30）：报告页人确认过的表头
    才是「本轮最终采用值」，config-snapshot 只是它的上游初始来源。若只读
    config-snapshot，报告页补的 4 项（客户名称/工程师/Email/电话）永远不进报告——
    那正是「确认了表头但报告表头没变」的根因。
    """
    artifacts = session.exec(select(Artifact).where(Artifact.run_id == run_id)).all()
    by_kind: dict[str, Any] = {}
    for a in artifacts:
        by_kind[a.artifact_kind] = a.content

    # ── 表头
    header: dict[str, str] = {}
    missing: list[str] = list(UPSTREAM_HEADER_KEYS)
    counts: dict[str, int] | None = None
    header_source_run_id: str | None = None

    def _apply_confirmed(conf: Any, source_run_id: str) -> None:
        """把一份「已确认」的报告实例套到 header/missing 上（就地修改闭包变量）。

        只认 status == 'confirmed' 且 header 是非空 dict 的那份：每轮 persistRun 还落了
        一份 status:'draft' 的草稿（只有 note），拿它当表头会把报告表头**清空**。
        确认值可含**全部**表头字段（不只上游 6 项），故不受 UPSTREAM_HEADER_KEYS 限制。
        """
        nonlocal header_source_run_id
        # 确认产物里带了模板表头的完整定义（fields），据此把「本流程该填但没填」
        # 的项也纳入 missing，报告里如实显示「未提供」，不让人误以为漏了整段。
        conf_fields = conf.get("fields")
        if isinstance(conf_fields, list):
            for f in conf_fields:
                if isinstance(f, dict) and f.get("key") and f["key"] not in missing:
                    missing.append(str(f["key"]))
        ch = conf.get("header")
        if isinstance(ch, dict):
            for k, v in ch.items():
                if not k or v is None or str(v) == "":
                    continue
                header[str(k)] = str(v)
                if k in missing:
                    missing.remove(k)
        header_source_run_id = source_run_id

    # ① 已确认的 report-instance（报告页「确认表头」落库）——**优先**，先看本轮
    conf = by_kind.get("report-instance")
    if (
        isinstance(conf, dict)
        and conf.get("status") == "confirmed"
        and isinstance(conf.get("header"), dict)
        and conf["header"]
    ):
        _apply_confirmed(conf, run_id)

    # ①b 本轮没有已确认表头 → **回退到本场景最近一份已确认实例**（2026-10-13 新增）
    #
    # 为什么必须回退：「确认」与「生成」常常不在同一轮（人确认完又跑了一轮，
    # 生成取的是最近轮）→ 本轮实例还是 draft → 报告表头全空。用户口径（2026-10-13）：
    # 「回退到最近已确认，并在报告里标注来源轮次」。命中失败就照旧写「未提供」。
    if header_source_run_id is None:
        sid = scene_id
        if not sid:
            # 未显式传 scene_id（脚本/旧调用）：按 run_id 反查本轮场景，保证口径一致
            try:
                cur_run = session.exec(select(Run).where(Run.run_id == run_id)).first()
                sid = cur_run.scene_id if cur_run else ""
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"report: 反查轮次场景失败（表头回退跳过）：{exc}")
                sid = ""
        hit = _latest_confirmed_report_instance(session, sid or "", exclude_run_id=run_id)
        if hit is not None:
            fb_conf, fb_run_id = hit
            _apply_confirmed(fb_conf, fb_run_id)
            logger.info(
                f"report: 本轮（{run_id[:8]}）无已确认表头，沿用本场景最近已确认实例"
                f"（轮次 {fb_run_id[:8]}）的 {len(header)} 项表头"
            )
        else:
            logger.info(f"report: 本场景没有已确认的报告实例（表头将如实写「未提供」）")

    snap = by_kind.get("config-snapshot")
    if isinstance(snap, dict) and isinstance(snap.get("product_attributes"), list):
        for a in snap["product_attributes"]:
            if not isinstance(a, dict):
                continue
            k = a.get("key")
            v = a.get("value")
            if not k or v is None or v == "":
                continue
            # 上游 6 项：**确认值优先**——人确认过的值覆盖快照原值（上面已写入的不再覆盖）
            if k in UPSTREAM_HEADER_KEYS and str(k) not in header:
                header[str(k)] = str(v)
                if k in missing:
                    missing.remove(k)
        # 三类计数：_class 缺省按本体属性算（老快照没有 _class，向后兼容）
        cls = {"attr": 0, "control": 0, "header": 0}
        for a in snap["product_attributes"]:
            if not isinstance(a, dict):
                continue
            c = a.get("_class") or "attr"
            if c in cls:
                cls[c] += 1
        counts = {
            "本体属性": cls["attr"],
            "控制参数": cls["control"],
            "报告表头": cls["header"],
        }

    # ── 判定汇总
    verdict: dict[str, Any] | None = None
    # 逐条判定明细（2026-10-10 编号 4 美化新增）：报告文件据此列出
    # 「哪几条判了什么」，让判据总数与通过数之间能逐条核对。
    verdict_items: list[dict[str, Any]] = []
    vt = by_kind.get("verdict-table")
    if isinstance(vt, dict) and isinstance(vt.get("verdicts"), list):
        states = [
            (v or {}).get("state", "") if isinstance(v, dict) else ""
            for v in vt["verdicts"]
        ]
        n_pass = sum(1 for s in states if s == "pass")
        n_fail = sum(1 for s in states if s == "fail")
        # 通过率（2026-10-10 新增，需求单编号 3）
        #   B 口径：通过率 = 通过 ÷（通过 + 不通过）。
        #   「未采集」「本台架不适用」「人工判定」三类都不进分子也不进分母——
        #   把没测到的算进分母，等于把「没测」当成「不合格」，那是造假。
        #   分母为 0 时给 None：展示层显示「—」，**不许显示 0%**
        #   （0% 会被读成「全不通过」，与实际语义相反）。
        judged = n_pass + n_fail
        verdict = {
            "total": len(states),
            "pass": n_pass,
            "fail": n_fail,
            "missing": sum(1 for s in states if s in ("missing", "未采集")),
            # 「本台架不适用」与「人工判定」也各自计数（2026-10-10 随通过率一并补）：
            # 通过率的分母把这两类排除了，报告里就必须看得见它们有多少条——
            # 否则「判据总数 34、通过 + 不通过才 8」会让人以为少了 26 条。
            "not_applicable": sum(1 for s in states if s in ("not_applicable", "本台架不适用")),
            "manual": sum(1 for s in states if s == "manual"),
            "pass_rate": (n_pass / judged) if judged else None,
            "authoritative": bool(vt.get("authoritative")),
        }
        # 明细只取「报告要用的三个字段」，state 原样透传（前端与 xlsm 各自映射中文，
        # 两边同词：通过 / 不通过 / 未采集 / 人工判定 / 本台架不适用）。
        verdict_items = [
            {
                "req_id": (v or {}).get("req_id") or "",
                "name": (v or {}).get("name") or "",
                "state": (v or {}).get("state") or "",
            }
            for v in vt["verdicts"]
            if isinstance(v, dict)
        ]

    return {
        "header": header,
        "missing_header_keys": missing,
        "verdict": verdict,
        "verdict_items": verdict_items,
        "artifact_kinds": [a.artifact_kind for a in artifacts],
        "snapshot_counts": counts,
        # 表头来源轮次：本轮命中=本轮 run_id；回退命中=来源轮 run_id；未命中=None。
        # 消费方（填充器）据此在报告「报告来源」行标注出处，便于人工核对。
        "header_source_run_id": header_source_run_id,
    }


def _bench_dir_has_captures(p: Path) -> bool:
    """该硬件运行目录是否含**真实采集记录**（events.jsonl 里至少一条 capture_completed）。

    为什么需要（2026-10-12 实测事故）：调优重试会紧跟失败轮次再起一轮，失败轮次
    （启动 2 秒即挂）的目录 mtime 反而更新 —— 纯按 mtime 选「最近目录」会把报告
    图表的数据源指到**空轮次**上，有完整采集的轮次被抢走，报告里趋势图/波形图
    全变「（无）」（a295cd3b 报告实测）。这里只读事件文件做判据，不改动任何数据。
    """
    try:
        text = (p / "events.jsonl").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return '"capture_completed"' in text


def _find_bench_run_dir(run_id: str, flow_finished_at: Any) -> Path | None:
    """找与 flow 轮次关联的**硬件运行目录**（图表数据源）。

    背景（2026-10-12）：flow 轮次与 fan-tests 硬件运行是**两个不同的 run_id**
    （fan-tests 由后端 `make_run_id` 生成、flow 轮次由 createRun 生成），
    且 `persistRun` 落的 artifact 里没有记录两者的关联。因此这里两级查找：

      ① 同名目录：`<runs>/<flow run_id>/` 直接存在（用 fan-tests 建轮次的场景）；
      ② **时间窗口兜底**：finish 时刻落在「flow 轮次结束前 30 分钟 ~ 结束后 2 分钟」
         的硬件目录中，按质量分层择优选：
           tier 1（最优）：**含采集数据** 且 mtime ≤ flow 结束 +2s
                           —— settleRun 发生在硬件终态后 1~2 秒内，真实数据源
                           必然紧贴在 finished_at **之前**；
           tier 2（次选）：含采集数据（哪怕 mtime 在结束之后 —— 重试轮次的场景）；
           tier 3（兜底）：其余目录按 mtime 最近（与原行为一致，如实写「（无）」）。
         同 tier 内取 mtime 最新者。

    为什么要分层（2026-10-12 实测）：自动化「调优重跑」产生的失败空轮次
    （目录 mtime 晚于本轮结束时刻）会把纯 mtime 排序的匹配抢走，报告图表全变「（无）」。
    分层后真实数据源（tier 1）稳定命中。

    ⚠️ ② 是关联缺失下的近似，不是精确关联；日志会把命中的目录与层级打出来，
    便于人工核对。找到即用、找不到返回 None（报告如实写「（无）」）。
    """
    runs_root = C_DIR / "hardware" / "v0.6" / "runs"
    if not runs_root.is_dir():
        return None
    direct = runs_root / _safe_name(run_id)
    if direct.is_dir():
        return direct
    if flow_finished_at is None:
        return None
    try:
        # flow_finished_at 是从 DB 读出的 naive UTC，显式赋 UTC 后取 epoch，与
        # 文件系统 mtime（epoch 秒）同尺度比较，避免 naive/aware 混比。
        base = flow_finished_at.replace(tzinfo=timezone.utc).timestamp()
    except (ValueError, TypeError):
        return None
    deadline = base + 120.0
    earliest = base - 1800.0
    # (tier, -mtime, path)：tier 小的优先；同 tier 取 mtime 大的。
    cands: list[tuple[int, float, Path]] = []
    try:
        for p in runs_root.iterdir():
            if not p.is_dir():
                continue
            try:
                m = p.stat().st_mtime
            except OSError:
                continue
            if not (earliest <= m <= deadline):
                continue
            if _bench_dir_has_captures(p):
                tier = 1 if m <= base + 2.0 else 2
            else:
                tier = 3
            cands.append((tier, -m, p))
    except OSError:
        return None
    if not cands:
        return None
    cands.sort(key=lambda t: (t[0], t[1]))
    tier, neg_m, best = cands[0]
    tier_note = {
        1: "含采集数据且在轮次结束前活跃",
        2: "含采集数据",
        3: "无采集证据（按 mtime 兜底）",
    }[tier]
    logger.info(
        f"report: bench run 目录按时间窗口命中 {best.name}"
        f"（tier={tier}，{tier_note}，flow {_safe_name(run_id)}，"
        f"mtime 距结束 {base - (-neg_m):.0f}s）"
    )
    return best


def _self_built_report(run_id: str, data: dict, flow_finished_at: Any = None) -> Path:
    """用**系统内置模板**生成正式报告：真文件、可下载、能在 Excel 里打开。

    2026-10-13 口径变更（用户拍板「报告使用这个模板出」「只填写报告上有的参数或问题」）：
    报告基底改为**用户提供的模板文件本身**（`builtin_report_template()`），由
    `report_template_fill.fill_report_template` 把本轮数据写进模板已有的「待填写」位，
    再把趋势图 / 波形图插进模板预留的图位。要点：

      · **只填模板上有的位**——不新增区块、不造字段（模板封面只有 6 个表头位，
        系统表头里多出来的 4 项不填）；
      · 五张可见工作表（报告封面 / 判定明细 / 趋势图 / 波形与截图 / 报告概要）原样保留；
        「报告概要」与 `_图表数据` 是模板带来的上一轮实例，**一字不改**，
        本批图表数据另落隐藏页 `_图表数据-本次`；
      · 文件名仍是 `report-<id>.xlsm`、接口仍回 `status="ok"`、下载端点不变。

    数据取自 `_collect_report_data`（只取真数据，缺的如实写「未提供 / （无）/ —」）。
    图表数据取自硬件运行目录（`hardware/v0.6/runs/<…>/`，见 `_find_bench_run_dir`
    的两级查找），缺失时如实写「（无）」+ 原因，**绝不编造图表数据**。

    ⚠️ 模板缺失 / 模板结构不符 / 落盘后仍有「待填写」残留时**如实抛错**
    （由调用方转 `blocked`），**不降级**成自建版式——降级会让人以为拿到的是模板版式，
    那是最危险的一种「看起来成功」。旧的自建实现 `report_workbook` 保留在仓里备查。

    ⚠️ 下载端点的兜底顺序**仍保留** `*.placeholder.xlsm` / `*.placeholder.json`：
    那是改版前生成的历史文件，不因这次改口径把旧报告变成 404。
    """
    dest = _report_path(run_id, "xlsm")
    # 图表数据：先按 run_id 找同名目录，找不到退时间窗口匹配（见 _find_bench_run_dir）
    chart_data = None
    run_dir = _find_bench_run_dir(run_id, flow_finished_at)
    if run_dir is not None:
        try:
            chart_data = report_charts.collect(run_dir)
        except Exception as exc:  # noqa: BLE001 —— 图表失败不许阻断报告主体
            logger.warning(f"report: chart data collection failed for {run_id}: {exc}")
            chart_data = {"trend": [], "waves": {}, "warnings": [f"图表数据读取失败：{type(exc).__name__}: {exc}"]}
    else:
        logger.info(f"report: no bench run dir for {run_id}（图表将如实写「无」）")

    filled = fill_report_template(
        builtin_report_template(),
        dest,
        ReportFillData(
            run_id=run_id,
            header=data.get("header") or {},
            missing_header_keys=data.get("missing_header_keys") or [],
            verdict=data.get("verdict"),
            verdict_items=data.get("verdict_items") or [],
            artifact_kinds=data.get("artifact_kinds") or [],
            snapshot_counts=data.get("snapshot_counts"),
            # 「报告来源」纸面文案（用户口径 2026-10-13：写「系统内置模板：标准版」）
            source_note="系统内置模板：标准版",
            chart_data=chart_data,
            # 表头来自哪一轮（不等于本轮时，报告「报告来源」行会标注来源轮次）
            header_source_run_id=data.get("header_source_run_id"),
        ),
    )
    logger.info(
        f"report: template filled for {run_id} —— 图表 {filled['charts']} 张、"
        f"行高增加 {filled['row_growth_pt']} pt、内容类型补丁 {filled['content_type_patched']}"
    )
    # 填充过程的如实说明（缺数 / 模板无位 / 判据对不上等）逐条进日志，便于事后核对
    for w in filled["warnings"]:
        logger.warning(f"report: fill warning（{run_id}）：{w}")
    return dest


@router.post("/reports/generate")
async def generate_report(
    run_id: str,
    template_path: str | None = None,
    image_dir: str | None = None,
    csv_path: str | None = None,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """生成报告。两档见模块头（ok / blocked）。

    ⚠️ 2026-10-12 起报告**自带图表**（趋势图 + 波形图，Excel 原生图表）：
    数据取自本轮硬件运行目录（events.jsonl 的逐次采集 + 最后一批 CH*.csv），
    见 `report_charts` 与 `_self_built_report` 的说明。无采集数据时如实写「（无）」。
    `image_dir` 仍保留入参（客户模板通路启用后可直接用）。
    """
    # 轮次必须存在——否则「生成成功」的是一份指向空轮次的报告
    run = session.exec(select(Run).where(Run.run_id == run_id)).first()
    if run is None:
        raise NotFoundException(f"轮次不存在：{run_id}")

    kinds = [
        a.artifact_kind
        for a in session.exec(select(Artifact).where(Artifact.run_id == run_id)).all()
    ]

    tpl = template_path or _read_template_path(session, run_id)
    tpl_exists = bool(tpl) and not tpl.startswith("[源]") and Path(tpl).exists()

    # ── 路径 1：用户**真的上传了客户模板** → 必须走客户模板填充工具
    if tpl_exists:
        if not WRITE_FILE_RUST.exists():
            # 明确要客户模板却缺填充程序：如实报 blocked，**不静默降级**成系统内置模板
            # （降级会让人以为拿到的是客户模板版式，那是最危险的一种「看起来成功」）。
            return success_response(data={
                "run_id": run_id, "status": "blocked", "artifacts": kinds,
                "reason": (
                    f"已上传客户模板（{Path(tpl).name}），但填充程序不存在：{WRITE_FILE_RUST}。"
                    "请把 write-file-rust.exe 放到该位置，或删除已上传的客户模板以改用系统内置模板。"
                ),
            }, message="报告生成失败（缺填充程序，未产出文件）")
        out = _report_path(run_id, "xlsm")
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [str(WRITE_FILE_RUST), "--template", tpl, "--images", image_dir or str(out.parent)]
        if csv_path:
            cmd += ["--csv", csv_path]
        cmd += ["--output", str(out)]
        logger.info(f"report: running write-file-rust for {run_id}")
        try:
            # write-file-rust 是控制台程序；后端以无控制台方式运行时（服务/守护）会弹黑框。
            # Windows 下加 CREATE_NO_WINDOW 抑制（仅该平台有该常量）。
            _run_kwargs = dict(
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=GEN_TIMEOUT_S, check=False,
            )
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                _run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            proc = subprocess.run(cmd, **_run_kwargs)
        except subprocess.TimeoutExpired:
            return success_response(data={
                "run_id": run_id, "status": "blocked", "artifacts": kinds,
                "reason": f"write-file-rust 超过 {GEN_TIMEOUT_S}s 未完成",
            }, message="报告生成超时（未产出文件）")
        if proc.returncode == 0 and out.exists():
            return success_response(data={
                "run_id": run_id, "status": "ok", "file": out.name,
                "bytes": out.stat().st_size, "artifacts": kinds,
                "download_url": f"/api/reports/{run_id}/download",
            }, message="报告已生成")
        tail = (proc.stderr or "").strip().splitlines()[-1:] or [""]
        return success_response(data={
            "run_id": run_id, "status": "blocked", "artifacts": kinds,
            "reason": f"write-file-rust 退出码 {proc.returncode}：{tail[0][:300]}",
        }, message="报告生成失败（未产出文件）")

    # ── 路径 2：没有客户模板 → 系统内置模板，**这就是正式报告**
    #
    # 2026-10-10 用户拍板：系统内置模板即客户认可的正式报告模板。
    # 2026-10-13 起该「内置模板」= 用户提供的模板文件（`builtin_report_template()`），
    # 报告以它为基底填充（见 `_self_built_report`）。
    # 这里因此仍返回 status="ok"、文件名不带 placeholder。
    # 数据取自 `_collect_report_data`（只取真数据，缺的如实留「未提供」）。
    # 抓不到的异常类别（磁盘满/权限/模板缺失/仍有占位残留）一律如实报 blocked，禁裸 catch。
    # scene_id 一并传入：本轮没有已确认表头时，按场景回退到最近一份已确认实例
    data = _collect_report_data(session, run_id, run.scene_id)
    try:
        dest = _self_built_report(run_id, data, run.finished_at)
    except Exception as exc:  # noqa: BLE001 —— 生成失败必须如实报，不能假装成功
        logger.exception(f"report: self-built build failed for {run_id}")
        return success_response(data={
            "run_id": run_id, "status": "blocked", "artifacts": kinds,
            "reason": f"报告生成失败：{type(exc).__name__}: {exc}",
        }, message="报告生成失败（未产出文件）")
    logger.info(f"report: generated (system built-in template) for {run_id}")
    return success_response(data={
        "run_id": run_id, "status": "ok", "file": dest.name,
        "bytes": dest.stat().st_size, "artifacts": kinds,
        "download_url": f"/api/reports/{run_id}/download",
        "note": (
            "报告已生成（xlsm，基于报告模板）：五个工作表（报告封面 / 判定明细 / 趋势图 / "
            "波形与截图 / 报告概要）齐全，模板上的「待填写」位已按本轮真实数据填好，"
            "趋势图与波形图为 Excel 原生图表（可悬停读点）。"
            "判定结论按后端权威结果如实呈现；「未采集」与「本台架不适用」均不计入通过率分母。"
        ),
    }, message="报告已生成")


@router.api_route("/reports/{run_id}/download", methods=["GET", "HEAD"])
async def download_report(
    run_id: str,
    request: Request,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """下载报告文件（修 G-07：此前**全后端无任何报告下载端点**）。

    找不到文件时返回 404 并**说明该怎么办**，不返回空文件——
    空文件会让人以为「报告生成了但内容是空的」，那是另一回事。

    ⚠️ 2026-10-12 补 HEAD 支持（修「下载总开关被 405 掐死」）：
    前端 `reportExists()` 用 `fetch(url, { method: 'HEAD' })` 探测文件是否存在，
    而本端点此前只注册了 GET → **HEAD 恒 405** → 前端恒判「没有文件」：
      · 自动化流程的结束阶段「自动下载」永不触发（结果卡只能含糊提示
        「下载可能被浏览器拦截」）；
      · 报告页手动下载也被拦（提示「报告还没生成」，而文件其实已在磁盘上）。
    HEAD 与 GET 走**同一套查找顺序与 404 语义**；HEAD 只回头（含 Content-Length
    与 Content-Disposition，文件名与 GET 一致），不返正文。
    """
    # 查找顺序（**正式名优先，历史文件兜底**）：
    #   ① report-<id>.xlsm            —— 正式报告（2026-10-10 起，系统内置模板也用它）
    #   ② report-<id>.placeholder.xlsm —— **改版前**生成的占位 xlsm（2026-09-28 ~ 10-09）
    #   ③ report-<id>.placeholder.json —— 更早的「只有元数据」版占位件
    # ②③ 只为兼容历史轮次：改口径不该让旧报告的下载变成 404
    # （历史记录不该因为改了格式而失效）。
    media_by_suffix = {
        ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
        ".json": "application/json",
    }
    for name in (
        f"report-{_safe_name(run_id)}.xlsm",
        f"report-{_safe_name(run_id)}.placeholder.xlsm",
        f"report-{_safe_name(run_id)}.placeholder.json",
    ):
        p = reports_dir() / name
        if p.exists():
            if request.method == "HEAD":
                return Response(
                    status_code=200,
                    headers={
                        "Content-Type": media_by_suffix.get(p.suffix, "application/octet-stream"),
                        "Content-Length": str(p.stat().st_size),
                        "Content-Disposition": f'attachment; filename="{p.name}"',
                    },
                )
            return FileResponse(
                path=str(p),
                media_type=media_by_suffix.get(p.suffix, "application/octet-stream"),
                filename=p.name,
                headers={"Content-Disposition": f'attachment; filename="{p.name}"'},
            )
    raise NotFoundException(
        f"轮次 {run_id} 还没有报告文件。先调用 POST /api/reports/generate?run_id={run_id} 生成。"
    )


def _looks_like_generated_report(content: bytes) -> str:
    """判断上传的文件是不是**本系统生成的测试报告**（而非客户报告模板）。

    为什么要查（2026-10-12 增）：实测用户**连续多次**把「下载的报告」当客户模板上传。
    一旦上传，`_read_template_path` 就优先返回它 → 报告生成切到「客户模板 + 填充程序」
    路径 → 因本部署没有 write-file-rust.exe 而如实 blocked。
    于是陷入「上传 → 生成失败 → 找人问原因」的循环，而正确的用法其实**根本不用上传**。

    本系统自建报告的文件特征（见 `_self_built_report` / report_charts.py）：
      · 工作表名「报告概要」与「_图表数据」（后者专用于存图表数据）；
      · 正文含「判定汇总」等报告小节标题。
    客户模板（如 Fortior_Motor_Checklist）不含这些，故可用于区分。

    ⚠️ 2026-10-13 起报告改为「以用户模板为基底填充」，故**本系统内置模板文件本身
    也带这两个工作表名**、同样会被本判据命中。这不影响功能：该判据只用于
    `upload_report_template`——拦的是「把（下载的）报告误当客户模板上传」，
    而内置模板本就不需要上传（生成时默认就是它）。

    返回 '' = 不是报告；否则返回命中的特征（拼成一句给人看）。
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
        names = zf.namelist()
        wb = zf.read('xl/workbook.xml').decode('utf-8', 'replace') if 'xl/workbook.xml' in names else ''
        ss = (zf.read('xl/sharedStrings.xml').decode('utf-8', 'replace')
              if 'xl/sharedStrings.xml' in names else '')
        hits: list[str] = []
        if '报告概要' in wb or '报告概要' in ss:
            hits.append('工作表「报告概要」')
        if '_图表数据' in wb or '_图表数据' in ss:
            hits.append('工作表「_图表数据」')
        if '判定汇总' in ss:
            hits.append('正文「判定汇总」')
        return '、'.join(hits)
    except Exception:  # noqa: BLE001 - 不是 zip / 读取失败 → 按「不是报告」处理，交给原流程报错
        return ''


@router.post("/reports/template")
async def upload_report_template(
    file: UploadFile = File(...),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传客户报告模板（.xlsm），覆盖式更新。

    用户通过报告页「上传模板文件」把客户正式模板放进来；上传后生成报告走
    真模板（write-file-rust），文件名不带 placeholder、status=ok。
    """
    filename = file.filename or ""
    if not filename.lower().endswith(".xlsm"):
        raise BadRequestException("模板必须是 .xlsm 文件（客户 Motor Checklist 模板）")

    content = await file.read()
    if not content:
        raise BadRequestException("上传的模板是空文件")

    # ⚠️ 2026-10-12 增：入口拦截「把生成的报告当模板上传」。
    report_like = _looks_like_generated_report(content)
    if report_like:
        raise BadRequestException(
            f"这个文件是本系统**生成的测试报告**（检测到 {report_like}），不是客户报告模板，已拒绝上传。"
            "报告**不需要上传**：回到报告页直接点「生成报告」，系统会自动填入数据并下载文件"
            "（走内置正式模板，含趋势图 / 波形图）。"
            "如果你确实要改用**客户提供的模板**，请上传客户给的 .xlsm 模板原件"
            "（例如 Fortior_Motor_Checklist 公用模板），而不是本系统的产出报告。"
        )

    d = report_templates_dir()
    d.mkdir(parents=True, exist_ok=True)
    # 覆盖式：清掉旧模板，避免多份 *.xlsm 让 _uploaded_template 取到旧的
    for old in d.glob("*.xlsm"):
        try:
            old.unlink()
        except OSError:
            pass
    dest = d / f"template-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.xlsm"
    dest.write_bytes(content)

    logger.info(f"report: template uploaded -> {dest.name} ({len(content)} bytes)")
    # ⚠️ 提示按**实际就绪状态**如实给（2026-10-12 修）：原提示无条件写
    # 「重新生成报告即为正式报告（status=ok）」——但填充程序缺失时生成会被
    # blocked（如实报错的设计），提示与实际行为不符会让人白跑一趟才发现。
    tool_ready = WRITE_FILE_RUST.exists()
    note = (
        "模板与填充程序均已就位，重新生成报告将走客户模板。"
        if tool_ready
        else f"模板已就位，但填充程序缺失（{WRITE_FILE_RUST}）——现在生成报告会如实报 blocked。"
        "请放入填充程序，或点「移除」按钮移除模板改用系统内置模板。"
    )
    return success_response(data={
        "filename": filename,
        "bytes": len(content),
        "stored": dest.name,
        "tool_ready": tool_ready,
        "note": note,
    }, message="客户模板已上传")


@router.delete("/reports/template")
async def delete_report_template(
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """移除已上传的客户模板，恢复「系统内置模板」生成路径（2026-10-12 新增）。

    为什么需要：生成报告被 blocked 时的提示写着「或删除已上传的客户模板以改用
    系统内置模板」——但此前**没有任何删除入口**（上传是覆盖式、无单独删除），
    人在界面上无从执行这条补救，只能找开发者上服务器手工删文件（实测发生：
    2026-10-12 有人把一份生成好的报告误当模板上传，之后所有报告生成全被
    blocked，而界面上无路可退）。本端点把这条补救闭环：移除后
    `generate_report` 自动回到系统内置模板路径（产出即含趋势图/波形图的正式报告）。

    ⚠️ 只删 `report_templates_dir()` 下的 `*.xlsm`（本功能自己的上传物），
    **不动其他目录的任何文件**——删除范围最小化。
    """
    d = report_templates_dir()
    removed: list[str] = []
    if d.is_dir():
        for old in d.glob("*.xlsm"):
            try:
                old.unlink()
                removed.append(old.name)
            except OSError:
                pass
    logger.info(f"report: template(s) removed: {removed}")
    if not removed:
        return success_response(data={
            "removed": [], "count": 0,
            "note": "当前没有已上传的客户模板，无需移除。",
        }, message="没有已上传的客户模板")
    return success_response(data={
        "removed": removed,
        "count": len(removed),
        "note": "已恢复系统内置模板路径：此后生成的报告使用内置正式模板（含趋势图 / 波形图）。",
    }, message="客户模板已移除")


@router.get("/reports/template/status")
async def report_template_status(
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查当前报告模板状态：已上传（客户模板）还是缺位（系统自建模板）。"""
    uploaded = _uploaded_template()
    if uploaded:
        p = Path(uploaded)
        st = p.stat()
        return success_response(data={
            "ready": True,
            "filename": p.name,
            "bytes": st.st_size,
            "uploaded_at": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
            "note": "客户模板已就位，生成报告为正式报告。",
        })
    return success_response(data={
        "ready": False,
        "note": "未上传客户模板，生成报告走系统自建模板（可替换）。",
    })
