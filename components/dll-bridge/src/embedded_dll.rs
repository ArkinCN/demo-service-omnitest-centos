//! 编译时嵌入 DLL 文件，运行时解压到临时目录
//!
//! 使用 include_bytes! 将 FTGeneralUtils.dll 编译进二进制文件，
//! 运行时解压到系统临时目录以供加载。Drop 时自动清理临时文件。

use std::fs;
use std::path::PathBuf;

use crate::types::*;

// 编译时嵌入 DLL 二进制数据（include_bytes! 要求字符串字面量，不能使用常量）
// 迁移进 c/ 后，DLL 随包放在本 crate 的 resources/ 目录，路径相对 src/ 上一级。
const EMBEDDED_DLL_BYTES: &[u8] = include_bytes!("../resources/FTGeneralUtils.dll");

/// 嵌入 DLL 的临时文件管理
///
/// 创建时将嵌入的 DLL 字节写入临时目录，销毁时自动清理。
pub struct EmbeddedDll {
    /// 临时目录路径（包含 DLL 文件）
    temp_dir: PathBuf,
    /// DLL 文件完整路径
    dll_path: PathBuf,
}

impl EmbeddedDll {
    /// 将嵌入的 DLL 解压到临时目录
    ///
    /// 使用 UUID 生成唯一临时目录名，避免多实例冲突。
    pub fn new() -> Result<Self, String> {
        let uid = uuid::Uuid::new_v4();
        let temp_dir = std::env::temp_dir().join(format!("{}{}", DLL_TEMP_DIR_PREFIX, uid));
        fs::create_dir_all(&temp_dir).map_err(|e| format!("创建临时目录失败: {}", e))?;

        let dll_path = temp_dir.join(DLL_FILE_NAME);
        fs::write(&dll_path, EMBEDDED_DLL_BYTES)
            .map_err(|e| format!("写入 DLL 到临时目录失败: {}", e))?;

        log::info!("嵌入 DLL 已解压到: {}", dll_path.display());
        Ok(Self { temp_dir, dll_path })
    }

    /// 获取 DLL 文件路径
    pub fn dll_path(&self) -> &PathBuf {
        &self.dll_path
    }
}

impl Drop for EmbeddedDll {
    fn drop(&mut self) {
        // 清理临时目录及其中的 DLL 文件
        if let Err(e) = fs::remove_dir_all(&self.temp_dir) {
            log::warn!("清理临时目录失败 {}: {}", self.temp_dir.display(), e);
        }
    }
}
