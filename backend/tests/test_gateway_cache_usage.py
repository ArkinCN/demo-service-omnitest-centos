from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.v1.gateway import _scan_usage_line
from app.api.v1.gateway_admin import (
    PricingRequest,
    _serialize_request_log,
    create_model,
    list_requests,
    update_model,
)
from app.db.session import _run_migrations
from app.models.ai_request import AIRequest
from app.models.credits import CreditTransaction
from app.models.gateway import ModelPricing
from app.models.user import User
from app.services.credits_service import CreditsService
from app.services.gateway_service import GatewayService


class _Result:
    def __init__(self, value=None):
        self.value = value

    def first(self):
        return self.value


class _PricingSession:
    def __init__(self, pricing):
        self.pricing = pricing

    def exec(self, _statement):
        return _Result(self.pricing)


class _AdminSession:
    def __init__(self, existing=None):
        self.existing = existing
        self.added = None

    def exec(self, _statement):
        return _Result(None)

    def get(self, _model, _pk):
        return self.existing

    def add(self, value):
        self.added = value

    def commit(self):
        pass

    def refresh(self, _value):
        pass


@pytest.mark.parametrize(
    ("protocol", "result", "expected"),
    [
        (
            "anthropic",
            {
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "cache_read_input_tokens": 50,
                    "cache_creation_input_tokens": 30,
                }
            },
            (180, 20, 50, 30),
        ),
        (
            "openai_chat",
            {
                "usage": {
                    "prompt_tokens": 180,
                    "completion_tokens": 20,
                    "prompt_tokens_details": {
                        "cached_tokens": 50,
                        "cache_write_tokens": 30,
                    },
                }
            },
            (180, 20, 50, 30),
        ),
        (
            "openai_responses",
            {
                "usage": {
                    "input_tokens": 180,
                    "output_tokens": 20,
                    "input_tokens_details": {
                        "cached_tokens": 50,
                        "cache_write_tokens": 30,
                    },
                }
            },
            (180, 20, 50, 30),
        ),
    ],
)
def test_parse_usage_maps_cache_creation(protocol, result, expected):
    assert GatewayService.parse_usage(result, protocol) == expected


def test_parse_usage_defaults_missing_cache_write_to_zero():
    result = {
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 10,
            "prompt_tokens_details": {"cached_tokens": 25},
        }
    }

    assert GatewayService.parse_usage(result, "openai_chat") == (100, 10, 25, 0)


def test_anthropic_stream_preserves_creation_across_usage_events():
    captured = {"pt": 0, "ct": 0, "input": 0, "cache": 0, "creation": 0}
    _scan_usage_line(
        'data: {"type":"message_start","message":{"usage":'
        '{"input_tokens":100,"cache_read_input_tokens":50,'
        '"cache_creation_input_tokens":30}}}',
        "anthropic",
        captured,
    )
    _scan_usage_line(
        'data: {"type":"message_delta","usage":{"output_tokens":20}}',
        "anthropic",
        captured,
    )

    assert captured == {
        "pt": 180,
        "ct": 20,
        "input": 100,
        "cache": 50,
        "creation": 30,
    }


def test_openai_responses_stream_reads_cache_write_tokens():
    captured = {"pt": 0, "ct": 0, "input": 0, "cache": 0, "creation": 0}
    _scan_usage_line(
        'data: {"type":"response.completed","response":{"usage":'
        '{"input_tokens":180,"output_tokens":20,"input_tokens_details":'
        '{"cached_tokens":50,"cache_write_tokens":30}}}}',
        "openai_responses",
        captured,
    )

    assert captured["pt"] == 180
    assert captured["ct"] == 20
    assert captured["cache"] == 50
    assert captured["creation"] == 30


def test_calc_consume_units_splits_regular_read_write_and_output():
    pricing = SimpleNamespace(
        model_id="test-model",
        is_active=True,
        in_rate=3.0,
        out_rate=15.0,
        cache_rate=0.3,
        cache_creation_rate=3.75,
        multiplier=1.0,
    )

    units, multiplier = CreditsService.calc_consume_units(
        _PricingSession(pricing),
        "test-model",
        prompt_tokens=180,
        completion_tokens=20,
        cache_read_tokens=50,
        cache_creation_tokens=30,
    )

    assert units == 728
    assert multiplier == 1.0


def test_calc_consume_units_preserves_old_price_when_creation_rate_equals_input():
    pricing = SimpleNamespace(
        model_id="test-model",
        is_active=True,
        in_rate=3.0,
        out_rate=15.0,
        cache_rate=0.3,
        cache_creation_rate=3.0,
        multiplier=1.0,
    )
    session = _PricingSession(pricing)

    units, _ = CreditsService.calc_consume_units(
        session,
        "test-model",
        prompt_tokens=180,
        completion_tokens=20,
        cache_read_tokens=50,
        cache_creation_tokens=30,
    )
    old_units = round(((180 - 50) * 3.0 + 50 * 0.3 + 20 * 15.0))

    assert units == old_units


@pytest.mark.asyncio
async def test_create_model_defaults_cache_creation_rate_to_input_rate():
    session = _AdminSession()

    await create_model(
        PricingRequest(model_id="test-model", in_rate=4.0),
        session=session,
        _=object(),
    )

    assert session.added.cache_creation_rate == 4.0


@pytest.mark.asyncio
async def test_update_model_preserves_or_explicitly_clears_cache_creation_rate():
    existing = ModelPricing(model_id="test-model", cache_creation_rate=4.0)
    session = _AdminSession(existing)

    await update_model(
        1,
        PricingRequest(model_id="test-model", cache_creation_rate=None),
        session=session,
        _=object(),
    )
    assert existing.cache_creation_rate == 4.0

    await update_model(
        1,
        PricingRequest(model_id="test-model", cache_creation_rate=0.0),
        session=session,
        _=object(),
    )
    assert existing.cache_creation_rate == 0.0


@pytest.mark.filterwarnings(
    "ignore:Could not instantiate type.*:sqlalchemy.exc.SAWarning"
)
def test_cache_creation_migration_backfills_once_and_preserves_explicit_zero():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE model_pricing (id INTEGER PRIMARY KEY, in_rate FLOAT NOT NULL)"
        ))
        conn.execute(text("INSERT INTO model_pricing (id, in_rate) VALUES (1, 4.0)"))
        conn.execute(text("CREATE TABLE ai_requests (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE credit_transactions (id INTEGER PRIMARY KEY)"))
        conn.execute(text(
            "CREATE TABLE feature_groups (group_key VARCHAR(50), i18n_key VARCHAR(100))"
        ))
        conn.execute(text(
            "CREATE TABLE feature_routes (route_path VARCHAR(100), i18n_key VARCHAR(100))"
        ))

    _run_migrations(engine)

    assert "cache_creation_rate" in {
        column["name"] for column in inspect(engine).get_columns("model_pricing")
    }
    assert {"cache_read_tokens", "cache_creation_tokens"}.issubset({
        column["name"] for column in inspect(engine).get_columns("ai_requests")
    })
    assert "cache_creation_tokens" in {
        column["name"] for column in inspect(engine).get_columns("credit_transactions")
    }
    with engine.begin() as conn:
        rate = conn.execute(text(
            "SELECT cache_creation_rate FROM model_pricing WHERE id = 1"
        )).scalar_one()
        assert rate == 4.0
        conn.execute(text(
            "UPDATE model_pricing SET cache_creation_rate = 0 WHERE id = 1"
        ))

    _run_migrations(engine)

    with engine.connect() as conn:
        rate = conn.execute(text(
            "SELECT cache_creation_rate FROM model_pricing WHERE id = 1"
        )).scalar_one()
    assert rate == 0.0


def test_cache_read_migration_backfills_from_consume_transactions():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE model_pricing (id INTEGER PRIMARY KEY, in_rate FLOAT NOT NULL)"
        ))
        conn.execute(text("CREATE TABLE ai_requests (id INTEGER PRIMARY KEY)"))
        conn.execute(text(
            "CREATE TABLE credit_transactions ("
            "id INTEGER PRIMARY KEY, ai_request_id INT, type VARCHAR(20),"
            "cache_read_tokens INT NOT NULL DEFAULT 0)"
        ))
        conn.execute(text(
            "CREATE TABLE feature_groups (group_key VARCHAR(50), i18n_key VARCHAR(100))"
        ))
        conn.execute(text(
            "CREATE TABLE feature_routes (route_path VARCHAR(100), i18n_key VARCHAR(100))"
        ))
        conn.execute(text("INSERT INTO ai_requests (id) VALUES (1), (2), (3), (4)"))
        conn.execute(text(
            "INSERT INTO credit_transactions (id, ai_request_id, type, cache_read_tokens) VALUES "
            "(1, 1, 'consume', 500),"   # 正常回填
            "(2, 2, 'consume', 0),"     # 流水无缓存 → 保持 0
            "(3, 3, 'grant', 999)"      # 非 consume → 不回填
            # id=4 无流水 → 保持 0
        ))

    _run_migrations(engine)

    with engine.connect() as conn:
        rows = dict(conn.execute(text(
            "SELECT id, cache_read_tokens FROM ai_requests ORDER BY id"
        )).all())
    assert rows == {1: 500, 2: 0, 3: 0, 4: 0}


def test_cache_read_migration_skips_legacy_transactions_schema():
    """credit_transactions 缺 ai_request_id 等列时回填应跳过而非报错。"""
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE model_pricing (id INTEGER PRIMARY KEY, in_rate FLOAT NOT NULL)"
        ))
        conn.execute(text("CREATE TABLE ai_requests (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE credit_transactions (id INTEGER PRIMARY KEY)"))
        conn.execute(text(
            "CREATE TABLE feature_groups (group_key VARCHAR(50), i18n_key VARCHAR(100))"
        ))
        conn.execute(text(
            "CREATE TABLE feature_routes (route_path VARCHAR(100), i18n_key VARCHAR(100))"
        ))
        conn.execute(text("INSERT INTO ai_requests (id) VALUES (1)"))

    _run_migrations(engine)

    with engine.connect() as conn:
        value = conn.execute(text(
            "SELECT cache_read_tokens FROM ai_requests WHERE id = 1"
        )).scalar_one()
    assert value == 0


def test_request_log_uses_historical_consume_transaction():
    request = AIRequest(
        id=1,
        user_id=7,
        module_name="ai_chat",
        model="test-model",
        prompt_tokens=180,
        completion_tokens=20,
        cache_read_tokens=1,
        cache_creation_tokens=2,
    )
    transaction = CreditTransaction(
        user_id=7,
        type="consume",
        amount=-728,
        balance_after=1000,
        ai_request_id=1,
        cache_read_tokens=50,
        cache_creation_tokens=30,
        multiplier=1.7,
    )

    result = _serialize_request_log(request, transaction)

    assert result["prompt_tokens"] == 180
    assert result["regular_input_tokens"] == 100
    assert result["cache_read_tokens"] == 50
    assert result["cache_creation_tokens"] == 30
    assert result["multiplier"] == 1.7
    assert result["cost_units"] == 728


def test_request_log_keeps_unbilled_request_and_clamps_regular_input():
    request = AIRequest(
        id=2,
        user_id=7,
        module_name="ai_chat",
        model="test-model",
        prompt_tokens=60,
        completion_tokens=0,
        cache_read_tokens=50,
        cache_creation_tokens=30,
        success=False,
    )

    result = _serialize_request_log(request, None)

    assert result["regular_input_tokens"] == 0
    assert result["cache_read_tokens"] == 50
    assert result["cache_creation_tokens"] == 30
    assert result["multiplier"] is None
    assert result["cost_units"] == 0


@pytest.mark.asyncio
async def test_list_requests_preserves_filters_order_limit_and_unbilled_rows():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            AIRequest.__table__,
            CreditTransaction.__table__,
            ModelPricing.__table__,
        ],
    )
    now = datetime.now(timezone.utc)

    with Session(engine) as session:
        user = User(username="admin", email="admin@example.com", role="admin")
        session.add(user)
        session.commit()
        session.refresh(user)

        billed = AIRequest(
            user_id=user.id,
            module_name="ai_chat",
            model="target-model",
            prompt_tokens=100,
            cache_read_tokens=20,
            success=True,
            created_at=now - timedelta(minutes=2),
        )
        unbilled = AIRequest(
            user_id=user.id,
            module_name="vibe-coding",
            model="target-model",
            prompt_tokens=50,
            success=True,
            created_at=now - timedelta(minutes=1),
        )
        filtered_out = AIRequest(
            user_id=user.id,
            module_name="ai_chat",
            model="target-model",
            success=False,
            created_at=now,
        )
        session.add_all([billed, unbilled, filtered_out])
        session.commit()
        session.refresh(billed)
        session.refresh(unbilled)

        session.add(CreditTransaction(
            user_id=user.id,
            type="consume",
            amount=-321,
            balance_after=1000,
            ai_request_id=billed.id,
            cache_read_tokens=20,
            multiplier=1.5,
        ))
        session.commit()

        response = await list_requests(
            user_id=user.id,
            model="target-model",
            success=True,
            limit=2,
            session=session,
            _=user,
        )
        limited_response = await list_requests(
            user_id=user.id,
            model="target-model",
            success=True,
            limit=1,
            session=session,
            _=user,
        )

    assert [row["id"] for row in response["data"]] == [unbilled.id, billed.id]
    assert response["data"][0]["cost_units"] == 0
    assert response["data"][0]["multiplier"] is None
    assert response["data"][1]["cost_units"] == 321
    assert len(limited_response["data"]) == 1
    assert limited_response["data"][0]["id"] == unbilled.id


@pytest.mark.asyncio
async def test_recalc_model_cost_updates_history_by_current_rates():
    from app.api.v1.gateway_admin import recalc_model_cost

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(
        engine,
        tables=[
            User.__table__, AIRequest.__table__, ModelPricing.__table__,
            CreditTransaction.__table__,
        ],
    )
    with Session(engine) as session:
        user = User(username="admin", email="admin2@example.com", role="admin")
        pricing = ModelPricing(
            model_id="m1", display_name="m1",
            in_rate=10.0, out_rate=50.0, cache_rate=1.0, cache_creation_rate=10.0,
        )
        session.add(user)
        session.add(pricing)
        session.commit()
        session.refresh(pricing)

        target = AIRequest(
            user_id=1, module_name="vibe-coding", model="m1",
            prompt_tokens=1_000_000 + 200_000 + 100_000,
            cache_read_tokens=200_000,
            cache_creation_tokens=100_000,
            completion_tokens=500_000,
            cost_cents=0, success=True,
        )
        other = AIRequest(
            user_id=1, module_name="vibe-coding", model="m2",
            prompt_tokens=999, completion_tokens=999, cost_cents=7, success=True,
        )
        session.add_all([target, other])
        session.commit()
        target_id, other_id = target.id, other.id

        response = await recalc_model_cost(pricing.id, session=session, _=user)

        # 1M×10 + 0.2M×1 + 0.1M×10 + 0.5M×50 = 36.2 credits → 362000 (0.0001 元)
        assert response["data"]["updated"] == 1
        assert session.get(AIRequest, target_id).cost_cents == 362000
        assert session.get(AIRequest, other_id).cost_cents == 7

def _recalc_engine():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(
        engine,
        tables=[
            User.__table__, AIRequest.__table__, ModelPricing.__table__,
            CreditTransaction.__table__,
        ],
    )
    return engine


@pytest.mark.asyncio
async def test_recalc_model_cost_rewrites_and_backfills_credit_transactions():
    from app.api.v1.gateway_admin import recalc_model_cost

    with Session(_recalc_engine()) as session:
        user = User(username="admin", email="admin3@example.com", role="admin")
        pricing = ModelPricing(
            model_id="m1", display_name="m1",
            in_rate=10.0, out_rate=50.0, cache_rate=1.0, cache_creation_rate=10.0,
            multiplier=2.0,
        )
        session.add_all([user, pricing])
        session.commit()
        session.refresh(pricing)

        billed_at = datetime(2026, 1, 2, 3, 4, 5)
        billed = AIRequest(
            user_id=1, module_name="vibe-coding", model="m1",
            prompt_tokens=1_000_000, completion_tokens=0,
            total_tokens=1_000_000, cost_cents=0, success=True,
            created_at=billed_at,
        )
        unbilled = AIRequest(
            user_id=1, module_name="vibe-coding", model="m1",
            prompt_tokens=500_000, completion_tokens=100_000,
            total_tokens=600_000, cost_cents=0, success=True,
            created_at=billed_at + timedelta(hours=1),
        )
        failed = AIRequest(
            user_id=1, module_name="vibe-coding", model="m1",
            prompt_tokens=100, total_tokens=100, cost_cents=0, success=False,
        )
        empty = AIRequest(
            user_id=1, module_name="vibe-coding", model="m1",
            prompt_tokens=0, total_tokens=0, cost_cents=0, success=True,
        )
        other_model = AIRequest(
            user_id=1, module_name="vibe-coding", model="m2",
            prompt_tokens=999, total_tokens=999, cost_cents=0, success=True,
        )
        session.add_all([billed, unbilled, failed, empty, other_model])
        session.commit()
        session.refresh(billed)
        session.refresh(unbilled)

        session.add(CreditTransaction(
            user_id=1, type="consume", amount=-1, balance_after=0,
            ai_request_id=billed.id, model="m1",
            prompt_tokens=1_000_000, completion_tokens=0, multiplier=1.0,
        ))
        session.commit()

        response = await recalc_model_cost(pricing.id, session=session, _=user)

        assert response["data"]["credits_updated"] == 1
        assert response["data"]["credits_backfilled"] == 1

        rewritten = session.exec(
            select(CreditTransaction).where(CreditTransaction.ai_request_id == billed.id)
        ).one()
        # 1M tokens × 10 credits/M × 倍率2.0 × CREDIT_UNIT ÷ 1M = 20_000_000
        assert rewritten.amount == -20_000_000
        assert rewritten.multiplier == 2.0

        backfilled = session.exec(
            select(CreditTransaction).where(CreditTransaction.ai_request_id == unbilled.id)
        ).one()
        # (0.5M×10 + 0.1M×50) × 2.0 = 20 credits → 20_000_000
        assert backfilled.amount == -20_000_000
        assert backfilled.multiplier == 2.0
        assert backfilled.created_at == unbilled.created_at
        assert backfilled.note == "补记：模型定价重算"
        assert backfilled.prompt_tokens == 500_000

        all_txns = session.exec(select(CreditTransaction)).all()
        assert len(all_txns) == 2  # 失败/0 token/其他模型均不补记


@pytest.mark.asyncio
async def test_recalc_model_cost_rejects_per_image_models():
    from app.api.v1.gateway_admin import recalc_model_cost

    with Session(_recalc_engine()) as session:
        user = User(username="admin", email="admin4@example.com", role="admin")
        pricing = ModelPricing(
            model_id="img1", display_name="img1", per_image_rate=0.5,
        )
        session.add_all([user, pricing])
        session.commit()
        session.refresh(pricing)

        response = await recalc_model_cost(pricing.id, session=session, _=user)
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_list_uncosted_models_aggregates_zero_cost_requests():
    from app.api.v1.gateway_admin import list_uncosted_models

    with Session(_recalc_engine()) as session:
        user = User(username="admin", email="admin5@example.com", role="admin")
        pricing = ModelPricing(model_id="priced", display_name="priced", in_rate=1.0)
        session.add_all([user, pricing])
        session.commit()
        session.refresh(pricing)

        t0 = datetime(2026, 1, 1, 0, 0, 0)
        session.add_all([
            AIRequest(user_id=1, module_name="m", model="unpriced",
                      total_tokens=100, cost_cents=0, success=True, created_at=t0),
            AIRequest(user_id=1, module_name="m", model="unpriced",
                      total_tokens=200, cost_cents=0, success=False,
                      created_at=t0 + timedelta(days=1)),
            AIRequest(user_id=1, module_name="m", model="priced",
                      total_tokens=50, cost_cents=0, success=True, created_at=t0),
            # 有成本/无 token 的请求不计入
            AIRequest(user_id=1, module_name="m", model="priced",
                      total_tokens=50, cost_cents=7, success=True, created_at=t0),
            AIRequest(user_id=1, module_name="m", model="unpriced",
                      total_tokens=0, cost_cents=0, success=True, created_at=t0),
        ])
        session.commit()

        response = await list_uncosted_models(session=session, _=user)

    rows = response["data"]
    assert [r["model"] for r in rows] == ["unpriced", "priced"]
    assert rows[0]["request_count"] == 2
    assert rows[0]["total_tokens"] == 300
    assert rows[0]["model_pk"] is None
    assert rows[0]["first_at"].startswith("2026-01-01")
    assert rows[0]["last_at"].startswith("2026-01-02")
    assert rows[1]["request_count"] == 1
    assert rows[1]["model_pk"] == pricing.id
