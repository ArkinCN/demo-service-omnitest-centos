"""全后端**唯一**的路径入口。

为什么要有这个文件：此前各处自行拼路径（`Path(__file__).parents[N] / ...` 散落
在 services、scripts、路由里），一旦目录层级调整就要逐处改，而且容易出现
Linux 绝对路径或写死盘符——那是不可交付的（Windows 盘符在不同机器上会变）。

本模块的三条纪律：
1. **不出现盘符、不出现用户名**：全部由本文件位置向上推导项目根，再相对拼接。
2. **环境变量优先**：部署方可用 `.env` 覆盖任一数据根（例如把知识库放到 D 盘某目录），
   不必改代码。
3. **目录不存在就地抛出**：宁可启动即失败，也不要让上层拿着不存在的路径去 diff、
   去 glob，最后报一个跟根因无关的错。

导出清单：
    PROJECT_ROOT   仓库根（含 c/ 的那一级）
    C_DIR          前端/后端所在的那一级（c/）
    BACKEND_DIR    c/backend
    WEB_DIR        c/web
    PUBLIC_DIR     c/web/public（前端运行时静态资源根）
    SCENES_DIR     场景包根
    KB_DATA_DIR    知识库流水线产物根
    DATA_DIR       前端 data/ 根
    kb_uploads_dir()   上传原件根（运行期数据）
    kb_vector_dir()    向量索引落盘根（运行期数据，可重建）
    kb_pipeline_dir()  kb-pipeline 目录（隔离 venv 所在）
    kb_pipeline_python()  kb-pipeline 的 venv 解释器
    builtin_report_template()  系统内置报告模板（随代码交付的 .xlsm 资产）
"""
from __future__ import annotations

import os
from pathlib import Path

# ── 项目根推导 ──
# 本文件位置：<repo>/c/backend/app/core/paths.py
#   parents[0]=core  [1]=app  [2]=backend  [3]=c  [4]=<repo>
CORE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = CORE_DIR.parents[1]          # c/backend
C_DIR = CORE_DIR.parents[2]                # c
PROJECT_ROOT = CORE_DIR.parents[3]         # 仓库根
WEB_DIR = C_DIR / "web"
PUBLIC_DIR = WEB_DIR / "public"
APP_DIR = CORE_DIR.parent                 # c/backend/app
APP_DATA_DIR = APP_DIR / "data"           # 随代码交付的数据资产（如 safety_keywords.json）


def env_path(key: str, default: Path) -> Path:
    """取路径：`.env`（经 settings）优先，其次系统环境变量，最后仓库相对推导。

    严禁把绝对路径写成常量：绝对路径在本机能跑、换台机器就失效。

    注意这里**同时**看 settings 与 os.environ：settings 走 .env 文件，
    os.environ 走进程环境；两者都算「外置」，先 .env（部署方更常改它）。
    为避免与 config 循环导入，settings 采用函数内延迟导入。
    """
    raw = ""
    try:
        from app.core.config import settings  # 延迟导入：paths 被 config 间接依赖

        raw = (getattr(settings, key, "") or "").strip()
    except Exception:
        # config 尚未就绪（例如被 scripts 单独导入）时静默回落环境变量
        raw = ""
    if not raw:
        raw = (os.environ.get(key) or "").strip()
    if not raw:
        return default
    # 相对值按项目根解析，绝对值原样用（部署方显式指定时由他负责）
    p = Path(raw)
    return p if p.is_absolute() else (PROJECT_ROOT / p)


# ── 三个运行时数据根 ──
#
# 刻意做成**函数**而不是模块级常量：模块级求值发生在 import 时，那一刻 .env
# 可能尚未被 settings 读到（settings 自身也 import 本模块），会拿到空值。
# 函数式访问保证「用的时候才解析」，且每次拿到的是最新配置。
def scenes_dir() -> Path:
    """场景包根。.env 的 SCENES_DIR 可覆盖，留空用 public/scenes。"""
    return env_path("SCENES_DIR", PUBLIC_DIR / "scenes")


def kb_data_dir() -> Path:
    """知识库流水线产物根。.env 的 KB_DATA_DIR 可覆盖，留空用 public/kb。"""
    return env_path("KB_DATA_DIR", PUBLIC_DIR / "kb")


def data_dir() -> Path:
    """前端 data/ 根。.env 的 DATA_DIR 可覆盖，留空用 public/data。"""
    return env_path("DATA_DIR", PUBLIC_DIR / "data")


def kb_uploads_dir() -> Path:
    """知识库上传原件的存放根。.env 的 KB_UPLOADS_DIR 可覆盖。

    与 kb_data_dir()（**产物**，前端 fetch 的 public/kb）刻意分开：
    这里是**原件**，属于运行期数据、不进交付包，也不该混进前端静态目录——
    混在一起会导致「产物目录里出现用户上传的 pdf」这种状态。
    默认放 backend/uploads/kb/（与项目既有的 uploads/avatars 同一层级口径）。
    """
    return env_path("KB_UPLOADS_DIR", BACKEND_DIR / "uploads" / "kb")


def reports_dir() -> Path:
    """报告产物（生成的 xlsm / 占位报告）的存放根。.env 的 REPORTS_DIR 可覆盖。

    与 kb_uploads_dir() 同属**运行期数据**：报告是跑出来的、不进交付包，
    也不该混进前端静态目录。默认放 backend/uploads/reports/。
    """
    return env_path("REPORTS_DIR", BACKEND_DIR / "uploads" / "reports")


def report_templates_dir() -> Path:
    """客户报告模板（.xlsm）的存放根。.env 的 REPORT_TEMPLATES_DIR 可覆盖。

    用户通过报告页「上传模板文件」把客户正式模板放进来；上传后生成报告走
    真模板（write-file-rust），未上传时用系统自建模板。默认放 backend/uploads/report_templates/。
    """
    return env_path("REPORT_TEMPLATES_DIR", BACKEND_DIR / "uploads" / "report_templates")


def builtin_report_template() -> Path:
    """系统内置报告模板（.xlsm）。.env 的 BUILTIN_REPORT_TEMPLATE 可覆盖。

    与 report_templates_dir() **严格分开**：两者语义与生命周期都不同。
      · report_templates_dir() —— **用户上传**的客户模板，属运行期数据（uploads/，不进交付包）；
      · 本函数 —— **随代码交付**的正式报告模板资产（app/data/，跟着版本控制走）。

    ⚠️ 为什么必须分开（2026-10-13 引入内置模板后尤其要紧）：上传目录里只要出现
    任何 .xlsm，`_uploaded_template()` 就会命中，把生成切到「客户模板 +
    write-file-rust」通路（本部署没有该 exe 时会如实 blocked）。若把内置模板塞进
    上传目录，等于每次生成都被判成「用户上传了模板」——那条通路永远走不通。

    默认 `backend/app/data/report_templates/测试报告模板-v1.xlsm`。
    调用方**必须自行校验存在性**并如实报错（「模板未就绪」），本函数不抛目录错误。
    """
    return env_path(
        "BUILTIN_REPORT_TEMPLATE",
        APP_DATA_DIR / "report_templates" / "测试报告模板-v1.xlsm",
    )


def kb_extract_dir() -> Path:
    """知识库**抽取稿**根目录（`<doc_id>/content.md` 所在处）。

    为什么单独一个入口：这里的 content.md 是 docling 抽出来的 Markdown 正文，
    当初**刻意没发布到前端 public/**（见 `features/scene/kb.ts` 的说明：前端只要
    切片与参数表，排除 content.md/figures 大图）。但「点源文件看内容」这个需求
    要读全文，只能由后端读这个数据目录再回给前端。.env 的 KB_EXTRACT_DIR 可覆盖。
    默认 `c/data/kb/documents`（数据侧，相对项目根推导，不写盘符）。
    """
    return env_path("KB_EXTRACT_DIR", C_DIR / "data" / "kb" / "documents")


def kb_vector_dir() -> Path:
    """向量索引落盘目录（阶段 3 补全新增）。

    .env 的 KB_VECTOR_DIR 可覆盖。默认放 backend/uploads/kb_vector/：
    与 kb_uploads_dir()（上传原件）同级，同属**运行期数据**——
    它不是交付内容，也不该混进前端 public/（那是静态资源根）。
    向量索引可以随时由 /kb/vector/rebuild 重建，所以不进版本控制。
    """
    return env_path("KB_VECTOR_DIR", BACKEND_DIR / "uploads" / "kb_vector")


def kb_pipeline_dir() -> Path:
    """kb-pipeline 目录（隔离 venv 所在处）。

    为什么收进这里：后端要子进程调它的 venv 解释器跑 docling 与向量化
    （见 kb_convert_service / kb_embed_service）。此前这个路径硬编码在
    kb_convert_service 里，现在向量一路也要用**同一个**路径——
    两处各写一遍迟早会分叉，收成一个入口。
    """
    return C_DIR / "kb-pipeline"


def kb_pipeline_python() -> Path:
    """kb-pipeline 隔离 venv 的解释器。Windows 是 Scripts/python.exe。

    这个文件**必须存在**才能跑 docling 与向量化；调用方每次使用前校验，
    缺失时明确报「环境未就绪」而不是让子进程抛一个看不懂的 FileNotFoundError。
    """
    return kb_pipeline_dir() / ".venv" / "Scripts" / "python.exe"


def require_dir(p: Path, what: str) -> Path:
    """取一个必须存在的目录；不存在就抛，附上排查提示。

    「取不到就停下来」比「带病继续」好：上层拿到空目录往往会静默产出空结果，
    把真正的配置问题伪装成业务问题。
    """
    if not p.is_dir():
        raise FileNotFoundError(
            f"{what} 不存在：{p}\n"
            f"  排查：① 确认已在前端 public/ 下生成该目录；"
            f"② 或用环境变量覆盖（SCENES_DIR / KB_DATA_DIR / DATA_DIR）。"
        )
    return p


def resolved() -> dict[str, str]:
    """给启动日志用的一览表（脱敏后只含仓库内相对路径）。"""
    def rel(p: Path) -> str:
        try:
            return str(p.relative_to(PROJECT_ROOT))
        except ValueError:
            return str(p)

    return {
        "项目根": rel(PROJECT_ROOT),
        "前端目录": rel(WEB_DIR),
        "场景包": rel(scenes_dir()),
        "知识库": rel(kb_data_dir()),
        "前端数据": rel(data_dir()),
        "上传原件": rel(kb_uploads_dir()),
        "报告产物": rel(reports_dir()),
        "内置报告模板": rel(builtin_report_template()),
    }
