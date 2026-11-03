# 散热风扇知识库（motor › cooling-fan › fortior-fu6832）

本目录是「文档 → 可用知识」转化流水线的产物，供前端「知识库管理」页直接加载。
生成脚本在 `[源] kb-pipeline/scripts`，一条命令全量重跑：`bash scripts/run_all.sh`。
源材料一律只读，复制到 `[源] kb-pipeline/input` 后再转换，原始目录未改动。

## 一、目录与文件含义

```
kb/
├── documents/                     文档性质知识
│   ├── index.json                 全部文档条目：三级分类、类型、流程标签、转化状态、切片数
│   ├── <doc-id>/source.json       标题 / 类型 / 页数 / 来源路径 / sha256
│   ├── <doc-id>/content.md        全文 markdown（表格保留为 markdown 表）
│   ├── <doc-id>/chunks.jsonl      按标题层级切片，每片 id / heading_path / text / page / tokens
│   ├── <doc-id>/entities.json     正则+启发式抽出的参数名、阈值、单位、寄存器名、规程步骤
│   ├── <doc-id>/figures/          抽出的图片，每份文档最多 20 张
│   └── customer-h-fu6832/params.json   Customer.h 结构化参数表（不走 markdown 切片）
├── experience/
│   ├── index.json                 经验条目
│   └── taxonomy.json              经验分类体系三维度 + 一键沉淀字段模板
├── search-samples.json            5 条示例查询的 BM25 检索结果
└── README.md                      本文件
```

## 二、文档转化工具选型

候选五个，查了 PyPI 最近发布时间后选 **Docling 2.129.0**（IBM Research，Apache-2.0）。

| 候选 | 最新版 / 发布日 | 取舍 |
|---|---|---|
| Docling | 2.129.0 / 2026-09-18 | **选它**。PDF 与 DOCX 同一套 API；表格走 TableFormer 结构模型而不是靠版面猜；导出 markdown 自带标题层级，配套 HierarchicalChunker 直接给出 heading_path 与页码 provenance；扫描件可切 RapidOCR（自带中文模型）；模型一次下载后完全离线。 |
| MinerU | 4.0.3 / 2026-09-18 | 中文 PDF 质量同样好，但默认依赖更重的版面与公式模型，本原型不需要公式识别。 |
| marker-pdf | 2.0.0 / 2026-07-20 | 依赖 surya 系列模型，CPU 上慢；且不处理 DOCX，本批 4 份 docx 要另接一条链路。 |
| unstructured | 0.27.6 / 2026-09-14 | 直接出局：要求 Python ≥ 3.11，本机是 3.10。 |
| pymupdf4llm | 1.28.2 / 2026-08-06 | 纯 Python、最快、零模型，但表格靠几何启发式，中文合并单元格容易串行；不处理 DOCX。本流水线仍装了它，只用它的底层 PyMuPDF 做**裁页**和**抽图**。 |

离线性：Docling 首次运行会拉一次版面与表格模型到本地缓存（docling-layout-heron 164 MB、
TableFormer fast 139 MB），之后设 `HF_HUB_OFFLINE=1` 即可完全断网跑。转换过程不调用任何大模型。

表格档位取的是 TableFormer **fast**，不是 accurate：本机到 HuggingFace 的连接反复断流，
accurate 权重（203 MB）多次下载不全，fast 档同属 TableFormer 结构模型（不是几何启发式），
够这批手册用。网络条件好时设 `TABLEFORMER_MODE=ACCURATE` 即可切档。

OCR 按需开：每份 PDF 先量前 5 页平均可抽字符数，低于 120 就判为图片型（PPT 导出或扫描件），
走 RapidOCR 的中文模型；有文字层的不开 OCR，既省时也避免重复抽取。本批 3 份走了 OCR。

## 三、每一步在做什么

| 脚本 | 输入 | 输出 |
|---|---|---|
| `02_parse_customer_h.py` | `input/code/Customer.h` | `documents/customer-h-fu6832/params.json` |
| `01_convert_docs.py` | `input/manuals/*`、`input/datasheet/*` | 每份文档的 `source.json` / `content.md` / `chunks.jsonl` / `entities.json` / `figures/` |
| `03_build_index.py` | 上面的产物 | `documents/index.json` |
| `04_search.py` | 全部切片 + 全部宏 | `search-samples.json` |
| `05_build_experience.py` | 98 次启动实验数据包、客户随装规程 | `experience/index.json` |
| `06_build_taxonomy.py` | —（设计产物） | `experience/taxonomy.json` |

先跑 `02` 再跑 `01` 是有意的：文档实体抽取会拿 Customer.h 的宏名表去比对，`entities.json`
里 `in_customer_h=true` 的参数就是「手册里讲到、且工程里真的有这个宏」的交集。

## 四、Customer.h 的转化示范

`params.json` 把 203 条 `#define` 拆成前端可直接渲染的字段：

- `value` / `raw_value` / `wrapper`：`_Q15(0.06)` 拆成数值 0.06 与外壳 `_Q15`。改值时外壳要原样写回，这是客户规程的硬纪律。
- `range`：从行尾注释 `[範圍: 0.01 ~ 0.4]` 解析出上下限，43 条有范围——正好喂左侧「加减号调数值」控件的边界。
- `unit`：从 `(單位: mS)` 解析，72 条有单位。
- `group.l1 / group.l2`：来自文件里的 Doxygen `@defgroup` 与 `@brief` 注释，6 个一级分组。
- `editable`：数值宏 164 条可直接调；其余是枚举、宏引用或表达式，要用下拉或只读呈现。

## 五、检索

`04_search.py` 提供 `KnowledgeSearch().search(query, k)`，引擎是 rank_bm25 的 BM25Okapi。
中文按「单字 + 相邻两字」切分，英文和宏名按小写词元并额外拆下划线段，
所以查「FG 输出配置」能同时命中中文段落和 `ROTATE_SIGNAL_TYPE` 一类宏。全程离线、无分词模型。

已知短板：纯中文词查纯英文宏名要靠手册段落搭桥。Customer.h 里没有中文注释的宏
（例如 `Pole_Pairs`）不会被「极对数」直接命中，这类查询目前由手册切片承接。

当库用（文件名以数字打头，要走 importlib）：

```python
import sys, importlib.util
spec = importlib.util.spec_from_file_location("kb_search", "scripts/04_search.py")
kb = importlib.util.module_from_spec(spec); sys.modules["kb_search"] = kb
spec.loader.exec_module(kb)
hits = kb.KnowledgeSearch().search("预定位强度 DOUT", k=5)
```

语料 577 个检索单元（文档切片 374 + Customer.h 宏 203）。
5 条示例查询的结果在 `search-samples.json`，每条结果带 `doc_id`、`page`、`heading_path` 与原文片段，
可以回指到具体页码。向量检索按要求只留接口未实现（`VectorIndex`）。

## 六、经验知识

`experience/index.json` 共 38 条：实验沉淀 30 条、规程沉淀 8 条、对话沉淀 0 条。

`experience/taxonomy.json` 给的分类体系是三个正交维度，一条经验在每个维度上取且只取一个值：

1. **所属流程**（6 值）：对应系统顶部六个典型流程，是检索主入口。
2. **问题类型**（6 值）：按现象归类而不是按根因归类，因为现场先看到的是现象。
3. **沉淀方式**（3 值）：实验 / 规程 / 对话，决定这条经验的证据强度与可核验路径。

同一份文件里还给了「从对话一键沉淀为经验」的字段模板：哪些字段自动填、哪些必须人工确认、
草稿何时才升级为可检索条目、以及同一 (产品, 参数, 故障类型) 下如何并条而不是重复沉淀。

## 七、哪些是示例、哪些是真数据

真数据：

- 登记的 12 份文档全部来自客户交付的原始 PDF / DOCX，12 份全部转化成功，
  每份的 `source.json` 里有 sha256 可核对。
- `params.json` 的 203 条宏是 Customer.h 的逐行解析结果。
- 30 条实验沉淀逐条回指 98 次启动实验数据包里的 attempt 目录、波形 CSV 与诊断报告。
- 8 条规程沉淀逐条回指客户软件随装规程 `coolingfan-openloop-debug/SKILL.md` 的现象分诊表。

是示例、不要当结论用：

- FU6832 数据手册只转了前 40 页（源文件 18 MB、共 296 页，本原型演示用）。
  **这 40 页几乎全是目录与引脚说明**，电气参数表在更后面，所以它的 `entities.json` 里
  抽出的 344 个标识符大多是目录里的寄存器条目名，阈值条数为 0。
  要拿真正的电气参数表，改 `config/registry.json` 里这条的 `page_limit` 或改成取后段页码再跑。
- `smo-angle-register-note`（SMO 角度估算的原理介绍和部分寄存器说明.docx）转得出来但**极慢**：
  docling 的 msword 后端处理它的 VML 旧式图形实测要 651 秒，其余 docx 都在 1 秒内完成。
  跑这份时 `DOC_TIMEOUT_S` 不要低于 900，否则会被子进程超时兜底记为失败。
- 30 条实验沉淀的 `result.status` 全是「未验证」：数据包只采了故障态，没有把修复值回灌重测。
- 30 条实验沉淀共用同一个注入故障（预定位强度过弱），条目之间的差别在实测波形特征，不在根因；
  这批数据没有正常样本，能测检出率，测不了误报率。
- 文档的 `process_tags`（用途流程标签）是按文档内容人工指派的，不是客户确认过的口径。
- 经验条目的 `confidence` 中，实验沉淀取自判定工具的打分，规程沉淀统一记 0.6 表示「规程约定、未实测」。
