//! dll-bridge.exe IPC 客户端模块
//!
//! 封装与 32 位桥接子进程的 stdin/stdout 通信，用于启动子进程、发送 IPC 请求、等待响应和关闭进程。

use std::io::{BufRead, Write as IoWrite};
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{ChildStdin, Command, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::Duration;

use crate::ipc::{IpcMessage, IpcRequest, IpcResponse};
use crate::types::*;

/// dll-bridge.exe IPC 桥接进程管理器。
///
/// stdout 读取在独立线程中完成，避免 DLL 二进制数据污染 JSON 行导致主线程阻塞。
///
/// # 示例
///
/// ```no_run
/// use dll_bridge::{BridgeProcess, IpcRequest};
/// use std::path::Path;
///
/// let ide_dir = Path::new(r"C:\Users\...\AppData\Roaming\com.motordebug.app\IDE");
/// let mut bridge = BridgeProcess::start(ide_dir).expect("启动失败");
/// let response = bridge.send_request(IpcRequest::Shutdown).expect("请求失败");
/// bridge.shutdown();
/// ```
pub struct BridgeProcess {
    /// 子进程实例
    child: std::process::Child,
    /// stdin 写入端（BufWriter 包装，用于发送 IPC 请求 JSON 行）
    stdin_writer: std::io::BufWriter<ChildStdin>,
    /// stdout reader 线程发送的有效 JSON 行接收端，主线程通过 recv_timeout 实现超时控制
    response_rx: mpsc::Receiver<String>,
}

impl BridgeProcess {
    /// 启动 dll-bridge.exe 子进程并等待 Ready 信号。
    ///
    /// 启动 stdout reader 线程以处理 DLL 二进制数据污染 JSON 的情况。
    ///
    /// # 参数
    /// - `ide_dir` - IDE 资源目录路径（用于查找预构建的 dll-bridge.exe，
    ///   同时作为子进程工作目录以使 DLL 能找到配置文件）
    ///
    /// # 返回
    /// 成功返回已就绪的 BridgeProcess 实例，失败返回错误描述字符串
    pub fn start(ide_dir: &Path) -> Result<Self, String> {
        // 查找 dll-bridge.exe
        let exe_path = find_bridge_exe(ide_dir)?;
        println!("[桥接] exe 路径: {}", exe_path.display());

        // DLL 依赖相对路径加载配置文件，需与 Python fice_session.py 一样在 IDE 目录运行。
        let mut child = Command::new(&exe_path)
            .current_dir(ide_dir)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .creation_flags(CREATE_NO_WINDOW_FLAG)
            .spawn()
            .map_err(|e| format!("启动 {} 失败: {}", BRIDGE_EXE_NAME, e))?;

        // 获取 stdin 管道写入端
        let stdin_writer =
            std::io::BufWriter::new(child.stdin.take().ok_or("无法获取 stdin 管道")?);
        // 获取 stdout 管道读取端
        let stdout_reader =
            std::io::BufReader::new(child.stdout.take().ok_or("无法获取 stdout 管道")?);

        // reader 线程发送有效 JSON 行，主线程通过 recv_timeout 实现超时控制。
        let (tx, rx) = mpsc::channel();

        // 独立线程阻塞读取 stdout，只将通过验证的 JSON 行发送到 channel。
        let _reader_handle = thread::Builder::new()
            .name(BRIDGE_STDOUT_READER_THREAD_NAME.to_string())
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

                    // DLL 可能直接向 stdout 写入二进制数据；截取首尾花括号之间的 JSON 对象。
                    let line = match std::str::from_utf8(&buf) {
                        Ok(s) => s.trim().to_string(),
                        Err(_) => {
                            // 定位 JSON 对象的首尾花括号
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

    /// 发送 IPC 请求并等待匹配的响应。
    ///
    /// 自动跳过 CallbackEvent、DllLoaded 等异步通知消息。
    ///
    /// # 参数
    /// - `request` - IPC 请求枚举值
    ///
    /// # 返回
    /// 成功返回与请求 ID 匹配的 IpcResponse，超时或通信失败返回错误描述
    pub fn send_request(&mut self, request: IpcRequest) -> Result<IpcResponse, String> {
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

        // 通过 mpsc channel 的 recv_timeout 循环读取响应直到匹配 request_id。
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
    ///
    /// FreeRun 期间 DLL callback 可能阻塞 stdout 管道，直接发送后 wait 子进程退出更可靠。
    pub fn shutdown(&mut self) {
        println!("[桥接] 正在关闭 {}...", BRIDGE_EXE_NAME);
        // 只发送 Shutdown 请求，不等待 IPC 响应
        let message = IpcMessage::new(IpcRequest::Shutdown);
        if let Ok(json) = message.to_json() {
            let _ = self.stdin_writer.write_all(json.as_bytes());
            let _ = self.stdin_writer.write_all(b"\n");
            let _ = self.stdin_writer.flush();
        }
        // 等待子进程退出（带超时：超时后强制终止）
        let wait_start = std::time::Instant::now();
        loop {
            match self.child.try_wait() {
                Ok(Some(status)) => {
                    println!("[桥接] {} 已退出: {}", BRIDGE_EXE_NAME, status);
                    return;
                }
                Ok(None) => {
                    if wait_start.elapsed() > Duration::from_secs(BRIDGE_SHUTDOWN_TIMEOUT_SECS) {
                        println!("[桥接] {} 退出超时，强制终止", BRIDGE_EXE_NAME);
                        let _ = self.child.kill();
                        let _ = self.child.wait();
                        return;
                    }
                    std::thread::sleep(Duration::from_millis(BRIDGE_SHUTDOWN_POLL_INTERVAL_MS));
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
    /// 析构函数：兜底清理子进程，避免 panic 或未显式 shutdown 时残留进程。
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

/// 按优先级查找 dll-bridge.exe 的路径，兼容预构建和打包安装目录。
///
/// # 参数
/// - `ide_dir` - IDE 资源目录路径
///
/// # 返回
/// 找到则返回 dll-bridge.exe 的完整路径，否则返回错误描述
pub fn find_bridge_exe(ide_dir: &Path) -> Result<PathBuf, String> {
    // 优先级 1: IDE 目录中已有（之前已复制过）
    let ide_exe = ide_dir.join(BRIDGE_EXE_NAME);
    if ide_exe.exists() {
        println!(
            "[桥接] 使用 IDE 目录中的 {}: {}",
            BRIDGE_EXE_NAME,
            ide_exe.display()
        );
        return Ok(ide_exe);
    }

    // Tauri 打包时 dll-bridge.exe 与主程序在同一目录，复制到 IDE 目录以保持 DLL 资源路径正确。
    if let Some(exe_dir) = std::env::current_exe()
        .ok()
        .and_then(|e| e.parent().map(|p| p.to_path_buf()))
    {
        let src = exe_dir.join(BRIDGE_EXE_NAME);
        if src.exists() {
            println!("[桥接] 从安装目录复制 {} 到 IDE 目录", BRIDGE_EXE_NAME);
            match std::fs::copy(&src, &ide_exe) {
                Ok(_) => println!("[桥接] 已复制到: {}", ide_exe.display()),
                Err(e) => println!("[桥接] ⚠ 复制失败: {}", e),
            }
            return Ok(ide_exe);
        }
    }

    Err(format!(
        "未找到 {}，请确保已构建 dll-bridge crate\
         （cargo build --target i686-pc-windows-msvc -p dll-bridge）",
        BRIDGE_EXE_NAME
    ))
}

/// 获取包含 FTGeneralUtils.dll、dll-bridge.exe 等资源文件的 IDE 目录路径。
///
/// 迁移进 c/ 后不再依赖 tauri 安装路径（原 %APPDATA%\com.motordebug.app\IDE），
/// 改为自定位资源目录：
///   1. 优先读环境变量 `DLL_BRIDGE_RES_DIR`（现场可覆盖）；
///   2. 未设置时回落到可执行文件同目录下的 `resources/` 子目录；
///   3. 仍不存在则回落到 exe 同目录本身。
pub fn get_ide_dir() -> PathBuf {
    // ① 环境变量显式指定（现场覆盖优先）
    if let Ok(dir) = std::env::var("DLL_BRIDGE_RES_DIR") {
        let p = PathBuf::from(dir.trim());
        if !p.as_os_str().is_empty() {
            return p;
        }
    }
    // ② 回落到 exe 同目录下的 resources/ 子目录（c/ 独立部署时 DLL 与 exe 打包在一起）
    if let Some(exe_dir) = std::env::current_exe()
        .ok()
        .and_then(|e| e.parent().map(|p| p.to_path_buf()))
    {
        let res = exe_dir.join("resources");
        if res.exists() {
            return res;
        }
        // ③ resources/ 不存在则退回 exe 同目录本身
        return exe_dir;
    }
    // 兜底：旧 APPDATA 路径（保留向后兼容，正常情况下不会走到这里）
    let app_data = std::env::var("APPDATA").expect("无法获取 APPDATA 环境变量");
    PathBuf::from(format!("{}\\{}", app_data, IDE_APPDATA_RELATIVE_PATH))
}
