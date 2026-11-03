# 模拟数据说明

所有 JSON 为 simulation:true，仅用于同事实现和测试接口，不是示波器实测。01是计划，02是第一次增量，04是后续缺测点，05重发sequence=2用于去重，03是终态示例（最后sequence=2，对应只使用02的独立完成用例），06是独立延期状态，07是单窗口波形。不要把所有文件机械拼成同一个完成序列。

字段统一sequence、run_id、t_s；commanded_pwm_pct与measured_pwm_duty_pct分开。current_a和rpm在本组未确认条件下始终null。波形time_s与实验t_s含义不同。URL由真实服务创建，模拟波形未提供虚构下载链接。

08_full_40s.json 是独立运行 synthetic-40s 的40个确定性模拟点（0.5～39.5秒），第16个点缺测；用于不接硬件先验证固定轴、四档和断线。前端须相应创建同run_id的40秒模拟计划；不要与demo-001合并。
