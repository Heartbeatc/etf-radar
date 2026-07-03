from datetime import datetime, timezone
from tempfile import TemporaryDirectory

from app.adapters.store import Store
from app.domain.models import AccountInput, EtfSnapshot, PositionAdjustInput, PositionExitInput, PositionInput
from app.services.portfolio import build_portfolio_snapshot


def test_portfolio_snapshot_calculates_cash_market_value_and_operable_cash():
    with TemporaryDirectory() as tmp:
        store = Store(f"{tmp}/test.db")
        store.upsert_account(AccountInput(cash_balance=10000, frozen_cash=1000, note="test"))
        store.upsert_position("600487", PositionInput(entry_price=10, shares=300, entry_date="2026-07-03", note=""))
        store.save_latest_snapshots([
            EtfSnapshot(code="600487", name="亨通光电", market_id=1, price=12, fetched_at=datetime.now(timezone.utc))
        ])

        portfolio = build_portfolio_snapshot(
            account=store.account_state(),
            positions=store.positions(),
            snapshots=store.latest_snapshots(),
        )

        assert portfolio.total_market_value == 3600
        assert portfolio.total_assets == 13600
        assert portfolio.available_cash == 9000
        assert round(portfolio.unrealized_profit_pct or 0, 2) == 20.0
        assert portfolio.risk_budget.operable_cash == 2040


def test_selling_position_credits_cash_when_account_exists():
    with TemporaryDirectory() as tmp:
        store = Store(f"{tmp}/test.db")
        store.upsert_account(AccountInput(cash_balance=10000, frozen_cash=0, note="test"))
        store.upsert_position("600487", PositionInput(entry_price=10, shares=100, entry_date="2026-07-03", note=""))
        store.close_position("600487", PositionExitInput(exit_price=12, shares=50, exit_date="2026-07-06", fee=1, reason="止盈"))

        assert store.account_state().cash_balance == 10599
        assert store.positions()["600487"].shares == 50


def test_buy_adjustment_recalculates_weighted_average_cost_and_debits_cash():
    with TemporaryDirectory() as tmp:
        store = Store(f"{tmp}/test.db")
        store.upsert_account(AccountInput(cash_balance=10000, frozen_cash=0, note="test"))
        store.upsert_position("600487", PositionInput(entry_price=10, shares=100, entry_date="2026-07-03", note="base"))

        record = store.adjust_position(
            "600487",
            PositionAdjustInput(side="buy", price=12, shares=100, trade_date="2026-07-06", fee=2, reason="加仓"),
        )

        position = store.positions()["600487"]
        assert position.shares == 200
        assert round(position.entry_price, 4) == 11.01
        assert record.average_cost_before == 10
        assert round(record.average_cost_after or 0, 4) == 11.01
        assert store.account_state().cash_balance == 8798


def test_sell_adjustment_keeps_remaining_average_cost_and_credits_cash():
    with TemporaryDirectory() as tmp:
        store = Store(f"{tmp}/test.db")
        store.upsert_account(AccountInput(cash_balance=10000, frozen_cash=0, note="test"))
        store.upsert_position("600487", PositionInput(entry_price=11.01, shares=200, entry_date="2026-07-03", note="base"))

        record = store.adjust_position(
            "600487",
            PositionAdjustInput(side="sell", price=13, shares=50, trade_date="2026-07-07", fee=1, reason="减仓"),
        )

        position = store.positions()["600487"]
        assert position.shares == 150
        assert position.entry_price == 11.01
        assert store.account_state().cash_balance == 10649
        assert round(record.realized_profit_amount or 0, 2) == 98.5
        assert round(record.realized_profit_pct or 0, 4) == round(98.5 / (11.01 * 50) * 100, 4)
