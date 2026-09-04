import { test, expect } from '@playwright/test';
import { stubApi } from './helpers';

// ---------------------------------------------------------------------------
// BRIEF 5 §1 — parity harness.
//
// Renders the Equity/P&L chart in a REAL browser across three data scenarios
// and dumps the numbers actually visible in the DOM, plus a screenshot.
//
// jsdom cannot do this: the chart draws via ResizeObserver-measured layout,
// and the Brief 4 stub returns an empty observer, so nothing measurable is
// emitted under vitest. This spec is the evidence Brief 5 §1 requires.
//
// Run BEFORE the swap (baseline, inline <svg>) and AFTER (EquityChartBklit);
// compare the JSON dumps to prove the displayed values are 1:1 identical.
// ---------------------------------------------------------------------------

const OUT = process.env.EQUITY_OUT_DIR || 'e2e/__screenshots__';
const TAG = process.env.EQUITY_TAG || 'baseline';

// ---- fixtures: 3 scenarios from §1 -------------------------------------

// 1. P&L positif (data normal) — cumulative ends positive
const posPositions = [
  { positionId: 10, accountId: 'ACC001', symbol: 'BBCA', quantity: 100, averagePrice: 9500, realizedPnl: 500000, status: 'CLOSED', direction: 'LONG', stopLoss: 9300, takeProfit: 9900, buyFeeAccumulated: 12, createdAt: '2026-08-25T09:00:00Z', updatedAt: '2026-08-25T09:05:00Z' },
  { positionId: 11, accountId: 'ACC001', symbol: 'BBCA', quantity: 100, averagePrice: 9500, realizedPnl: 800000, status: 'CLOSED', direction: 'LONG', stopLoss: 9300, takeProfit: 9900, buyFeeAccumulated: 12, createdAt: '2026-08-26T09:00:00Z', updatedAt: '2026-08-26T09:05:00Z' },
  { positionId: 12, accountId: 'ACC001', symbol: 'TLKM', quantity: 100, averagePrice: 4200, realizedPnl: 600000, status: 'CLOSED', direction: 'LONG', stopLoss: 4000, takeProfit: 4600, buyFeeAccumulated: 10, createdAt: '2026-08-28T09:00:00Z', updatedAt: '2026-08-28T09:05:00Z' },
];
// cumulative: 500000, 1300000, 1900000

// 2. P&L negatif (rugi) — cumulative ends below zero
const negPositions = [
  { positionId: 20, accountId: 'ACC001', symbol: 'BBCA', quantity: 100, averagePrice: 9500, realizedPnl: 300000, status: 'CLOSED', direction: 'LONG', stopLoss: 9300, takeProfit: 9900, buyFeeAccumulated: 12, createdAt: '2026-08-25T09:00:00Z', updatedAt: '2026-08-25T09:05:00Z' },
  { positionId: 21, accountId: 'ACC001', symbol: 'BBCA', quantity: 100, averagePrice: 9500, realizedPnl: -900000, status: 'CLOSED', direction: 'LONG', stopLoss: 9300, takeProfit: 9900, buyFeeAccumulated: 12, createdAt: '2026-08-26T09:00:00Z', updatedAt: '2026-08-26T09:05:00Z' },
  { positionId: 22, accountId: 'ACC001', symbol: 'TLKM', quantity: 100, averagePrice: 4200, realizedPnl: -200000, status: 'CLOSED', direction: 'LONG', stopLoss: 4000, takeProfit: 4600, buyFeeAccumulated: 10, createdAt: '2026-08-28T09:00:00Z', updatedAt: '2026-08-28T09:05:00Z' },
];
// cumulative: 300000, -600000, -800000

// 3. Data kosong — no closed positions, no trades -> empty state, not a chart
const emptyPositions: any[] = [];

const trades = [
  { tradeId: 10, orderId: 10, accountId: 'ACC001', symbol: 'BBCA', action: 'BUY', quantity: 100, fillPrice: 9500, fee: 10, tax: 5, executedAt: '2026-08-25T09:01:00Z' },
  { tradeId: 11, orderId: 11, accountId: 'ACC001', symbol: 'BBCA', action: 'SELL', quantity: 100, fillPrice: 9700, fee: 10, tax: 5, executedAt: '2026-08-26T09:01:00Z' },
];

async function mountEquity(page: any, positions: any[], tradesData: any[]) {
  await page.addInitScript(() => { try { localStorage.setItem('aios.session', '1'); } catch {} });
  await stubApi(page);
  // last-registered route wins in Playwright
  await page.route('**/api/phase3/positions', (route: any) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(positions) }));
  await page.route('**/api/phase3/trades', (route: any) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(tradesData) }));
  await page.goto('/phase3');
  await page.locator('button.tab-btn:has-text("Equity")').click();
  await page.waitForTimeout(1800); // let layout-measured chart settle
}

// Extract everything readable from the chart region.
async function dump(page: any) {
  return page.evaluate(() => {
    const root = document.querySelector('[aria-label^="Equity curve"]');
    if (!root) return { present: false, reason: 'no [aria-label="Equity curve"] element' };
    const text = (root.textContent || '').replace(/\s+/g, ' ').trim();
    const svgPaths = Array.from(root.querySelectorAll('path')).map((p) =>
      (p.getAttribute('d') || '').slice(0, 40));
    const polyline = Array.from(root.querySelectorAll('polyline')).map((p) =>
      (p.getAttribute('points') || '').slice(0, 40));
    const texts = Array.from(root.querySelectorAll('text')).map((t) => (t.textContent || '').trim());
    const strokes = Array.from(root.querySelectorAll('[stroke]'))
      .map((e) => e.getAttribute('stroke')).filter(Boolean);
    return {
      present: true,
      tag: root.tagName.toLowerCase(),
      role: root.getAttribute('role'),
      ariaLabel: root.getAttribute('aria-label'),
      text,
      texts,
      pathCount: svgPaths.length,
      paths: svgPaths,
      polyline,
      strokes: Array.from(new Set(strokes)),
      rect: (() => { const r = root.getBoundingClientRect(); return { w: Math.round(r.width), h: Math.round(r.height) }; })(),
    };
  });
}

test.describe(`Equity parity [${TAG}]`, () => {
  test('scenario 1 — P&L positif', async ({ page }) => {
    await mountEquity(page, posPositions, trades);
    const chart = page.locator('[aria-label^="Equity curve"]');
    await expect(chart).toBeVisible({ timeout: 10000 });
    await chart.scrollIntoViewIfNeeded();
    const data = await dump(page);
    console.log(`DUMP_POSITIF_${TAG}:` + JSON.stringify(data, null, 1));
    await chart.screenshot({ path: `${OUT}/parity-${TAG}-1-positif.png` });
    expect(data.present).toBe(true);
  });

  test('scenario 2 — P&L negatif (rugi)', async ({ page }) => {
    await mountEquity(page, negPositions, trades);
    const chart = page.locator('[aria-label^="Equity curve"]');
    await expect(chart).toBeVisible({ timeout: 10000 });
    await chart.scrollIntoViewIfNeeded();
    const data = await dump(page);
    console.log(`DUMP_NEGATIF_${TAG}:` + JSON.stringify(data, null, 1));
    await chart.screenshot({ path: `${OUT}/parity-${TAG}-2-negatif.png` });
    expect(data.present).toBe(true);
  });

  test('scenario 3 — data kosong (empty state, bukan chart)', async ({ page }) => {
    await mountEquity(page, emptyPositions, []);
    // Empty state shows the alert, NOT a chart.
    const alert = page.locator('text=Belum ada data trade');
    await expect(alert).toBeVisible({ timeout: 10000 });
    const chartVisible = await page.locator('[aria-label^="Equity curve"]').count();
    console.log(`DUMP_KOSONG_${TAG}:` + JSON.stringify({ emptyStateShown: true, chartElements: chartVisible }));
    await page.screenshot({ path: `${OUT}/parity-${TAG}-3-kosong.png` });
    expect(chartVisible, 'chart must NOT render when there is no data').toBe(0);
  });
});
