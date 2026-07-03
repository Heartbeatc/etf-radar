import { useEffect, useState } from 'react';
import type { AccountInput, PortfolioSnapshotResponse, PositionExitInput, PositionInput, QuantDecisionResponse, QuantDirectionDecision, QuantHoldingDecision, QuantStockDecision, TradeJournalResponse } from '../../types';
import { formatDateTime, formatScore } from './formatters';

interface QuantWorkbenchProps {
  decision?: QuantDecisionResponse;
  tradeJournal?: TradeJournalResponse;
  portfolio?: PortfolioSnapshotResponse;
  onRefresh: () => void;
  refreshing: boolean;
  onLogout: () => void;
  onSaveAccount: (input: AccountInput) => void;
  onSavePosition: (code: string, input: PositionInput) => void;
  onClosePosition: (code: string, input: PositionExitInput) => void;
  onDeletePosition: (code: string) => void;
  savingAccount: boolean;
  savingPosition: boolean;
  closingPosition: boolean;
  deletingPosition: boolean;
  errorMessage: string | null;
}

export function QuantWorkbench({
  decision,
  tradeJournal,
  portfolio,
  onRefresh,
  refreshing,
  onLogout,
  onSaveAccount,
  onSavePosition,
  onClosePosition,
  onDeletePosition,
  savingAccount,
  savingPosition,
  closingPosition,
  deletingPosition,
  errorMessage
}: QuantWorkbenchProps) {
  const direction = decision?.direction;
  const holdings = decision?.holdings ?? [];
  const candidates = pickStocks(decision?.bottom_candidates ?? []);
  const [cashBalance, setCashBalance] = useState('');
  const [frozenCash, setFrozenCash] = useState('');
  const [accountNote, setAccountNote] = useState('');
  const [code, setCode] = useState('');
  const [entryPrice, setEntryPrice] = useState('');
  const [shares, setShares] = useState('');
  const [entryDate, setEntryDate] = useState(todayText());
  const [note, setNote] = useState('');

  useEffect(() => {
    if (!portfolio?.account) return;
    setCashBalance(String(portfolio.account.cash_balance));
    setFrozenCash(String(portfolio.account.frozen_cash));
    setAccountNote(portfolio.account.note ?? '');
  }, [portfolio?.account?.updated_at]);

  const saveAccount = () => {
    const parsedCash = Number(cashBalance);
    const parsedFrozen = frozenCash.trim() ? Number(frozenCash) : 0;
    if (!Number.isFinite(parsedCash) || parsedCash < 0) {
      window.alert('请输入有效现金余额');
      return;
    }
    if (!Number.isFinite(parsedFrozen) || parsedFrozen < 0) {
      window.alert('冻结资金不能为负数');
      return;
    }
    if (parsedFrozen > parsedCash) {
      window.alert('冻结资金不能大于现金余额');
      return;
    }
    onSaveAccount({ cash_balance: parsedCash, frozen_cash: parsedFrozen, note: accountNote.trim() });
  };

  const save = () => {
    const normalized = code.trim();
    const parsedEntry = Number(entryPrice);
    const parsedShares = shares.trim() ? Number(shares) : null;
    if (!/^\d{6}$/.test(normalized)) {
      window.alert('请输入6位A股代码');
      return;
    }
    if (!Number.isFinite(parsedEntry) || parsedEntry <= 0) {
      window.alert('请输入有效成本价');
      return;
    }
    if (parsedShares !== null && (!Number.isFinite(parsedShares) || parsedShares <= 0)) {
      window.alert('数量必须大于0，或留空');
      return;
    }
    onSavePosition(normalized, {
      entry_price: parsedEntry,
      shares: parsedShares,
      entry_date: entryDate || null,
      note: note.trim()
    });
  };

  return (
    <main className="quant-page">
      <section className="quant-toolbar" aria-label="系统状态">
        <div>
          <strong>A股量化执行表</strong>
          <span>{formatMarketStatus(decision)} · 行情 {formatDateTime(decision?.data_time)} · {formatDataAgeLabel(decision)}</span>
        </div>
        <div className="toolbar-actions">
          <button type="button" onClick={onRefresh} disabled={refreshing}>{refreshing ? '刷新中' : '刷新'}</button>
          <button type="button" onClick={onLogout}>退出</button>
        </div>
      </section>

      {errorMessage ? <div className="quant-error">{errorMessage}</div> : null}

      <table className="quant-sheet" aria-label="A股量化执行表">
        <thead>
          <tr>
            <th>类型</th>
            <th>标的</th>
            <th>状态</th>
            <th>关键价</th>
            <th>动作</th>
            <th>备注</th>
          </tr>
        </thead>
        <tbody>
          <MarketRow decision={decision} direction={direction} />
          <PortfolioRow portfolio={portfolio} />
          <TradeSummaryRow journal={tradeJournal} />
          {holdings.map((holding) => (
            <HoldingRow
              key={holding.code}
              item={holding}
              onClose={onClosePosition}
              onDelete={onDeletePosition}
              closing={closingPosition}
              deleting={deletingPosition}
            />
          ))}
          {holdings.length === 0 && candidates.map((stock) => (
            <CandidateRow key={stock.code} item={stock} />
          ))}
          {holdings.length === 0 && candidates.length === 0 ? <EmptyRow /> : null}
        </tbody>
      </table>

      <section className="position-strip account-strip" aria-label="录入账户资金">
        <strong>账户资金</strong>
        <input value={cashBalance} onChange={(event) => setCashBalance(event.target.value)} placeholder="现金余额" inputMode="decimal" />
        <input value={frozenCash} onChange={(event) => setFrozenCash(event.target.value)} placeholder="冻结资金" inputMode="decimal" />
        <input className="note-input" value={accountNote} onChange={(event) => setAccountNote(event.target.value)} placeholder="备注可空" />
        <button type="button" onClick={saveAccount} disabled={savingAccount}>{savingAccount ? '保存中' : '保存账户'}</button>
      </section>

      <section className="position-strip" aria-label="录入持仓">
        <strong>录入持仓</strong>
        <input value={code} onChange={(event) => setCode(event.target.value)} placeholder="代码" maxLength={6} />
        <input value={entryPrice} onChange={(event) => setEntryPrice(event.target.value)} placeholder="成本" inputMode="decimal" />
        <input value={shares} onChange={(event) => setShares(event.target.value)} placeholder="数量可空" inputMode="decimal" />
        <input value={entryDate} onChange={(event) => setEntryDate(event.target.value)} type="date" />
        <input className="note-input" value={note} onChange={(event) => setNote(event.target.value)} placeholder="备注可空" />
        <button type="button" onClick={save} disabled={savingPosition}>{savingPosition ? '保存中' : '保存'}</button>
      </section>
    </main>
  );
}

function MarketRow({ decision, direction }: { decision?: QuantDecisionResponse; direction?: QuantDirectionDecision }) {
  const capital = capitalStatus(direction);
  return (
    <tr>
      <td>市场</td>
      <td>
        <strong>{direction?.direction_label ?? '暂无方向'}</strong>
        <span>7日 {scoreText(direction?.seven_day_score)} / 主线 {scoreText(direction?.mainline_probability)}</span>
      </td>
      <td>
        <strong className={`capital-${capital.kind}`}>{capital.label}</strong>
        <span>{direction?.phase_label ?? '无阶段'} · {confidenceLabel(direction?.confidence)}</span>
      </td>
      <td>
        <strong>{decision?.should_poll_realtime ? '实时' : '闭市快照'}</strong>
        <span>下个交易日 {decision?.next_trading_day ?? '-'}</span>
      </td>
      <td>
        <strong>{marketAction(direction, decision)}</strong>
        <span>{decision?.should_poll_realtime ? '盘中按信号更新' : '闭市不产生新买点'}</span>
      </td>
      <td>{shortText(decision?.conclusion ?? decision?.market_note ?? '等待数据', 46)}</td>
    </tr>
  );
}

function PortfolioRow({ portfolio }: { portfolio?: PortfolioSnapshotResponse }) {
  const warning = portfolio?.warnings?.[0];
  return (
    <tr className="portfolio-row">
      <td>账户</td>
      <td>
        <strong>总资产 {moneyText(portfolio?.total_assets)}</strong>
        <span>持仓 {portfolio?.positions.length ?? 0} 个 / 市值 {moneyText(portfolio?.total_market_value)}</span>
      </td>
      <td>
        <strong>仓位 {pctText(portfolio?.position_exposure_pct)}</strong>
        <span>浮盈亏 {amountText(portfolio?.unrealized_profit_amount)} / {pctText(portfolio?.unrealized_profit_pct)}</span>
      </td>
      <td>
        <strong>可用 {moneyText(portfolio?.available_cash)}</strong>
        <span>现金 {moneyText(portfolio?.cash_balance)} / 冻结 {moneyText(portfolio?.frozen_cash)}</span>
      </td>
      <td>
        <strong>可操作 {moneyText(portfolio?.risk_budget.operable_cash)}</strong>
        <span>单票上限 {moneyText(portfolio?.risk_budget.max_single_trade_cash)}</span>
      </td>
      <td>{shortText(warning ?? portfolio?.risk_budget.risk_note ?? '账户资金未录入', 54)}</td>
    </tr>
  );
}

function TradeSummaryRow({ journal }: { journal?: TradeJournalResponse }) {
  const summary = journal?.summary;
  return (
    <tr className="journal-row">
      <td>账本</td>
      <td>
        <strong>已平仓 {summary?.closed_trade_count ?? 0} 笔</strong>
        <span>当前持仓 {summary?.open_position_count ?? 0} 个</span>
      </td>
      <td>
        <strong>胜率 {pctText(summary?.win_rate_pct)}</strong>
        <span>均值 {pctText(summary?.average_return_pct)}</span>
      </td>
      <td>
        <strong>已实现 {amountText(summary?.realized_profit_amount)}</strong>
        <span>按你录入的成交价计算</span>
      </td>
      <td>
        <strong>最好 {pctText(summary?.best_return_pct)}</strong>
        <span>最差 {pctText(summary?.worst_return_pct)}</span>
      </td>
      <td>卖出后必须入账，否则系统无法计算真实收益、胜率和策略质量。</td>
    </tr>
  );
}

function HoldingRow({
  item,
  onClose,
  onDelete,
  closing,
  deleting
}: {
  item: QuantHoldingDecision;
  onClose: (code: string, input: PositionExitInput) => void;
  onDelete: (code: string) => void;
  closing: boolean;
  deleting: boolean;
}) {
  const close = () => {
    const priceText = window.prompt(`卖出价格：${item.code} ${item.name}`, item.current_price ? item.current_price.toFixed(2) : '');
    if (priceText === null) return;
    const exitPrice = Number(priceText);
    if (!Number.isFinite(exitPrice) || exitPrice <= 0) {
      window.alert('请输入有效卖出价格');
      return;
    }

    const sharesText = window.prompt('卖出数量，留空表示全部平仓', item.shares ? String(item.shares) : '');
    if (sharesText === null) return;
    const parsedShares = sharesText.trim() ? Number(sharesText) : null;
    if (parsedShares !== null && (!Number.isFinite(parsedShares) || parsedShares <= 0)) {
      window.alert('卖出数量必须大于0，或留空');
      return;
    }

    const exitDate = window.prompt('卖出日期', todayText()) ?? todayText();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(exitDate)) {
      window.alert('卖出日期格式必须是 YYYY-MM-DD');
      return;
    }

    const feeText = window.prompt('手续费/税费，留空为0', '0');
    if (feeText === null) return;
    const fee = feeText.trim() ? Number(feeText) : 0;
    if (!Number.isFinite(fee) || fee < 0) {
      window.alert('费用不能为负数');
      return;
    }

    const reason = window.prompt('卖出原因：止损 / 止盈 / 手动 / 风控', item.action_label) ?? '';
    onClose(item.code, {
      exit_price: exitPrice,
      shares: parsedShares,
      exit_date: exitDate,
      reason: reason.trim(),
      note: item.exit_plan,
      fee
    });
  };

  const deleteWithoutJournal = () => {
    if (window.confirm('只在录错持仓时删除。真实卖出请用“卖出记录”，否则收益不会入账。')) {
      onDelete(item.code);
    }
  };

  return (
    <tr className="holding-row">
      <td>持仓</td>
      <td>
        <strong>{item.code} {item.name}</strong>
        <span>{sharesText(item.shares)} / 成本 {priceText(item.entry_price)} / 买入 {item.entry_date ?? '-'}</span>
      </td>
      <td>
        <strong className={`holding-action holding-${item.risk_level}`}>{item.action_label}</strong>
        <span>{mainForceLabel(item.main_force_state)} · {directionMatchLabel(item.direction_match)}</span>
      </td>
      <td>
        <strong>现价 {priceText(item.current_price)}</strong>
        <span>市值 {moneyText(item.market_value)} / 弱防 {priceText(item.weak_exit_price)} / 止损 {priceText(item.stop_price)}</span>
      </td>
      <td>
        <strong>{item.can_add_position ? '可小幅滚动' : '不补仓'}</strong>
        <span>反抽 {priceText(item.rebound_reduce_price)} / 止盈 {priceText(item.take_profit_price)}</span>
      </td>
      <td>
        <strong className={pnlClass(item.floating_profit_pct)}>浮盈亏 {pctText(item.floating_profit_pct)}</strong>
        <span>{shortText(item.exit_plan, 42)}</span>
        {item.ai_risk_review ? <span className={`ai-risk ai-risk-${item.ai_risk_review.risk_level}`}>AI {shortText(item.ai_risk_review.conclusion, 34)}</span> : null}
        <span className="row-actions">
          <button type="button" className="link-button primary-link" onClick={close} disabled={closing}>卖出记录</button>
          <button type="button" className="link-button" onClick={deleteWithoutJournal} disabled={deleting}>删除不记账</button>
        </span>
      </td>
    </tr>
  );
}

function CandidateRow({ item }: { item: QuantStockDecision }) {
  const execution = item.execution;
  return (
    <tr>
      <td>候选</td>
      <td>
        <strong>{item.code} {item.name}</strong>
        <span>{stockRoleLabel(item.verifier_role)} / 抄底 {formatScore(item.bottom_score)} / 强度 {formatScore(item.score)}</span>
      </td>
      <td>
        <strong>{execution?.decision_label ?? actionLabel(item.action)}</strong>
        <span>{item.direction_label ?? '-'}</span>
      </td>
      <td>
        <strong>现价 {priceText(item.price)}</strong>
        <span>低吸 {rangeText(execution?.buy_zone_low, execution?.buy_zone_high)}</span>
      </td>
      <td>
        <strong>{execution?.decision_state === 'buy_probe' ? '可试仓' : '等待'}</strong>
        <span>防守 {priceText(execution?.stop_price)} / 止盈 {priceText(execution?.take_profit_price)}</span>
      </td>
      <td>{shortText(execution?.decision_reason ?? item.operation, 46)}</td>
    </tr>
  );
}

function EmptyRow() {
  return (
    <tr>
      <td>空仓</td>
      <td colSpan={5}>暂无满足条件的买入候选。没有价格、方向、承接同时达标，就不交易。</td>
    </tr>
  );
}

function pickStocks(items: QuantStockDecision[]): QuantStockDecision[] {
  const actionRank: Record<string, number> = {
    BUY_PROBE: 0,
    WAIT_CONFIRMATION: 1,
    WAIT_BUY_ZONE: 2,
    WAIT_PULLBACK: 3,
    DO_NOT_CHASE: 4,
    OBSERVE_NEXT_DAY: 5,
    VERIFY_ONLY: 6,
    VERIFY_DIRECTION: 7,
    AVOID: 8,
    WATCH: 9
  };
  return [...items]
    .filter((item) => item.code && item.name)
    .sort((a, b) => (actionRank[a.action] ?? 50) - (actionRank[b.action] ?? 50) || b.bottom_score - a.bottom_score || b.score - a.score)
    .slice(0, 3);
}

function formatMarketStatus(decision?: QuantDecisionResponse): string {
  if (!decision) return '等待数据';
  const label = decision.market_status_label || marketStatusFallback(decision.market_status);
  return decision.should_poll_realtime ? label : `${label} / 下个交易日 ${decision.next_trading_day ?? '-'}`;
}

function marketStatusFallback(value: string | null | undefined): string {
  const map: Record<string, string> = {
    trading: '交易中',
    pre_open: '开盘前',
    midday_break: '午间休市',
    post_close: '已收盘',
    closed_weekend: '周末休市',
    closed_holiday: '节假日休市',
    closed: '非交易时段'
  };
  return value ? map[value] ?? value : '-';
}

function formatDataAgeLabel(decision?: QuantDecisionResponse): string {
  if (!decision) return '等待数据';
  if (!decision.should_poll_realtime) return '闭市快照';
  const value = decision.data_age_seconds;
  if (value == null || !Number.isFinite(value)) return '数据未知';
  if (value < 60) return `${Math.max(0, Math.round(value))}秒`;
  return `${Math.round(value / 60)}分`;
}

function marketAction(direction?: QuantDirectionDecision, decision?: QuantDecisionResponse): string {
  if (!decision?.should_poll_realtime) return '不追盘后数据';
  if (!direction || direction.phase === 'no_direction') return '等待';
  if (direction.phase === 'main_up_low_buy') return '等低吸';
  if (direction.phase === 'main_up_hold') return '持有优先';
  if (direction.phase === 'weakening' || direction.phase === 'weak') return '防守';
  return '观察';
}

function capitalStatus(direction?: QuantDirectionDecision): { label: string; kind: string } {
  if (!direction || direction.phase === 'no_direction') return { label: '不在', kind: 'off' };
  const probability = direction.mainline_probability ?? direction.phase_score ?? 0;
  const residency = direction.residency_score ?? 0;
  const retention = direction.retention_score ?? 0;
  if (probability >= 70 && residency >= 60 && retention >= 55) return { label: '在', kind: 'on' };
  if (probability >= 55 && (residency >= 45 || retention >= 45)) return { label: '试探', kind: 'test' };
  if (probability >= 40) return { label: '观察', kind: 'watch' };
  return { label: '不在', kind: 'off' };
}

function mainForceLabel(value: string) {
  const map: Record<string, string> = { present: '主力在', watch: '试探', weak: '走弱', left: '疑似撤退', unknown: '未知' };
  return map[value] ?? value;
}

function directionMatchLabel(value: string) {
  const map: Record<string, string> = { frontline: '前排方向', related: '相关方向', not_frontline: '非前排', unknown: '未知' };
  return map[value] ?? value;
}

function stockRoleLabel(value: string | null | undefined): string {
  const map: Record<string, string> = { leader: '龙头', second_leader: '二龙', expansion: '扩散' };
  return value ? map[value] ?? value : '候选';
}

function confidenceLabel(value: string | null | undefined): string {
  const map: Record<string, string> = { high: '高置信', medium: '中置信', 'medium-low': '中低置信', low: '低置信' };
  return value ? map[value] ?? value : '-';
}

function actionLabel(value: string | null | undefined): string {
  const map: Record<string, string> = {
    BUY_PROBE: '可试仓',
    WAIT_CONFIRMATION: '等承接',
    WAIT_BUY_ZONE: '等低吸区',
    WATCH_LOW_BUY: '等低吸',
    WAIT_PULLBACK: '等回踩',
    DO_NOT_CHASE: '不追高',
    OBSERVE_NEXT_DAY: '看次日',
    VERIFY_ONLY: '只验证',
    VERIFY_DIRECTION: '验证方向',
    AVOID: '回避',
    WATCH: '观察'
  };
  return value ? map[value] ?? value : '等待';
}

function scoreText(value: number | null | undefined): string {
  return value == null ? '-' : formatScore(value);
}

function priceText(value: number | null | undefined): string {
  return value == null ? '-' : value.toFixed(2);
}

function pctText(value: number | null | undefined): string {
  return value == null ? '-' : `${value.toFixed(2)}%`;
}

function amountText(value: number | null | undefined): string {
  if (value == null) return '-';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}`;
}

function moneyText(value: number | null | undefined): string {
  if (value == null) return '-';
  if (Math.abs(value) >= 10000) return `${(value / 10000).toFixed(2)}万`;
  return value.toFixed(2);
}

function sharesText(value: number | null | undefined): string {
  if (value == null) return '数量未录';
  return `${value.toFixed(0)}股/${(value / 100).toFixed(1)}手`;
}

function rangeText(low: number | null | undefined, high: number | null | undefined): string {
  if (low == null || high == null) return '-';
  return `${low.toFixed(2)}-${high.toFixed(2)}`;
}

function pnlClass(value: number | null | undefined): string {
  if (value == null) return '';
  return value < 0 ? 'loss-text' : 'profit-text';
}

function shortText(value: string | null | undefined, max = 60): string {
  const text = (value ?? '').trim();
  if (!text) return '-';
  return text.length > max ? `${text.slice(0, max)}...` : text;
}

function todayText() {
  return new Date().toISOString().slice(0, 10);
}
