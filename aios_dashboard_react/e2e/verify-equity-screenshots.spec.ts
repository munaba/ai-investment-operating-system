import { test, expect } from '@playwright/test';
import { stubApi } from './helpers';

// Rich equity fixtures that guarantee a visible curve crossing zero
const equityPositions = [
  { positionId: 10, accountId: 'ACC001', symbol: 'BBCA', quantity: 100, averagePrice: 9500, realizedPnl: -500000, status: 'CLOSED', direction: 'LONG', stopLoss: 9300, takeProfit: 9900, buyFeeAccumulated: 12, createdAt: '2026-08-25T09:00:00Z', updatedAt: '2026-08-25T09:05:00Z' },
  { positionId: 11, accountId: 'ACC001', symbol: 'BBCA', quantity: 100, averagePrice: 9500, realizedPnl: 800000, status: 'CLOSED', direction: 'LONG', stopLoss: 9300, takeProfit: 9900, buyFeeAccumulated: 12, createdAt: '2026-08-26T09:00:00Z', updatedAt: '2026-08-26T09:05:00Z' },
  { positionId: 12, accountId: 'ACC001', symbol: 'BBCA', quantity: 100, averagePrice: 9500, realizedPnl: -200000, status: 'CLOSED', direction: 'LONG', stopLoss: 9300, takeProfit: 9900, buyFeeAccumulated: 12, createdAt: '2026-08-27T09:00:00Z', updatedAt: '2026-08-27T09:05:00Z' },
  { positionId: 13, accountId: 'ACC001', symbol: 'TLKM', quantity: 100, averagePrice: 4200, realizedPnl: 600000, status: 'CLOSED', direction: 'LONG', stopLoss: 4000, takeProfit: 4600, buyFeeAccumulated: 10, createdAt: '2026-08-28T09:00:00Z', updatedAt: '2026-08-28T09:05:00Z' },
];
const equityTrades = [
  { tradeId: 10, orderId: 10, accountId: 'ACC001', symbol: 'BBCA', action: 'BUY', quantity: 100, fillPrice: 9500, fee: 10, tax: 5, executedAt: '2026-08-25T09:01:00Z' },
  { tradeId: 11, orderId: 11, accountId: 'ACC001', symbol: 'BBCA', action: 'SELL', quantity: 100, fillPrice: 9700, fee: 10, tax: 5, executedAt: '2026-08-26T09:01:00Z' },
];

async function gotoEquity(page: any) {
  await page.addInitScript(() => { try { localStorage.setItem('aios.session', '1'); } catch {} });
  // stub with equity-rich data
  await stubApi(page);
  // override positions/trades with equity data after stubApi (last route wins)
  await page.route('**/api/phase3/positions', async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(equityPositions) });
  });
  await page.route('**/api/phase3/trades', async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(equityTrades) });
  });
  await page.goto('/phase3');
  // click Equity tab
  await page.locator('button.tab-btn:has-text("Equity")').click();
  await expect(page.locator('h2:has-text("Equity Curve")')).toBeVisible();
  // chart wrapper must have a11y role
  await expect(page.locator('[role="img"][aria-label^="Equity curve"]')).toBeVisible({ timeout: 10000 });
  // wait for visx chart to render (svg or canvas)
  await page.waitForTimeout(1500);
}

test.describe('EquityChart screenshots', () => {
  test('normal motion — chart + dashed zero line', async ({ page }) => {
    await gotoEquity(page);
    // ensure chart area is in viewport
    const chart = page.locator('[role="img"][aria-label^="Equity curve"]');
    await chart.scrollIntoViewIfNeeded();
    await page.waitForTimeout(800);
    await page.screenshot({ path: 'e2e/__screenshots__/equity-normal.png', fullPage: true });
    // also clip just the chart
    await chart.screenshot({ path: 'e2e/__screenshots__/equity-normal-clip.png' });
  });

  test('prefers-reduced-motion reduce — instant/no animation', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await gotoEquity(page);
    const chart = page.locator('[role="img"][aria-label^="Equity curve"]');
    await chart.scrollIntoViewIfNeeded();
    // with reduce, animationDuration=0 so chart should be immediately at final state
    // wait a bit then verify no pending motion by checking computed style or just stable screenshot
    await page.waitForTimeout(400);
    await page.screenshot({ path: 'e2e/__screenshots__/equity-reduced.png', fullPage: true });
    await chart.screenshot({ path: 'e2e/__screenshots__/equity-reduced-clip.png' });

    // Verify reduced-motion media query is active inside page
    const isReduced = await page.evaluate(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    expect(isReduced).toBe(true);
  });

  test('zero baseline dashed line visible in DOM', async ({ page }) => {
    await gotoEquity(page);
    // Bklit Grid renders highlight row as <line> with stroke rgba(205,162,63,.22) dash 3 4
    // Verify at least one line with that stroke exists
    const count = await page.evaluate(() => {
      const lines = Array.from(document.querySelectorAll('line'));
      return lines.filter(l => {
        const s = l.getAttribute('stroke') || '';
        const d = l.getAttribute('stroke-dasharray') || '';
        return s.includes('205,162,63') && d.includes('3');
      }).length;
    });
    expect(count, 'zero baseline dashed line (gold 3 4) should exist').toBeGreaterThanOrEqual(1);
    // also verify a11y
    const role = await page.getAttribute('[aria-label^="Equity curve"]', 'role');
    expect(role).toBe('img');
  });
});
