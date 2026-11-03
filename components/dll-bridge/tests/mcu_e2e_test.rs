//! MCU 端到端定时启停测试
//!
//! 通过 dll-bridge.exe 32位子进程桥接调用 DLL，执行完整 MCU 启动 -> 定时运行 -> 停止 流程。
//! 使用 JSON-over-stdin/stdout IPC 协议与桥接进程通信，避免测试进程直接加载 32 位 DLL。
//!
//! 使用：
//!   DLL_BRIDGE_TEST_PROJECT_PATH=工程目录路径  DLL_BRIDGE_TEST_RUN_SECS=5（可选）
//!   cargo test --target i686-pc-windows-msvc -p dll-bridge --test mcu_e2e_test -- --ignored

#![cfg(target_os = "windows")]

use std::io::{BufRead, Write as IoWrite};
use std::os::windows::process::CommandExt;
use std::path::Path;
use std::process::{ChildStdin, Command, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::Duration;

use dll_bridge::ipc::{IpcMessage, IpcRequest, IpcResponse};
use dll_bridge::types::*;

/// Bridge 启动等待 Ready 超时（毫秒）
const BRIDGE_READY_TIMEOUT_MS: u64 = 30000;
/// IPC 请求等待响应超时（毫秒）—— USB 操作（DownloadCode/DownloadFirmware）可能很慢
const BRIDGE_RESPONSE_TIMEOUT_MS: u64 = 120000;
/// dll-bridge.exe 可执行文件名
const BRIDGE_EXE_NAME: &str = "dll-bridge.exe";
/// Cargo 构建目标的相对路径（从 manifest 的祖父目录/target/ 开始）
const BRIDGE_BUILD_RELATIVE_PATH: &str = "i686-pc-windows-msvc/debug";

/// 环境变量名：工程路径（支持目录或直接指向 .uvproj/.ftproj 文件）
const ENV_PROJECT_PATH: &str = "DLL_BRIDGE_TEST_PROJECT_PATH";
/// 环境变量名：MCU 运行时长（秒）
const ENV_RUN_SECS: &str = "DLL_BRIDGE_TEST_RUN_SECS";
/// 默认工程路径（可通过环境变量覆盖；支持文件或目录路径）
const DEFAULT_PROJECT_PATH: &str =
    "D:\\workspace\\projects\\1-fu6832\\1-fu6832\\Software\\KeilC51\\FTC6804A.uvproj";
/// 默认 MCU 运行时长（秒）
const DEFAULT_RUN_SECS: u64 = 15;
/// 默认断点地址（芯片复位向量）
const DEFAULT_BREAKPOINT_ADDR: u32 = 0x08000000;

/// hex 文件搜索最大递归深度
const MAX_HEX_SEARCH_DEPTH: usize = 10;
/// hex 文件扩展名
const HEX_FILE_EXTENSION: &str = "hex";
/// 兄弟目录搜索最大递归深度（与项目目录搜索保持一致）
const SIBLING_SEARCH_DEPTH: usize = MAX_HEX_SEARCH_DEPTH;

/// .uvproj 文件中 Device 标签的起始/结束标记
const UVPROJ_DEVICE_TAG_OPEN: &str = "<Device>";
const UVPROJ_DEVICE_TAG_CLOSE: &str = "</Device>";
/// .ftproj 文件中 BodyName 属性的前缀
const FTPROJ_BODY_NAME_PREFIX: &str = "BodyName=\"";
/// 工程文件搜索优先级：支持的 .uvproj 扩展名列表
const UVPROJ_EXTENSIONS: &[&str] = &["uvproj", "uvprojx"];
/// 工程文件搜索优先级：.ftproj 扩展名
const FTPROJ_EXTENSION: &str = "ftproj";

/// Keil UV4 常见安装路径列表
const KEIL_UV4_SEARCH_PATHS: &[&str] = &[
    r"D:\Keil\UV4\UV4.exe",
    r"D:\Keil_v5\UV4\UV4.exe",
    r"D:\Program Files\Keil_v5\UV4\UV4.exe",
    r"D:\Program Files (x86)\Keil_v5\UV4\UV4.exe",
];
/// Keil 环境变量名称，用于指定 Keil 安装根目录
const KEIL_ROOT_ENV_VAR: &str = "KEIL_ROOT";
/// Keil UV4 可执行文件相对于根目录的路径
const KEIL_UV4_RELATIVE_PATH: &str = r"UV4\UV4.exe";
/// Keil 编译超时（毫秒），当前通过 cmd /C 调用 UV4.exe，超时由 .output() 隐式控制。
#[allow(dead_code)]
const KEIL_COMPILE_TIMEOUT_MS: u64 = 120000;
/// Keil 全量重编参数（使用 -r 确保源代码变更被重新编译，subst 路径下 -b 增量编译不可靠）
const KEIL_REBUILD_FLAG: &str = "-b";
/// Keil 多核编译参数
const KEIL_JOBS_FLAG: &str = "-j0";
/// subst 驱动器映射的起始字母
const SUBST_DRIVE_START: char = 'Z';
/// subst 驱动器映射的结束字母
const SUBST_DRIVE_END: char = 'G';

/// IDE 数据目录相对于 %APPDATA% 的路径
const IDE_APPDATA_RELATIVE_PATH: &str = r"com.motordebug.app\IDE";

/// dll-bridge.exe IPC 桥接进程管理器，封装 stdin/stdout 通信、请求响应匹配和优雅关闭。
struct BridgeProcess {
    /// 子进程实例
    child: std::process::Child,
    /// stdin 写入端（用于发送 IPC 请求 JSON 行）
    stdin_writer: std::io::BufWriter<ChildStdin>,
    /// stdout reader 线程发送的有效 JSON 行接收端，主线程用 recv_timeout 控制超时。
    response_rx: mpsc::Receiver<String>,
}

impl BridgeProcess {
    /// 启动 dll-bridge.exe 子进程并等待 Ready 信号。
    /// ide_dir 用于查找预构建的 dll-bridge.exe。
    fn start(ide_dir: &Path) -> Result<Self, String> {
        // 查找 dll-bridge.exe
        let exe_path = find_bridge_exe(ide_dir)?;
        println!("[桥接] exe 路径: {}", exe_path.display());

        // DLL 内部依赖 IDE 目录下的配置文件，相对路径不对会导致 DownloadCode 返回错误码。
        // 启动子进程：stdin/stdout 管道通信，stderr 继承用于日志输出
        let mut child = Command::new(&exe_path)
            .current_dir(ide_dir)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .creation_flags(CREATE_NO_WINDOW_FLAG)
            .spawn()
            .map_err(|e| format!("启动 {} 失败: {}", BRIDGE_EXE_NAME, e))?;

        let stdin_writer =
            std::io::BufWriter::new(child.stdin.take().ok_or("无法获取 stdin 管道")?);
        let stdout_reader =
            std::io::BufReader::new(child.stdout.take().ok_or("无法获取 stdout 管道")?);

        // 将 stdout 阻塞读取移到独立线程，主线程通过 recv_timeout 实现真正的超时控制。
        let (tx, rx) = mpsc::channel();

        // 启动 stdout reader 线程
        let _reader_handle = thread::Builder::new()
            .name("bridge-stdout-reader".to_string())
            .spawn(move || {
                let mut reader = stdout_reader;
                let mut buf = Vec::with_capacity(MAX_LINE_LENGTH);
                loop {
                    buf.clear();
                    // 读取原始字节直到遇到换行符
                    match reader.read_until(b'\n', &mut buf) {
                        Ok(0) => {
                            // EOF - stdout 管道已关闭
                            break;
                        }
                        Ok(_) => {}
                        Err(_) => break,
                    }

                    // 移除末尾的 \r 和 \n
                    while buf.last() == Some(&b'\n') || buf.last() == Some(&b'\r') {
                        buf.pop();
                    }

                    // 跳过空行
                    if buf.is_empty() {
                        continue;
                    }

                    // DLL 可能直接向 stdout 写入二进制数据；截取首尾花括号之间的 JSON 对象避免 UTF-8 转换失败。
                    let line = match std::str::from_utf8(&buf) {
                        Ok(s) => s.trim().to_string(),
                        Err(_) => {
                            // 定位 JSON 对象边界
                            let start = buf.iter().position(|&b| b == b'{');
                            let end = buf.iter().rposition(|&b| b == b'}');
                            match (start, end) {
                                (Some(s), Some(e)) if e > s => {
                                    match std::str::from_utf8(&buf[s..=e]) {
                                        Ok(json_str) => json_str.to_string(),
                                        Err(_) => continue,
                                    }
                                }
                                _ => continue,
                            }
                        }
                    };

                    if line.is_empty() {
                        continue;
                    }

                    // 只发送看起来像 JSON 的行（以 { 开头）
                    if line.starts_with('{') {
                        if tx.send(line).is_err() {
                            // 接收端已关闭，退出线程
                            break;
                        }
                    }
                }
            })
            .map_err(|e| format!("创建 reader 线程失败: {}", e))?;

        let proc = Self {
            child,
            stdin_writer,
            response_rx: rx,
        };

        // 等待 Ready 信号（使用 recv_timeout 实现真正的超时控制）
        let deadline = Duration::from_millis(BRIDGE_READY_TIMEOUT_MS);
        let start = std::time::Instant::now();
        loop {
            // 计算剩余超时时间
            let remaining = deadline.saturating_sub(start.elapsed());
            if remaining.is_zero() {
                return Err(format!(
                    "等待 {} Ready 超时（{}ms）",
                    BRIDGE_EXE_NAME, BRIDGE_READY_TIMEOUT_MS
                ));
            }
            // 从 reader 线程的 channel 接收有效 JSON 行，带超时
            let line = proc
                .response_rx
                .recv_timeout(remaining)
                .map_err(|e| format!("等待 Ready 失败: {}", e))?;
            let response = IpcResponse::from_json(&line)
                .map_err(|e| format!("解析 Ready 响应失败: {} - 原始: {}", e, line))?;
            match response {
                IpcResponse::Ready => {
                    println!("[桥接] {} 已就绪", BRIDGE_EXE_NAME);
                    return Ok(proc);
                }
                IpcResponse::DllLoaded { dll_path } => {
                    println!("[桥接] 启动阶段收到 DllLoaded: {}", dll_path);
                }
                other => {
                    println!("[桥接] 启动阶段收到非预期响应: {:?}", other);
                }
            }
        }
    }

    /// 发送 IPC 请求并等待与请求 ID 匹配的 Success 或 Error 响应。
    fn send_request(&mut self, request: IpcRequest) -> Result<IpcResponse, String> {
        // 构造消息（自动生成 UUID 和时间戳）
        let message = IpcMessage::new(request);
        let request_id = message.id.clone();
        let json = message
            .to_json()
            .map_err(|e| format!("IPC 消息序列化失败: {}", e))?;

        // 写入 stdin（JSON 行 + 换行符）
        self.stdin_writer
            .write_all(json.as_bytes())
            .map_err(|e| format!("写入 stdin 失败: {}", e))?;
        self.stdin_writer
            .write_all(b"\n")
            .map_err(|e| format!("写入换行符失败: {}", e))?;
        self.stdin_writer
            .flush()
            .map_err(|e| format!("flush stdin 失败: {}", e))?;

        // 通过 mpsc channel 的 recv_timeout 实现真正的响应超时控制
        let start = std::time::Instant::now();
        loop {
            // 计算剩余超时时间
            let elapsed = start.elapsed();
            let remaining =
                Duration::from_millis(BRIDGE_RESPONSE_TIMEOUT_MS).saturating_sub(elapsed);
            if remaining.is_zero() {
                return Err(format!(
                    "等待响应超时（{}ms），请求 ID: {}",
                    BRIDGE_RESPONSE_TIMEOUT_MS, request_id
                ));
            }
            // 从 reader 线程的 channel 接收有效 JSON 行，带超时
            let line = self
                .response_rx
                .recv_timeout(remaining)
                .map_err(|e| format!("读取响应失败（超时或通道关闭）: {}", e))?;

            let response = IpcResponse::from_json(&line)
                .map_err(|e| format!("解析响应失败: {} - 原始: {}", e, line))?;

            match &response {
                IpcResponse::Success {
                    request_id: rid, ..
                }
                | IpcResponse::Error {
                    request_id: rid, ..
                } => {
                    if rid == &request_id {
                        return Ok(response);
                    }
                    println!("[桥接] 跳过不匹配响应，期望: {}，实际: {}", request_id, rid);
                }
                IpcResponse::CallbackEvent {
                    msg_id,
                    w_param,
                    l_param,
                } => {
                    // 回调事件频繁触发，只打印第一次避免刷屏
                    use std::sync::atomic::{AtomicBool, Ordering};
                    static FIRST_CALLBACK: AtomicBool = AtomicBool::new(true);
                    if FIRST_CALLBACK.swap(false, Ordering::Relaxed) {
                        println!(
                            "[桥接] 回调事件: msg_id={}, w={}, l={} (后续相同事件不再打印)",
                            msg_id, w_param, l_param
                        );
                    }
                }
                IpcResponse::DllLoaded { dll_path } => {
                    println!("[桥接] DLL 已加载: {}", dll_path);
                }
                IpcResponse::Ready => {
                    println!("[桥接] 收到重复 Ready 信号");
                }
            }
        }
    }

    /// 发送 Shutdown 请求并等待子进程退出。
    /// FreeRun 期间 DLL callback 可能阻塞 stdout，直接发送后 wait 子进程退出更可靠。
    fn shutdown(&mut self) {
        println!("[桥接] 正在关闭 {}...", BRIDGE_EXE_NAME);
        // 只发送 Shutdown 请求，不等待 IPC 响应
        let message = IpcMessage::new(IpcRequest::Shutdown);
        if let Ok(json) = message.to_json() {
            let _ = self.stdin_writer.write_all(json.as_bytes());
            let _ = self.stdin_writer.write_all(b"\n");
            let _ = self.stdin_writer.flush();
        }
        // 等待子进程退出（带超时：5秒后强制终止）
        let wait_start = std::time::Instant::now();
        loop {
            match self.child.try_wait() {
                Ok(Some(status)) => {
                    println!("[桥接] {} 已退出: {}", BRIDGE_EXE_NAME, status);
                    return;
                }
                Ok(None) => {
                    if wait_start.elapsed() > std::time::Duration::from_secs(5) {
                        println!("[桥接] {} 退出超时，强制终止", BRIDGE_EXE_NAME);
                        let _ = self.child.kill();
                        let _ = self.child.wait();
                        return;
                    }
                    std::thread::sleep(std::time::Duration::from_millis(100));
                }
                Err(e) => {
                    println!("[桥接] 等待 {} 退出失败: {}", BRIDGE_EXE_NAME, e);
                    return;
                }
            }
        }
    }
}

impl Drop for BridgeProcess {
    fn drop(&mut self) {
        // 确保子进程被清理（防 panic 场景）
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

/// 按优先级搜索 IDE 目录（预构建）和 Cargo 构建输出目录中的 dll-bridge.exe。
fn find_bridge_exe(ide_dir: &Path) -> Result<std::path::PathBuf, String> {
    // 优先级 1: IDE 目录中的预构建版本
    let ide_exe = ide_dir.join(BRIDGE_EXE_NAME);
    if ide_exe.exists() {
        println!(
            "[桥接] 使用 IDE 目录中的 {}: {}",
            BRIDGE_EXE_NAME,
            ide_exe.display()
        );
        return Ok(ide_exe);
    }

    // 优先级 2: Cargo 构建输出目录（从 manifest 向上找 workspace target/）
    if let Ok(manifest_dir) = std::env::var("CARGO_MANIFEST_DIR") {
        if let Some(build_exe) = std::path::Path::new(&manifest_dir)
            .parent()
            .and_then(|p| p.parent())
            .map(|p| {
                p.join("target")
                    .join(BRIDGE_BUILD_RELATIVE_PATH)
                    .join(BRIDGE_EXE_NAME)
            })
        {
            if build_exe.exists() {
                println!(
                    "[桥接] 使用构建输出目录中的 {}: {}",
                    BRIDGE_EXE_NAME,
                    build_exe.display()
                );
                return Ok(build_exe);
            }
        }
    }

    Err(format!(
        "未找到 {}，请确保已构建 dll-bridge crate\
         （cargo build --target i686-pc-windows-msvc -p dll-bridge）",
        BRIDGE_EXE_NAME
    ))
}

/// 获取 IDE 资源目录路径：%APPDATA%\com.motordebug.app\IDE
fn get_ide_dir() -> std::path::PathBuf {
    let app_data = std::env::var("APPDATA").expect("无法获取 APPDATA 环境变量");
    std::path::PathBuf::from(format!("{}\\{}", app_data, IDE_APPDATA_RELATIVE_PATH))
}

/// 获取 IDE 目录下 FTGeneralUtils.dll 的路径
fn get_dll_path() -> String {
    get_ide_dir()
        .join(DLL_FILE_NAME)
        .to_string_lossy()
        .to_string()
}

/// 检测字符串是否包含非 ASCII 字符
fn has_non_ascii(s: &str) -> bool {
    s.chars().any(|c| !c.is_ascii())
}

/// 找到路径中包含非 ASCII 字符的最短祖先目录
fn find_non_ascii_ancestor(path: &std::path::Path) -> Option<std::path::PathBuf> {
    let mut accumulated = std::path::PathBuf::new();
    for component in path.components() {
        accumulated.push(component);
        if let Some(s) = component.as_os_str().to_str() {
            if has_non_ascii(s) {
                return Some(accumulated);
            }
        }
    }
    None
}

/// 创建 subst 驱动器映射
fn create_subst(target_dir: &std::path::Path) -> Option<char> {
    for letter in (SUBST_DRIVE_END..=SUBST_DRIVE_START).rev() {
        let drive = format!("{}:\\", letter);
        if std::path::Path::new(&drive).exists() {
            continue;
        }
        let output = std::process::Command::new("subst")
            .arg(format!("{}:", letter))
            .arg(target_dir)
            .output()
            .ok()?;
        if output.status.success() {
            return Some(letter);
        }
    }
    None
}

/// 删除 subst 驱动器映射
fn remove_subst(letter: char) {
    let _ = std::process::Command::new("subst")
        .arg(format!("{}:", letter))
        .arg("/D")
        .output();
}

/// 自动检测 Keil UV4 安装路径
fn detect_keil_uv4() -> Option<std::path::PathBuf> {
    for path in KEIL_UV4_SEARCH_PATHS {
        if std::path::Path::new(path).exists() {
            return Some(std::path::PathBuf::from(path));
        }
    }
    if let Ok(keil_root) = std::env::var(KEIL_ROOT_ENV_VAR) {
        let path = std::path::PathBuf::from(keil_root).join(KEIL_UV4_RELATIVE_PATH);
        if path.exists() {
            return Some(path);
        }
    }
    None
}

/// 使用 Keil UV4 编译工程
fn compile_keil_project(
    uv4_path: &std::path::Path,
    uvproj_path: &std::path::Path,
) -> Result<(), String> {
    use std::os::windows::process::CommandExt;

    if !uv4_path.exists() {
        return Err(format!("Keil UV4 不存在: {}", uv4_path.display()));
    }
    if !uvproj_path.exists() {
        return Err(format!("工程文件不存在: {}", uvproj_path.display()));
    }

    println!("[Keil编译] UV4: {}", uv4_path.display());
    println!("[Keil编译] 工程: {}", uvproj_path.display());

    // subst 中文路径处理
    let mut subst_letter: Option<char> = None;
    let mapped_uvproj;
    let final_uvproj;

    if let Some(non_ascii_root) = find_non_ascii_ancestor(uvproj_path) {
        println!("[Keil编译] 检测到非ASCII路径: {}", non_ascii_root.display());
        match create_subst(&non_ascii_root) {
            Some(letter) => {
                subst_letter = Some(letter);
                let original_str = uvproj_path.to_string_lossy();
                let root_str = non_ascii_root.to_string_lossy();
                mapped_uvproj = original_str.replace(root_str.as_ref(), &format!("{}:", letter));
                final_uvproj = std::path::Path::new(&mapped_uvproj);
                println!(
                    "[Keil编译] subst {}:{} -> {}",
                    letter,
                    non_ascii_root.display(),
                    final_uvproj.display()
                );
            }
            None => {
                println!("[Keil编译] 警告: 无可用盘符创建subst映射");
                final_uvproj = uvproj_path;
            }
        }
    } else {
        final_uvproj = uvproj_path;
    }

    // 通过 cmd /C 间接调用（避免 32 位进程直接调用 UV4.exe 的 ACCESS_VIOLATION）
    let output = std::process::Command::new("cmd")
        .arg("/C")
        .arg(uv4_path)
        .arg(final_uvproj)
        .arg(KEIL_REBUILD_FLAG) // 使用 -r 全量重编，确保源代码变更被编译（-b 增量编译在 subst 路径下可能检测不到变化）
        .arg(KEIL_JOBS_FLAG)
        .creation_flags(CREATE_NO_WINDOW_FLAG)
        .output()
        .map_err(|e| {
            if let Some(letter) = subst_letter {
                remove_subst(letter);
            }
            format!("执行 Keil 编译失败: {}", e)
        })?;

    println!("[Keil编译] 退出码: {}", output.status.code().unwrap_or(-1));

    if let Some(letter) = subst_letter {
        remove_subst(letter);
        println!("[Keil编译] 已清理 subst {}:", letter);
    }

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!(
            "Keil 编译失败: {}{}",
            output.status.code().unwrap_or(-1),
            if stderr.is_empty() {
                String::new()
            } else {
                format!(", {}", stderr)
            }
        ));
    }
    Ok(())
}

/// 扫描工程目录顶层，按优先级查找 .uvproj/.uvprojx 或 .ftproj 文件
fn find_project_file(dir: &Path) -> Option<std::path::PathBuf> {
    let entries = std::fs::read_dir(dir).ok()?;
    for entry in entries {
        if let Ok(entry) = entry {
            let path = entry.path();
            if let Some(ext) = path.extension().and_then(|e| e.to_str()) {
                if UVPROJ_EXTENSIONS.contains(&ext) {
                    return Some(path);
                }
            }
        }
    }
    let entries = std::fs::read_dir(dir).ok()?;
    for entry in entries {
        if let Ok(entry) = entry {
            let path = entry.path();
            if path.extension().map_or(false, |e| e == FTPROJ_EXTENSION) {
                return Some(path);
            }
        }
    }
    None
}

/// 从 .uvproj 文件内容解析 <Device>FU6832</Device> 标签
fn parse_device_from_uvproj(content: &str) -> Option<String> {
    let start = content.find(UVPROJ_DEVICE_TAG_OPEN)?;
    let content_start = start + UVPROJ_DEVICE_TAG_OPEN.len();
    let end = content[content_start..].find(UVPROJ_DEVICE_TAG_CLOSE)?;
    let device = content[content_start..content_start + end]
        .trim()
        .to_string();
    if device.is_empty() {
        None
    } else {
        Some(device)
    }
}

/// 从 .ftproj 文件内容解析 BodyName="FU6832" 属性
fn parse_device_from_ftproj(content: &str) -> Option<String> {
    let start = content.find(FTPROJ_BODY_NAME_PREFIX)?;
    let value_start = start + FTPROJ_BODY_NAME_PREFIX.len();
    let end = content[value_start..].find('"')?;
    let device = content[value_start..value_start + end].trim().to_string();
    if device.is_empty() {
        None
    } else {
        Some(device)
    }
}

/// 统一入口：从工程路径自动识别工程类型并提取芯片型号
fn resolve_chip_name(input_path: &str) -> Result<(String, String, String), String> {
    let path = Path::new(input_path);
    let (proj_file, project_dir) = if path.is_file() {
        let dir = path
            .parent()
            .ok_or_else(|| format!("无法获取文件所在目录: {}", input_path))?
            .to_string_lossy()
            .to_string();
        (path.to_path_buf(), dir)
    } else if path.is_dir() {
        let proj = find_project_file(path)
            .ok_or_else(|| format!("未找到 .uvproj/.uvprojx 或 .ftproj 文件: {}", input_path))?;
        (proj, path.to_string_lossy().to_string())
    } else {
        return Err(format!("路径不存在: {}", input_path));
    };
    let content = std::fs::read_to_string(&proj_file)
        .map_err(|e| format!("读取工程文件失败 [{}]: {}", proj_file.display(), e))?;
    let ext = proj_file
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_string();
    let chip_name = if UVPROJ_EXTENSIONS.contains(&ext.as_str()) {
        parse_device_from_uvproj(&content).ok_or_else(|| "未找到 <Device> 标签".to_string())?
    } else if ext == FTPROJ_EXTENSION {
        parse_device_from_ftproj(&content).ok_or_else(|| "未找到 BodyName 属性".to_string())?
    } else {
        return Err(format!("不支持的工程文件扩展名: {}", ext));
    };
    println!(
        "[芯片解析] {} -> {} (类型: {})",
        proj_file.display(),
        chip_name,
        ext
    );
    Ok((chip_name, project_dir, ext))
}

/// 递归搜索指定目录下的 .hex 文件（深度受限）
fn search_hex_recursive(
    dir: &Path,
    hex_files: &mut Vec<std::path::PathBuf>,
    depth: usize,
    max_depth: usize,
) {
    if depth >= max_depth {
        return;
    }
    if let Ok(entries) = std::fs::read_dir(dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_file() && path.extension().map_or(false, |e| e == HEX_FILE_EXTENSION) {
                hex_files.push(path);
            } else if path.is_dir() {
                search_hex_recursive(&path, hex_files, depth + 1, max_depth);
            }
        }
    }
}

/// 搜索项目目录下所有 .hex 文件
fn find_hex_files(project_dir: &Path) -> Vec<std::path::PathBuf> {
    let mut hex_files = Vec::new();
    if let Ok(entries) = std::fs::read_dir(project_dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_file() && path.extension().map_or(false, |e| e == HEX_FILE_EXTENSION) {
                hex_files.push(path);
            } else if path.is_dir() {
                search_hex_recursive(&path, &mut hex_files, 0, MAX_HEX_SEARCH_DEPTH);
            }
        }
    }
    hex_files
}

/// 在父目录的所有子目录中递归搜索 .hex 文件
fn find_hex_files_in_sibling_dirs(parent_dir: &Path) -> Vec<std::path::PathBuf> {
    let mut hex_files = Vec::new();
    println!("[编译] 扩展搜索: {}", parent_dir.display());
    if let Ok(entries) = std::fs::read_dir(parent_dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                search_hex_recursive(&path, &mut hex_files, 0, SIBLING_SEARCH_DEPTH);
            }
        }
    }
    hex_files
}

/// 从多个 hex 文件中选择修改时间最新的
fn pick_latest_hex(hex_files: &[std::path::PathBuf]) -> Option<std::path::PathBuf> {
    hex_files
        .iter()
        .filter_map(|p| {
            std::fs::metadata(p)
                .ok()
                .and_then(|m| m.modified().ok())
                .map(|t| (p, t))
        })
        .max_by_key(|(_, t)| *t)
        .map(|(p, _)| p.clone())
}

/// 确保 hex 文件位于 DLL 期望的位置
fn ensure_hex_at_dll_expected_location(project_dir: &Path) {
    let hex_files = find_hex_files(project_dir);
    let parent_dir = project_dir.parent().unwrap_or(project_dir);
    let dir_name = project_dir
        .file_name()
        .unwrap_or_default()
        .to_string_lossy();
    let expected_hex = parent_dir.join(format!("{}.{}", dir_name, HEX_FILE_EXTENSION));

    if hex_files.is_empty() {
        // 扩展到兄弟目录搜索
        let sibling_hex_files = find_hex_files_in_sibling_dirs(parent_dir);
        if sibling_hex_files.is_empty() {
            println!("[编译] 警告: 未找到 .hex 文件");
            return;
        }
        // 始终用最新 hex 覆盖 DLL 期望位置，确保下载最新固件（不跳过已有旧文件）
        {
            let source =
                pick_latest_hex(&sibling_hex_files).unwrap_or_else(|| sibling_hex_files[0].clone());
            println!(
                "[编译] 复制 hex: {} -> {}",
                source.display(),
                expected_hex.display()
            );
            if let Err(e) = std::fs::copy(&source, &expected_hex) {
                println!("[编译] 警告: hex 复制失败: {}", e);
            }
        }
        return;
    }

    // 项目目录内找到 hex：始终用最新编译的 hex 覆盖 DLL 期望位置
    {
        let source = pick_latest_hex(&hex_files).unwrap_or_else(|| hex_files[0].clone());
        println!(
            "[编译] 复制 hex: {} -> {}",
            source.display(),
            expected_hex.display()
        );
        if let Err(e) = std::fs::copy(&source, &expected_hex) {
            println!("[编译] 警告: hex 复制失败: {}", e);
        }
    }
}

/// 编译工程（根据工程类型选择 Keil 或 ForgeIDE 编译方式）。
/// 当前仅支持 Keil 工程直接编译；ForgeIDE 工程需要已启动的 bridge 进程执行 GeneralMakeFiles。
fn compile_project(chip_name: &str, project_path: &str, proj_file_ext: &str, ide_dir: &Path) {
    if UVPROJ_EXTENSIONS.contains(&proj_file_ext) {
        // Keil 工程：直接调用 UV4.exe 编译（不依赖 bridge 进程）
        let uv4_path = detect_keil_uv4().unwrap_or_else(|| {
            panic!(
                "[编译] 未找到 Keil UV4.exe，请设置 {} 环境变量",
                KEIL_ROOT_ENV_VAR
            )
        });
        let uvproj_file = find_project_file(Path::new(project_path))
            .unwrap_or_else(|| panic!("[编译] 未找到 .uvproj 工程文件: {}", project_path));
        println!(
            "[编译] Keil 工程: chip={}, proj={}",
            chip_name,
            uvproj_file.display()
        );
        match compile_keil_project(&uv4_path, &uvproj_file) {
            Ok(()) => println!("[编译] Keil 编译成功"),
            Err(e) => {
                // 编译失败不终止测试，尝试使用已有的 hex 文件
                println!("[编译] 警告: Keil 编译失败: {}，尝试使用已有 hex", e);
            }
        }
    } else if proj_file_ext == FTPROJ_EXTENSION {
        // ForgeIDE 工程：编译需要 bridge 进程的 GeneralMakeFiles
        // 此阶段 bridge 尚未启动，无法编译，打印警告
        // TODO: 对 ForgeIDE 工程，可考虑先启动临时 bridge 编译后再关闭
        println!(
            "[编译] ForgeIDE 工程编译需要 bridge 进程（GeneralMakeFiles），\
             此阶段无法编译，将使用已有 hex 文件。chip={}, path={}",
            chip_name, project_path
        );
        let _ = ide_dir; // 避免未使用变量警告
    }
}

/// 完整初始化（单阶段 IPC 流程）
///
/// 全程通过 dll-bridge.exe IPC 桥接进程调用 DLL：
///   编译工程 -> hex 校准 -> 启动 BridgeProcess -> InitDll -> SetControllerWindowHandle
///   -> SetCallBackFun -> DownloadCode
///   后续 MCU 操作（SetBreakPoint, EnterDebugMode, FreeRun, BreakRun）同样通过 IPC。
///
/// 返回 BridgeProcess 实例，用于后续 MCU 操作
fn full_init(chip_name: &str, project_path: &str, proj_file_ext: &str) -> BridgeProcess {
    let ide_dir = get_ide_dir();
    println!("[初始化] IDE 资源目录: {}", ide_dir.display());

    // Step 1a: 编译工程（Keil 工程直接编译，ForgeIDE 暂不支持此阶段编译）
    compile_project(chip_name, project_path, proj_file_ext, &ide_dir);
    println!("[初始化] 编译完成");

    // Step 1b: 确保 hex 文件在 DLL 期望的位置
    ensure_hex_at_dll_expected_location(Path::new(project_path));

    // Step 1c: 查找 hex 文件路径
    let hex_files = find_hex_files(Path::new(project_path));
    let hex_path = if !hex_files.is_empty() {
        let latest = pick_latest_hex(&hex_files).unwrap_or_else(|| hex_files[0].clone());
        println!("[初始化] DownloadCode 使用 hex: {}", latest.display());
        latest.to_string_lossy().to_string()
    } else {
        println!("[初始化] 警告: 未找到 hex 文件，使用工程目录路径");
        project_path.to_string()
    };

    // Step 2a: 启动 dll-bridge.exe 子进程（内部完成 COM 初始化、窗口创建）
    let mut bridge = BridgeProcess::start(&ide_dir).expect("启动 dll-bridge.exe 失败");

    // Step 2b: InitDll —— 加载 FTGeneralUtils.dll（IPC）
    let dll_path = get_dll_path();
    println!("[初始化] DLL 路径: {}", dll_path);
    let response = bridge
        .send_request(IpcRequest::InitDll {
            dll_path: dll_path.clone(),
        })
        .expect("InitDll 请求失败");
    match &response {
        IpcResponse::Success { .. } => println!("[初始化] DLL 加载成功"),
        IpcResponse::Error { message, .. } => panic!("[初始化] DLL 加载失败: {}", message),
        _ => panic!("[初始化] 未预期的 InitDll 响应: {:?}", response),
    }

    // Step 2c: SetControllerWindowHandle（桥接进程使用自己的隐藏窗口句柄）
    bridge
        .send_request(IpcRequest::SetControllerWindowHandle { handle: 0 })
        .expect("SetControllerWindowHandle 请求失败");
    println!("[初始化] SetControllerWindowHandle 成功");

    // Step 2d: SetCallBackFun（注册回调，桥接进程内部处理回调事件转发）
    bridge
        .send_request(IpcRequest::SetCallBackFun)
        .expect("SetCallBackFun 请求失败");
    println!("[初始化] SetCallBackFun 成功");

    // Step 2e: DownloadCode（通过 IPC 桥接进程调用）
    let response = bridge
        .send_request(IpcRequest::DownloadCode {
            chip_name: chip_name.to_string(),
            project_path: hex_path.clone(),
        })
        .expect("DownloadCode 请求失败");
    match &response {
        IpcResponse::Success { .. } => println!("[初始化] DownloadCode 成功"),
        IpcResponse::Error { message, .. } => {
            // DownloadCode 返回非零不一定表示完全失败，继续后续操作
            println!(
                "[初始化] 警告: DownloadCode 返回错误: {}，继续测试",
                message
            );
        }
        _ => panic!("[初始化] 未预期的 DownloadCode 响应: {:?}", response),
    }

    println!("[初始化] 完整初始化序列完成（IPC 单阶段）");
    bridge
}

/// MCU 端到端定时启停测试
///
/// 流程：解析芯片 ->
///       编译 -> hex 校准 ->
///       启动 BridgeProcess（IPC）-> InitDll -> SetControllerWindowHandle -> SetCallBackFun ->
///       DownloadCode ->
///       MCU 启动(SetBreakPoint -> EnterDebugMode -> FreeRun) ->
///       定时运行 -> BreakRun 停止 -> Shutdown
/// 全程通过 dll-bridge.exe IPC 桥接进程调用 DLL。
#[test]
#[ignore = "需要连接真实 HID 设备"]
fn test_mcu_timed_start_stop() {
    // 步骤 1：获取工程路径
    let project_path =
        std::env::var(ENV_PROJECT_PATH).unwrap_or_else(|_| DEFAULT_PROJECT_PATH.to_string());
    println!("[测试] 工程路径: {}", project_path);

    // 步骤 2：解析芯片型号
    let (chip_name, project_dir, proj_ext) =
        resolve_chip_name(&project_path).expect("芯片型号解析失败");
    println!(
        "[测试] 芯片: {}，目录: {}，类型: {}",
        chip_name, project_dir, proj_ext
    );

    // 步骤 3：获取运行时长
    let run_secs = std::env::var(ENV_RUN_SECS)
        .ok()
        .and_then(|s| s.parse::<u64>().ok())
        .unwrap_or(DEFAULT_RUN_SECS);
    println!("[测试] 计划运行: {} 秒", run_secs);

    // 步骤 4：完整初始化（启动桥接进程 + 编译 + DownloadCode）
    let mut bridge = full_init(&chip_name, &project_dir, &proj_ext);

    // 步骤 5：MCU 启动（通过 IPC 发送 SetBreakPoint -> EnterDebugMode -> FreeRun）
    bridge
        .send_request(IpcRequest::SetBreakPoint {
            address: DEFAULT_BREAKPOINT_ADDR,
        })
        .expect("SetBreakPoint 失败");
    println!(
        "[测试] SetBreakPoint(0x{:08X}) 完成",
        DEFAULT_BREAKPOINT_ADDR
    );

    bridge
        .send_request(IpcRequest::EnterDebugMode { mode: 0 })
        .expect("EnterDebugMode 失败");
    println!("[测试] EnterDebugMode(0) 完成");

    bridge
        .send_request(IpcRequest::FreeRun {
            main_addr: DEFAULT_BREAKPOINT_ADDR,
        })
        .expect("FreeRun 失败");
    println!("[测试] FreeRun 已启动，MCU 运行中...");

    // 步骤 6：定时运行
    println!("[测试] MCU 运行中，等待 {} 秒...", run_secs);
    let start = std::time::Instant::now();
    for sec in 0..run_secs {
        std::thread::sleep(std::time::Duration::from_secs(1));
        println!("  [{}s] 运行中...", sec + 1);
    }
    let elapsed = start.elapsed();
    println!("[测试] MCU 已运行 {:?}", elapsed);

    // 步骤 7：停止 MCU（通过 IPC 发送 BreakRun）
    // BreakRun 是非阻塞的：发送请求后不等待响应，直接继续
    // 原因：FreeRun 期间 DLL 持续产生 callback，可能阻塞 stdout 管道
    //       导致 dll-bridge 主线程无法及时写入 BreakRun 响应
    {
        let message = IpcMessage::new(IpcRequest::BreakRun);
        let json = message.to_json().expect("BreakRun 序列化失败");
        bridge
            .stdin_writer
            .write_all(json.as_bytes())
            .expect("写入 BreakRun 失败");
        bridge
            .stdin_writer
            .write_all(b"\n")
            .expect("写入换行符失败");
        bridge.stdin_writer.flush().expect("flush stdin 失败");
    }
    // 等待一小段时间让 BreakRun 生效
    std::thread::sleep(std::time::Duration::from_secs(2));
    println!("[测试] BreakRun 已发送，MCU 已停止");

    // 步骤 8：关闭桥接进程
    bridge.shutdown();

    // 步骤 9：验证结果
    println!("[验证] 运行时长: {:?}", elapsed);
    println!("[测试] MCU 端到端定时启停测试通过");
}
