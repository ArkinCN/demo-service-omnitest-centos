//! dll-bridge 32 位子进程入口文件（多线程架构）
//!
//!       DLL 实例存储在全局 Mutex 中，回调函数通过全局 stdout 锁实现线程安全写入。
//!
//! 架构设计（参考 Python fice_session.py）：
//! - stdin 读取线程：逐行读取 stdin → mpsc 通道 → 主线程
//! - 主线程：Windows 消息泵 + IPC 消息处理（非阻塞分发）
//! - Worker 线程：处理阻塞 DLL 调用（FreeRun/EnterDebugMode/DownloadFirmware）
//! - BreakRun：从主线程直接调用，可中断正在运行的 worker 线程
//!

// 仅在 Windows 平台编译，与 lib.rs 保持一致
#![cfg(target_os = "windows")]

use std::ffi::CString;
use std::io::{self, BufRead, Write};
use std::sync::Mutex;

// GBK 编码支持：Windows 本地 DLL 的 char* 参数期望 GBK（系统 ANSI 编码），而非 UTF-8
use encoding_rs::GBK;

use log::{error, info, warn};

use dll_bridge::ffi::FtGeneralDll;
use dll_bridge::ipc::{IpcMessage, IpcRequest, IpcResponse};
use dll_bridge::types::*;
use dll_bridge::window;

/// 全局 DLL 实例
static DLL: Mutex<Option<FtGeneralDll>> = Mutex::new(None);

/// 全局 stdout 写入锁
static STDOUT_LOCK: Mutex<()> = Mutex::new(());

/// 持久化 worker 线程的动作发送端
static WORKER_TX: Mutex<Option<std::sync::mpsc::Sender<WorkerAction>>> = Mutex::new(None);

/// 持久化 worker 线程句柄（Shutdown 时 join 用）
static WORKER_HANDLE: Mutex<Option<std::thread::JoinHandle<()>>> = Mutex::new(None);

/// 全局运行标志
static RUNNING: Mutex<bool> = Mutex::new(true);

/// Worker 线程运行状态标志
static WORKER_ACTIVE: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

/// 将 IpcResponse 序列化为 JSON 并写入 stdout（线程安全）
///
fn write_response_to_stdout(response: &IpcResponse) {
    let _lock = STDOUT_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    let mut stdout = io::stdout().lock();

    match response.to_json() {
        Ok(json) => {
            if let Err(e) = stdout.write_all(json.as_bytes()) {
                error!("写入响应 JSON 失败: {}", e);
            }
            if let Err(e) = stdout.write_all(b"\n") {
                error!("写入响应换行符失败: {}", e);
            }
            if let Err(e) = stdout.flush() {
                error!("刷新 stdout 失败: {}", e);
            }
        }
        Err(e) => {
            error!("响应序列化失败: {}", e);
        }
    }
}

/// DLL 回调函数，由 DLL 在编译/下载等操作过程中调用
///
///       通过 stdout 发送给主进程。使用 STDOUT_LOCK 保证线程安全。
///       FreeRun 期间 callback 频率极高（每秒数百次），为避免 stdout 管道阻塞
///       导致主线程无法处理 IPC 请求，对相同 msg_id 的事件进行节流。
extern "C" fn dll_callback(msg_id: i32, w_param: i32, l_param: i32) -> i32 {
    // Worker 线程执行阻塞 DLL 调用时，跳过回调写入避免 stdout 管道阻塞
    // 原因：FreeRun 期间 callback 频率极高，大量 JSON 写入会填满管道导致死锁
    if WORKER_ACTIVE.load(std::sync::atomic::Ordering::Relaxed) {
        return CALLBACK_RETURN_VALUE_PROCESSED;
    }

    // 节流：记录上次发送的 msg_id，相同事件不重复写 stdout
    // 原因：DLL 高频调用 callback（msg_id=40），大量 JSON 写入会填满 stdout 管道缓冲区
    use std::sync::atomic::{AtomicI32, Ordering};
    static LAST_MSG_ID: AtomicI32 = AtomicI32::new(i32::MIN);
    let prev = LAST_MSG_ID.swap(msg_id, Ordering::Relaxed);
    if prev == msg_id {
        // 与上次相同的 msg_id，跳过写 stdout，只返回已处理
        return CALLBACK_RETURN_VALUE_PROCESSED;
    }

    let event = IpcResponse::CallbackEvent {
        msg_id,
        w_param,
        l_param,
    };
    write_response_to_stdout(&event);
    CALLBACK_RETURN_VALUE_PROCESSED
}

/// 获取全局 DLL 实例的可变引用（通过闭包回调方式）
///
fn with_dll<F, R>(f: F) -> R
where
    F: FnOnce(Option<&FtGeneralDll>) -> R,
{
    let guard = DLL.lock().unwrap_or_else(|e| e.into_inner());
    f(guard.as_ref())
}

/// Worker 线程动作封装
struct WorkerAction {
    name: &'static str,
    action: Box<dyn FnOnce() + Send>,
    auto_shutdown: bool,
}

/// 初始化持久化 worker 线程（与 Python fice_session.py 的 _session_worker 一致）
///
///       线程启动时初始化 COM（Python: CoInitialize），确保 DLL 内部的
///       线程局部状态（TLS）在同一线程上保持一致。
fn init_worker_thread() {
    let (tx, rx) = std::sync::mpsc::channel::<WorkerAction>();

    let handle = std::thread::Builder::new()
        .name("dll-worker".to_string())
        .spawn(move || {
            // COM 初始化（与 Python _session_worker 的 CoInitialize 一致）
            // 原因：DLL 内部可能使用 COM 对象（如 USB/HID 通信），
            //       需要在 worker 线程上初始化 COM 才能正确工作
            #[cfg(target_os = "windows")]
            {
                use windows_sys::Win32::System::Com::CoInitialize;
                let hr = unsafe { CoInitialize(std::ptr::null()) };
                if hr < 0 {
                    warn!("Worker 线程 COM 初始化返回: 0x{:08X}", hr as u32);
                } else {
                    info!("Worker 线程 COM 初始化成功");
                }
            }

            // 设置 Worker 线程为最高优先级（与 Python fice_session.py 第 387-388 行一致）
            // 原因：DLL 的 FreeRun/BreakRun 内部线程同步依赖线程优先级，
            //       高优先级确保 FreeRun 线程在收到 BreakRun 信号后能及时被调度唤醒
            #[cfg(target_os = "windows")]
            {
                use windows_sys::Win32::System::Threading::{
                    GetCurrentThread, SetThreadPriority, THREAD_PRIORITY_HIGHEST,
                };
                unsafe {
                    SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_HIGHEST);
                }
                info!("Worker 线程优先级已设置为 THREAD_PRIORITY_HIGHEST");
            }

            info!("持久化 worker 线程已启动，等待任务...");

            // 循环接收并执行动作（channel 关闭时自动退出）
            for work in rx {
                // 标记 worker 活跃，dll_callback 将静默不写 stdout
                WORKER_ACTIVE.store(true, std::sync::atomic::Ordering::Relaxed);
                info!("[{}] worker 开始执行", work.name);

                (work.action)();

                // 动作完成，恢复回调写入
                WORKER_ACTIVE.store(false, std::sync::atomic::Ordering::Relaxed);
                info!("[{}] worker 执行完成", work.name);

                // DownloadFirmware 完成后自动触发 shutdown，释放 HID 设备
                if work.auto_shutdown {
                    info!("[{}] 自动触发 shutdown", work.name);
                    let mut running = RUNNING.lock().unwrap_or_else(|e| e.into_inner());
                    *running = false;
                }
            }

            // channel 关闭，清理 COM
            #[cfg(target_os = "windows")]
            {
                use windows_sys::Win32::System::Com::CoUninitialize;
                unsafe { CoUninitialize() };
            }
            info!("持久化 worker 线程退出");
        })
        .expect("创建持久化 worker 线程失败");

    // 存储 channel 发送端和线程句柄
    {
        let mut tx_guard = WORKER_TX.lock().unwrap_or_else(|e| e.into_inner());
        *tx_guard = Some(tx);
    }
    {
        let mut handle_guard = WORKER_HANDLE.lock().unwrap_or_else(|e| e.into_inner());
        *handle_guard = Some(handle);
    }
}

/// 向持久化 worker 线程发送动作（非阻塞）
///
fn spawn_worker_thread<F>(worker_name: &'static str, action: F, auto_shutdown: bool)
where
    F: FnOnce() + Send + 'static,
{
    let tx_guard = WORKER_TX.lock().unwrap_or_else(|e| e.into_inner());
    if let Some(tx) = tx_guard.as_ref() {
        if let Err(e) = tx.send(WorkerAction {
            name: worker_name,
            action: Box::new(action),
            auto_shutdown,
        }) {
            error!("[{}] 发送动作到 worker 线程失败: {}", worker_name, e);
        }
    } else {
        error!("[{}] worker 线程未初始化", worker_name);
    }
}

/// 处理 InitDll 请求 -- 加载指定路径的 DLL 文件
fn handle_init_dll(request_id: &str, dll_path: &str) -> IpcResponse {
    info!("开始加载 DLL: {}", dll_path);
    match FtGeneralDll::load(dll_path) {
        Ok(dll) => {
            let mut guard = DLL.lock().unwrap_or_else(|e| e.into_inner());
            if guard.is_some() {
                warn!("DLL 已加载，将被新实例替换");
            }
            *guard = Some(dll);
            let loaded_response = IpcResponse::DllLoaded {
                dll_path: dll_path.to_string(),
            };
            write_response_to_stdout(&loaded_response);
            IpcResponse::ok(request_id)
        }
        Err(e) => {
            error!("DLL 加载失败: {}", e);
            IpcResponse::error_with_code(
                request_id,
                format!("DLL 加载失败: {}", e),
                ERROR_CODE_DLL_LOAD_FAILED,
            )
        }
    }
}

/// 处理 GeneralMakeFiles 请求 -- 编译构建项目
fn handle_general_make_files(request_id: &str, project_path: &str) -> IpcResponse {
    // 使用 GBK 编码转换路径，因为 DLL 的 char* 参数期望 GBK（Windows ANSI 编码）
    let path_cstr = match utf8_to_gbk_cstring(project_path) {
        Ok(s) => s,
        Err(e) => {
            return IpcResponse::error_with_code(
                request_id,
                format!("工程路径编码转换失败: {}", e),
                ERROR_CODE_INVALID_PARAMS,
            );
        }
    };

    with_dll(|dll_opt| match dll_opt {
        None => IpcResponse::error_with_code(
            request_id,
            "DLL 未加载，请先调用 InitDll",
            ERROR_CODE_DLL_NOT_INITIALIZED,
        ),
        Some(dll) => match dll.general_make_files {
            None => IpcResponse::error_with_code(
                request_id,
                "DLL 中未找到 GeneralMakeFiles 函数",
                ERROR_CODE_DLL_CALL_FAILED,
            ),
            Some(func) => {
                let result = unsafe {
                    func(
                        GENERAL_MAKE_FILES_DEFAULT_TYPE,
                        path_cstr.as_ptr() as *const i8,
                    )
                };
                info!("GeneralMakeFiles 返回值: {}", result);
                if result == DLL_RETURN_SUCCESS {
                    IpcResponse::ok_with_data(request_id, serde_json::json!({"result": result}))
                } else {
                    IpcResponse::error_with_code(
                        request_id,
                        format!("GeneralMakeFiles 执行失败，返回码: {}", result),
                        ERROR_CODE_DLL_CALL_FAILED,
                    )
                }
            }
        },
    })
}

/// 将 UTF-8 字符串转换为 GBK 编码的 CString
///       中文路径在 UTF-8 和 GBK 下字节完全不同，直接传 UTF-8 会导致 DLL 解析路径失败。
fn utf8_to_gbk_cstring(s: &str) -> Result<CString, String> {
    let (encoded, _, had_errors) = GBK.encode(s);
    if had_errors {
        return Err(format!("{}{}", ERROR_MSG_GBK_ENCODE_FAILED, s));
    }
    CString::new(encoded.into_owned()).map_err(|e| format!("{}{}", ERROR_MSG_GBK_INTERIOR_NUL, e))
}

/// 处理 DownloadCode 请求 -- 固件下载到目标设备（worker 线程 + subst 路径映射）
///
///       Windows 消息（满足 DLL 文档要求）。
/// 路径编码策略：DLL 无法处理中文路径，通过 subst 驱动器映射将含中文的路径
///       转为纯 ASCII 路径后传给 DLL。subst 映射后路径是纯 ASCII，
///       UTF-8 = ASCII = GBK，直接用 CString::new 即可。
fn handle_download_code(request_id: &str, chip_name: &str, project_path: &str) -> IpcResponse {
    // 第一步：芯片名称参数转换（芯片名是 ASCII，直接用 CString::new 即可，无需 GBK 编码）
    let chip_cstr = match CString::new(chip_name) {
        Ok(s) => s,
        Err(e) => {
            return IpcResponse::error_with_code(
                request_id,
                format!("芯片名称包含非法字符: {}", e),
                ERROR_CODE_INVALID_PARAMS,
            );
        }
    };

    // 第二步：工程路径参数转换
    // 参照 Python fice_session.py：直接传原始路径（UTF-8 编码），不做 subst 映射
    // Python 实测：传含中文的 UTF-8 路径，DownloadCode 正常工作（耗时 ~28s 完成 USB 固件下载）
    // subst 虚拟盘符（如 S:\）反而导致 DLL 瞬间返回错误码 -1610479752
    let final_path_for_log = project_path.to_string();

    let path_cstr = match CString::new(project_path) {
        Ok(s) => s,
        Err(e) => {
            return IpcResponse::error_with_code(
                request_id,
                format!("工程路径包含非法字符: {}", e),
                ERROR_CODE_INVALID_PARAMS,
            );
        }
    };
    // 日志输出到 stderr，避免污染 stdout IPC 管道
    info!("[DownloadCode] 最终路径: {:?}", path_cstr);

    // 第三步：检查 DLL 是否已加载且 DownloadCode 函数可用
    {
        let guard = DLL.lock().unwrap_or_else(|e| e.into_inner());
        if guard.is_none() {
            return IpcResponse::error_with_code(
                request_id,
                "DLL 未加载，请先调用 InitDll",
                ERROR_CODE_DLL_NOT_INITIALIZED,
            );
        }
        if guard.as_ref().unwrap().download_code.is_none() {
            return IpcResponse::error_with_code(
                request_id,
                "DLL 中未找到 DownloadCode 函数",
                ERROR_CODE_DLL_CALL_FAILED,
            );
        }
    }

    // 第四步：在主线程直接调用 DownloadCode（与 Python fice_session.py 一致）
    // 原因：Python 中 DownloadCode 在主线程同步执行（第114行），DLL 可能在此时
    //       建立 USB/HID 连接并绑定到调用线程。如果在 worker 线程执行，
    //       后续 BreakRun（主线程）无法访问这些线程绑定的连接，导致无法中断 FreeRun。
    let func = with_dll(|dll_opt| dll_opt.as_ref().and_then(|dll| dll.download_code));
    let dll_result = match func {
        None => ERROR_CODE_DLL_CALL_FAILED,
        Some(func) => {
            info!("[DownloadCode] 主线程开始调用 DLL...");
            let result = unsafe {
                func(
                    chip_cstr.as_ptr() as *const i8,
                    path_cstr.as_ptr() as *const i8,
                )
            };
            info!(
                "[DownloadCode] DLL 返回值: {} (0x{:08X})",
                result, result as u32
            );
            result
        }
    };

    // 第七步：返回结果
    if dll_result == DLL_RETURN_SUCCESS {
        IpcResponse::ok_with_data(request_id, serde_json::json!({"result": dll_result}))
    } else {
        // 包含实际传给 DLL 的路径，方便调试路径问题
        IpcResponse::error_with_code(
            request_id,
            format!(
                "DownloadCode 执行失败，返回码: {}，实际路径: {}",
                dll_result, final_path_for_log
            ),
            ERROR_CODE_DLL_CALL_FAILED,
        )
    }
}

/// 处理 SetControllerWindowHandle 请求 -- 设置控制器窗口句柄
fn handle_set_controller_window_handle(request_id: &str, _handle: u64) -> IpcResponse {
    // 使用子进程自己的隐藏窗口句柄，而非主进程传入的值
    let hwnd = window::get_hidden_window_hwnd();
    with_dll(|dll_opt| match dll_opt {
        None => IpcResponse::error_with_code(
            request_id,
            "DLL 未加载，请先调用 InitDll",
            ERROR_CODE_DLL_NOT_INITIALIZED,
        ),
        Some(dll) => match dll.set_controller_window_handle {
            None => IpcResponse::error_with_code(
                request_id,
                "DLL 中未找到 SetControllerWindowHandle 函数",
                ERROR_CODE_DLL_CALL_FAILED,
            ),
            Some(func) => {
                let result = unsafe { func(hwnd) };
                info!(
                    "SetControllerWindowHandle(隐藏窗口 HWND) 返回值: {}",
                    result
                );
                if result == DLL_RETURN_SUCCESS {
                    IpcResponse::ok(request_id)
                } else {
                    IpcResponse::error_with_code(
                        request_id,
                        format!("SetControllerWindowHandle 失败，返回码: {}", result),
                        ERROR_CODE_DLL_CALL_FAILED,
                    )
                }
            }
        },
    })
}

/// 处理 SetCallBackFun 请求 -- 注册 DLL 回调函数
fn handle_set_callback_fun(request_id: &str) -> IpcResponse {
    with_dll(|dll_opt| match dll_opt {
        None => IpcResponse::error_with_code(
            request_id,
            "DLL 未加载，请先调用 InitDll",
            ERROR_CODE_DLL_NOT_INITIALIZED,
        ),
        Some(dll) => match dll.set_callback_fun {
            None => IpcResponse::error_with_code(
                request_id,
                "DLL 中未找到 SetCallBackFun 函数",
                ERROR_CODE_DLL_CALL_FAILED,
            ),
            Some(func) => {
                unsafe { func(Some(dll_callback)) };
                info!("DLL 回调函数已注册");
                IpcResponse::ok(request_id)
            }
        },
    })
}

/// 处理 SetBreakPoint 请求 -- 设置断点
/// 处理 SetBreakPoint 请求 -- 在 worker 线程上设置断点
///
///       Python fice_session.py 中 SetBreakPoint 在 _session_worker 线程执行，
///       DLL 内部可能在 SetBreakPoint 时初始化线程局部状态，BreakRun 依赖这些状态中断 FreeRun。
fn handle_set_break_point(request_id: &str, address: u32) -> IpcResponse {
    // 先检查 DLL 是否已加载
    {
        let guard = DLL.lock().unwrap_or_else(|e| e.into_inner());
        if guard.is_none() {
            return IpcResponse::error_with_code(
                request_id,
                "DLL 未加载，请先调用 InitDll",
                ERROR_CODE_DLL_NOT_INITIALIZED,
            );
        }
        if guard.as_ref().unwrap().set_break_point.is_none() {
            return IpcResponse::error_with_code(
                request_id,
                "DLL 中未找到 SetBreakPoint 函数",
                ERROR_CODE_DLL_CALL_FAILED,
            );
        }
    }

    // 在 worker 线程上执行 SetBreakPoint（与 Python _session_worker 一致）
    let (result_tx, result_rx) = std::sync::mpsc::channel::<IpcResponse>();
    let rid = request_id.to_string();

    spawn_worker_thread(
        "set-break-point",
        move || {
            let response = with_dll(
                |dll_opt| match dll_opt.and_then(|dll| dll.set_break_point) {
                    None => IpcResponse::error_with_code(
                        &rid,
                        "SetBreakPoint 函数不可用",
                        ERROR_CODE_DLL_CALL_FAILED,
                    ),
                    Some(func) => {
                        unsafe { func(address) };
                        info!("断点已设置: 地址=0x{:08X}", address);
                        IpcResponse::ok(&rid)
                    }
                },
            );
            let _ = result_tx.send(response);
        },
        false,
    );

    // 主线程等待结果（泵送消息避免 DLL 内部死锁）
    loop {
        if !window::pump_messages() {
            return IpcResponse::error_with_code(request_id, "收到 WM_QUIT", ERROR_CODE_GENERAL);
        }
        match result_rx.try_recv() {
            Ok(response) => return response,
            Err(std::sync::mpsc::TryRecvError::Empty) => {
                std::thread::sleep(std::time::Duration::from_millis(
                    MESSAGE_PUMP_TIMEOUT_MS as u64,
                ));
            }
            Err(std::sync::mpsc::TryRecvError::Disconnected) => {
                return IpcResponse::error_with_code(
                    request_id,
                    "SetBreakPoint worker 异常退出",
                    ERROR_CODE_GENERAL,
                );
            }
        }
    }
}

/// 处理 FreeRun 请求 -- 阻塞模式 MCU 启动序列（SetBreakPoint → EnterDebugMode → FreeRun）
///
///       等 FreeRun 确认运行后才返回成功响应（等待 500ms 确认 MCU 正常启动）。
///       FreeRun 继续在后台阻塞直到 BreakRun 中断。
fn handle_free_run(request_id: &str, main_addr: u32) -> IpcResponse {
    // 先检查 DLL 是否已加载
    {
        let guard = DLL.lock().unwrap_or_else(|e| e.into_inner());
        if guard.is_none() {
            return IpcResponse::error_with_code(
                request_id,
                "DLL 未加载，请先调用 InitDll",
                ERROR_CODE_DLL_NOT_INITIALIZED,
            );
        }
    }

    // 用 channel 等待 EnterDebugMode 完成，实现阻塞模式
    let (ready_tx, ready_rx) = std::sync::mpsc::channel::<Result<(), String>>();

    // 在 worker 线程中执行原子化启动序列
    spawn_worker_thread(
        "free-run",
        move || {
            let (bp_func, edm_func, fr_func) = with_dll(|dll_opt| {
                dll_opt
                    .as_ref()
                    .map(|dll| (dll.set_break_point, dll.enter_debug_mode, dll.free_run))
                    .unwrap_or((None, None, None))
            });

            // 第一步：SetBreakPoint（使用调用方传入的 main_addr，来自 MAP 文件解析）
            if let Some(func) = bp_func {
                info!(
                    "[FreeRun] worker 线程调用 SetBreakPoint(0x{:08X})...",
                    main_addr
                );
                unsafe { func(main_addr) };
                info!("[FreeRun] SetBreakPoint 完成");
            }

            // 第二步：EnterDebugMode（耗时约7秒）
            if let Some(func) = edm_func {
                info!("[FreeRun] worker 线程调用 EnterDebugMode(0)...");
                let result = unsafe { func(0) };
                info!(
                    "[FreeRun] EnterDebugMode 返回值: {} (0x{:08X})",
                    result, result as u32
                );
                if result != 0 {
                    // 非零返回值记录为警告，不中断流程
                    // 原因：DownloadCode 后 MCU 已在 debug 模式，EnterDebugMode 返回非零是正常的
                    warn!(
                        "[FreeRun] EnterDebugMode 返回非零值({}), 继续执行 FreeRun",
                        result
                    );
                }
            }

            // 第三步：FreeRun（阻塞直到 BreakRun 中断）
            // 必须在 worker 线程上调用（DLL 依赖线程局部状态，BreakRun 才能正确中断）
            // 通知点在 FreeRun 调用之前，确认 EnterDebugMode 成功且 FreeRun 函数就绪
            if let Some(func) = fr_func {
                info!("[FreeRun] worker 线程调用 FreeRun...");
                // EnterDebugMode 已完成，FreeRun 函数就绪，通知主线程返回成功
                let _ = ready_tx.send(Ok(()));
                // FreeRun 在 worker 线程上阻塞调用，BreakRun 可中断
                unsafe { func() };
                info!("[FreeRun] worker 线程 FreeRun 完成（已被 BreakRun 中断或 MCU 命中断点）");
            } else {
                error!("[FreeRun] FreeRun 函数指针为空");
                let _ = ready_tx.send(Err("FreeRun 函数指针为空".into()));
            }
        },
        false,
    );

    // 阻塞等待 FreeRun 确认运行（主线程在此等待，MCU 真正启动后才返回响应）
    match ready_rx.recv_timeout(std::time::Duration::from_secs(30)) {
        Ok(Ok(())) => {
            // MCU 已就绪，发送成功响应
            info!("[FreeRun] MCU 已启动，发送成功响应");
            let response = IpcResponse::ok(request_id);
            write_response_to_stdout(&response);
        }
        Ok(Err(msg)) => {
            // EnterDebugMode 失败
            error!("[FreeRun] 启动失败: {}", msg);
            let response =
                IpcResponse::error_with_code(request_id, &msg, ERROR_CODE_DLL_CALL_FAILED);
            write_response_to_stdout(&response);
        }
        Err(_) => {
            // 超时或 worker 线程 panic
            error!("[FreeRun] 等待 EnterDebugMode 超时（30秒）");
            let response = IpcResponse::error_with_code(
                request_id,
                "等待 EnterDebugMode 超时",
                ERROR_CODE_TIMEOUT,
            );
            write_response_to_stdout(&response);
        }
    }

    // 已手动发送响应，返回 Ready 占位符，外层会跳过发送
    IpcResponse::Ready
}

/// 处理 BreakRun 请求 -- 非阻塞停止运行
///
///       不在主线程执行 DLL 调用，避免阻塞消息泵（DLL 可能需要消息泵来完成中断）。
///       参考 Python fice_session.py 的 BreakRun 模式。
fn handle_break_run(request_id: &str) -> IpcResponse {
    // 诊断：记录 WORKER_ACTIVE 状态
    let worker_active = WORKER_ACTIVE.load(std::sync::atomic::Ordering::Relaxed);

    // 提取 BreakRun 函数指针（释放 DLL Mutex）
    let break_run_func = with_dll(|dll_opt| dll_opt.and_then(|dll| dll.break_run));

    match break_run_func {
        None => IpcResponse::error_with_code(
            request_id,
            format!(
                "DLL 未加载或未找到 BreakRun 函数 (worker_active={})",
                worker_active
            ),
            ERROR_CODE_DLL_CALL_FAILED,
        ),
        Some(func) => {
            // 第一次调用 BreakRun（与 Python fice_session.py 一致：主线程直接调用）
            unsafe { func() };

            // 第一次泵送消息（与 Python 主循环 _wait_msg + _pump 一致）
            // 原因：DLL 的 BreakRun 通过内部消息机制通知 FreeRun 返回，
            //       需要主线程泵送 Windows 消息才能完成中断
            let pump_deadline = std::time::Instant::now() + std::time::Duration::from_millis(500);
            while std::time::Instant::now() < pump_deadline {
                if !window::pump_messages() {
                    break;
                }
                #[cfg(target_os = "windows")]
                {
                    const QS_ALLINPUT: u32 = 0x04FF;
                    unsafe {
                        windows_sys::Win32::UI::WindowsAndMessaging::MsgWaitForMultipleObjects(
                            0,
                            std::ptr::null(),
                            windows_sys::Win32::Foundation::FALSE,
                            5,
                            QS_ALLINPUT,
                        );
                    }
                }
            }

            // 如果第一次 BreakRun 后 worker 仍活跃，调用第二次
            // 原因：实测发现 DLL 的 BreakRun 需要两次调用才能中断 FreeRun：
            //       第一次设置内部状态，第二次实际停止。
            //       Python 不需要两次是因为其主循环无限运行，
            //       持续调用 _wait_msg + _pump，等效于多次 BreakRun 尝试。
            if WORKER_ACTIVE.load(std::sync::atomic::Ordering::Relaxed) {
                unsafe { func() };
            }

            // 持续泵送消息直到 worker 停止（5 秒超时保护）
            let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
            while WORKER_ACTIVE.load(std::sync::atomic::Ordering::Relaxed) {
                if std::time::Instant::now() > deadline {
                    warn!("[BreakRun] 等待 worker 停止超时（5s）");
                    break;
                }
                if !window::pump_messages() {
                    break;
                }
                #[cfg(target_os = "windows")]
                {
                    const QS_ALLINPUT: u32 = 0x04FF;
                    unsafe {
                        windows_sys::Win32::UI::WindowsAndMessaging::MsgWaitForMultipleObjects(
                            0,
                            std::ptr::null(),
                            windows_sys::Win32::Foundation::FALSE,
                            5,
                            QS_ALLINPUT,
                        );
                    }
                }
            }

            let stopped = !WORKER_ACTIVE.load(std::sync::atomic::Ordering::Relaxed);
            IpcResponse::ok_with_data(
                request_id,
                serde_json::json!({
                    "break_run_called": true,
                    "worker_active": worker_active,
                    "mcu_stopped": stopped
                }),
            )
        }
    }
}

/// 处理 Reset 请求 -- 复位 MCU 并停在断点
///
fn handle_reset(request_id: &str, address: u32) -> IpcResponse {
    // 提取 BreakRun 函数指针
    let break_run_func = with_dll(|dll_opt| dll_opt.and_then(|dll| dll.break_run));

    // 第一步：BreakRun 停止 FreeRun（与 handle_break_run 逻辑一致）
    if let Some(func) = break_run_func {
        unsafe { func() };
        // 泵送消息 500ms
        let pump_deadline = std::time::Instant::now() + std::time::Duration::from_millis(500);
        while std::time::Instant::now() < pump_deadline {
            if !window::pump_messages() {
                break;
            }
            #[cfg(target_os = "windows")]
            {
                const QS_ALLINPUT: u32 = 0x04FF;
                unsafe {
                    windows_sys::Win32::UI::WindowsAndMessaging::MsgWaitForMultipleObjects(
                        0,
                        std::ptr::null(),
                        windows_sys::Win32::Foundation::FALSE,
                        5,
                        QS_ALLINPUT,
                    );
                }
            }
        }
        // 如果 worker 仍活跃，第二次 BreakRun
        if WORKER_ACTIVE.load(std::sync::atomic::Ordering::Relaxed) {
            unsafe { func() };
        }
        // 持续泵送直到 worker 停止
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
        while WORKER_ACTIVE.load(std::sync::atomic::Ordering::Relaxed) {
            if std::time::Instant::now() > deadline {
                break;
            }
            if !window::pump_messages() {
                break;
            }
            #[cfg(target_os = "windows")]
            {
                const QS_ALLINPUT: u32 = 0x04FF;
                unsafe {
                    windows_sys::Win32::UI::WindowsAndMessaging::MsgWaitForMultipleObjects(
                        0,
                        std::ptr::null(),
                        windows_sys::Win32::Foundation::FALSE,
                        5,
                        QS_ALLINPUT,
                    );
                }
            }
        }
    }

    let stopped = !WORKER_ACTIVE.load(std::sync::atomic::Ordering::Relaxed);

    // 第二步：在 worker 线程上执行 SetBreakPoint + EnterDebugMode（与 Python _handle_reset 一致）
    let (result_tx, result_rx) = std::sync::mpsc::channel::<IpcResponse>();
    let rid = request_id.to_string();

    spawn_worker_thread(
        "reset",
        move || {
            let (bp_func, edm_func) = with_dll(|dll_opt| {
                dll_opt
                    .as_ref()
                    .map(|dll| (dll.set_break_point, dll.enter_debug_mode))
                    .unwrap_or((None, None))
            });

            // SetBreakPoint（与 Python _handle_reset 第 342 行一致）
            if let Some(func) = bp_func {
                info!("[Reset] SetBreakPoint(0x{:08X})", address);
                unsafe { func(address) };
            }

            // EnterDebugMode(0)（与 Python _handle_reset 后续流程一致）
            if let Some(func) = edm_func {
                info!("[Reset] EnterDebugMode(0)");
                let result = unsafe { func(0) };
                info!("[Reset] EnterDebugMode 返回值: {}", result);
            }

            let _ = result_tx.send(IpcResponse::ok(&rid));
        },
        false,
    );

    // 主线程等待 worker 完成（泵送消息避免 DLL 内部死锁）
    // 超时保护：EnterDebugMode 正常 ~7 秒，超过 RESET_ENTER_DEBUG_MODE_TIMEOUT_MS 视为卡死
    // 救援机制：超时后从主线程调用 BreakRun 强制解除 EnterDebugMode 阻塞
    //           （与 Python fice_session.py 的 _EDM_TIMEOUT + BreakRun 救援机制一致）
    let reset_deadline = std::time::Instant::now()
        + std::time::Duration::from_millis(RESET_ENTER_DEBUG_MODE_TIMEOUT_MS);
    // 救援防重入哨兵：当前控制流在内层 while 结束后无条件 return，所以本次写入不会被再读取；
    // 保留 `mut` + 赋值是为了一旦未来把超时分支末尾的 `return` 改成 `continue`，外层 loop 重入时不会再次触发救援
    let mut rescue_break_run_sent = false;

    loop {
        // 检查 EnterDebugMode 超时
        if std::time::Instant::now() > reset_deadline {
            if !rescue_break_run_sent {
                // 首次超时：从主线程调用 BreakRun 强制解除 worker 的 EnterDebugMode 阻塞
                warn!(
                    "[Reset] EnterDebugMode 超时（{}ms），调用 BreakRun 强制解除阻塞",
                    RESET_ENTER_DEBUG_MODE_TIMEOUT_MS
                );
                if let Some(func) = break_run_func {
                    unsafe { func() };
                }
                // 救援防重入哨兵置位：当前内层 while 走完即 return，本次写入不会被再读取；
                // 保留赋值是为了将来若把外层超时分支末尾的 return 改成 continue 时，外层 loop 重入不再触发救援
                #[allow(unused_assignments)]
                {
                    rescue_break_run_sent = true;
                }
            }

            // 等待 BreakRun 救援生效（给 worker 时间退出 EnterDebugMode）
            let rescue_deadline =
                std::time::Instant::now() + std::time::Duration::from_millis(RESET_RESCUE_WAIT_MS);
            while std::time::Instant::now() < rescue_deadline {
                if !window::pump_messages() {
                    return IpcResponse::error_with_code(
                        request_id,
                        "收到 WM_QUIT",
                        ERROR_CODE_GENERAL,
                    );
                }
                match result_rx.try_recv() {
                    Ok(_) => {
                        warn!("[Reset] BreakRun 已解除 EnterDebugMode 阻塞（视为超时失败）");
                        return IpcResponse::error_with_code(
                            request_id,
                            &format!(
                                "Reset EnterDebugMode 超时（{}ms），已通过 BreakRun 强制中断",
                                RESET_ENTER_DEBUG_MODE_TIMEOUT_MS
                            ),
                            ERROR_CODE_TIMEOUT,
                        );
                    }
                    Err(std::sync::mpsc::TryRecvError::Empty) => {
                        std::thread::sleep(std::time::Duration::from_millis(
                            MESSAGE_PUMP_TIMEOUT_MS as u64,
                        ));
                    }
                    Err(std::sync::mpsc::TryRecvError::Disconnected) => {
                        return IpcResponse::error_with_code(
                            request_id,
                            "Reset worker 异常退出（EnterDebugMode 超时后）",
                            ERROR_CODE_GENERAL,
                        );
                    }
                }
            }
            // BreakRun 救援也超时，返回错误
            warn!("[Reset] BreakRun 救援后 worker 仍未退出");
            return IpcResponse::error_with_code(
                request_id,
                &format!(
                    "Reset 等待 worker 超时（{}ms + {}ms 救援等待）",
                    RESET_ENTER_DEBUG_MODE_TIMEOUT_MS, RESET_RESCUE_WAIT_MS
                ),
                ERROR_CODE_TIMEOUT,
            );
        }

        if !window::pump_messages() {
            return IpcResponse::error_with_code(request_id, "收到 WM_QUIT", ERROR_CODE_GENERAL);
        }
        match result_rx.try_recv() {
            Ok(_response) => {
                return IpcResponse::ok_with_data(
                    request_id,
                    serde_json::json!({
                        "mcu_stopped": stopped,
                        "reset_completed": true,
                    }),
                );
            }
            Err(std::sync::mpsc::TryRecvError::Empty) => {
                std::thread::sleep(std::time::Duration::from_millis(
                    MESSAGE_PUMP_TIMEOUT_MS as u64,
                ));
            }
            Err(std::sync::mpsc::TryRecvError::Disconnected) => {
                return IpcResponse::error_with_code(
                    request_id,
                    "Reset worker 异常退出",
                    ERROR_CODE_GENERAL,
                );
            }
        }
    }
}

/// 处理 ReadMemValue 请求 -- 读取目标芯片内存值
fn handle_read_mem_value(request_id: &str, length: u32) -> IpcResponse {
    if length == 0 {
        return IpcResponse::error_with_code(
            request_id,
            "读取长度不能为 0",
            ERROR_CODE_INVALID_PARAMS,
        );
    }
    if length as usize > MAX_READ_MEM_LENGTH {
        return IpcResponse::error_with_code(
            request_id,
            format!("读取长度 {} 超过最大限制 {}", length, MAX_READ_MEM_LENGTH),
            ERROR_CODE_INVALID_PARAMS,
        );
    }

    let mut buffer = vec![0u8; length as usize];
    with_dll(|dll_opt| match dll_opt {
        None => IpcResponse::error_with_code(
            request_id,
            "DLL 未加载，请先调用 InitDll",
            ERROR_CODE_DLL_NOT_INITIALIZED,
        ),
        Some(dll) => match dll.read_mem_value {
            None => IpcResponse::error_with_code(
                request_id,
                "DLL 中未找到 ReadMemValue 函数",
                ERROR_CODE_DLL_CALL_FAILED,
            ),
            Some(func) => {
                let bytes_read = unsafe { func(buffer.as_mut_ptr(), length) };
                info!("ReadMemValue 返回: 读取了 {} 字节", bytes_read);
                if bytes_read < 0 {
                    IpcResponse::error_with_code(
                        request_id,
                        format!("ReadMemValue 失败，错误码: {}", bytes_read),
                        ERROR_CODE_DLL_CALL_FAILED,
                    )
                } else {
                    let actual_len = bytes_read as usize;
                    let data = &buffer[..actual_len.min(buffer.len())];
                    IpcResponse::ok_with_data(
                        request_id,
                        serde_json::json!({"bytes": data, "length": actual_len}),
                    )
                }
            }
        },
    })
}

/// 处理 EnterDebugMode 请求 -- 非阻塞进入调试模式
///
///       参考 Python fice_session.py 的 worker 线程模式。
fn handle_enter_debug_mode(request_id: &str, mode: i32) -> IpcResponse {
    // 先检查 DLL 是否已加载
    {
        let guard = DLL.lock().unwrap_or_else(|e| e.into_inner());
        if guard.is_none() {
            return IpcResponse::error_with_code(
                request_id,
                "DLL 未加载，请先调用 InitDll",
                ERROR_CODE_DLL_NOT_INITIALIZED,
            );
        }
        if guard.as_ref().unwrap().enter_debug_mode.is_none() {
            return IpcResponse::error_with_code(
                request_id,
                "DLL 中未找到 EnterDebugMode 函数",
                ERROR_CODE_DLL_CALL_FAILED,
            );
        }
    }

    // 立即返回成功响应
    let response = IpcResponse::ok(request_id);
    write_response_to_stdout(&response);

    // 在 worker 线程中执行阻塞的 EnterDebugMode 调用
    spawn_worker_thread(
        "enter-debug-mode",
        move || {
            let func = with_dll(|dll_opt| dll_opt.as_ref().and_then(|dll| dll.enter_debug_mode));
            if let Some(func) = func {
                info!("EnterDebugMode worker 线程开始调用 DLL (mode={})...", mode);
                let result = unsafe { func(mode) };
                info!(
                    "EnterDebugMode worker 线程 DLL 调用完成，返回值: {}",
                    result
                );
            }
        },
        false,
    );

    // 已在上方手动发送响应，返回 Ready 占位符，外层会跳过发送
    IpcResponse::Ready
}

/// 处理 DownloadFirmware 请求 -- 阻塞模式固件升级
///
///       参考 Python fice_session.py 的 worker 线程模式。
fn handle_download_firmware(request_id: &str) -> IpcResponse {
    // 先提取函数指针，检查 DLL 和函数是否可用
    let func = with_dll(|dll_opt| dll_opt.as_ref().and_then(|dll| dll.download_firmware));
    if func.is_none() {
        // DLL 未加载或函数未找到，返回错误
        let dll_loaded = with_dll(|opt| opt.is_some());
        if !dll_loaded {
            return IpcResponse::error_with_code(
                request_id,
                "DLL 未加载，请先调用 InitDll",
                ERROR_CODE_DLL_NOT_INITIALIZED,
            );
        }
        return IpcResponse::error_with_code(
            request_id,
            "DLL 中未找到 DownloadFirmware 函数",
            ERROR_CODE_DLL_CALL_FAILED,
        );
    }

    // 阻塞调用，确保 DLL 关闭 HID 句柄后再返回，避免 PnP 幽灵设备节点
    let func = func.unwrap();
    info!("DownloadFirmware 阻塞模式：开始调用 DLL...");
    unsafe { func() };
    info!("DownloadFirmware 阻塞模式：DLL 调用完成");

    // DLL 调用完成后返回成功响应，主进程收到后才会执行 shutdown
    IpcResponse::ok(request_id)
}

/// 处理单个 IPC 消息
///
///       Shutdown 请求返回 true 表示应退出主循环。
///
///
/// 返回值：
/// - true: 应退出主循环
/// - false: 继续处理
fn handle_message(msg: &IpcMessage) -> bool {
    let request_id = &msg.id;

    let response = match &msg.payload {
        IpcRequest::InitDll { dll_path } => {
            info!("收到 InitDll 请求: dll_path={}", dll_path);
            handle_init_dll(request_id, dll_path)
        }

        IpcRequest::GeneralMakeFiles { project_path } => {
            info!("收到 GeneralMakeFiles 请求: project_path={}", project_path);
            handle_general_make_files(request_id, project_path)
        }

        IpcRequest::DownloadCode {
            chip_name,
            project_path,
        } => {
            info!(
                "收到 DownloadCode 请求: chip_name={}, project_path={}",
                chip_name, project_path
            );
            handle_download_code(request_id, chip_name, project_path)
        }

        IpcRequest::SetControllerWindowHandle { handle } => {
            info!("收到 SetControllerWindowHandle 请求: handle={}", handle);
            handle_set_controller_window_handle(request_id, *handle)
        }

        IpcRequest::SetCallBackFun => {
            info!("收到 SetCallBackFun 请求");
            handle_set_callback_fun(request_id)
        }

        IpcRequest::SetBreakPoint { address } => {
            info!("收到 SetBreakPoint 请求: address=0x{:08X}", address);
            handle_set_break_point(request_id, *address)
        }

        // 阻塞 FreeRun：等待 MCU 启动后才返回成功响应
        IpcRequest::FreeRun { main_addr } => {
            info!(
                "收到 FreeRun 请求（阻塞模式，main_addr=0x{:08X}）",
                main_addr
            );
            handle_free_run(request_id, *main_addr)
        }

        // BreakRun：主线程直接调用，可中断 worker
        IpcRequest::BreakRun => {
            info!("收到 BreakRun 请求");
            handle_break_run(request_id)
        }

        // Reset：BreakRun + SetBreakPoint + EnterDebugMode 复位 MCU
        IpcRequest::Reset { address } => {
            info!("收到 Reset 请求: address=0x{:08X}", address);
            handle_reset(request_id, *address)
        }

        IpcRequest::ReadMemValue { length } => {
            info!("收到 ReadMemValue 请求: length={}", length);
            handle_read_mem_value(request_id, *length)
        }

        // 非阻塞 EnterDebugMode：立即响应 + worker 线程后台执行
        IpcRequest::EnterDebugMode { mode } => {
            info!("收到 EnterDebugMode 请求（非阻塞模式）: mode={}", mode);
            handle_enter_debug_mode(request_id, *mode)
        }

        // 阻塞 DownloadFirmware：DLL 调用完成后才返回响应，确保 HID 句柄正常释放
        IpcRequest::DownloadFirmware => {
            info!("收到 DownloadFirmware 请求（阻塞模式）");
            handle_download_firmware(request_id)
        }

        IpcRequest::Shutdown => {
            info!("收到 Shutdown 请求，准备退出");

            // 关闭 worker channel，使持久化 worker 线程退出循环
            {
                let mut tx_guard = WORKER_TX.lock().unwrap_or_else(|e| e.into_inner());
                *tx_guard = None; // drop Sender，关闭 channel
                info!("Shutdown：已关闭 worker channel");
            }

            // 等待持久化 worker 线程退出
            {
                let mut handle_guard = WORKER_HANDLE.lock().unwrap_or_else(|e| e.into_inner());
                if let Some(handle) = handle_guard.take() {
                    info!("Shutdown：等待 worker 线程退出...");
                    let _ = handle.join();
                    info!("Shutdown：worker 线程已退出");
                }
            }

            // 清理 DLL 实例
            let mut guard = DLL.lock().unwrap_or_else(|e| e.into_inner());
            *guard = None;
            info!("DLL 实例已释放");
            write_response_to_stdout(&IpcResponse::ok(request_id));
            return true;
        }
    };

    // 对于 Ready 占位符不发送响应（非阻塞操作已自行发送）
    //       手动调用了 write_response_to_stdout，返回 Ready 作为占位符避免重复发送
    if !matches!(response, IpcResponse::Ready) {
        write_response_to_stdout(&response);
    }
    false
}

/// 启动 stdin 读取线程
///
///       主线程在 Windows 消息泵间隙从通道接收消息处理。
///
///
/// 参数：
/// - `tx`: mpsc 通道的发送端
///
/// 返回值：
/// - Ok(()): stdin 读取线程已启动
/// - Err(String): 线程创建失败
fn start_stdin_reader_thread(tx: std::sync::mpsc::Sender<IpcMessage>) -> Result<(), String> {
    std::thread::Builder::new()
        .name("stdin-reader".to_string())
        .spawn(move || {
            let stdin = io::stdin();
            let mut reader = stdin.lock();

            info!("stdin 读取线程已启动");
            loop {
                let mut line = String::new();
                match reader.read_line(&mut line) {
                    Ok(0) => {
                        info!("stdin 已关闭（EOF），主进程可能已退出");
                        break;
                    }
                    Ok(_) => {
                        let trimmed = line.trim();
                        if trimmed.is_empty() {
                            continue;
                        }

                        // 限制单行消息长度
                        if trimmed.len() > MAX_LINE_LENGTH {
                            error!("消息过长: {} 字节", trimmed.len());
                            write_response_to_stdout(&IpcResponse::error_with_code(
                                "unknown",
                                format!("消息过长: {} 字节", trimmed.len()),
                                ERROR_CODE_JSON_PARSE_FAILED,
                            ));
                            continue;
                        }

                        match IpcMessage::from_json(trimmed) {
                            Ok(msg) => {
                                if tx.send(msg).is_err() {
                                    info!("IPC 通道已关闭，退出 stdin 读取线程");
                                    break;
                                }
                            }
                            Err(e) => {
                                error!("JSON 解析失败: {}", e);
                                write_response_to_stdout(&IpcResponse::error_with_code(
                                    "unknown",
                                    format!("JSON 解析失败: {}", e),
                                    ERROR_CODE_JSON_PARSE_FAILED,
                                ));
                            }
                        }
                    }
                    Err(e) => {
                        error!("stdin 读取错误: {}", e);
                        break;
                    }
                }
            }
            info!("stdin 读取线程退出");
        })
        .map_err(|e| format!("创建 stdin 读取线程失败: {}", e))?;

    Ok(())
}

/// 子进程主函数（多线程架构）
///
///       在主线程运行 Windows 消息泵 + IPC 消息处理的主循环。
///
/// 架构流程：
/// 1. 初始化日志（stderr）
/// 2. COM 初始化（ole32 CoInitialize）
/// 3. 创建隐藏窗口（提供真实 HWND 给 DLL）
/// 4. 发送 Ready 信号
/// 5. 启动 stdin 读取线程
/// 6. 主循环：PeekMessage -> try_recv -> handle_message
/// 7. 退出时销毁窗口、清理 DLL
///
fn main() {
    // CLI 一次性执行模式检测：有命令行参数时走 CLI 路径，否则走 stdin/stdout IPC 模式
    let args: Vec<String> = std::env::args().collect();
    if args.len() > 1 {
        dll_bridge::cli::run_cli_mode();
        return;
    }

    // 初始化日志系统，输出到 stderr 避免污染 stdout IPC 管道
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info"))
        .target(env_logger::Target::Stderr)
        .init();

    info!(
        "dll-bridge 子进程启动（多线程架构），协议版本: {}",
        PROTOCOL_VERSION
    );

    // COM 初始化
    #[cfg(target_os = "windows")]
    {
        use windows_sys::Win32::System::Com::CoInitialize;
        let hr = unsafe { CoInitialize(std::ptr::null()) };
        if hr < 0 {
            warn!("COM 初始化返回: 0x{:08X}，继续执行", hr as u32);
        } else {
            info!("COM 初始化成功");
        }
    }

    // 创建隐藏窗口
    let hwnd = match window::create_hidden_window() {
        Ok(h) => {
            info!("隐藏窗口创建成功，HWND: {:?}", h);
            h
        }
        Err(e) => {
            error!("隐藏窗口创建失败: {}，继续执行（DLL 回调可能不工作）", e);
            std::ptr::null_mut() // HWND 类型正确的 null 值
        }
    };

    // 初始化持久化 worker 线程（与 Python _session_worker 一致）
    init_worker_thread();

    // 启动时发送 Ready 信号
    write_response_to_stdout(&IpcResponse::Ready);
    info!("已发送 Ready 信号，等待主进程请求...");

    // 创建 IPC 消息通道
    let (tx, rx) = std::sync::mpsc::channel::<IpcMessage>();

    // 启动 stdin 读取线程
    if let Err(e) = start_stdin_reader_thread(tx) {
        error!("启动 stdin 读取线程失败: {}", e);
        // 清理并退出
        if !hwnd.is_null() {
            window::destroy_hidden_window(hwnd);
        }
        return;
    }

    // 主循环：Windows 消息泵 + IPC 消息处理
    let mut should_exit = false;
    while !should_exit {
        // 检查是否应该退出
        {
            let running = RUNNING.lock().unwrap_or_else(|e| e.into_inner());
            if !*running {
                info!("收到退出信号（RUNNING=false），准备退出");
                break;
            }
        }

        // 处理 Windows 消息（非阻塞）
        if !window::pump_messages() {
            info!("收到 WM_QUIT，准备退出");
            break;
        }

        // 从 IPC 通道接收消息（非阻塞）
        match rx.try_recv() {
            Ok(msg) => {
                info!("收到消息: id={}", msg.id);
                if handle_message(&msg) {
                    should_exit = true;
                }
            }
            Err(std::sync::mpsc::TryRecvError::Empty) => {
                // 使用 MsgWaitForMultipleObjects 替代 thread::sleep（与 Python fice_session.py 的 _wait_msg 一致）
                // 原因：thread::sleep 只能等超时唤醒，DLL 通过 PostMessage 发送的回调消息会被延迟处理。
                //       MsgWaitForMultipleObjects 在有 Windows 消息时立即返回，确保 DLL 消息及时处理。
                //       Python 参考：_wait_msg(5) = MsgWaitForMultipleObjects(0, None, False, 5, QS_ALLINPUT)
                #[cfg(target_os = "windows")]
                {
                    const QS_ALLINPUT: u32 = 0x04FF;
                    unsafe {
                        windows_sys::Win32::UI::WindowsAndMessaging::MsgWaitForMultipleObjects(
                            0,                // 无句柄等待
                            std::ptr::null(), // 无句柄数组
                            windows_sys::Win32::Foundation::FALSE,
                            MESSAGE_PUMP_TIMEOUT_MS, // 超时时间（毫秒，与 Python _wait_msg 参数一致）
                            QS_ALLINPUT,             // 等待任何输入消息（包括 DLL PostMessage）
                        );
                    }
                }
            }
            Err(std::sync::mpsc::TryRecvError::Disconnected) => {
                info!("IPC 通道已断开，stdin 读取线程可能已退出");
                break;
            }
        }
    }

    // 退出清理
    info!("开始退出清理...");

    // 关闭 worker channel 并等待 worker 线程退出
    {
        let mut tx_guard = WORKER_TX.lock().unwrap_or_else(|e| e.into_inner());
        *tx_guard = None; // drop Sender，关闭 channel
    }
    {
        let mut handle_guard = WORKER_HANDLE.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(handle) = handle_guard.take() {
            info!("等待 worker 线程退出...");
            let _ = handle.join();
            info!("worker 线程已退出");
        }
    }

    // 清理 DLL 实例
    {
        let mut guard = DLL.lock().unwrap_or_else(|e| e.into_inner());
        *guard = None;
        info!("DLL 实例已释放");
    }

    // 销毁隐藏窗口
    if !hwnd.is_null() {
        window::destroy_hidden_window(hwnd);
        info!("隐藏窗口已销毁");
    }

    // COM 反初始化
    #[cfg(target_os = "windows")]
    {
        use windows_sys::Win32::System::Com::CoUninitialize;
        unsafe { CoUninitialize() };
        info!("COM 已反初始化");
    }

    info!("dll-bridge 子进程退出");
}
