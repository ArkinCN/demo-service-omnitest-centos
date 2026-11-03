use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::types::{ERROR_CODE_GENERAL, IPC_MAX_MESSAGE_SIZE};

#[derive(Debug, Clone, Serialize, Deserialize)]
// serde 的 tag 属性只接受字符串字面量，需与 types.rs 中的 tag 常量保持一致。
// rename_all 控制变体名（如 InitDll -> initDll），
// rename_all_fields 控制变体内部字段名（如 dll_path -> dllPath）
#[serde(
    tag = "type",
    rename_all = "camelCase",
    rename_all_fields = "camelCase"
)]
pub enum IpcRequest {
    /// 初始化 DLL —— 加载指定路径的 DLL 文件
    InitDll {
        /// DLL 文件绝对路径
        dll_path: String,
    },

    /// 编译构建 —— 对指定工程路径执行 GeneralMakeFiles
    GeneralMakeFiles {
        /// 工程目录绝对路径
        project_path: String,
    },

    /// 固件下载 —— 将编译产物下载到目标芯片
    DownloadCode {
        /// 芯片型号名称
        chip_name: String,
        /// 工程目录绝对路径
        project_path: String,
    },

    /// 设置窗口句柄 —— 传递主窗口句柄给 DLL 用于消息回调
    SetControllerWindowHandle {
        /// 窗口句柄（Windows HWND 转为 u64）
        handle: u64,
    },

    /// 设置回调函数 —— 通知子进程注册 DLL 回调
    SetCallBackFun,

    /// 设置断点 —— 在指定地址设置运行断点
    SetBreakPoint {
        /// 断点内存地址
        address: u32,
    },

    /// 自由运行 —— 启动/继续目标芯片运行
    /// main_addr: SetBreakPoint 断点地址（从 MAP 文件解析的 main 函数地址）
    FreeRun {
        /// main 函数地址（断点地址），从 MAP 文件解析
        main_addr: u32,
    },

    /// 停止运行 —— 暂停/中断目标芯片运行
    BreakRun,

    /// 复位 MCU —— BreakRun 停止 + SetBreakPoint + EnterDebugMode 复位到断点
    /// 与 Python fice_session.py 的 _handle_reset 一致
    Reset {
        /// 断点地址（MCU 复位后停在此地址）
        address: u32,
    },

    /// 读取内存 —— 从目标芯片当前地址读取数据（DLL 内部维护读取地址）
    ReadMemValue {
        /// 读取长度（字节数）
        length: u32,
    },

    /// 进入调试模式 —— 切换芯片到调试运行模式
    EnterDebugMode {
        /// 调试模式编号
        mode: i32,
    },

    /// 固件升级 —— 调用 DLL 的 DownloadFirmware 函数
    DownloadFirmware,

    /// 关闭 —— 通知子进程优雅退出，释放 DLL 资源
    Shutdown,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
// serde 的 tag 属性只接受字符串字面量，需与 types.rs 中的 tag 常量保持一致。
// rename_all 控制变体名（如 Success -> success），
// rename_all_fields 控制变体内部字段名（如 request_id -> requestId）
#[serde(
    tag = "type",
    rename_all = "camelCase",
    rename_all_fields = "camelCase"
)]
pub enum IpcResponse {
    /// 操作成功 —— 请求执行成功，携带可选数据
    Success {
        /// 对应请求的消息 ID，用于匹配请求和响应
        request_id: String,
        /// 可选的返回数据（如 ReadMemValue 返回的内存数据）
        #[serde(skip_serializing_if = "Option::is_none")]
        data: Option<serde_json::Value>,
    },

    /// 操作失败 —— 请求执行失败，携带错误信息
    Error {
        /// 对应请求的消息 ID
        request_id: String,
        /// 人类可读的错误描述
        message: String,
        /// 可选的错误码（引用 types.rs 中的 ERROR_CODE_* 常量）
        #[serde(skip_serializing_if = "Option::is_none")]
        code: Option<i32>,
    },

    /// DLL 回调事件 —— DLL 通过回调通知的异步事件
    CallbackEvent {
        /// 回调消息 ID（DLL 定义的回调消息标识）
        msg_id: i32,
        /// WPARAM 参数
        w_param: i32,
        /// LPARAM 参数
        l_param: i32,
    },

    /// DLL 加载完成 —— 通知 DLL 文件已成功加载
    DllLoaded {
        /// 已加载的 DLL 文件路径
        dll_path: String,
    },

    /// 子进程就绪 —— 子进程启动完成后发送，表示可以接收请求
    Ready,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct IpcMessage {
    /// 消息唯一标识（UUID v4），用于匹配请求和响应
    pub id: String,
    /// 消息发送时间戳（Unix 毫秒）
    pub timestamp: u64,
    /// 消息体 —— 具体的 IPC 请求内容
    pub payload: IpcRequest,
}

impl IpcMessage {
    /// 创建新的 IPC 消息，自动生成 UUID 和当前时间戳
    pub fn new(payload: IpcRequest) -> Self {
        Self {
            id: Uuid::new_v4().to_string(),
            timestamp: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_millis() as u64,
            payload,
        }
    }

    /// 将 IPC 消息序列化为 JSON 字符串
    pub fn to_json(&self) -> Result<String, IpcError> {
        let json = serde_json::to_string(self)?;
        // 防止超大消息导致管道阻塞或内存溢出
        if json.len() > IPC_MAX_MESSAGE_SIZE {
            return Err(IpcError::MessageTooLarge {
                size: json.len(),
                max: IPC_MAX_MESSAGE_SIZE,
            });
        }
        Ok(json)
    }

    /// 从 JSON 字符串反序列化 IPC 消息
    pub fn from_json(json: &str) -> Result<Self, IpcError> {
        Ok(serde_json::from_str(json)?)
    }
}

impl IpcResponse {
    /// 将 IPC 响应序列化为 JSON 字符串
    pub fn to_json(&self) -> Result<String, IpcError> {
        let json = serde_json::to_string(self)?;
        if json.len() > IPC_MAX_MESSAGE_SIZE {
            return Err(IpcError::MessageTooLarge {
                size: json.len(),
                max: IPC_MAX_MESSAGE_SIZE,
            });
        }
        Ok(json)
    }

    /// 从 JSON 字符串反序列化 IPC 响应
    pub fn from_json(json: &str) -> Result<Self, IpcError> {
        Ok(serde_json::from_str(json)?)
    }

    /// 从 JSON 行解析（去除首尾空白和换行符）
    pub fn from_json_line(line: &str) -> Result<Self, IpcError> {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            return Err(IpcError::EmptyMessage);
        }
        Self::from_json(trimmed)
    }

    /// 提取响应中的 request_id（如果存在）
    pub fn request_id(&self) -> Option<&str> {
        match self {
            IpcResponse::Success { request_id, .. } => Some(request_id),
            IpcResponse::Error { request_id, .. } => Some(request_id),
            IpcResponse::CallbackEvent { .. } => None,
            IpcResponse::DllLoaded { .. } => None,
            IpcResponse::Ready => None,
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum IpcError {
    /// JSON 序列化/反序列化失败
    #[error("JSON 序列化/反序列化失败: {0}")]
    JsonError(#[from] serde_json::Error),

    /// 消息超过最大长度限制
    #[error("消息过大: {size} 字节，最大允许 {max} 字节")]
    MessageTooLarge { size: usize, max: usize },

    /// 收到空消息
    #[error("收到空消息")]
    EmptyMessage,

    /// 管道 IO 错误
    #[error("管道 IO 错误: {0}")]
    IoError(#[from] std::io::Error),

    /// 请求超时
    #[error("请求超时，消息 ID: {request_id}")]
    Timeout { request_id: String },
}

impl IpcResponse {
    /// 构造成功响应（无附加数据）
    pub fn ok(request_id: impl Into<String>) -> Self {
        IpcResponse::Success {
            request_id: request_id.into(),
            data: None,
        }
    }

    /// 构造成功响应（带附加数据）
    pub fn ok_with_data(request_id: impl Into<String>, data: serde_json::Value) -> Self {
        IpcResponse::Success {
            request_id: request_id.into(),
            data: Some(data),
        }
    }

    /// 构造通用错误响应
    pub fn error(request_id: impl Into<String>, message: impl Into<String>) -> Self {
        IpcResponse::Error {
            request_id: request_id.into(),
            message: message.into(),
            code: Some(ERROR_CODE_GENERAL),
        }
    }

    /// 构造带错误码的错误响应
    pub fn error_with_code(
        request_id: impl Into<String>,
        message: impl Into<String>,
        code: i32,
    ) -> Self {
        IpcResponse::Error {
            request_id: request_id.into(),
            message: message.into(),
            code: Some(code),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::*;

    /// 测试 IpcMessage 创建时自动生成 ID 和时间戳
    #[test]
    fn test_ipc_message_new_generates_id_and_timestamp() {
        let msg = IpcMessage::new(IpcRequest::Shutdown);
        assert!(!msg.id.is_empty(), "消息 ID 不应为空");
        assert!(msg.timestamp > 0, "时间戳应大于 0");
    }

    /// 测试 IpcMessage 序列化和反序列化的对称性
    #[test]
    fn test_ipc_message_roundtrip() {
        let original = IpcMessage::new(IpcRequest::InitDll {
            dll_path: "C:\\test\\.dll".to_string(),
        });
        let json = original.to_json().expect("序列化应成功");
        let restored = IpcMessage::from_json(&json).expect("反序列化应成功");
        assert_eq!(original.id, restored.id);
    }

    /// 测试 IpcRequest 序列化的 camelCase 字段名和 type tag
    #[test]
    fn test_ipc_request_serialization_format() {
        let msg = IpcMessage {
            id: "test-id".to_string(),
            timestamp: 1000,
            payload: IpcRequest::InitDll {
                dll_path: "test.dll".to_string(),
            },
        };
        let json = msg.to_json().unwrap();
        let value: serde_json::Value = serde_json::from_str(&json).unwrap();

        // 验证 tag 字段
        assert_eq!(value["payload"]["type"], "initDll");
        // 验证 camelCase 字段名
        assert!(value["payload"]["dllPath"].is_string());
    }

    /// 测试 IpcResponse 成功响应序列化
    #[test]
    fn test_ipc_response_success_serialization() {
        let resp = IpcResponse::ok_with_data("req-1", serde_json::json!({"bytes": [1, 2, 3]}));
        let json = resp.to_json().unwrap();
        let value: serde_json::Value = serde_json::from_str(&json).unwrap();

        assert_eq!(value["type"], "success");
        assert_eq!(value["requestId"], "req-1");
        assert!(value["data"]["bytes"].is_array());
    }

    /// 测试 IpcResponse 错误响应
    #[test]
    fn test_ipc_response_error_with_code() {
        let resp =
            IpcResponse::error_with_code("req-2", "DLL 加载失败", ERROR_CODE_DLL_LOAD_FAILED);
        let json = resp.to_json().unwrap();
        let value: serde_json::Value = serde_json::from_str(&json).unwrap();

        assert_eq!(value["type"], "error");
        assert_eq!(value["code"], ERROR_CODE_DLL_LOAD_FAILED);
        assert_eq!(value["message"], "DLL 加载失败");
    }

    /// 测试 IpcResponse CallbackEvent 序列化
    #[test]
    fn test_ipc_response_callback_event() {
        let resp = IpcResponse::CallbackEvent {
            msg_id: 100,
            w_param: 1,
            l_param: 2,
        };
        let json = resp.to_json().unwrap();
        let value: serde_json::Value = serde_json::from_str(&json).unwrap();

        assert_eq!(value["type"], "callbackEvent");
        assert_eq!(value["msgId"], 100);
        assert_eq!(value["wParam"], 1);
        assert_eq!(value["lParam"], 2);
    }

    /// 测试 IpcResponse::request_id() 提取
    #[test]
    fn test_ipc_response_request_id_extraction() {
        let success = IpcResponse::ok("abc");
        assert_eq!(success.request_id(), Some("abc"));

        let error = IpcResponse::error("def", "err");
        assert_eq!(error.request_id(), Some("def"));

        let callback = IpcResponse::CallbackEvent {
            msg_id: 0,
            w_param: 0,
            l_param: 0,
        };
        assert_eq!(callback.request_id(), None);

        assert_eq!(IpcResponse::Ready.request_id(), None);
    }

    /// 测试 IpcResponse::from_json_line 处理空白行
    #[test]
    fn test_ipc_response_from_json_line_empty() {
        let result = IpcResponse::from_json_line("  \n  ");
        assert!(result.is_err());
        match result {
            Err(IpcError::EmptyMessage) => {}
            _ => panic!("应返回 EmptyMessage 错误"),
        }
    }

    /// 测试所有 IpcRequest 变体都能正确序列化/反序列化
    #[test]
    fn test_all_ipc_request_variants_roundtrip() {
        let variants = vec![
            IpcRequest::InitDll {
                dll_path: "path".into(),
            },
            IpcRequest::GeneralMakeFiles {
                project_path: "proj".into(),
            },
            IpcRequest::DownloadCode {
                chip_name: "chip".into(),
                project_path: "proj".into(),
            },
            IpcRequest::SetControllerWindowHandle { handle: 12345 },
            IpcRequest::SetCallBackFun,
            IpcRequest::SetBreakPoint { address: 0x1000 },
            IpcRequest::FreeRun {
                main_addr: DEFAULT_BREAKPOINT_ADDR,
            },
            IpcRequest::BreakRun,
            IpcRequest::ReadMemValue { length: 64 },
            IpcRequest::EnterDebugMode { mode: 1 },
            IpcRequest::DownloadFirmware,
            IpcRequest::Shutdown,
        ];

        for original in variants {
            let msg = IpcMessage::new(original);
            let json = msg.to_json().expect("序列化应成功");
            let restored = IpcMessage::from_json(&json).expect("反序列化应成功");
            assert_eq!(msg.id, restored.id, "ID 应匹配");
        }
    }

    /// 测试错误码常量值的唯一性（确保不同错误码不重复）
    #[test]
    fn test_error_codes_are_unique() {
        let codes = [
            ERROR_CODE_SUCCESS,
            ERROR_CODE_GENERAL,
            ERROR_CODE_DLL_LOAD_FAILED,
            ERROR_CODE_DLL_CALL_FAILED,
            ERROR_CODE_DLL_NOT_INITIALIZED,
            ERROR_CODE_INVALID_PARAMS,
            ERROR_CODE_INVALID_ADDRESS,
            ERROR_CODE_TIMEOUT,
            ERROR_CODE_PIPE_DISCONNECTED,
            ERROR_CODE_JSON_PARSE_FAILED,
            ERROR_CODE_UNKNOWN_REQUEST,
            ERROR_CODE_NOT_READY,
            ERROR_CODE_REJECTED,
        ];
        // 使用集合去重验证唯一性
        let unique: std::collections::HashSet<i32> = codes.iter().copied().collect();
        assert_eq!(unique.len(), codes.len(), "所有错误码应唯一");
    }
}
