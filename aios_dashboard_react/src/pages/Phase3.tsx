import { useEffect, useMemo, useState } from 'react';
import type { AuditEvent, NotificationDedupState, Order, Position, SchedulerJobRun, Trade } from '../api/types';
import { getPhase3Audit, getPhase3Dedup, getPhase3Orders, getPhase3Positions, getPhase3Scheduler, getPhase3Trades } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import Icon from '../components/Icon';
import { formatDateTime, formatIdr, downloadCsv, downloadMarkdown } from '../lib/format';
import { PageReveal, EASE_OUT } from '../motion/Motion';
import { AnimatePresence, motion } from 'framer-motion';
import NumberFlow from '@number-flow/react';
import { useReducedMotionSafe } from '../hooks/useReducedMotionSafe';
import { useVaultMotion } from '../hooks/useVaultMotion';

type Tab = 'positions' | 'orders' | 'trades' | 'equity' | 'scheduler';

function statusBadge(s: string) {
  switch (s) {
    case 'OPEN': case 'FILLED': case 'SUCCESS': return 'badge badge-status-available';
    case 'CLOSED': case 'RUNNING': return 'badge badge-status-available';
    case 'FAILED': case 'REJECTED': return 'badge badge-status-no-data';
    case 'PARTIALLY_FILLED': case 'INSUFFICIENT_DATA': return 'badge badge-status-insufficient-data';
    default: return 'badge bg-secondary';
  }
}
function actionBadge(a: string) {
  switch (a) {
    case 'BUY': return 'badge badge-status-available';
    case 'SELL': return 'badge badge-status-no-data';
    default: return 'badge bg-secondary';
  }
}
function jobBadge(s: string) {
  switch (s) {
    case 'SUCCESS': return 'badge badge-status-available';
    case 'RUNNING': return 'badge badge-status-available';
    case 'FAILED': return 'badge badge-status-no-data';
    default: return 'badge bg-secondary';
  }
}
function dedupBadge(s: string) {
  switch (s) {
    case 'SENT': return 'badge badge-status-available';
    case 'SUPPRESSED': return 'badge badge-status-insufficient-data';
    case 'FAILED': return 'badge badge-status-no-data';
    default: return 'badge bg-secondary';
  }
}

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: 'positions', label: 'Positions', icon: 'book-open' },
  { id: 'orders', label: 'Orders', icon: 'file-text' },
  { id: 'trades', label: 'Trades', icon: 'activity' },
  { id: 'equity', label: 'Equity/P&L', icon: 'arrow-up-right' },
  { id: 'scheduler', label: 'Scheduler', icon: 'settings' },
];

export default function Phase3() {
  const prefersReduced = useReducedMotionSafe();
  const [tab, setTab] = useState<Tab>('positions');
  const positionsP = usePolling<Position[]>(() => getPhase3Positions(), 30_000, { immediate: true });
  const ordersP = usePolling<Order[]>(() => getPhase3Orders(), 30_000, { immediate: true });
  const tradesP = usePolling<Trade[]>(() => getPhase3Trades(), 30_000, { immediate: true });
  const schedP = usePolling<SchedulerJobRun[]>(() => getPhase3Scheduler(), 30_000, { immediate: true });
  const dedupP = usePolling<NotificationDedupState[]>(() => getPhase3Dedup(), 30_000, { immediate: true });
  const auditP = usePolling<AuditEvent[]>(() => getPhase3Audit(50), 30_000, { immediate: true });

  const positions = positionsP.data ?? [];
  const orders = ordersP.data ?? [];
  const trades = tradesP.data ?? [];
  const jobs = schedP.data ?? [];
  const dedup = dedupP.data ?? [];
    const audit = auditP.data ?? [];

  const openCount = positions.filter((p) => p.status === 'OPEN').length;
  const closedCount = positions.filter((p) => p.status === 'CLOSED').length;
  const totalPnl = positions.reduce((s, p) => s + p.realizedPnl, 0);
  const totalFees = trades.reduce((s, t) => s + t.fee, 0);

  // Build equity curve (cumulative realized P&L) — same logic as Blazor Phase3.
  const equity = useMemo(() => {
    const closed = positions
      .filter((p) => p.status === 'CLOSED' && p.realizedPnl !== 0)
      .sort((a, b) => a.createdAt.localeCompare(b.createdAt));
    const labels: string[] = [];
    const data: number[] = [];
    let cum = 0;
    for (const p of closed) {
      const d = new Date(p.createdAt);
      if (Number.isNaN(d.getTime())) continue;
      labels.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`);
      cum += p.realizedPnl;
      data.push(cum);
    }
    if (labels.length === 0 && trades.length > 0) {
      const sorted = [...trades].sort((a, b) => a.executedAt.localeCompare(b.executedAt));
      for (const t of sorted) {
        const d = new Date(t.executedAt);
        if (Number.isNaN(d.getTime())) continue;
        labels.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`);
        const pnl = (t.action === 'SELL' ? 1 : -1) * t.fillPrice * t.quantity - t.fee - t.tax;
        cum += pnl;
        data.push(cum);
      }
    }
    return { labels, data };
  }, [positions, trades]);

  // Vault motion layer: per-row + section-head scroll reveals, gated on
  // prefers-reduced-motion (see hooks/useVaultMotion.ts).
  const scopeRef = useVaultMotion<HTMLDivElement>();

  return (
    <div ref={scopeRef}>
    <PageReveal>
      <h1 className="font-display page-title text-2xl font-bold tracking-tight">Paper book &amp; operations</h1>
      <p className="page-sub">Simulated fills only. This page can never touch a real broker.</p>

      <div className="dataline">
        <span className="dl"><span className="lbl">Open positions</span><span className="v">{openCount}</span></span>
        <span className="dl"><span className="lbl">Closed positions</span><span className="v">{closedCount}</span></span>
        <span className="dl"><span className="lbl">Realized P&L</span><span className={`v ${totalPnl >= 0 ? 'pos' : 'neg'}`}>
          {prefersReduced ? formatIdr(totalPnl) : <NumberFlow value={totalPnl} locales="id-ID" format={{ style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }} />}
        </span></span>
        <span className="dl"><span className="lbl">Total fees</span><span className="v">
          {prefersReduced ? formatIdr(totalFees) : <NumberFlow value={totalFees} locales="id-ID" format={{ style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }} />}
        </span></span>
      </div>

      <div className="tabs">
        {TABS.map((t) => (
          <button key={t.id} className={`tab-btn${tab === t.id ? ' active' : ''}`} onClick={() => setTab(t.id)} aria-current={tab === t.id ? 'page' : undefined}>
            <Icon name={t.icon} /> {t.label}
            {tab === t.id && (
              <motion.span className="tab-underline" layoutId="phase3-tab-underline" transition={{ duration: 0.18, ease: EASE_OUT }} />
            )}
          </button>
        ))}
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={tab}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.2, ease: EASE_OUT }}
        >
        <TableCard title="Paper Positions" count={positions.length} loading={positionsP.loading} onCsv={() => downloadCsv(positions, `paper_positions_${new Date().toISOString().slice(0,10)}.csv`)} onMd={() => downloadMarkdown(
          [
            { header: 'Position ID', render: (p: Position) => String(p.positionId) },
            { header: 'Account', render: (p) => p.accountId },
            { header: 'Symbol', render: (p) => p.symbol },
            { header: 'Qty', render: (p) => p.quantity.toFixed(2) },
            { header: 'Avg Price', render: (p) => p.averagePrice.toFixed(2) },
            { header: 'Realized P&L', render: (p) => p.realizedPnl.toFixed(0) },
            { header: 'Status', render: (p) => p.status },
            { header: 'Direction', render: (p) => p.direction },
            { header: 'Stop Loss', render: (p) => p.stopLoss?.toFixed(2) ?? '—' },
            { header: 'Take Profit', render: (p) => p.takeProfit?.toFixed(2) ?? '—' },
            { header: 'Buy Fee Acc.', render: (p) => p.buyFeeAccumulated.toFixed(2) },
            { header: 'Created At', render: (p) => formatDateTime(p.createdAt) },
          ],
          positions, `paper_positions_${new Date().toISOString().slice(0,10)}.md`,
        )}>
          <thead><tr>
            <th>Position ID</th><th>Account</th><th>Symbol</th><th>Qty</th><th>Avg Price</th>
            <th>Realized P&L</th><th>Status</th><th>Direction</th><th>Stop Loss</th><th>Take Profit</th><th>Buy Fee Acc.</th><th>Created At</th>
          </tr></thead>
          <tbody>
            {positions.map((p) => (
              <tr key={p.positionId}>
                <td>{p.positionId}</td><td>{p.accountId}</td><td>{p.symbol}</td><td>{p.quantity.toFixed(2)}</td>
                <td>{p.averagePrice.toFixed(2)}</td>
                <td className={p.realizedPnl >= 0 ? 'text-success' : 'text-danger'}>{p.realizedPnl.toFixed(0)}</td>
                <td><span className={`badge ${statusBadge(p.status)}`}>{p.status}</span></td>
                <td>{p.direction}</td>
                <td>{p.stopLoss?.toFixed(2) ?? '—'}</td><td>{p.takeProfit?.toFixed(2) ?? '—'}</td>
                <td>{p.buyFeeAccumulated.toFixed(2)}</td><td>{formatDateTime(p.createdAt)}</td>
              </tr>
            ))}
          </tbody>
        </TableCard>

      {tab === 'orders' && (
        <TableCard title="Paper Orders" count={orders.length} loading={ordersP.loading} onCsv={() => downloadCsv(orders, `paper_orders_${new Date().toISOString().slice(0,10)}.csv`)} onMd={() => downloadMarkdown(
          [
            { header: 'Order ID', render: (o: Order) => String(o.orderId) },
            { header: 'Account', render: (o) => o.accountId },
            { header: 'Symbol', render: (o) => o.symbol },
            { header: 'Action', render: (o) => o.action },
            { header: 'Qty', render: (o) => o.quantity.toFixed(2) },
            { header: 'Req Price', render: (o) => o.requestedPrice.toFixed(2) },
            { header: 'Filled Price', render: (o) => o.filledPrice.toFixed(2) },
            { header: 'Filled Qty', render: (o) => o.filledQuantity.toFixed(2) },
            { header: 'Status', render: (o) => o.status },
            { header: 'Reason', render: (o) => o.reason },
            { header: 'Created At', render: (o) => formatDateTime(o.createdAt) },
            { header: 'Filled At', render: (o) => formatDateTime(o.filledAt) },
            { header: 'Analysis Snapshot', render: (o) => o.analysisSnapshotId?.toString() ?? '—' },
          ],
          orders, `paper_orders_${new Date().toISOString().slice(0,10)}.md`,
        )}>
          <thead><tr>
            <th>Order ID</th><th>Account</th><th>Symbol</th><th>Action</th><th>Qty</th><th>Req Price</th>
            <th>Filled Price</th><th>Filled Qty</th><th>Status</th><th>Reason</th><th>Created At</th><th>Filled At</th><th>Analysis Snapshot</th>
          </tr></thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.orderId}>
                <td>{o.orderId}</td><td>{o.accountId}</td><td>{o.symbol}</td>
                <td><span className={`badge ${actionBadge(o.action)}`}>{o.action}</span></td>
                <td>{o.quantity.toFixed(2)}</td><td>{o.requestedPrice.toFixed(2)}</td><td>{o.filledPrice.toFixed(2)}</td>
                <td>{o.filledQuantity.toFixed(2)}</td><td><span className={`badge ${statusBadge(o.status)}`}>{o.status}</span></td>
                <td>{o.reason}</td><td>{formatDateTime(o.createdAt)}</td><td>{formatDateTime(o.filledAt)}</td>
                <td>{o.analysisSnapshotId?.toString() ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </TableCard>
      )}

      {tab === 'trades' && (
        <TableCard title="Paper Trades" count={trades.length} loading={tradesP.loading} onCsv={() => downloadCsv(trades, `paper_trades_${new Date().toISOString().slice(0,10)}.csv`)} onMd={() => downloadMarkdown(
          [
            { header: 'Trade ID', render: (t: Trade) => String(t.tradeId) },
            { header: 'Order ID', render: (t) => String(t.orderId) },
            { header: 'Account', render: (t) => t.accountId },
            { header: 'Symbol', render: (t) => t.symbol },
            { header: 'Action', render: (t) => t.action },
            { header: 'Qty', render: (t) => t.quantity.toFixed(2) },
            { header: 'Fill Price', render: (t) => t.fillPrice.toFixed(2) },
            { header: 'Fee', render: (t) => t.fee.toFixed(2) },
            { header: 'Tax', render: (t) => t.tax.toFixed(2) },
            { header: 'Executed At', render: (t) => formatDateTime(t.executedAt) },
          ],
          trades, `paper_trades_${new Date().toISOString().slice(0,10)}.md`,
        )}>
          <thead><tr>
            <th>Trade ID</th><th>Order ID</th><th>Account</th><th>Symbol</th><th>Action</th><th>Qty</th>
            <th>Fill Price</th><th>Fee</th><th>Tax</th><th>Executed At</th>
          </tr></thead>
          <tbody>
            {trades.map((t) => (
              <tr key={t.tradeId}>
                <td>{t.tradeId}</td><td>{t.orderId}</td><td>{t.accountId}</td><td>{t.symbol}</td>
                <td><span className={`badge ${actionBadge(t.action)}`}>{t.action}</span></td>
                <td>{t.quantity.toFixed(2)}</td><td>{t.fillPrice.toFixed(2)}</td><td>{t.fee.toFixed(2)}</td>
                <td>{t.tax.toFixed(2)}</td><td>{formatDateTime(t.executedAt)}</td>
              </tr>
            ))}
          </tbody>
        </TableCard>
      )}

      {tab === 'equity' && (
              <div className="card">
                <div className="card-header"><h2 className="mb-0 h5"><Icon name="arrow-up-right" /> Equity Curve / Realized P&L</h2></div>
                <div className="card-body">
                  {equity.data.length === 0 ? (
                    <div className="alert alert-info text-center py-5">
                      <Icon name="activity" size="lg" color="dim" className="mb-2" />
                      <h2 className="h5">Belum ada data trade untuk periode ini</h2>
                      <p className="text-muted mb-0">Chart equity/P&L akan muncul otomatis setelah ada trade yang terekseskusi.</p>
                    </div>
                  ) : (
                    <div className="flex flex-wrap items-start gap-6">
                      {/* Left – chart, takes remaining space, min 500px before wrap */}
                      <div className="min-w-0 flex-[2_1_500px]">
                        <EquityChart labels={equity.labels} data={equity.data} />
                      </div>

                      {/* Right – last 50 trades, fixed max height, vertical scroll */}
                      <div className="min-w-0 flex-[1_1_380px] max-h-[400px] overflow-y-auto">
                        <TableCard
                          title="Paper Trades (last 50)"
                          count={trades.length}
                          loading={tradesP.loading}
                          onCsv={() => downloadCsv(trades, `paper_trades_${new Date().toISOString().slice(0,10)}.csv`)}
                          onMd={() => downloadMarkdown([
                            { header: 'Trade ID', render: (t: Trade) => String(t.tradeId) },
                            { header: 'Order ID', render: (t) => String(t.orderId) },
                            { header: 'Account', render: (t) => t.accountId },
                            { header: 'Symbol', render: (t) => t.symbol },
                            { header: 'Action', render: (t) => t.action },
                            { header: 'Qty', render: (t) => t.quantity.toFixed(2) },
                            { header: 'Fill Price', render: (t) => t.fillPrice.toFixed(2) },
                            { header: 'Fee', render: (t) => t.fee.toFixed(2) },
                            { header: 'Tax', render: (t) => t.tax.toFixed(2) },
                            { header: 'Executed At', render: (t) => formatDateTime(t.executedAt) },
                          ], trades, `paper_trades_${new Date().toISOString().slice(0,10)}.md`)}
                        >
                          <thead><tr>
                            <th>Trade ID</th><th>Order ID</th><th>Account</th><th>Symbol</th><th>Action</th><th>Qty</th>
                            <th>Fill Price</th><th>Fee</th><th>Tax</th><th>Executed At</th>
                          </tr></thead>
                          <tbody>
                            {[...trades]
                              .sort((a, b) => b.executedAt.localeCompare(a.executedAt))
                              .slice(0, 50)
                              .map((t) => (
                                <tr key={t.tradeId}>
                                  <td>{t.tradeId}</td><td>{t.orderId}</td><td>{t.accountId}</td><td>{t.symbol}</td>
                                  <td><span className={`badge ${actionBadge(t.action)}`}>{t.action}</span></td>
                                  <td>{t.quantity.toFixed(2)}</td><td>{t.fillPrice.toFixed(2)}</td>
                                  <td>{t.fee.toFixed(2)}</td><td>{t.tax.toFixed(2)}</td>
                                  <td>{formatDateTime(t.executedAt)}</td>
                                </tr>
                              ))}
                          </tbody>
                        </TableCard>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

      {tab === 'scheduler' && (
        <>
          <div className="card mb-4">
            <div className="card-header d-flex justify-content-between align-items-center">
              <h2 className="mb-0 h5"><Icon name="settings" /> Latest Job Runs</h2>
              <div>
                <button className="btn btn-sm btn-outline-primary me-2" onClick={() => downloadCsv(jobs, `scheduler_job_runs_${new Date().toISOString().slice(0,10)}.csv`)}><Icon name="arrow-down-right" /> CSV</button>
                <button className="btn btn-sm btn-outline-secondary" onClick={() => downloadMarkdown(
                  [
                    { header: 'Job Type', render: (j: SchedulerJobRun) => j.jobType },
                    { header: 'Trading Date', render: (j) => j.tradingDate },
                    { header: 'Status', render: (j) => j.status },
                    { header: 'Attempt', render: (j) => String(j.attempt) },
                    { header: 'Started At', render: (j) => formatDateTime(j.startedAt) },
                    { header: 'Finished At', render: (j) => formatDateTime(j.finishedAt) },
                    { header: 'Next Retry', render: (j) => formatDateTime(j.nextRetryAt) },
                    { header: 'Detail', render: (j) => j.detail ?? '' },
                  ],
                  jobs, `scheduler_job_runs_${new Date().toISOString().slice(0,10)}.md`,
                )}><Icon name="copy" /> Markdown</button>
              </div>
            </div>
            <div className="card-body p-0">
              {jobs.length > 0 ? (
                <>
                  <div className="table-responsive">
                    <table className="table table-striped table-hover mb-0">
                      <thead><tr><th>Job Type</th><th>Trading Date</th><th>Status</th><th>Attempt</th><th>Started At</th><th>Finished At</th><th>Next Retry</th><th>Detail</th></tr></thead>
                      <tbody>
                        {jobs.map((j, i) => (
                          <tr key={`${j.jobType}-${j.tradingDate}-${i}`}>
                            <td>{j.jobType}</td><td>{j.tradingDate}</td><td><span className={`badge ${jobBadge(j.status)}`}>{j.status}</span></td>
                            <td>{j.attempt}</td><td>{formatDateTime(j.startedAt)}</td><td>{formatDateTime(j.finishedAt)}</td>
                            <td>{formatDateTime(j.nextRetryAt)}</td><td>{j.detail ?? ''}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="card-footer">
                    <h3 className="h6">Job Status Summary</h3>
                    <div className="flex flex-wrap gap-3">
                      {Object.entries(jobs.reduce<Record<string, number>>((m, j) => { m[j.status] = (m[j.status] ?? 0) + 1; return m; }, {})).map(([k, v]) => (
                        <span key={k} className={`badge ${jobBadge(k)}`} style={{ fontSize: '0.78rem' }}>{k}: {v}</span>
                      ))}
                    </div>
                  </div>
                </>
              ) : <div className="p-3 text-center text-muted">No scheduler job runs recorded</div>}
            </div>
          </div>

          <div className="card mb-4">
            <div className="card-header d-flex justify-content-between align-items-center">
              <h2 className="mb-0 h5"><Icon name="circle-dot" /> Notification Dedup State</h2>
              <div>
                <button className="btn btn-sm btn-outline-primary me-2" onClick={() => downloadCsv(dedup, `notification_dedup_state_${new Date().toISOString().slice(0,10)}.csv`)}><Icon name="arrow-down-right" /> CSV</button>
                <button className="btn btn-sm btn-outline-secondary" onClick={() => downloadMarkdown(
                  [
                    { header: 'Alert Type', render: (d: NotificationDedupState) => d.alertType },
                    { header: 'Last Signature', render: (d) => d.lastSignature ?? '—' },
                    { header: 'Last Sent At', render: (d) => formatDateTime(d.lastSentAt) },
                    { header: 'Last Status', render: (d) => d.lastStatus },
                    { header: 'Updated At', render: (d) => formatDateTime(d.updatedAt) },
                  ],
                  dedup, `notification_dedup_state_${new Date().toISOString().slice(0,10)}.md`,
                )}><Icon name="copy" /> Markdown</button>
              </div>
            </div>
            <div className="card-body p-0">
              {dedup.length > 0 ? (
                <div className="table-responsive">
                  <table className="table table-striped table-hover mb-0">
                    <thead><tr><th>Alert Type</th><th>Last Signature</th><th>Last Sent At</th><th>Last Status</th><th>Updated At</th></tr></thead>
                    <tbody>
                      {dedup.map((d, i) => (
                        <tr key={`${d.alertType}-${i}`}>
                          <td>{d.alertType}</td><td>{d.lastSignature ?? '—'}</td><td>{formatDateTime(d.lastSentAt)}</td>
                          <td><span className={`badge ${dedupBadge(d.lastStatus)}`}>{d.lastStatus}</span></td><td>{formatDateTime(d.updatedAt)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <div className="p-3 text-center text-muted d-flex align-items-center justify-content-center gap-2"><Icon name="shield-check" size="sm" color="dim" /> Belum ada duplikasi notifikasi terdeteksi — sistem berjalan normal</div>}
            </div>
          </div>

          <div className="card">
            <div className="card-header d-flex justify-content-between align-items-center">
              <h2 className="mb-0 h5"><Icon name="activity" /> Recent Audit Events (Last 50)</h2>
              <div>
                <button className="btn btn-sm btn-outline-primary me-2" onClick={() => downloadCsv(audit, `audit_events_${new Date().toISOString().slice(0,10)}.csv`)}><Icon name="arrow-down-right" /> CSV</button>
                <button className="btn btn-sm btn-outline-secondary" onClick={() => downloadMarkdown(
                  [
                    { header: 'ID', render: (a: AuditEvent) => a.id?.toString() ?? '—' },
                    { header: 'Event Type', render: (a) => a.eventType },
                    { header: 'Payload', render: (a) => a.payload ?? '' },
                    { header: 'Created At', render: (a) => formatDateTime(a.createdAt) },
                  ],
                  audit, `audit_events_${new Date().toISOString().slice(0,10)}.md`,
                )}><Icon name="copy" /> Markdown</button>
              </div>
            </div>
            <div className="card-body p-0">
              {audit.length > 0 ? (
                <div className="table-responsive">
                  <table className="table table-striped table-hover mb-0">
                    <thead><tr><th>ID</th><th>Event Type</th><th>Payload</th><th>Created At</th></tr></thead>
                    <tbody>
                      {audit.map((a, i) => (
                        <tr key={a.id ?? i}>
                          <td>{a.id ?? '—'}</td><td>{a.eventType}</td>
                          <td><pre className="mb-0 small" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{a.payload ?? ''}</pre></td>
                          <td>{formatDateTime(a.createdAt)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <div className="p-3 text-center text-muted d-flex align-items-center justify-content-center gap-2"><Icon name="activity" size="sm" color="dim" /> Belum ada aktivitas audit tercatat — log akan muncul saat ada event sistem</div>}
            </div>
          </div>
        </>
      )}
      </motion.div>
      </AnimatePresence>
    </PageReveal>
    </div>
  );
}

function TableCard({ title, count, loading, onCsv, onMd, children }: {
  title: string; count: number; loading: boolean;
  onCsv: () => void; onMd: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="card mb-4">
      <div className="card-header d-flex justify-content-between align-items-center section-head">
        <h2 className="mb-0 h5"><Icon name="book-open" /> {title} ({count} records)</h2>
        <div>
          <button className="btn btn-sm btn-outline-primary me-2" onClick={onCsv}><Icon name="arrow-down-right" /> CSV</button>
          <button className="btn btn-sm btn-outline-secondary" onClick={onMd}><Icon name="copy" /> Markdown</button>
        </div>
      </div>
      <div className="card-body p-0">
              {loading ? <div className="text-center py-4"><span className="spinner" /></div>
                : count > 0 ? <div className="table-responsive"><table className="table table-striped table-hover mb-0">{children}</table></div>
                : <div className="alert alert-info d-flex align-items-center gap-2" role="status">
                    <Icon name="circle-dot" size="sm" color="dim" />
                    <span>Belum ada {title.toLowerCase()} — data akan muncul otomatis saat tersedia.</span>
                  </div>}
            </div>
    </div>
  );
}

function EquityChart({ labels, data }: { labels: string[]; data: number[] }) {
  const reduced = useReducedMotionSafe();
  const W = 720, H = 320, pad = 40;
  const max = Math.max(...data, 1);
  const min = Math.min(...data, 0);
  const span = max - min || 1;
  const xAt = (i: number) => pad + (i / Math.max(data.length - 1, 1)) * (W - 2 * pad);
  const yAt = (v: number) => H - pad - ((v - min) / span) * (H - 2 * pad);
  const linePts = data.map((v, i) => `${xAt(i).toFixed(1)},${yAt(v).toFixed(1)}`).join(' ');
  // Area path: line points then down to baseline and back.
  const baseY = yAt(0);
  const areaPath =
    `M ${xAt(0).toFixed(1)},${baseY.toFixed(1)} ` +
    data.map((v, i) => `L ${xAt(i).toFixed(1)},${yAt(v).toFixed(1)}`).join(' ') +
    ` L ${xAt(data.length - 1).toFixed(1)},${baseY.toFixed(1)} Z`;
  const last = data[data.length - 1];
  const gridY = [0.25, 0.5, 0.75].map((f) => pad + f * (H - 2 * pad));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', maxHeight: 400, background: '#070707', borderRadius: 8, border: '1px solid var(--edge)' }} role="img" aria-label="Equity curve">
      {/* gridlines */}
      {gridY.map((y, i) => (
        <line key={i} x1={pad} y1={y} x2={W - pad} y2={y} stroke="#161616" />
      ))}
      {/* axes */}
      <line x1={pad} y1={H - pad} x2={W - pad} y2={H - pad} stroke="#232323" />
      <line x1={pad} y1={pad} x2={pad} y2={H - pad} stroke="#232323" />
      {/* zero baseline emphasized */}
      <line x1={pad} y1={baseY} x2={W - pad} y2={baseY} stroke="rgba(212,255,63,.22)" strokeDasharray="3 4" />
      {/* area fill */}
      <motion.path
        d={areaPath} fill="url(#equityFill)" stroke="none"
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: reduced ? 0 : 0.6, ease: EASE_OUT }}
      />
      <defs>
        <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="rgba(212,255,63,.18)" />
          <stop offset="100%" stopColor="rgba(212,255,63,0)" />
        </linearGradient>
      </defs>
      {/* line draw-in */}
      <motion.polyline
        points={linePts} fill="none" stroke="var(--lime)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round"
        initial={{ pathLength: reduced ? 1 : 0, opacity: reduced ? 1 : 0 }}
        animate={{ pathLength: 1, opacity: 1 }}
        transition={{ duration: reduced ? 0 : 0.7, ease: EASE_OUT }}
      />
      {/* end marker */}
      {!reduced && (
        <motion.circle cx={xAt(data.length - 1)} cy={yAt(last)} r={3.5} fill="var(--lime)"
          initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ delay: 0.6, duration: 0.2, ease: EASE_OUT }} />
      )}
      <text x={pad} y={pad - 10} fill="var(--gray)" fontSize={11} fontFamily="var(--font-mono)">
        {last >= 0 ? '+' : ''}{last.toLocaleString('id-ID')} IDR
      </text>
    </svg>
  );
}
