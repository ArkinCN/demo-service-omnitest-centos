# 模拟接口样例

`simulation-events.jsonl` 来自生产入口的本地模拟验证：没有打开设备，首末事件 `simulation: true`，无示波器波形、RPM或实测指标。机器路径替换成 `C:/SIMULATION_EXAMPLE`，这些路径是示例，占位而非可访问产物。

系统可以先用该小文件练习逐行 JSON 解析、sequence 去重、档位进度与终态；真实采集事件 `capture_completed` 的结构见 `schemas/capture.schema.json` 和主 README。实际仪器数据须运行已接好的台架取得。
