from tempfile import TemporaryDirectory

from app.adapters.store import Store
from app.domain.models import PositionExitInput, PositionInput


def test_close_position_records_realized_trade_and_removes_position():
    with TemporaryDirectory() as tmp:
        store = Store(f"{tmp}/test.db")
        store.upsert_position(
            "600487",
            PositionInput(entry_price=92.4, shares=100, entry_date="2026-07-03", note="test"),
        )

        record = store.close_position(
            "600487",
            PositionExitInput(exit_price=89.42, shares=None, exit_date="2026-07-06", reason="止损", fee=0),
        )

        assert record.code == "600487"
        assert record.shares == 100
        assert round(record.realized_profit_pct, 2) == -3.23
        assert round(record.realized_profit_amount or 0, 2) == -298.0
        assert record.holding_days == 3
        assert store.positions() == {}
        assert store.closed_trades()[0].id == record.id


def test_close_position_partially_reduces_open_shares():
    with TemporaryDirectory() as tmp:
        store = Store(f"{tmp}/test.db")
        store.upsert_position(
            "600487",
            PositionInput(entry_price=92.4, shares=200, entry_date="2026-07-03", note="test"),
        )

        record = store.close_position(
            "600487",
            PositionExitInput(exit_price=96.0, shares=50, exit_date="2026-07-06", reason="止盈", fee=1.0),
        )

        positions = store.positions()
        assert record.remaining_shares == 150
        assert positions["600487"].shares == 150
        assert round(record.realized_profit_amount or 0, 2) == 179.0
