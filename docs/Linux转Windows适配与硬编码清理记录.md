# Linux 转 Windows 适配与硬编码清理记录

**执行日期**：2026-09-23
**执行范围**：`c/` 全仓库（后端 FastAPI + 前端 React + 知识库流水线 + 场景包 + 文档）
**依据**：用户指令「这个项目没有 linux，全都是 win 的全改，禁止写硬编码，做完要有书面记录」
**验收口径**：Q1 全仓彻底清 / Q2 相对路径（禁盘符）/ Q3 `.sh` 改 `.py` / Q4 全配置不硬编码

---

## 一、结论摘要

| 项 | 结果 |
|---|---|
| Linux 绝对路径（`/mnt`、`/home`、`~/`） | **已清零**（唯一例外见 §5 豁免清单） |
| 场景包 `file_path` | **6 条 cop+generated 全部合规**、2 条 registered_only 已脱敏 |
| 硬编码端口 / 路径根 | **已外置**到 `.env`，新增统一路径入口 `core/paths.py` |
| `.sh` 脚本 | **5 个全部改为 `.py`**，原 `.sh` 已删除 |
| 完整性自检 | **通过**（232 个 .py 语法零错、759 文件全 UTF-8、27 场景 JSON 可解析） |
| 前端构建 | **通过**（`npm run build` 退出码 0） |
| 场景包路径校验 | **通过**（`verify_scene_paths.py` 退出码 0） |

---

## 二、改动清单

### 2.1 新增文件

| 文件 | 作用 |
|---|---|
| `c/backend/app/core/paths.py` | **全后端唯一路径入口**：项目根推导 + `.env` 覆盖；导出 `scenes_dir()` / `kb_data_dir()` / `data_dir()` |
| `c/backend/scripts/clean_linux_paths.py` | 批量清洗工具（`scan` / `fix [--dry-run]` / `verify` 三合一，内置 `/assets/` 断言、UTF-8 无 BOM、幂等） |
| `c/backend/scripts/verify_scene_paths.py` | 场景包路径合规校验（按 `mode` 分别断言，与前端消费逻辑逐条对齐） |
| `c/backend/scripts/check_integrity.py` | 改造后完整性自检（语法 / 编码 / 关键文件 / JSON 四查） |
| `c/backend/scripts/clean_legacy_repo_refs.py` | 清理旧仓库名（`~/agent-test-web` 等）的历史引用 |
| `c/backend/scripts/fix_over_sanitized.py` | 修复前两轮清洗过度造成的文档损坏 |
| `c/kb-pipeline/scripts/run_all.py` | 知识库流水线全量重跑（替代 `run_all.sh`） |
| `c/backend/scripts/deploy_frontend.py` | 前端零停机部署（替代 `deploy_frontend.sh`） |
| `c/components/spike-device-mcp/run_bridge.py` | 设备桥重启（替代 `run-bridge.sh`） |
| `c/components/spike-device-mcp/run_mcp_http.py` | MCP streamable-http 启动（替代 `run-mcp-http.sh`） |
| `c/components/spike-device-mcp/run_evidence.py` | 设备桥取证（替代 `run-evidence.sh`） |
| `c/docs/Linux转Windows适配与硬编码清理记录.md` | 本文件 |

### 2.2 修改文件（要点）

| 文件 | 改动 |
|---|---|
| `c/backend/app/core/config.py` | 新增 `BACKEND_HOST` / `BACKEND_PORT` / `WEB_PORT` / `SCENES_DIR` / `KB_DATA_DIR` / `DATA_DIR` 六项外置配置；默认上游注释补充 OpenRouter 注意事项 |
| `c/backend/app/services/kb_search.py` | 路径改走 `app.core.paths.kb_data_dir()`，删除自行拼目录的代码 |
| `c/kb-pipeline/scripts/common.py` | `KB_OUT` 由 Linux 绝对路径改为「脚本位置推导 + `.env` 可覆盖」，默认指向前端 `public/kb` |
| `c/backend/.env.example` | 补齐新增外置项与注释 |
| `c/web/public/scenes/**/*.json` | `file_path` 等字段：Linux 绝对路径 → `./assets/...` 或脱敏标记 |
| `c/docs/**`、`c/web/README.md`、`CHANGELOG-*.md` | 文档中的主机路径改为仓库相对描述 |

### 2.3 删除文件

`c/kb-pipeline/scripts/run_all.sh`、`c/backend/scripts/deploy_frontend.sh`、
`c/components/spike-device-mcp/run-bridge.sh`、`run-evidence.sh`、`run-mcp-http.sh`

---

## 三、原有 Linux 路径分布（清洗前统计）

| 载体 | 命中处数 | 典型形态 |
|---|---:|---|
| `c/web/public/scenes/**/*.json` | **约 700** | `file_path: "/mnt/f/Main/File/2_Projects/.../assets/xxx.csv"` |
| `c/data/scenes/**/*.json`（场景包源副本） | 约 700 | 同上 |
| `c/data/kb/**`、`c/web/public/kb/**` | 约 90 | `_source.file` 溯源字段 |
| `c/docs/**/*.md` | 约 900 | 文档里的路径引用、命令示例 |
| `c/**/*.py` 代码常量 | 约 30 | `KB_OUT = "/mnt/..."`、`WBW_MAIN = os.path.join(REPO, ...)` |
| `c/web/src/**` 注释 | 约 20 | 文件头「源目录：…」 |
| `.sh` 脚本内部 | 约 20 | `#!/usr/bin/env`、`~/lab/...` |
| **合计** | **约 2500+** | —— |

> 说明：数字为按载体分类的命中统计，含同一路径在多个文件中重复登记的情况。

---

## 四、转换后的相对路径规范

### 4.1 三条规则

| # | 场景 | 规则 | 示例 |
|---|---|---|---|
| **1** | 运行时资源（前端要 fetch） | **`./assets/<rel>`，必须保留 `/assets/` 分隔符** | `/mnt/.../scene/assets/waveforms/a.csv` → `./assets/waveforms/a.csv` |
| **2** | 配置常量（代码里） | 脚本位置推导 + `.env` 可覆盖 | `"/home/zzz/out"` → `Path(os.environ.get("KB_OUT", BASE/"out"))` |
| **3** | 溯源记录（`_source` 等） | 脱敏为 `[源] <末两段>` | `/mnt/f/.../FU-AM-FOC方案调试手册-.pdf` → `[源] 调试经验文档/FU-AM-FOC方案调试手册-.pdf` |

### 4.2 为什么必须保留 `/assets/`

前端两处消费 `file_path`：

```150:152:c/web/src/features/waveforms/index.ts
      const rel = d.file_path.split('/assets/')[1]
      if (!rel) continue
      const r = await loadCsv(`${pack.base}assets/${rel}`, { timeColumn: 'time_s' })
```

```84:84:c/web/src/features/scene/workflows.ts
      assetPath: w.file_path.split('/assets/')[1] ? `assets/${w.file_path.split('/assets/')[1]}` : '',
```

改成 `./assets/waveforms/a.csv` 后，`split('/assets/')[1]` 仍得 `waveforms/a.csv`，**拼接结果不变**。
若改成含盘符的绝对路径，切分逻辑立即报废，波形不再加载。

**防护机制**：清洗脚本内置断言——原值含 `/assets/` 而新值不含时，**拒绝写入并报错**，不静默改坏。

### 4.3 两类 `file_path` 的区别（重要）

场景包 `datasets[]` 有两种 `mode`，处理方式**不同**：

| mode | 文件位置 | 前端行为 | 本次处理 |
|---|---|---|---|
| `copied_into_pack` | 真在 `assets/` 下 | `split('/assets/')[1]` 加载 | → `./assets/...` |
| `registered_only` | 在客户工程别处，**不在包内** | `if (!rel) continue` **跳过** | → `[源] ...`（不含 `/assets/`） |

对 `registered_only` 也硬套 `/assets/` 断言会误报——这是实施中修正过的一个判断。

---

## 五、`.sh` → `.py` 对照表

| 原脚本 | 新脚本 | 关键差异与说明 |
|---|---|---|
| `c/kb-pipeline/scripts/run_all.sh` | `run_all.py` | 步骤顺序不变（02 先于 01）；`sys.executable` 替代写死的 `.venv/bin/python`（Windows 解释器在 `Scripts/`） |
| `c/backend/scripts/deploy_frontend.sh` | `deploy_frontend.py` | Windows 无 `ln -sfn` → 优先 symlink、失败退**目录联接（junction）**、再退整份复制（日志会明示非原子） |
| `c/components/spike-device-mcp/run-bridge.sh` | `run_bridge.py` | `setsid`/`nohup` → `DETACHED_PROCESS`；`kill -0` → `tasklist` 查存活；`. ./.env` → 内置解析器 |
| `c/components/spike-device-mcp/run-evidence.sh` | `run_evidence.py` | 四段取证流程与产物文件名**逐一对应**，便于与既往记录对照 |
| `c/components/spike-device-mcp/run-mcp-http.sh` | `run_mcp_http.py` | 同上；端口仍走 `MCP_HTTP_PORT` |

**共性处理**：参数、步骤顺序、日志格式、退出码语义与原 bash 版保持一致；写文件统一 UTF-8 无 BOM。

---

## 六、配置外置清单（Q4）

| 配置项 | 原状态 | 现状态 |
|---|---|---|
| `BACKEND_HOST` / `BACKEND_PORT` | 写死在启动命令与文档 | `.env`，`core/config.py` 有默认 8011 |
| `WEB_PORT` | 写死在文档 | `.env`，默认 5173 |
| `SCENES_DIR` / `KB_DATA_DIR` / `DATA_DIR` | 各处自行拼路径 | `.env` 可覆盖，缺省由 `core/paths.py` 推导 |
| `KB_OUT`（流水线输出） | Linux 绝对路径 | `common.py` 推导 + `.env` 可覆盖 |
| `MOTORDEBUG_LLM_*` | 已外置 | 保持（上游已切 OpenRouter） |
| `KB_SEARCH_TIMEOUT` 等超时 | 已在 `.env` | 保持 |

**「缺必填项直接启动报错」**：由 pydantic-settings 承担——`SECRET_KEY`、`JWT_SECRET_KEY`、`DATABASE_URL`、LDAP 四项均为 `Field(...)` 无默认值，缺失时 `settings` 实例化即抛 `ValidationError`，进程启动中断。

**禁止硬编码的具体禁令**（已写入代码注释，供后续维护者遵守）：
1. 不出现盘符（`D:\`）与用户名（`/home/<user>`、`~/`）；
2. 不出现 Linux 绝对根（`/mnt`、`/opt` 等）；
3. 路径一律由 `core/paths.py` 或其等效推导给出；
4. 端口、超时、模型名、限额一律走 `.env`。

---

## 七、豁免清单（保留的 14 处，附理由）

| 处数 | 形态 | 保留理由 |
|---:|---|---|
| 12 | `#!/usr/bin/env python3` | **跨平台惯例**。Python shebang 在 Windows 下被忽略，`python xxx.py` 照常执行；删掉反而失去类 Unix 环境下的可执行性 |
| 1 | `tests/test_skill_expansion.py` 的 `"../etc/passwd"` | **路径穿越安全测试的用例数据**。删改会破坏测试意图（该用例断言此类路径被规范化拦截） |
| 1 | `fix_over_sanitized.py` 内的 `[源]` 检测模式 | 脚本事后复检用的**匹配模式**，非真实路径 |

---

## 八、验证记录（Windows 本机实跑）

| # | 验证项 | 命令 | 结果 |
|---|---|---|---|
| 1 | 完整性自检 | `python scripts/check_integrity.py` | **通过**：232 个 .py 语法零错；759 文件全 UTF-8；10 个关键文件齐备；27 个场景 JSON 可解析 |
| 2 | 场景包路径合规 | `python scripts/verify_scene_paths.py` | **通过**：copied/generated 6 条、registered_only 2 条，全部合规 |
| 3 | 残留复扫 | `python scripts/clean_linux_paths.py verify` | 剩余 14 处，**全部为 §7 豁免项** |
| 4 | 前端构建 | `cd c/web && npm run build` | **通过**，退出码 0 |
| 5 | 路径解析 | `python -c "from app.core.paths import resolved; ..."` | 场景包 `c\web\public\scenes`、知识库 `c\web\public\kb` 均存在 |

### 未在本轮执行、需接管者补验
- ~~**后端启动**与**助手链路实跑**~~ → **已于 §8.1 完成端到端验证**

### 8.1 端到端验证（2026-09-23 补测，Windows 本机实跑）

改造后重启后端，逐项实测核心链路：

| # | 验证项 | 方法 | 结果 |
|---|---|---|---|
| 1 | **后端启动** | `uvicorn app.main:app --port 8011` | **成功**：`Database tables created`、seed 全过、`Application startup complete` |
| 2 | **健康检查** | `GET /health` | `{"status":"healthy"}` |
| 3 | **知识库检索**（依赖 `paths.py`） | `POST /api/kb/search {"query":"FG 输出配置","k":3}` | **200**，命中 3 条宏名（`ROTATE_SIGNAL_TYPE` / `FG_PULSE_PERIOD` / `FG_INITIAL_DELAY_TIMES`），`hit_docs:["customer-h-fu6832"]` |
| 4 | **场景包静态资源** | `GET /scenes/index.json`、`scene.json`、波形 CSV | 全部 **200** |
| 5 | **资源可达性（模拟前端拼路径）** | `scripts/e2e_verify.py`，复刻 `split('/assets/')[1]` 后实际请求 | **10 个资源全部可达**：玻璃升降器 3 条波形、散热风扇 3 条波形均 200；2 条 `registered_only` 正确跳过 |
| 6 | **助手 SSE 链路** | `POST /api/agent/stream`（经 vite 代理→后端→OpenRouter） | **通**：事件序列 `message_delta × 10 → done`，共 11 个事件 |
| 7 | **运行时路径解析** | `from app.core.paths import resolved` | 场景包 `c\web\public\scenes`（3 子目录）、知识库 `c\web\public\kb`（14 documents）均存在 |

**第 5 项是最关键的一条**：它证明 `file_path` 从 Linux 绝对路径改为 `./assets/...` 之后，
前端的 `split('/assets/')[1]` 仍然成立，**波形加载没有断**——这是本次改造风险最高的点。

验证脚本已落盘，可重复执行：
```bash
cd c/backend
python scripts/e2e_verify.py          # 默认打前端 5173
```

---

## 九、实施过程记录（含两次自我纠错）

为确保接管者理解「为什么是现在这个样子」，记录两次已修复的自身失误：

1. **清洗工具改坏了自己的正则**。首轮 `fix` 扫描范围包含本工具自身，把它 Python 源码里的 `"/mnt/|/home/"` 正则替换成了 `[源]`，导致后续扫描失效。
   **修正**：`NEVER_TOUCH` 加入 `Path(__file__)` 自排除。
   **教训**：清洗工具必须把自己排除在扫描范围外。

2. **文档被过度脱敏**。`~/lab/agent-test-web/c` 叠加两条规则后产出 `[源] [源] c`，使文档里 `cd [源] [源] c` 成为**不可执行的命令**。
   **修正**：`fix_over_sanitized.py` 按语义还原为仓库相对路径（如 `cd c/web`），修 70 个文件、471 处。
   **教训**：**文档里的路径是给人看的描述，脱敏到「不可读」就失去了文档的价值**；替换规则要区分「运行时数据」与「叙述性文本」。

---

## 十、后续维护指引

1. **新增运行时路径**：一律加到 `c/backend/app/core/paths.py`，不要在业务代码里拼。
2. **新增配置项**：加到 `core/config.py` 并同步 `.env.example`；必填项用 `Field(...)`。
3. **新增脚本**：写 `.py`，不写 `.sh`；路径用 `pathlib`，不用字符串拼接。
4. **改场景包路径**：改完必须跑 `python scripts/verify_scene_paths.py`。
5. **改完任何一批文件后**：跑 `python scripts/check_integrity.py` 与 `cd c/web && npm run build`。
6. **复查残留**：`python scripts/clean_linux_paths.py verify`，出现 §7 之外的新命中即视为回归。
