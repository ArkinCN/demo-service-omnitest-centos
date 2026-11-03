//! FTGeneralUtils.dll 的 Rust FFI 桥接层，仅在 Windows 平台编译。

#![cfg(target_os = "windows")]

pub mod bridge_client;
pub mod cli;
pub mod embedded_dll;
pub mod ffi;
pub mod ipc;
pub mod types;
pub mod window;

// 重新导出常用公共 API，简化上层导入路径。

pub use bridge_client::BridgeProcess;
pub use ffi::FtGeneralDll;
pub use ipc::{IpcError, IpcMessage, IpcRequest, IpcResponse};
pub use types::*;
