# OmniTest 后端镜像（FastAPI + gunicorn）
#
# 关键约束（与部署体系一致）：
#   - 基础镜像必须带 -bookworm 后缀：Debian 13(trixie) 缺 libgl1-mesa-glx 等包，
#     opencv / pdf 处理类依赖会装不上。
#   - pip 走国内镜像（阿里云）：服务器直连 pypi.org 很慢。
#   - 启动必须用 gunicorn，不用 uvicorn/Flask 内置服务器。
#   - ⚠️ 本项目 README 要求「单 worker」：db/session.py 连接池是按单 worker 设计的
#     （pool_size=100 + max_overflow=300）。worker 数务必保持 1（见 gunicorn.conf.py）。
#
# ⚠️ 目录布局（关键，别乱改）：
#   app/core/paths.py 用 CORE_DIR.parents[3] 推导 C_DIR，用 parents[4] 推导仓库根。
#   即它硬性要求容器内路径为 **<repo>/c/backend/app/core/paths.py**（四层 parent）。
#   所以 backend 不能平铺到 /app，必须放在 <repo>/c/backend。
#   本镜像取 repo=/srv/omnitest，布局：
#       /srv/omnitest/c/backend/**            ← 后端源码
#       /srv/omnitest/c/web/public/**         ← 场景包与知识库静态数据（PUBLIC_DIR）
#       /srv/omnitest/c/data/kb/documents/**  ← 知识库抽取稿（KB_EXTRACT_DIR 默认）
#   web/ 与 data/ 只读挂载进来即可，不需要前端构建产物。
FROM python:3.11-slim-bookworm

ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com \
    OMNITEST_REPO=/srv/omnitest \
    FAN_PYTHON=/usr/local/bin/python
# FAN_PYTHON：显式钉死拉起 hardware/py 的解释器（= 上面装了 pyserial/pyvisa 的那个）。
#   不设时 fan_executor 会依次探测 hardware/.env 与 backend/.venv 兄弟解释器，
#   显式给出可避免「探测到另一个没装硬件库的解释器」这类静默失败。
# ⚠️ 故意**不设** FAN_CONFIG_PATH：留空才会走 fan_executor._resolve_overlay_path() 的
#   平台分支（os.name != "nt" → acceptance.linux.json），这正是「零代码改动」的关键。
#   一旦设了 FAN_CONFIG_PATH，overlay 就由该变量决定，Linux 机器差异字段将不再自动补齐。

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 系统依赖：build-essential 用于编译期；curl 供健康检查/排障
# libusb-1.0-0：硬件采集（部署方案 A：硬件挂 Linux 本体机 + 容器 devices 直通）必需。
#   容器内 pyvisa-py 的 usbtmc 后端靠 ctypes.util.find_library("libusb-1.0") 找 .so，
#   装不到就静默退到 libusb0 后端 → 表现为「能枚举到设备却 claim_interface 失败」。
#   ⚠️ 不用 hardware/py/requirements.txt 里的 libusb-package：那是 Windows 的
#      「自带 dll 免装系统 libusb」方案，在 Linux 上多余且可能与 apt 版冲突。
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 按 paths.py 要求的层级建立布局：<repo>/c/backend
WORKDIR /srv/omnitest/c/backend

# 先装依赖，利用镜像层缓存
COPY requirements.txt .
# 容器专用及尚未列入 requirements.txt 的依赖在此补装：
#   1. gunicorn  —— 部署要求用 gunicorn 起服务，requirements 里只有 uvicorn。
#      openpyxl 已列入 requirements.txt，直接启动和镜像使用相同版本。
#   3. pymupdf   —— 源码有 import pymupdf（PDF 处理），requirements 未列。
#
# ⚠️ 硬件依赖（2026-10-10 部署方案 A 新增）：装进**同一个** python 环境，
#   使 fan_executor._resolve_python() 回退到 sys.executable 时即可 import serial/pyvisa
#   （它只探测这两个模块，见 _probe_dependencies）。
#   为什么内联而不 COPY hardware/py/requirements.txt：compose 的 build context 是
#   ./backend，Dockerfile 拿不到 ../hardware/；改 context 会连带影响 COPY . . 与
#   app/core/paths.py 要求的 <repo>/c/backend 四层布局，收益不抵风险。
#   4. python-usbtmc —— Linux USB-TMC 设备访问（包名 python-usbtmc，import 名 usbtmc）。
#      ⚠️ 这是 Linux 上让 pyvisa-py 能枚举 /dev/usbtmc* 的**必需**依赖，缺了会报
#      「No RIGOL USB-TMC scope found; enumerated: ['ASRL/dev/ttyUSB0::INSTR']」——
#      只认得串口、认不出示波器。原因：RIGOL 的 USB 接口类为 0xFE/0x03（USB-TMC），
#      被内核 usbtmc 驱动独占（见 /sys/bus/usb/drivers/usbtmc/），libusb 抢不到会
#      报 USBError [Errno 5]；pyvisa-py 的 usbtmc 后端走的正是这个包的 ioctl 封装。
#      ⚠️ 改动时须与 hardware/py/requirements.txt 保持同步（此处刻意不装 libusb-package，见上）。
RUN pip install --no-cache-dir -r requirements.txt \
        gunicorn==21.2.0 \
        pymupdf==1.24.14 \
        "pyserial>=3.5" \
        "pyvisa>=1.15" \
        "pyvisa-py>=0.8" \
        "pyusb>=1.2" \
        "python-usbtmc==0.8" \
    -i https://mirrors.cloud.tencent.com/pypi/simple

# 再拷后端源码
COPY . .

# 运行期目录（与 docker-compose 的挂载点一致）
RUN mkdir -p /var/log/demo uploads/avatars uploads/kb uploads/kb_vector uploads/reports .deploy/logs

EXPOSE 5100

# gunicorn.conf.py 与 app 都在 /srv/omnitest/c/backend 下，WORKDIR 即此处
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app.main:app"]
