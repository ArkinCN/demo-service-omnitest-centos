> 本文件为v0.4历史验收摘要，非v0.5新增入口实测。完整历史证据保留在本机同级v0.4-20261005/verification，本ZIP不重复打包历史大数据。v0.5入口证据见V0.5-VERIFICATION.md。

# v0.4 验收证据 · 2026-10-05

已完成可运行源码、实际设备一轮四档采集、持续模式开始与停止、结构化数据文件核验。旧 v0.2/v0.3 源文件保持历史，当前结果来自本包 v0.4。测速传感器尚未接入，CH4/RPM 未验收。

## 实际设备

测试机 SK-20251218QPBB，Windows PowerShell 5.1 64位；依赖检查实际返回 ready=true、COM4、visa64Loadable=true。UNO 精确识别 `READY UNO_FAN_V2 25000`；示波器精确识别 `RIGOL TECHNOLOGIES,DS1104Z Plus,DS1ZC271600575,00.04.05.SP2`。没有刷新当前固件。

`hardware_acceptance_002` 在 15:19:31～15:20:18（北京时间）运行一轮，四档分别目标10秒，完成4次采集。终态 `completed`、`simulation:false`、`terminalPublished:true`、`completedCycles:1`、`captureCount:4`、`failed:false`、`exitCode:0`；最后 `SET 0 → OK DUTY 0`。

|PWM命令|从显示波形推算的占空比|从显示波形推算的频率|CH1原始均值|
|---|---:|---:|---:|
|30%|29.945%|24.950kHz|0.002859V|
|50%|50.003%|24.967kHz|0.006931V|
|70%|69.975%|24.964kHz|0.012939V|
|100%|null（直流设定）|null|0.022776V|

![v0.4 实机70%档原屏幕](../docs/assets/08_hardware_v04_duty070.png)

此图是 v0.4 新实机截图。20µs/div，CH1黄20mV/div、CH2青2V/div、CH3紫1V/div；CH4关闭。主线可读出 CH3 高约70%、低约30%，约25kHz，与CSV统计一致。图中 CH1 是电流钳原始电压，不是标定后安培。CH2/3物理探头倍率仍未独立确认，标记 false；实际单根导线/匝数尚待核对，因此没有开启电流换算，也没有报 RPM。

每份采集实际含CH1/2/3各1200行，增量0.2µs、窗口239.8µs；共12个波形CSV、4个BMP、4份capture.json及对应preamble。五份真实capture.json（包括持续测试的一份）均通过 `capture.schema.json`，不是模拟数据。输出是NORM短窗口，不能代表十秒连续趋势。

`hardware_continuous_stop_001` 使用 cycles=0，常驻父调用异步start后看到真实首档capture_completed，再调用stop -RunDirectory。终态 `stopped`、`simulation:false`、`terminalPublished:true`、`cancelled:true`、`captureCount:1`、`failed:false`、`exitCode:0`。停止文件UTC为07:21:18.2755138，零档ACK记录UTC为07:21:18.3023686，本次处于驻留等待时相隔约26.9ms；这不保证在VISA调用期间也有同样延迟。结束检查无run-experiment进程，串口/示波器会话已释放。没有用强杀替代零档命令。

本地完整真实产物位于 `verification/hardware_20261005_v1/hardware_acceptance_002` 与 `hardware_continuous_stop_001`，原始归档为 `verification/hardware-evidence.zip`；交接ZIP保留本文、截图、源码与 `verification/hardware-interface-evidence` 的实际summary/事件/指令CSV，避免把全部波形数据复制成分发依赖。测试机完整结果位于 `C:/fc_pull/usb-fan-control-v0.4-20261005/runs/`。`physicalStopVerified:false` 保持准确；软件零档ACK不证明叶片物理停转。

## 启动生命周期限制

最先的 `hardware_acceptance_001` 仅返回 launched 后，短SSH会话退出，其Windows Job把子进程一并结束；留下claim/snapshot和空stdout/stderr，无runner.started、无events，未进入串口打开阶段。这一条不登记为实机成功。之后两个有效测试在同一SSH连接内保留父进程至收尾，真实验证同事系统常驻后端调用。

从短SSH会话启动后立即断开不能保证存活；同事系统应在设备电脑的常驻后端调用，等待真实running事件，最后读取 terminalPublished=true 的summary。没有为验证擅自创建计划任务或常驻服务。

## 本地与独立审查

Windows PowerShell 5.1 完整17项验证PASS：精确身份、指令范围/注入、ACK错误、帧限/超时、SCPI块、生产循环顺序、重复RunId、失败收尾、串口互斥、异步开始与停止、波形算法。最终证据 `verification/evidence_20261005_151238_376/results.txt`。

另7项定点回归PASS：null duty数组、无BOM UTF8中文配置、start原子claim防抢占、不可变配置快照、权威终态最后一次性发布、state读锁不终止运行且原子替换恢复、迟到READY拒绝。证据 `verification/fixes_20261005_151025_275`。这些测试不打开物理设备；模拟样例显式标 simulation=true。配置JSON schema通过，所有PowerShell源解析零错误。

独立真实Codex CLI使用gpt-6.1-sol/high：首次发现6项核心P2及2项schema P2，批量修复并真实回归；最终仅针对修复diff复核，全部Resolved，剩余P0/P1/P2为零。审查底稿单独保存项目90_临时区，不拼入对外主文。可选D2 INPUT_PULLUP固件编译成功2696B flash、227B RAM，未上传实机，未验收测速功能。

## 图像审核记录

接线、时序、系统事件与LZ-MK10条件接线四张PNG均亲自打开检查实际关系；图文字不靠多种线型猜含义。新70%实机屏幕也亲自打开读到CH1/2/3量程、20µs/div、CH4关闭及CH3高/低比例，核对CSV约69.975%/24.964kHz。新图与前版历史图在正文分别标明，没有把概念图称运行截图。

最终发布前再次逐图读出“红色供电单线→电流钳→CH1原始V”“PWM蓝线→CH3频率/占空比”“30/50/70/100顺序驻留→每档短抓→下一轮”“开始→独立运行→数据文件→capture_completed→系统读取”“停止请求→SET 0 ACK→最终summary”及“传感器黑OUT→CH4脉冲→确认PPR后换算RPM”。发现系统图状态事件JSONL文字被箭头横线穿过，已上移标签、重新渲染四图并逐张重看，合格；正文图片均在对应接线、时序、调用或实际证据小节。

