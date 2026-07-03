from datetime import datetime, timezone
from tempfile import TemporaryDirectory

from app.adapters.store import Store
from app.domain.models import AccountInput, EtfSnapshot, PositionExitInput, PositionInput
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
