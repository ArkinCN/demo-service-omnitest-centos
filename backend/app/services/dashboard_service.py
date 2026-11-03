"""
Dashboard service for AI request statistics
"""
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Tuple
from calendar import monthrange
from sqlmodel import Session, select, func, and_, case
from sqlalchemy import extract, text
from structlog import get_logger

# China timezone offset (UTC+8)
CHINA_TZ_OFFSET = timedelta(hours=8)
CHINA_TZ = timezone(CHINA_TZ_OFFSET)

# Blocked modules (excluded from statistics)
from app.models.ai_request import AIRequest
from app.models.credits import CreditTransaction
from app.models.user import User
from app.models.user_group import UserGroup, UserGroupMember
from app.models.stat_group import StatGroupSelection
from app.schemas.dashboard import (
    MonthlyStatsResponse, DailyStatsResponse,
    RankingItem, RankingResponse, LegendItem,
    DailyOverviewResponse, TrendDataPoint, TrendStatsResponse,
    CostTrendDataPoint, CostTrendStatsResponse,
    UserStatsResponse, GroupStatsResponse, ModelTokenStatItem, ModelTokenStatsResponse
)

logger = get_logger(__name__)

# Color palette for charts (distinct colors)
CHART_COLORS = [
    "#0088FE", "#00C49F", "#FFBB28", "#FF8042", "#8884D8",
    "#82CA9D", "#FFC658", "#8DD1E1", "#A4DE6C", "#D0ED57",
    "#FAD000", "#F66D44", "#FEAE65", "#E6F69D", "#AADEA7",
    "#64C2A6", "#2D87BB", "#7B68EE", "#FF6B6B", "#4ECDC4"
]


def get_color(index: int) -> str:
    """Get color from palette by index"""
    return CHART_COLORS[index % len(CHART_COLORS)]


# 长周期图表里低频维度会撑爆图例，期间请求数低于该阈值的合并为“其他”
OTHER_DIMENSION = "其他"
OTHER_MERGE_THRESHOLD = 100


class DashboardService:
    """Service for dashboard statistics"""

    @staticmethod
    def expand_group_ids(session: Session, group_id: int) -> list[int]:
        """展开分组及其所有后代分组 ID（父分组统计需覆盖整棵子树）"""
        pairs = session.exec(select(UserGroup.id, UserGroup.parent_id)).all()
        children: dict[int, list[int]] = {}
        for gid, pid in pairs:
            if pid is not None:
                children.setdefault(pid, []).append(gid)
        ids = [group_id]
        queue = [group_id]
        while queue:
            for child in children.get(queue.pop(), []):
                ids.append(child)
                queue.append(child)
        return ids

    @staticmethod
    def _group_member_condition(session: Session, group_id: int):
        """限定 AIRequest 只统计指定用户分组（含其所有子分组）的成员"""
        group_ids = DashboardService.expand_group_ids(session, group_id)
        return AIRequest.user_id.in_(
            select(UserGroupMember.user_id).where(UserGroupMember.group_id.in_(group_ids))
        )

    @staticmethod
    def _consume_credits_total(session: Session, user_scope, utc_start: datetime, utc_end: datetime) -> float:
        """区间内 consume 流水实扣 Credits 合计（÷1M，user_scope 限定用户范围）"""
        total = session.exec(
            select(func.sum(CreditTransaction.amount)).where(and_(
                CreditTransaction.type == "consume",
                CreditTransaction.created_at >= utc_start,
                CreditTransaction.created_at < utc_end,
                user_scope,
            ))
        ).one()
        return round(abs(float(total or 0)) / 1_000_000, 2)

    @staticmethod
    def _resolve_daily_range(
        days: int,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Tuple[datetime, datetime, int]:
        """解析日趋势的本地时间范围

        显式传 start_date/end_date（YYYY-MM-DD，含端点）时优先生效，
        否则回退"最近 days 天"。返回 (本地起点, 本地终点开区间, 天数)。
        """
        if start_date and end_date:
            if end_date < start_date:
                raise ValueError("end_date must be on or after start_date")
            sy, sm, sd = map(int, start_date.split("-"))
            ey, em, ed = map(int, end_date.split("-"))
            start_local = datetime(sy, sm, sd, 0, 0, 0, tzinfo=CHINA_TZ)
            end_local = datetime(ey, em, ed, 0, 0, 0, tzinfo=CHINA_TZ) + timedelta(days=1)
            num_days = (end_local - start_local).days
            if num_days > 366:
                raise ValueError("Date range too large (max 366 days)")
        else:
            now_local = datetime.now(CHINA_TZ)
            end_local = (now_local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            start_local = (now_local - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
            num_days = days
        return start_local, end_local, num_days

    @staticmethod
    def get_monthly_stats(
        session: Session,
        month: str,
        dimension: str = "model",
        use_requests: bool = False,
        group_id: int | None = None
    ) -> MonthlyStatsResponse:
        """
        Get monthly statistics grouped by dimension

        Args:
            session: Database session
            month: Month in YYYY-MM format
            dimension: Dimension to group by (model, group, module)
            use_requests: If True, show request counts instead of costs

        Returns:
            MonthlyStatsResponse with chart data and legend
        """
        try:
            # Parse month
            year, month_num = map(int, month.split("-"))
            days_in_month = monthrange(year, month_num)[1]

            # Date range (local time converted to UTC for query)
            local_start = datetime(year, month_num, 1, tzinfo=CHINA_TZ)
            local_end = datetime(year, month_num, days_in_month, tzinfo=CHINA_TZ) + timedelta(days=1)
            start_date = local_start.astimezone(timezone.utc).replace(tzinfo=None)
            end_date = local_end.astimezone(timezone.utc).replace(tzinfo=None)

            # Convert created_at to local time for grouping
            local_created_at = func.convert_tz(AIRequest.created_at, '+00:00', '+08:00')

            # Get dimension field
            if dimension == "model":
                dim_field = AIRequest.model
            elif dimension == "module":
                dim_field = AIRequest.module_name
            elif dimension == "group":
                # For group dimension, we need to join with user_group_members
                return DashboardService._get_monthly_stats_by_group(
                    session, month, year, month_num, days_in_month, start_date, end_date,
                    use_requests, group_id
                )
            else:
                dim_field = AIRequest.model

            conditions = [
                AIRequest.created_at >= start_date,
                AIRequest.created_at < end_date,
            ]
            if group_id is not None:
                conditions.append(DashboardService._group_member_condition(session, group_id))

            # Query aggregated data by day and dimension
            query = select(
                extract('day', local_created_at).label('day'),
                dim_field.label('dimension'),
                func.sum(AIRequest.cost_cents).label('total_cost'),
                func.sum(AIRequest.total_tokens).label('total_tokens'),
                func.count(AIRequest.id).label('request_count')
            ).where(
                and_(*conditions)
            ).group_by(
                extract('day', local_created_at),
                dim_field
            )

            results = session.exec(query).all()

            # Process results into chart data
            return DashboardService._process_monthly_results(
                results, month, days_in_month, use_requests
            )

        except Exception as e:
            logger.error(f"Error getting monthly stats: {str(e)}", exc_info=True)
            raise

    @staticmethod
    def _get_monthly_stats_by_group(
        session: Session,
        month: str,
        year: int,
        month_num: int,
        days_in_month: int,
        start_date: datetime,
        end_date: datetime,
        use_requests: bool = False,
        group_id: int | None = None
    ) -> MonthlyStatsResponse:
        """Get monthly statistics grouped by selected user groups (direct members only)"""
        # Convert created_at to local time for grouping
        local_created_at = func.convert_tz(AIRequest.created_at, '+00:00', '+08:00')

        conditions = [
            AIRequest.created_at >= start_date,
            AIRequest.created_at < end_date,
        ]
        if group_id is not None:
            conditions.append(DashboardService._group_member_condition(session, group_id))

        query = select(
            extract('day', local_created_at).label('day'),
            UserGroup.name.label('dimension'),
            func.sum(AIRequest.cost_cents).label('total_cost'),
            func.sum(AIRequest.total_tokens).label('total_tokens'),
            func.count(AIRequest.id).label('request_count')
        ).join(
            UserGroupMember, UserGroupMember.user_id == AIRequest.user_id
        ).join(
            StatGroupSelection, StatGroupSelection.user_group_id == UserGroupMember.group_id
        ).join(
            UserGroup, UserGroup.id == UserGroupMember.group_id
        ).where(
            and_(*conditions)
        ).group_by(
            extract('day', local_created_at),
            UserGroup.name
        )

        results = session.exec(query).all()
        return DashboardService._process_monthly_results(results, month, days_in_month, use_requests)

    @staticmethod
    def _merge_small_dimensions(
        dimension_totals: Dict[str, Dict[str, float]],
        period_data: Dict[str, Dict[str, float]]
    ) -> None:
        """把期间请求数低于阈值的维度合并为 OTHER_DIMENSION（原地修改两个字典）"""
        small = [
            name for name, totals in dimension_totals.items()
            if name != OTHER_DIMENSION and totals['requests'] < OTHER_MERGE_THRESHOLD
        ]
        if not small:
            return

        merged = dimension_totals.setdefault(OTHER_DIMENSION, {'cost': 0, 'tokens': 0, 'requests': 0})
        for name in small:
            totals = dimension_totals.pop(name)
            merged['cost'] += totals['cost']
            merged['tokens'] += totals['tokens']
            merged['requests'] += totals['requests']

        for values in period_data.values():
            other_value = values.get(OTHER_DIMENSION, 0)
            for name in small:
                other_value += values.pop(name, 0)
            if other_value:
                values[OTHER_DIMENSION] = other_value

    @staticmethod
    def _process_monthly_results(
        results: List[Tuple],
        month: str,
        days_in_month: int,
        use_requests: bool = False
    ) -> MonthlyStatsResponse:
        """Process query results into MonthlyStatsResponse"""
        # Collect all dimensions and their totals
        dimension_totals: Dict[str, Dict[str, float]] = {}
        day_data: Dict[str, Dict[str, float]] = {}

        total_cost = 0.0
        total_tokens = 0
        total_requests = 0

        for row in results:
            day = str(int(row.day))  # Convert to string (extract returns int)
            dim_name = row.dimension or 'unknown'
            cost = float(row.total_cost or 0) / 10000  # Convert to CNY
            tokens = int(row.total_tokens or 0)
            requests = int(row.request_count or 0)

            # Accumulate dimension totals
            if dim_name not in dimension_totals:
                dimension_totals[dim_name] = {'cost': 0, 'tokens': 0, 'requests': 0}
            dimension_totals[dim_name]['cost'] += cost
            dimension_totals[dim_name]['tokens'] += tokens
            dimension_totals[dim_name]['requests'] += requests

            # Accumulate day data (use requests or cost based on flag)
            if day not in day_data:
                day_data[day] = {}
            day_data[day][dim_name] = requests if use_requests else cost

            # Accumulate totals
            total_cost += cost
            total_tokens += tokens
            total_requests += requests

        DashboardService._merge_small_dimensions(dimension_totals, day_data)

        # Sort dimensions by the selected metric
        sort_key = 'requests' if use_requests else 'cost'
        sorted_dims = sorted(
            dimension_totals.items(),
            key=lambda x: x[1][sort_key],
            reverse=True
        )
        # “其他”固定排在图例末尾
        sorted_dims.sort(key=lambda x: x[0] == OTHER_DIMENSION)

        # Build dimension keys (top dimensions)
        dimension_keys = [dim for dim, _ in sorted_dims]

        # Build legend items
        legend_items = []
        total_metric = total_requests if use_requests else total_cost
        for idx, (dim_name, totals) in enumerate(sorted_dims):
            metric_value = totals['requests'] if use_requests else totals['cost']
            percentage = (metric_value / total_metric * 100) if total_metric > 0 else 0
            legend_items.append(LegendItem(
                name=dim_name,
                value=round(metric_value, 2) if not use_requests else int(metric_value),
                percentage=round(percentage, 1),
                color=get_color(idx)
            ))

        # Build chart data (one entry per day)
        chart_data = []
        for day in range(1, days_in_month + 1):
            day_str = str(day)
            data_point = {'label': f"{month.split('-')[1]}月{day}日"}

            for dim_name in dimension_keys:
                value = day_data.get(day_str, {}).get(dim_name, 0)
                data_point[dim_name] = int(value) if use_requests else round(value, 2)

            chart_data.append(data_point)

        return MonthlyStatsResponse(
            month=month,
            total_cost=round(total_cost, 2),
            total_requests=total_requests,
            total_tokens=total_tokens,
            chart_data=chart_data,
            legend_items=legend_items,
            dimension_keys=dimension_keys
        )

    @staticmethod
    def _daily_buckets(date: str, end_date: str | None) -> List[Tuple[str, str]]:
        """构建日度图表桶：单日按 24 小时，跨天按自然日（键与显示标签）"""
        if not end_date or end_date == date:
            return [(f"{hour:02d}", f"{hour:02d}:00") for hour in range(24)]
        start = datetime.strptime(date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
        buckets = []
        current = start
        while current <= end:
            key = current.strftime("%m-%d")
            buckets.append((key, key))
            current += timedelta(days=1)
        return buckets

    @staticmethod
    def get_daily_stats(
        session: Session,
        date: str,
        dimension: str = "model",
        use_requests: bool = False,
        end_date: str | None = None,
        group_id: int | None = None
    ) -> DailyStatsResponse:
        """
        Get daily statistics grouped by dimension

        Args:
            session: Database session
            date: Date in YYYY-MM-DD format (range start when end_date is given)
            dimension: Dimension to group by (model, group, module)
            use_requests: If True, show request counts instead of costs
            end_date: Optional range end in YYYY-MM-DD format (inclusive);
                multi-day ranges are bucketed by day instead of hour

        Returns:
            DailyStatsResponse with chart data and legend
        """
        try:
            # Parse date
            year, month, day = map(int, date.split("-"))
            multi_day = bool(end_date) and end_date != date

            # Date range (local time converted to UTC for query)
            local_start = datetime(year, month, day, 0, 0, 0, tzinfo=CHINA_TZ)
            if multi_day:
                end_year, end_month, end_day = map(int, end_date.split("-"))
                local_end = datetime(end_year, end_month, end_day, 0, 0, 0, tzinfo=CHINA_TZ) + timedelta(days=1)
                if local_end <= local_start:
                    raise ValueError("end_date must be on or after date")
            else:
                local_end = local_start + timedelta(days=1)
            start_date = local_start.astimezone(timezone.utc).replace(tzinfo=None)
            end_utc = local_end.astimezone(timezone.utc).replace(tzinfo=None)

            # Convert created_at to local time for grouping
            local_created_at = func.convert_tz(AIRequest.created_at, '+00:00', '+08:00')
            bucket_expr = func.date_format(local_created_at, '%m-%d' if multi_day else '%H')
            buckets = DashboardService._daily_buckets(date, end_date)

            # Get dimension field
            if dimension == "model":
                dim_field = AIRequest.model
            elif dimension == "module":
                dim_field = AIRequest.module_name
            elif dimension == "group":
                return DashboardService._get_daily_stats_by_group(
                    session, date, start_date, end_utc, use_requests, bucket_expr, buckets,
                    multi_day, group_id
                )
            else:
                dim_field = AIRequest.model

            conditions = [
                AIRequest.created_at >= start_date,
                AIRequest.created_at < end_utc,
            ]
            if group_id is not None:
                conditions.append(DashboardService._group_member_condition(session, group_id))

            # Query aggregated data by bucket and dimension
            query = select(
                bucket_expr.label('bucket'),
                dim_field.label('dimension'),
                func.sum(AIRequest.cost_cents).label('total_cost'),
                func.sum(AIRequest.total_tokens).label('total_tokens'),
                func.count(AIRequest.id).label('request_count')
            ).where(
                and_(*conditions)
            ).group_by(
                bucket_expr,
                dim_field
            )

            results = session.exec(query).all()
            return DashboardService._process_daily_results(results, date, use_requests, buckets, multi_day)

        except Exception as e:
            logger.error(f"Error getting daily stats: {str(e)}", exc_info=True)
            raise

    @staticmethod
    def _get_daily_stats_by_group(
        session: Session,
        date: str,
        start_date: datetime,
        end_date: datetime,
        use_requests: bool,
        bucket_expr,
        buckets: List[Tuple[str, str]],
        merge_small: bool = False,
        group_id: int | None = None
    ) -> DailyStatsResponse:
        """Get daily statistics grouped by selected user groups (direct members only)"""
        conditions = [
            AIRequest.created_at >= start_date,
            AIRequest.created_at < end_date,
        ]
        if group_id is not None:
            conditions.append(DashboardService._group_member_condition(session, group_id))

        query = select(
            bucket_expr.label('bucket'),
            UserGroup.name.label('dimension'),
            func.sum(AIRequest.cost_cents).label('total_cost'),
            func.sum(AIRequest.total_tokens).label('total_tokens'),
            func.count(AIRequest.id).label('request_count')
        ).join(
            UserGroupMember, UserGroupMember.user_id == AIRequest.user_id
        ).join(
            StatGroupSelection, StatGroupSelection.user_group_id == UserGroupMember.group_id
        ).join(
            UserGroup, UserGroup.id == UserGroupMember.group_id
        ).where(
            and_(*conditions)
        ).group_by(
            bucket_expr,
            UserGroup.name
        )

        results = session.exec(query).all()
        return DashboardService._process_daily_results(results, date, use_requests, buckets, merge_small)

    @staticmethod
    def _process_daily_results(
        results: List[Tuple],
        date: str,
        use_requests: bool,
        buckets: List[Tuple[str, str]],
        merge_small: bool = False
    ) -> DailyStatsResponse:
        """Process query results into DailyStatsResponse"""
        dimension_totals: Dict[str, Dict[str, float]] = {}
        bucket_data: Dict[str, Dict[str, float]] = {}

        total_cost = 0.0
        total_tokens = 0
        total_requests = 0

        for row in results:
            bucket = str(row.bucket)
            dim_name = row.dimension or 'unknown'
            cost = float(row.total_cost or 0) / 10000
            tokens = int(row.total_tokens or 0)
            requests = int(row.request_count or 0)

            if dim_name not in dimension_totals:
                dimension_totals[dim_name] = {'cost': 0, 'tokens': 0, 'requests': 0}
            dimension_totals[dim_name]['cost'] += cost
            dimension_totals[dim_name]['tokens'] += tokens
            dimension_totals[dim_name]['requests'] += requests

            if bucket not in bucket_data:
                bucket_data[bucket] = {}
            bucket_data[bucket][dim_name] = requests if use_requests else cost

            total_cost += cost
            total_tokens += tokens
            total_requests += requests

        if merge_small:
            DashboardService._merge_small_dimensions(dimension_totals, bucket_data)

        # Sort dimensions by the selected metric
        sort_key = 'requests' if use_requests else 'cost'
        sorted_dims = sorted(
            dimension_totals.items(),
            key=lambda x: x[1][sort_key],
            reverse=True
        )
        # “其他”固定排在图例末尾
        sorted_dims.sort(key=lambda x: x[0] == OTHER_DIMENSION)

        dimension_keys = [dim for dim, _ in sorted_dims]

        # Build legend items
        legend_items = []
        total_metric = total_requests if use_requests else total_cost
        for idx, (dim_name, totals) in enumerate(sorted_dims):
            metric_value = totals['requests'] if use_requests else totals['cost']
            percentage = (metric_value / total_metric * 100) if total_metric > 0 else 0
            legend_items.append(LegendItem(
                name=dim_name,
                value=round(metric_value, 2) if not use_requests else int(metric_value),
                percentage=round(percentage, 1),
                color=get_color(idx)
            ))

        chart_data = []
        for bucket_key, bucket_label in buckets:
            data_point = {'label': bucket_label}

            for dim_name in dimension_keys:
                value = bucket_data.get(bucket_key, {}).get(dim_name, 0)
                data_point[dim_name] = int(value) if use_requests else round(value, 2)

            chart_data.append(data_point)

        return DailyStatsResponse(
            date=date,
            total_cost=round(total_cost, 2),
            total_requests=total_requests,
            total_tokens=total_tokens,
            chart_data=chart_data,
            legend_items=legend_items,
            dimension_keys=dimension_keys
        )

    @staticmethod
    def get_user_ranking(
        session: Session,
        start_date: str,
        end_date: str,
        limit: int = 10,
        module: str | None = None,
        sort_by: str = "requests",
        group_id: int | None = None
    ) -> RankingResponse:
        """
        Get user ranking by cost

        Args:
            session: Database session
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            limit: Number of items to return
            module: Optional module name to filter by
            sort_by: Sort by "requests", "cost" or "tokens"
            group_id: Optional user group id; only rank direct members of the group

        Returns:
            RankingResponse with user ranking
        """
        try:
            # Parse dates and convert local time to UTC
            start_local = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=CHINA_TZ)
            end_local = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=CHINA_TZ)
            start = start_local.astimezone(timezone.utc).replace(tzinfo=None)
            end = (end_local + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None)

            # Build base conditions
            conditions = [
                AIRequest.created_at >= start,
                AIRequest.created_at < end
            ]
            if module:
                conditions.append(AIRequest.module_name == module)
            if group_id is not None:
                conditions.append(DashboardService._group_member_condition(session, group_id))

            # Determine sort order
            if sort_by == "tokens":
                order_by_field = func.sum(AIRequest.total_tokens)
            elif sort_by == "cost":
                order_by_field = func.sum(AIRequest.cost_cents)
            else:
                order_by_field = func.count(AIRequest.id)

            # Query user statistics
            query = select(
                AIRequest.user_id,
                User.username,
                User.nickname,
                User.avatar_url,
                func.sum(AIRequest.cost_cents).label('total_cost'),
                func.sum(AIRequest.total_tokens).label('total_tokens'),
                func.count(AIRequest.id).label('request_count')
            ).join(
                User, User.id == AIRequest.user_id
            ).where(
                and_(*conditions)
            ).group_by(
                AIRequest.user_id,
                User.username,
                User.nickname,
                User.avatar_url
            ).order_by(
                order_by_field.desc()
            ).limit(limit)

            results = session.exec(query).all()

            # Get total count
            count_query = select(
                func.count(func.distinct(AIRequest.user_id))
            ).where(
                and_(*conditions)
            )
            total_count = session.exec(count_query).one() or 0

            items = []
            for idx, row in enumerate(results):
                items.append(RankingItem(
                    rank=idx + 1,
                    id=row.user_id,
                    name=row.nickname or row.username,
                    avatar_url=row.avatar_url,
                    request_count=int(row.request_count or 0),
                    total_tokens=int(row.total_tokens or 0),
                    total_cost=round(float(row.total_cost or 0) / 10000, 2)
                ))

            return RankingResponse(items=items, total_count=total_count)

        except Exception as e:
            logger.error(f"Error getting user ranking: {str(e)}", exc_info=True)
            raise

    @staticmethod
    def get_group_ranking(
        session: Session,
        start_date: str,
        end_date: str,
        limit: int = 10,
        module: str | None = None,
        sort_by: str = "requests"
    ) -> RankingResponse:
        """
        Get group ranking by cost

        Args:
            session: Database session
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            limit: Number of items to return
            module: Optional module name to filter by
            sort_by: Sort by "requests", "cost" or "tokens"

        Returns:
            RankingResponse with group ranking
        """
        try:
            # Parse dates and convert local time to UTC
            start_local = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=CHINA_TZ)
            end_local = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=CHINA_TZ)
            start = start_local.astimezone(timezone.utc).replace(tzinfo=None)
            end = (end_local + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None)

            # Build base conditions
            conditions = [
                AIRequest.created_at >= start,
                AIRequest.created_at < end,
            ]
            if module:
                conditions.append(AIRequest.module_name == module)

            # Determine sort order
            if sort_by == "tokens":
                order_by_field = func.sum(AIRequest.total_tokens)
            elif sort_by == "cost":
                order_by_field = func.sum(AIRequest.cost_cents)
            else:
                order_by_field = func.count(AIRequest.id)

            # Query group statistics
            query = select(
                UserGroup.id,
                UserGroup.name,
                func.sum(AIRequest.cost_cents).label('total_cost'),
                func.sum(AIRequest.total_tokens).label('total_tokens'),
                func.count(AIRequest.id).label('request_count')
            ).select_from(StatGroupSelection).join(
                UserGroup, UserGroup.id == StatGroupSelection.user_group_id
            ).join(
                UserGroupMember, UserGroupMember.group_id == UserGroup.id
            ).join(
                AIRequest, AIRequest.user_id == UserGroupMember.user_id
            ).where(
                and_(*conditions)
            ).group_by(
                UserGroup.id,
                UserGroup.name
            ).order_by(
                order_by_field.desc()
            ).limit(limit)

            results = session.exec(query).all()

            # Get total count
            count_query = select(
                func.count(func.distinct(UserGroup.id))
            ).select_from(StatGroupSelection).join(
                UserGroup, UserGroup.id == StatGroupSelection.user_group_id
            ).join(
                UserGroupMember, UserGroupMember.group_id == UserGroup.id
            ).join(
                AIRequest, AIRequest.user_id == UserGroupMember.user_id
            ).where(
                and_(*conditions)
            )
            total_count = session.exec(count_query).one() or 0

            items = []
            for idx, row in enumerate(results):
                items.append(RankingItem(
                    rank=idx + 1,
                    id=row.id,
                    name=row.name,
                    avatar_url=None,
                    request_count=int(row.request_count or 0),
                    total_tokens=int(row.total_tokens or 0),
                    total_cost=round(float(row.total_cost or 0) / 10000, 2)
                ))

            return RankingResponse(items=items, total_count=total_count)

        except Exception as e:
            logger.error(f"Error getting group ranking: {str(e)}", exc_info=True)
            raise

    @staticmethod
    def get_daily_overview(
        session: Session,
        date: str,
        end_date: str | None = None,
        group_id: int | None = None
    ) -> DailyOverviewResponse:
        """
        Get daily overview statistics

        Args:
            session: Database session
            date: Date in YYYY-MM-DD format (range start when end_date is given)
            end_date: Optional range end in YYYY-MM-DD format (inclusive)

        Returns:
            DailyOverviewResponse with unique users, total requests, tokens, and success rate
        """
        try:
            # Parse date and convert local time to UTC
            year, month, day = map(int, date.split("-"))
            local_start = datetime(year, month, day, 0, 0, 0, tzinfo=CHINA_TZ)
            if end_date:
                if end_date < date:
                    raise ValueError("end_date must be on or after date")
                ey, em, ed = map(int, end_date.split("-"))
                local_end = datetime(ey, em, ed, 0, 0, 0, tzinfo=CHINA_TZ) + timedelta(days=1)
            else:
                local_end = local_start + timedelta(days=1)
            utc_start = local_start.astimezone(timezone.utc).replace(tzinfo=None)
            utc_end = local_end.astimezone(timezone.utc).replace(tzinfo=None)

            # Query aggregated statistics
            conditions = [
                AIRequest.created_at >= utc_start,
                AIRequest.created_at < utc_end,
            ]
            if group_id is not None:
                conditions.append(DashboardService._group_member_condition(session, group_id))

            query = select(
                func.count(func.distinct(AIRequest.user_id)).label('unique_users'),
                func.count(AIRequest.id).label('total_requests'),
                func.sum(AIRequest.total_tokens).label('total_tokens'),
                func.sum(case((AIRequest.success == True, 1), else_=0)).label('success_count'),
                func.sum(AIRequest.cost_cents).label('total_cost_cents')
            ).where(
                and_(*conditions)
            )

            result = session.exec(query).one()

            unique_users = int(result.unique_users or 0)
            total_requests = int(result.total_requests or 0)
            total_tokens = int(result.total_tokens or 0)
            success_count = int(result.success_count or 0)
            total_cost = float(result.total_cost_cents or 0) / 10000

            # Credits 口径与成本不同：来自 consume 流水实扣金额，独立聚合
            tx_conditions = [
                CreditTransaction.type == "consume",
                CreditTransaction.created_at >= utc_start,
                CreditTransaction.created_at < utc_end,
            ]
            if group_id is not None:
                group_ids = DashboardService.expand_group_ids(session, group_id)
                tx_conditions.append(CreditTransaction.user_id.in_(
                    select(UserGroupMember.user_id).where(UserGroupMember.group_id.in_(group_ids))
                ))
            credit_sum = session.exec(
                select(func.sum(CreditTransaction.amount)).where(and_(*tx_conditions))
            ).one()
            total_credits = abs(float(credit_sum or 0)) / 1_000_000

            # Calculate success rate
            success_rate = (success_count / total_requests * 100) if total_requests > 0 else 100.0

            return DailyOverviewResponse(
                date=date,
                unique_users=unique_users,
                total_requests=total_requests,
                total_tokens=total_tokens,
                success_rate=round(success_rate, 1),
                total_cost=round(total_cost, 2),
                total_credits=round(total_credits, 2)
            )

        except Exception as e:
            logger.error(f"Error getting daily overview: {str(e)}", exc_info=True)
            raise

    @staticmethod
    def get_model_token_stats(
        session: Session,
        date: str,
        end_date: str | None = None,
        group_id: int | None = None
    ) -> ModelTokenStatsResponse:
        """
        Get per-model token consumption for a date range

        Args:
            session: Database session
            date: Date in YYYY-MM-DD format (range start when end_date is given)
            end_date: Optional range end in YYYY-MM-DD format (inclusive)
            group_id: Optional user group id (includes descendant groups)

        Returns:
            ModelTokenStatsResponse with per-model breakdown sorted by tokens desc
        """
        try:
            year, month, day = map(int, date.split("-"))
            local_start = datetime(year, month, day, 0, 0, 0, tzinfo=CHINA_TZ)
            if end_date:
                if end_date < date:
                    raise ValueError("end_date must be on or after date")
                ey, em, ed = map(int, end_date.split("-"))
                local_end = datetime(ey, em, ed, 0, 0, 0, tzinfo=CHINA_TZ) + timedelta(days=1)
            else:
                local_end = local_start + timedelta(days=1)
            utc_start = local_start.astimezone(timezone.utc).replace(tzinfo=None)
            utc_end = local_end.astimezone(timezone.utc).replace(tzinfo=None)

            conditions = [
                AIRequest.created_at >= utc_start,
                AIRequest.created_at < utc_end,
            ]
            if group_id is not None:
                conditions.append(DashboardService._group_member_condition(session, group_id))

            query = select(
                AIRequest.model.label('model'),
                func.count(AIRequest.id).label('request_count'),
                func.sum(AIRequest.prompt_tokens).label('prompt_tokens'),
                func.sum(AIRequest.completion_tokens).label('completion_tokens'),
                func.sum(AIRequest.total_tokens).label('total_tokens'),
            ).where(
                and_(*conditions)
            ).group_by(
                AIRequest.model
            ).order_by(
                func.sum(AIRequest.total_tokens).desc()
            )
            rows = session.exec(query).all()

            grand_total = sum(int(row.total_tokens or 0) for row in rows)
            items = [
                ModelTokenStatItem(
                    model=row.model or "未知",
                    request_count=int(row.request_count or 0),
                    prompt_tokens=int(row.prompt_tokens or 0),
                    completion_tokens=int(row.completion_tokens or 0),
                    total_tokens=int(row.total_tokens or 0),
                    percentage=round(int(row.total_tokens or 0) / grand_total * 100, 1) if grand_total else 0.0,
                )
                for row in rows
            ]
            return ModelTokenStatsResponse(date=date, total_tokens=grand_total, items=items)

        except Exception as e:
            logger.error(f"Error getting model token stats: {str(e)}", exc_info=True)
            raise

    @staticmethod
    def get_trend_stats(
        session: Session,
        days: int = 30,
        metric: str = "users",
        module: str | None = None,
        group_id: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None
    ) -> TrendStatsResponse:
        """
        Get trend statistics for the last N days or an explicit date range

        Args:
            session: Database session
            days: Number of days to look back (default 30, ignored when start/end given)
            metric: Metric type (users, requests, tokens, success_rate)
            module: Optional module name to filter by
            start_date: Optional range start in YYYY-MM-DD format (inclusive)
            end_date: Optional range end in YYYY-MM-DD format (inclusive)

        Returns:
            TrendStatsResponse with daily data points
        """
        try:
            start_local, end_local, num_days = DashboardService._resolve_daily_range(
                days, start_date, end_date
            )
            utc_range_start = start_local.astimezone(timezone.utc).replace(tzinfo=None)
            utc_range_end = end_local.astimezone(timezone.utc).replace(tzinfo=None)

            # Convert created_at to local time for grouping
            local_created_at = func.convert_tz(AIRequest.created_at, '+00:00', '+08:00')
            day_expr = func.date(local_created_at)

            # Build base conditions
            conditions = [
                AIRequest.created_at >= utc_range_start,
                AIRequest.created_at < utc_range_end
            ]
            if module:
                conditions.append(AIRequest.module_name == module)
            if group_id is not None:
                conditions.append(DashboardService._group_member_condition(session, group_id))

            # Build query based on metric type
            if metric == "users":
                query = select(
                    day_expr.label('day'),
                    func.count(func.distinct(AIRequest.user_id)).label('value')
                ).where(
                    and_(*conditions)
                ).group_by(day_expr)
            elif metric == "requests":
                query = select(
                    day_expr.label('day'),
                    func.count(AIRequest.id).label('value')
                ).where(
                    and_(*conditions)
                ).group_by(day_expr)
            elif metric == "tokens":
                query = select(
                    day_expr.label('day'),
                    func.sum(AIRequest.total_tokens).label('value')
                ).where(
                    and_(*conditions)
                ).group_by(day_expr)
            elif metric == "success_rate":
                query = select(
                    day_expr.label('day'),
                    (func.sum(case((AIRequest.success == True, 1), else_=0)) * 100.0
                     / func.count(AIRequest.id)).label('value')
                ).where(
                    and_(*conditions)
                ).group_by(day_expr)
            else:
                raise ValueError(f"Invalid metric: {metric}")

            results = session.exec(query).all()

            # Build a map of date -> value
            day_values: Dict[str, float] = {}
            for row in results:
                day_str = str(row.day)
                day_values[day_str] = float(row.value or 0)

            # Build data points for each day (fill missing days with 0)
            data = []
            for i in range(num_days):
                current_date = start_local + timedelta(days=i)
                date_key = current_date.strftime("%Y-%m-%d")
                date_label = f"{current_date.month}月{current_date.day}日"
                value = day_values.get(date_key, 0.0)

                if metric == "success_rate":
                    value = round(value, 1)
                elif metric == "tokens":
                    value = int(value)
                else:
                    value = int(value)

                data.append(TrendDataPoint(date=date_label, value=value))

            return TrendStatsResponse(
                metric=metric,
                days=num_days,
                data=data
            )

        except Exception as e:
            logger.error(f"Error getting trend stats: {str(e)}", exc_info=True)
            raise

    @staticmethod
    def get_cost_trend_stats(
        session: Session,
        days: int = 30,
        group_id: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None
    ) -> CostTrendStatsResponse:
        """
        Get daily cost (CNY) and credits consumption trend

        成本来自 AIRequest.cost_cents（÷10000 = 元），Credits 来自 consume
        流水实扣金额（÷CREDIT_UNIT），两者口径不同，分别独立按天聚合。
        显式传 start_date/end_date 时优先生效，否则回退最近 days 天。
        """
        try:
            start_local, end_local, num_days = DashboardService._resolve_daily_range(
                days, start_date, end_date
            )
            utc_range_start = start_local.astimezone(timezone.utc).replace(tzinfo=None)
            utc_range_end = end_local.astimezone(timezone.utc).replace(tzinfo=None)

            member_select = None
            if group_id is not None:
                group_ids = DashboardService.expand_group_ids(session, group_id)
                member_select = select(UserGroupMember.user_id).where(
                    UserGroupMember.group_id.in_(group_ids)
                )

            req_day = func.date(func.convert_tz(AIRequest.created_at, '+00:00', '+08:00'))
            req_conditions = [
                AIRequest.created_at >= utc_range_start,
                AIRequest.created_at < utc_range_end,
            ]
            if member_select is not None:
                req_conditions.append(AIRequest.user_id.in_(member_select))
            cost_rows = session.exec(
                select(req_day.label('day'), func.sum(AIRequest.cost_cents).label('value'))
                .where(and_(*req_conditions))
                .group_by(req_day)
            ).all()

            tx_day = func.date(func.convert_tz(CreditTransaction.created_at, '+00:00', '+08:00'))
            tx_conditions = [
                CreditTransaction.type == "consume",
                CreditTransaction.created_at >= utc_range_start,
                CreditTransaction.created_at < utc_range_end,
            ]
            if member_select is not None:
                tx_conditions.append(CreditTransaction.user_id.in_(member_select))
            credit_rows = session.exec(
                select(tx_day.label('day'), func.sum(CreditTransaction.amount).label('value'))
                .where(and_(*tx_conditions))
                .group_by(tx_day)
            ).all()

            cost_map = {str(row.day): float(row.value or 0) for row in cost_rows}
            credit_map = {str(row.day): float(row.value or 0) for row in credit_rows}

            data = []
            for i in range(num_days):
                current_date = start_local + timedelta(days=i)
                date_key = current_date.strftime("%Y-%m-%d")
                date_label = f"{current_date.month}月{current_date.day}日"
                data.append(CostTrendDataPoint(
                    date=date_label,
                    cost=round(cost_map.get(date_key, 0.0) / 10000, 2),
                    credits=round(abs(credit_map.get(date_key, 0.0)) / 1_000_000, 2),
                ))

            return CostTrendStatsResponse(days=num_days, data=data)

        except Exception as e:
            logger.error(f"Error getting cost trend stats: {str(e)}", exc_info=True)
            raise

    @staticmethod
    def _aggregate_request_stats(
        session: Session,
        conditions: List[Any],
        start_local: datetime,
        end_local: datetime,
        is_single_day: bool
    ) -> Dict[str, Any]:
        """聚合一组请求条件下的总量、模块/模型分布与趋势数据（用户/分组详情共用）"""
        # Overview: total requests, cost, tokens, success rate
        overview_query = select(
            func.count(AIRequest.id).label('total_requests'),
            func.sum(AIRequest.cost_cents).label('total_cost'),
            func.sum(AIRequest.total_tokens).label('total_tokens'),
            func.sum(case((AIRequest.success == True, 1), else_=0)).label('success_count')
        ).where(and_(*conditions))

        overview = session.exec(overview_query).one()
        total_requests = int(overview.total_requests or 0)
        total_cost_raw = float(overview.total_cost or 0)
        total_tokens = int(overview.total_tokens or 0)
        success_count = int(overview.success_count or 0)
        success_rate = (success_count / total_requests * 100) if total_requests > 0 else 100.0

        # Module breakdown
        module_query = select(
            AIRequest.module_name,
            func.count(AIRequest.id).label('request_count'),
            func.sum(AIRequest.cost_cents).label('cost')
        ).where(and_(*conditions)).group_by(
            AIRequest.module_name
        ).order_by(func.count(AIRequest.id).desc())

        module_results = session.exec(module_query).all()
        module_breakdown = []
        for idx, row in enumerate(module_results):
            pct = (int(row.request_count or 0) / total_requests * 100) if total_requests > 0 else 0
            module_breakdown.append(LegendItem(
                name=row.module_name or "unknown",
                value=int(row.request_count or 0),
                percentage=round(pct, 1),
                color=get_color(idx)
            ))

        # Model breakdown（按消耗 token 降序）
        model_query = select(
            AIRequest.model,
            func.count(AIRequest.id).label('request_count'),
            func.sum(AIRequest.cost_cents).label('cost'),
            func.sum(AIRequest.total_tokens).label('tokens')
        ).where(and_(*conditions)).group_by(
            AIRequest.model
        ).order_by(func.sum(AIRequest.total_tokens).desc())

        model_results = session.exec(model_query).all()
        model_breakdown = []
        for idx, row in enumerate(model_results):
            pct = (int(row.request_count or 0) / total_requests * 100) if total_requests > 0 else 0
            model_breakdown.append(LegendItem(
                name=row.model or "unknown",
                value=int(row.request_count or 0),
                percentage=round(pct, 1),
                color=get_color(idx),
                tokens=int(row.tokens or 0)
            ))

        # Trend chart data: per-model breakdown over time
        local_created_at = func.convert_tz(AIRequest.created_at, '+00:00', '+08:00')

        # Use model_breakdown order (sorted by request count desc) for dimension keys
        trend_dimension_keys = [item.name for item in model_breakdown]

        if is_single_day:
            # Single day: group by hour
            hour_expr = extract('hour', local_created_at)
            trend_query = select(
                hour_expr.label('hour'),
                AIRequest.model,
                func.count(AIRequest.id).label('count')
            ).where(and_(*conditions)).group_by(hour_expr, AIRequest.model)

            trend_results = session.exec(trend_query).all()

            # Build hour->model->count map
            hour_model_map: Dict[int, Dict[str, int]] = {}
            for row in trend_results:
                h = int(row.hour)
                model_name = row.model or "unknown"
                if h not in hour_model_map:
                    hour_model_map[h] = {}
                hour_model_map[h][model_name] = int(row.count or 0)

            # Fill all 24 hours
            trend_chart_data: List[Dict[str, Any]] = []
            for h in range(24):
                point: Dict[str, Any] = {"label": f"{h}:00"}
                hour_data = hour_model_map.get(h, {})
                for model_key in trend_dimension_keys:
                    point[model_key] = hour_data.get(model_key, 0)
                trend_chart_data.append(point)
        else:
            # Multi-day: group by date
            day_expr = func.date(local_created_at)
            trend_query = select(
                day_expr.label('day'),
                AIRequest.model,
                func.count(AIRequest.id).label('count')
            ).where(and_(*conditions)).group_by(day_expr, AIRequest.model)

            trend_results = session.exec(trend_query).all()

            # Build day->model->count map
            day_model_map: Dict[str, Dict[str, int]] = {}
            for row in trend_results:
                day_str = str(row.day)
                model_name = row.model or "unknown"
                if day_str not in day_model_map:
                    day_model_map[day_str] = {}
                day_model_map[day_str][model_name] = int(row.count or 0)

            # Fill all days
            total_days = (end_local - start_local).days + 1
            # Use short label for ranges > 7 days
            use_short_label = total_days > 7

            trend_chart_data: List[Dict[str, Any]] = []
            current = start_local
            while current <= end_local:
                date_key = current.strftime("%Y-%m-%d")
                date_label = f"{current.month}/{current.day}" if use_short_label else f"{current.month}月{current.day}日"
                point: Dict[str, Any] = {"label": date_label}
                day_data = day_model_map.get(date_key, {})
                for model_key in trend_dimension_keys:
                    point[model_key] = day_data.get(model_key, 0)
                trend_chart_data.append(point)
                current += timedelta(days=1)

        # Build daily cost trend for multi-day (area chart)
        daily_total_trend: List[TrendDataPoint] = []
        if not is_single_day:
            cost_trend_query = select(
                func.date(local_created_at).label('day'),
                func.sum(AIRequest.cost_cents).label('cost')
            ).where(and_(*conditions)).group_by(func.date(local_created_at))
            cost_trend_results = {str(row.day): float(row.cost or 0) for row in session.exec(cost_trend_query).all()}

            current = start_local
            while current <= end_local:
                date_key = current.strftime("%Y-%m-%d")
                date_label = f"{current.month}/{current.day}" if use_short_label else f"{current.month}月{current.day}日"
                daily_cost = cost_trend_results.get(date_key, 0) / 10000
                daily_total_trend.append(TrendDataPoint(
                    date=date_label,
                    value=round(daily_cost, 2)
                ))
                current += timedelta(days=1)

        return {
            "total_requests": total_requests,
            "total_cost": round(total_cost_raw / 10000, 2),
            "total_tokens": total_tokens,
            "success_rate": round(success_rate, 1),
            "module_breakdown": module_breakdown,
            "model_breakdown": model_breakdown,
            "trend_chart_data": trend_chart_data,
            "trend_dimension_keys": trend_dimension_keys,
            "daily_total_trend": daily_total_trend,
        }

    @staticmethod
    def get_user_stats(
        session: Session,
        user_id: int,
        start_date: str,
        end_date: str
    ) -> UserStatsResponse:
        """
        Get detailed statistics for a specific user

        Args:
            session: Database session
            user_id: User ID
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format

        Returns:
            UserStatsResponse with per-user detailed statistics
        """
        try:
            # Parse dates and convert local time to UTC
            start_local = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=CHINA_TZ)
            end_local = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=CHINA_TZ)
            start = start_local.astimezone(timezone.utc).replace(tzinfo=None)
            end = (end_local + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None)

            # Get user info
            user = session.get(User, user_id)
            if not user:
                raise ValueError(f"User not found: {user_id}")

            # Get user group names (LDAP 同步分组仅作组织结构，抽屉只展示手工维护的自定义分组)
            group_query = select(UserGroup.name).join(
                UserGroupMember, UserGroupMember.group_id == UserGroup.id
            ).where(
                UserGroupMember.user_id == user_id,
                UserGroup.group_type == 'CUSTOM',
                UserGroup.name != '示例科技'
            )
            group_names = list(session.exec(group_query).all())

            # Base conditions
            conditions = [
                AIRequest.created_at >= start,
                AIRequest.created_at < end,
                AIRequest.user_id == user_id
            ]

            stats = DashboardService._aggregate_request_stats(
                session, conditions, start_local, end_local, start_date == end_date
            )
            total_credits = DashboardService._consume_credits_total(
                session, CreditTransaction.user_id == user_id, start, end
            )

            return UserStatsResponse(
                user_id=user_id,
                username=user.username,
                nickname=user.nickname,
                avatar_url=user.avatar_url,
                group_names=group_names,
                total_credits=total_credits,
                **stats
            )

        except Exception as e:
            logger.error(f"Error getting user stats: {str(e)}", exc_info=True)
            raise

    @staticmethod
    def get_group_stats(
        session: Session,
        group_id: int,
        start_date: str,
        end_date: str
    ) -> GroupStatsResponse:
        """
        Get detailed statistics for a user group

        统计口径与分组排行一致：仅计分组直属成员的请求。
        """
        try:
            start_local = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=CHINA_TZ)
            end_local = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=CHINA_TZ)
            start = start_local.astimezone(timezone.utc).replace(tzinfo=None)
            end = (end_local + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None)

            group = session.get(UserGroup, group_id)
            if not group:
                raise ValueError(f"Group not found: {group_id}")

            member_select = select(UserGroupMember.user_id).where(
                UserGroupMember.group_id == group_id
            )
            member_count = len(session.exec(member_select).all())

            conditions = [
                AIRequest.created_at >= start,
                AIRequest.created_at < end,
                AIRequest.user_id.in_(member_select)
            ]
            stats = DashboardService._aggregate_request_stats(
                session, conditions, start_local, end_local, start_date == end_date
            )
            total_credits = DashboardService._consume_credits_total(
                session, CreditTransaction.user_id.in_(member_select), start, end
            )

            return GroupStatsResponse(
                group_id=group_id,
                name=group.name,
                member_count=member_count,
                total_credits=total_credits,
                **stats
            )

        except Exception as e:
            logger.error(f"Error getting group stats: {str(e)}", exc_info=True)
            raise
