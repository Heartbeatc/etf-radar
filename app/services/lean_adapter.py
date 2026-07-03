from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.adapters.store import Store
from app.domain.models import (
    DailyBar,
    LeanExportFile,
    LeanExportReport,
    Position,
    StrategyValidationReport,
)
from app.services.backtest import ENTRY_SIGNALS, _exit_reason, _snapshot_from_daily
from app.services.scoring import AnalysisInputs, build_plan

PROJECT_DIR_NAME = "AShareDirectionPullback"
MIN_SIGNAL_PREFIX_BARS = 25
DEFAULT_POSITION_SIZE = 0.2
DEFAULT_SLIPPAGE_BPS = 10
DEFAULT_FEE_PER_TRADE = 5


def export_lean_project(store: Store, validation: StrategyValidationReport, export_root: str | Path) -> LeanExportReport:
    project_name = _safe_name(validation.strategy.id or "a_share_direction_pullback_v1")
    workspace = Path(export_root) / project_name
    project_dir = workspace / PROJECT_DIR_NAME
    data_dir = workspace / "data" / "a_share_daily"
    project_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    universe = validation.strategy.universe
    names = {item.code: item.name for item in validation.items}
    roles = {item.code: item.role for item in validation.items}
    validation_by_code = {item.code: item for item in validation.items}
    all_dates: list[str] = []
    signal_payload: dict[str, dict[str, list[dict[str, Any]]]] = {}
    signal_count = 0
    files: list[LeanExportFile] = []
    warnings: list[str] = []

    for code in universe:
        bars = store.get_daily_bars(code)[-validation.days :]
        if not bars:
            warnings.append(f"{code} has no daily bars; LEAN export includes no price data for it.")
            continue
        all_dates.extend(bar.date for bar in bars)
        data_file = data_dir / f"{code}.csv"
        _write_daily_csv(data_file, bars)
        files.append(_file_record(data_file, "LEAN local custom daily data"))
        events = _signal_events(code, names.get(code, code), roles.get(code, "candidate"), bars)
        signal_payload[code] = _signals_by_date(events)
        signal_count += len(events)

    spec_payload = validation.strategy.model_dump(mode="json")
    spec_payload["engine"] = "lean_export_adapter"
    spec_payload["lean_integration_status"] = "project_exported_not_executed"
    validation_payload = validation.model_dump(mode="json")
    validation_payload["strategy"] = spec_payload

    project_files = {
        project_dir / "config.json": _project_config(validation),
        project_dir / "strategy_spec.json": spec_payload,
        project_dir / "validation_report.json": validation_payload,
        project_dir / "strategy_signals.json": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "etf-radar internal signal replay",
            "position_size": DEFAULT_POSITION_SIZE,
            "signals": signal_payload,
        },
        project_dir / "main.py": _lean_algorithm_py(universe, names, validation_by_code),
        workspace / "README.md": _readme(workspace, validation, signal_count),
    }

    for file_path, payload in project_files.items():
        if isinstance(payload, str):
            _write_text(file_path, payload)
        else:
            _write_json(file_path, payload)
        files.append(_file_record(file_path, _purpose(file_path.name)))

    start_date = min(all_dates) if all_dates else None
    end_date = max(all_dates) if all_dates else None
    if signal_count == 0:
        warnings.append("No entry/exit events were generated from the current internal signal replay.")
    warnings.append("LEAN project export is generated but not executed; install/init Lean CLI before running the command.")

    return LeanExportReport(
        generated_at=datetime.now(timezone.utc),
        status="exported_not_executed",
        project_name=PROJECT_DIR_NAME,
        workspace_path=str(workspace),
        project_path=str(project_dir),
        lean_cli_command=f"cd {workspace} && lean backtest {PROJECT_DIR_NAME}",
        universe=universe,
        start_date=start_date,
        end_date=end_date,
        signal_count=signal_count,
        files=files,
        warnings=_dedupe(warnings),
        assumptions=[
            "This adapter exports a LEAN project; it does not execute LEAN or place orders.",
            "A-share prices are exported as LEAN custom daily data because local LEAN does not include free A-share market data by default.",
            "Orders are replayed from etf-radar's internal signal ledger so LEAN can apply event-driven portfolio, fill, fee, and slippage models in the next phase.",
            "Default generated algorithm uses 20% allocation per symbol, 10 bps slippage placeholder, and a flat fee placeholder; these must be calibrated before trusting results.",
            "Run results from this project are research evidence only, not trading instructions.",
        ],
    )


def _signal_events(code: str, name: str, role: str, bars: list[DailyBar]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if len(bars) < MIN_SIGNAL_PREFIX_BARS + 2:
        return events

    position: dict[str, float] | None = None
    for idx in range(MIN_SIGNAL_PREFIX_BARS, len(bars) - 1):
        current = bars[idx]
        prev = bars[idx - 1]
        prefix = bars[: idx + 1]
        position_model = None
        if position:
            position_model = Position(
                code=code,
                entry_price=position["entry_price"],
                shares=None,
                note="lean-export",
                updated_at=datetime.now(timezone.utc),
            )
        snapshot = _snapshot_from_daily(code, name, role, current, prev, prefix)
        plan = build_plan(
            AnalysisInputs(
                snapshot=snapshot,
                daily=prefix,
                minute=[],
                position=position_model,
                stale_seconds=10**9,
            )
        )
        next_bar = bars[idx + 1]
        if position:
            exit_reason = _exit_reason(plan, current)
            if exit_reason or idx == len(bars) - 2:
                reason = exit_reason or "period_end"
                events.append(
                    {
                        "date": next_bar.date,
                        "action": "SELL",
                        "reason": reason,
                        "source_signal": plan.signal,
                        "reference_price": round(next_bar.open, 4),
                    }
                )
                position = None
            continue
        if plan.signal in ENTRY_SIGNALS and plan.risk_score < 75:
            events.append(
                {
                    "date": next_bar.date,
                    "action": "BUY",
                    "reason": plan.signal,
                    "source_signal": plan.signal,
                    "reference_price": round(next_bar.open, 4),
                }
            )
            position = {"entry_price": next_bar.open}
    return events


def _signals_by_date(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault(event["date"], []).append(event)
    return grouped


def _write_daily_csv(path: Path, bars: list[DailyBar]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "open", "high", "low", "close", "volume", "amount", "turnover_pct", "change_pct"])
        for bar in bars:
            writer.writerow(
                [
                    bar.date,
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.volume,
                    bar.amount,
                    bar.turnover_pct if bar.turnover_pct is not None else "",
                    bar.change_pct if bar.change_pct is not None else "",
                ]
            )


def _project_config(validation: StrategyValidationReport) -> dict[str, Any]:
    return {
        "algorithm-language": "Python",
        "algorithm-type-name": "AShareDirectionPullbackAlgorithm",
        "algorithm-location": "main.py",
        "parameters": {
            "strategy-id": validation.strategy.id,
            "validation-days": str(validation.days),
            "position-size": str(DEFAULT_POSITION_SIZE),
            "slippage-bps": str(DEFAULT_SLIPPAGE_BPS),
            "fee-per-trade": str(DEFAULT_FEE_PER_TRADE),
        },
        "description": "Generated by etf-radar LEAN adapter. Research backtest only.",
    }


def _lean_algorithm_py(universe: list[str], names: dict[str, str], validation_by_code: dict[str, Any]) -> str:
    universe_payload = [
        {
            "code": code,
            "name": names.get(code, code),
            "validation_state": getattr(validation_by_code.get(code), "validation_state", "unknown"),
            "validation_score": getattr(validation_by_code.get(code), "validation_score", None),
        }
        for code in universe
    ]
    return f'''from AlgorithmImports import *
import json
import os
from datetime import datetime, timedelta

UNIVERSE = {json.dumps(universe_payload, ensure_ascii=False, indent=4)}
POSITION_SIZE = {DEFAULT_POSITION_SIZE}
SLIPPAGE_RATE = {DEFAULT_SLIPPAGE_BPS / 10000:.6f}
FEE_PER_TRADE = {DEFAULT_FEE_PER_TRADE}


class AShareDaily(PythonData):
    def GetSource(self, config, date, isLiveMode):
        path = os.path.join(Globals.DataFolder, "a_share_daily", f"{{config.Symbol.Value}}.csv")
        return SubscriptionDataSource(path, SubscriptionTransportMedium.LocalFile)

    def Reader(self, config, line, date, isLiveMode):
        if not line or line.startswith("date"):
            return None
        parts = line.split(",")
        if len(parts) < 7:
            return None
        bar = AShareDaily()
        bar.Symbol = config.Symbol
        bar.Time = datetime.strptime(parts[0], "%Y-%m-%d")
        bar.EndTime = bar.Time + timedelta(days=1)
        bar.Value = float(parts[4])
        bar["open"] = float(parts[1])
        bar["high"] = float(parts[2])
        bar["low"] = float(parts[3])
        bar["close"] = float(parts[4])
        bar["volume"] = float(parts[5] or 0)
        bar["amount"] = float(parts[6] or 0)
        return bar


class FlatAshareFeeModel(FeeModel):
    def GetOrderFee(self, parameters):
        return OrderFee(CashAmount(FEE_PER_TRADE, "CNY"))


class AShareDirectionPullbackAlgorithm(QCAlgorithm):
    def Initialize(self):
        signal_path = os.path.join(os.path.dirname(__file__), "strategy_signals.json")
        with open(signal_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self.signals = payload.get("signals", {{}})
        self.symbol_by_code = {{}}
        self.SetCash("CNY", 100000)

        dates = [day for by_day in self.signals.values() for day in by_day.keys()]
        if dates:
            start = datetime.strptime(min(dates), "%Y-%m-%d")
            end = datetime.strptime(max(dates), "%Y-%m-%d")
            self.SetStartDate(start.year, start.month, start.day)
            self.SetEndDate(end.year, end.month, end.day)

        for item in UNIVERSE:
            code = item["code"]
            symbol = self.AddData(AShareDaily, code, Resolution.Daily).Symbol
            security = self.Securities[symbol]
            security.SetLeverage(1)
            security.SetFeeModel(FlatAshareFeeModel())
            try:
                security.SetSlippageModel(ConstantSlippageModel(SLIPPAGE_RATE))
            except Exception:
                self.Debug("ConstantSlippageModel unavailable; using LEAN default slippage model")
            self.symbol_by_code[code] = symbol

    def OnData(self, data):
        day = self.Time.strftime("%Y-%m-%d")
        for code, symbol in self.symbol_by_code.items():
            if not data.ContainsKey(symbol):
                continue
            for event in self.signals.get(code, {{}}).get(day, []):
                action = event.get("action")
                reason = event.get("reason", "signal")
                if action == "BUY" and not self.Portfolio[symbol].Invested:
                    self.SetHoldings(symbol, POSITION_SIZE, tag=reason)
                elif action == "SELL" and self.Portfolio[symbol].Invested:
                    self.Liquidate(symbol, tag=reason)
'''


def _readme(workspace: Path, validation: StrategyValidationReport, signal_count: int) -> str:
    return f'''# etf-radar LEAN Export

This directory is generated by etf-radar from `StrategySpec` `{validation.strategy.id}`.

## Run

```bash
cd {workspace}
lean backtest {PROJECT_DIR_NAME}
```

If Lean CLI complains that the workspace is not initialized, run `lean init` in this directory first, then run the same backtest command.

## Contents

- `{PROJECT_DIR_NAME}/main.py`: LEAN Python algorithm adapter.
- `{PROJECT_DIR_NAME}/strategy_spec.json`: exact strategy rules exported from etf-radar.
- `{PROJECT_DIR_NAME}/validation_report.json`: validation gate report used for this export.
- `{PROJECT_DIR_NAME}/strategy_signals.json`: precomputed internal BUY/SELL signal replay.
- `data/a_share_daily/*.csv`: local A-share daily custom data files.

## Current Export

- Universe: {', '.join(validation.strategy.universe) or 'empty'}
- Signals: {signal_count}
- Validation: pass {validation.pass_count}, warning {validation.warning_count}, fail {validation.fail_count}

This is a research adapter. It is not an automatic trading bridge.
'''


def _write_json(path: Path, payload: Any) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _file_record(path: Path, purpose: str) -> LeanExportFile:
    data = path.read_bytes()
    return LeanExportFile(path=str(path), purpose=purpose, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def _purpose(name: str) -> str:
    return {
        "config.json": "LEAN project configuration",
        "strategy_spec.json": "serialized etf-radar StrategySpec",
        "validation_report.json": "strategy validation gate report",
        "strategy_signals.json": "precomputed BUY/SELL signal replay",
        "main.py": "LEAN Python algorithm adapter",
        "README.md": "operator runbook",
    }.get(name, "LEAN export artifact")


def _safe_name(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip())
    return normalized or "a_share_direction_pullback_v1"


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
