from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from app.core.market import MARKET_TZ
from app.domain.models import AlertEvent, AiSummaryItem, AiTradeRiskReview, DailyBar, EtfSnapshot, EventItem, MarketFlowResponse, MinuteBar, Position, PositionExitInput, PositionInput, QuantFrameworkResponse, QuantSignalRecord, SignalRecord, SourceStatus, TradePlan, TradeRecord


class Store:
    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists schema_meta (
                    key text primary key,
                    value text not null
                );

                create table if not exists snapshots (
                    id integer primary key autoincrement,
                    code text not null,
                    fetched_at text not null,
                    payload text not null
                );
                create index if not exists idx_snapshots_code_time on snapshots(code, fetched_at desc);

                create table if not exists latest_snapshots (
                    code text primary key,
                    fetched_at text not null,
                    payload text not null
                );

                create table if not exists daily_bars (
                    code text primary key,
                    fetched_at text not null,
                    payload text not null
                );

                create table if not exists minute_bars (
                    code text primary key,
                    fetched_at text not null,
                    payload text not null
                );

                create table if not exists positions (
                    code text primary key,
                    entry_price real not null,
                    shares real,
                    entry_date text,
                    note text not null default '',
                    updated_at text not null
                );

                create table if not exists closed_trades (
                    id integer primary key autoincrement,
                    code text not null,
                    entry_price real not null,
                    exit_price real not null,
                    shares real,
                    entry_date text,
                    exit_date text not null,
                    reason text not null default '',
                    note text not null default '',
                    fee real not null default 0,
                    realized_profit_pct real not null,
                    realized_profit_amount real,
                    holding_days integer,
                    closed_at text not null,
                    remaining_shares real,
                    source text not null default 'manual',
                    payload text not null
                );
                create index if not exists idx_closed_trades_code_time on closed_trades(code, closed_at desc);
                create index if not exists idx_closed_trades_time on closed_trades(closed_at desc);

                create table if not exists signal_history (
                    id integer primary key autoincrement,
                    code text not null,
                    name text not null,
                    role text not null,
                    signal_at text not null,
                    signal text not null,
                    confidence text not null,
                    direction_score integer not null,
                    low_buy_score integer not null,
                    hold_score integer not null,
                    take_profit_score integer not null,
                    risk_score integer not null,
                    current_price real,
                    data_state text not null,
                    payload text not null
                );
                create index if not exists idx_signal_history_code_time on signal_history(code, signal_at desc);
                create index if not exists idx_signal_history_signal_time on signal_history(signal, signal_at desc);

                create table if not exists quant_signal_history (
                    id integer primary key autoincrement,
                    signal_at text not null,
                    code text not null,
                    name text not null,
                    side text not null,
                    action text not null,
                    urgency text not null,
                    target_weight_pct real,
                    current_price real,
                    trigger_price_low real,
                    trigger_price_high real,
                    stop_price real,
                    take_profit_price real,
                    evidence_strength text not null,
                    live_trading_ready integer not null,
                    blocker_count integer not null,
                    signal_key text not null,
                    payload text not null
                );
                create index if not exists idx_quant_signal_code_time on quant_signal_history(code, signal_at desc);
                create index if not exists idx_quant_signal_side_time on quant_signal_history(side, signal_at desc);
                create index if not exists idx_quant_signal_key_time on quant_signal_history(signal_key, signal_at desc);

                create table if not exists alert_events (
                    id integer primary key autoincrement,
                    code text not null,
                    alert_at text not null,
                    level text not null,
                    event text not null,
                    message text not null,
                    delivered integer not null default 0,
                    error text,
                    payload text not null
                );
                create index if not exists idx_alert_events_code_time on alert_events(code, alert_at desc);
                create index if not exists idx_alert_events_event_time on alert_events(event, alert_at desc);

                create table if not exists source_status (
                    code text primary key,
                    checked_at text not null,
                    ok integer not null,
                    payload text not null
                );

                create table if not exists market_flow_history (
                    id integer primary key autoincrement,
                    generated_at text not null,
                    payload text not null
                );
                create index if not exists idx_market_flow_history_time on market_flow_history(generated_at desc);

                create table if not exists event_items (
                    id text primary key,
                    source text not null,
                    title text not null,
                    published_at text,
                    fetched_at text not null,
                    direction_key text,
                    relevance_score integer not null,
                    payload text not null
                );
                create index if not exists idx_event_items_time on event_items(published_at desc, fetched_at desc);
                create index if not exists idx_event_items_direction on event_items(direction_key, published_at desc, fetched_at desc);

                create table if not exists runtime_settings (
                    key text primary key,
                    value text not null,
                    updated_at text not null
                );

                create table if not exists ai_summaries (
                    id integer primary key autoincrement,
                    kind text not null,
                    trading_date text not null,
                    generated_at text not null,
                    source_data_time text,
                    model text not null,
                    status text not null,
                    summary text not null,
                    error text,
                    payload text not null,
                    unique(kind, trading_date)
                );
                create index if not exists idx_ai_summaries_time on ai_summaries(generated_at desc);

                create table if not exists ai_call_log (
                    id integer primary key autoincrement,
                    purpose text not null,
                    kind text not null,
                    trading_date text not null,
                    called_at text not null,
                    status text not null,
                    error text
                );
                create index if not exists idx_ai_call_log_date on ai_call_log(trading_date, called_at desc);
                create index if not exists idx_ai_call_log_purpose_date on ai_call_log(purpose, trading_date, called_at desc);

                create table if not exists ai_trade_reviews (
                    id integer primary key autoincrement,
                    review_key text not null unique,
                    code text not null,
                    name text not null,
                    side text not null,
                    action text not null,
                    trading_date text not null,
                    generated_at text not null,
                    model text not null,
                    status text not null,
                    source text not null,
                    risk_level text not null,
                    conclusion text not null,
                    error text,
                    payload text not null
                );
                create index if not exists idx_ai_trade_reviews_date on ai_trade_reviews(trading_date, generated_at desc);
                create index if not exists idx_ai_trade_reviews_code on ai_trade_reviews(code, generated_at desc);
                """
            )
            conn.execute(
                "insert into schema_meta(key, value) values('schema_version', '2') on conflict(key) do update set value = excluded.value"
            )
            columns = {row[1] for row in conn.execute("pragma table_info(positions)").fetchall()}
            if "entry_date" not in columns:
                conn.execute("alter table positions add column entry_date text")

    def save_snapshots(self, snapshots: list[EtfSnapshot]) -> None:
        with self._lock, self._connect() as conn:
            for snapshot in snapshots:
                payload = snapshot.model_dump_json()
                fetched_at = snapshot.fetched_at.isoformat()
                conn.execute(
                    "insert into snapshots(code, fetched_at, payload) values (?, ?, ?)",
                    (snapshot.code, fetched_at, payload),
                )
                conn.execute(
                    """
                    insert into latest_snapshots(code, fetched_at, payload) values (?, ?, ?)
                    on conflict(code) do update set fetched_at = excluded.fetched_at, payload = excluded.payload
                    """,
                    (snapshot.code, fetched_at, payload),
                )
            conn.execute(
                "delete from snapshots where id not in (select id from snapshots order by fetched_at desc limit 20000)"
            )

    def save_latest_snapshots(self, snapshots: list[EtfSnapshot]) -> None:
        with self._lock, self._connect() as conn:
            for snapshot in snapshots:
                conn.execute(
                    """
                    insert into latest_snapshots(code, fetched_at, payload) values (?, ?, ?)
                    on conflict(code) do update set fetched_at = excluded.fetched_at, payload = excluded.payload
                    """,
                    (snapshot.code, snapshot.fetched_at.isoformat(), snapshot.model_dump_json()),
                )

    def latest_snapshots(self) -> dict[str, EtfSnapshot]:
        with self._connect() as conn:
            rows = conn.execute("select code, payload from latest_snapshots").fetchall()
        return {row["code"]: EtfSnapshot.model_validate_json(row["payload"]) for row in rows}

    def save_market_flow_report(self, report: MarketFlowResponse) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "insert into market_flow_history(generated_at, payload) values (?, ?)",
                (report.generated_at.isoformat(), report.model_dump_json()),
            )
            conn.execute(
                "delete from market_flow_history where id not in (select id from market_flow_history order by generated_at desc limit 25000)"
            )

    def market_flow_history(self, limit: int = 25000) -> list[MarketFlowResponse]:
        with self._connect() as conn:
            rows = conn.execute(
                "select payload from market_flow_history order by generated_at desc limit ?",
                (limit,),
            ).fetchall()
        reports: list[MarketFlowResponse] = []
        for row in rows:
            try:
                reports.append(MarketFlowResponse.model_validate_json(row["payload"]))
            except Exception:
                continue
        return reports

    def save_event_items(self, items: list[EventItem]) -> int:
        inserted = 0
        with self._lock, self._connect() as conn:
            for item in items:
                payload = item.model_dump_json()
                published_at = item.published_at.isoformat() if item.published_at else None
                fetched_at = item.fetched_at.isoformat()
                cursor = conn.execute(
                    """
                    insert or ignore into event_items(
                        id, source, title, published_at, fetched_at, direction_key, relevance_score, payload
                    ) values (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.id,
                        item.source,
                        item.title,
                        published_at,
                        fetched_at,
                        item.direction_key,
                        item.relevance_score,
                        payload,
                    ),
                )
                if cursor.rowcount:
                    inserted += 1
                else:
                    conn.execute(
                        """
                        update event_items
                        set source = ?, title = ?, published_at = ?, fetched_at = ?,
                            direction_key = ?, relevance_score = ?, payload = ?
                        where id = ?
                        """,
                        (
                            item.source,
                            item.title,
                            published_at,
                            fetched_at,
                            item.direction_key,
                            item.relevance_score,
                            payload,
                            item.id,
                        ),
                    )
            conn.execute(
                "delete from event_items where id not in (select id from event_items order by fetched_at desc limit 10000)"
            )
        return inserted

    def event_items(self, direction_key: str | None = None, limit: int = 200) -> list[EventItem]:
        limit = max(1, min(limit, 1000))
        if direction_key:
            sql = "select payload from event_items where direction_key = ? order by coalesce(published_at, fetched_at) desc limit ?"
            params: tuple[Any, ...] = (direction_key, limit)
        else:
            sql = "select payload from event_items order by coalesce(published_at, fetched_at) desc limit ?"
            params = (limit,)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        events: list[EventItem] = []
        for row in rows:
            try:
                events.append(EventItem.model_validate_json(row["payload"]))
            except Exception:
                continue
        return events

    def save_daily_bars(self, code: str, bars: list[DailyBar]) -> None:
        self._save_bars("daily_bars", code, [bar.model_dump() for bar in bars])

    def save_minute_bars(self, code: str, bars: list[MinuteBar]) -> None:
        self._save_bars("minute_bars", code, [bar.model_dump() for bar in bars])

    def get_daily_bars(self, code: str) -> list[DailyBar]:
        return [DailyBar.model_validate(item) for item in self._get_bars("daily_bars", code)]

    def get_minute_bars(self, code: str) -> list[MinuteBar]:
        return [MinuteBar.model_validate(item) for item in self._get_bars("minute_bars", code)]

    def _save_bars(self, table: str, code: str, payload: list[dict]) -> None:
        fetched_at = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                f"""
                insert into {table}(code, fetched_at, payload) values (?, ?, ?)
                on conflict(code) do update set fetched_at = excluded.fetched_at, payload = excluded.payload
                """,
                (code, fetched_at, json.dumps(payload, ensure_ascii=False)),
            )

    def _get_bars(self, table: str, code: str) -> list[dict]:
        with self._connect() as conn:
            row = conn.execute(f"select payload from {table} where code = ?", (code,)).fetchone()
        if not row:
            return []
        return json.loads(row["payload"])

    def upsert_position(self, code: str, position: PositionInput) -> Position:
        updated_at = datetime.now(timezone.utc)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                insert into positions(code, entry_price, shares, entry_date, note, updated_at) values (?, ?, ?, ?, ?, ?)
                on conflict(code) do update set
                    entry_price = excluded.entry_price,
                    shares = excluded.shares,
                    entry_date = excluded.entry_date,
                    note = excluded.note,
                    updated_at = excluded.updated_at
                """,
                (code, position.entry_price, position.shares, position.entry_date, position.note, updated_at.isoformat()),
            )
        return Position(code=code, updated_at=updated_at, **position.model_dump())

    def close_position(self, code: str, exit_input: PositionExitInput) -> TradeRecord:
        closed_at = datetime.now(timezone.utc)
        exit_date = exit_input.exit_date or datetime.now(MARKET_TZ).date().isoformat()
        try:
            date.fromisoformat(exit_date)
        except ValueError:
            raise ValueError("exit_date must be YYYY-MM-DD")
        with self._lock, self._connect() as conn:
            row = conn.execute("select * from positions where code = ?", (code,)).fetchone()
            if row is None:
                raise KeyError(code)

            position = self._position_from_row(row)
            close_shares = exit_input.shares if exit_input.shares is not None else position.shares
            remaining_shares = self._remaining_shares(position.shares, close_shares)
            if remaining_shares is not None and remaining_shares < -0.000001:
                raise ValueError("sell shares exceed open position shares")
            if remaining_shares is not None and remaining_shares <= 0.000001:
                remaining_shares = None

            realized_amount = None
            realized_pct = (exit_input.exit_price - position.entry_price) / position.entry_price * 100
            if close_shares is not None:
                realized_amount = (exit_input.exit_price - position.entry_price) * close_shares - exit_input.fee
                cost_amount = position.entry_price * close_shares
                if cost_amount > 0:
                    realized_pct = realized_amount / cost_amount * 100

            holding_days = self._holding_days(position.entry_date, exit_date)
            payload = {
                "position": position.model_dump(mode="json"),
                "exit": exit_input.model_dump(mode="json"),
            }
            cursor = conn.execute(
                """
                insert into closed_trades(
                    code, entry_price, exit_price, shares, entry_date, exit_date, reason, note, fee,
                    realized_profit_pct, realized_profit_amount, holding_days, closed_at, remaining_shares, source, payload
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    code,
                    position.entry_price,
                    exit_input.exit_price,
                    close_shares,
                    position.entry_date,
                    exit_date,
                    exit_input.reason.strip(),
                    exit_input.note.strip(),
                    exit_input.fee,
                    realized_pct,
                    realized_amount,
                    holding_days,
                    closed_at.isoformat(),
                    remaining_shares,
                    "manual",
                    json.dumps(payload, ensure_ascii=False),
                ),
            )

            if remaining_shares is None:
                conn.execute("delete from positions where code = ?", (code,))
            else:
                conn.execute(
                    "update positions set shares = ?, note = ?, updated_at = ? where code = ?",
                    (remaining_shares, position.note, closed_at.isoformat(), code),
                )

            return TradeRecord(
                id=int(cursor.lastrowid),
                code=code,
                entry_price=position.entry_price,
                exit_price=exit_input.exit_price,
                shares=close_shares,
                entry_date=position.entry_date,
                exit_date=exit_date,
                reason=exit_input.reason.strip(),
                note=exit_input.note.strip(),
                fee=exit_input.fee,
                realized_profit_pct=realized_pct,
                realized_profit_amount=realized_amount,
                holding_days=holding_days,
                closed_at=closed_at,
                remaining_shares=remaining_shares,
            )

    def closed_trades(self, code: str | None = None, limit: int = 200) -> list[TradeRecord]:
        with self._connect() as conn:
            if code:
                rows = conn.execute(
                    "select * from closed_trades where code = ? order by closed_at desc, id desc limit ?",
                    (code, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "select * from closed_trades order by closed_at desc, id desc limit ?",
                    (limit,),
                ).fetchall()
        return [self._trade_from_row(row) for row in rows]

    def delete_position(self, code: str) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute("delete from positions where code = ?", (code,))
            return cursor.rowcount > 0

    def positions(self) -> dict[str, Position]:
        with self._connect() as conn:
            rows = conn.execute("select * from positions").fetchall()
        return {row["code"]: self._position_from_row(row) for row in rows}

    def _position_from_row(self, row: sqlite3.Row) -> Position:
        return Position(
            code=row["code"],
            entry_price=row["entry_price"],
            shares=row["shares"],
            entry_date=row["entry_date"],
            note=row["note"],
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _trade_from_row(self, row: sqlite3.Row) -> TradeRecord:
        return TradeRecord(
            id=row["id"],
            code=row["code"],
            entry_price=row["entry_price"],
            exit_price=row["exit_price"],
            shares=row["shares"],
            entry_date=row["entry_date"],
            exit_date=row["exit_date"],
            reason=row["reason"],
            note=row["note"],
            fee=row["fee"],
            realized_profit_pct=row["realized_profit_pct"],
            realized_profit_amount=row["realized_profit_amount"],
            holding_days=row["holding_days"],
            closed_at=datetime.fromisoformat(row["closed_at"]),
            remaining_shares=row["remaining_shares"],
            source=row["source"],
        )

    def _remaining_shares(self, position_shares: float | None, close_shares: float | None) -> float | None:
        if position_shares is None:
            return None
        if close_shares is None:
            return None
        return position_shares - close_shares

    def _holding_days(self, entry_date: str | None, exit_date: str) -> int | None:
        if not entry_date:
            return None
        try:
            entry = date.fromisoformat(entry_date)
            exit_day = date.fromisoformat(exit_date)
        except ValueError:
            return None
        return max(0, (exit_day - entry).days)

    def save_signal_history(self, plans: list[TradePlan]) -> None:
        signal_at = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn:
            for plan in plans:
                conn.execute(
                    """
                    insert into signal_history(
                        code, name, role, signal_at, signal, confidence, direction_score, low_buy_score,
                        hold_score, take_profit_score, risk_score, current_price, data_state, payload
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        plan.code,
                        plan.name,
                        plan.role,
                        signal_at,
                        plan.signal,
                        plan.confidence,
                        plan.direction_score,
                        plan.low_buy_score,
                        plan.hold_score,
                        plan.take_profit_score,
                        plan.risk_score,
                        plan.current_price,
                        plan.data_state,
                        plan.model_dump_json(),
                    ),
                )
            conn.execute(
                "delete from signal_history where id not in (select id from signal_history order by signal_at desc limit 50000)"
            )

    def save_quant_framework_signals(self, report: QuantFrameworkResponse, dedupe_minutes: int = 20) -> int:
        signal_at = report.generated_at.isoformat()
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max(1, dedupe_minutes))).isoformat()
        action_by_code = {item.code: item for item in report.final_actions}
        inserted = 0
        with self._lock, self._connect() as conn:
            for advice in report.execution_plan:
                action = action_by_code.get(advice.code)
                signal_key = _quant_signal_key(advice.model_dump(), report.validation.evidence_strength)
                row = conn.execute(
                    """
                    select 1 from quant_signal_history
                    where code = ? and signal_key = ? and signal_at >= ?
                    limit 1
                    """,
                    (advice.code, signal_key, cutoff),
                ).fetchone()
                if row:
                    continue
                payload = {
                    "advice": advice.model_dump(mode="json"),
                    "action": action.model_dump(mode="json") if action else None,
                    "validation": report.validation.model_dump(mode="json"),
                    "market_status": report.market_status,
                }
                conn.execute(
                    """
                    insert into quant_signal_history(
                        signal_at, code, name, side, action, urgency, target_weight_pct, current_price,
                        trigger_price_low, trigger_price_high, stop_price, take_profit_price,
                        evidence_strength, live_trading_ready, blocker_count, signal_key, payload
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        signal_at,
                        advice.code,
                        advice.name,
                        advice.side,
                        advice.action,
                        advice.urgency,
                        advice.target_weight_pct,
                        action.current_price if action else None,
                        advice.trigger_price_low,
                        advice.trigger_price_high,
                        advice.stop_price,
                        advice.take_profit_price,
                        report.validation.evidence_strength,
                        int(report.validation.live_trading_ready),
                        len(advice.blockers),
                        signal_key,
                        json.dumps(payload, ensure_ascii=False),
                    ),
                )
                inserted += 1
            conn.execute(
                "delete from quant_signal_history where id not in (select id from quant_signal_history order by signal_at desc limit 50000)"
            )
        return inserted

    def quant_signal_history(self, code: str | None = None, limit: int = 1000) -> list[QuantSignalRecord]:
        limit = max(1, min(limit, 5000))
        params: tuple[Any, ...]
        sql = "select * from quant_signal_history"
        if code:
            sql += " where code = ?"
            params = (code,)
        else:
            params = ()
        sql += " order by signal_at desc limit ?"
        params = (*params, limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_quant_signal_record(row) for row in rows]

    def previous_signals(self, codes: list[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        with self._connect() as conn:
            for code in codes:
                row = conn.execute(
                    "select signal from signal_history where code = ? order by signal_at desc limit 1",
                    (code,),
                ).fetchone()
                if row:
                    result[code] = row["signal"]
        return result

    def signal_history(self, code: str | None = None, limit: int = 200) -> list[SignalRecord]:
        limit = max(1, min(limit, 1000))
        params: tuple[Any, ...]
        sql = "select * from signal_history"
        if code:
            sql += " where code = ?"
            params = (code,)
        else:
            params = ()
        sql += " order by signal_at desc limit ?"
        params = (*params, limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_signal_record(row) for row in rows]

    def get_bool_setting(self, key: str, default: bool) -> bool:
        with self._connect() as conn:
            row = conn.execute("select value from runtime_settings where key = ?", (key,)).fetchone()
        if not row:
            return default
        return str(row["value"]).strip().lower() in {"1", "true", "yes", "on"}

    def set_bool_setting(self, key: str, value: bool) -> None:
        self.set_text_setting(key, "true" if value else "false")

    def get_text_setting(self, key: str, default: str = "") -> str:
        with self._connect() as conn:
            row = conn.execute("select value from runtime_settings where key = ?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def set_text_setting(self, key: str, value: str) -> None:
        updated_at = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                insert into runtime_settings(key, value, updated_at) values (?, ?, ?)
                on conflict(key) do update set value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, updated_at),
            )

    def save_ai_summary(self, summary: AiSummaryItem) -> AiSummaryItem:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                insert into ai_summaries(kind, trading_date, generated_at, source_data_time, model, status, summary, error, payload)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(kind, trading_date) do update set
                    generated_at = excluded.generated_at,
                    source_data_time = excluded.source_data_time,
                    model = excluded.model,
                    status = excluded.status,
                    summary = excluded.summary,
                    error = excluded.error,
                    payload = excluded.payload
                """,
                (
                    summary.kind,
                    summary.trading_date,
                    summary.generated_at.isoformat(),
                    summary.source_data_time.isoformat() if summary.source_data_time else None,
                    summary.model,
                    summary.status,
                    summary.summary,
                    summary.error,
                    json.dumps(summary.payload, ensure_ascii=False),
                ),
            )
        return summary

    def latest_ai_summaries(self, limit: int = 20) -> list[AiSummaryItem]:
        limit = max(1, min(limit, 100))
        with self._connect() as conn:
            rows = conn.execute("select * from ai_summaries order by generated_at desc limit ?", (limit,)).fetchall()
        return [_ai_summary_item(row) for row in rows]

    def ai_summary_for(self, kind: str, trading_date: str) -> AiSummaryItem | None:
        with self._connect() as conn:
            row = conn.execute(
                "select * from ai_summaries where kind = ? and trading_date = ?",
                (kind, trading_date),
            ).fetchone()
        return _ai_summary_item(row) if row else None

    def log_ai_call(self, purpose: str, kind: str, trading_date: str, status: str, error: str | None = None) -> None:
        called_at = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                "insert into ai_call_log(purpose, kind, trading_date, called_at, status, error) values (?, ?, ?, ?, ?, ?)",
                (purpose, kind, trading_date, called_at, status, error),
            )
            conn.execute(
                "delete from ai_call_log where id not in (select id from ai_call_log order by called_at desc limit 1000)"
            )

    def ai_call_count(self, trading_date: str, purpose: str | None = None) -> int:
        with self._connect() as conn:
            if purpose:
                row = conn.execute(
                    "select count(*) as count from ai_call_log where trading_date = ? and purpose = ?",
                    (trading_date, purpose),
                ).fetchone()
            else:
                row = conn.execute("select count(*) as count from ai_call_log where trading_date = ?", (trading_date,)).fetchone()
        return int(row["count"] if row else 0)

    def save_ai_trade_review(self, review: AiTradeRiskReview) -> AiTradeRiskReview:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                insert into ai_trade_reviews(
                    review_key, code, name, side, action, trading_date, generated_at, model, status, source,
                    risk_level, conclusion, error, payload
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(review_key) do update set
                    generated_at = excluded.generated_at,
                    model = excluded.model,
                    status = excluded.status,
                    source = excluded.source,
                    risk_level = excluded.risk_level,
                    conclusion = excluded.conclusion,
                    error = excluded.error,
                    payload = excluded.payload
                """,
                (
                    review.review_key,
                    review.code,
                    review.name,
                    review.side,
                    review.action,
                    review.trading_date,
                    review.generated_at.isoformat(),
                    review.model,
                    review.status,
                    review.source,
                    review.risk_level,
                    review.conclusion,
                    review.error,
                    review.model_dump_json(),
                ),
            )
            conn.execute(
                "delete from ai_trade_reviews where id not in (select id from ai_trade_reviews order by generated_at desc limit 1000)"
            )
        return review

    def ai_trade_review_for(self, review_key: str) -> AiTradeRiskReview | None:
        with self._connect() as conn:
            row = conn.execute("select payload from ai_trade_reviews where review_key = ?", (review_key,)).fetchone()
        if not row:
            return None
        return AiTradeRiskReview.model_validate_json(row["payload"])

    def latest_ai_trade_reviews(self, limit: int = 20) -> list[AiTradeRiskReview]:
        limit = max(1, min(limit, 100))
        with self._connect() as conn:
            rows = conn.execute("select payload from ai_trade_reviews order by generated_at desc limit ?", (limit,)).fetchall()
        return [AiTradeRiskReview.model_validate_json(row["payload"]) for row in rows]

    def save_source_status(self, statuses: list[SourceStatus]) -> None:
        checked_at = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn:
            for status in statuses:
                conn.execute(
                    """
                    insert into source_status(code, checked_at, ok, payload) values (?, ?, ?, ?)
                    on conflict(code) do update set checked_at = excluded.checked_at, ok = excluded.ok, payload = excluded.payload
                    """,
                    (status.code, checked_at, int(status.ok), status.model_dump_json()),
                )

    def source_statuses(self) -> list[SourceStatus]:
        with self._connect() as conn:
            rows = conn.execute("select payload from source_status order by code").fetchall()
        return [SourceStatus.model_validate_json(row["payload"]) for row in rows]

    def recent_alert_exists(self, code: str, event: str, cooldown_seconds: int) -> bool:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=cooldown_seconds)).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "select 1 from alert_events where code = ? and event = ? and alert_at >= ? limit 1",
                (code, event, cutoff),
            ).fetchone()
        return row is not None

    def save_alert_event(
        self,
        code: str,
        level: str,
        event: str,
        message: str,
        payload: dict[str, Any],
        delivered: bool = False,
        error: str | None = None,
    ) -> AlertEvent:
        alert_at = datetime.now(timezone.utc)
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                insert into alert_events(code, alert_at, level, event, message, delivered, error, payload)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    code,
                    alert_at.isoformat(),
                    level,
                    event,
                    message,
                    int(delivered),
                    error,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            event_id = int(cursor.lastrowid)
            conn.execute(
                "delete from alert_events where id not in (select id from alert_events order by alert_at desc limit 5000)"
            )
        return AlertEvent(
            id=event_id,
            code=code,
            alert_at=alert_at,
            level=level,
            event=event,
            message=message,
            delivered=delivered,
            error=error,
            payload=payload,
        )

    def mark_alert_delivery(self, event_id: int, delivered: bool, error: str | None = None) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "update alert_events set delivered = ?, error = ? where id = ?",
                (int(delivered), error, event_id),
            )

    def alert_events(self, code: str | None = None, limit: int = 100) -> list[AlertEvent]:
        limit = max(1, min(limit, 1000))
        params: tuple[Any, ...]
        sql = "select * from alert_events"
        if code:
            sql += " where code = ?"
            params = (code,)
        else:
            params = ()
        sql += " order by alert_at desc limit ?"
        params = (*params, limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_alert_event(row) for row in rows]


def _signal_record(row: sqlite3.Row) -> SignalRecord:
    return SignalRecord(
        id=row["id"],
        code=row["code"],
        name=row["name"],
        role=row["role"],
        signal_at=datetime.fromisoformat(row["signal_at"]),
        signal=row["signal"],
        confidence=row["confidence"],
        direction_score=row["direction_score"],
        low_buy_score=row["low_buy_score"],
        hold_score=row["hold_score"],
        take_profit_score=row["take_profit_score"],
        risk_score=row["risk_score"],
        current_price=row["current_price"],
        data_state=row["data_state"],
        payload=json.loads(row["payload"]),
    )



def _quant_signal_record(row: sqlite3.Row) -> QuantSignalRecord:
    return QuantSignalRecord(
        id=row["id"],
        signal_at=datetime.fromisoformat(row["signal_at"]),
        code=row["code"],
        name=row["name"],
        side=row["side"],
        action=row["action"],
        urgency=row["urgency"],
        target_weight_pct=row["target_weight_pct"],
        current_price=row["current_price"],
        trigger_price_low=row["trigger_price_low"],
        trigger_price_high=row["trigger_price_high"],
        stop_price=row["stop_price"],
        take_profit_price=row["take_profit_price"],
        evidence_strength=row["evidence_strength"],
        live_trading_ready=bool(row["live_trading_ready"]),
        blocker_count=row["blocker_count"],
        signal_key=row["signal_key"],
        payload=json.loads(row["payload"]),
    )


def _quant_signal_key(payload: dict[str, Any], evidence_strength: str) -> str:
    values = [
        payload.get("code"),
        payload.get("side"),
        payload.get("action"),
        payload.get("urgency"),
        _round_key(payload.get("target_weight_pct")),
        _round_key(payload.get("trigger_price_low")),
        _round_key(payload.get("trigger_price_high")),
        _round_key(payload.get("stop_price")),
        _round_key(payload.get("take_profit_price")),
        len(payload.get("blockers") or []),
        evidence_strength,
    ]
    return "|".join(str(value) for value in values)


def _round_key(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.3f}"
    return "-" if value is None else str(value)

def _ai_summary_item(row: sqlite3.Row) -> AiSummaryItem:
    return AiSummaryItem(
        kind=row["kind"],
        title=_ai_summary_title(row["kind"]),
        trading_date=row["trading_date"],
        generated_at=datetime.fromisoformat(row["generated_at"]),
        source_data_time=datetime.fromisoformat(row["source_data_time"]) if row["source_data_time"] else None,
        model=row["model"],
        status=row["status"],
        summary=row["summary"],
        error=row["error"],
        payload=json.loads(row["payload"]),
    )


def _ai_summary_title(kind: str) -> str:
    if kind.startswith("direction_shift"):
        return "方向突变复核"
    return {
        "opening_auction": "早盘方向探索",
        "midday": "午盘方向复盘",
        "closing": "晚盘方向复盘",
        "direction_shift": "方向突变复核",
    }.get(kind, kind)


def _alert_event(row: sqlite3.Row) -> AlertEvent:
    return AlertEvent(
        id=row["id"],
        code=row["code"],
        alert_at=datetime.fromisoformat(row["alert_at"]),
        level=row["level"],
        event=row["event"],
        message=row["message"],
        delivered=bool(row["delivered"]),
        error=row["error"],
        payload=json.loads(row["payload"]),
    )
