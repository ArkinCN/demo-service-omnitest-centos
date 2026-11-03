# B-汽车场景测试案例素材

调研日期 2026-09-19。用途：为「多场景的基于 Agent 的测试系统」补第二个完整案例（第一案例为峰岹散热风扇电机），证明系统可跨场景泛化。六个典型流程的定义取自同目录上级文件 `docs/20260919-通用Agent测试系统v2.0/00-用户需求原话-20260919.md`。

**可信度三档口径（全文通用）**

| 档位 | 含义 | 允许的用法 |
|---|---|---|
| 已核实 | 本次调研在标准正文原件、发布机构官网详情页或官方数据库页面上直接看到「编号 + 全名」或该数值 | 可直接写入测试用例与判定逻辑 |
| 待核实 | 仅来自第三方解读、检测机构页面、征求意见稿或搜索摘要 | 只能做量级参考与台架能力规划，不得作为判定阈值 |
| 未取得 | 编号与全名已核实，但正文条款未拿到 | 只能写「依据某标准」的引用占位，数值必须先采购正文 |

---

## 一、选题论证

### 1.1 候选池与初筛

用户给的候选有七个：汽车雨刮电机、车窗/天窗电机、电动座椅电机、EPS 转向电机、汽车冷却风扇电机、电动水泵、电子节气门。按「可运动产品 + 有测试标准 + 有公开数据或波形」三条硬门槛先做一轮淘汰。

| 候选 | 标准可得性 | 公开数据/波形 | 与峰岹案例的差异度 | 初筛结论 |
|---|---|---|---|---|
| 汽车雨刮电机 | QC/T 29090-2023《汽车用刮水电动机》**全文在手**，20 项判据全量化 | 无专用波形；有刷直流代理集可借 | 高（有刷直流 + 往复摆动 vs 无刷风扇 + 单向旋转） | **进入决赛** |
| 车窗/天窗电机（玻璃升降器，含防夹） | QC/T 626-2019 编号已核实 + 其征求意见稿全文在手；GB 11552-2009 防夹条款原文在手；FMVSS 118 法条在手 | 无专用波形；防夹电流纹波与霍尔脉冲有成熟可合成模型 | 高（有刷直流 + 直线行程 + 人身安全判据） | **进入决赛** |
| 汽车冷却风扇电机 | QC/T 773-2006 编号已核实，**正文未取得**；SAE J2867-202410 已核实 | 可复用峰岹既有方法 | **低**（与第一案例同构，泛化说服力弱） | **进入决赛，作对照项** |
| 电动座椅电机 | QC/T 831-2010 编号已核实，正文未取得 | 零命中 | 中 | 淘汰：标准正文与数据双空 |
| EPS 转向电机 | QC/T 1082-2017 编号已核实，正文未取得 | 数据集零命中；MathWorks Simscape Electrical 有车规示例模型 | 中 | 淘汰：判据完全拿不到，环路参数属主机厂私有 |
| 电动水泵 | QC/T 1122-2019 编号与范围已核实、限值未取得；团标《新能源汽车高电压电子冷却水泵技术要求》征求意见稿**全文在手**，判据量化 | 工业离心泵代理集可借，车载泵零命中 | 中（离心负载与风扇接近） | 淘汰：与风扇负载特性接近，泛化说服力不如前三 |
| 电子节气门 | QC/T 1035-2016 编号已核实，正文未取得 | Zenodo 上唯一命名匹配的记录内容存疑（见 §5.3） | 高 | 淘汰：标准与数据均不可靠 |

### 1.2 决赛三选一：按六个流程逐格打分

评分口径：● 素材充足可直接落地；◐ 有素材但需补齐或迁移；○ 零命中或只能自建。

| 流程 | 候选 A 雨刮电机 | 候选 B 玻璃升降器（含防夹） | 候选 C 汽车冷却风扇电机 |
|---|---|---|---|
| 1 知识库管理 | ● QC/T 29090-2023 全文 + GB 15085-2013 + SAE J903/J198 | ● QC/T 626-2019 征求意见稿全文 + GB 11552-2009 条文 + FMVSS 118 + UN ECE R21 + GB 7258-2017，**四地法规同题可比** | ◐ QC/T 773-2006 正文未取得；SAE J2867 需购 |
| 2 初始化配置 | ◐ TIDA-01530 参考设计；QC/T 29090 给出电压 9–16 V、温度 −40 至 +85 ℃ | ● 四家芯片厂参考设计（TI/NXP/Microchip/Infineon）+ QC/T 626 给出电压 9–16 V、工作电流 ≤12 A、堵转电流 ≤28 A、堵转力 ≥212 N | ◐ TIDA-00901 参数完整，但被测电机本体参数缺 |
| 3 测试需求确认 | ● **判据最全**：噪声分挡、温升 60 K、停位角 ±6°、IP5K4K、堵转 30 s、堵转耐久 1 万次、整机耐久 50 万 + 100 万次 | ● 判据齐全且**含跨标准协调**：本体判据（速度、噪音、自锁 600 N、热保护表、耐久 1 万循环 13 道工序）+ 三地一致的防夹 100 N / 4–200 mm | ◐ 只能借 GB/T 28046 与 SAE J2867 的通用框架 |
| 4 启动测试与结果分析 | ◐ 无雨刮波形，借有刷直流代理集 + 仿真合成 | ◐ 同左，但防夹场景的电流纹波与霍尔脉冲有明确可合成的物理模型 | ● 可直接复用峰岹既有示波器波形与工作流 |
| 5 调优确认及运行 | ○ 雨刮专用调参笔记**全网零命中** | ● 防夹阈值自适应、霍尔纹波计数、堵转去抖、力阈值标定，论文与厂商方案都有 | ◐ 无感 FOC 调参资料丰富，但与峰岹重复 |
| 6 测试报告及产出 | ○ 无雨刮专用报告样张 | ● **NHTSA 公开合规测试报告全套可下载**，36 页含目录/数据表/设备清单/照片页，是全网唯一"同产品官方报告样张" | ○ 无公开样张 |

### 1.3 推荐：候选 B，汽车电动玻璃升降器（含防夹功能）

三条理由。

**第一，六个流程里没有空格。** 候选 A 在流程 5 与流程 6 上是两个零命中，做出来的演示会在「调优」和「报告」两屏上无米下锅；候选 C 在流程 1、6 上空，且它与第一案例同构——用一台汽车风扇去证明"系统不只能测风扇"，逻辑上自相矛盾。只有候选 B 六格全部落在 ● 或 ◐。

**第二，报告环节有真实可下载的官方样张，这是最难补的一环。** 美国国家公路交通安全管理局（National Highway Traffic Safety Administration, NHTSA）的合规测试报告数据库里有完整的 FMVSS No. 118 测试报告 PDF，被测对象正是电动车窗系统，报告结构、数据表字段、设备校准表、照片页一应俱全。第三方检测机构（TÜV Rheinland、SGS、Intertek、中国汽研 CATARC 等）的报告样张在本次调研中是**全面零命中**——这类文件通常不公开。候选 B 是唯一能绕开这个缺口的选题。

**第三，与峰岹案例的差异度恰到好处。** 峰岹散热风扇是无刷直流、单向旋转、以转速与相电流为主判据；玻璃升降器是有刷直流、直线往复行程、判据里同时有机械量（速度 mm/s、堵转力 N、自锁位移 mm）、声学量（dB(A)）、热保护时序（循环次数与恢复秒数）和人身安全量（防夹力 100 N）。这四类判据在第一案例里一个都没有，能有力支撑"同一套 Agent 骨架换场景仍然跑得通"的叙事。同时两者又共享电压/电流/温升/盐雾/EMC 这批公共维度，正好演示知识库三级分类里"场景不同、二级判据复用"的设计。

**备选方案（写进文档留退路）**：若正式版 QC/T 626-2019 采购不到，导致本体判据只能停留在征求意见稿（待核实档），则切换到候选 A 雨刮电机——它的 QC/T 29090-2023 正文已在手、判据 20 项全部已核实，代价是流程 5 与流程 6 需要自建。

---

## 二、流程 1 · 知识库管理：产品技术文档与标准清单

### 2.1 主选产品（玻璃升降器）的直接对口标准

| 素材 | 来源全名 | URL | 可用形态 | 可信度 |
|---|---|---|---|---|
| QC/T 626-2019《汽车玻璃升降器》 | 中华人民共和国工业和信息化部发布，全国汽车标准化技术委员会（SAC/TC 114）归口，起草单位重庆海德世拉索系统（集团）有限公司、汉阳专用汽车研究所。2019-11-11 发布 / 2020-04-01 实施，现行，同时代替 QC/T 626-2008 与 QC/T 636-2014 | https://hbba.sacinfo.org.cn/stdDetail/9ca3b738497da0d0d84ae02e3b7e1815c9dd070e4233e5d3a3ba126dad340b73 | 平台以"潜在版权问题"不公开全文，需采购 | 编号与代替关系已核实；正文未取得 |
| 《汽车玻璃升降器》行业标准征求意见稿（拟代替 QC/T 626-2008、QC/T 636-2014） | 中国汽车技术研究中心有限公司（China Automotive Technology and Research Center Co., Ltd., CATARC）官网公开挂载，16 页 PDF | https://www.catarc.org.cn/upload/201807/13/201807131600519972.pdf | **PDF 全文在手，已提取为纯文本**，含第 5 章要求与第 6 章试验方法全部条款 | 文件本身已核实（本次下载并逐条提取）；其**数值相对正式版可能调整，判据一律标待核实** |
| QC/T 636-2014《汽车电动玻璃升降器》 | 工业和信息化部，2014-05-06 发布 / 2014-10-01 实施，**已废止**，被 QC/T 626-2019 代替 | https://hbba.sacinfo.org.cn/stdDetail/479072c1dba6d1cf28a8c5a281020203 | 仅作沿革参照 | 已核实 |
| GB 11552-2009《乘用车内部凸出物》（英文名 The interior fittings of passenger car） | 国家质量监督检验检疫总局与国家标准化管理委员会联合发布，工业和信息化部归口。2009-09-30 发布 / 2012-01-01 实施，现行，代替 GB 11552-1999 | 详情页 https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno=6A3758226270FE03F4F4B841A56428B9 ；条文 PDF（law.resource.org 公开转载）https://law.resource.org/pub/cn/ibr/gb.11552.c.2009.pdf | **报批稿全文 32 页在手**，第 4.8 条「车窗、天窗及隔断系统的电操作」原文逐字可引 | 编号、全名、英文名、发布与实施日期已核实；第 4.8 条条文本次直接从 PDF 文本层提取，**已核实** |
| GB 7258-2017《机动车运行安全技术条件》 | 国家标准化管理委员会，强制性国家标准 | 经解读页 https://www.smartautoclub.com/p/50318/ 转述 | 整车级要求：车窗与天窗在移动中能在任意位置可靠停住，或遇障碍可自动下降回缩 | 待核实（未取得标准原文条款号） |
| 49 CFR § 571.118 — Standard No. 118; Power-operated window, partition, and roof panel systems（美国联邦机动车安全标准第 118 号：电动车窗、隔板与顶板系统） | 美国国家公路交通安全管理局（National Highway Traffic Safety Administration, NHTSA）；法规全文由康奈尔法学院法律信息研究所（Legal Information Institute）与美国联邦法规电子版（eCFR）公开 | https://www.ecfr.gov/current/title-49/subtitle-B/chapter-V/part-571/subpart-B/section-571.118 ；https://www.law.cornell.edu/cfr/text/49/571.118 | 网页全文，含试验方法与判据 | 100 N 与 4–200 mm 已核实；S4/S7/S8 条款编号待核实 |
| UN ECE R21 — Uniform Provisions Concerning the Approval of Vehicles with Regard to Their Interior Fittings（联合国欧洲经济委员会第 21 号法规：车辆内饰认证统一规定） | 联合国欧洲经济委员会（United Nations Economic Commission for Europe, UNECE） | https://unece.org/DAM/trans/main/wp29/wp29wgs/wp29grsp/grspinf/28/28-inf01.pdf ；欧盟官方公报版 https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:42008X0716(01) | 法规 PDF，第 5.8 条系列 | 待核实（未打开原文逐字确认） |
| Federal Motor Vehicle Safety Standards; Power-Operated Window, Partition, and Roof Panel Systems（FMVSS 118 规则制定文件） | 美国联邦公报（Federal Register），文件号 E9-21042，2009-09-01 | https://www.federalregister.gov/documents/2009/09/01/E9-21042/federal-motor-vehicle-safety-standards-power-operated-window-partition-and-roof-panel-systems | 网页全文，给出试验棒尺寸区间的立法理由（4 mm 对应幼儿手指、200 mm 对应第 95 百分位成年男性头部最大宽度） | 已核实 |

### 2.2 通用底座与环境试验标准（两个案例共用，属知识库二级分类）

| 素材 | 来源全名 | URL | 可用形态 | 可信度 |
|---|---|---|---|---|
| QC/T 413-2002《汽车电气设备基本技术条件》 | 国家经济贸易委员会，2002-12-31 发布 / 2003-03-01 实施，现行，代替 QC/T 413-1999 | https://hbba.sacinfo.org.cn/stdDetail/4e925606f256d82d41af1bb0f8859f7d | 所有车用电机标准的公共底座，QC/T 626、QC/T 1102、QC/T 29090 均引用其扫频振动条件 | 已核实；正文未取得 |
| GB/T 28046 系列《道路车辆 电气及电子设备的环境条件和试验》第 1 至 5 部分 | 工业和信息化部提出，全国汽车标准化技术委员会归口。第 1 部分一般规定 GB/T 28046.1-2011、第 2 部分电气负荷 GB/T 28046.2-2019、第 3 部分机械负荷 GB/T 28046.3-2011、第 4 部分气候负荷 GB/T 28046.4-2011、第 5 部分化学负荷 GB/T 28046.5-2013 | 列表页 https://openstd.samr.gov.cn/bzgk/gb/std_list?p.p2=28046 | 全系列共五部分，无第 6 部分 | 编号与状态已核实；谱表与温度点未取得 |
| ISO 16750 系列 Road vehicles — Environmental conditions and testing for electrical and electronic equipment（道路车辆 电气电子设备的环境条件与试验），第 1 至 5 部分，均为 2023 版 | 国际标准化组织（International Organization for Standardization, ISO），技术委员会 ISO/TC 22/SC 32 | -1 https://www.iso.org/standard/77578.html ；-2 https://www.iso.org/standard/76119.html ；-3 https://www.iso.org/standard/77579.html ；-4 https://www.iso.org/standard/77580.html ；-5 https://www.iso.org/standard/77581.html | 正式预览件含完整目录与部分开放正文页（iTeh 托管的 ISO 官方样张）：-2 见 https://cdn.standards.iteh.ai/samples/76119/f42b46cc6aef47daa9c6612e225b6f35/ISO-16750-2-2023.pdf ，-4 见 https://cdn.standards.iteh.ai/samples/77580/566a2608296348ef944168a85dc51bab/ISO-16750-4-2023.pdf | 编号、版次、页数、条款清单已核实 |
| GB/T 21437 系列《道路车辆 电气/电子部件对传导和耦合引起的电骚扰试验方法》第 1 至 3 部分，均为 2021 版；第 4 部分为 GB/Z 21437.4-2025 | 全国汽车标准化技术委员会电子电磁兼容分技术委员会 | https://openstd.samr.gov.cn/bzgk/gb/std_list?p.p2=21437 | 第 2 部分为沿电源线的电瞬态传导发射与抗扰性，是升降器 EMC 条款的引用对象 | 编号与状态已核实；脉冲幅值表待核实 |
| GB/T 18655-2025《车辆、船和内燃机 无线电骚扰特性 用于保护车载接收机的限值和测量方法》 | 全国无线电干扰标准化技术委员会，2025-02-28 发布并实施，现行，**代替 GB/T 18655-2018**（后者已废止） | https://openstd.samr.gov.cn/bzgk/gb/std_list?p.p2=18655 | 对应国际标准 CISPR 25 | 已核实。**换版预警**：QC/T 626 征求意见稿引用的是 GB/T 18655-2010，已两代过期 |
| CISPR 25:2021 Vehicles, boats and internal combustion engines — Radio disturbance characteristics — Limits and methods of measurement for the protection of on-board receivers，第 5.0 版，372 页 | 国际电工委员会国际无线电干扰特别委员会（IEC / CISPR），分技术委员会 CIS/D，2021-12-16 | https://webstore.iec.ch/publication/64645 | 频率范围 150 kHz 至 5 925 MHz | 编号、版次、频率范围已核实；Class 1–5 限值数值未取得 |
| GB/T 4208-2017《外壳防护等级（IP代码）》 | 国家标准化管理委员会，2017-07-31 发布 / 2018-02-01 实施，现行 | https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=09CCED55688D4116ED89659C1E7526F8 ；陕西省市场监督管理局公开 PDF https://snamr.shaanxi.gov.cn/sy/ztzl/sbgxhxfpyjhx/bzcx/gjbz/202409/P020250320613606362189.pdf | QC/T 1102 的电机防水条款直接引 IPX4 | 部分核实（扫描件机器读取） |
| GB/T 30038-2013《道路车辆 电气电子设备防护等级（IP代码）》；换版为 GB/T 30038-2026，2027-02-01 实施 | 国家标准化管理委员会。新版修改采用 ISO 20653:2023 | https://openstd.samr.gov.cn/bzgk/gb/std_list?p.p2=30038 | 车用版 IP 代码，相对 GB/T 4208 增设 IPX9K | 编号与日期已核实；IPX9K 参数未取得 |
| GB/T 10125-2021《人造气氛腐蚀试验 盐雾试验》 | 国家标准化管理委员会，2021-08-20 发布 / 2022-03-01 实施，现行，全部代替 GB/T 10125-2012 | 国家标准全文公开系统检索"盐雾" | QC/T 626 征求意见稿引用的是 2012 版，已换版 | 已核实 |
| GB/T 5171.22-2017《小功率电动机 第22部分：永磁无刷直流电动机试验方法》；配套 GB/T 5171.1-2014 通用技术条件、GB/T 5171.21-2016 通用试验方法 | 国家标准化管理委员会 | 国家标准全文公开系统检索"小功率电动机" | 对汽车小电机适用性高于三相异步机试验标准 | 已核实 |

### 2.3 跨场景可复用的国际与 OEM 规范（知识库一级分类"汽车"的公共层）

| 素材 | 来源全名 | URL | 可用形态 | 可信度 |
|---|---|---|---|---|
| AEC-Q100 Failure Mechanism Based Stress Test Qualification for Integrated Circuits in Automotive Applications，Rev J1，2026-03-24 | 汽车电子委员会（Automotive Electronics Council, AEC） | http://www.aecouncil.com/AECDocuments.html （该站 HTTPS 证书握手失败，须走 HTTP） | **官方免费 PDF 已下载**，含温度等级表与全部应力试验条件 | 已核实 |
| AEC-Q101 Rev E（2021-03-01，分立半导体）、AEC-Q102 Rev A（2020-04-06，光电半导体）、AEC-Q104 Rev A（2025-11-28，多芯片模块）、AEC-Q200 Rev E（2023-03-20，被动元件） | 同上 | 同上 | 官方免费 PDF 已全部下载 | 已核实。**注意 AEC-Q200 Rev E 已取消 Grade 0–4 温度分级表**，改为供应商自行声明且最低覆盖 −40 至 +85 ℃ |
| LV 124 — Elektrische und elektronische Komponenten in Kraftfahrzeugen bis 3,5 t: Allgemeine Anforderungen, Prüfbedingungen und Prüfungen（3.5 t 以下机动车电气电子部件：通用要求、试验条件与试验） | 由奥迪（AUDI AG）、宝马（BMW AG）、戴姆勒（Daimler AG）、保时捷（Porsche AG）、大众（Volkswagen AG）五家在工作组 AK 4.9 内共同制定。可核实基础版 Edition 2013-02-28，文档版本 2.2 | 原文证据为梅赛德斯-奔驰企业标准 MBN LV 124-1: 2013-03，https://www.etest-emc.com/uploads/soft/250506/LV124-12013.pdf | PDF 全文，含 E-01 至 E-22 电气试验全部参数 | 制定方、工作组、版本日期已核实。**该 PDF 为公网流传的非授权副本，正式引用须经采购渠道取得授权原本复核** |
| VW 80000 — Electrical and Electronic Components in Motor Vehicles up to 3,5 t: General Requirements, Test Conditions, and Tests，大众集团标准，分类号 8MA00，Issue 2022-12 | 大众汽车股份公司（Volkswagen AG） | https://www.etest-emc.com/uploads/soft/250707/VW80000_2022大众汽车零部件电性能标准.pdf | PDF 全文，含 E-01 至 E-24、M-01 至 M-09、K-01 至 K-19、C-01、L-01 至 L-03 全部试验目录与参数 | 已核实；同为非授权副本 |
| MBN LV 148: 2013-11 — Electric and Electronic Components in Motor Vehicles: 48 V On-Board Electrical System, Requirements and Test Conditions | 戴姆勒（Daimler AG）采标版，基础版 LV 148 Edition 2013-07 | https://www.etest-emc.com/uploads/soft/250709/LV148MBN2013-11.pdf | PDF 全文，48 V 电网电压定义与 E48-01 至 E48-21 试验清单 | 已核实；非授权副本 |
| GMW3172 — General Specification for Electrical/Electronic Component Analytical/Development/Validation (A/D/V) Procedures for Conformance to Vehicle Environmental, Reliability, and Performance Requirements | 通用汽车全球工程标准（General Motors Global Engineering Standards）。可取得原文级内容的是 2008 版，载于 The GMW3172 Users Guide, Revision 19, 2008-02-13，作者 Larry Edson | https://www.atecorp.com/compliance-standards/gm/gmw3172-standard | 五位代码字母串定义部件试验等级（电气/机械/气候/温度/防护） | 2008 版内容已核实；**当前现行版次待核实**，距今 18 年 |
| ISO 26262 系列 Road vehicles — Functional safety，第 1 至 12 部分，均为 2018-12 第 2 版（Part 11、12 为第 1 版） | 国际标准化组织 ISO | Part 1 https://www.iso.org/standard/68383.html 至 Part 12 https://www.iso.org/standard/69605.html | 全部 12 个部分当前均有 ISO/DIS 修订在研 | 已核实 |
| GB/T 34590 系列《道路车辆 功能安全》第 1 至 12 部分，均为 2022 版 | 国家标准化管理委员会，2022-12-30 发布 / 2023-07-01 实施，现行；2017 版第 1 至 10 部分已全部废止 | https://openstd.samr.gov.cn/bzgk/gb/std_list?p.p2=GB%2FT%2034590 | ISO 26262 的中国对应系列 | 已核实 |

### 2.4 换版预警（知识库必须内置的元数据）

| 标准 | 变化 | 时间点 |
|---|---|---|
| GB 34660-2026《道路车辆 电磁兼容性要求和试验方法》 | 将代替 GB 34660-2017 | 2027-07-01 实施 |
| GB/T 30038-2026《道路车辆 电气电子设备防护等级（IP代码）》 | 将代替 GB/T 30038-2013 | 2027-02-01 实施 |
| GB/T 33012.5-2026《整车混响室法》 | 新增 | 2027-03-01 实施 |
| GB/T 18655-2025 | 已代替 GB/T 18655-2018 | 2025-02-28 已生效 |
| GB/T 755-2025《旋转电机 定额与性能》 | 已代替 GB/T 755-2019 | 2026-02-01 实施 |
| QC/T 627-2025《汽车电动门锁装置》、QC/T 777-2025《汽车冷却系统电磁离合器》 | 均已发布待实施 | 2026-07-01 实施 |

---

## 三、流程 2 · 初始化配置：产品参数、驱动方案与测试保护

### 3.1 被测件本体参数（来自 QC/T 626 征求意见稿，条款号与数值可直接映射到"参数配置"左栏）

下表全部来自 CATARC 公开的《汽车玻璃升降器》征求意见稿 PDF（§2.1 给出链接），**整表标待核实**：正式版 QC/T 626-2019 可能调整。

| 参数 | 条款 | 数值 | 在系统里的角色 |
|---|---|---|---|
| 工作电压范围 | 5.4.1 a) | 9 V 至 16 V，运行平稳、无异音无卡滞 | 初始化配置的电压上下限，左右加减号调节 |
| 试验电压 | 6.1 b) | 13.5 ± 0.3 V；接线电阻 0.15 ± 0.02 Ω | 台架程控电源设定值 |
| 工作电流上限 | 5.4.1 b) | ≤ 12 A | 过流保护阈值的基准 |
| 堵转电流上限 | 5.4.1 b) | ≤ 28 A | 堵转判据与过流保护阈值 |
| 堵转力 | 5.4.1 c) | ≥ 212 N | 力传感器量程选型依据 |
| 上升运行速度 | 5.4.1 d) | 80 至 160 mm/s | 位移传感器与判据 |
| 下降运行速度 | 5.4.1 d) | ≤ 200 mm/s | 同上 |
| 工作噪音 | 5.4.1 e) | < 60 dB(A) | 声学测点：电机出力轴正上方 300 mm |
| 启动电压 | 5.4.1 f) | ≤ 9 V | 低压启动能力判据 |
| 自锁能力 | 5.5 | 托架中心垂直施加 600 N 保持 5 s，下降量 ≤ 5 mm | 静态加载工位 |
| 常温定义 | 6.1 c) | 23 ± 2 ℃ | 环境基线 |
| 额定负载计算式 | 6.1 d) | 上升：玻璃重量 + 胶条滑动阻力；下降：玻璃重量 − 胶条滑动阻力 | 模拟工装配重设定 |
| 仪器精度 | 6.1 a) | 电源纹波峰峰值 ≤100 mV；电压表 ≥0.5 级；电流表 ≥1 级；长度器具最小刻度 ≤0.05 mm；扭矩仪最小刻度 ≤0.01 N·m | 台架仪器选型门槛 |

### 3.2 驱动方案与芯片侧参数（对应"产品驱动程序""产品功能清单"两类配置文档）

| 素材 | 来源全名 | 编号/年份 | URL | 可用形态 | 可信度 |
|---|---|---|---|---|---|
| Small-Footprint Sunroof Motor Module Reference Design（小尺寸天窗电机模块参考设计，含防夹检测） | 德州仪器（Texas Instruments Incorporated） | 设计编号 TIDA-01389；设计指南 TIDUCQ9 Rev. A，2017-07-21 | https://www.ti.com/tool/TIDA-01389 | 产品页 + 设计指南 PDF + 原理图 TIDRQE4 / BOM TIDRQE5 / PCB TIDRQE7 / Gerber TIDCDA8 | 已核实。可提参数：有刷直流电机、驱动能力 15 A、栅极驱动器 DRV8703-Q1 耐压 47 V、两颗 DRV5013-Q1 锁存霍尔构成位置编码（带宽 30 kHz）、支持防夹检测与反接保护 |
| Anti-Pinch Window Lift Reference Design（防夹车窗升降参考设计，与同济大学合作开发） | 恩智浦半导体（NXP Semiconductors N.V.） | 方案编号 RDS12VR；资料单文件 RDS12VRFS.pdf；年份待核实 | https://www.nxp.com/docs/en/fact-sheet/RDS12VRFS.pdf ；社区条目 https://community.nxp.com/t5/NXP-Designs-Knowledge-Base/RDS12VR-Anti-Pinch-Window-Lift-Reference-Design/ta-p/1116886 | 资料单 PDF + 软硬件包 + 参数设置图形界面 | 待核实（PDF 超 10 MB 抓取失败）。特征：S12 MagniV S12VR 混合信号微控制器、霍尔与电流采样双判据防夹、**防夹区间与防夹力可调**、防夹区外做堵转检测 |
| S12VR Window Lift StarterTRAK Reference Design（车窗升降与继电器式直流电机控制入门套件） | 恩智浦半导体 | 套件编号 TRK-S12VR-WLFT-1 | https://www.nxp.com/design/design-center/development-boards-and-designs/s12vr-window-lift-startertrak-reference-design:TRK-S12VR-WLFT-1 | 开发板 + 配套文档 | 待核实 |
| Window Lift with Anti-Pinch Reference Design（带防夹的车窗升降参考设计） | 微芯科技（Microchip Technology Inc.） | 开发工具编号 APGRD002 | https://www.microchip.com/en-us/development-tool/apgrd002 | 参考设计板 + 应用笔记 | 待核实（该页对自动抓取返回 HTTP 403，仅由搜索结果确认存在） |
| TLE9855QX Window Lift Reference Design Guide，v01_01 | 英飞凌科技（Infineon Technologies AG），此处经贸泽电子（Mouser Electronics）镜像发布 | v01_01，年份待核实 | https://www.mouser.com/pdfDocs/Infineon-TLE9855QX_Window_Lift_Reference_Design_Guide_Preview-UserManual-v01_01-EN.pdf | 参考设计指南 PDF（预览版） | 待核实（infineon.com 本域在本次环境中被网络策略拦截） |
| Smart window lift module（智能车窗升降模块应用页，MOTIX™ TLE985x 系列 H 桥 MOSFET 驱动片上系统） | 英飞凌科技 | 无文档号 | https://www.infineon.com/cms/en/applications/automotive/body-electronics-and-lighting/comfort-convenience-electronics/smart-window-lift-module/ | 应用页 + 器件数据手册入口 | 待核实。特征：12 V 电机控制片上系统、Arm Cortex-M0 内核、片上电池电压与温度测量、自适应栅极电流控制 |
| Automotive Brushed-Motor Ripple Counter Reference Design（车规有刷电机纹波计数参考设计） | 德州仪器 | 设计指南文档号 TIDUD30A；关联设计 TIDA-01421 | https://www.ti.com/lit/ug/tidud30a/tidud30a.pdf ；https://www.ti.com/tool/TIDA-01421 | 设计指南 PDF | 待核实。原理：电机电流交流分量中的纹波与换向器极经过电刷一一对应，纹波频率正比于实际转速，可转成数字口可计的脉冲 |

### 3.3 测试保护与安全联锁（对应"不能违背的原则"配置项）

来源分两层：被测件自身的保护判据，和试验台架对人与设备的安全要求。

**第一层：被测件保护判据**

| 保护项 | 判据 | 来[源] | 可信度 |
|---|---|---|---|
| 过压 | 施加 16.5 V，按图 2 跑 10 个工作循环后基本性能仍合格 | QC/T 626 征求意见稿 6.11.1 | 待核实 |
| 长时过电压 | 12 V 系统施加 18 V 持续 60 min，环境温度为 Tmax 减 20 K，要求最低功能状态 class C | ISO 16750-2:2023 §4.3.1.1.2 | 已核实 |
| 跨接启动 | 12 V 系统施加 26 V 持续 60 ± 6 s，最低功能状态 class C | ISO 16750-2:2023 §4.3.1.2.2 表 5 | 已核实 |
| 瞬态过电压 | 12 V 系统 18 V 持续 400 ms、上升与下降 1 ms、间隔 1 s、5 次，要求最低 class B | ISO 16750-2:2023 §4.3.2.2 表 6 | 已核实 |
| 反极性 | 10.8 V 到 −4.0 V，持续 60 s（若继电器在极性反接时切断供电则改为 8 ms），3 个循环。**标准原文明确要求反极性期间不得触发任何安全相关功能，并点名电动车窗、天窗、起动机** | LV 124 / VW 80000 试验 E-15 | 已核实 |
| 堵转电流 | ≤ 28 A（常温）；80 ℃ 时 ≤ 29 A；−30 ℃ 时 ≤ 30 A | QC/T 626 征求意见稿 5.4.1 b)、表 1、表 3 | 待核实 |
| 热保护（首次启动 / 恢复 / 再启动） | −40 ℃ 与常温：首次启动 ≥30 循环、恢复 ≤60 s、再启动 ≥2 循环；80 ℃：首次启动 ≥15 循环、恢复 ≤100 s、再启动 ≥2 循环 | QC/T 626 征求意见稿表 5 | 待核实 |
| 绝缘介电强度 | 550 V、50 Hz 正弦交流，历时 1 min；批量生产可用 660 V / 1 s 替代 | QC/T 626 征求意见稿 6.12.2 | 待核实 |
| 绝缘电阻 | 500 V 直流、60 s；试前须经交变湿热预处理并干燥 30 min | LV 124 试验 E-18 | 已核实 |
| 短路 | 每个引脚单独对地与对电源各短路 60 s | LV 124 试验 E-17 | 已核实 |
| 防夹力 | 开口 4 mm 至 200 mm 范围内，在夹紧力大于 100 N 之前必须回缩 | GB 11552-2009 §4.8.3.1.1 | 已核实（本次从条文 PDF 直接提取） |

**第二层：台架与人员安全（Agent 自动加载、自动切换工况、自动施加过压与堵转时必须满足）**

| 标准编号 | 全名 | 机构 | 年份 | 关键内容 | URL | 可信度 |
|---|---|---|---|---|---|---|
| GB/T 5226.1-2019 | 机械电气安全 机械电气设备 第1部分：通用技术条件 | 国家市场监督管理总局与国家标准化管理委员会 | 2019-06-04 / 2020-01-01，现行，代替 GB 5226.1-2008，**等同采用 IEC 60204-1:2016** | 适用于额定电压不超过交流 1000 V 或直流 1500 V 的机械电气设备；含电源断路开关、电击防护、控制电路与控制功能、电动机及相关设备、标志与警告标识 | https://www.ndls.org.cn/standard/detail/eb10a2db1aab4da873d16f763009371a | 已核实。注意前缀由 GB 改为 GB/T，即由强制性改为推荐性 |
| GB/T 15706-2012 | 机械安全 设计通则 风险评估与风险减小 | 国家标准化管理委员会 | 2012，现行，以翻译法等同采用 ISO 12100:2010 | A 类基础安全标准，规定风险评估与风险减小的原则与方法 | https://std.samr.gov.cn/gb/search/gbDetailed?id=7E2903B0D76C5A63E05397BE0A0AF660 | 已核实 |
| ISO 13849-1:2023 | Safety of machinery — Safety-related parts of control systems — Part 1: General principles for design（机械安全 控制系统安全相关部件 第1部分：设计通则） | 国际标准化组织 ISO | 2023，代替 2015 版 | 性能等级 PL 分 a 至 e 五档，每档对应一个每小时危险失效平均概率区间 | https://www.iso.org/standard/73481.html | 已核实 |
| IEC 62061:2021 | Safety of machinery — Functional safety of safety-related control systems（机械安全 安全相关控制系统的功能安全），第 2.0 版 | 国际电工委员会 IEC | 2021，取代 2005 第 1 版及其两个修订案 | 2021 版不再限于电气系统，可用于液压、气动等所有技术类型；新增功能安全计划与周期性测试要求 | https://webstore.iec.ch/en/publication/59927 | 已核实 |
| ISO 14119:2024 | Safety of machinery — Interlocking devices associated with guards — Principles for design and selection（机械安全 与防护装置相关的联锁装置 设计与选择原则） | ISO | 2024，代替 2013 版 | 2024 版在原四类基础上新增第 5 类钥匙转移式联锁装置，适合"必须先切断动力才能开门"的工位 | https://www.iso.org/standard/75942.html | 已核实 |
| IEC 61010-1 | Safety requirements for electrical equipment for measurement, control, and laboratory use — Part 1: General requirements（测量、控制和实验室用电气设备的安全要求 第1部分：通用要求） | IEC | 第 3 版 2010；合订版 Ed. 3.1 b:2017 | 适用于标称供电电压不超过交流 1000 V 或直流 1500 V 的设备 | https://webstore.iec.ch/en/publication/4279 | 已核实。中国对应的 GB 4793.1-2007 等同于 IEC 61010-1:2001，**落后两代** |
| ISO/IEC 17025:2017 | General requirements for the competence of testing and calibration laboratories（检测和校准实验室能力的通用要求），第 3 版 | ISO 与 IEC 联合 | 2017 | 实验室能力、公正性与运行一致性的通用要求；第 7.8 条规定报告必含要素 | https://www.iso.org/standard/66912.html | 已核实 |

> 说明：把上述机械安全标准落到"Agent 自动施加过压、堵转、短路"这一具体场景（先按 GB/T 15706 做风险评估，再按 ISO 13849-1 定性能等级或按 IEC 62061 定安全完整性等级，防护门联锁按 ISO 14119 选型）是**基于标准适用范围的推断，不是任何一本标准的原文结论**。

---

## 四、流程 3 · 测试需求确认：可量化判据表

### 4.1 主选产品：玻璃升降器完整判据（整表待核实，来源为 §2.1 的征求意见稿 PDF）

| 试验项目 | 条款 | 条件 | 合格判据 |
|---|---|---|---|
| 基本性能 | 5.4.1 / 6.4.1 | 试验电压 13.5 ± 0.3 V，常温 23 ± 2 ℃ | 见 §3.1 参数表 |
| 自锁性 | 5.5 / 6.5 | 上止点与半行程两处，垂直向下 600 N 保持 5 s | 托架下降量 ≤ 5 mm，且不损坏 |
| 耐高温特性 | 5.6.1 / 6.6.1 | 80 ℃ 放置 2 h 后，在该温度下空载不堵转运行 5 个工作循环 | 上升工作电流 ≤12 A、下降 ≤7 A；堵转电流 ≤29 A；堵转力 ≥164 N；上升速度 80–160 mm/s、下降 ≤200 mm/s；启动电压 ≤9 V |
| 耐低温特性 | 5.6.2 / 6.6.2 | −30 ℃ 放置 2 h 后同上 | 上升工作电流 ≤20 A、下降 ≤16 A；堵转电流 ≤30 A；堵转力 ≥190 N；上升速度 ≥60 mm/s、下降 ≥70 mm/s；启动电压 ≤10 V |
| 耐振动性 | 5.7 / 6.7 | 按 QC/T 413-2002 的扫频振动条件 | 试验后仍符合 5.4 条 |
| 耐腐蚀性 | 5.8 / 6.8 | 按 GB/T 10125-2012 中性盐雾 120 h | 工作电压项须合格；电流、堵转力、速度、噪音四项允许与试验前偏差 20 %；黑色金属零件主要表面无基体腐蚀物 |
| 耐久性（电动，前门） | 5.9.1 / 6.9.1 表 7 | 最大额定负载，13 道工序：常温 3000 次 → 80 ℃ 1500 → 60 ℃/90 %RH 2500 → 10 ℃/95 %RH 1000 → −30 ℃ 1000 → 常温 1000，各段之间喷洒泥水 | 累计 10 000 个循环周期；试验后功能正常、无异响跳齿打滑卡滞，塑料件无裂纹；性能允许偏差 20 % |
| 耐久性（电动，后门） | 同上 | 各段次数减半 | 累计 5 000 个循环周期 |
| 耐久试验预处理 | 6.9.1 表 7 序号 2 | 托架升至上止点堵转 1 s、切断电源、90 ℃ 环境放置 2 h | — |
| 耐久泥水配比 | 6.9.1 注 | 92.5 % 蒸馏水或去离子水 + 7.5 % 粉尘；粉尘按 ISO 12103-1 取 50 % A2 + 50 % A4 | — |
| 耐久单循环波形 | 6.9.1 注 3 | 起始位置 → 上止点堵转 1 s 停 4 s → 1/3 位置 → 下止点堵转 1 s 停 4 s，末次停 60 s | 试验中允许对电机风冷或水冷 |
| 耐高温高湿放置 | 5.10 / 6.10 | 上止点堵转 1 s 关电源，80 ℃ / 90 %RH 放置 480 h，取出后常温加最大额定负载跑 100 个工作循环 | 零部件无裂纹融解；性能允许偏差 20 % |
| 耐过负载操作强度 | 5.11.1 / 6.11.1 | 最大额定负载下施加 16.5 V，跑 10 个工作循环 | 试验后基本性能合格 |
| 防水性 | 5.12.1 / 6.12.1 表 9 | 喷水压力 0.1 MPa、孔径 φ1.2 mm、孔数 40、喷水量 20 L/min、时间 30 min | 拆机后电机内部不应进水 |
| 绝缘介电强度 | 5.12.2 / 6.12.2 | 550 V / 50 Hz / 1 min；批量可用 660 V / 1 s | 绝缘不被击穿 |
| 热保护性 | 5.12.3 / 6.12.3 表 5 | 最大额定负载，分 −40 ℃、常温、80 ℃ 三档 | −40 ℃ 与常温：首次启动 ≥30 循环、恢复 ≤60 s、再启动 ≥2 循环；80 ℃：首次启动 ≥15 循环、恢复 ≤100 s、再启动 ≥2 循环 |
| 电磁兼容性 | 5.12.4 / 6.12.4 | 辐射发射、传导发射、瞬态传导发射 | 辐射与传导发射满足 GB/T 18655-2010 等级 3；瞬态传导发射满足 GB/T 21437.2-2008 等级 III。**两本引用标准均已换版，落地时须改引 GB/T 18655-2025 与 GB/T 21437.2-2021** |
| 有害物质 | 5.3 / 6.3 | 按 GB/T 30512-2014 | 铅、汞、镉、六价铬、多溴联苯、多溴二苯醚含量合格 |

### 4.2 防夹功能判据：三地法规对照（这是本案例最有演示价值的一屏）

三地在 100 N 与 4–200 mm 上完全一致，差异在试验棒刚度与回缩后位置。

| 法规 | 完整名称与发布机构 | 防夹力限值 | 开口范围 | 回缩后要求 | 试验棒刚度 | URL | 可信度 |
|---|---|---|---|---|---|---|---|
| GB 11552-2009 §4.8.3.1 | 《乘用车内部凸出物》，国家质量监督检验检疫总局与国家标准化管理委员会发布，工业和信息化部归口，适用 M1 类 | 夹紧力大于 100 N 之前必须回缩 | 开口从 200 mm 到 4 mm | 四选一：允许穿过开口放置直径 200 mm 的半刚性柱状试验棒的位置；关闭之前的最初位置；比开始回缩时至少多开 50 mm 的位置；天窗倾斜运动时为最大角度开启位置 | (10 ± 0.5) N/mm | https://law.resource.org/pub/cn/ibr/gb.11552.c.2009.pdf | **已核实**，本次从条文 PDF 文本层逐字提取 |
| FMVSS 118（49 CFR § 571.118） | Standard No. 118; Power-operated window, partition, and roof panel systems，美国国家公路交通安全管理局 NHTSA。适用于乘用车、多用途乘用车、总重 4 536 kg 及以下卡车 | 在接触试验棒之前，或在对半刚性圆柱试验棒施加 100 N 及以上挤压力之前，须停止并反向 | 4 mm 至 200 mm | 制造商二选一：至少开到关闭开始时的位置；或比反向时的位置至少多开 125 mm | 25–200 mm 试棒取 20 N/mm（待核实） | https://www.ecfr.gov/current/title-49/subtitle-B/chapter-V/part-571/subpart-B/section-571.118 | 100 N 与 4–200 mm 已核实；条款编号 S4/S7/S8 待核实 |
| UN ECE R21 §5.8 | Uniform Provisions Concerning the Approval of Vehicles with Regard to Their Interior Fittings，联合国欧洲经济委员会 UNECE | 不超过 100 N | 上边缘上方 200 mm 至 4 mm | 三种可选位置之一 | 10 N/mm（待核实） | https://unece.org/DAM/trans/main/wp29/wp29wgs/wp29grsp/grspinf/28/28-inf01.pdf | 待核实 |

**无防夹功能时的替代要求（GB 11552-2009 §4.8.2，已核实）**：电动车窗从开口不超过 4 mm 处开始关闭时允许关闭；遥控关闭的作用距离不超过 6 m，车辆可直接看见时不超过 11 m；仅驾驶员侧车门与天窗、且仅在点火钥匙处于发动机运转位置期间可一键关闭。

**一条对项目定位有影响的事实**：中国、美国、欧洲三地现行法规**都不强制要求配备防夹功能**，只在配备时才对其性能作规定（来源为智能汽车资源网法规解读页 https://www.smartautoclub.com/p/50318/ ，待核实）。这意味着"是否测防夹"本身就是测试需求确认这一步要由 Agent 与用户确认的分支条件，正好构成一个可演示的决策节点。

### 4.3 可跨场景复用的通用判据（知识库二级层，两个案例共享）

**ISO 16750-2:2023 供电电压代码（已核实，来自标准正式预览件开放正文页）**

| 系统 | 代码 | 电压范围 |
|---|---|---|
| 12 V | A | 6 至 16 V |
| 12 V | B | 8 至 16 V |
| 12 V | **C** | **9 至 16 V**（玻璃升降器与刮水电动机均落在此档） |
| 12 V | D | 10.5 至 16 V |
| 24 V | E | 10 至 32 V |
| 24 V | F | 16 至 32 V |
| 24 V | G | 22 至 32 V |
| 24 V | H | 18 至 32 V |

**ISO 16750-4:2023 工作温度代码（已核实）**：代码 A 为 −20/65 ℃、B 为 −30/65 ℃、**C 为 −40/65 ℃**，代码 D 至 J 的上限依次为 70、75、80、85、90、95、100 ℃。低温贮存 −40 ℃ / 24 h（要求 class C）；高温贮存 85 ℃ / 48 h（class C）；高温工作 Tmax / 96 h（class A）；温度阶梯试验步长 5 ℃；温度循环（小而轻被测件）30 个循环，单循环 480 min。

**VW 80000 机械试验 M-04 谱型 D（簧上质量挂装件，已核实）**：宽带随机振动，每轴 8 h，加速度均方根 30.8 m/s²，功率谱密度折点 [(m/s²)²/Hz] 为 5 Hz 0.884、10 Hz 20、55 Hz 6.5、180 Hz 0.25、300 Hz 0.25、360 Hz 0.14、1000 Hz 0.14、2000 Hz 0.14。**车门上的玻璃升降器正属于这一类安装位置。**

**VW 80000 机械试验 M-06 连续机械冲击（已核实）**：峰值 300 m/s²、6 ms 半正弦。冲击次数按安装位置分档——**驾驶员车门 100 000 次、副驾及后门 50 000 次**、行李厢盖与尾门 30 000 次、发动机罩 3 000 次。这一条对车门件是直接适用的耐久判据。

**AEC-Q100 Rev J1 温度等级与关键应力条件（已核实）**

| 等级 | 温度范围 | 温度循环 A4 | 高温工作寿命 B1 |
|---|---|---|---|
| Grade 0 | −40 至 +150 ℃ | −55 至 +150 ℃，1500 循环 | +150 ℃ / 1000 h |
| Grade 1 | −40 至 +125 ℃ | −55 至 +150 ℃，1000 循环 | +125 ℃ / 1000 h |
| Grade 2 | −40 至 +105 ℃ | −55 至 +125 ℃，1000 循环 | +105 ℃ / 1000 h |
| Grade 3 | −40 至 +85 ℃ | −55 至 +125 ℃，500 循环 | +85 ℃ / 1000 h |

静电放电目标：人体模型 2 kV（AEC-Q100-002）；充电器件模型角引脚 750 V、其余引脚 500 V（AEC-Q100-011）。

### 4.4 备选产品判据（候选 A 雨刮电机，全部已核实，供切换时直接启用）

来源为 QC/T 29090-2023《汽车用刮水电动机》标准全文 PDF（工业和信息化部发布，SAC/TC 114 归口，2023-04-21 发布 / 2023-11-01 实施，代替 QC/T 29090-1992），详情页 https://hbba.sacinfo.org.cn/stdDetail/fa7c67530404b45b4a1d5352bd5af5016d98d799798d2fd0b4edd58ab79d4f22 。

| 试验项目 | 条款 | 参数与判据 |
|---|---|---|
| 工作温度 | 4.2.1 表 1 | −40 ℃ 至 +85 ℃ |
| 贮存温度 | 4.2.1 表 1 | −40 ℃ 至 +95 ℃ |
| 工作电压 | 4.2.2 表 2 | 12 V 系统 9 至 16 V；24 V 系统 16 至 32 V |
| 试验环境 | 5.1.2 表 4 | 23 ± 5 ℃、45 % 至 75 %RH、86 至 106 kPa |
| 性能参数体系 | 4.4 | 三组：空载电流与空载转速；负载电流、负载转速、负载转矩；堵转转矩与堵转电流。负载转矩定义为标称转矩的 15 %，双速电机高速挡取 10 % |
| 噪声 | 4.14 表 3 / 5.14 | 低速 1 级 50 dB(A)、2 级 55 dB(A)；高速 1 级 55 dB(A)、2 级 60 dB(A)；带两级齿轮减速允许大 3 dB(A)。全消声室、背景噪声低于 37.5 dB(A)、弹性绳悬挂距地 1 m、传声器置于输出轴端面正前方 300 mm |
| 温升 | 4.15 / 5.15 | 环境温度不大于 40 ℃，低速带负载转矩连续运转，每 30 min 测一次、30 min 内变化不超过 1 ℃ 为稳定；磁极处外壳表面温升不高于 60 K |
| 停位角 | 4.16 / 5.16 | 负载转矩下运行 30 min 后，旋转式与往复式输出电机的停位角变化范围均在 ±6° 内 |
| 防护等级 | 4.17 | 前刮水电机 IP5K4K；后刮水电机 IP5KX（按 GB/T 30038-2013，以实车装配状态试验） |
| 堵转 | 4.18 / 5.18 | 试验电压下连续通电 30 s 堵转，试验后不损坏且性能符合 4.4 |
| 堵转耐久 | 4.19 / 5.19 | 通电 1 s、断开 59 s 为一循环，共 10 000 次 |
| 耐久性能（前刮水电机） | 4.21 / 5.21 | 低高速循环运转，从低速开始每 25 万次变速一次，不允许更换零部件；50 万次后性能仍符合 4.4，再经 100 万次后仍可继续工作 |
| 耐久性能（后刮水电机） | 4.21 / 5.21 | 25 万次后性能仍符合 4.4，再经 50 万次后仍可继续工作 |
| 盐雾 | 4.10 / 5.10 | 按 GB/T 28046.4-2011 §5.5.1.2，前刮水电机严酷度等级 5、后刮水电机等级 4。免检部位含螺纹、输出轴滚花处、板材切割处、旋铆处 |
| 过电压 | 5.6 | 按 GB/T 28046.2-2019 §4.3，温度 65 ℃、低速挡空载，施加 18 V（12 V 系）或 36 V（24 V 系）持续 60 min |
| 耐电压 | 4.13 | 大批量连续生产时可用 660 V、1 s 替代 |
| 电磁兼容 | 4.20 | 传导发射电压法按 GB/T 18655-2018 表 5 等级 2；辐射发射按表 7 等级 2；沿电源线电瞬态传导按 GB/T 21437.2-2021 附录 C.3.7 等级 III |
| 仪器精度 | 5.1.5 | 直流稳压电源纹波系数 ≤5 %；电压表 ≥0.5 级；电流表 ≥1.0 级；转矩测量仪精度 ≥±3 % |
| 型式检验 | 6.3 | 20 个项目分 6 组，每组不少于 2 套，顺序按 GB/T 28046.1-2011 附录 A.1 |
| 出厂检验 | 6.2 | 按 GB/T 2828.1-2012，一般检查水平 II，接收质量限 0.4 至 4.0，一次正常检查抽样方案 |

---

## 五、流程 4 · 启动测试与结果分析：公开数据集与波形

### 5.1 核心结论先说

**汽车低压执行器电机（雨刮、车窗、天窗、座椅、EPS、节气门）的专用公开波形数据集，在十三个平台上确认为空白。** 这是检索证实的结论，不是遗漏，详见 §7.3。因此本案例的数据方案必须是三层结构：车用工况级慢速时序（真实但低采样率）+ 波形级相电流（真实但非汽车执行器）+ 参数化仿真合成（补齐执行器空白）。

### 5.2 第一层：真实实测，车用或准车用

| 素材 | 来源全名 | URL | 数据内容 | 可用形态 | 可信度 |
|---|---|---|---|---|---|
| Electric Motor Temperature（车用永磁同步电机台架温度与电气量数据集） | 采集方为德国帕德博恩大学电驱动系统教研室（Universität Paderborn, Lehrstuhl für Elektrische Antriebssysteme, LEA）；Kaggle 账号 wkirgsn（Wilhelm Kirchgäßner）发布。2018 首发，末次更新 2021-04-26 | https://www.kaggle.com/datasets/wkirgsn/electric-motor-temperature | 12 通道：d/q 轴电流 i_d/i_q、d/q 轴电压 u_d/u_q、转速、转矩、环境温度、冷却液温度、转子磁钢温度、定子轭/齿/绕组温度。**采样率 2 Hz**，总时长 185 小时，按 profile_id 分若干 1–6 小时会话 | CSV，约 286 MB（300 061 411 字节），**CC BY-SA 4.0，可商用，需署名 + 相同方式共享** | **已核实**（经 Kaggle 元数据接口直读标题、许可证、字节数、更新日期）。"52 kW 德国某整车厂原型机"的说法来自数据集描述文字，待核实 |
| BLDC Hub Motor Fault Detection Dataset: Multi-Rate Sampling Phase Current Measurements with Software-Injected Imbalance Faults | 爱沙尼亚塔林理工大学（Tallinn University of Technology），作者 Diana Belolipetskaja、Martin Võip、Mahmoud Ibrahim、Anton Rassõlkin，2026-08-23 | https://ieee-dataport.org/documents/bldc-hub-motor-fault-detection-dataset-multi-rate-sampling-phase-current-measurements （DOI 10.21227/ekxt-ny35） | 三相电流 A/B/C + 转矩 + 输入电压 + 转速；被测件为电动滑板车 XW48V350W 轮毂 BLDC 电机 + VESC6 控制器；**基线 100 kHz**，另降采样至 50 kHz 至 250 Hz 共 8 档；软件注入 10 %/20 %/30 % 相不平衡故障 | CSV，144 个文件，12.4 GB。**需 IEEE DataPort 订阅** | 已核实 |
| EV Starter Motor Fault Detection Using DWT Skewness and Kurtosis（汽车起动电机电枢匝间短路） | IEEE DataPort 投稿，发布机构页面未明示，2025 | https://ieee-dataport.org/documents/ev-starter-motor-fault-detection-using-dwt-skewness-and-kurtosis （DOI 10.21227/r41x-k977） | 覆盖蓄电池不同荷电状态（100 % 至约 8 %）；提供的是小波分解后的偏度/峰度特征表（ka1–ka9 / kd1–kd9），**不含原始电流波形** | .xlsx + .bib，6 张表，需订阅 | 已核实 |
| F.A.I.R. open dataset of brushed DC motor faults for testing of AI algorithms（**有刷直流电机**故障数据集） | 西班牙 CARTIF 技术中心（Fundación CARTIF，巴利亚多利德），2020 | https://zenodo.org/records/4314249 （DOI 10.5281/zenodo.4314249） | 振动(g) + 电流(A) + 电压(V)；小型有刷直流电机，故障从 30 分钟演化到 6 小时 | HDF5 + Excel，483 MB，**CC BY 4.0** | 已核实。**本次调研中离"汽车低压执行器"结构最近的真实集——雨刮、车窗、座椅电机正是有刷直流** |
| Vibration and Current Dataset of Three-Phase Permanent Magnet Synchronous Motors with Stator Faults | 韩国科学技术院（Korea Advanced Institute of Science and Technology, KAIST），2022-11-17 | https://data.mendeley.com/datasets/rgn5brrgrn/5 （DOI 10.17632/rgn5brrgrn.5） | z 向振动 25.6 kHz + 三相电流 100 kHz；1000 W / 1500 W 两档 PMSM；匝间短路与线圈间短路，多档严重度 | TDMS，**CC BY 4.0** | 已核实 |
| 帕德博恩大学轴承数据中心数据集（KAt-DataCenter Bearing Dataset，帕德博恩大学设计与传动技术教研室 Lehrstuhl für Konstruktions- und Antriebstechnik），Lessmeier 等，2016 | 德国帕德博恩大学 | 说明页 https://mb.uni-paderborn.de/kat/forschung/bearing-datacenter ；下载目录 https://groups.uni-paderborn.de/kat/BearingDataCenter/ | **电机相电流与振动加速度同步采集**；32 种轴承状态 × 4 工况，每组 20 次 × 4 秒 | MATLAB .mat，打包为 RAR，约 34 个包。**CC BY-NC 4.0，禁止商用，商用需联系作者** | 下载目录与许可证已核实；常被引用的 64 kHz 采样率官方页未明示，待核实。**若本案例属商业交付，该许可证是硬约束** |

### 5.3 存疑条目（必须先证伪或证实再用）

| 素材 | 来源全名 | URL | 疑点 |
|---|---|---|---|
| KoNAMIC Electronic Throttle Body Experimental Dataset for Nonlinear System Identification | Nicolas Bongiovanni，法国蔚蓝海岸大学（Université Côte d'Azur）与索菲亚·安蒂波利斯信息、信号与系统实验室（Laboratoire d'Informatique, Signaux et Systèmes, I3S），2026-08-25，v1.0.0，CC BY 4.0 | https://zenodo.org/records/22096081 （DOI 10.5281/zenodo.22096081） | 全网唯一命名匹配"电子节气门"的数据集，但：记录页未给出任何通道、采样率、样本数；文件仅 790 189 字节；下载量 4 次；其关联仓库 https://github.com/NBongiovanni/KoNAMIC 实际内容是四旋翼与倒立摆的 Koopman 辨识，与节气门无对应关系。**链接与许可证已核实，内容真实性存疑，使用前必须下载解包人工确认** |
| Fault Diagnosis Dataset for New Energy Vehicles | Kaggle 账号 ziya07，未标注任何机构，2024-12-14，CC0 | https://www.kaggle.com/datasets/ziya07/fault-diagnosis-dataset-for-new-energy-vehicles | 名称与通道（电压、电流、转速、温度、振动）都对口，但无台架、无车型、无机构说明；同一上传者的其他数据集在描述中自认为合成数据。**高度怀疑为合成，使用前必须下载核查物理一致性** |

已明确排除（避免后续重复捞）：SiCWell Dataset（IEEE DataPort, DOI 10.21227/mnmw-8c42，实为车规锂电池单体数据，不含电机量）；ziya07/bldc-motor-dataset（页面自认 synthetic，且为设计参数表）；sabermalek/imfds（Kaggle 链接 404）；Three Phase Induction Motor Stator Fault Data（IEEE DataPort, DOI 10.21227/0kwj-g017，平台标注数据文件尚未上传）；Brushless DC Motor sound dataset for PdM（Mendeley, j4yr5fmhv4，实为无人机 A2212 电机音频）。

### 5.4 第二层：参数化仿真合成（本案例的实际主路径）

| 素材 | 来源全名 | URL | 能生成什么 | 许可证 | 可信度 |
|---|---|---|---|---|---|
| gym-electric-motor（GEM），电机控制强化学习仿真环境 | 德国帕德博恩大学电驱动系统教研室（Universität Paderborn, LEA） | https://github.com/upb-lea/gym-electric-motor | abc 与 dq 三相电流、转速、转矩、端电压、直流母线电压；内置逆变器与负载模型；支持永磁同步机、同步磁阻机、电励磁同步机、鼠笼异步机、双馈异步机与多种直流电机；时间步长可配（微秒至毫秒级） | **MIT** | 已核实（仓库活跃，427 星 / 1157 次提交）。定子电阻、电感、极对数、额定电压与电流全部开放为参数，可直接配到 12 V 车用量级 |
| Simscape Electrical — Electric Power Assisted Steering（电动助力转向示例） | MathWorks | https://www.mathworks.com/help/sps/ug/electric-power-assisted-steering.html | 永磁同步电机放大驾驶员转向力矩；示波器输出逆变器电压与电流波形，以及驾驶员/助力/总力矩波形 | 需 MATLAB + Simscape Electrical 商业授权 | 已核实。**唯一开箱即为车规场景的模型**，若项目已有 MATLAB 授权，优先级高于开源方案 |
| PyLEECAN（PYthon Library for Electrical Engineering Computational ANalysis） | 法国 EOMYS ENGINEERING 发起，现由 Green Forge Coop 支持 | https://github.com/Eomys/pyleecan | 耦合有限元求解器 FEMM 做电磁仿真，输出磁场、转矩、损耗 | **Apache 2.0** | 已核实。偏电机本体设计，要产出传感器级时序需自建电路外壳 |
| ITSC — 三相感应电机匝间短路故障电流数据集（含读取脚本） | GitHub 账号 ibarram；被测件 Baldor CM3542（0.75 hp） | https://github.com/ibarram/ITSC | 三相电流实测；健康 + 12 种故障（3 相 × 10/20/30/40 % 严重度）；1 kHz 采样，每次 5 秒，60 Hz 空载稳态，每工况重复 5 次；附 Python/MATLAB/R/C 读取脚本 | **MIT** | 已核实（全部字段） |
| C2000Ware MotorControl SDK（含 InstaSPIN-FOC 有感与无感磁场定向控制方案） | 德州仪器 | https://www.ti.com/tool/C2000WARE-MOTORCONTROL-SDK | BLDC/PMSM 电流环与速度环例程；InstaSPIN Universal GUI 可监测电流、转速、转矩估计等内部变量 | SDK 免费下载，配合免费的 Code Composer Studio | 已核实 |
| X-CUBE-MCSDK（STM32 电机控制软件开发包）+ ST Motor Pilot | 意法半导体（STMicroelectronics N.V.） | https://www.st.com/en/embedded-software/x-cube-mcsdk.html | Motor Pilot 支持实时绘图，右键选寄存器变量生成标准图与 XY 图，可记录电流、转速等控制量 | 免费下载，ST 自有软件许可协议 | 已核实 |

### 5.5 第三层：参数化到汽车量级的公开参数锚点

| 电机类型 | 可引用参数 | 来源与 URL | 可信度 |
|---|---|---|---|
| 玻璃升降器 | 工作电流 ≤12 A、堵转电流 ≤28 A、堵转力 ≥212 N、上升速度 80–160 mm/s、工作电压 9–16 V | QC/T 626 征求意见稿，https://www.catarc.org.cn/upload/201807/13/201807131600519972.pdf | 待核实（征求意见稿） |
| 车用电子水泵 | Pierburg CWA200：工作电压 8–16 V，额定电流 15 A（最大 16.5 A），转速约 18–4500 rpm，流量 116 L/min @0.45 bar。CWA150：9–16 V，约 56–6692 rpm。CWA400：额定 35.5 A（最大 36.3 A），约 5900 rpm | Pierburg GmbH（隶属莱茵金属 Rheinmetall 集团）原厂数据手册，https://www.tecomotive.com/download/datasheets/CWA200_EN.pdf | 待核实（数值来自搜索摘要转述，未逐字段比对 PDF 原文） |
| 雨刮电机 | 额定电流约 2–4 A，正常挡约 45 rpm、快挡约 65 rpm | 二手聚合站点；配套测试设备手册见 Magtrol 雨刮电机测试系统 https://www.magtrol.com/wp-content/uploads/cmts-wiper.pdf （PDF 为图形排版，文字层无法提取） | 待核实 |
| 电动助力转向电机 | 两个量级口径并存：大功率无刷交流机约 85 A @12 V；小功率 12 V BLDC 典型为空载电流 0.15 A、额定电流 4.2 A、额定转速 3000 rpm、额定转矩 0.16 N·m、堵转转矩 0.45 N·m、额定功率 50 W | 行业科普页与 ABLIC 官网；原始出处指向 SAE Technical Paper 2001-01-819（未取全文） | 待核实。两个口径差 20 倍，说明选参数前须先定车型与助力级别 |

---

## 六、流程 5 · 调优确认及运行：可调参数与调优经验

### 6.1 防夹算法调参（主选产品专属，本流程的主戏）

| 素材 | 来源全名 | URL | 可提炼的可调参数 | 可信度 |
|---|---|---|---|---|
| Automatic Threshold on Current based Anti-pinch Mechanism for Power Windows（基于电流的电动车窗防夹机构自动阈值方法） | 刊于 International Journal of Electrical and Computer Engineering (IJECE)，2018 | https://ijece.iaescore.com/index.php/IJECE/article/view/7702 ；另有 ResearchGate 条目 https://www.researchgate.net/publication/326403597 | 电流突变门限的自适应设定方法；阈值随工况自整定 | 待核实（未打开正文逐字确认） |
| Practical pinch detection algorithm for low-cost anti-pinch window control system（低成本防夹车窗控制系统的实用夹持检测算法） | IEEE 会议论文 | https://ieeexplore.ieee.org/document/1600781 | 基于转矩变化率（torque rate）的检测判据；文中指出转矩变化率对电机参数不确定性的敏感度低于转矩或角速度本身 | 待核实 |
| Power Window Anti-Pinch Control Based on Hall Pulse Signal and Mechanical Power（基于霍尔脉冲信号与机械功率的车窗防夹控制） | 收录于 Atlantis Press，ICMSE 2018 会议论文集 | https://www.atlantis-press.com/proceedings/icmse-18/25895047 | 霍尔脉冲计数与机械功率联合判据 | 待核实 |
| Research on Anti-pinch Control Strategy of Window Start-up Phase based on Ripple Motor（基于纹波电机的车窗启动阶段防夹控制策略研究） | ResearchGate 条目，2021 | https://www.researchgate.net/publication/349300884 | **启动阶段**的防夹策略——启动瞬间的浪涌电流会掩盖夹持特征，是防夹算法最难的一段，也是调参重点 | 待核实（未确认期刊/会议全名与作者） |
| Automotive Brushed-Motor Ripple Counter Reference Design | 德州仪器，设计指南 TIDUD30A；关联设计 TIDA-01421 | https://www.ti.com/lit/ug/tidud30a/tidud30a.pdf | 纹波提取的高通/带通滤波参数、比较器迟滞、脉冲整形门限；纹波频率对应换向器极数，为 2N（N 为绕组对数） | 待核实 |
| Anti-Pinch Window Lift Reference Design（RDS12VR） | 恩智浦半导体 | https://www.nxp.com/docs/en/fact-sheet/RDS12VRFS.pdf | 官方明示可调项：**防夹区间**与**防夹力**；防夹区外切换为堵转检测 | 待核实 |

**由上述材料可整理出的防夹调参清单（本文档的综合，非任一来源原文）**

| 参数 | 典型作用 | 调大的后果 | 调小的后果 |
|---|---|---|---|
| 防夹力阈值 | 判定夹持的力门限 | 逼近或超出 100 N 法规上限，判定不合格 | 误触发率升高，正常密封阻力被误判为夹持 |
| 防夹生效区间（行程窗口） | 法规要求 4–200 mm 有效 | 进入密封压紧段仍生效，无法正常关窗 | 下沿高于 4 mm 则不合规 |
| 启动段屏蔽时间 | 屏蔽启动浪涌电流 | 启动瞬间夹持漏检 | 浪涌被误判为夹持 |
| 纹波计数滤波带宽与迟滞 | 从电流交流分量提取转速脉冲 | 低速段丢脉冲，位置累计误差 | 引入噪声计数，位置漂移 |
| 堵转判定电流门限与去抖时间 | 区分到达上止点与遇障 | 遇障后仍继续加力，力峰值超标 | 到达上止点被误判为夹持，无法关到位 |
| 回缩行程量 | 回缩后的开口 | 无风险，但用户体验差 | 低于 50 mm 或未达法规要求的三种位置之一则不合规 |

### 6.2 通用电机调参（跨场景复用，备选产品也用得上）

| 素材 | 来源全名 | URL | 可提炼参数 | 可信度 |
|---|---|---|---|---|
| Motor Control Application Framework (MCAF) 文档 5.1.6 节 Current loop tuning（电流环整定） | 微芯科技（Microchip Technology Inc.），MCAF R7 RC37 文档，版本 7.0.2 | https://microchiptech.github.io/mcaf-doc/7.0.2/algorithms/foc/tuning.html | 见下表 | **已核实**（本次调研中唯一给出"参数名 + 默认值 + 推荐区间 + 增减后果"完整闭环的公开文档） |
| UM3259 — STM32 motor control SDK: 6-step firmware sensorless parameter optimization | 意法半导体 | https://www.st.com/resource/en/user_manual/um3259-stm32-motor-control-sdk--6step-firmware-sensorless-parameter-optimization-stmicroelectronics.pdf | 对齐与启动、单段或多段加速斜坡；大惯量电机先缓斜坡后陡斜坡 | 待核实（抓取超时） |
| STM32 Motor Control Frequently Asked Questions | 意法半导体 STM32 微控制器 Wiki | https://wiki.stmicroelectronics.cn/stm32mcu/wiki/STM32MotorControl:Frequently_Asked_Questions | 启动调参口径：将 Speed ramp final value 提高到最大应用转速的 40 %，将 Minimum startup output speed 降到 10 % | 待核实 |
| iMOTION™ Motion Control Engine Software Reference Manual（含 MCEWizard 全部可配参数），V 1.34，2021-09-17，203 页 | 英飞凌科技，社区镜像 | https://community.infineon.com/gfawx74859/attachments/gfawx74859/jpmotixmcu/693/1/Infineon-MCESW-RM-UserManual-v01_03-EN.pdf | IS_Pulses、IS_Duty、IS_IqInit（由 MCEWizard 自动计算）；初始角检测按六个角度注入电流脉冲；过压/欠压保护、过流检测、堵转防护 | 待核实（infineon.com 本域被拦截，走社区镜像） |
| How to Reduce Motor Noise with Code-Free, Sensorless FOC（用免代码无感磁场定向控制降低电机噪声） | 德州仪器，文献号 SLLA567 | https://www.ti.com/lit/an/slla567/slla567.pdf | 自动死区补偿、PWM 调制方式对声学表现的影响 | 待核实 |
| Driving Brushed DC Motors Using PWM Output: Losses and Points to be Noted（用 PWM 驱动有刷直流电机：损耗与注意事项） | 罗姆半导体（ROHM Co., Ltd.）TechWeb 技术专栏，条目 346 | https://techweb.rohm.com/product/motor/motor-types/346/ | 死区的必要性与死区导致的损耗；开关损耗与效率折中 | 待核实 |

**Microchip MCAF 7.0.2 电流环整定参数（已核实，可直接写进调优页）**

| 参数 | 文档中的变量名或口径 | 默认与推荐区间 | 调整后果 |
|---|---|---|---|
| 电流环比例增益 Kp | `motor.idCtrl.kp`、`motor.iqCtrl.kp` | 由下面两项设计指标反算 | 决定对电流误差的即时电压响应 |
| 电流环积分增益 Ki | `motor.idCtrl.ki`、`motor.iqCtrl.ki` | 同上 | 决定向给定值收敛的速度 |
| 相位裕度 φm | 设计指标 | 默认 80°，实测后推荐 50° 至 70° | 调小则 Kp 与 Ki 同时变大，响应更快但超调风险升高；调大则增益下降、稳定性提高、带宽降低 |
| PI 在穿越频率处的相位滞后 φz | 设计指标 | 默认 45°，实测后推荐 8° 至 20°，低于 5° 不建议 | 调小则 Kp 变大、Ki 变小，短期响应改善 |
| 电流环带宽 | 设计指标 | 典型取 PWM 频率的 5 % 至 15 %（20 kHz PWM 对应 1 至 3 kHz）；良好整定目标约为采样率的 1/10 | 约束条件：机械时间常数 × 带宽须大于 1 |

同一文档另外明确：无感位置估计器本身会给换相角引入误差；若正常启动时序跑不通或无法正确切入闭环换相，电流环整定需在开环换相下进行。这一条直接规定了"先整定电流环、再调开闭环切换"的调优顺序。

---

## 七、流程 6 · 测试报告及产出：模板与范例

### 7.1 可直接下载的真实官方报告样张（本案例最强的一环）

| 素材 | 来源全名 | URL | 可用形态 | 可信度 |
|---|---|---|---|---|
| REPORT NUMBER 118-GTL-11-002, SAFETY COMPLIANCE TESTING FOR FMVSS NO. 118, POWER-OPERATED WINDOW, PARTITION AND ROOF PANEL SYSTEMS — 2011 NISSAN JUKE S MPV, NHTSA NO. CB5201 | 检测方 General Testing Laboratories, Inc.（1623 Leedstown Road, Colonial Beach, Virginia 22443）；委托方 美国交通部国家公路交通安全管理局车辆安全合规办公室（U.S. DOT / NHTSA, Office of Vehicle Safety Compliance, NVS-220）。项目工程师 Grant Farrand，项目经理 Debbie Messick。最终报告日期 2011-03-17，试验日期 2011-03-15，合同号 DTNH22-06-C-00032 | https://www.carsandracingstuff.com/library/reports/5683.pdf | **36 页 PDF 全文在手**（本次已下载并提取文本），结构见 §7.2 | 已核实 |
| REPORT NUMBER 118-GTL-20-003（2020 Ford Explorer XLT MPV）与 REPORT NUMBER 118-GTL-18-004（2018 BMW 530i 轿车） | 同上体系 | https://static.nhtsa.gov/odi/ctr/9999/TRTR-646394-2020-001.pdf ；https://static.nhtsa.gov/odi/ctr/9999/TRTR-645269-2018-001.pdf | 同类报告 PDF，可做版式互校 | 已核实（链接与标题） |
| REPORT NUMBER 118-GTL-08-004（2008 BMW 328i 轿车） | 同上 | https://www.carsandracingstuff.com/library/reports/5109.pdf | 同上 | 已核实 |
| NHTSA Compliance Test Report Search（合规测试报告检索数据库） | 美国国家公路交通安全管理局 | https://www.nhtsa.gov/compliance/ | 可按标准号检索历年公开报告，覆盖车辆、儿童座椅、轮胎、头盔等 | 已核实。官方声明：报告公开是为信息交流，其意见、发现与结论不应被视为产品是否合规的最终判定 |
| OVSC Laboratory Test Procedure TP-118-06（FMVSS 118 实验室测试程序），2006-04-12 | 美国交通部 NHTSA 车辆安全合规办公室 | https://www.nhtsa.gov/sites/nhtsa.gov/files/documents/tp-118-06_tag.pdf | 与报告配套的测试程序文件，报告正文明确声明"所有试验按 TP-118-06 与 GTL 内部程序 TP-118-03A 执行" | 链接与标题已核实；正文本次抓取失败（Socket closed），**待核实** |

### 7.2 该报告的章节结构与字段清单（可直接作为系统报告模板骨架，已核实）

| 层级 | 内容 |
|---|---|
| 封面 | 报告编号、标准号与标题、被测车辆制造商与型号、NHTSA 编号、检测实验室名称与地址、日期、FINAL REPORT 字样、委托机构全称与地址 |
| 免责声明页 | 分发声明 + Prepared By / Approved By 双数字签名 + 批准日期 |
| Technical Report Documentation Page（技术报告著录页） | 13 个编号字段：1 报告号、2 政府入藏号、3 接收方目录号、4 标题与副标题、5 报告日期、6 执行机构代码、7 作者、8 执行机构报告号、9 执行机构名称与地址、10 工作单元号、11 合同或资助号、12 主办机构名称与地址、13 报告类型与周期 |
| 第 1 节 Purpose of Compliance Test | 1.0 试验目的；1.1 被测车辆识别（车辆识别代号 VIN、NHTSA 编号、制造商、制造日期、颜色）；1.2 试验日期 |
| 第 2 节 Test Procedure and Summary of Results | 2.0 试验程序（引用 TP-118-06 与实验室内部程序编号）+ 八个步骤的执行序列 A 至 H；2.1 结果摘要 |
| 第 3 节 Test Data | 逐项数据表（本例含内部锁止系统关闭试验、钥匙拔出后的锁止试验、乘员舱促动装置试验含球体试验与上拉/外拉试验） |
| 第 4 节 Test Equipment List | 设备清单 |
| 第 5 节 Photographs | 15 张编号照片：整车左前 3/4 视图、右后 3/4 视图、车辆认证标签特写、轮胎信息标签特写、四个车窗开关特写、钥匙、点火开关、仪器装配、四处球体试验照片 |
| 第 6 节 Owner's Manual Information | 用户手册相关信息（对应 GB 11552-2009 §4.8.6 的用户手册要求） |

### 7.3 报告字段的合规依据（跨场景通用）

| 素材 | 来源全名 | URL | 可用形态 | 可信度 |
|---|---|---|---|---|
| ISO/IEC 17025:2017 第 7.8 条 Reporting of results（结果报告） | 国际标准化组织与国际电工委员会联合发布；此处经 Perry Johnson Laboratory Accreditation, Inc. (PJLA) 公开培训讲义转述 | https://www.pjlabs.com/downloads/webinar_slides/3.31.2022_Reporting-Results.pdf ；https://www.pjlabs.com/downloads/webinar_slides/10.9.2024_Reporting-Results.pdf ；标准本体 https://www.iso.org/standard/66912.html | 7.8.2 必含要素：标题、实验室标识、每页唯一报告编号、客户信息、方法引用、样品描述、接收/试验/签发日期、带单位的结果、授权签字、修订条款 | 标准编号与版次已核实；讲义转述的字段清单待核实 |
| CNAS-EL-13《检测报告和校准证书相关要求的认可说明》，发布日期 2019-12-25 | 中国合格评定国家认可委员会（China National Accreditation Service for Conformity Assessment, CNAS） | https://www.cnas.org.cn/cms_files/filemanager/328304128/attach/202412/7AF84C12378754996D4B69CB95C50127.pdf | 国内报告字段合规性的主依据 | 待核实（PDF 文本层抽取失败，文件号与标题来自搜索结果标题行） |
| 45.2 Question on Amendments to Test Reports, ISO/IEC 17025 Clause 7.8.8.1（关于试验报告修订的官方问答） | 欧洲认可合作组织（European Accreditation） | https://european-accreditation.org/sp_accordion_faqs/45-2-question-on-amendments-to-test-reports-iso-iec-17025-clause-7-8-8-1/ | 可用于"报告修订与换版"字段设计 | 待核实 |
| QC/T 626 征求意见稿第 7 章检验规则 | 见 §2.1 | 同 §2.1 | 型式检验与出厂检验的分组、抽样与判定规则，是报告"结论"段的生成逻辑 | 待核实 |
| QC/T 29090-2023 第 6 章检验规则 | 见 §4.4 | 同 §4.4 | 20 个项目分 6 组、每组不少于 2 套，顺序按 GB/T 28046.1-2011 附录 A.1；出厂检验按 GB/T 2828.1-2012 一般检查水平 II、接收质量限 0.4 至 4.0 | 已核实 |
| FCC Equipment Authorization 公开数据库（FCC ID 检索入口） | 美国联邦通信委员会工程技术办公室（Federal Communications Commission, Office of Engineering and Technology）；第三方镜像 fcc.report、fccid.io（非官方） | https://www.fcc.gov/oet/ea/fccid ；https://apps.fcc.gov/oetcf/eas/reports/GenericSearch.cfm | 可公开下载的电磁兼容测试报告 PDF，含完整报告版式、测试布置照片、限值与实测曲线 | 入口已核实。**但见 §8.3 零命中**：库中检索不到汽车电机模块的报告，原因是 FCC 设备认证覆盖的是含射频发射的设备 |

---

## 八、与峰岹案例的对照表

### 8.1 六个流程逐格对照

| 流程 | 案例一：峰岹散热风扇电机 | 案例二：汽车电动玻璃升降器（含防夹） | 共用的系统能力 |
|---|---|---|---|
| **1 知识库管理** | 已有 25 份调试规程、8 份调试手册、Keil 工程、原理图、63 个测试工作流，全部为**客户私有文档**，走上传→解析→入库链路 | 全部为**公开标准文档**：QC/T 626-2019 + GB 11552-2009 + FMVSS 118 + UN ECE R21 + GB 7258-2017，走"标准编号→条款抽取→判据结构化"链路 | 三级分类骨架（一级场景=消费电子/汽车，二级=部件大类，三级=产品类型）；文档→判据的结构化转换器；换版预警元数据 |
| **2 初始化配置** | `Customer.h` 参数头文件（电机极对数、载波、保护阈值等），参数直接来自客户源码 | QC/T 626 判据表 + 芯片厂参考设计（TIDA-01389 / RDS12VR / APGRD002 / TLE9855QX），参数来自标准与公开设计文档 | 参数读取→呈现→左右加减号调值；测试保护项（过压、过流、堵转、温度、人员防护）的统一表达 |
| **3 测试需求确认** | 63 个测试工作流（.wfw），判据源自客户内部经验与规程 | 标准条款直出判据：本体 18 项 + 防夹三地法规对照 | 工作流一步步运转、可调整；判据的量纲/条件/阈值三元组模型 |
| **4 启动测试与结果分析** | 示波器实测相电流与 FG 转速波形（已有深存储采集能力，绕过软件 1200 点限制） | 无实测波形，走三层数据方案：Electric Motor Temperature（2 Hz 车用工况）+ CARTIF 有刷直流故障集（波形级）+ gym-electric-motor 参数化合成 | 时序曲线呈现与异常判别；示波器这类单机设备走 SSH 远控；合成数据必须在界面标注来[源] |
| **5 调优确认及运行** | FOC 电流环/速度环、载波频率、启动斜坡等（峰岹既有经验） | 防夹专属六参数（力阈值、生效区间、启动屏蔽时间、纹波滤波带宽与迟滞、堵转门限与去抖、回缩行程）+ 通用 Microchip MCAF 电流环整定五参数 | 未达标项→推荐参数→回测试页的闭环；参数改动的前后对比留痕 |
| **6 测试报告及产出** | Excel 报告模板（客户既有） | NHTSA FMVSS 118 合规报告模板（六节结构 + 13 字段技术著录页 + 15 张编号照片）；字段合规依据为 ISO/IEC 17025:2017 §7.8 与 CNAS-EL-13 | 模板确认、信息确认；报告字段与判据表的自动绑定；报告修订与版本管理 |

### 8.2 两个案例的技术差异（这正是"泛化"要证明的东西）

| 维度 | 峰岹散热风扇电机 | 汽车玻璃升降器 |
|---|---|---|
| 电机类型 | 无刷直流 / 永磁同步，电子换向 | 有刷直流，机械换向 |
| 运动形式 | 单向连续旋转 | 直线往复有限行程，有上下止点 |
| 位置反馈 | 转速反馈信号 FG | 霍尔锁存脉冲计数，或电流纹波计数 |
| 主判据量纲 | 转速 rpm、相电流 A、温升 K | 线速度 mm/s、力 N、位移 mm、声压级 dB(A) |
| 安全属性 | 设备安全（过温、堵转） | **人身安全**（防夹力 100 N，受三地法规约束） |
| 耐久口径 | 连续运行小时数 | 开闭循环次数（前门 10 000 次，13 道温湿度工序） |
| 数据来[源] | 示波器实测深存储 | 合成为主，实测代理集为辅 |
| 判据来[源] | 客户内部规程与经验 | 公开标准条款，可被第三方复核 |
| 电压/温度/盐雾/EMC | **两案例共用同一套通用层**：ISO 16750 / GB/T 28046 / GB/T 18655 / GB/T 21437 | 同左 |

最后一行是关键：两个案例在"通用层"完全重合、在"产品层"完全不同，这就是知识库三级分类设计的实证依据——二级判据（环境应力、电气负荷、电磁兼容）跨场景复用，三级判据（产品专属性能与安全）逐产品定义。

---

## 九、搜索范围与零命中

### 9.1 本次调研的检索通道

分四路并行执行，合计 WebSearch 200 次（本会话配额用满）、官方登记库与检索接口约 90 次、WebFetch 与 curl 直取页面与 PDF 约 165 次。

| 通道 | 站点或接口 | 结果 |
|---|---|---|
| 中国行业标准 | 行业标准信息服务平台 hbba.sacinfo.org.cn，含 `POST /stdQueryList` 按行业枚举接口与 `/stdDetail/<pk>` 详情页 | 主力来源，QC/T 全部已核实条目出自此处，并取得 4 本标准全文 |
| 中国国家标准 | 国家标准全文公开系统 openstd.samr.gov.cn；全国标准信息公共服务平台 std.samr.gov.cn | 主力来源，GB/GB-T 全部已核实条目出自此处 |
| ISO | committee.iso.org/standard/<id>.html 与 committee.iso.org/ics/<ICS>/x/（www.iso.org 对自动访问返回 403，OBP 在线浏览平台同样不可用）；ISO 官方预览件经 cdn.standards.iteh.ai 托管 | ICS 43.040.10 全目录 419 条与 ICS 43.120 全目录 100 条逐条解析，抓取 26 个标准详情页；取得 ISO 16750-2/-4/-5:2023 与 16750-3:2012 的完整目录 |
| IEC 与 CISPR | webstore-search-api.iec.ch/api/search 公开检索接口；免费预览件取法为先取详情页 previewFile 字段再做 Base64 编码请求 preview 端点 | 25 次以上 API 查询，取得 CISPR 25:2021、CISPR 12:2025、IEC 60034-1:2026、IEC 60034-5:2020 完整目录 |
| AEC | aecouncil.com/AECDocuments.html（须走 HTTP，其 HTTPS 证书握手失败） | Q100 Rev J1、Q101 Rev E、Q102 Rev A、Q104 Rev A、Q200 Rev E 全部下载解析 |
| OEM 规范 | etest-emc.com 托管的 MBN LV 124-1: 2013-03、MBN LV 148: 2013-11、VW 80000: 2022-12；szilassy.eu 托管的 BMW GS 95024-3-1: 2010-01；GMW3172 Users Guide Rev.19 | 内容可信但**均为公网流传的非授权副本**，正式引用须经采购渠道取得授权原本复核 |
| 法规 | ecfr.gov、law.cornell.edu、unece.org、eur-lex.europa.eu、law.resource.org、federalregister.gov、nhtsa.gov | 取得 GB 11552-2009 报批稿全文、FMVSS 118 判据、NHTSA 合规报告与检索入口 |
| 数据集平台（13 个） | Kaggle（含元数据 API）、IEEE DataPort、Zenodo（含 REST API）、Figshare、Mendeley Data、Hugging Face Datasets、UCI 机器学习仓库、GitHub、PHM Society 数据挑战、NASA 预测数据仓库、OpenML（含 REST API）、Papers with Code、科学数据银行 ScienceDB | 详见 §9.3 |
| 芯片与设计资[源] | ti.com、nxp.com、infineon.com（本域被网络策略拦截）、st.com、microchip.com、toshiba、allegro、melexis、rohm | 取得五份 TI 参考设计编号与设计指南号；Microchip MCAF 调参文档为唯一完整参数闭环 |

### 9.2 关键词记录

**标准侧（中国行业标准库 industry=汽车，实跑 33 个关键词）**：电动机、电机、微电机、直流、换向器、起动机、刮水、玻璃升降器、玻璃、座椅、风扇、水泵、泵、节气门、助力转向、燃油泵、后视镜、门锁、滑门、背门、散热器、空调、风机、暖风、空气压缩机、真空泵、窗、顶窗、遮阳、传感器、调光、冷却、电子、电动、电气设备、电器、电线束、开关、继电器、台架试验、耐久、噪声。

**国家标准侧（约 27 个）**：GB/T 34590、33014、33012、21437、28046、18655、14023、34660、30038、19951、17619、4208、10125、18488、10069、22669、29259、2423.17、32131、25984、旋转电机、三相异步电动机试验方法、小功率电动机、电动汽车用驱动电机、环境试验、道路车辆 电气、汽车用电动机、刮水器、汽车天窗、电动座椅。

**数据集侧**：按四个维度交叉换词——信号维度（motor current / phase current / 相电流、motor speed / 转速、vibration / 振动、temperature、voltage、torque、motor current signature analysis）；电机类型（PMSM、BLDC、induction motor、brushed DC motor、IPMSM、hub motor）；汽车部件（windshield wiper motor、power window motor、sunroof motor、seat adjuster motor、electric power steering、radiator cooling fan motor、electric water pump、electronic throttle body、starter motor、EV traction motor、automotive actuator）；故障类型（inter-turn short circuit、stator winding fault、demagnetization、broken rotor bar、eccentricity、locked rotor / stall、bearing fault）。

**报告侧**：ISO 16750 报告模板与附录、ISO/IEC 17025 条款 7.8 字段、GB/T 28046 附录试验报告、QC/T 标准附录记录表、SGS 与 TÜV Rheinland 汽车零部件报告样张、CNAS 检测报告模板与要素、FCC ID 公开 EMC 报告、CISPR 25、防夹力 100 N 门限。

### 9.3 零命中清单（这些是检索证实的结论，不是遗漏）

**第一类：汽车低压执行器电机专用数据集，全平台零命中。**
在 Kaggle、UCI 机器学习仓库、OpenML、Hugging Face Datasets、Zenodo、IEEE DataPort、Figshare、Mendeley Data、科学数据银行 ScienceDB、GitHub 上，雨刮电机、车窗与天窗电机、座椅调节电机、电动助力转向电机、汽车冷却风扇电机六类产品**均未检索到任何独立命名的公开时序数据集**。搜到的全是专利文献、产品页、维基条目与一台测试设备手册，没有数据。电子节气门的唯一命名匹配项见 §5.3，内容存疑。

**第二类：检索平台层面的结构性障碍。**

| 平台 | 情况 |
|---|---|
| OpenML | 通过官方 REST API 对 motor、PMSM、bearing、ElectricMotorTemperature、Sensorless_drive_diagnosis 精确名称匹配，**全部返回错误码 372（无结果）**。网页搜索为纯前端渲染，无法复核 |
| Papers with Code | `paperswithcode.com/datasets` **返回 HTTP 302 重定向至 huggingface.co/papers/trending**，数据集板块已停止独立运作，不再是有效检索[源] |
| 科学数据银行 ScienceDB | 中英文多轮换词全部零命中，返回的是分子性质预测、基材缺陷、南极声学剖面等无关条目。不能完全排除站内索引不同步导致的假阴性 |
| Figshare | 页面对自动抓取返回 HTTP 403，3 条候选的许可证与字段均未能一手核实 |
| PHM Society Data Challenge | 逐年核对 2008 至 2025，**没有任何一届以电机或汽车执行器为诊断对象**。最接近的是 2023 年届齿轮箱挑战（驱动侧用两台 45 kW 西门子伺服电机，但故障标签面向齿轮箱）。各届页面均未标注数据许可证，下载前需邮件联系 dc@phmconference.org |
| NASA Prognostics Center of Excellence 数据仓库 | 21 个数据集中**没有任何 Electric Motor 或 Actuator 专用集**，与电相关的是 4 个电池集与 IGBT/MOSFET/电容老化集 |
| nonlinearbenchmark.org | 16 个基准中机电类只有工业机器人、机电定位系统、双电机耦合驱动、F-16 地面振动试验四个，**没有汽车执行器基准** |

**第三类：中国标准体系内确实不存在的。**

| 检索对象 | 结论 |
|---|---|
| 乘用车电动天窗 | QC/T 与 GB/GB-T 两库均零命中。只有 QC/T 766-2006《客车安全顶窗》，是客车逃生顶窗。**乘用车电动天窗目前无对口产品标准**——这也是本案例选"车窗"而非"天窗"的一个附加理由 |
| 洗涤器电机 | QC/T 零命中，唯一出口是强制性国家标准 GB 15085-2013《汽车风窗玻璃刮水器和洗涤器 性能要求和试验方法》 |
| 电子驻车制动（EPB） | QC/T 零命中。现有三本驻车制动标准（QC/T 237-2022、QC/T 1066-2017、QC/T 959-2013）全部针对机械式，不涉及 EPB 电机 |
| 汽车电动燃油泵 | QC/T 零命中（只有摩托车版 QC/T 1040-2016），汽车侧归 GB/T 25984.1-2010 |
| "汽车用电动机通用技术条件" | 两库均零命中，**不存在这本标准**。唯一公共底座是 QC/T 413-2002 |
| VDA 电机可靠性专卷 | 零命中。VDA 是质量管理与过程方法体系，产品级电机试验条件落在 LV 124 / VW 80000 / GMW3172 一侧 |
| SAE 雨刮/车窗/鼓风电机本体标准 | 零命中。命中的 SAE J903 与 J198 是雨刮系统性能标准，J1339 与 J2867 是风扇风量性能标准，均非电机零部件应力试验 |
| ISO 19453-2 | ICS 两个完整目录共 519 条中均无该条目，**该分部从未立项** |
| ISO 11452-6 现行版 | 仅 1997 版与其 1999 技术勘误，状态均为作废，无替代标准 |
| GB/T 21437 第 5 部分 | openstd 检索无该编号，第三方摘要所称的"第5部分：脉冲发生器和验证方法"**判为错误信息** |
| AEC-Q103-001 | 官网文档列表中不存在，Q103 系列目前只有 -002 与 -003 |
| GB/T 27025 | 本次检索未返回该标准的任何官方条目，年份与现行状态均未取得 |

**第四类：术语错配导致的假零命中（供后续检索复用）。**

| 用错的词 | 正确的行业术语 | 对应标准 |
|---|---|---|
| 鼓风机 | 汽车空调风机 | QC/T 708-2019 |
| 尾门 | 背门 | QC/T 1148-2021 |
| 执行器（门锁侧） | 电动驱动器 | QC/T 627-2025 §3.2 |

**第五类：报告与调优侧的零命中。**

| 零命中内容 | 已试方向 | 状态判断 |
|---|---|---|
| 第三方检测机构（TÜV Rheinland、SGS、Intertek、UL、中国汽车技术研究中心 CATARC、上海机动车检测认证技术研究中心 SMVIC）的汽车电机检测报告样张 PDF | 中英文双语检索机构名 + 样张 / sample report / 报告格式说明 | 零命中。这类机构公开的是服务介绍页，报告样张通常不公开。**本案例的解法是改用 NHTSA 公开合规报告（§7.1），这是选题推荐的第二条理由** |
| ISO 16750 系列、GB/T 28046 系列的附录试验记录表格 | 标准号 + 附录 + 试验报告 / annex + test record template | 零命中，标准正文需购买 |
| 汽车电机模块的公开 FCC ID 电磁兼容测试报告 | fcc.report + automotive motor + CISPR 25 | 零命中。结构性原因：FCC 设备认证覆盖含射频发射的设备，纯电机驱动模块通常不进入 FCC ID 库 |
| 雨刮电机专用调参应用笔记 | 雨刮 + PI 整定 / 调参 | 零命中。雨刮为有刷直流 + 限流斩波，公开资料只到驱动电路层，无磁场定向控制级调参文档 |
| 座椅电机、电动助力转向的具体可调参数清单（含典型取值与增减后果） | EPS / seat + tuning + parameters | 零命中。公开资料止于驱动器保护功能层，环路参数属主机厂与一级供应商私有 |
| 汽车冷却风扇电机与车窗升降电机的量化参数数据手册 | 各厂商官网 | 零命中，只找到应用场景描述，无可引用的一手厂商规格 PDF |
| Ansys Motor-CAD、Altair FluxMotor、JMAG 的免费示例数据包 | 三家官网 | 零命中，只有付费产品介绍与试用申请 |

### 9.4 访问受阻记录

| 目标 | 结果 | 应对 |
|---|---|---|
| www.iso.org/standard/*.html 与 www.iso.org/obp/ui/ | HTTP 403（Cloudflare 人机校验） | 改用官方同源镜像 committee.iso.org 成功绕过；**任务书期望的"OBP 免费看范围与目录"路径本次不可用** |
| webstore.ansi.org 预览页（7 个标准） | HTTP 403 | 未解决 |
| infineon.com 全域 | 被本次环境的网络策略拦截 | 改走 community.infineon.com 与 mouser.com 镜像 |
| Microchip APGRD002 页面 | HTTP 403 | 仅由搜索结果确认存在 |
| NXP RDS12VRFS.pdf | 超 10 MB 抓取上限 | 未取得正文 |
| GB 11552-2009 全文 PDF（law.resource.org） | WebFetch 文本层解析失败 | **已解决**：本地用 PyMuPDF 提取文本层成功，§4.2 的条文为逐字提取 |
| CATARC 玻璃升降器征求意见稿 PDF | WebFetch 返回二进制乱码 | **已解决**：同上，本地提取成功 |
| TI 设计指南 TIDUDJ1、TI SLVA830、CNAS-EL-13 | PDF 文本层为图像或抽取不完整 | 未取得正文数值 |
| Allegro A4960 数据手册、ST UM3259 | 超时与连接中断 | 未取得 |
| lite.duckduckgo.com 与 bing.com 的 curl 兜底检索 | 两者均对 curl 的 User-Agent 返回空结果页 | 未解决 |

### 9.5 已知召回缺口（诚实披露）

1. **WebSearch 配额在调研中段耗尽**（本会话 200 次上限用满），后段全部改用 WebFetch 与 curl 直接访问完成，未再做新的搜索式发现。不排除进一步搜索能找到同类素材。
2. **未做捕获-再捕获式跨源交叉核对**，没有系统比对某篇权威综述的汇总表来估计召回率。
3. **未覆盖的潜在源**：4TU.ResearchData（荷兰）、Dryad、DataCite 全局检索、Monash/UEA/UCR 时序归档、Google Dataset Search、国家基础学科公共科学数据中心。题目未要求，但检索过程中被反复提及。
4. **标"待核实"的条目共 60 余条**，均未逐字段打开原页面确认。
5. **QC/T 626-2019 正式版正文未取得**，本文档 §3.1 与 §4.1 的全部数值均来自征求意见稿，**这是本案例最大的单点风险**。

---

## 十、下一步动作清单（按性价比排序）

每一项都写明了完整的对象名与获取方式，可直接执行。

**必须优先采购的三本标准正文**

1. **QC/T 626-2019《汽车玻璃升降器》**（工业和信息化部，2019-11-11 发布 / 2020-04-01 实施）——用于核对本文档 §3.1 与 §4.1 全部数值相对征求意见稿的偏差。详情页 https://hbba.sacinfo.org.cn/stdDetail/9ca3b738497da0d0d84ae02e3b7e1815c9dd070e4233e5d3a3ba126dad340b73 ，平台以"潜在版权问题"不公开全文。
2. **ISO 16750-3:2023 Road vehicles — Environmental conditions and testing for electrical and electronic equipment — Part 3: Mechanical loads**（第 4 版，104 页）——本文档只能给 2012 第 3 版的振动谱值，2023 版谱值是否变更未核实，不得直接当作现行判据。https://www.iso.org/standard/77579.html
3. **ISO 20653:2023 Road vehicles — Degrees of protection (IP code)**——IPX9K 的水压、水温、流量、喷嘴距离、喷射角度与时长均未取得。https://www.iso.org/standard/76116.html

**必须先做的三项核实**

4. 下载 **KoNAMIC Electronic Throttle Body Experimental Dataset**（https://zenodo.org/records/22096081 ，790 kB tar.gz）解包，确认它是否真为电子节气门实验数据。它是全网唯一命名匹配的汽车执行器数据集，值得花十分钟证伪或证实。
5. 下载 **Pierburg CWA200 数据手册**（https://www.tecomotive.com/download/datasheets/CWA200_EN.pdf ）逐字段核对电压、电流、转速数值后再引用。
6. 回 **国家标准全文公开系统 GB 11552-2009 详情页**（https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno=6A3758226270FE03F4F4B841A56428B9 ）人工确认其强制性属性——抓取结果标注为"推荐性国家标准"，但编号为 GB 11552 而非 GB/T 11552，按中国标准编号规则应属强制性，此处存在矛盾。

**可立即落地的三项素材加工**

7. 下载 **NHTSA 的三份 FMVSS 118 合规测试报告**（报告编号 118-GTL-11-002 / 118-GTL-20-003 / 118-GTL-18-004，URL 见 §7.1），提取其共同字段，直接生成系统的报告模板 schema。
8. 用 **PyMuPDF** 批量提取已下载的 TI 设计指南 PDF（TIDUCQ9 天窗电机模块、TIDUDJ1 雨刮驱动、TIDUBP9 车规 12 V 200 W BLDC、TIDUED3 电动座椅、TIDUFH6 48 V HVAC 泵），拿到各自的"测试条件 + 实测参数表"，绕开 WebFetch 对 TI 扫描版 PDF 的抽取失败。
9. 用 **gym-electric-motor**（https://github.com/upb-lea/gym-electric-motor ，MIT 许可）按 §3.1 的参数（9–16 V、工作电流 ≤12 A、堵转电流 ≤28 A）搭一个有刷直流升降器模型，生成正常关窗、遇障夹持、到达上止点三类电流波形，作为流程 4 的演示数据。**界面上必须标注"合成数据 + 参数来源"，不能让读者误以为是实测。**

---

## 附：本次调研落地的本地文件

以下文件已下载并提取文本，位于本会话临时目录 `[源] 08713152-f584-4a4d-95af-24ea19918150/scratchpad`。该目录为会话级，**若需长期保留请尽快归档到项目仓库**。

| 文件 | 内容 |
|---|---|
| `qc636.txt` | 《汽车玻璃升降器》征求意见稿全文文本（16 页） |
| `gb11552.txt` | GB 11552-2009 报批稿全文文本（32 页） |
| `twp.txt` | 团体标准《新能源汽车高电压电子冷却水泵技术要求》征求意见稿全文文本（16 页） |
| `q100.pdf` / `q100.txt` 等五组 | AEC-Q100 / Q101 / Q102 / Q104 / Q200 官方文档 |
| `p_ISO+16750-1-2023.pdf` 等 | ISO 16750 系列、ISO 20653、ISO 10605、ISO 11452-1、ISO 7637-2 官方预览件 |
| `lv124.pdf` / `lv148.pdf` / `vw80000.pdf` / `bmw.pdf` / `gmwhb.pdf` | OEM 规范（均为非授权副本，见 §9.1 说明） |
