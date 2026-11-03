//! FTGeneralUtils.dll 类型定义模块
//!
//! DLL 导出函数名常量、回调函数类型。禁止硬编码，所有常量和类型
//! 统一存放在此文件中供 ffi.rs 引用。

/// FTGeneralUtils.dll 默认文件名
pub const DLL_FILE_NAME: &str = "FTGeneralUtils.dll";

/// GeneralMakeFiles 导出函数名
pub const FN_GENERAL_MAKE_FILES: &str = "GeneralMakeFiles";

/// DownloadCode 导出函数名
pub const FN_DOWNLOAD_CODE: &str = "DownloadCode";

/// SetControllerWindowHandle 导出函数名
pub const FN_SET_CONTROLLER_WINDOW_HANDLE: &str = "SetControllerWindowHandle";

/// SetCallBackFun 导出函数名
pub const FN_SET_CALLBACK_FUN: &str = "SetCallBackFun";

/// SetBreakPoint 导出函数名
pub const FN_SET_BREAK_POINT: &str = "SetBreakPoint";

/// FreeRun 导出函数名
pub const FN_FREE_RUN: &str = "FreeRun";

/// BreakRun 导出函数名
pub const FN_BREAK_RUN: &str = "BreakRun";

/// ReadMemValue 导出函数名
pub const FN_READ_MEM_VALUE: &str = "ReadMemValue";

/// EnterDebugMode 导出函数名
pub const FN_ENTER_DEBUG_MODE: &str = "EnterDebugMode";

/// DownloadFirmware 导出函数名
pub const FN_DOWNLOAD_FIRMWARE: &str = "DownloadFirmware";

/// SetKeilIncludePath 导出函数名
pub const FN_SET_KEIL_INCLUDE_PATH: &str = "SetKeilIncludePath";

/// SetKeilBuildExterInfo 导出函数名
pub const FN_SET_KEIL_BUILD_EXTER_INFO: &str = "SetKeilBuildExterInfo";

/// GeneralMakeFiles 函数签名
/// 原型：int GeneralMakeFiles(int nType, char* lpOutput)
/// 参数：nType - 编译类型；lpOutput - 输出信息缓冲区
/// 返回值：0 表示成功，非 0 表示错误码
pub type GeneralMakeFilesFn = unsafe extern "C" fn(i32, *const i8) -> i32;

/// DownloadCode 函数签名
/// 原型：int DownloadCode(char* lpChipName, char* lpHexFilePath)
/// 参数：lpChipName - 芯片型号名称（如 "FU6832"）；lpHexFilePath - hex 文件完整路径
pub type DownloadCodeFn = unsafe extern "C" fn(*const i8, *const i8) -> i32;

/// SetControllerWindowHandle 函数签名
/// 原型：int SetControllerWindowHandle(void* hWnd)
/// 参数：hWnd - 窗口句柄指针（对应 Windows HWND）
/// 返回值：0 表示成功，非 0 表示错误码
pub type SetControllerWindowHandleFn = unsafe extern "C" fn(*mut std::ffi::c_void) -> i32;

/// DLL 回调函数类型
/// 原型：int CALLBACK CallbackFunc(int msgType, int wParam, int lParam)
/// 参数：msgType - 消息类型；wParam - 宽参数；lParam - 长参数
/// 返回值：回调处理结果
pub type DllCallbackFn = extern "C" fn(i32, i32, i32) -> i32;

/// SetCallBackFun 函数签名
/// 原型：void SetCallBackFun(void* lpCallback)
/// 参数：lpCallback - 回调函数指针，类型为 DllCallbackFn
pub type SetCallBackFunFn = unsafe extern "C" fn(Option<DllCallbackFn>) -> ();

/// SetBreakPoint 函数签名
/// 原型：void SetBreakPoint(uint32_t addr)
/// 参数：addr - 断点地址
pub type SetBreakPointFn = unsafe extern "C" fn(u32) -> ();

/// FreeRun 函数签名
/// 原型：void FreeRun()
/// 参数：无
pub type FreeRunFn = unsafe extern "C" fn() -> ();

/// BreakRun 函数签名
/// 原型：void BreakRun()
/// 参数：无
pub type BreakRunFn = unsafe extern "C" fn() -> ();

/// ReadMemValue 函数签名
/// 原型：int ReadMemValue(uint8_t* lpBuffer, uint32_t nLen)
/// 参数：lpBuffer - 输出缓冲区指针；nLen - 读取长度
/// 返回值：实际读取的字节数，或错误码（负值）
pub type ReadMemValueFn = unsafe extern "C" fn(*mut u8, u32) -> i32;

/// EnterDebugMode 函数签名
/// 原型：int EnterDebugMode(int nMode)
/// 参数：nMode - 调试模式类型
/// 返回值：0 表示成功，非 0 表示错误码
pub type EnterDebugModeFn = unsafe extern "C" fn(i32) -> i32;

/// DownloadFirmware 函数签名
/// 原型：void DownloadFirmware(void)
/// 参数：无
/// 返回值：无
pub type DownloadFirmwareFn = unsafe extern "C" fn() -> ();

/// SetKeilIncludePath 函数签名
/// 原型：int SetKeilIncludePath(char* lpPath)
/// 参数：lpPath - 头文件包含路径字符串
/// 返回值：0 表示成功，非 0 表示错误码
pub type SetKeilIncludePathFn = unsafe extern "C" fn(*const i8) -> i32;

/// SetKeilBuildExterInfo 函数签名
/// 原型：int SetKeilBuildExterInfo(char* lpInfo)
/// 参数：lpInfo - 外部构建信息字符串
/// 返回值：0 表示成功，非 0 表示错误码
pub type SetKeilBuildExterInfoFn = unsafe extern "C" fn(*const i8) -> i32;

/// 操作成功
pub const ERROR_CODE_SUCCESS: i32 = 0;

/// 通用错误
pub const ERROR_CODE_GENERAL: i32 = -1;

/// DLL 加载失败
pub const ERROR_CODE_DLL_LOAD_FAILED: i32 = -100;

/// DLL 函数调用失败
pub const ERROR_CODE_DLL_CALL_FAILED: i32 = -101;

/// DLL 未初始化
pub const ERROR_CODE_DLL_NOT_INITIALIZED: i32 = -102;

/// 无效参数
pub const ERROR_CODE_INVALID_PARAMS: i32 = -200;

/// 无效地址
pub const ERROR_CODE_INVALID_ADDRESS: i32 = -201;

/// 超时错误
pub const ERROR_CODE_TIMEOUT: i32 = -300;

/// 通信管道断开
pub const ERROR_CODE_PIPE_DISCONNECTED: i32 = -301;

/// JSON 序列化/反序列化失败
pub const ERROR_CODE_JSON_PARSE_FAILED: i32 = -400;

/// 未知请求类型
pub const ERROR_CODE_UNKNOWN_REQUEST: i32 = -500;

/// 子进程未就绪
pub const ERROR_CODE_NOT_READY: i32 = -600;

/// 操作被拒绝（如 DLL 已加载时重复加载）
pub const ERROR_CODE_REJECTED: i32 = -700;

/// GBK 编码转换失败时的错误消息模板
pub const ERROR_MSG_GBK_ENCODE_FAILED: &str = "GBK 编码转换失败，路径可能包含无法转换的字符: ";

/// GBK 编码后的字节包含内部 NUL 字符时的错误消息
pub const ERROR_MSG_GBK_INTERIOR_NUL: &str = "GBK 编码后的字节包含非法 NUL 字符: ";

/// IpcRequest/IpcResponse 的 serde tag 字段名
pub const IPC_REQUEST_TAG: &str = "type";

/// IpcResponse 的 serde tag 字段名（与请求相同）
pub const IPC_RESPONSE_TAG: &str = "type";

/// 单条消息最大长度（字节），防止恶意或异常超大消息
pub const IPC_MAX_MESSAGE_SIZE: usize = 1024 * 1024; // 1 MB

/// 管道读取缓冲区大小
pub const IPC_READ_BUFFER_SIZE: usize = 4096;

/// 默认请求超时时间（毫秒）
pub const IPC_DEFAULT_TIMEOUT_MS: u64 = 30000; // 30 秒

/// 子进程启动超时时间（毫秒）
pub const IPC_PROCESS_STARTUP_TIMEOUT_MS: u64 = 10000; // 10 秒

/// 单行消息的最大长度（字节）
pub const MAX_LINE_LENGTH: usize = 64 * 1024; // 64 KiB

/// DLL 函数通用成功返回值
pub const DLL_RETURN_SUCCESS: i32 = 0;

/// GeneralMakeFiles 的默认编译类型参数
pub const GENERAL_MAKE_FILES_DEFAULT_TYPE: i32 = 0;

/// DLL 回调函数的"已处理"返回值
pub const CALLBACK_RETURN_VALUE_PROCESSED: i32 = 1;

/// ReadMemValue 单次读取的最大字节数
pub const MAX_READ_MEM_LENGTH: usize = 64 * 1024; // 64 KiB

/// 协议版本号
pub const PROTOCOL_VERSION: &str = "1.0.0";

/// 隐藏窗口类名
pub const WINDOW_CLASS_NAME: &str = "FiceSessionCtrl";

/// 隐藏窗口标题
pub const WINDOW_TITLE: &str = "FiceSession";

/// 消息泵超时时间（毫秒）
pub const MESSAGE_PUMP_TIMEOUT_MS: u32 = 10;

/// IPC 通道缓冲区大小
pub const IPC_CHANNEL_CAPACITY: usize = 256;

/// Worker 线程最大等待超时（毫秒）
pub const WORKER_JOIN_TIMEOUT_MS: u64 = 5000;

/// Reset 操作中 EnterDebugMode 的超时阈值（毫秒）
pub const RESET_ENTER_DEBUG_MODE_TIMEOUT_MS: u64 = 15000; // 15 秒

/// Reset 超时后 BreakRun 救援的等待时间（毫秒）
pub const RESET_RESCUE_WAIT_MS: u64 = 3000; // 3 秒

/// 默认断点地址（芯片复位向量）
pub const DEFAULT_BREAKPOINT_ADDR: u32 = 0x08000000;

/// CREATE_NO_WINDOW 标志值
pub const CREATE_NO_WINDOW_FLAG: u32 = 0x08000000;

/// subst 驱动器映射的起始盘符（从 Z 开始倒序分配）
pub const SUBST_DRIVE_START: char = 'Z';

/// subst 驱动器映射的结束盘符
pub const SUBST_DRIVE_END: char = 'G';

/// Bridge 启动等待 Ready 超时（毫秒）
pub const BRIDGE_READY_TIMEOUT_MS: u64 = 30000;

/// IPC 请求等待响应超时（毫秒）
pub const BRIDGE_RESPONSE_TIMEOUT_MS: u64 = 120000;

/// dll-bridge.exe 可执行文件名
pub const BRIDGE_EXE_NAME: &str = "dll-bridge.exe";

/// Cargo 构建目标的相对路径（从 manifest 的祖父目录/target/ 开始）
pub const BRIDGE_BUILD_RELATIVE_PATH: &str = "i686-pc-windows-msvc/debug";

/// IDE 数据目录相对于 %APPDATA% 的路径
pub const IDE_APPDATA_RELATIVE_PATH: &str = r"com.motordebug.app\IDE";

/// Bridge shutdown 等待子进程退出的超时时间（秒）
pub const BRIDGE_SHUTDOWN_TIMEOUT_SECS: u64 = 5;

/// Bridge shutdown 轮询子进程状态的间隔（毫秒）
pub const BRIDGE_SHUTDOWN_POLL_INTERVAL_MS: u64 = 100;

/// stdout reader 线程名称
pub const BRIDGE_STDOUT_READER_THREAD_NAME: &str = "bridge-stdout-reader";

// ============================================================
// CLI 模式相关常量
// ============================================================

/// 嵌入 DLL 的编译时相对路径（从 src/ 目录出发）
pub const EMBEDDED_DLL_RELATIVE_PATH: &str = "../../../resources/unpacked/IDE/FTGeneralUtils.dll";

/// CLI 输出 JSON 中 success 字段名
pub const CLI_JSON_KEY_SUCCESS: &str = "success";

/// CLI 输出 JSON 中 data 字段名
pub const CLI_JSON_KEY_DATA: &str = "data";

/// CLI 输出 JSON 中 message 字段名
pub const CLI_JSON_KEY_MESSAGE: &str = "message";

/// CLI 输出 JSON 中 error_code 字段名
pub const CLI_JSON_KEY_ERROR_CODE: &str = "error_code";

/// CLI 子命令名：编译构建
pub const CLI_CMD_GENERAL_MAKE_FILES: &str = "general-make-files";

/// CLI 子命令名：固件下载
pub const CLI_CMD_DOWNLOAD_CODE: &str = "download-code";

/// CLI 子命令名：自由运行
pub const CLI_CMD_FREE_RUN: &str = "free-run";

/// CLI 子命令名：停止运行
pub const CLI_CMD_BREAK_RUN: &str = "break-run";

/// CLI 子命令名：进入调试模式
pub const CLI_CMD_ENTER_DEBUG: &str = "enter-debug";

/// CLI 子命令名：读取内存
pub const CLI_CMD_READ_MEM: &str = "read-mem";

/// CLI 子命令名：设置断点
pub const CLI_CMD_SET_BREAKPOINT: &str = "set-breakpoint";

/// CLI 子命令名：固件升级
pub const CLI_CMD_DOWNLOAD_FIRMWARE: &str = "download-firmware";

/// CLI ReadMem 默认读取长度（字节）
pub const CLI_DEFAULT_READ_MEM_LENGTH: u32 = 256;

/// DLL temp 目录前缀
pub const DLL_TEMP_DIR_PREFIX: &str = "dll-bridge-";
