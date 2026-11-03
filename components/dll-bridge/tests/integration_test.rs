//! dll-bridge 集成测试
//!
//! 验证 DLL Bridge 子进程的核心功能：隐藏窗口、DLL 符号解析、完整初始化序列和 FreeRun/BreakRun worker 模型。
//!
//! 需要真实 DLL 文件和可能的硬件设备连接；带 #[ignore] 的测试默认跳过。

// 仅在 Windows 平台编译
#![cfg(target_os = "windows")]

use dll_bridge::ffi::FtGeneralDll;
use dll_bridge::ipc::{IpcMessage, IpcRequest, IpcResponse};
use dll_bridge::types::*;
use dll_bridge::window;

/// 获取 IDE 目录下 FTGeneralUtils.dll 的路径
fn get_dll_path() -> String {
    // 默认路径：AppData/Roaming/com.motordebug.app/IDE/FTGeneralUtils.dll
    let app_data = std::env::var("APPDATA").expect("无法获取 APPDATA 环境变量");
    format!(
        "{}\\com.motordebug.app\\IDE\\{}",
        app_data,
        dll_bridge::DLL_FILE_NAME
    )
}

/// 测试隐藏窗口创建
#[test]
fn test_create_hidden_window() {
    let hwnd = window::create_hidden_window();
    assert!(hwnd.is_ok(), "隐藏窗口创建应成功: {:?}", hwnd.err());

    let hwnd = hwnd.unwrap();
    assert!(!hwnd.is_null(), "HWND 不应为 null");
    println!("✅ 隐藏窗口创建成功，HWND: {:?}", hwnd);

    // 验证 get_hidden_window_hwnd 返回相同值
    let stored_hwnd = window::get_hidden_window_hwnd();
    assert_eq!(hwnd, stored_hwnd, "全局存储的 HWND 应与返回值一致");

    // 清理
    window::destroy_hidden_window(hwnd);
    println!("✅ 隐藏窗口已销毁");
}

/// 测试消息泵非阻塞特性
#[test]
fn test_pump_messages_non_blocking() {
    // 先创建窗口（pump_messages 依赖窗口存在）
    let hwnd = window::create_hidden_window().expect("创建隐藏窗口失败");

    // pump_messages 在没有消息时应立即返回 true
    let start = std::time::Instant::now();
    let result = window::pump_messages();
    let elapsed = start.elapsed();

    assert!(result, "无消息时 pump_messages 应返回 true");
    assert!(
        elapsed.as_millis() < 100,
        "pump_messages 应非阻塞，耗时: {:?}",
        elapsed
    );
    println!("✅ pump_messages 非阻塞验证通过，耗时: {:?}", elapsed);

    // 清理
    window::destroy_hidden_window(hwnd);
}

/// 测试 DLL 加载和符号解析
#[test]
fn test_dll_load_and_symbols() {
    let dll_path = get_dll_path();
    if !std::path::Path::new(&dll_path).exists() {
        eprintln!("⚠️ 跳过：DLL 文件不存在: {}", dll_path);
        return;
    }

    let dll = FtGeneralDll::load(&dll_path);
    assert!(dll.is_ok(), "DLL 加载应成功: {:?}", dll.err());

    let dll = dll.unwrap();

    // 验证所有 12 个导出函数都已解析
    assert!(
        dll.general_make_files.is_some(),
        "GeneralMakeFiles 应已解析"
    );
    assert!(dll.download_code.is_some(), "DownloadCode 应已解析");
    assert!(
        dll.set_controller_window_handle.is_some(),
        "SetControllerWindowHandle 应已解析"
    );
    assert!(dll.set_callback_fun.is_some(), "SetCallBackFun 应已解析");
    assert!(dll.set_break_point.is_some(), "SetBreakPoint 应已解析");
    assert!(dll.free_run.is_some(), "FreeRun 应已解析");
    assert!(dll.break_run.is_some(), "BreakRun 应已解析");
    assert!(dll.read_mem_value.is_some(), "ReadMemValue 应已解析");
    assert!(dll.enter_debug_mode.is_some(), "EnterDebugMode 应已解析");
    assert!(dll.download_firmware.is_some(), "DownloadFirmware 应已解析");
    assert!(
        dll.set_keil_include_path.is_some(),
        "SetKeilIncludePath 应已解析"
    );
    assert!(
        dll.set_keil_build_exter_info.is_some(),
        "SetKeilBuildExterInfo 应已解析"
    );

    println!("✅ DLL 加载成功，12/12 个导出函数已解析");
}

/// 测试 DLL 完整初始化序列
///       DLL 加载 → 创建隐藏窗口 → SetControllerWindowHandle → SetCallBackFun
#[test]
fn test_full_initialization_sequence() {
    let dll_path = get_dll_path();
    if !std::path::Path::new(&dll_path).exists() {
        eprintln!("⚠️ 跳过：DLL 文件不存在: {}", dll_path);
        return;
    }

    // 步骤 1：创建隐藏窗口
    let hwnd = window::create_hidden_window().expect("隐藏窗口创建失败");
    println!("步骤 1 ✅ 隐藏窗口创建成功，HWND: {:?}", hwnd);

    // 步骤 2：加载 DLL
    let dll = FtGeneralDll::load(&dll_path).expect("DLL 加载失败");
    println!("步骤 2 ✅ DLL 加载成功");

    // 步骤 3：SetControllerWindowHandle（使用隐藏窗口的真实 HWND）
    if let Some(func) = dll.set_controller_window_handle {
        let result = unsafe { func(hwnd) };
        assert_eq!(
            result, DLL_RETURN_SUCCESS,
            "SetControllerWindowHandle 应返回成功，实际返回: {}",
            result
        );
        println!(
            "步骤 3 ✅ SetControllerWindowHandle(HWND={:?}) 返回: {}",
            hwnd, result
        );
    }

    // 步骤 4：SetCallBackFun（注册空回调）
    extern "C" fn test_callback(_msg_id: i32, _w_param: i32, _l_param: i32) -> i32 {
        CALLBACK_RETURN_VALUE_PROCESSED
    }
    if let Some(func) = dll.set_callback_fun {
        unsafe { func(Some(test_callback)) };
        println!("步骤 4 ✅ SetCallBackFun 注册成功");
    }

    // 步骤 5：处理消息（验证消息泵不阻塞）
    let pump_result = window::pump_messages();
    assert!(pump_result, "消息泵应返回 true");
    println!("步骤 5 ✅ 消息泵运行正常");

    // 清理
    window::destroy_hidden_window(hwnd);
    println!("✅ 完整初始化序列测试通过");
}

/// 测试所有 IPC 请求类型的序列化/反序列化
#[test]
fn test_all_ipc_request_types() {
    let requests = vec![
        IpcRequest::InitDll {
            dll_path: "C:\\test\\FTGeneralUtils.dll".to_string(),
        },
        IpcRequest::GeneralMakeFiles {
            project_path: "C:\\test\\project".to_string(),
        },
        IpcRequest::DownloadCode {
            chip_name: "FT32F030".to_string(),
            project_path: "C:\\test\\project".to_string(),
        },
        IpcRequest::SetControllerWindowHandle { handle: 12345 },
        IpcRequest::SetCallBackFun,
        IpcRequest::SetBreakPoint {
            address: 0x08000000,
        },
        IpcRequest::FreeRun {
            main_addr: DEFAULT_BREAKPOINT_ADDR,
        },
        IpcRequest::BreakRun,
        IpcRequest::ReadMemValue { length: 256 },
        IpcRequest::EnterDebugMode { mode: 0 },
        IpcRequest::DownloadFirmware,
        IpcRequest::Shutdown,
    ];

    // 验证每种请求都能正确序列化/反序列化
    for request in requests {
        let msg = IpcMessage::new(request);
        let json = msg.to_json().expect("序列化应成功");

        // 验证 JSON 格式正确：顶层 IpcMessage 有 id/timestamp/payload，type 在 payload 内
        let value: serde_json::Value = serde_json::from_str(&json).expect("JSON 解析应成功");
        assert!(value["id"].is_string(), "消息应有 id 字段");
        assert!(value["payload"].is_object(), "消息应有 payload 字段");
        assert!(
            value["payload"]["type"].is_string(),
            "payload 内应有 type 字段（IpcRequest 内部 tag）"
        );

        // 验证反序列化
        let restored = IpcMessage::from_json(&json).expect("反序列化应成功");
        assert_eq!(msg.id, restored.id, "消息 ID 应一致");
    }
    println!("✅ 所有 12 种 IPC 请求类型序列化测试通过");
}

/// 测试 IpcResponse 所有变体的序列化/反序列化
#[test]
fn test_all_ipc_response_types() {
    let responses = vec![
        IpcResponse::ok("test-1"),
        IpcResponse::ok_with_data("test-2", serde_json::json!({"result": 0})),
        IpcResponse::error("test-3", "测试错误"),
        IpcResponse::error_with_code("test-4", "DLL 错误", ERROR_CODE_DLL_CALL_FAILED),
        IpcResponse::CallbackEvent {
            msg_id: 100,
            w_param: 1,
            l_param: 2,
        },
        IpcResponse::DllLoaded {
            dll_path: "C:\\test.dll".to_string(),
        },
        IpcResponse::Ready,
    ];

    for response in responses {
        let json = response.to_json().expect("响应序列化应成功");
        let restored = IpcResponse::from_json(&json).expect("响应反序列化应成功");
        assert_eq!(
            response.request_id(),
            restored.request_id(),
            "request_id 应一致"
        );
    }
    println!("✅ 所有 7 种 IPC 响应类型序列化测试通过");
}

/// 测试 FreeRun + BreakRun 非阻塞模式（需要硬件设备）
/// 使用 cargo test -- --ignored 运行此测试
#[test]
#[ignore = "需要连接真实 HID 设备"]
fn test_freerun_breakrun_nonblocking() {
    let dll_path = get_dll_path();
    if !std::path::Path::new(&dll_path).exists() {
        panic!("DLL 文件不存在: {}", dll_path);
    }

    // 初始化序列
    let hwnd = window::create_hidden_window().expect("窗口创建失败");
    let dll = FtGeneralDll::load(&dll_path).expect("DLL 加载失败");

    // SetControllerWindowHandle
    if let Some(func) = dll.set_controller_window_handle {
        let result = unsafe { func(hwnd) };
        assert_eq!(result, DLL_RETURN_SUCCESS, "SetControllerWindowHandle 失败");
    }

    // SetCallBackFun
    extern "C" fn test_cb(_msg_id: i32, _w_param: i32, _l_param: i32) -> i32 {
        CALLBACK_RETURN_VALUE_PROCESSED
    }
    if let Some(func) = dll.set_callback_fun {
        unsafe { func(Some(test_cb)) };
    }

    // SetBreakPoint
    if let Some(func) = dll.set_break_point {
        unsafe { func(0x08000000) };
        println!("✅ SetBreakPoint(0x08000000) 已设置");
    }

    // EnterDebugMode（非阻塞测试）
    if let Some(func) = dll.enter_debug_mode {
        let result = unsafe { func(0) };
        println!("EnterDebugMode(0) 返回: {}", result);
    }

    // FreeRun（非阻塞验证）
    let start = std::time::Instant::now();
    if let Some(func) = dll.free_run {
        unsafe { func() };
    }
    let elapsed = start.elapsed();
    println!("FreeRun 耗时: {:?}", elapsed);

    // 等待一小段时间让 MCU 运行
    std::thread::sleep(std::time::Duration::from_millis(500));

    // BreakRun（非阻塞验证）
    if let Some(func) = dll.break_run {
        unsafe { func() };
        println!("✅ BreakRun 已执行");
    }

    // 处理残留消息
    window::pump_messages();

    // 清理
    window::destroy_hidden_window(hwnd);
    println!("✅ FreeRun/BreakRun 非阻塞测试通过");
}

/// 测试 DownloadFirmware 完整流程（需要硬件设备）
/// 使用 cargo test -- --ignored 运行此测试
#[test]
#[ignore = "需要连接真实 HID 设备"]
fn test_download_firmware() {
    let dll_path = get_dll_path();
    if !std::path::Path::new(&dll_path).exists() {
        panic!("DLL 文件不存在: {}", dll_path);
    }

    // 初始化序列
    let hwnd = window::create_hidden_window().expect("窗口创建失败");
    let dll = FtGeneralDll::load(&dll_path).expect("DLL 加载失败");

    if let Some(func) = dll.set_controller_window_handle {
        let result = unsafe { func(hwnd) };
        assert_eq!(result, DLL_RETURN_SUCCESS);
    }

    extern "C" fn test_cb2(msg_id: i32, w_param: i32, l_param: i32) -> i32 {
        println!(
            "回调: msg_id={}, w_param={}, l_param={}",
            msg_id, w_param, l_param
        );
        CALLBACK_RETURN_VALUE_PROCESSED
    }
    if let Some(func) = dll.set_callback_fun {
        unsafe { func(Some(test_cb2)) };
    }

    // DownloadFirmware（阻塞调用，可能需要较长时间）
    println!("开始 DownloadFirmware...");
    let start = std::time::Instant::now();
    if let Some(func) = dll.download_firmware {
        unsafe { func() };
    }
    let elapsed = start.elapsed();
    println!("✅ DownloadFirmware 完成，耗时: {:?}", elapsed);

    // 处理残留消息
    window::pump_messages();

    // 清理
    window::destroy_hidden_window(hwnd);
    println!("✅ DownloadFirmware 测试通过");
}

// 使用 cargo test --target i686-pc-windows-msvc -p dll-bridge -- --ignored 运行

/// MCU 测试的默认断点地址（芯片复位向量）
const TEST_BREAKPOINT_ADDR: u32 = 0x08000000;

/// MCU 测试的读取缓冲区大小
const TEST_READ_BUFFER_SIZE: u32 = 256;

/// MCU 启动等待时间（毫秒）
const MCU_STARTUP_WAIT_MS: u64 = 2000;

/// MCU 操作间短暂等待时间（毫秒）
const MCU_SETTLE_WAIT_MS: u64 = 200;

/// MCU 复位/重启等待时间（毫秒）
const MCU_RESET_WAIT_MS: u64 = 1500;

/// MCU 停止后短暂稳定时间（毫秒）
const MCU_STOP_SETTLE_MS: u64 = 100;

/// MCU 恢复运行等待时间（毫秒）
const MCU_RESUME_WAIT_MS: u64 = 1000;

/// 内存读取哨兵值
const MEM_READ_SENTINEL: u8 = 0xFF;

/// 内存预览打印最大字节数
const MEM_PREVIEW_LENGTH: usize = 32;

use std::sync::atomic::{AtomicBool, AtomicI32, AtomicUsize, Ordering};
use std::sync::Arc;

/// 回调事件计数器（线程安全）
static CALLBACK_COUNT: AtomicUsize = AtomicUsize::new(0);

/// 最后一次回调的消息 ID（线程安全）
static CALLBACK_LAST_MSG_ID: AtomicI32 = AtomicI32::new(0);

/// DLL 回调函数（用于 MCU 启停测试）
extern "C" fn mcu_test_callback(msg_id: i32, _w_param: i32, _l_param: i32) -> i32 {
    // 递增回调计数器，使用 SeqCst 保证多线程可见性
    CALLBACK_COUNT.fetch_add(1, Ordering::SeqCst);
    // 记录最新回调的消息 ID
    CALLBACK_LAST_MSG_ID.store(msg_id, Ordering::SeqCst);
    CALLBACK_RETURN_VALUE_PROCESSED
}

/// MCU 测试共享初始化函数
///
///       统一所有 MCU 测试的前置初始化步骤，避免重复代码
///
///
/// 返回值：(&'static FtGeneralDll, HWND) 元组
///   - &'static 引用：通过 Box::leak 获得，可安全跨线程传递（满足 'static 约束）
///   - HWND：用于清理窗口资源
fn mcu_test_init() -> (&'static FtGeneralDll, windows_sys::Win32::Foundation::HWND) {
    // 获取 DLL 文件路径
    let dll_path = get_dll_path();
    if !std::path::Path::new(&dll_path).exists() {
        panic!("DLL 文件不存在: {}", dll_path);
    }

    // 重置回调计数器（确保每次测试从零开始）
    CALLBACK_COUNT.store(0, Ordering::SeqCst);
    CALLBACK_LAST_MSG_ID.store(0, Ordering::SeqCst);

    // 创建隐藏窗口（提供真实 HWND 给 DLL）
    let hwnd = window::create_hidden_window().expect("隐藏窗口创建失败");

    // 加载 DLL 并解析导出函数
    //       这是安全的，因为：测试函数退出后进程即结束，不会造成内存泄漏问题
    //       且 FtGeneralDll 的函数指针必须在整个测试期间保持有效
    let dll = FtGeneralDll::load(&dll_path).expect("DLL 加载失败");
    let dll = Box::leak(Box::new(dll));

    // SetControllerWindowHandle：将窗口句柄传给 DLL
    if let Some(func) = dll.set_controller_window_handle {
        let result = unsafe { func(hwnd) };
        assert_eq!(
            result, DLL_RETURN_SUCCESS,
            "SetControllerWindowHandle 失败: {}",
            result
        );
    }

    // SetCallBackFun：注册回调函数
    if let Some(func) = dll.set_callback_fun {
        unsafe { func(Some(mcu_test_callback)) };
    }

    (dll, hwnd)
}

/// 执行 MCU 启动序列（阻塞操作，应在 worker 线程中调用）
///
///       SetBreakPoint -> EnterDebugMode(0) -> FreeRun
///       其中 FreeRun 是阻塞操作，会持续运行直到被 BreakRun 中断
///
///
/// 参数：
/// - dll: DLL 实例的 'static 引用（通过 Box::leak 获得，可安全跨线程传递）
/// - breakpoint_addr: 断点地址（芯片复位向量）
fn mcu_start_sequence(dll: &'static FtGeneralDll, breakpoint_addr: u32) {
    // 步骤 1：SetBreakPoint（设置芯片复位地址为断点）
    if let Some(func) = dll.set_break_point {
        unsafe { func(breakpoint_addr) };
        println!("  [启动] SetBreakPoint(0x{:08X}) 完成", breakpoint_addr);
    }

    // 步骤 2：EnterDebugMode(0)（进入调试模式，mode=0 表示默认模式）
    if let Some(func) = dll.enter_debug_mode {
        let result = unsafe { func(0) };
        println!("  [启动] EnterDebugMode(0) 返回: {}", result);
    }

    // 步骤 3：FreeRun（阻塞操作，MCU 全速运行直到被 BreakRun 中断）
    if let Some(func) = dll.free_run {
        println!("  [启动] FreeRun 开始...");
        unsafe { func() };
        println!("  [启动] FreeRun 完成（已被 BreakRun 中断）");
    }
}

/// 测试 MCU 完整启停流程（需要硬件设备）
///
///
/// 流程：
///   1. 初始化（DLL 加载 + 窗口 + SetControllerWindowHandle + SetCallBackFun）
///   2. 启动 MCU（SetBreakPoint -> EnterDebugMode -> FreeRun，在 worker 线程中执行）
///   3. 等待 MCU 运行并验证回调触发
///   4. 停止 MCU（BreakRun，在主线程中执行）
///   5. 等待 worker 线程正常退出
///
/// 参考 Python fice_session.py 的 _session_worker 线程模式：
/// - FreeRun 在独立线程执行（阻塞操作）
/// - BreakRun 在主线程执行（非阻塞，中断 FreeRun）
///
///
/// 使用 cargo test --target i686-pc-windows-msvc -p dll-bridge -- --ignored 运行此测试
#[test]
#[ignore = "需要连接真实 HID 设备"]
fn test_mcu_start_stop() {
    // Phase 0: 共享初始化
    let (dll, hwnd) = mcu_test_init();
    println!("MCU 测试初始化完成");

    // Phase 1: 启动 MCU（在 worker 线程中执行，因为 FreeRun 是阻塞操作）
    // dll 为 &'static FtGeneralDll，满足线程 'static 约束
    let dll_for_worker = dll;
    let start_handle = std::thread::Builder::new()
        .name("mcu-start-worker".to_string())
        .spawn(move || {
            mcu_start_sequence(dll_for_worker, TEST_BREAKPOINT_ADDR);
        })
        .expect("创建启动 worker 线程失败");

    // 等待 MCU 启动并运行一段时间
    println!("等待 MCU 启动...");
    std::thread::sleep(std::time::Duration::from_millis(MCU_STARTUP_WAIT_MS));

    // 处理 Windows 消息（DLL 可能通过 PostMessage 发送回调通知）
    window::pump_messages();

    // 验证回调已被触发
    let callback_count = CALLBACK_COUNT.load(Ordering::SeqCst);
    println!("当前回调触发次数: {}", callback_count);

    // Phase 2: 停止 MCU（在主线程执行 BreakRun）
    println!("正在停止 MCU...");
    if let Some(func) = dll.break_run {
        unsafe { func() };
        println!("BreakRun 已执行");
    }

    // 等待 worker 线程完成（FreeRun 被 BreakRun 中断后应正常退出）
    let join_result = start_handle.join();
    assert!(
        join_result.is_ok(),
        "worker 线程 join 失败: {:?}",
        join_result.err()
    );
    println!("worker 线程已正常完成");

    // 处理残留消息
    window::pump_messages();

    // 清理资源
    window::destroy_hidden_window(hwnd);
    println!("MCU 完整启停测试通过");
}

/// 测试 MCU 复位流程（需要硬件设备）
///
///
/// 流程：
///   1. 首次启动 MCU（SetBreakPoint -> EnterDebugMode -> FreeRun）
///   2. 停止 MCU（BreakRun）
///   3. 复位序列（BreakRun -> SetBreakPoint -> ReadMemValue -> SetBreakPoint -> EnterDebugMode）
///   4. 重新启动 MCU（FreeRun）
///   5. 最终停止（BreakRun）
///
/// 参考 Python fice_session.py 的 _handle_reset 函数
///
///
/// 使用 cargo test --target i686-pc-windows-msvc -p dll-bridge -- --ignored 运行此测试
#[test]
#[ignore = "需要连接真实 HID 设备"]
fn test_mcu_reset_sequence() {
    // Phase 0: 共享初始化
    let (dll, hwnd) = mcu_test_init();
    println!("MCU 测试初始化完成（复位测试）");

    // Phase 1: 首次启动 MCU
    // dll 为 &'static FtGeneralDll，满足线程 'static 约束
    let dll_for_start = dll;
    let start_handle = std::thread::Builder::new()
        .name("mcu-reset-worker-1".to_string())
        .spawn(move || {
            mcu_start_sequence(dll_for_start, TEST_BREAKPOINT_ADDR);
        })
        .expect("创建 worker 线程 1 失败");

    // 等待 MCU 启动并稳定运行
    std::thread::sleep(std::time::Duration::from_millis(MCU_RESET_WAIT_MS));
    window::pump_messages();
    println!("Phase 1: MCU 首次启动完成");

    // Phase 2: 停止 MCU
    if let Some(func) = dll.break_run {
        unsafe { func() };
    }
    // 等待 worker 线程结束
    let _ = start_handle.join();
    window::pump_messages();
    println!("Phase 2: MCU 已停止");

    // Phase 3: 复位序列（参考 Python _handle_reset 函数）

    // 步骤 3a: 再次确认停止（复位前确保 MCU 完全停止）
    if let Some(func) = dll.break_run {
        unsafe { func() };
    }
    std::thread::sleep(std::time::Duration::from_millis(MCU_STOP_SETTLE_MS));

    // 步骤 3b: 设置断点（复位向量的断点地址）
    if let Some(func) = dll.set_break_point {
        unsafe { func(TEST_BREAKPOINT_ADDR) };
        println!(
            "  [复位] SetBreakPoint(0x{:08X}) 完成",
            TEST_BREAKPOINT_ADDR
        );
    }

    // 步骤 3c: 读取内存（复位流程中的读取步骤）
    if let Some(func) = dll.read_mem_value {
        let mut buf = vec![0u8; TEST_READ_BUFFER_SIZE as usize];
        let bytes_read = unsafe { func(buf.as_mut_ptr(), TEST_READ_BUFFER_SIZE) };
        println!("  [复位] ReadMemValue 返回: {} 字节", bytes_read);
    }

    // 步骤 3d: 重新设置断点（确保断点生效）
    if let Some(func) = dll.set_break_point {
        unsafe { func(TEST_BREAKPOINT_ADDR) };
    }

    // Phase 4: 重新启动 MCU（验证复位后可正常启动）
    // dll 为 &'static FtGeneralDll，满足线程 'static 约束
    let dll_for_restart = dll;
    let restart_handle = std::thread::Builder::new()
        .name("mcu-reset-worker-2".to_string())
        .spawn(move || {
            // EnterDebugMode（进入调试模式）
            if let Some(func) = dll_for_restart.enter_debug_mode {
                let result = unsafe { func(0) };
                println!("  [复位] EnterDebugMode(0) 返回: {}", result);
            }
            // FreeRun（阻塞操作，MCU 全速运行）
            if let Some(func) = dll_for_restart.free_run {
                unsafe { func() };
                println!("  [复位] FreeRun 完成");
            }
        })
        .expect("创建 worker 线程 2 失败");

    // 等待 MCU 复位后启动稳定
    std::thread::sleep(std::time::Duration::from_millis(MCU_RESET_WAIT_MS));
    println!("Phase 4: MCU 复位后重新启动完成");

    // Phase 5: 最终停止（清理 MCU 运行状态）
    if let Some(func) = dll.break_run {
        unsafe { func() };
    }
    let _ = restart_handle.join();
    window::pump_messages();
    println!("Phase 5: MCU 最终停止完成");

    // 清理资源
    window::destroy_hidden_window(hwnd);
    println!("MCU 复位流程测试通过");
}

/// 测试 MCU 内存读取流程（需要硬件设备）
///
///
/// 流程：
///   1. 启动 MCU（SetBreakPoint -> EnterDebugMode -> FreeRun）
///   2. 停止 MCU（BreakRun，ReadMemValue 需要 MCU 处于停止状态）
///   3. 读取内存（ReadMemValue，带哨兵值检测机制）
///   4. 恢复运行（FreeRun）
///   5. 最终停止（BreakRun）
///
/// 参考 Python fice_session.py 的 _readmem_dedicated_worker
///
///
/// 使用 cargo test --target i686-pc-windows-msvc -p dll-bridge -- --ignored 运行此测试
#[test]
#[ignore = "需要连接真实 HID 设备"]
fn test_mcu_read_mem_value() {
    // Phase 0: 共享初始化
    let (dll, hwnd) = mcu_test_init();
    println!("MCU 测试初始化完成（内存读取测试）");

    // Phase 1: 启动 MCU
    // dll 为 &'static FtGeneralDll，满足线程 'static 约束
    let dll_for_start = dll;
    let start_handle = std::thread::Builder::new()
        .name("mcu-read-worker-1".to_string())
        .spawn(move || {
            mcu_start_sequence(dll_for_start, TEST_BREAKPOINT_ADDR);
        })
        .expect("创建启动 worker 线程失败");

    // 等待 MCU 启动并稳定
    std::thread::sleep(std::time::Duration::from_millis(MCU_RESET_WAIT_MS));
    window::pump_messages();
    println!("Phase 1: MCU 已启动");

    // Phase 2: 停止 MCU 以读取内存
    if let Some(func) = dll.break_run {
        unsafe { func() };
    }
    // 等待 worker 线程结束（FreeRun 被 BreakRun 中断）
    let _ = start_handle.join();
    // 等待 MCU 完全停止
    std::thread::sleep(std::time::Duration::from_millis(MCU_SETTLE_WAIT_MS));
    window::pump_messages();
    println!("Phase 2: MCU 已停止，准备读取内存");

    // Phase 3: 读取内存
    // 参考 Python 的 ReadMemValue 调用模式
    if let Some(func) = dll.read_mem_value {
        // 分配读取缓冲区
        let mut buffer = vec![0u8; TEST_READ_BUFFER_SIZE as usize];

        // 哨兵值填充（参考 Python 的哨兵值检测机制）
        for byte in buffer.iter_mut() {
            *byte = MEM_READ_SENTINEL;
        }

        // 执行内存读取
        let bytes_read = unsafe { func(buffer.as_mut_ptr(), TEST_READ_BUFFER_SIZE) };
        println!("Phase 3: ReadMemValue 返回: {} 字节", bytes_read);

        // 验证读取结果
        if bytes_read >= 0 {
            let actual_len = bytes_read as usize;
            // 安全截取：取实际读取长度和缓冲区长度的较小值
            let data = &buffer[..actual_len.min(buffer.len())];
            println!("  读取到 {} 字节有效数据", data.len());

            // 检查是否有非哨兵值（验证数据确实被读取）
            let has_real_data = data.iter().any(|&b| b != MEM_READ_SENTINEL);
            if has_real_data {
                println!("  检测到有效数据（非哨兵值）");
            } else {
                println!("  所有字节为哨兵值 0xFF，可能读取失败或内存确实全为 0xFF");
            }

            // 打印前 N 字节用于调试（N 由 MEM_PREVIEW_LENGTH 常量控制）
            let preview_len = MEM_PREVIEW_LENGTH.min(data.len());
            println!("  前 {} 字节: {:02X?}", preview_len, &data[..preview_len]);
        } else {
            // 读取返回负数错误码
            println!("  ReadMemValue 返回错误码: {}", bytes_read);
        }
    }

    // Phase 4: 恢复 MCU 运行
    // dll 为 &'static FtGeneralDll，满足线程 'static 约束
    let dll_for_resume = dll;
    let resume_handle = std::thread::Builder::new()
        .name("mcu-read-worker-2".to_string())
        .spawn(move || {
            if let Some(func) = dll_for_resume.free_run {
                println!("  [恢复] FreeRun 开始...");
                unsafe { func() };
                println!("  [恢复] FreeRun 完成");
            }
        })
        .expect("创建恢复 worker 线程失败");

    // 等待 MCU 恢复运行
    std::thread::sleep(std::time::Duration::from_millis(MCU_RESUME_WAIT_MS));
    window::pump_messages();
    println!("Phase 4: MCU 已恢复运行");

    // Phase 5: 最终停止（清理 MCU 运行状态）
    if let Some(func) = dll.break_run {
        unsafe { func() };
    }
    let _ = resume_handle.join();
    window::pump_messages();
    println!("Phase 5: MCU 最终停止");

    // 清理资源
    window::destroy_hidden_window(hwnd);
    println!("MCU 内存读取测试通过");
}

//
//       1. Worker 线程生命周期管理（启动、中断、join）
//       2. 回调函数的线程安全性（并发触发、计数准确性）
//       3. IPC 请求序列与 Python fice_session.py 流程的一致性
//
// 这些测试不需要硬件设备，不需要 DLL 文件，可随时运行
//

/// Worker 线程测试的安全阀迭代上限
const WORKER_TEST_MAX_ITERATIONS: usize = 2000;

/// Worker 线程测试的单次迭代休眠时间（毫秒）
const WORKER_TEST_ITERATION_SLEEP_MS: u64 = 1;

/// Worker 线程中断等待时间（毫秒）
const WORKER_TEST_BREAK_DELAY_MS: u64 = 10;

/// Worker 线程循环测试的轮数
const WORKER_TEST_CYCLE_COUNT: usize = 3;

/// Worker 线程循环测试中每轮的等待时间（毫秒）
const WORKER_TEST_CYCLE_SLEEP_MS: u64 = 5;

/// 回调线程安全测试的并发线程数
const CALLBACK_TEST_THREAD_COUNT: usize = 8;

/// 回调线程安全测试中每线程的回调次数
const CALLBACK_TEST_PER_THREAD_COUNT: usize = 100;

/// 回调类型签名测试的线程数
const CALLBACK_TYPE_TEST_THREAD_COUNT: usize = 4;

/// 测试 worker 线程生命周期管理（不需要硬件设备）
///
///       验证以下场景：
///       1. Worker 线程启动后能被主线程 join
///       2. AtomicBool 中断信号能正确从主线程传递到 worker 线程
///       3. BreakRun 信号能中断长时间运行的 worker
///       4. 连续多次 FreeRun/BreakRun 循环的稳定性
///
/// 模拟方式：
///       使用 AtomicBool 替代 DLL 的 FreeRun 阻塞状态，
///       worker 线程在循环中检查 AtomicBool，主线程设置标志模拟 BreakRun
///
#[test]
fn test_mcu_worker_thread_lifecycle() {
    // --- 验证点 1：Worker 线程启动和正常完成 ---
    {
        // running 标志：模拟 worker 线程的运行状态
        // 使用 Arc 共享所有权，满足 'static 生命周期要求
        let running = Arc::new(AtomicBool::new(true));
        // completed 标志：记录 worker 线程是否执行完毕
        let completed = Arc::new(AtomicBool::new(false));

        // 克隆 Arc 引用传入 worker 线程（满足 'static 要求）
        let running_clone = Arc::clone(&running);
        let completed_clone = Arc::clone(&completed);

        // 启动 worker 线程，模拟 FreeRun 阻塞调用
        let handle = std::thread::Builder::new()
            .name("test-worker-normal".to_string())
            .spawn(move || {
                // 模拟 FreeRun 的阻塞循环
                let mut iterations = 0usize;
                while running_clone.load(Ordering::Acquire) {
                    iterations += 1;
                    // 模拟短时间工作负载
                    std::thread::sleep(std::time::Duration::from_millis(
                        WORKER_TEST_ITERATION_SLEEP_MS,
                    ));
                    // 安全阀：防止无限循环
                    if iterations > WORKER_TEST_MAX_ITERATIONS {
                        break;
                    }
                }
                // 标记 worker 已完成
                completed_clone.store(true, Ordering::Release);
            })
            .expect("创建 worker 线程应成功");

        // 模拟短时间后 BreakRun 中断
        std::thread::sleep(std::time::Duration::from_millis(WORKER_TEST_BREAK_DELAY_MS));
        running.store(false, Ordering::Release);

        // 等待 worker 线程完成（模拟 join 操作）
        handle.join().expect("worker 线程 join 应成功");

        assert!(
            completed.load(Ordering::Acquire),
            "worker 线程应标记为已完成"
        );
    }

    // --- 验证点 2：BreakRun 中断长时间运行的 worker ---
    {
        // freerun_active 标志：模拟 FreeRun 是否正在阻塞
        let freerun_active = Arc::new(AtomicBool::new(true));
        // break_triggered 标志：记录 BreakRun 是否已被触发
        let break_triggered = Arc::new(AtomicBool::new(false));
        // worker_exited 标志：记录 worker 线程是否已退出
        let worker_exited = Arc::new(AtomicBool::new(false));

        // 克隆 Arc 引用传入 worker 线程
        let freerun_active_clone = Arc::clone(&freerun_active);
        let worker_exited_clone = Arc::clone(&worker_exited);

        // 启动 worker 线程，模拟 FreeRun 的长时间阻塞
        let worker_handle = std::thread::Builder::new()
            .name("test-worker-freerun".to_string())
            .spawn(move || {
                // 模拟 FreeRun 阻塞：持续运行直到被中断
                let mut loop_count = 0usize;
                while freerun_active_clone.load(Ordering::Acquire) {
                    loop_count += 1;
                    std::thread::sleep(std::time::Duration::from_millis(
                        WORKER_TEST_ITERATION_SLEEP_MS,
                    ));
                    // 安全阀：防止中断信号失败导致无限循环
                    if loop_count > WORKER_TEST_MAX_ITERATIONS {
                        break;
                    }
                }
                worker_exited_clone.store(true, Ordering::Release);
            })
            .expect("创建 FreeRun worker 线程应成功");

        // 等待 worker 线程进入运行状态
        std::thread::sleep(std::time::Duration::from_millis(
            WORKER_TEST_BREAK_DELAY_MS / 2,
        ));

        // 模拟 BreakRun：设置中断标志
        break_triggered.store(true, Ordering::Release);
        freerun_active.store(false, Ordering::Release);

        // 等待 worker 线程响应中断并退出
        worker_handle.join().expect("FreeRun worker join 应成功");

        assert!(
            break_triggered.load(Ordering::Acquire),
            "BreakRun 应已被触发"
        );
        assert!(
            worker_exited.load(Ordering::Acquire),
            "FreeRun worker 应已退出"
        );
    }

    // --- 验证点 3：连续的 FreeRun -> BreakRun 循环 ---
    {
        for cycle in 0..WORKER_TEST_CYCLE_COUNT {
            // 使用 Arc 共享，主线程和 worker 线程各自持有一份
            let active = Arc::new(AtomicBool::new(true));
            let done = Arc::new(AtomicBool::new(false));

            let active_clone = Arc::clone(&active);
            let done_clone = Arc::clone(&done);

            let h = std::thread::Builder::new()
                .name(format!("test-worker-cycle-{}", cycle))
                .spawn(move || {
                    let mut n = 0usize;
                    while active_clone.load(Ordering::Acquire) {
                        n += 1;
                        std::thread::sleep(std::time::Duration::from_millis(
                            WORKER_TEST_ITERATION_SLEEP_MS,
                        ));
                        if n > WORKER_TEST_MAX_ITERATIONS {
                            break;
                        }
                    }
                    done_clone.store(true, Ordering::Release);
                })
                .expect("创建循环测试 worker 线程应成功");

            // 每轮短暂等待后中断
            std::thread::sleep(std::time::Duration::from_millis(WORKER_TEST_CYCLE_SLEEP_MS));
            active.store(false, Ordering::Release);
            h.join()
                .expect(format!("第 {} 轮 worker join 应成功", cycle).as_str());

            assert!(
                done.load(Ordering::Acquire),
                "第 {} 轮 worker 应已完成",
                cycle
            );
        }
    }
}

/// 测试回调函数的线程安全性（不需要硬件设备）
///
///       1. 多线程并发触发回调时 AtomicUsize 计数器准确性
///       2. DllCallbackFn 类型签名在多线程中的行为正确性
///       3. CALLBACK_RETURN_VALUE_PROCESSED 返回值一致性
///
/// 模拟方式：
///       使用 AtomicUsize 计数器模拟回调调用，多线程并发递增，
///       验证最终计数与预期一致。
///
#[test]
fn test_callback_thread_safety() {
    // --- 验证点 1：多线程并发回调计数准确性 ---
    // 使用 Arc 包装以满足线程 'static 生命周期要求
    {
        // 回调调用计数器（Arc 包装以跨线程共享）
        let callback_count = Arc::new(AtomicUsize::new(0));
        // 预期总回调次数
        let expected_total = CALLBACK_TEST_THREAD_COUNT * CALLBACK_TEST_PER_THREAD_COUNT;

        // 使用 Arc<Barrier> 确保所有线程同时开始（满足 'static 要求）
        let barrier = Arc::new(std::sync::Barrier::new(CALLBACK_TEST_THREAD_COUNT));
        // 收集线程句柄
        let mut handles = Vec::with_capacity(CALLBACK_TEST_THREAD_COUNT);

        for thread_idx in 0..CALLBACK_TEST_THREAD_COUNT {
            // Arc::clone 产生新的所有权，满足 'static 生命周期要求
            let counter = Arc::clone(&callback_count);
            let barrier_ref = Arc::clone(&barrier);

            let handle = std::thread::Builder::new()
                .name(format!("callback-thread-{}", thread_idx))
                .spawn(move || {
                    // 等待所有线程就绪后同时开始
                    barrier_ref.wait();

                    // 模拟多次回调调用
                    for _call_idx in 0..CALLBACK_TEST_PER_THREAD_COUNT {
                        // 原子递增计数器，对应 dll_callback 中的操作
                        counter.fetch_add(1, Ordering::Relaxed);
                    }

                    // 验证回调返回值：模拟 CALLBACK_RETURN_VALUE_PROCESSED
                    let callback_return_value: i32 = CALLBACK_RETURN_VALUE_PROCESSED;
                    callback_return_value
                })
                .expect("创建回调测试线程应成功");

            handles.push(handle);
        }

        // 等待所有线程完成并收集返回值
        let mut all_return_values = Vec::with_capacity(CALLBACK_TEST_THREAD_COUNT);
        for handle in handles {
            let ret = handle.join().expect("回调线程 join 应成功");
            all_return_values.push(ret);
        }

        // 验证所有回调计数正确
        let final_count = callback_count.load(Ordering::Acquire);
        assert_eq!(
            final_count, expected_total,
            "回调计数应为 {}，实际为 {}",
            expected_total, final_count
        );

        // 验证所有返回值都是 CALLBACK_RETURN_VALUE_PROCESSED
        for (idx, ret) in all_return_values.iter().enumerate() {
            assert_eq!(
                *ret, CALLBACK_RETURN_VALUE_PROCESSED,
                "线程 {} 的回调返回值应为 CALLBACK_RETURN_VALUE_PROCESSED ({})，实际为 {}",
                idx, CALLBACK_RETURN_VALUE_PROCESSED, ret
            );
        }
    }

    // --- 验证点 2：DllCallbackFn 类型签名正确性 ---
    {
        // 定义符合 DllCallbackFn 签名的回调函数
        extern "C" fn mock_dll_callback(msg_id: i32, w_param: i32, l_param: i32) -> i32 {
            // 验证参数传递正确性
            // msg_id: DLL 回调消息 ID
            // w_param: WPARAM 参数
            // l_param: LPARAM 参数
            let _ = (msg_id, w_param, l_param);
            CALLBACK_RETURN_VALUE_PROCESSED
        }

        // 多线程并发调用 mock 回调（Arc 包装以跨线程共享）
        let call_count = Arc::new(AtomicUsize::new(0));
        let mut handles = Vec::with_capacity(CALLBACK_TYPE_TEST_THREAD_COUNT);

        for i in 0..CALLBACK_TYPE_TEST_THREAD_COUNT {
            // Arc::clone 产生新的所有权，满足 'static 生命周期要求
            let counter = Arc::clone(&call_count);
            let handle = std::thread::spawn(move || {
                // 每个线程调用不同参数组合的回调
                let msg_ids = [0i32, 1, 100, -1];
                let w_params = [0i32, 256, 512, 1024];
                let l_params = [0i32, 10, 20, 30];

                // 通过函数指针调用，验证 DllCallbackFn 类型转换正确
                // 调用 extern "C" fn 不需要 unsafe 块
                let callback: extern "C" fn(i32, i32, i32) -> i32 = mock_dll_callback;
                let result = callback(
                    msg_ids[i % msg_ids.len()],
                    w_params[i % w_params.len()],
                    l_params[i % l_params.len()],
                );

                counter.fetch_add(1, Ordering::Relaxed);
                result
            });
            handles.push(handle);
        }

        // 验证所有调用均返回 CALLBACK_RETURN_VALUE_PROCESSED
        for (idx, handle) in handles.into_iter().enumerate() {
            let result = handle.join().expect("回调线程 join 应成功");
            assert_eq!(
                result, CALLBACK_RETURN_VALUE_PROCESSED,
                "回调线程 {} 返回值应为 {}，实际为 {}",
                idx, CALLBACK_RETURN_VALUE_PROCESSED, result
            );
        }

        assert_eq!(
            call_count.load(Ordering::Acquire),
            CALLBACK_TYPE_TEST_THREAD_COUNT,
            "应完成 {} 次回调调用",
            CALLBACK_TYPE_TEST_THREAD_COUNT
        );
    }
}

/// 测试用 IPC 请求序列：MCU 启动步骤数
const IPC_MCU_START_STEPS: usize = 3;

/// 测试用 IPC 请求序列：MCU 停止步骤数
const IPC_MCU_STOP_STEPS: usize = 2;

/// 测试用 IPC 请求序列：MCU 复位步骤数
const IPC_MCU_RESET_STEPS: usize = 4;

/// 测试用 IPC 请求序列：完整初始化步骤数
const IPC_FULL_INIT_STEPS: usize = 6;

/// 测试用 IPC 请求序列：MCU 启动序列的 type 标签
const IPC_MCU_START_TYPE_TAGS: [&str; IPC_MCU_START_STEPS] =
    ["setBreakPoint", "enterDebugMode", "freeRun"];

/// 测试用 IPC 请求序列：MCU 停止序列的 type 标签
const IPC_MCU_STOP_TYPE_TAGS: [&str; IPC_MCU_STOP_STEPS] = ["breakRun", "readMemValue"];

/// 测试用 IPC 请求序列：MCU 复位序列的 type 标签
const IPC_MCU_RESET_TYPE_TAGS: [&str; IPC_MCU_RESET_STEPS] =
    ["breakRun", "setBreakPoint", "enterDebugMode", "freeRun"];

/// 测试用 IPC 请求序列：完整初始化的 type 标签
const IPC_FULL_INIT_TYPE_TAGS: [&str; IPC_FULL_INIT_STEPS] = [
    "initDll",
    "setControllerWindowHandle",
    "setCallBackFun",
    "setBreakPoint",
    "enterDebugMode",
    "freeRun",
];

/// 测试 IPC 请求序列与 Python fice_session.py 的流程一致性（不需要硬件设备）
///
///       包括：
///       1. MCU 启动序列：SetBreakPoint -> EnterDebugMode -> FreeRun
///       2. MCU 停止序列：BreakRun -> ReadMemValue（可选）
///       3. MCU 复位序列：BreakRun -> SetBreakPoint -> EnterDebugMode -> FreeRun
///       4. 完整初始化序列：InitDll -> ... -> FreeRun
///       5. 每个序列步骤的 JSON 序列化字段正确性
///
#[test]
fn test_ipc_request_matches_dll_flow() {
    // --- 验证点 1：MCU 启动 IPC 序列（SetBreakPoint -> EnterDebugMode -> FreeRun） ---
    {
        // 测试用断点地址，对应 Python 中的 set_break_point 调用
        let test_breakpoint_address: u32 = TEST_BREAKPOINT_ADDR;
        // 测试用调试模式参数
        let test_debug_mode: i32 = 0;

        // 构造 MCU 启动序列的 IPC 请求
        let mcu_start_sequence: Vec<IpcRequest> = vec![
            // 步骤 1：设置断点
            IpcRequest::SetBreakPoint {
                address: test_breakpoint_address,
            },
            // 步骤 2：进入调试模式
            IpcRequest::EnterDebugMode {
                mode: test_debug_mode,
            },
            // 步骤 3：自由运行（启动 MCU）
            IpcRequest::FreeRun {
                main_addr: DEFAULT_BREAKPOINT_ADDR,
            },
        ];

        // 验证序列长度正确
        assert_eq!(
            mcu_start_sequence.len(),
            IPC_MCU_START_STEPS,
            "MCU 启动序列应包含 {} 个步骤",
            IPC_MCU_START_STEPS
        );

        // 验证每个步骤的序列化格式
        for (step_idx, request) in mcu_start_sequence.iter().enumerate() {
            let msg = IpcMessage::new(request.clone());
            let json = msg
                .to_json()
                .unwrap_or_else(|e| panic!("MCU 启动序列第 {} 步序列化失败: {}", step_idx, e));

            // 解析 JSON 验证结构
            let value: serde_json::Value = serde_json::from_str(&json)
                .unwrap_or_else(|e| panic!("第 {} 步 JSON 解析失败: {}", step_idx, e));

            // 验证顶层字段
            assert!(value["id"].is_string(), "第 {} 步应包含 id 字段", step_idx);
            assert!(
                value["timestamp"].is_number(),
                "第 {} 步应包含 timestamp 字段",
                step_idx
            );
            assert!(
                value["payload"].is_object(),
                "第 {} 步应包含 payload 对象",
                step_idx
            );

            // 验证 payload 中的 type 标签与常量一致
            let payload_type = value["payload"]["type"]
                .as_str()
                .unwrap_or_else(|| panic!("第 {} 步 payload.type 应为字符串", step_idx));
            assert_eq!(
                payload_type, IPC_MCU_START_TYPE_TAGS[step_idx],
                "第 {} 步 type 应为 {}，实际为 {}",
                step_idx, IPC_MCU_START_TYPE_TAGS[step_idx], payload_type
            );

            // 验证反序列化对称性
            let restored = IpcMessage::from_json(&json)
                .unwrap_or_else(|e| panic!("第 {} 步反序列化失败: {}", step_idx, e));
            assert_eq!(msg.id, restored.id, "第 {} 步消息 ID 应一致", step_idx);
        }

        // 验证 SetBreakPoint 的 address 字段使用 camelCase
        let bp_msg = IpcMessage::new(IpcRequest::SetBreakPoint {
            address: test_breakpoint_address,
        });
        let bp_json = bp_msg.to_json().expect("SetBreakPoint 序列化应成功");
        let bp_value: serde_json::Value =
            serde_json::from_str(&bp_json).expect("SetBreakPoint JSON 解析应成功");
        assert_eq!(
            bp_value["payload"]["address"].as_u64(),
            Some(test_breakpoint_address as u64),
            "SetBreakPoint address 字段值应正确"
        );
    }

    // --- 验证点 2：MCU 停止 IPC 序列（BreakRun -> ReadMemValue） ---
    {
        // 测试用内存读取长度
        let test_read_length: u32 = TEST_READ_BUFFER_SIZE;

        // 构造 MCU 停止序列的 IPC 请求
        let mcu_stop_sequence: Vec<IpcRequest> = vec![
            // 步骤 1：停止运行（中断 MCU）
            IpcRequest::BreakRun,
            // 步骤 2：读取内存值（获取停止后的 MCU 状态）
            IpcRequest::ReadMemValue {
                length: test_read_length,
            },
        ];

        // 验证序列长度
        assert_eq!(
            mcu_stop_sequence.len(),
            IPC_MCU_STOP_STEPS,
            "MCU 停止序列应包含 {} 个步骤",
            IPC_MCU_STOP_STEPS
        );

        // 验证每步 type 标签与常量一致
        for (step_idx, request) in mcu_stop_sequence.iter().enumerate() {
            let msg = IpcMessage::new(request.clone());
            let json = msg
                .to_json()
                .unwrap_or_else(|e| panic!("MCU 停止序列第 {} 步序列化失败: {}", step_idx, e));
            let value: serde_json::Value = serde_json::from_str(&json)
                .unwrap_or_else(|e| panic!("第 {} 步 JSON 解析失败: {}", step_idx, e));
            let actual_type = value["payload"]["type"]
                .as_str()
                .unwrap_or_else(|| panic!("第 {} 步 payload.type 应为字符串", step_idx));
            assert_eq!(
                actual_type, IPC_MCU_STOP_TYPE_TAGS[step_idx],
                "MCU 停止第 {} 步 type 应为 {}，实际为 {}",
                step_idx, IPC_MCU_STOP_TYPE_TAGS[step_idx], actual_type
            );
        }

        // 验证 ReadMemValue 的 length 字段
        let read_msg = IpcMessage::new(IpcRequest::ReadMemValue {
            length: test_read_length,
        });
        let read_json = read_msg.to_json().expect("ReadMemValue 序列化应成功");
        let read_value: serde_json::Value =
            serde_json::from_str(&read_json).expect("ReadMemValue JSON 解析应成功");
        assert_eq!(
            read_value["payload"]["length"].as_u64(),
            Some(test_read_length as u64),
            "ReadMemValue length 字段值应正确"
        );
    }

    // --- 验证点 3：MCU 复位 IPC 序列（BreakRun -> SetBreakPoint -> EnterDebugMode -> FreeRun） ---
    {
        // 测试用调试模式参数（复位后重新进入调试模式）
        let test_reset_debug_mode: i32 = 0;
        // 测试用断点地址（复位后重新设置断点）
        let test_reset_breakpoint: u32 = TEST_BREAKPOINT_ADDR;

        // 构造 MCU 复位序列的 IPC 请求
        let mcu_reset_sequence: Vec<IpcRequest> = vec![
            // 步骤 1：停止当前运行
            IpcRequest::BreakRun,
            // 步骤 2：重新设置断点
            IpcRequest::SetBreakPoint {
                address: test_reset_breakpoint,
            },
            // 步骤 3：重新进入调试模式
            IpcRequest::EnterDebugMode {
                mode: test_reset_debug_mode,
            },
            // 步骤 4：自由运行（重新启动 MCU）
            IpcRequest::FreeRun {
                main_addr: DEFAULT_BREAKPOINT_ADDR,
            },
        ];

        // 验证序列长度
        assert_eq!(
            mcu_reset_sequence.len(),
            IPC_MCU_RESET_STEPS,
            "MCU 复位序列应包含 {} 个步骤",
            IPC_MCU_RESET_STEPS
        );

        // 验证完整序列的 roundtrip 序列化/反序列化
        for (step_idx, request) in mcu_reset_sequence.iter().enumerate() {
            let msg = IpcMessage::new(request.clone());
            let json = msg
                .to_json()
                .unwrap_or_else(|e| panic!("复位序列第 {} 步序列化失败: {}", step_idx, e));

            // 验证 type 标签与常量一致
            let value: serde_json::Value = serde_json::from_str(&json)
                .unwrap_or_else(|e| panic!("复位序列第 {} 步 JSON 解析失败: {}", step_idx, e));
            let actual_type = value["payload"]["type"]
                .as_str()
                .unwrap_or_else(|| panic!("复位序列第 {} 步 payload.type 应为字符串", step_idx));
            assert_eq!(
                actual_type, IPC_MCU_RESET_TYPE_TAGS[step_idx],
                "复位序列第 {} 步 type 应为 {}，实际为 {}",
                step_idx, IPC_MCU_RESET_TYPE_TAGS[step_idx], actual_type
            );

            // 验证反序列化对称性
            let restored = IpcMessage::from_json(&json)
                .unwrap_or_else(|e| panic!("复位序列第 {} 步反序列化失败: {}", step_idx, e));
            assert_eq!(
                msg.id, restored.id,
                "复位序列第 {} 步消息 ID 应一致",
                step_idx
            );
        }
    }

    // --- 验证点 4：MCU 完整初始化 IPC 序列（InitDll -> SetControllerWindowHandle -> SetCallBackFun -> SetBreakPoint -> EnterDebugMode -> FreeRun） ---
    {
        // 测试用 DLL 路径
        let test_dll_path = format!("C:\\AppData\\{}", dll_bridge::DLL_FILE_NAME);
        // 测试用窗口句柄
        let test_window_handle: u64 = 0;
        // 测试用断点地址
        let test_init_breakpoint: u32 = TEST_BREAKPOINT_ADDR;
        // 测试用调试模式
        let test_init_debug_mode: i32 = 0;

        // 构造完整初始化到运行的 IPC 序列
        let full_init_sequence: Vec<IpcRequest> = vec![
            // 步骤 1：加载 DLL
            IpcRequest::InitDll {
                dll_path: test_dll_path.clone(),
            },
            // 步骤 2：设置控制器窗口句柄
            IpcRequest::SetControllerWindowHandle {
                handle: test_window_handle,
            },
            // 步骤 3：注册回调函数
            IpcRequest::SetCallBackFun,
            // 步骤 4：设置断点
            IpcRequest::SetBreakPoint {
                address: test_init_breakpoint,
            },
            // 步骤 5：进入调试模式
            IpcRequest::EnterDebugMode {
                mode: test_init_debug_mode,
            },
            // 步骤 6：自由运行（启动 MCU）
            IpcRequest::FreeRun {
                main_addr: DEFAULT_BREAKPOINT_ADDR,
            },
        ];

        // 验证完整初始化序列长度
        assert_eq!(
            full_init_sequence.len(),
            IPC_FULL_INIT_STEPS,
            "完整初始化序列应包含 {} 个步骤",
            IPC_FULL_INIT_STEPS
        );

        // 验证每步的 type 标签按预期排列
        for (step_idx, request) in full_init_sequence.iter().enumerate() {
            let msg = IpcMessage::new(request.clone());
            let json = msg
                .to_json()
                .unwrap_or_else(|e| panic!("初始化序列第 {} 步序列化失败: {}", step_idx, e));
            let value: serde_json::Value = serde_json::from_str(&json)
                .unwrap_or_else(|e| panic!("初始化序列第 {} 步 JSON 解析失败: {}", step_idx, e));

            let actual_type = value["payload"]["type"]
                .as_str()
                .unwrap_or_else(|| panic!("第 {} 步 payload.type 应为字符串", step_idx));

            assert_eq!(
                actual_type, IPC_FULL_INIT_TYPE_TAGS[step_idx],
                "初始化序列第 {} 步 type 应为 {}，实际为 {}",
                step_idx, IPC_FULL_INIT_TYPE_TAGS[step_idx], actual_type
            );
        }

        // 验证 InitDll 的 dllPath 字段使用 camelCase 命名
        let init_msg = IpcMessage::new(IpcRequest::InitDll {
            dll_path: test_dll_path.clone(),
        });
        let init_json = init_msg.to_json().expect("InitDll 序列化应成功");
        let init_value: serde_json::Value =
            serde_json::from_str(&init_json).expect("InitDll JSON 解析应成功");
        assert_eq!(
            init_value["payload"]["dllPath"].as_str(),
            Some(test_dll_path.as_str()),
            "InitDll dllPath 字段应使用 camelCase 命名"
        );
    }
}
