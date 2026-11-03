"""
Dashboard API endpoints for AI request statistics
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session
from structlog import get_logger

from app.db.session import get_session
from app.api.deps import get_current_active_user
from app.models.user import User
from app.schemas.common import success_response, error_response
from app.services.dashboard_service import DashboardService

logger = get_logger(__name__)
router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def require_admin(current_user: User = Depends(get_current_active_user)):
    """Dependency to require admin role"""
    from fastapi import HTTPException
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


@router.get("/monthly-stats")
async def get_monthly_stats(
    month: str = Query(..., description="Month in YYYY-MM format", pattern=r"^\d{4}-\d{2}$"),
    dimension: str = Query("model", description="Dimension: model, group, module"),
    use_requests: bool = Query(False, description="Show request counts instead of costs"),
    group_id: int = Query(None, description="Optional user group id to filter by"),
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin)
):
    """
    Get monthly statistics for AI requests

    Args:
        month: Month in YYYY-MM format (e.g., "2026-01")
        dimension: Dimension to group by (model, group, module)
        use_requests: If True, show request counts instead of costs

    Returns:
        Monthly statistics with chart data and legend
    """
    try:
        if dimension not in ["model", "group", "module"]:
            return error_response(message="Invalid dimension. Must be one of: model, group, module", code=400)

        result = DashboardService.get_monthly_stats(
            session=session,
            month=month,
            dimension=dimension,
            use_requests=use_requests,
            group_id=group_id
        )
        return success_response(data=result.dict())

    except ValueError as e:
        logger.error(f"Invalid month format: {str(e)}")
        return error_response(message="Invalid month format. Use YYYY-MM", code=400)
    except Exception as e:
        logger.error(f"Error getting monthly stats: {str(e)}", exc_info=True)
        return error_response(message="Failed to get monthly statistics", code=500)


@router.get("/daily-stats")
async def get_daily_stats(
    date: str = Query(..., description="Date in YYYY-MM-DD format", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str = Query(None, description="Optional range end in YYYY-MM-DD format (inclusive)", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    dimension: str = Query("model", description="Dimension: model, group, module"),
    use_requests: bool = Query(False, description="Show request counts instead of costs"),
    group_id: int = Query(None, description="Optional user group id to filter by"),
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin)
):
    """
    Get daily statistics for AI requests

    Args:
        date: Date in YYYY-MM-DD format (e.g., "2026-01-26"); range start when end_date is given
        end_date: Optional range end (inclusive); multi-day ranges are bucketed by day
        dimension: Dimension to group by (model, group, module)
        use_requests: If True, show request counts instead of costs

    Returns:
        Daily statistics with chart data and legend
    """
    try:
        if dimension not in ["model", "group", "module"]:
            return error_response(message="Invalid dimension. Must be one of: model, group, module", code=400)

        if end_date:
            if end_date < date:
                return error_response(message="end_date must be on or after date", code=400)
            span_days = (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(date, "%Y-%m-%d")).days + 1
            if span_days > 366:
                return error_response(message="Date range cannot exceed 366 days", code=400)

        result = DashboardService.get_daily_stats(
            session=session,
            date=date,
            dimension=dimension,
            use_requests=use_requests,
            end_date=end_date,
            group_id=group_id
        )
        return success_response(data=result.dict())

    except ValueError as e:
        logger.error(f"Invalid date format: {str(e)}")
        return error_response(message="Invalid date format. Use YYYY-MM-DD", code=400)
    except Exception as e:
        logger.error(f"Error getting daily stats: {str(e)}", exc_info=True)
        return error_response(message="Failed to get daily statistics", code=500)


@router.get("/user-ranking")
async def get_user_ranking(
    start_date: str = Query(..., description="Start date in YYYY-MM-DD format", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str = Query(..., description="End date in YYYY-MM-DD format", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    limit: int = Query(10, ge=1, le=1000, description="Number of items to return"),
    module: str = Query(None, description="Optional module name to filter by"),
    sort_by: str = Query("requests", description="Sort by: requests, cost or tokens"),
    group_id: int = Query(None, description="Optional user group id to filter by"),
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin)
):
    """
    Get user ranking by cost

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        limit: Number of items to return (default 10, max 1000)
        module: Optional module name to filter by
        sort_by: Sort by requests, cost or tokens

    Returns:
        User ranking with request count, tokens, and cost
    """
    try:
        result = DashboardService.get_user_ranking(
            session=session,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            module=module,
            sort_by=sort_by,
            group_id=group_id
        )
        return success_response(data=result.dict())

    except ValueError as e:
        logger.error(f"Invalid date format: {str(e)}")
        return error_response(message="Invalid date format. Use YYYY-MM-DD", code=400)
    except Exception as e:
        logger.error(f"Error getting user ranking: {str(e)}", exc_info=True)
        return error_response(message="Failed to get user ranking", code=500)


@router.get("/group-ranking")
async def get_group_ranking(
    start_date: str = Query(..., description="Start date in YYYY-MM-DD format", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str = Query(..., description="End date in YYYY-MM-DD format", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    limit: int = Query(10, ge=1, le=1000, description="Number of items to return"),
    module: str = Query(None, description="Optional module name to filter by"),
    sort_by: str = Query("requests", description="Sort by: requests, cost or tokens"),
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin)
):
    """
    Get group ranking by cost

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        limit: Number of items to return (default 10, max 1000)
        module: Optional module name to filter by
        sort_by: Sort by requests, cost or tokens

    Returns:
        Group ranking with request count, tokens, and cost
    """
    try:
        result = DashboardService.get_group_ranking(
            session=session,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            module=module,
            sort_by=sort_by
        )
        return success_response(data=result.dict())

    except ValueError as e:
        logger.error(f"Invalid date format: {str(e)}")
        return error_response(message="Invalid date format. Use YYYY-MM-DD", code=400)
    except Exception as e:
        logger.error(f"Error getting group ranking: {str(e)}", exc_info=True)
        return error_response(message="Failed to get group ranking", code=500)


@router.get("/trend-stats")
async def get_trend_stats(
    days: int = Query(30, ge=1, le=90, description="Number of days to look back"),
    metric: str = Query("users", description="Metric: users, requests, tokens, success_rate"),
    module: str = Query(None, description="Optional module name to filter by"),
    group_id: int = Query(None, description="Optional user group id to filter by"),
    start_date: str = Query(None, description="Optional range start in YYYY-MM-DD format", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str = Query(None, description="Optional range end in YYYY-MM-DD format", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin)
):
    """
    Get trend statistics for the last N days

    Args:
        days: Number of days (default 30, max 90)
        metric: Metric type (users, requests, tokens, success_rate)
        module: Optional module name to filter by

    Returns:
        Trend statistics with daily data points
    """
    try:
        valid_metrics = ["users", "requests", "tokens", "success_rate"]
        if metric not in valid_metrics:
            return error_response(
                message=f"Invalid metric. Must be one of: {', '.join(valid_metrics)}", code=400
            )

        result = DashboardService.get_trend_stats(
            session=session,
            days=days,
            metric=metric,
            module=module,
            group_id=group_id,
            start_date=start_date,
            end_date=end_date
        )
        return success_response(data=result.dict())

    except ValueError as e:
        logger.error(f"Invalid request: {str(e)}")
        return error_response(message=str(e), code=400)
    except Exception as e:
        logger.error(f"Error getting trend stats: {str(e)}", exc_info=True)
        return error_response(message="Failed to get trend statistics", code=500)


@router.get("/cost-trend-stats")
async def get_cost_trend_stats(
    days: int = Query(30, ge=1, le=90, description="Number of days to look back"),
    group_id: int = Query(None, description="Optional user group id to filter by"),
    start_date: str = Query(None, description="Optional range start in YYYY-MM-DD format", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str = Query(None, description="Optional range end in YYYY-MM-DD format", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin)
):
    """
    Get daily cost (CNY) and credits consumption trend for the last N days
    """
    try:
        result = DashboardService.get_cost_trend_stats(
            session=session,
            days=days,
            group_id=group_id,
            start_date=start_date,
            end_date=end_date
        )
        return success_response(data=result.dict())

    except ValueError as e:
        logger.error(f"Invalid request: {str(e)}")
        return error_response(message=str(e), code=400)
    except Exception as e:
        logger.error(f"Error getting cost trend stats: {str(e)}", exc_info=True)
        return error_response(message="Failed to get cost trend statistics", code=500)


@router.get("/daily-overview")
async def get_daily_overview(
    date: str = Query(..., description="Date in YYYY-MM-DD format", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str = Query(None, description="Optional range end in YYYY-MM-DD format (inclusive)", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    group_id: int = Query(None, description="Optional user group id to filter by"),
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin)
):
    """
    Get daily overview statistics

    Args:
        date: Date in YYYY-MM-DD format (e.g., "2026-01-26"); range start when end_date is given
        end_date: Optional range end (inclusive); aggregates over the whole range

    Returns:
        Daily overview with unique users, total requests, tokens, and success rate
    """
    try:
        if end_date:
            if end_date < date:
                return error_response(message="end_date must be on or after date", code=400)
            span_days = (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(date, "%Y-%m-%d")).days + 1
            if span_days > 366:
                return error_response(message="Date range cannot exceed 366 days", code=400)

        result = DashboardService.get_daily_overview(
            session=session,
            date=date,
            end_date=end_date,
            group_id=group_id
        )
        return success_response(data=result.dict())

    except ValueError as e:
        logger.error(f"Invalid date format: {str(e)}")
        return error_response(message="Invalid date format. Use YYYY-MM-DD", code=400)
    except Exception as e:
        logger.error(f"Error getting daily overview: {str(e)}", exc_info=True)
        return error_response(message="Failed to get daily overview", code=500)


@router.get("/model-token-stats")
async def get_model_token_stats(
    date: str = Query(..., description="Date in YYYY-MM-DD format", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str = Query(None, description="Optional range end in YYYY-MM-DD format (inclusive)", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    group_id: int = Query(None, description="Optional user group id to filter by"),
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin)
):
    """
    Get per-model token consumption statistics

    Args:
        date: Date in YYYY-MM-DD format; range start when end_date is given
        end_date: Optional range end (inclusive); aggregates over the whole range

    Returns:
        Per-model token breakdown sorted by total tokens desc
    """
    try:
        if end_date:
            if end_date < date:
                return error_response(message="end_date must be on or after date", code=400)
            span_days = (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(date, "%Y-%m-%d")).days + 1
            if span_days > 366:
                return error_response(message="Date range cannot exceed 366 days", code=400)

        result = DashboardService.get_model_token_stats(
            session=session,
            date=date,
            end_date=end_date,
            group_id=group_id
        )
        return success_response(data=result.dict())

    except ValueError as e:
        logger.error(f"Invalid date format: {str(e)}")
        return error_response(message="Invalid date format. Use YYYY-MM-DD", code=400)
    except Exception as e:
        logger.error(f"Error getting model token stats: {str(e)}", exc_info=True)
        return error_response(message="Failed to get model token stats", code=500)


@router.get("/user-stats")
async def get_user_stats(
    user_id: int = Query(..., description="User ID"),
    start_date: str = Query(..., description="Start date in YYYY-MM-DD format", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str = Query(..., description="End date in YYYY-MM-DD format", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin)
):
    """
    Get detailed statistics for a specific user

    Args:
        user_id: User ID
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format

    Returns:
        Per-user detailed statistics including module/model breakdown and daily trend
    """
    try:
        result = DashboardService.get_user_stats(
            session=session,
            user_id=user_id,
            start_date=start_date,
            end_date=end_date
        )
        return success_response(data=result.dict())

    except ValueError as e:
        logger.error(f"Invalid request: {str(e)}")
        return error_response(message=str(e), code=400)
    except Exception as e:
        logger.error(f"Error getting user stats: {str(e)}", exc_info=True)
        return error_response(message="Failed to get user statistics", code=500)


@router.get("/group-stats")
async def get_group_stats(
    group_id: int = Query(..., description="User group ID"),
    start_date: str = Query(..., description="Start date in YYYY-MM-DD format", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str = Query(..., description="End date in YYYY-MM-DD format", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin)
):
    """
    Get detailed statistics for a user group (direct members only)
    """
    try:
        result = DashboardService.get_group_stats(
            session=session,
            group_id=group_id,
            start_date=start_date,
            end_date=end_date
        )
        return success_response(data=result.dict())

    except ValueError as e:
        logger.error(f"Invalid request: {str(e)}")
        return error_response(message=str(e), code=400)
    except Exception as e:
        logger.error(f"Error getting group stats: {str(e)}", exc_info=True)
        return error_response(message="Failed to get group statistics", code=500)
