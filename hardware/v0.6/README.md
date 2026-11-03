# 风扇硬件与 OmniTest 前端对接交接包 v0.6

同事先看这份，再按 [实施验收清单](docs/02_逐步实施验收.md) 开工。完整修改逻辑见 [前端对接方案](docs/01_前端对接方案.md)。本版新增的是**方案、格式样例和验收用例**；硬件执行源码与 v0.5 相同，尚未实现 OmniTest 实时接口和图表修改，也未新增硬件实测。

## ZIP 中的文件位置

解压后的目录是 `v0.6-20261005/`。完整解压，不要只取入口文件，也不要在 ZIP 内运行。

|用途|ZIP 内路径|实际执行脚本|
|---|---|---|
|风扇独立运行|v0.6-20261005/run-fan.cmd|run-fan.ps1|
|示波器独立采集|v0.6-20261005/run-scope.cmd|run-scope.ps1|
|联合运行|v0.6-20261005/start.cmd|start.ps1|
|停止|v0.6-20261005/stop.cmd|stop.ps1|
|配置|v0.6-20261005/config/acceptance.json|首次有限一轮；experiment.json 默认连续|
|完整硬件接线说明|v0.6-20261005/docs/00_硬件运行说明-v0.5.md|沿用 v0.5，含通道和测速接线|
|接口模拟样例|v0.6-20261005/docs/examples/|不代表实测数据|

## 同事先做什么

1. 在仪器电脑完整解压。硬件脚本无需 Python，使用 Windows PowerShell 5.1 64 位、CH340 驱动和 NI-VISA 64 位。OmniTest 后端仍需其自身 Python 环境。
2. 核对 `config/acceptance.json` 的 COM、VISA 身份和接线。运行 `check-dependencies.cmd`；默认设备号不可当成每台电脑固定值。
3. 先单独运行风扇，再单独运行示波器；二者不要同时运行抢设备。首次命令如下。
4. 按验收清单先用模拟 JSON 做图，再接一次真实联合实验，最后修改持续趋势采集。不要把四个短窗口伪装成连续曲线。

```powershell
.\run-fan.cmd -ConfigPath .\config\acceptance.json
.\run-scope.cmd -ConfigPath .\config\acceptance.json
.\start.cmd -ConfigPath .\config\acceptance.json -RunId acceptance_001
```

上述三次按顺序执行，每次结束再执行下一条。start 异步返回 launched，继续读 events/summary 判断完成。停止联合运行：

```powershell
.\stop.cmd -RunId acceptance_001
```

本包硬件入口默认仍是连续循环（experiment.json 的 cycles=0）；**前端首次测试提案使用 acceptance.json 的有限一次：30/50/70/100%，每档10秒，计划40秒**。握手和采集开销可能使实际时间更长。停止 ACK 不证明物理叶片停转。

## 图与读数的约定

![数据由执行器到图表](docs/assets/08_data_flow.png)

前端点击开始后先画完整计划横轴；后台约每秒提供新增趋势点，横轴不随每个点缩放。无计划时默认60秒；超过计划必须显示延期并扩展实际时间。PWM目标不是实测RPM。CH1 未确认换算条件时 current_a=null，保留原始探头电压；CH4 未接和未确认PPR时 rpm=null。

硬件脚本目前每档抓一个短窗口，不是10秒连续记录。旧验证与未实测限制见硬件说明、verification/V0.5-VERIFICATION.md。本版只检查文档、样例、图片和打包，不声称硬件连通或前后端已完成。
