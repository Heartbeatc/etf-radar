from __future__ import annotations

from datetime import datetime, timezone

from app.domain.models import AccountState, EtfSnapshot, PortfolioPosition, PortfolioRiskBudget, PortfolioSnapshotResponse, Position

MAX_SINGLE_TRADE_PCT = 15.0
CASH_BUFFER_PCT = 10.0


def build_portfolio_snapshot(
    *,
    account: AccountState | None,
    positions: dict[str, Position],
    snapshots: dict[str, EtfSnapshot],
) -> PortfolioSnapshotResponse:
    warnings: list[str] = []
    rows: list[PortfolioPosition] = []
    total_market_value = 0.0
    total_cost_amount = 0.0
    market_value_known = True
    cost_known = True

    for position in positions.values():
        snapshot = snapshots.get(position.code)
        current_price = snapshot.price if snapshot else None
        cost_amount = position.entry_price * position.shares if position.shares is not None else None
        market_value = current_price * position.shares if current_price is not None and position.shares is not None else None
        unrealized_amount = market_value - cost_amount if market_value is not None and cost_amount is not None else None
        unrealized_pct = unrealized_amount / cost_amount * 100 if unrealized_amount is not None and cost_amount and cost_amount > 0 else None

        if position.shares is None:
            warnings.append(f"{position.code} 未录入数量，无法计算市值、仓位和可操作资金。")
        if current_price is None:
            warnings.append(f"{position.code} 缺少当前价格，持仓市值按未知处理。")
        if market_value is None:
            market_value_known = False
        else:
            total_market_value += market_value
        if cost_amount is None:
            cost_known = False
        else:
            total_cost_amount += cost_amount

        rows.append(
            PortfolioPosition(
                code=position.code,
                name=snapshot.name if snapshot else None,
                entry_price=position.entry_price,
                shares=position.shares,
                lots=position.shares / 100 if position.shares is not None else None,
                current_price=current_price,
                cost_amount=cost_amount,
                market_value=market_value,
                unrealized_profit_amount=unrealized_amount,
                unrealized_profit_pct=unrealized_pct,
                entry_date=position.entry_date,
                note=position.note,
            )
        )

    cash_balance = account.cash_balance if account else None
    frozen_cash = account.frozen_cash if account else None
    available_cash = max(0.0, cash_balance - frozen_cash) if cash_balance is not None and frozen_cash is not None else None
    total_assets = cash_balance + total_market_value if cash_balance is not None and market_value_known else None
    total_cost = total_cost_amount if cost_known else None
    unrealized_amount_total = total_market_value - total_cost_amount if market_value_known and cost_known else None
    unrealized_pct_total = unrealized_amount_total / total_cost_amount * 100 if unrealized_amount_total is not None and total_cost_amount > 0 else None
    exposure_pct = total_market_value / total_assets * 100 if total_assets and total_assets > 0 and market_value_known else None

    for row in rows:
        if total_assets and row.market_value is not None:
            row.position_weight_pct = row.market_value / total_assets * 100

    if account is None:
        warnings.append("尚未录入账户现金，无法计算总资产、可用资金、可操作资金和仓位比例。")

    risk_budget = _risk_budget(total_assets=total_assets, available_cash=available_cash)
    return PortfolioSnapshotResponse(
        generated_at=datetime.now(timezone.utc),
        account=account,
        positions=rows,
        total_assets=total_assets,
        cash_balance=cash_balance,
        frozen_cash=frozen_cash,
        available_cash=available_cash,
        total_market_value=total_market_value if market_value_known else None,
        total_cost_amount=total_cost,
        unrealized_profit_amount=unrealized_amount_total,
        unrealized_profit_pct=unrealized_pct_total,
        position_exposure_pct=exposure_pct,
        risk_budget=risk_budget,
        warnings=warnings,
    )


def _risk_budget(*, total_assets: float | None, available_cash: float | None) -> PortfolioRiskBudget:
    if total_assets is None or available_cash is None:
        return PortfolioRiskBudget(risk_note="先录入账户现金和持仓数量，否则无法给出可操作资金。")
    cash_buffer = total_assets * CASH_BUFFER_PCT / 100
    max_single_trade_cash = total_assets * MAX_SINGLE_TRADE_PCT / 100
    cash_after_buffer = max(0.0, available_cash - cash_buffer)
    operable_cash = min(cash_after_buffer, max_single_trade_cash)
    return PortfolioRiskBudget(
        available_cash=available_cash,
        operable_cash=operable_cash,
        max_single_trade_cash=max_single_trade_cash,
        cash_buffer=cash_buffer,
        risk_note=f"单笔上限按总资产{MAX_SINGLE_TRADE_PCT:.0f}%估算，并保留{CASH_BUFFER_PCT:.0f}%现金缓冲。",
    )
