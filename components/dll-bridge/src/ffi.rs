//! FTGeneralUtils.dll FFI 封装实现
//!
//! FtGeneralDll 封装 DLL 动态库句柄和导出函数指针，函数指针使用 Option 兼容不同 DLL 版本。
//!
//! 使用示例：
//! ```no_run
//! use dll_bridge::ffi::FtGeneralDll;
//!
//! let dll = FtGeneralDll::load("C:\\path\\to\\FTGeneralUtils.dll")
//!     .expect("DLL 加载失败");
//!
//! if let Some(general_make_files) = dll.general_make_files {
//!     let result = unsafe { general_make_files(0, b"default\0".as_ptr() as *const i8) };
//!     println!("编译结果: {}", result);
//! }
//! ```

use crate::types::*;
use libloading::Library;
use std::path::Path;

/// FTGeneralUtils.dll 封装结构体
///
/// 所有函数指针字段均为 Option 类型，因为某些版本的 DLL 可能不导出全部函数。
///
/// 生命周期说明：
/// - library 字段持有 DLL 句柄，必须在整个结构体生命周期内保持有效
/// - 函数指针来自 library 的符号解析，其有效性依赖于 library 不被释放
/// - 因此 library 字段必须为最后一个字段（drop 顺序保证），或使用 phantomdata 标记
pub struct FtGeneralDll {
    /// GeneralMakeFiles - 编译构建，生成 Makefile
    pub general_make_files: Option<GeneralMakeFilesFn>,

    /// DownloadCode - 固件下载到目标设备
    pub download_code: Option<DownloadCodeFn>,

    /// SetControllerWindowHandle - 设置控制器窗口句柄
    pub set_controller_window_handle: Option<SetControllerWindowHandleFn>,

    /// SetCallBackFun - 注册回调函数
    pub set_callback_fun: Option<SetCallBackFunFn>,

    /// SetBreakPoint - 设置断点
    pub set_break_point: Option<SetBreakPointFn>,

    /// FreeRun - 自由运行
    pub free_run: Option<FreeRunFn>,

    /// BreakRun - 停止运行
    pub break_run: Option<BreakRunFn>,

    /// ReadMemValue - 读取内存值
    pub read_mem_value: Option<ReadMemValueFn>,

    /// EnterDebugMode - 进入调试模式
    pub enter_debug_mode: Option<EnterDebugModeFn>,

    /// DownloadFirmware - 固件升级
    pub download_firmware: Option<DownloadFirmwareFn>,

    /// SetKeilIncludePath - 设置 Keil 头文件包含路径
    pub set_keil_include_path: Option<SetKeilIncludePathFn>,

    /// SetKeilBuildExterInfo - 设置 Keil 外部构建信息
    pub set_keil_build_exter_info: Option<SetKeilBuildExterInfoFn>,

    /// DLL 动态库句柄
    ///
    /// 此字段必须放在结构体最后位置，确保 drop 时函数指针先被释放，再释放 DLL 句柄。
    _library: Library,
}

impl FtGeneralDll {
    /// 加载 FTGeneralUtils.dll 并解析所有导出函数符号
    ///
    /// 某个函数符号不存在时，对应字段设为 None 而不报错，以兼容不同版本或精简版的 DLL。
    ///
    /// 参数：
    /// - path: DLL 文件的完整路径（绝对路径推荐）
    ///
    /// 返回值：
    /// - Ok(FtGeneralDll): 成功加载（至少 DLL 文件本身可加载）
    /// - Err(String): DLL 文件加载失败（文件不存在、格式错误等）
    pub fn load(path: &str) -> Result<Self, String> {
        let dll_path = Path::new(path);

        // 验证文件路径有效性
        if !dll_path.exists() {
            return Err(format!("DLL 文件不存在: {}", dll_path.display()));
        }

        // 加载 DLL 动态库，后续符号解析依赖此句柄。
        let library = unsafe {
            Library::new(dll_path)
                .map_err(|e| format!("加载 DLL 失败 [{}]: {}", dll_path.display(), e))?
        };

        // 逐一解析导出函数符号。
        let general_make_files = Self::resolve_symbol(&library, FN_GENERAL_MAKE_FILES);
        let download_code = Self::resolve_symbol(&library, FN_DOWNLOAD_CODE);
        let set_controller_window_handle =
            Self::resolve_symbol(&library, FN_SET_CONTROLLER_WINDOW_HANDLE);
        let set_callback_fun = Self::resolve_symbol(&library, FN_SET_CALLBACK_FUN);
        let set_break_point = Self::resolve_symbol(&library, FN_SET_BREAK_POINT);
        let free_run = Self::resolve_symbol(&library, FN_FREE_RUN);
        let break_run = Self::resolve_symbol(&library, FN_BREAK_RUN);
        let read_mem_value = Self::resolve_symbol(&library, FN_READ_MEM_VALUE);
        let enter_debug_mode = Self::resolve_symbol(&library, FN_ENTER_DEBUG_MODE);
        let download_firmware = Self::resolve_symbol(&library, FN_DOWNLOAD_FIRMWARE);
        let set_keil_include_path = Self::resolve_symbol(&library, FN_SET_KEIL_INCLUDE_PATH);
        let set_keil_build_exter_info =
            Self::resolve_symbol(&library, FN_SET_KEIL_BUILD_EXTER_INFO);

        // 统计成功解析的函数数量，辅助排查 DLL 版本兼容性问题。
        let resolved_count = [
            general_make_files.is_some(),
            download_code.is_some(),
            set_controller_window_handle.is_some(),
            set_callback_fun.is_some(),
            set_break_point.is_some(),
            free_run.is_some(),
            break_run.is_some(),
            read_mem_value.is_some(),
            enter_debug_mode.is_some(),
            download_firmware.is_some(),
            set_keil_include_path.is_some(),
            set_keil_build_exter_info.is_some(),
        ]
        .iter()
        .filter(|&&resolved| resolved)
        .count();

        log::info!(
            "FTGeneralUtils.dll 加载成功: [{}]，已解析 {}/12 个导出函数",
            dll_path.display(),
            resolved_count
        );

        Ok(Self {
            general_make_files,
            download_code,
            set_controller_window_handle,
            set_callback_fun,
            set_break_point,
            free_run,
            break_run,
            read_mem_value,
            enter_debug_mode,
            download_firmware,
            set_keil_include_path,
            set_keil_build_exter_info,
            _library: library,
        })
    }

    /// 从 DLL 中解析指定名称的导出函数符号
    ///
    /// 解析失败时返回 None，以兼容不同版本 DLL。
    ///
    /// 类型参数 F：目标函数签名类型（对应 types.rs 中定义的类型别名）
    ///
    /// 参数：
    /// - library: 已加载的 DLL 句柄
    /// - symbol_name: 导出函数名（来自 types.rs 中的常量）
    ///
    /// 返回值：
    /// - Some(F): 符号解析成功
    /// - None: 符号不存在（函数在当前 DLL 版本中未导出）
    #[allow(clippy::type_complexity)]
    fn resolve_symbol<F: Copy>(library: &Library, symbol_name: &str) -> Option<F> {
        unsafe {
            match library.get::<F>(symbol_name.as_bytes()) {
                Ok(symbol) => {
                    log::debug!("DLL 符号解析成功: {}", symbol_name);
                    Some(*symbol.into_raw())
                }
                Err(e) => {
                    log::warn!(
                        "DLL 符号解析跳过 [{}]: {}（当前版本 DLL 可能不包含此函数）",
                        symbol_name,
                        e
                    );
                    None
                }
            }
        }
    }
}
