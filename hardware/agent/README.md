# OmniTest 硬件采集 agent（主机侧 sidecar）

## 为什么存在

NI-VISA 的 NI-PAL **无法在 Docker 容器内初始化**（实测 `--privileged` / `--ipc=host` /
`--pid=host` 均返回 `VI_ERROR_SYSTEM_ERROR`，而宿主进程一切正常）。示波器采集
因此只能跑在宿主。本 agent 把「运行 hardware/py 下的采集脚本」暴露成一个最小
HTTP 接口，容器内的 backend 通过代理脚本调用它。

```
容器 backend ──HTTP(带 token)──▶ 宿主 hw-agent ──spawn──▶ start.py
                                                          ├─ NI-VISA(@ivi) → 示波器
                                                          └─ pyserial      → UNO 风扇
                                       runs/ 目录（bind-mount 共享，宿主写、容器读）
```

## 组成

| 文件 | 作用 |
|---|---|
| `omnitest_hw_agent.py` | agent 主体（仅标准库，零新增依赖） |
| `omnitest-hw-agent.service` | systemd 单元（模板，令牌安装时替换） |
| `run_via_agent.py` | **容器内**代理：把 backend 对 `start.py` 的调用转发给 agent |
| `stop_via_agent.py` | **容器内**代理：把 `stop.py` 调用转发给 agent |

`fan_executor.py` **不需要任何改动**：它仍以为自己在启动一个普通本地子进程。

## 两个必须知道的语义细节

1. **`start.py` 是瞬时启动器**。它拉起 `run_experiment.py` 后立刻退出，所以
   「启动器退出」≠「采集结束」。agent 会从 launch JSON 的 `processId` 跟踪真实
   worker；`run_via_agent.py` 则以事件流里的 `run_finished`（或 `summary.json`
   的 `terminalPublished`）判断收尾。
2. **路径视角不同**。`start.py` 打印的是宿主绝对路径，而 backend 在容器里读文件，
   因此 `run_via_agent.py` 会把 `eventsPath` / `summaryPath` 改写成容器路径再输出；
   `directory` **故意保留宿主路径**，因为停止时它会被原样传给宿主执行的 `stop.py`。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/healthz` | 存活信息（无需 token） |
| GET | `/runs` | 当前跟踪的运行列表 |
| POST | `/runs` | 异步启动脚本（`start.py`） |
| GET | `/runs/{id}/status` | 存活 / 退出码 / 首行 launch JSON / 日志尾部 |
| POST | `/exec` | 同步执行脚本（`stop.py`），返回退出码与输出 |
| POST | `/runs/{id}/stop` | 向进程组发 SIGINT（兜底；正常停止走 `stop.py`） |

所有接口（除 `/healthz`）要求请求头 `X-Agent-Token`；脚本路径必须在
`HWA_SCRIPT_ROOT` 之内。

## 部署与自检

```bash
# 1) 服务状态
systemctl status omnitest-hw-agent --no-pager
journalctl -u omnitest-hw-agent -n 50 --no-pager

# 2) 健康检查（宿主）
curl -s http://172.21.0.1:8790/healthz

# 3) 容器侧连通性
docker exec <backend容器> python -c \
  "import urllib.request;print(urllib.request.urlopen('http://172.21.0.1:8790/healthz',timeout=5).status)"

# 4) 只读硬件探测（不转风扇）——最常用的一步
TOKEN=$(cat ~/.omnitest-agent/token)
curl -s -X POST http://172.21.0.1:8790/exec \
  -H "X-Agent-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"script\":\"<仓库>/hardware/py/entrypoints/check_deps.py\",\"timeout\":50}"
```

## 依赖前置（宿主）

- NI-VISA 21.0（`ni-visa` 包）+ **`systemctl start nipal`**（负责创建 `/dev/nipalk`；
  缺了它 `libnipalu.so` 初始化必失败）
- **内核 `usbtmc` 必须不在位**：`/etc/modprobe.d/blacklist-usbtmc.conf` 写
  `blacklist usbtmc`，并 `rmmod usbtmc`
- `agent_env`（conda，Python 3.10）内含 `pyvisa / pyserial / pyusb / python-usbtmc`
- `fjs` 需在 `dialout` 组（串口 `/dev/ttyUSB0` 属 `root:dialout`）

## 故障排查

| 现象 | 先查 |
|---|---|
| 容器内 409 / 启动被拒 | agent 是否已有活跃 run（单设备锁） |
| `@ivi` 打不开库 | `nipal` 是否跑过、`/dev/nipalk` 是否存在 |
| 示波器枚举不到设备 | `lsmod \| grep usbtmc`（必须在位=错）；`nivisa_usbtmc` udev 规则是否生效 |
| 后端报"未产出事件流" | `run_via_agent.py` 的路径改写是否生效（看 stdout 首行是不是 `/srv/...` 开头） |
| 采集卡在某档 | 先跑 `/exec check_deps.py`，再看 `runs/<id>/cycle*/` 下 CH*.csv 是否落盘 |
