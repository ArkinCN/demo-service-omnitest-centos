# kb-pipeline — 峰岹散热风扇知识库转化流水线

把客户交付的手册、数据手册、工程源码，转成前端「知识库管理」页可直接加载的结构化知识；
另从 98 次启动实验数据包与客户随装规程提炼经验条目。

- 输出目录：`c-data/kb`（可用环境变量 `KB_OUT` 覆盖）
- 源材料**只读**：先复制到 `input/`，再在副本上转换。

## 跑起来

```bash
cd c/components/kb-pipeline
uv venv --python 3.10 .venv
VIRTUAL_ENV=$PWD/.venv UV_DEFAULT_INDEX=https://pypi.org/simple \
  uv pip install docling==2.129.0 rank_bm25 pymupdf4llm --torch-backend=cpu
bash scripts/run_all.sh              # 全量
bash scripts/run_all.sh foc-debug-manual   # 只重转某几份文档
```

首次运行 Docling 会下载一次版面与表格模型到本地缓存，之后完全离线。

注意：本机默认 pip 源（清华镜像）对上述包返回 403，必须显式指定 `UV_DEFAULT_INDEX=https://pypi.org/simple`。

## 目录

```
config/registry.json    文档清单：doc-id、标题、类型、用途流程标签、裁页设置
input/                  源材料副本（.gitignore 排除）
scripts/
  common.py             路径、三级分类、sha256、token 估算
  entities.py           实体抽取的正则与启发式
  01_convert_docs.py    Docling 转换 + 层级切片 + 抽图 + 实体抽取
  02_parse_customer_h.py  Customer.h → params.json
  03_build_index.py     documents/index.json
  04_search.py          BM25 离线检索 + 示例查询
  05_build_experience.py  经验条目
  06_build_taxonomy.py  经验分类体系与沉淀模板
  07_write_readme.py    按实际产物生成 kb/README.md
  run_all.sh
work/                   裁页中间件与转换报告（.gitignore 排除）
```

产物含义与选型理由见生成出来的 `kb/README.md`。
