import type { Page, Request, Route } from '@playwright/test';

// Deterministic fixtures typed to match src/api/types.ts (camelCase).

export const phase1JournalFixture = [
  {
    entryId: 1001, briefId: 2001, symbol: 'BBCA', decision: 'TAKE',
    decidedAt: '2026-08-29T09:30:00Z', riskPolicyStatus: 'ACCEPTED',
    riskPolicyReason: 'within limits', plannedR: 2.5, note: 'breakout retest',
    briefStatus: 'READY', briefGeneratedAt: '2026-08-29T08:55:00Z',
    sourceSnapshotId: 9001, briefReason: 'flag-pole',
    entryPrice: 9500, stopLossPrice: 9300, takeProfitPrice: 9900, riskAmount: 200, positionSize: 100, riskRewardRatio: 2.0,
  },
  {
    entryId: 1002, briefId: 2002, symbol: 'TLKM', decision: 'SKIP',
    decidedAt: '2026-08-29T10:15:00Z', riskPolicyStatus: 'RISK_REJECTED',
    riskPolicyReason: 'over max position', plannedR: null, note: '',
    briefStatus: 'DRAFT', briefGeneratedAt: '2026-08-29T09:00:00Z',
    sourceSnapshotId: 9002, briefReason: 'over-extended',
    entryPrice: 4200, stopLossPrice: 4000, takeProfitPrice: 4600, riskAmount: 200, positionSize: 100, riskRewardRatio: 2.0,
  },
  {
    entryId: 1003, briefId: 2003, symbol: 'ASII', decision: 'WAIT',
    decidedAt: '2026-08-30T08:00:00Z', riskPolicyStatus: 'ACCEPTED',
    riskPolicyReason: 'within limits', plannedR: 1.8, note: 'awaiting confirm',
    briefStatus: 'READY', briefGeneratedAt: '2026-08-30T07:30:00Z',
    sourceSnapshotId: 9003, briefReason: 'pullback',
    entryPrice: 6500, stopLossPrice: 6300, takeProfitPrice: 6900, riskAmount: 200, positionSize: 100, riskRewardRatio: 2.0,
  },
];

export const phase1SymbolsFixture = ['BBCA', 'TLKM', 'ASII'];

export const phase3PositionsFixture = [
  { positionId: 1, accountId: 'ACC001', symbol: 'BBCA', quantity: 100, averagePrice: 9500, realizedPnl: 0, status: 'OPEN', direction: 'LONG', stopLoss: 9300, takeProfit: 9900, buyFeeAccumulated: 12.5, createdAt: '2026-08-29T09:31:00Z', updatedAt: '2026-08-29T09:31:00Z' },
];

export const phase3OrdersFixture = [
  { orderId: 1, accountId: 'ACC001', symbol: 'BBCA', action: 'BUY', quantity: 100, requestedPrice: 9500, filledPrice: 9500, filledQuantity: 100, status: 'FILLED', reason: 'ok', createdAt: '2026-08-29T09:30:00Z', updatedAt: '2026-08-29T09:31:00Z', filledAt: '2026-08-29T09:31:00Z', analysisSnapshotId: 1 },
];

export const phase3TradesFixture = [
  { tradeId: 1, orderId: 1, accountId: 'ACC001', symbol: 'BBCA', action: 'BUY', quantity: 100, fillPrice: 9500, fee: 10, tax: 5, executedAt: '2026-08-29T09:31:00Z' },
];

export const phase3SchedulerFixture = [
  { jobType: 'decide', tradingDate: '2026-08-30', status: 'SUCCESS', attempt: 1, startedAt: '2026-08-30T07:00:00Z', finishedAt: '2026-08-30T07:00:05Z', nextRetryAt: null, detail: 'ok' },
];

export const phase3DedupFixture = [
  { alertType: 'gap-up', lastSignature: 'AALI:2026-08-30', lastSentAt: '2026-08-30T07:30:00Z', lastStatus: 'SENT', updatedAt: '2026-08-30T07:30:00Z' },
];

export const phase3AuditFixture = [
  { id: 1, eventType: 'snapshot.created', payload: '{}', createdAt: '2026-08-30T07:00:00Z' },
];

export const phase2WindowsFixture = [
  { windowId: 7001, startAt: '2026-08-29T08:00:00Z', endAt: '2026-08-29T17:00:00Z', timezone: 'Asia/Jakarta', note: 'active window', status: 'ACTIVE', createdAt: '2026-08-29T07:00:00Z', closedAt: null },
  { windowId: 7002, startAt: '2026-08-28T08:00:00Z', endAt: '2026-08-28T17:00:00Z', timezone: 'Asia/Jakarta', note: 'closed window', status: 'CLOSED', createdAt: '2026-08-28T07:00:00Z', closedAt: '2026-08-28T17:00:00Z' },
];

export const phase2ReviewFixture = {
  reviewId: 1, observationWindowId: 7001, reviewedAt: '2026-08-29T12:00:00Z',
  evidenceStatus: 'COMPLETE_EVIDENCE', knownLimitations: '[]', operatorFeedbackIds: '[]',
  humanDecision: 'PENDING', decisionNote: null, decidedAt: null, decidedBy: null,
  createdAt: '2026-08-29T12:00:00Z', updatedAt: '2026-08-29T12:00:00Z',
};

export const phase0DbInfoFixture = { path: 'F:\\My Son\\data\\investment_platform.db', exists: true, sizeMb: 12.34 };
export const phase0TablesFixture = ['journal_entries', 'decision_briefs', 'positions'];
export const alertsFixture: unknown[] = [];

// Captures every network request so a test can assert no write methods leaked.
export class RequestLog {
  readonly requests: Request[] = [];
  attach(page: Page): void {
    page.on('request', (req) => {
      const url = req.url();
      if (
        url.includes('/@vite/') || url.includes('/__vite_ping') ||
        url.includes('/node_modules/') || url.includes('/assets/') ||
        url.endsWith('.css') || url.endsWith('.js') || url.endsWith('.png') || url.endsWith('.svg') || url.endsWith('.ico') || url.endsWith('.woff2')
      ) return;
      this.requests.push(req);
    });
  }
  apiRequests(): Request[] { return this.requests.filter((r) => r.url().includes('/api/')); }
  writeAttempts(): Request[] {
    return this.apiRequests().filter((r) => {
      const m = r.method();
      return m === 'POST' || m === 'PUT' || m === 'DELETE' || m === 'PATCH';
    });
  }
}

// Stub every /api/* endpoint with a fixture. Unknown /api/* fails loudly (404).
// Route matching in Playwright is LAST-registered-first-matched, so the catch-all
// goes first; specific routes are layered on top.
export async function stubApi(page: Page): Promise<void> {
  const reply = (route: Route, body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });

  // Catch-all 404 first
  await page.route('**/api/**', async (route) => {
    await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: 'unstubbed', url: route.request().url() }) });
  });

  // Specific routes layered on top
  await page.route('**/api/health', (r) => reply(r, { status: 'ok', timestamp: new Date().toISOString() }));

  await page.route('**/api/phase1/symbols', (r) => reply(r, phase1SymbolsFixture));
  await page.route(/\/api\/phase1\/journal/, async (route) => {
    const url = new URL(route.request().url());
    let rows = [...phase1JournalFixture];
    const sym = url.searchParams.get('symbol');
    const dec = url.searchParams.get('decision');
    const risk = url.searchParams.get('riskPolicy');
    const fromDate = url.searchParams.get('fromDate');
    if (sym) rows = rows.filter((e) => e.symbol === sym);
    if (dec) rows = rows.filter((e) => e.decision === dec);
    if (risk) rows = rows.filter((e) => e.riskPolicyStatus === risk);
    if (fromDate) rows = rows.filter((e) => e.decidedAt.slice(0, 10) >= fromDate);
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(rows) });
  });

  await page.route('**/api/phase3/positions', (r) => reply(r, phase3PositionsFixture));
  await page.route('**/api/phase3/orders', (r) => reply(r, phase3OrdersFixture));
  await page.route('**/api/phase3/trades', (r) => reply(r, phase3TradesFixture));
  await page.route('**/api/phase3/scheduler', (r) => reply(r, phase3SchedulerFixture));
  await page.route('**/api/phase3/dedup', (r) => reply(r, phase3DedupFixture));
  await page.route(/\/api\/phase3\/audit/, (r) => reply(r, phase3AuditFixture));
  await page.route('**/api/alerts', (r) => reply(r, alertsFixture));

  await page.route('**/api/phase2/windows', (r) => reply(r, phase2WindowsFixture));
  await page.route(/\/api\/phase2\/review\//, (r) => reply(r, phase2ReviewFixture));
  await page.route(/\/api\/phase2\/feedback\//, (r) => reply(r, []));

  await page.route('**/api/phase0/db-info', (r) => reply(r, phase0DbInfoFixture));
  await page.route('**/api/phase0/tables', (r) => reply(r, phase0TablesFixture));
}
