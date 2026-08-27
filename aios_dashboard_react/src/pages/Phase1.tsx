import { useMemo, useState } from 'react';
import type { JournalEntry } from '../api/types';
import { getPhase1Journal, getPhase1Symbols } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import Icon from '../components/Icon';
import { formatDateTime, downloadCsv, downloadMarkdown } from '../lib/format';

function decisionBadgeClass(d: string): string {
  switch (d) {
    case 'TAKE': return 'badge bg-success';
    case 'SKIP': return 'badge bg-secondary';
    case 'WAIT': return 'badge bg-warning';
    default: return 'badge bg-secondary';
  }
}
function riskBadgeClass(s: string): string {
  switch (s) {
    case 'ACCEPTED': return 'badge bg-success';
    case 'RISK_REJECTED': return 'badge bg-danger';
    default: return 'badge bg-secondary';
  }
}

export default function Phase1() {
  const [symbol, setSymbol] = useState('');
  const [decision, setDecision] = useState('');
  const [riskPolicy, setRiskPolicy] = useState('');
  const [fromDate, setFromDate] = useState('');
  const [selected, setSelected] = useState<JournalEntry | null>(null);

  const { data: symbols } = usePolling(() => getPhase1Symbols(), 60_000, { immediate: true });

  const journal = usePolling<JournalEntry[]>(
    () => getPhase1Journal({ symbol: symbol || undefined, decision: decision || undefined, riskPolicy: riskPolicy || undefined, fromDate: fromDate || undefined }),
    30_000,
    { immediate: true },
  );

  const entries = useMemo(() => journal.data ?? [], [journal.data]);

  const onRefresh = async () => {
    await journal.refresh();
  };

  const journalDetailJson = (e: JournalEntry) =>
    JSON.stringify(
      {
        entry_id: e.entryId, brief_id: e.briefId, symbol: e.symbol, decision: e.decision,
        decided_at: e.decidedAt, risk_policy_status: e.riskPolicyStatus,
        risk_policy_reason: e.riskPolicyReason, planned_r: e.plannedR, note: e.note,
      },
      null,
      2,
    );

  const briefDetailJson = (e: JournalEntry) =>
    JSON.stringify(
      {
        brief_id: e.briefId, status: e.briefStatus, generated_at: e.briefGeneratedAt,
        source_snapshot_id: e.sourceSnapshotId, reason: e.briefReason, entry_price: e.entryPrice,
        stop_loss_price: e.stopLossPrice, take_profit_price: e.takeProfitPrice,
        risk_amount: e.riskAmount, position_size: e.positionSize, risk_reward_ratio: e.riskRewardRatio,
      },
      null,
      2,
    );

  return (
    <>
      <h1 className="display-serif">Journal &amp; briefs</h1>

      <div className="card mb-4">
        <div className="card-body">
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <div style={{ flex: '1 1 160px' }}>
              <label className="form-label">Symbol</label>
              <select className="form-select" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
                <option value="">All</option>
                {(symbols ?? []).map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div style={{ flex: '1 1 120px' }}>
              <label className="form-label">Decision</label>
              <select className="form-select" value={decision} onChange={(e) => setDecision(e.target.value)}>
                <option value="">All</option>
                <option value="TAKE">TAKE</option>
                <option value="SKIP">SKIP</option>
                <option value="WAIT">WAIT</option>
              </select>
            </div>
            <div style={{ flex: '1 1 120px' }}>
              <label className="form-label">Risk Policy</label>
              <select className="form-select" value={riskPolicy} onChange={(e) => setRiskPolicy(e.target.value)}>
                <option value="">All</option>
                <option value="ACCEPTED">ACCEPTED</option>
                <option value="RISK_REJECTED">RISK_REJECTED</option>
              </select>
            </div>
            <div style={{ flex: '1 1 160px' }}>
              <label className="form-label">From Date</label>
              <input type="date" className="form-control" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
            </div>
            <div style={{ flex: '0 1 auto' }}>
              <button className="btn btn-outline-secondary w-100" onClick={onRefresh} disabled={journal.loading}>
                <Icon name="refresh-cw" /> Refresh
              </button>
            </div>
          </div>
        </div>
      </div>

      {journal.loading && !journal.data ? (
        <div className="text-center py-4"><span className="spinner" /> <p>Loading journal entries…</p></div>
      ) : entries.length > 0 ? (
        <>
          <div className="card mb-4">
            <div className="card-header d-flex justify-content-between align-items-center">
              <h5 className="mb-0"><Icon name="book-open" /> Journal Entries ({entries.length} records)</h5>
              <div>
                <button className="btn btn-sm btn-outline-primary me-2" onClick={() => downloadCsv(entries, `journal_entries_${new Date().toISOString().slice(0,10)}.csv`)}>
                  <Icon name="arrow-down-right" /> CSV
                </button>
                <button className="btn btn-sm btn-outline-secondary" onClick={() => downloadMarkdown(
                  [
                    { header: 'Entry ID', render: (r: JournalEntry) => String(r.entryId) },
                    { header: 'Symbol', render: (r) => r.symbol },
                    { header: 'Decision', render: (r) => r.decision },
                    { header: 'Decided At', render: (r) => formatDateTime(r.decidedAt) },
                    { header: 'Risk Policy', render: (r) => r.riskPolicyStatus },
                    { header: 'Planned R', render: (r) => (r.plannedR != null ? r.plannedR.toFixed(2) : '—') },
                    { header: 'Brief Status', render: (r) => (r.briefStatus ?? '—') },
                    { header: 'Note', render: (r) => (r.note ?? '') },
                  ],
                  entries,
                  `journal_entries_${new Date().toISOString().slice(0,10)}.md`,
                )}>
                  <Icon name="copy" /> Markdown
                </button>
              </div>
            </div>
            <div className="card-body p-0">
              <div className="table-responsive">
                <table className="table table-striped table-hover mb-0">
                  <thead>
                    <tr>
                      <th>Entry ID</th><th>Symbol</th><th>Decision</th><th>Decided At</th>
                      <th>Risk Policy</th><th>Planned R</th><th>Brief Status</th><th>Note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map((e) => (
                      <tr key={e.entryId} onClick={() => setSelected(e)}
                          style={{ cursor: 'pointer' }}
                          className={selected?.entryId === e.entryId ? 'table-primary' : ''}>
                        <td>{e.entryId}</td>
                        <td>{e.symbol}</td>
                        <td><span className={`badge ${decisionBadgeClass(e.decision)}`}>{e.decision}</span></td>
                        <td>{formatDateTime(e.decidedAt)}</td>
                        <td><span className={`badge ${riskBadgeClass(e.riskPolicyStatus)}`}>{e.riskPolicyStatus}</span></td>
                        <td>{e.plannedR != null ? e.plannedR.toFixed(2) : '—'}</td>
                        <td>{e.briefStatus ?? '—'}</td>
                        <td>{e.note ?? ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {selected && (
            <div className="row g-4" style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
              <div className="card" style={{ flex: '1 1 360px' }}>
                <div className="card-header"><h5><Icon name="file-text" /> Journal Entry Details</h5></div>
                <div className="card-body">
                  <pre className="mb-0"><code>{journalDetailJson(selected)}</code></pre>
                </div>
              </div>
              <div className="card" style={{ flex: '1 1 360px' }}>
                <div className="card-header"><h5><Icon name="file-text" /> Decision Brief Details</h5></div>
                <div className="card-body">
                  {selected.briefId > 0
                    ? <pre className="mb-0"><code>{briefDetailJson(selected)}</code></pre>
                    : <div className="text-muted">No linked brief</div>}
                </div>
              </div>
            </div>
          )}
        </>
      ) : (
        <div className="alert alert-info">No journal entries match the filters</div>
      )}
    </>
  );
}
