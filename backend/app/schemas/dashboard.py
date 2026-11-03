"""
Dashboard schemas for AI request statistics API
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator

from app.schemas.user import _make_avatar_url_absolute


class ChartDataPoint(BaseModel):
    """Chart data point with dynamic keys for each dimension value"""
    label: str = Field(description="X-axis label (date or hour)")
    # Dynamic keys will be added for each dimension value (model name, group name, etc.)

    class Config:
        extra = "allow"  # Allow dynamic fields


class LegendItem(BaseModel):
    """Legend item for chart"""
    name: str = Field(description="Dimension name (model, group, module)")
    value: float = Field(description="Value (cost or tokens)")
    percentage: float = Field(description="Percentage 0-100")
    color: str = Field(description="Color hex value")
    tokens: Optional[int] = Field(default=None, description="Total tokens for the dimension")


class MonthlyStatsResponse(BaseModel):
    """Monthly statistics response"""
    month: str = Field(description="Month in YYYY-MM format")
    total_cost: float = Field(description="Total cost in CNY")
    total_requests: int = Field(description="Total request count")
    total_tokens: int = Field(description="Total token count")
    chart_data: List[Dict[str, Any]] = Field(description="Chart data points (31 days)")
    legend_items: List[LegendItem] = Field(description="Legend items")
    dimension_keys: List[str] = Field(description="Dimension keys for chart rendering")


class DailyStatsResponse(BaseModel):
    """Daily statistics response"""
    date: str = Field(description="Date in YYYY-MM-DD format")
    total_cost: float = Field(description="Total cost in CNY")
    total_requests: int = Field(description="Total request count")
    total_tokens: int = Field(description="Total token count")
    chart_data: List[Dict[str, Any]] = Field(description="Chart data points (24 hours)")
    legend_items: List[LegendItem] = Field(description="Legend items")
    dimension_keys: List[str] = Field(description="Dimension keys for chart rendering")


class DailyOverviewResponse(BaseModel):
    """Daily overview statistics response"""
    date: str = Field(description="Date in YYYY-MM-DD format")
    unique_users: int = Field(description="Number of unique users")
    total_requests: int = Field(description="Total request count")
    total_tokens: int = Field(description="Total token count")
    success_rate: float = Field(description="Success rate 0-100")
    total_cost: float = Field(default=0.0, description="Total cost in CNY")
    total_credits: float = Field(default=0.0, description="Total credits consumed")


class ModelTokenStatItem(BaseModel):
    """Per-model token consumption item"""
    model: str = Field(description="Model name")
    request_count: int = Field(description="Request count")
    prompt_tokens: int = Field(description="Input token count")
    completion_tokens: int = Field(description="Output token count")
    total_tokens: int = Field(description="Total token count")
    percentage: float = Field(description="Share of total tokens 0-100")


class ModelTokenStatsResponse(BaseModel):
    """Per-model token consumption response"""
    date: str = Field(description="Range start date in YYYY-MM-DD format")
    total_tokens: int = Field(description="Total token count across all models")
    items: List[ModelTokenStatItem] = Field(description="Per-model breakdown sorted by tokens desc")


class TrendDataPoint(BaseModel):
    """Trend chart data point"""
    date: str = Field(description="Date label (e.g., 1月27日)")
    value: float = Field(description="Metric value")


class TrendStatsResponse(BaseModel):
    """Trend statistics response for 30-day chart"""
    metric: str = Field(description="Metric type: users, requests, tokens, success_rate")
    days: int = Field(description="Number of days")
    data: List[TrendDataPoint] = Field(description="Trend data points")


class CostTrendDataPoint(BaseModel):
    """Cost & credits trend chart data point"""
    date: str = Field(description="Date label (e.g., 1月27日)")
    cost: float = Field(description="Cost in CNY")
    credits: float = Field(description="Credits consumed")


class CostTrendStatsResponse(BaseModel):
    """Cost & credits trend statistics response"""
    days: int = Field(description="Number of days")
    data: List[CostTrendDataPoint] = Field(description="Trend data points")


class RankingItem(BaseModel):
    """Ranking item for user or group"""
    rank: int = Field(description="Rank position")
    id: int = Field(description="User or group ID")
    name: str = Field(description="User or group name")
    avatar_url: Optional[str] = Field(default=None, description="User avatar URL")
    request_count: int = Field(description="Total request count")
    total_tokens: int = Field(description="Total token count")
    total_cost: float = Field(description="Total cost in CNY")

    @field_validator("avatar_url", mode="after")
    @classmethod
    def resolve_avatar_url(cls, v: Optional[str]) -> Optional[str]:
        return _make_avatar_url_absolute(v)


class GroupStatsResponse(BaseModel):
    """Per-group detailed statistics response"""
    model_config = {"protected_namespaces": ()}
    group_id: int = Field(description="User group ID")
    name: str = Field(description="Group name")
    member_count: int = Field(description="Direct member count")
    total_requests: int = Field(description="Total request count")
    total_cost: float = Field(description="Total cost in CNY")
    total_credits: float = Field(default=0.0, description="Total credits consumed")
    total_tokens: int = Field(description="Total token count")
    success_rate: float = Field(description="Success rate 0-100")
    module_breakdown: List[LegendItem] = Field(description="Usage breakdown by module")
    model_breakdown: List[LegendItem] = Field(description="Usage breakdown by model")
    trend_chart_data: List[Dict[str, Any]] = Field(description="Trend chart data with model breakdown")
    trend_dimension_keys: List[str] = Field(description="Model keys for trend chart rendering")
    daily_total_trend: List[TrendDataPoint] = Field(default_factory=list, description="Daily total cost trend (multi-day only)")


class RankingResponse(BaseModel):
    """Ranking response"""
    items: List[RankingItem] = Field(description="Ranking items")
    total_count: int = Field(description="Total count")


class UserStatsResponse(BaseModel):
    """Per-user detailed statistics response"""
    model_config = {"protected_namespaces": ()}
    user_id: int = Field(description="User ID")
    username: str = Field(description="Username")
    nickname: Optional[str] = Field(default=None, description="User nickname")
    avatar_url: Optional[str] = Field(default=None, description="User avatar URL")
    group_names: List[str] = Field(default_factory=list, description="User group names")
    total_requests: int = Field(description="Total request count")
    total_cost: float = Field(description="Total cost in CNY")
    total_credits: float = Field(default=0.0, description="Total credits consumed")
    total_tokens: int = Field(description="Total token count")
    success_rate: float = Field(description="Success rate 0-100")
    module_breakdown: List[LegendItem] = Field(description="Usage breakdown by module")
    model_breakdown: List[LegendItem] = Field(description="Usage breakdown by model")
    trend_chart_data: List[Dict[str, Any]] = Field(description="Trend chart data with model breakdown")
    trend_dimension_keys: List[str] = Field(description="Model keys for trend chart rendering")
    daily_total_trend: List[TrendDataPoint] = Field(default_factory=list, description="Daily total request trend (multi-day only)")

    @field_validator("avatar_url", mode="after")
    @classmethod
    def resolve_avatar_url(cls, v: Optional[str]) -> Optional[str]:
        return _make_avatar_url_absolute(v)


# Request schemas
class MonthlyStatsRequest(BaseModel):
    """Monthly stats request parameters"""
    month: str = Field(description="Month in YYYY-MM format")
    dimension: str = Field(default="model", description="Dimension: model, group, module")


class DailyStatsRequest(BaseModel):
    """Daily stats request parameters"""
    date: str = Field(description="Date in YYYY-MM-DD format")
    dimension: str = Field(default="model", description="Dimension: model, group, module")


class RankingRequest(BaseModel):
    """Ranking request parameters"""
    start_date: str = Field(description="Start date in YYYY-MM-DD format")
    end_date: str = Field(description="End date in YYYY-MM-DD format")
    limit: int = Field(default=10, description="Number of items to return")
