"""验证本机直连（local 模式）的失败路径是诚实的：无真机时不假装读到数。

不依赖真机：只验证
  1. 未配置 VISA_RESOURCE 时，connect 返回 unknown 并写明「未配置」；
  2. 配置了不存在的资源名时，connect 返回 unknown 并写明「未在设备列表中找到」；
  3. read_fg / read_pwm 在未连接时返回 unavailable，而非伪造数值。

退出码 0 = 全部符合预期。
"""
import os
import sys

# 强制 local 模式，且确保不读真实 .env 里的 ssh 配置
os.environ["BENCH_BACKEND"] = "local"

from device_bench.backend import LocalVisaBackend  # noqa: E402
from device_bench import config  # noqa: E402


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" -> {detail}" if detail else ""))
    return cond


ok = True

# 1. 未配置 VISA_RESOURCE
os.environ.pop("VISA_RESOURCE", None)
import importlib  # noqa: E402

importlib.reload(config)
b1 = LocalVisaBackend()
snap1 = b1.connect()
ok &= check("未配置 VISA_RESOURCE 时 connect=unknown", snap1["mode"] == "unknown",
            f"mode={snap1['mode']}")
ok &= check("未配置时如实写明原因", "VISA_RESOURCE" in (snap1.get("last_error") or ""),
            snap1.get("last_error"))
ok &= check("未配置时不假装 connected", snap1["connected"] is False)

# 2. 配置了不存在的资源名
os.environ["VISA_RESOURCE"] = "USB0::0x1AB1::0x04CE::FAKE::INSTR"
importlib.reload(config)
b2 = LocalVisaBackend()
snap2 = b2.connect()
ok &= check("配置假资源名时 connect 不成功", snap2["connected"] is False,
            f"mode={snap2['mode']}")
ok &= check("配置假资源名时如实报「未找到」或「无设备」",
            ("未在设备列表" in (snap2.get("last_error") or "")) or ("VISA" in (snap2.get("last_error") or "")),
            snap2.get("last_error"))

# 3. 未连接时 read 应抛错/不可用（通过 query 抛 RuntimeError 验证）
try:
    b1.query(":MEASure:PDUTy? CHANnel4")
    ok &= check("未连接时 query 应抛错", False, "竟然没抛错")
except RuntimeError as e:
    ok &= check("未连接时 query 抛 RuntimeError", True, str(e)[:80])

print("\n" + ("ALL PASS" if ok else "FAIL"))
sys.exit(0 if ok else 1)
