# 场景包：电机 / 散热风扇 / FU6832 散热风扇驱动板

场景 id：`motor.cooling-fan.fortior-fu6832`
生成日期：2026-09-19
生成方式：`python3 _build/build_scene_pack.py`（脚本只读源材料，不写回源材料）

这是给「通用 Agent 测试系统 v2.0」网页原型用的一份**真实数据**场景包。六个流程（知识库管理、初始化配置、测试需求确认、启动测试及结果分析、调优确认及运行、测试报告及产出）需要的结构化数据，全部整理成前端可直接 `fetch` 的 JSON。

---

## 一、三级分类

本包对应的分类路径是固定的三级，不设第四级：

| 层级 | key | 名称 |
|---|---|---|
| 一级 · 场景 | `motor` | 电机 |
| 二级 | `cooling-fan` | 散热风扇 |
| 三级 · 产品类型 | `fortior-fu6832` | FU6832 散热风扇驱动板 |

---

## 二、文件清单

### 2.1 数据文件

| 文件 | 干什么 | 主条数 | 主要给哪个流程用 |
|---|---|---:|---|
| `scene.json` | 场景身份：三级分类、产品名、简介、图片引用、三套原理图变体、六流程清单 | 1 张图 | 全流程的入口 |
| `product-attributes.json` | 产品**本体**属性：极对数、Rs/Ld/Ke、转速区间、电压电流规格、采样链路、转速信号 | 29 | 初始化配置 |
| `control-parameters.json` | **控制/整定**参数：启动电流、闭环切换转速、DKP/DKI、SKP/SKI、ATO_BW、载波与死区、顺逆风、限流限功率 | 70 | 启动测试 / 调优确认 |
| `safety-interlocks.json` | 安全联锁规则 + FAULT 位图 | 19 | 初始化配置（确认）/ 启动测试（放行闸口） |
| `test-requirements.json` | 测试项与合格判据（含判据表达式） | 26 | 测试需求确认 / 启动测试 |
| `workflows.json` | 归档 `.wfw` 工作流索引（节点数、分组、电压等级、用途） | 67 | 测试需求确认 / 启动测试 |
| `datasets.json` | 可回放时序数据登记（2 条只登记 + 3 条已复制） | 5 | 启动测试及结果分析 |
| `experience.json` | 经验库样例 | 24 | 知识库管理（经验类）/ 调优时被检索 |
| `documents.json` | 文档库清单（手册、数据手册、原理图、规程、模板、案例表、我方文档） | 61 | 知识库管理（文档类） |
| `report-template.json` | 报告模板字段（表头、十节规格、性能表列、波形图位） | 10 节 | 测试报告及产出 |

### 2.2 资产文件

| 路径 | 说明 | 字节 |
|---|---|---:|
| `assets/schematic-standard-p1.png` | 标准方案原理图首页，PyMuPDF 150 dpi 渲染 | 226,579 |
| `assets/waveforms/TRY-0009_CH1_powerup_normalized.csv` | 合格样本相电流波形 | 1,043,507 |
| `assets/waveforms/TRY-0010_CH1_powerup_normalized.csv` | 不合格样本 1（案例 CF-L-0003） | 1,005,511 |
| `assets/waveforms/TRY-0021_CH1_powerup_normalized.csv` | 不合格样本 2（案例 CF-L-0007） | 1,011,657 |

### 2.3 生成脚本

| 文件 | 说明 |
|---|---|
| `_build/common.py` | 源材料绝对路径常量、`_source` 构造器、占位统计 |
| `_build/gen_a.py` | 生成前 5 个 JSON；含 `#define` 行号定位器 `macro_line()` |
| `_build/gen_b.py` | 生成后 5 个 JSON |
| `_build/build_scene_pack.py` | 入口，跑完打印文件清单、条数、占位比例、未找到项 |

---

## 三、通用字段约定

### 3.1 `_source`（每条数据都有）

```json
"_source": {
  "file": "[源] include/Customer.h",
  "locator": "Customer.h:139 (#define MOTOR_LOOP_RPM)"
}
```

- `file` 一律是**绝对路径**，可独立定位，不依赖本 README 的上下文。
- `locator` 给行号、单元格、PDF 页码、JSON 字段路径或小节标题。
- 某条结论靠多份材料互证时，`_source` 是数组。
- **宏的行号不是手抄的**：`gen_a.py` 在构建时现场扫 `Customer.h` / `Protect.h` / `Motor_Protection.h`，扫不到的宏会进「未找到项」列表。本次构建**全部命中**。

### 3.2 `_placeholder`

值为 `true` 表示**这个数值是编的或借来的**，源材料里没有，前端应显式标注「待确认」，不得直接当真值用。本包共 12 处，见第五节。

### 3.3 可调参数的六件套

`product-attributes.json` 与 `control-parameters.json` 里每项都带：

- `value` 当前值、`default` 默认值
- `unit` 单位
- `min` / `max` / `step` —— 给前端左右加减号用
- `editable` 是否允许调（板级硬件常数为 `false`）

`min` / `max` 优先取 `Customer.h` 行尾注释里的 `[範圍: a ~ b]`。源文件没给范围、由本包推定的，除 `note` 写明外还带 `range_estimated: true`，前端应把这类区间当参考而不是硬约束。本包三处：`ato_bw`、`pwm_deadtime`、`tailwind_start_uq`。

**枚举型参数不适用 min/max/step。** 取值不是连续量的参数（`motor_start_mode`、`svpwm_mode`、`speed_mode`、`current_limiter_mode`、`power_limiter_mode` 五个）三个数值字段一律为 `null`，可选值收在 `options` 数组里，每项带 `value` 与中文 `label`，前端应渲染成下拉选择而不是加减号。缺口型参数（源材料没给上下限）同理，`min` / `max` 为 `null` 时不要按 0 处理。

**`value_below_min: true`** 表示实配值低于源注释自己写的下限，属源材料自身不一致，本包按原样登记未做修正。本包一处：`current_limiter_threshold` 实配 0.6 A，源注释下限写 1.0 A。前端必须显式标出，不得当成落在合法区间内的值。

`control-parameters.json` 额外带 `value_shell`，保留源文件的数值外壳（`I_Value(x)` / `_Q12(x)` / `_Q15(x)`）。**回写 `Customer.h` 时必须沿用原外壳，只改括号内数字**——换外壳等于换量纲，且编译未必报错。

---

## 四、各文件字段说明

### 4.1 `scene.json`

`taxonomy` 三级分类 · `product` 产品名与控制方案 · `summary` 简介 · `images` 图片引用（含渲染参数与像素尺寸）· `schematic_variants` 三套原理图（标准 / VSP 调速 / 无二极体）· `flows` 六流程。

标准方案目录名是「標準方案」，但里面的文件名写作 `FU6832N-Diode-VSP-V1.0`——源材料如此，按原样登记，没有改名。

### 4.2 `product-attributes.json`

八个分组：电机本体、转速规格、电压规格、电流规格、芯片规格、采样链路、转速信号、机械。

芯片规格（VCC 5~28 V、绝对最大 36 V、TA −40~85 ℃、TJ 上限 150 ℃、IVCC 20/40 mA）来自 FU6832 数据手册第 56 页表 5-1 与表 5-2，`editable: false`。

采样电阻一项与原理图做了交叉核对：`HW_RSHUNT` 写 0.01 Ω，原理图上 RS1、RS2 各 0.02R/1206/1%，两只并联正好 0.01 Ω，两侧一致。

### 4.3 `control-parameters.json`

十个分组：启动、预定位、观测器、电流环 PI、速度外环 PI、限幅、载波与死区、调速、顺逆风、限流限功率。

`adjustable_in_flows` 字段说明**这个参数在哪个流程里可调**。大致分工：
- 使能类开关（`OUTLOOP_ENABLED`、`MOTOR_TAILWIND_ENABLED`、`SPEED_MODE`）在**初始化配置**确认；
- 目标转速、启动电流在**启动测试及结果分析**设定；
- PI 系数、观测器带宽、切换转速在**调优确认及运行**调整。

两处命名对不上的地方已在 `note` 里写明：
- 吸尘器规程里的 `LOOP_TIME`，在本散热风扇工程对应 `SPEED_REFRESH_TIMES`，本工程没有 `LOOP_TIME` 宏；
- `CURRENT_LIMITER_THRESHOLD` 实配 0.6 A，低于源注释自己写的范围下限 1.0——源材料自身不一致，按原样登记未做修正，并置 `value_below_min: true`。

该项的 `max` 不再留空。源注释把上限写作符号 `HW_BOARD_CURR_MAX`，该符号在 `Parameter.h:42` 有定义：`HW_BOARD_CURR_MAX = HW_ADC_REF / 2.0 / HW_AMPGAIN / HW_RSHUNT`。三个入参在本工程都有确定值——`HW_ADC_REF` 取 5.0 V（`Parameter.h:106`，因 `Customer.h:87` 的 `HW_ADC_REF_TYPE` 为 `REF_5V0`）、`HW_AMPGAIN` 取 16（`Customer.h:86` 的 `GAIN_16`）、`HW_RSHUNT` 取 0.01 Ω（`Customer.h:85`）。代入得 5.0 / 2 / 16 / 0.01 = 15.625 A，已填进 `max`。

### 4.4 `safety-interlocks.json`

每条带 `id` / `name` / `type` / `threshold` / `action` / `blocking` / `_source`，多数附 `quote` 原话。

`type` 三分，合计 19 条 = 硬件 10 + 流程 7 + 人员 2：

- **硬件**（10 条）。其中固件阈值 7 条（`SI-HW-01`~`SI-HW-07`）：过压 18.0 V / 恢复 14.0 V、欠压 7.0 V / 恢复 8.0 V、下电 6.5 V、软过流 10.0 A、堵转计数 25 次 / 恢复 6000 ms、缺相、温度上限。设备在线校验 3 条（`SI-EQ-01`~`SI-EQ-03`）：示波器在线校验、程控电源在线校验、台架信号接线校验（FG1/FG2/PWM1/PWM2）。设备校验三条的 `type` 也是「硬件」，旧版 README 写「硬件 8 条」是把它们漏掉了。
- **流程**（7 条）：PASS 基线禁改、跑完必停机、改参先问用户、阶段顺序（功率标定必须排在运行稳定前）、保护阈值严禁在线改写、工作区 clean 与中断即还原、电源调回复检 ±5%。前四条摘自 `dc-rules/vacuum-flow-discipline.md`，已标 `source_product_line: "vacuum"`。
- **人员**（2 条）：人员离场确认、半自动步骤的人工确认闸口。

`SI-HW-07` 温度上限的 105 ℃ 不是无条件上限。数据手册给的是两种供电条件下才放宽，满足其一即可（`ambient_derate_logic: "any_of"`）：双电源模式（`VCC_MODE = 1`、`VDD5 = 5 V`、`VCC < 28 V`），或单电源模式（`VCC_MODE = 0`、`VCC < 15 V`）。两种都不满足时上限仍是 85 ℃。键名相应从 `ambient_max_dual_supply_c` 改成 `ambient_max_derated_c`，条件列表放在 `ambient_derate_conditions`。本板走哪种供电模式尚未核实，前端不得直接按 105 ℃ 放行。

**`fault_bitmap` 的查表方式要分两步，不能一上来就按位与。** 13 条覆盖 `0x0000` 到 `0x8000`，来自 `Motor_Protection.h:49-61`。

第一步，拿 fault 整值做精确匹配。有两条只能这样命中：`0x0000`（`FAULT_NONE` 无错误）与任何掩码按位与都是 0；`0x0060`（`FAULT_STALL_METHOD_UQOF`）是 `0x0020 | 0x0040` 的复合常量，不是独立位。

第二步，整值没命中时才按位拆，逐位与 bits 里的单位常量做 `&` 运算，列出全部命中项。

堵转一族（`0x0020` / `0x0040` / `0x0060` / `0x0080`）合起来占 bit5~bit7，按位判定用掩码 `0xE0` 就全覆盖了，无须再单列 `0x0060`。这条规则与两个辅助字段（`composite_values`、`masks`）已写进 `fault_bitmap` 本身。

### 4.5 `test-requirements.json`

十类判据，26 条。`criterion_text` 是人读版本，`evidence` 说明这条判据靠什么证据成立。

**判据的可求值性做了显式收口。** 每条带四个配套字段：

| 字段 | 含义 |
|---|---|
| `evaluable` | 这条能不能真的求出布尔值。本包 20 条 true、6 条 false |
| `criterion` | JavaScript 语法的判据表达式；散文式、取不到标志位的条目为 `null` |
| `variables` | 表达式里每个自由变量映射到确定的取值来[源] |
| `not_evaluable_reason` | `evaluable` 为 false 时写明卡在哪 |

`variables` 的 `source` 四种取值，每种都能解析到一个确定目标：

- `runtime.measure` —— 指向顶层 `runtime_measures` 登记表（42 个），每个测量量带中文名、单位与 `obtained_by`（靠哪个工具怎么取）。
- `threshold` —— 指向本条自己的 `threshold` 字段，如 `threshold.tolerance_pct`。
- `control-parameters` —— 指向 `control-parameters.json` 的某个 `parameters[].key`。
- `constant` —— 编译期常量，`ref` 或 `derived_from` 指向 `safety-interlocks.json` 的 `fault_bitmap`。

6 条 `evaluable: false` 分两种原因。阈值空缺 3 条：`TR-PWM-03`（阶跃时间）、`TR-WIND-03`（强制退出秒数）、`TR-ONOFF-01`（ON/OFF 次数），表达式写得出来但 `threshold` 里的值是 `null`。无标志位可取 3 条：`TR-PROT-03`（LVW）、`TR-PROT-05`（超速）、`TR-PROT-06`（启动失败），本工程 13 个 `FAULT_*` 位里没有对应位，`criterion` 只能是 `null`。

**位运算一律加括号。** C 与 JS 里 `&` 的优先级低于比较运算符，`fault & 0x0008 != 0` 会先算 `0x0008 != 0` 得 1、再与 fault 按位与，判据恒等于 fault 的最低位。四条保护判据（`TR-PROT-01` / `02` / `04` / `07`）已改写成 `(fault_flag & FAULT_OVP) !== 0` 这种形式。堵转掩码原写作 `0x0020|0x0040|0x0060|0x0080`，其中 `0x0060` 是前两者的或值、纯属冗余，已收成 `0xE0`。

几条主判据：

- 起动成功率：100 次启停（可配 1~1000），要求 100/100，FG2 > 10000 RPM 且无 fault。
- FG1 / FG2 转速一致性：`|FG1/FG2 − 2.00| ≤ 0.05`。极对数 2 → 电气频率 = 2 × 机械频率。
- 稳态转速偏差 ≤ 5%，稳定性（3 次极差/均值）≤ 3%。
- 12 档顺风残速重启，间隔 500~6000 ms。
- PWM 调速曲线全档位：三条通过条件同时成立才算 PASS——RPM 误差 ≤ ±5%、过冲 ≤ 10%、稳态电流 ≤ 该档稳态上限。三条来自 `report.xlsm` 的 `PWM·VSP 性能測試` 分页 A3 单元格原文，旧版本只收了第一条。
- 保护验证七项：过压、欠压、低压告警、堵转、超速、启动失败、过流。其中低压告警、超速、启动失败三项本工程无对应宏与 fault 位，`evaluable` 为 false。
- 硬件自检两项：母线电压 ±10%、三相相位 ±5°。

### 4.6 `workflows.json`

67 条，全部实际解析过 `.wfw`。

`.wfw` 实测是**明文 UTF-8 JSON（带 BOM），不是 gzip**；顶层三键 `formatVersion` / `metadata` / `definition`，节点在 `definition.nodes`。脚本保留了 gzip 探测分支以防后续版本换格式，本次 67 个文件 `gzip` 字段全为 `false`。

每条带：`id` / `name` / `metadata_name`（工作流内部名，多为「新工作流」）/ `group`（11 个取值：`HEADWINDTEST` 逆风测试、`TAILWINDWIND` 顺风测试、`StaticStart` 静止启动测试、`OPENCLOSEPOWER` 上下电测试、`PWMDUTY_0TO100` / `PWMDUTY_100TO0` 占空比扫描、`PWMDUTY_HIGHTOLOW` / `PWMDUTY_LOWTOHIGH` 高低速互切、`OTHERTEST` 其他专项测试、`WORKINGflow` 未分组主流程、`子流程` 可复用子流程；前 9 个是按目录切的场景分组，后 2 个是「没进场景目录」的兜底桶）/ `voltage_level`（HV 高压、SV 标准电压、LV 低压，或 `HV+SV+LV` 三档串跑）/ `file_path` / `node_count` / `edge_count` / `node_types`（按类型计数，带中文名）/ `purpose`。

`node_type_legend` 给出 25 种节点类型的中文对照，涵盖设备控制（设置母线电压、继电器通断、上下电）、测试动作（转速测试、启停测试、顺逆风设置）、采集（RIGOL 示波器采集、查询转速/电流）、编排（循环、跳出循环、调用子流程、延时、变量、曲线查表）与产出（生成报告、交给 Agent 调试）。

**`purpose` 字段带 `purpose_derived: true`**，由目录分组 + 电压等级 + 节点类型组合生成，不是源文件里的原话。

数量口径对账：`WORKINGflow/WORKINGflow` 下 58 个（与任务书「58 个归档工作流」一致），`子流程/子流程` 下 9 个，合计 67。调研文档 B 记的是「63 个主工作流 + 9 个子流程」，与本次实测不符，**以本次实测为准**。

### 4.7 `datasets.json`

两种登记方式：

- `mode: "registered_only"` —— 百 MB 级文件只登记路径、表头列名与列义，不复制。两条：`faithful_norm1200.csv`（1200 点降采样复现）与 `fullrun_v2b_20260627.csv`（六档变速全程，101 MB）。四列语义：`ch1_current_V` 相电流、`ch2_fg1_V` FG1 电气转速、`ch3_fg2_V` FG2 红外机械转速、`ch4_pwm1_V` PWM1 驱动输出。
- `mode: "copied_into_pack"` —— 从 98 次实验数据包里挑 3 个 attempt 的 `CH1_上电时刻归一化.csv` 复制进 `assets/waveforms/`，各约 1 MB、24000 行，采样率 2000 Sa/s、存储深度 12000、示波器 RIGOL DS1104Z。

读这三条波形前**必须**先读 `label`、`note` 与 `probe_ratio_note` 三个字段，有四个坑：

1. 列名 `voltage_v` 是采集脚本沿用示波器通道命名，**物理量是相电流（安培）**，不是电压。
2. `t < 0` 的上电前窗口是已知断电条件下的**人工 0 V 补线**，不是示波器实测，不得据此评噪声或零漂。
3. 本批 98 条登记样本的成因金标准**全部**是 `align_weak`（预定位太弱），**正常样本 0 条**。`PASS` 与 `FAIL` 的差别只是这一次启动成没成，不是固件参数正常还是故障——所以这批数据能测检出率，测不了误报率。
4. **探头变比未确认**，三条波形均带 `probe_ratio_confirmed: false`。客户已澄清 CH1 采的就是电流、`voltage_v` 列按安培读，但探头是不是 1 A/V 还没定。若不是，全部数值要按客户给的 mV/A 系数整体缩放一次。形状类判据不受影响，但 `align_mean_a` 一类绝对量级阈值在变比确认前不得对外引用。出处：`峰岹agent/数据/20260811_启动故障98次实验与30例对照数据包/分析报告-预定位太弱判定-20260812.md` 第 450 行的待办表，与同文件第 470 行「待客户确认」第 1 项。

`package_stats` 给出全包口径：101 个 attempt，98 条有标签（PASS 67 / FAIL 30 / INVALID 1），进入波形分析的是 97 条。

### 4.8 `experience.json`

24 条。每条 = 问题现象 `symptom` / 原因 `cause` / 调整动作 `action` / 结果 `result` / 来[源] `_source` / 标签 `tags`。

`tags` 三个维度：`scene`（三级分类）、`flow`（属哪个流程）、`parameters`（涉及哪些参数宏名），另有 `topic` 主题词。前端做「按参数检索经验」时直接用 `tags.parameters`。

`evidence_level` 四档，标明这条经验的证据强度：

| 档位 | 条数 | 含义 |
|---|---:|---|
| 规程条款 | 17 | 客户机 25 份 `dc-skills` 与 5 份 `dc-rules` 的成文规则 |
| 台架实测数据 | 4 | 有实测数字，来自 98 次实验数据包与其分析报告 |
| 台架经验 | 2 | 本项目台架硬件记忆，尚未成文进规程 |
| 判定工具输出 | 1 | 来自判定工具的结构化结论 |

内容上三个来源：`coolingfan-openloop-debug` 规程的 8 现象分诊表（过流、堵转、缺相、不转、切闭环掉速、未进闭环、稳态偏差、稳态振荡）、98 次实验的诊断报告与分析报告、台架与规程纪律。

### 4.9 `documents.json`

61 条，七类：调试手册 8 份、培训材料与原理说明 6 份、芯片数据手册 1 份、原理图 3 套、产品驱动程序 3 份、报告模板与案例表 3 份、调试规程 25 份 + 调试纪律 5 份、我方文档 7 份。

每条带 `type` / `title` / `path` / `size_bytes` / `exists` / `used_in_flows` / `conversion_status` / `conversion_status_label` / `converted_into`。

`conversion_status` 是「文档→知识库转化」的进度，已收成固定枚举的 5 个取值，中文说明单独放在 `conversion_status_label`：

| 枚举值 | 含义 | 条数 |
|---|---|---:|
| `markdown_native` | 本身就是 Markdown，可直接进知识库 | 7 |
| `markdown_extracted` | 源目录已有同名 `.md` 抽取版 | 14 |
| `parsed_into_pack` | 本场景包已把它解析成结构化 JSON | 5 |
| `pdf_renderable` | PDF 可按页渲图给前端 | 3 |
| `not_converted` | 尚未做文档→知识库的转化 | 32 |

旧版本把转化目标baked进状态字符串本身（写成「已解析为 report-template.json」），同一个语义会分裂成好几个取值，前端没法按状态过滤。现在目标单独收在 `converted_into` 数组里，只有 `parsed_into_pack` 非空；数组元素形如 `safety-interlocks.json#fault_bitmap` 的表示落到该文件的某个字段。

规程与纪律条目额外带 `applies_to_cooling_fan` 与 `source_product_line`。

- **25 份 `dc-skills` 规程里只有 `coolingfan-openloop-debug` 一份面向散热风扇**（`source_product_line: "cooling-fan"`），其余 24 份面向吸尘器（`"vacuum"`），迁到散热风扇要重新核对宏名与阈值。
- **5 份 `dc-rules` 纪律逐份判过，判据是纪律正文指向哪条产品线而不是文件名。** 适用 3 份（`protect-config-check`、`scene-hw-selfcheck`、`scene-protect-verify`，`source_product_line: "generic"`），不适用 2 份（`scene-requirement` 正文点名要调 `vacuum-customer-h` skill、`vacuum-flow-discipline` 标题即「吸尘器调试通用铁律」，两者均为 `"vacuum"`）。逐条理由写在各自的 `note`。

### 4.10 `report-template.json`

模板文件 `Fortior_Motor_Checklist_公用模板_7(1).xlsm`，已填充样例 `report.xlsm`（2026-06-22 批次）。

- `sheets`：11 个分页的行列数与内嵌图片数（LV 35 张、SV 36 张等，openpyxl 实测）。
- `header_fields`：10 个表头字段，**标签格与取值格已拆开**。旧版本的 `cell` 字段指的是标签格（`B4` 里写的是「客戶名稱」四个字），前端照着填会把值写进标签格。openpyxl 实测模板与已填充样例的 `測試程式規格表` 布局完全一致：B 列、D 列是标签（灰底 `FFE7E6E6`），C 列、E 列是取值格（黄底 `FFFFF2CC`）。所以标签 `Bn` 的取值格是 `Cn`，标签 `Dn` 的取值格是 `En`，分别记在 `label_cell` 与 `value_cell`。韧体版本对应 `Customer.h` 的 `PROJECT_VERSION` 宏。

  **已填充样例 `report.xlsm` 的这 10 项表头一项都没填**（`header_filled_count` 为 0，每项 `filled_in_sample` 均为 `false`，openpyxl 实测 C4:C8 与 E4:E8 全空）。旧版 README 把这份文件笼统称作「已填充样例」，容易让人以为表头有真值可抄——它填的只是波形图与性能表，表头是空的。
- `spec_sections`：規格表十节（电机参数、控制设计、转速、电压、调速方式、FG/RD 讯号、保护、顺逆风、其他必须测试、其他特殊需求），每节带行区间、字段列表、`from_flow`，以及 `maps_to`——**这一节的内容由本包哪个 JSON 提供**。
- `performance_table`：PWM·VSP 性能测试表，11 个占空比档位 × 10 列，Inlet / Outlet 两区。

  **通过条件是三条不是一条。** `pass_condition` 已从单条字符串改成数组，收齐 A3 单元格原文的三条：RPM 误差 ≤ ±5%、过冲 ≤ 10%、稳态电流 ≤ 稳态上限。每条带 `maps_to` 指回 `test-requirements.json` 的 `TR-PWM-01`，两处判据同步。

  **四列的 CSV 单位与 Excel 表头单位差 1000 倍**，每列现在带 `csv_unit` / `sheet_unit` / `scale_factor`（`scale_factor` 的语义是「CSV 数值 × 它 = 该写进 Excel 的数值」）：

  | 列 | Excel 表头 | CSV 列名与单位 | scale_factor |
  |---|---|---|---:|
  | E | Max 電流 (mA) | Max Current (A) | 1000 |
  | F | 穩態電流 (mA) | Steady Current (A) | 1000 |
  | H | 穩態上限 (mA) | Steady Limit (A) | 1000 |
  | I | 加速時間 (s) | Accel Time (ms) | 0.001 |

  出处是 `平台代码/writeFile_rust/README.md` 第 143-152 行的 CSV 列定义表，与 `平台代码/writeFile_rust/src/excel_writer.rs` 第 170 行起的写入调用。

  **`auto_filled_by_tool`** 标明哪些列是工具自动填的。按 `excel_writer.rs` 第 160-163 行的列映射注释与其后五次 `set_value_number` 实测，工具只写 C、E、F、H、I 五列；D、G 是表内公式列；A、B、J 三列工具不写（A 是模板预置的档位，B 的数据虽在 CSV 里但代码不写它，J 要人工填）。另有 K 列「虛擬 FG 讀取（FG 實測 RPM）」存在于 `report.xlsm` 的 K8，既不在工具写入集合里也不在本 `columns` 数组里，属未登记列。

  每列另标了在 CSV 里是第几列（`rpm_error_pct` 与 `fake_fg_target_rpm` 两列 `csv_index` 为 `null`）。
- `waveform_image_slots`：波形截图按文件名自动插入的 6 条命名规则（`Duty_50_Start_SV.png` 静止启动、`Duty_0t10_SV.png` 加减速、`Lock_*` 堵转、`HSPtLSP_*` 高切低、`HSP_BLow_*` 高速制动、`LSPtHSP_*` 低切高）与三档电压对应的分页。
- `filler_tool`：填充工具 `writeFile_rust`（Rust 替代 VBA 宏，保留模板里的 VBA）及其 CLI。

---

## 五、哪些是占位（12 处，占带源对象总数的 3.6%）

凡 `_placeholder: true` 的条目，前端一律要标「待确认」。

### 5.1 源材料确实没有（5 处）

| 位置 | 项 | 情况 |
|---|---|---|
| `product-attributes.json` | 风扇外形尺寸 | `Customer.h`、数据手册、原理图、调研文档 A/B 均无机械尺寸，需向客户索取 |
| `product-attributes.json` | 风扇厚度 | 同上 |
| `test-requirements.json` | 每 10% PWM 阶跃响应时间 | 模板里是空白待填项 |
| `test-requirements.json` | 顺逆风强制退出秒数 | 模板里是空白待填项 |
| `test-requirements.json` | 三档电压 ON/OFF 次数 | 模板原文即写「客戶需求待確認」 |

### 5.2 由旁证推出，不是明文（3 处）

| 位置 | 项 | 推法 |
|---|---|---|
| `product-attributes.json` | 额定母线电压 12.0 V | 归档工作流把母线设到 12.5 V；过压 18.0 V / 欠压 7.0 V 的窗口也指向 12 V 级母线 |
| `product-attributes.json` | 额定转速 28000 RPM | 按 `MOTOR_MAX_SPEED` 暂取 |
| `product-attributes.json` | 整机额定相电流 0.6 A | 按运行阶段 Q 轴初始电流 `I_Value(0.6)` 暂取 |

### 5.3 判定带宽是本包设的，不是源材料给的（1 处）

| 位置 | 项 | 情况 |
|---|---|---|
| `test-requirements.json` | FG1/FG2 比值容差 ±0.05 | 台架记忆只写「FG1 ≠ 2×FG2 即异常」，没给容差数值。比值 2.00 本身是真的（极对数 2） |

### 5.4 借自吸尘器线，适用性待确认（3 处）

| 位置 | 项 | 情况 |
|---|---|---|
| `safety-interlocks.json` | 温度上限 | 本工程 `Customer.h` / `Protect.h` grep `TEMP` / `NTC` 零命中，没有过温保护宏。填的是数据手册的**器件级**规格，不是驱动板的整机过温联锁 |
| `test-requirements.json` | 低压告警 LVW 验证 | 本工程 `Protect.h` 无 LVW 阈值宏，散热风扇是否有低压告警待确认 |
| `test-requirements.json` | 超速保护验证 | 规程针对吸尘器的 `OVER_SPEED_EN` 宏，本工程 `Protect.h` 无超速保护宏 |

---

## 六、本次构建没有出现的问题

`_build/build_scene_pack.py` 会把两类问题打进「未找到项」：`Customer.h` / `Protect.h` / `Motor_Protection.h` 里扫不到的宏，以及 `documents.json` / `datasets.json` 里登记了但磁盘上不存在的文件。**本次构建两类均为 0 条**——引用的 70 个控制参数宏、29 个属性宏、全部 61 份文档与 5 个数据集路径都在。

## 七、已知的上游缺口（不是本包的问题，但会影响演示）

1. **功率标定断点**：纪律要求「功率标定必须排在运行稳定前」，但 `power-calibration` 在客户场景清单里仍是 `planned`，流程链有断点。
2. **规程覆盖不均**：25 份规程里只有 1 份面向散热风扇，其余 24 份是吸尘器线。
3. **本批数据测不了误报率**：98 条全是 `align_weak` 注入，正常样本 0 条。
4. **规程只在客户机 D 盘**：`dc-skills` 与 `dc-rules` 未进版本库，本包只登记路径与描述，没有复制正文。
5. **填充工具与报告模板的单位口径矛盾，且工具不做换算**：模板的 `PWM·VSP 性能測試` 表头把电流三列写作毫安、加速时间写作秒，而 `writeFile_rust` 读的 CSV 给的是安培与毫秒（`平台代码/writeFile_rust/README.md:143-152`）。`平台代码/writeFile_rust/src/excel_writer.rs` 第 170 行起是五次裸的 `set_value_number`，**直接把 CSV 数值写进单元格，中间没有任何换算**。结果是电流列填出来比表头单位小 1000 倍、加速时间列大 1000 倍。本包如实登记两侧单位与 `scale_factor`，不替上游决定谁对；要么改工具加换算，要么改模板表头单位，需客户拍板。
6. **`report.xlsm` 的表头 10 项是空的**：这份「已填充样例」只填了波形图与性能表，`測試程式規格表` 的客戶名稱、Model、韌體版本等 10 项取值格全空，不能拿它当表头填写范例。

---

## 八、重新生成

```bash
cd [源] scenes/motor.cooling-fan.fortior-fu6832
python3 _build/build_scene_pack.py
```

依赖：`PyMuPDF`（渲原理图）、`openpyxl`（读 xlsm）。

脚本会**覆盖**全部 10 个 JSON 与 `assets/` 下的 4 个资产，并打印文件清单、各文件条数、占位比例与未找到项。对源材料全程只读。
