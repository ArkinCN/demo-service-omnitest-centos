//! CLI 一次性执行模式
//!
//! 使用 clap derive 定义子命令，每个子命令直接调用对应的 DLL FFI 函数。
//! 输出统一 JSON 格式到 stdout，执行完毕后立即退出。

use std::ffi::CString;
use std::sync::atomic::{AtomicBool, AtomicI32, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};

use clap::{Parser, Subcommand};
use encoding_rs::GBK;
use log::{error, info};
use serde_json::{json, Value};

use crate::ffi::FtGeneralDll;
use crate::types::*;
use crate::window;

// CLI 回调全局状态：记录最后一次 DLL 回调参数，供主线程在完成后读取
static CLI_LAST_CALLBACK_MSG_ID: AtomicI32 = AtomicI32::new(i32::MIN);
static CLI_LAST_CALLBACK_W_PARAM: AtomicI32 = AtomicI32::new(0);
static CLI_LAST_CALLBACK_L_PARAM: AtomicI32 = AtomicI32::new(0);
static CLI_CALLBACK_FIRED: AtomicBool = AtomicBool::new(false);

/// CLI 模式 DLL 回调：将回调参数写入全局原子变量，供主线程轮询
extern "C" fn cli_dll_callback(msg_id: i32, w_param: i32, l_param: i32) -> i32 {
    CLI_LAST_CALLBACK_MSG_ID.store(msg_id, Ordering::Relaxed);
    CLI_LAST_CALLBACK_W_PARAM.store(w_param, Ordering::Relaxed);
    CLI_LAST_CALLBACK_L_PARAM.store(l_param, Ordering::Relaxed);
    CLI_CALLBACK_FIRED.store(true, Ordering::Relaxed);
    info!(
        "CLI 回调: msg_id={}, w_param={}, l_param={}",
        msg_id, w_param, l_param
    );
    CALLBACK_RETURN_VALUE_PROCESSED
}

// ============================================================
// CLI 参数定义
// ============================================================

/// FTGeneralUtils.dll 命令行工具
#[derive(Parser)]
#[command(name = "dll-bridge", about = "FTGeneralUtils.dll FFI 桥接工具")]
struct Cli {
    #[command(subcommand)]
    command: CliCommand,
}

/// CLI 子命令
#[derive(Subcommand)]
enum CliCommand {
    /// 编译构建项目
    #[command(name = CLI_CMD_GENERAL_MAKE_FILES)]
    GeneralMakeFiles {
        /// 工程路径（将被转换为 GBK 编码传给 DLL）
        project_path: String,
        /// Keil 头文件包含路径（可选）
        #[arg(long)]
        include_path: Option<String>,
        /// Keil 外部构建信息（可选）
        #[arg(long)]
        build_info: Option<String>,
    },

    /// 固件下载到目标设备
    #[command(name = CLI_CMD_DOWNLOAD_CODE)]
    DownloadCode {
        /// 芯片型号名称（如 "FU6832"）
        chip_name: String,
        /// hex 文件完整路径
        hex_file_path: String,
    },

    /// 自由运行（MCU 启动）
    #[command(name = CLI_CMD_FREE_RUN)]
    FreeRun {
        /// 主函数地址（必填，从 map 文件中获取）
        #[arg(long)]
        main_addr: u32,
    },

    /// 停止运行
    #[command(name = CLI_CMD_BREAK_RUN)]
    BreakRun,

    /// 进入调试模式
    #[command(name = CLI_CMD_ENTER_DEBUG)]
    EnterDebug {
        /// 调试模式类型（默认 0）
        #[arg(long, default_value_t = 0)]
        mode: i32,
    },

    /// 读取芯片内存
    #[command(name = CLI_CMD_READ_MEM)]
    ReadMem {
        /// 读取字节数（默认 CLI_DEFAULT_READ_MEM_LENGTH）
        #[arg(long, default_value_t = CLI_DEFAULT_READ_MEM_LENGTH)]
        length: u32,
    },

    /// 设置断点
    #[command(name = CLI_CMD_SET_BREAKPOINT)]
    SetBreakpoint {
        /// 断点地址（必填）
        #[arg(long)]
        address: u32,
    },

    /// 固件升级（阻塞模式，需要设备连接）
    #[command(name = CLI_CMD_DOWNLOAD_FIRMWARE)]
    DownloadFirmware {
        /// 超时时间（秒），默认 120 秒
        #[arg(short, long, default_value_t = 120)]
        timeout: u64,
    },
}

// ============================================================
// JSON 输出工具
// ============================================================

/// 构建成功响应 JSON
fn success_json(data: Value) -> String {
    json!({
        CLI_JSON_KEY_SUCCESS: true,
        CLI_JSON_KEY_DATA: data,
        CLI_JSON_KEY_MESSAGE: "OK",
        CLI_JSON_KEY_ERROR_CODE: ERROR_CODE_SUCCESS,
    })
    .to_string()
}

/// 构建失败响应 JSON
fn error_json(message: &str, error_code: i32) -> String {
    json!({
        CLI_JSON_KEY_SUCCESS: false,
        CLI_JSON_KEY_DATA: Value::Null,
        CLI_JSON_KEY_MESSAGE: message,
        CLI_JSON_KEY_ERROR_CODE: error_code,
    })
    .to_string()
}

/// 输出 JSON 到 stdout 并退出
fn output_and_exit(json_str: &str) {
    println!("{}", json_str);
    log::info!("CLI 输出: {}", json_str);
}

/// 输出成功结果并退出
fn exit_success(data: Value) -> ! {
    output_and_exit(&success_json(data));
    std::process::exit(0);
}

/// 输出错误结果并退出
fn exit_error(message: &str, error_code: i32) -> ! {
    let json_str = error_json(message, error_code);
    error!("CLI 错误: {}", message);
    output_and_exit(&json_str);
    std::process::exit(1);
}

// ============================================================
// GBK 编码工具
// ============================================================

/// UTF-8 字符串转换为 GBK 编码的 CString
fn utf8_to_gbk_cstring(s: &str) -> Result<CString, String> {
    let (encoded, _, had_errors) = GBK.encode(s);
    if had_errors {
        return Err(format!("{}{}", ERROR_MSG_GBK_ENCODE_FAILED, s));
    }
    CString::new(encoded.into_owned()).map_err(|e| format!("{}{}", ERROR_MSG_GBK_INTERIOR_NUL, e))
}

// ============================================================
// DLL 加载 + 窗口初始化
// ============================================================

/// CLI 模式完整初始化流程：从 EXE 同目录加载 DLL → 创建窗口 → 设置句柄
fn cli_init() -> FtGeneralDll {
    // 获取 EXE 所在目录
    let exe_path = std::env::current_exe().unwrap_or_else(|e| {
        exit_error(&format!("获取 EXE 路径失败: {}", e), ERROR_CODE_GENERAL);
    });
    let exe_dir = exe_path.parent().unwrap_or_else(|| {
        exit_error("无法确定 EXE 所在目录", ERROR_CODE_GENERAL);
    });

    // 将 DLL 所在目录加入 Windows DLL 搜索路径，使 DLL 内部能加载同目录的子 DLL（USB 驱动等）
    // 等效于 Python 的 os.add_dll_directory(root_dir)
    // 必须在 FtGeneralDll::load() 之前调用，否则 DLL 内部依赖的子模块无法加载
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::ffi::OsStrExt;
        use windows_sys::Win32::System::LibraryLoader::SetDllDirectoryW;

        let wide: Vec<u16> = std::ffi::OsStr::new(exe_dir)
            .encode_wide()
            .chain(std::iter::once(0))
            .collect();

        let result = unsafe { SetDllDirectoryW(wide.as_ptr()) };
        if result == 0 {
            log::warn!("SetDllDirectoryW 失败，DLL 子模块可能无法加载");
        } else {
            log::info!("DLL 搜索路径已设置: {}", exe_dir.display());
        }
    }

    // DLL 必须与 EXE 在同一目录
    let dll_path = exe_dir.join(crate::types::DLL_FILE_NAME);

    // 加载 DLL
    let dll = FtGeneralDll::load(dll_path.to_str().unwrap_or("")).unwrap_or_else(|e| {
        exit_error(
            &format!("DLL 加载失败: {} (期望路径: {})", e, dll_path.display()),
            ERROR_CODE_DLL_LOAD_FAILED,
        );
    });

    // 创建隐藏窗口（DLL 回调需要真实 HWND）
    let hwnd = match window::create_hidden_window() {
        Ok(h) => h,
        Err(e) => {
            log::warn!("隐藏窗口创建失败: {}，DLL 回调可能不工作", e);
            std::ptr::null_mut()
        }
    };

    // 设置窗口句柄给 DLL
    if let Some(func) = dll.set_controller_window_handle {
        if !hwnd.is_null() {
            let result = unsafe { func(hwnd) };
            info!("SetControllerWindowHandle 返回值: {}", result);
        }
    }

    // 注册回调函数（DLL 固件更新/调试等依赖回调通信）
    if let Some(set_cb) = dll.set_callback_fun {
        unsafe { set_cb(Some(cli_dll_callback)) };
        info!("DLL 回调函数已注册");
    }

    dll
}

// ============================================================
// 子命令执行
// ============================================================

/// 执行 GeneralMakeFiles
fn exec_general_make_files(
    dll: &FtGeneralDll,
    project_path: &str,
    include_path: Option<&str>,
    build_info: Option<&str>,
) -> ! {
    let path_cstr = utf8_to_gbk_cstring(project_path).unwrap_or_else(|e| {
        exit_error(
            &format!("工程路径编码转换失败: {}", e),
            ERROR_CODE_INVALID_PARAMS,
        );
    });

    // 可选：设置 Keil 头文件路径
    if let Some(func) = dll.set_keil_include_path {
        if let Some(inc_path) = include_path {
            let inc_cstr = utf8_to_gbk_cstring(inc_path).unwrap_or_else(|e| {
                exit_error(
                    &format!("include_path 编码转换失败: {}", e),
                    ERROR_CODE_INVALID_PARAMS,
                );
            });
            let result = unsafe { func(inc_cstr.as_ptr()) };
            info!("SetKeilIncludePath 返回值: {}", result);
        }
    }

    // 可选：设置 Keil 构建信息
    if let Some(func) = dll.set_keil_build_exter_info {
        if let Some(bi) = build_info {
            let bi_cstr = utf8_to_gbk_cstring(bi).unwrap_or_else(|e| {
                exit_error(
                    &format!("build_info 编码转换失败: {}", e),
                    ERROR_CODE_INVALID_PARAMS,
                );
            });
            let result = unsafe { func(bi_cstr.as_ptr()) };
            info!("SetKeilBuildExterInfo 返回值: {}", result);
        }
    }

    // 调用 GeneralMakeFiles
    match dll.general_make_files {
        None => exit_error(
            "DLL 中未找到 GeneralMakeFiles 函数",
            ERROR_CODE_DLL_CALL_FAILED,
        ),
        Some(func) => {
            info!(
                "调用 GeneralMakeFiles({}, {:?})",
                GENERAL_MAKE_FILES_DEFAULT_TYPE, project_path
            );
            let result = unsafe { func(GENERAL_MAKE_FILES_DEFAULT_TYPE, path_cstr.as_ptr()) };
            info!("GeneralMakeFiles 返回值: {}", result);

            if result == DLL_RETURN_SUCCESS {
                exit_success(json!({"result": result}));
            } else {
                exit_error(
                    &format!("GeneralMakeFiles 执行失败，返回码: {}", result),
                    ERROR_CODE_DLL_CALL_FAILED,
                );
            }
        }
    }
}

/// 执行 DownloadCode（阻塞模式，子线程调用 DLL + 主线程消息泵）
fn exec_download_code(dll: &FtGeneralDll, chip_name: &str, hex_file_path: &str) -> ! {
    let chip_cstr = CString::new(chip_name).unwrap_or_else(|e| {
        exit_error(
            &format!("芯片名称包含非法字符: {}", e),
            ERROR_CODE_INVALID_PARAMS,
        );
    });

    let path_cstr = CString::new(hex_file_path).unwrap_or_else(|e| {
        exit_error(
            &format!("hex 文件路径包含非法字符: {}", e),
            ERROR_CODE_INVALID_PARAMS,
        );
    });

    match dll.download_code {
        None => exit_error("DLL 中未找到 DownloadCode 函数", ERROR_CODE_DLL_CALL_FAILED),
        Some(func) => {
            info!(
                "调用 DownloadCode({}, {:?})（消息泵模式）",
                chip_name, hex_file_path
            );

            // DownloadCode 阻塞扫描设备，需 worker 线程 + 主线程消息泵
            let dll_result = Arc::new(AtomicI32::new(i32::MIN));
            let dll_result_clone = Arc::clone(&dll_result);
            let result = run_with_message_pump(BRIDGE_RESPONSE_TIMEOUT_MS, move || {
                let ret = unsafe { func(chip_cstr.as_ptr(), path_cstr.as_ptr()) };
                dll_result_clone.store(ret, Ordering::Relaxed);
            });

            match result {
                Ok(()) => {
                    let ret = dll_result.load(Ordering::Relaxed);
                    info!("DownloadCode 返回值: {} (0x{:08X})", ret, ret as u32);
                    if ret == DLL_RETURN_SUCCESS {
                        exit_success(json!({"result": ret}));
                    } else {
                        exit_error(
                            &format!(
                                "DownloadCode 执行失败，返回码: {} (0x{:08X})",
                                ret, ret as u32
                            ),
                            ERROR_CODE_DLL_CALL_FAILED,
                        );
                    }
                }
                Err((code, msg)) => exit_error(&msg, code),
            }
        }
    }
}

/// 在子线程执行 DLL 阻塞调用，主线程同时运行 Windows 消息泵
///
/// DLL 的固件更新/调试操作可能依赖 Windows 消息来驱动内部状态机，
/// 因此主线程必须持续 pump messages。
///
/// timeout_ms: 最大等待时间（毫秒），超时返回错误
/// dll_call: 要执行的 DLL 调用闭包
fn run_with_message_pump<F>(timeout_ms: u64, dll_call: F) -> Result<(), (i32, String)>
where
    F: FnOnce() + Send + 'static,
{
    let done = Arc::new(AtomicBool::new(false));
    let done_clone = Arc::clone(&done);
    let start = Instant::now();

    // 子线程执行 DLL 阻塞调用
    let handle = thread::Builder::new()
        .name("cli-worker".to_string())
        .spawn(move || {
            dll_call();
            done_clone.store(true, Ordering::Relaxed);
            info!("DLL worker 线程完成");
        })
        .map_err(|e| (ERROR_CODE_GENERAL, format!("创建 worker 线程失败: {e}")))?;

    // 主线程 pump messages，等待子线程完成或超时
    while !done.load(Ordering::Relaxed) {
        if start.elapsed().as_millis() as u64 > timeout_ms {
            return Err((ERROR_CODE_TIMEOUT, format!("操作超时 ({}ms)", timeout_ms)));
        }
        window::pump_messages();
        thread::sleep(Duration::from_millis(MESSAGE_PUMP_TIMEOUT_MS as u64));
    }

    let _ = handle.join();
    Ok(())
}

/// 执行 FreeRun（SetBreakPoint → EnterDebugMode → FreeRun 原子序列）
fn exec_free_run(dll: &FtGeneralDll, main_addr: u32) -> ! {
    // SetBreakPoint
    if let Some(func) = dll.set_break_point {
        info!("调用 SetBreakPoint(0x{:08X})", main_addr);
        unsafe { func(main_addr) };
    }

    // EnterDebugMode
    if let Some(func) = dll.enter_debug_mode {
        info!("调用 EnterDebugMode(0)");
        let result = unsafe { func(0) };
        info!("EnterDebugMode 返回值: {}", result);
        // 非零返回值不中断（DownloadCode 后 MCU 已在 debug 模式）
    }

    // FreeRun 在 worker 线程执行，主线程同步 pump messages
    match dll.free_run {
        None => exit_error("DLL 中未找到 FreeRun 函数", ERROR_CODE_DLL_CALL_FAILED),
        Some(func) => {
            info!(
                "调用 FreeRun()（消息泵模式，超时 {}ms）",
                IPC_DEFAULT_TIMEOUT_MS
            );
            let result = run_with_message_pump(IPC_DEFAULT_TIMEOUT_MS, move || {
                unsafe { func() };
            });

            match result {
                Ok(()) => {
                    info!("FreeRun 已返回");
                    exit_success(json!({"main_addr": main_addr}));
                }
                Err((code, msg)) => exit_error(&msg, code),
            }
        }
    }
}

/// 执行 BreakRun
fn exec_break_run(dll: &FtGeneralDll) -> ! {
    match dll.break_run {
        None => exit_error("DLL 中未找到 BreakRun 函数", ERROR_CODE_DLL_CALL_FAILED),
        Some(func) => {
            info!("调用 BreakRun()");
            unsafe { func() };

            // 泵送消息以完成中断（与 main.rs 逻辑一致）
            let deadline = std::time::Instant::now() + std::time::Duration::from_millis(500);
            while std::time::Instant::now() < deadline {
                if !window::pump_messages() {
                    break;
                }
            }

            exit_success(json!({"break_run_called": true}));
        }
    }
}

/// 执行 EnterDebugMode
fn exec_enter_debug(dll: &FtGeneralDll, mode: i32) -> ! {
    match dll.enter_debug_mode {
        None => exit_error(
            "DLL 中未找到 EnterDebugMode 函数",
            ERROR_CODE_DLL_CALL_FAILED,
        ),
        Some(func) => {
            info!("调用 EnterDebugMode({})", mode);
            let result = unsafe { func(mode) };
            info!("EnterDebugMode 返回值: {}", result);

            if result == DLL_RETURN_SUCCESS {
                exit_success(json!({"result": result, "mode": mode}));
            } else {
                exit_error(
                    &format!("EnterDebugMode 执行失败，返回码: {}", result),
                    ERROR_CODE_DLL_CALL_FAILED,
                );
            }
        }
    }
}

/// 执行 ReadMem
fn exec_read_mem(dll: &FtGeneralDll, length: u32) -> ! {
    if length == 0 {
        exit_error("读取长度不能为 0", ERROR_CODE_INVALID_PARAMS);
    }
    if length as usize > MAX_READ_MEM_LENGTH {
        exit_error(
            &format!("读取长度 {} 超过最大限制 {}", length, MAX_READ_MEM_LENGTH),
            ERROR_CODE_INVALID_PARAMS,
        );
    }

    match dll.read_mem_value {
        None => exit_error("DLL 中未找到 ReadMemValue 函数", ERROR_CODE_DLL_CALL_FAILED),
        Some(func) => {
            let mut buffer = vec![0u8; length as usize];
            let bytes_read = unsafe { func(buffer.as_mut_ptr(), length) };
            info!("ReadMemValue 返回: 读取了 {} 字节", bytes_read);

            if bytes_read < 0 {
                exit_error(
                    &format!("ReadMemValue 失败，错误码: {}", bytes_read),
                    ERROR_CODE_DLL_CALL_FAILED,
                );
            } else {
                let actual_len = bytes_read as usize;
                let data = &buffer[..actual_len.min(buffer.len())];
                exit_success(json!({
                    "bytes": data,
                    "length": actual_len,
                }));
            }
        }
    }
}

/// 执行 SetBreakpoint
fn exec_set_breakpoint(dll: &FtGeneralDll, address: u32) -> ! {
    match dll.set_break_point {
        None => exit_error(
            "DLL 中未找到 SetBreakPoint 函数",
            ERROR_CODE_DLL_CALL_FAILED,
        ),
        Some(func) => {
            info!("调用 SetBreakPoint(0x{:08X})", address);
            unsafe { func(address) };
            exit_success(json!({"address": address}));
        }
    }
}

/// 执行 DownloadFirmware（阻塞模式，子线程调用 DLL + 主线程消息泵）
fn exec_download_firmware(dll: &FtGeneralDll, timeout_secs: u64) -> ! {
    let timeout_ms = timeout_secs * 1000;

    match dll.download_firmware {
        None => exit_error(
            "DLL 中未找到 DownloadFirmware 函数",
            ERROR_CODE_DLL_CALL_FAILED,
        ),
        Some(func) => {
            info!(
                "调用 DownloadFirmware()（消息泵模式，超时 {}ms）",
                timeout_ms
            );

            let result = run_with_message_pump(timeout_ms, move || {
                unsafe { func() };
            });

            match result {
                Ok(()) => {
                    // 输出最后的回调信息（如果有）
                    let callback_data = if CLI_CALLBACK_FIRED.load(Ordering::Relaxed) {
                        json!({
                            "last_callback": {
                                "msg_id": CLI_LAST_CALLBACK_MSG_ID.load(Ordering::Relaxed),
                                "w_param": CLI_LAST_CALLBACK_W_PARAM.load(Ordering::Relaxed),
                                "l_param": CLI_LAST_CALLBACK_L_PARAM.load(Ordering::Relaxed),
                            }
                        })
                    } else {
                        json!({})
                    };
                    info!("DownloadFirmware 完成");
                    exit_success(callback_data);
                }
                Err((code, msg)) => exit_error(&msg, code),
            }
        }
    }
}

// ============================================================
// CLI 入口
// ============================================================

/// CLI 模式主入口
///
/// 流程：解析参数 → 解压 DLL → 加载 → 创建窗口 → 执行命令 → 输出 JSON → 退出
pub fn run_cli_mode() {
    // 初始化日志（stderr，不污染 stdout 的 JSON 输出）
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info"))
        .target(env_logger::Target::Stderr)
        .init();

    info!("dll-bridge CLI 模式启动");

    // 解析 CLI 参数
    let cli = Cli::try_parse().unwrap_or_else(|e| {
        // clap 解析失败时输出错误信息到 stderr（clap 默认行为）
        eprint!("{}", e);
        std::process::exit(1);
    });

    // COM 初始化（与 main.rs IPC 模式一致）
    #[cfg(target_os = "windows")]
    {
        use windows_sys::Win32::System::Com::CoInitialize;
        let hr = unsafe { CoInitialize(std::ptr::null()) };
        if hr < 0 {
            log::warn!("COM 初始化返回: 0x{:08X}", hr as u32);
        }
    }

    // 初始化 DLL 和窗口
    let dll = cli_init();

    // 分发子命令
    match cli.command {
        CliCommand::GeneralMakeFiles {
            project_path,
            include_path,
            build_info,
        } => {
            exec_general_make_files(
                &dll,
                &project_path,
                include_path.as_deref(),
                build_info.as_deref(),
            );
        }
        CliCommand::DownloadCode {
            chip_name,
            hex_file_path,
        } => {
            exec_download_code(&dll, &chip_name, &hex_file_path);
        }
        CliCommand::FreeRun { main_addr } => {
            exec_free_run(&dll, main_addr);
        }
        CliCommand::BreakRun => {
            exec_break_run(&dll);
        }
        CliCommand::EnterDebug { mode } => {
            exec_enter_debug(&dll, mode);
        }
        CliCommand::ReadMem { length } => {
            exec_read_mem(&dll, length);
        }
        CliCommand::SetBreakpoint { address } => {
            exec_set_breakpoint(&dll, address);
        }
        CliCommand::DownloadFirmware { timeout } => {
            exec_download_firmware(&dll, timeout);
        }
    }
}
