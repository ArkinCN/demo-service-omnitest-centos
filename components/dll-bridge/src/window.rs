//! DLL Bridge 隐藏窗口模块
//!
//! 为 DLL Bridge 子进程提供真实 HWND，并在主线程运行 Windows 消息泵，
//! 以处理 DLL 通过 PostMessage 发出的回调。窗口创建模式参考 Python fice_session.py。

use std::mem;
use std::ptr;

use windows_sys::Win32::Foundation::*;
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::UI::WindowsAndMessaging::*;

use crate::types::*;

/// 隐藏窗口句柄（全局存储，供 main.rs 读取传递给 DLL）
static mut HIDDEN_WINDOW_HWND: HWND = ptr::null_mut();

/// 窗口过程（WndProc）
///
/// 处理发送到隐藏窗口的 Windows 消息。DLL 通过 PostMessage 发送的消息会到达此过程。
/// 当前实现为默认处理（DefWindowProcW），后续可扩展处理特定 DLL 消息。
unsafe extern "system" fn wnd_proc(
    hwnd: HWND,
    msg: u32,
    w_param: WPARAM,
    l_param: LPARAM,
) -> LRESULT {
    // WM_USER 范围常量（Windows 定义）
    const WM_USER: u32 = 0x0400;

    match msg {
        WM_DESTROY => {
            // 窗口销毁时发送 WM_QUIT 以退出消息循环
            PostQuitMessage(0);
            0
        }
        // DLL 通过 PostMessage/SendMessage 发送 WM_USER 范围的自定义消息
        // 返回 1 表示"已处理"（与 Python fice_session.py _bridge_wnd_proc 一致）
        // 原因：DLL 可能检查 SendMessage 返回值来判断命令（如 BreakRun）是否被窗口接收处理，
        //       DefWindowProcW 对这些消息返回 0（未处理），导致 DLL 认为命令失败
        m if m >= WM_USER => 1,
        _ => {
            // 标准系统消息交给默认处理
            DefWindowProcW(hwnd, msg, w_param, l_param)
        }
    }
}

/// 注册窗口类并创建隐藏窗口
///
/// 创建一个不可见的消息窗口，用于接收 DLL 的 PostMessage 回调。
/// 参考 Python fice_session.py 中的 CreateWindowExA 调用。
///
/// 返回值：
/// - Ok(HWND): 窗口创建成功，返回窗口句柄
/// - Err(String): 窗口类注册或窗口创建失败
pub fn create_hidden_window() -> Result<HWND, String> {
    unsafe {
        // Windows API 使用 UTF-16 编码的窗口类名和标题
        let class_name_wide: Vec<u16> = WINDOW_CLASS_NAME
            .encode_utf16()
            .chain(std::iter::once(0))
            .collect();
        let window_title_wide: Vec<u16> = WINDOW_TITLE
            .encode_utf16()
            .chain(std::iter::once(0))
            .collect();

        // RegisterClassW 和 CreateWindowExW 都需要模块实例句柄
        let h_instance = GetModuleHandleW(ptr::null());

        // WNDCLASSW 不实现 Default，需手动设置窗口过程、实例句柄等必要字段
        let wnd_class = WNDCLASSW {
            lpfnWndProc: Some(wnd_proc),
            hInstance: h_instance,
            lpszClassName: class_name_wide.as_ptr(),
            style: 0,
            cbClsExtra: 0,
            cbWndExtra: 0,
            hIcon: ptr::null_mut(),
            hCursor: ptr::null_mut(),
            hbrBackground: ptr::null_mut(),
            lpszMenuName: ptr::null(),
        };

        // RegisterClassW 返回 0 表示失败，类已注册不算错误（可能重复调用）
        if RegisterClassW(&wnd_class) == 0 {
            let err = GetLastError();
            if err != ERROR_CLASS_ALREADY_EXISTS as u32 {
                return Err(format!("RegisterClassW 失败，错误码: {}", err));
            }
        }

        // 创建一个不可见的消息窗口，仅用于接收 DLL PostMessage 回调
        // 对应 Python 中 CreateWindowExA(0, "FiceSessionCtrl", "FiceSession", ...)
        let hwnd = CreateWindowExW(
            0,                          // dwExStyle: 无扩展样式
            class_name_wide.as_ptr(),   // lpClassName: 窗口类名
            window_title_wide.as_ptr(), // lpWindowName: 窗口标题
            0,                          // dwStyle: 无样式（不可见）
            0,
            0,
            0,
            0,               // x, y, width, height: 全零
            ptr::null_mut(), // hWndParent: 无父窗口
            ptr::null_mut(), // hMenu: 无菜单
            h_instance,      // hInstance: 当前模块句柄
            ptr::null_mut(), // lpParam: 无附加参数
        );

        // HWND 为 null 表示创建失败，需要向调用方报告错误
        if hwnd.is_null() {
            return Err(format!("CreateWindowExW 失败，错误码: {}", GetLastError()));
        }

        // 保存到全局变量，供其他模块通过 get_hidden_window_hwnd() 获取窗口句柄
        HIDDEN_WINDOW_HWND = hwnd;

        log::info!("隐藏窗口创建成功，HWND: {:?}", hwnd);
        Ok(hwnd)
    }
}

/// 处理所有待处理的 Windows 消息（非阻塞）
///
/// 使用 PeekMessageW 而非 GetMessageW 实现非阻塞，
/// 使主线程能在消息泵间隙处理 IPC 通道消息。
///
/// 返回值：
/// - true: 继续运行（未收到 WM_QUIT）
/// - false: 收到 WM_QUIT，应退出主循环
pub fn pump_messages() -> bool {
    unsafe {
        // MSG 不实现 Default trait，通过 zeroed 获得零值初始化
        let mut msg: MSG = mem::zeroed();

        // 使用 PeekMessageW 非阻塞检查待处理消息
        while PeekMessageW(&mut msg, ptr::null_mut(), 0, 0, PM_REMOVE) != 0 {
            // WM_QUIT 表示应退出消息循环
            if msg.message == WM_QUIT {
                return false;
            }
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        true
    }
}

/// 销毁隐藏窗口
///
/// 在子进程退出前释放窗口资源。销毁窗口会触发 WM_DESTROY 消息，进而发送 WM_QUIT。
pub fn destroy_hidden_window(hwnd: HWND) {
    unsafe {
        // 避免对空句柄调用 DestroyWindow
        if !hwnd.is_null() {
            DestroyWindow(hwnd);
            HIDDEN_WINDOW_HWND = ptr::null_mut();
        }
    }
}

/// 获取当前隐藏窗口句柄
pub fn get_hidden_window_hwnd() -> HWND {
    // 安全说明：读取全局静态 HWND，仅在 create_hidden_window/destroy_hidden_window 中修改
    unsafe { HIDDEN_WINDOW_HWND }
}
