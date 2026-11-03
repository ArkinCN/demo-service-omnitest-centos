"""部署 Webhook 的请求与响应模型"""
from pydantic import BaseModel, Field


class DeployRequest(BaseModel):
    """部署请求模型"""
    tag: str = Field(description="Git tag 名称，如 'v1.0.0'")
    project: str = Field(description="项目名称，如 'docusaurus_motordebug'")


class DeployResponse(BaseModel):
    """部署响应模型"""
    success: bool = Field(description="是否成功触发部署")
    message: str = Field(description="响应消息")
    tag: str = Field(description="触发部署的 Git tag")
