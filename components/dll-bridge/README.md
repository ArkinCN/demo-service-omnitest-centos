# dll-bridge — 32 位设备控制桥

把峰岹（Fortior）电机控制能力做成一个独立的 32 位子进程，通过 stdin/stdout JSON IPC 协议与主进程通信。

## 这个 crate 是什么

从客户源码 `app/src-tauri/crates/dll-bridge/` 迁移而来，**脱离客户源码与 tauri 运行时，独立存在**。

作用：加载 32 位 `FTGeneralUtils.dll`（客户电机控制库），把它的导出函数（`FreeRun` 启动 / `BreakRun` 停止 / `DownloadCode` 烧录 / `Reset` 复位 / `ReadMemValue` 读内存 等）暴露成 JSON-over-stdin/stdout 的 IPC 接口，供上层（我方 `c/backend` 或设备桥）用 subprocess 调用。

## 目录结构

```
c/components/dll-bridge/
├── Cargo.toml              # 独立 package，无 workspace 依赖
├── Cargo.lock
├── src/                    # 9 个 .rs，业务逻辑与客户一致（迁移时未改）
│   ├── main.rs             # stdin/stdout IPC 常驻模式 + CLI 模式入口
│   ├── lib.rs
│   ├── ipc.rs              # IPC 消息协议
│   ├── ffi.rs              # FTGeneralUtils.dll FFI 封装
│   ├── cli.rs              # CLI 一次性执行模式
│   ├── types.rs            # 常量与类型
│   ├── bridge_client.rs    # BridgeProcess 客户端（get_ide_dir 已改为 c/ 自定位）
│   ├── embedded_dll.rs     # 编译期嵌入 DLL（include_bytes 已改为 c/ 相对路径）
│   └── window.rs           # 隐藏窗口 + 消息泵
├── resources/
│   └── FTGeneralUtils.dll  # 客户 32 位控制库（随包自带）
└── tests/
    ├── integration_test.rs
    └── mcu_e2e_test.rs     # 需真机 + 固件，默认 #[ignore]
```

## 迁移时改动的两处（相对客户源码）

1. `src/embedded_dll.rs`：`include_bytes!` 路径由 `../../../resources/unpacked/IDE/FTGeneralUtils.dll` 改为 `../resources/FTGeneralUtils.dll`（DLL 随包放在本 crate 的 `resources/`）。
2. `src/bridge_client.rs` 的 `get_ide_dir()`：由返回 tauri 安装路径 `%APPDATA%\com.motordebug.app\IDE`，改为自定位——优先环境变量 `DLL_BRIDGE_RES_DIR`，否则回落 exe 同目录的 `resources/`，再回落 exe 同目录。

其余业务逻辑（IPC 协议、FreeRun/Reset 序列、DLL FFI、隐藏窗口消息泵）**与客户源码逐行一致，未做任何改动**。

## 编译

> ⚠️ 关键约束：`FTGeneralUtils.dll` 是 **32 位**，`libloading` 加载它要求 `dll-bridge.exe` 也必须是 32 位。
> 所以编译目标必须是 **i686**，不是默认 x64。

```bash
# 32 位 MSVC 目标（推荐，与客户原构建一致）
rustup target add i686-pc-windows-msvc
cargo build --target i686-pc-windows-msvc --release

# 或 32 位 GNU 目标（需先装 32 位 mingw 链接器 i686-w64-mingw32-gcc）
rustup target add i686-pc-windows-gnu
cargo build --target i686-pc-windows-gnu --release
```

**前置依赖**：32 位 Windows C 工具链。
- MSVC 路线：Visual Studio Build Tools（含「使用 C++ 的桌面开发」）。
- GNU 路线：32 位 MinGW-w64（`i686-w64-mingw32-gcc`）。

> 2026-09-29 编译记录：已用本机 MSVC 工具链从源码**独立编译成功**（`Finished release in 25.57s`），
> 自编译 exe 已验证独立启动打印 Ready。工具链调用方式：
>
> ```bat
> cmd /d /c "call E:\Software_Installation\CppTools\VC\Auxiliary\Build\vcvarsall.bat x86 && cargo build --target i686-pc-windows-msvc --release"
> ```
>
> （MSVC 14.44 装在 `E:\Software_Installation\CppTools`；备选 32 位 MinGW 在
> `E:\Software_Installation\07_Programming_Languages\Cpp\mingw-i686`，用
> `cargo +stable-x86_64-pc-windows-gnu build --target i686-pc-windows-gnu`。）

## 运行（IPC 常驻模式）

无参启动即进入 stdin/stdout IPC 常驻模式，启动后打印 `Ready` 信号等待 JSON 请求：

```bash
dll-bridge.exe          # 无参 → IPC 常驻，stdout 打印 Ready
dll-bridge.exe free-run ...   # 有参 → CLI 一次性执行（见 cli.rs 子命令）
```

## 与客户源码的关系

- 源：`app/src-tauri/crates/dll-bridge/`（客户 MotorDebug 桌面端，只读，未改动）。
- 迁移方式：复制副本到 `c/components/dll-bridge/` 后，只改上面两处路径绑定，业务逻辑不动。
- `FTGeneralUtils.dll` 源：`app/src-tauri/resources/unpacked/IDE/FTGeneralUtils.dll`，已复制随包。
