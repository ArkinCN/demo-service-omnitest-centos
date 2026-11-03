# 七份既有产物 Schema

来源：原交付目录 `01-设计规格-信息架构与页面.md` 第 15 节，提取于 2026-09-21。JSON 内容保留原义，只统一缩进。原文件 SHA-256：`8300707b0f16f2958601ac5623f705b8114ccb0ebfb2866f35d2239726014a20`。

这七份描述配置、需求基线、已完成轮次、判定表、缺口、参数变更和报告产物。不是实时业务数据库模型，也不是已实现 API。旧枚举与新版 missing/manual/error 的映射须实现显式转换；不兼容时出 schema 新版本并迁移，禁止伪造字段满足校验。场景包 12 份 Schema 与两阶段校验器继续使用仓库 docs/08b-场景包契约，不被这七份替代。

文件清单：

- `config-snapshot.schema.json`
- `requirement-baseline.schema.json`
- `run-artifact.schema.json`
- `verdict-table.schema.json`
- `gap-list.schema.json`
- `param-change.schema.json`
- `report-instance.schema.json`
