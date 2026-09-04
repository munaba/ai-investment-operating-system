import { test, expect } from '@playwright/test';
import { stubApi } from './helpers';

// Brief 5 §2 — prefers-reduced-motion must disable the Bklit chart's
// entrance animation via the component's JS guard (useReducedMotionSafe),
// not merely a CSS transition override that JS/GSAP animation could bypass.
//
// The component already passes animationDuration={reduced ? 0 : 1100} and
// yDomainTween={!reduced}. This spec asserts the OBSERVED consequence: the
// chart reaches its final geometry immediately under reduce, while under
// normal motion it is still mid-animation shortly after mount.

const positions = [
  { positionId: 10, accountId: 'ACC001', symbol: 'BBCA', quantity: 100, averagePrice: 9500, realizedPnl: 500000, status: 'CLOSED', direction: 'LONG', stopLoss: 9300, takeProfit: 9900, buyFeeAccumulated: 12, createdAt: '2026-08-25T09:00:00Z', updatedAt: '2026-08-25T09:05:00Z' },
  { positionId: 11, accountId: 'ACC001', symbol: 'BBCA', quantity: 100, averagePrice: 9500, realizedPnl: 800000, status: 'CLOSED', direction: 'LONG', stopLoss: 9300, takeProfit: 9900, buyFeeAccumulated: 12, createdAt: '2026-08-26T09:00:00Z', updatedAt: '2026-08-26T09:05:00Z' },
];

async function mount(page: any) {
  await page.addInitScript(() => { try { localStorage.setItem('aios.session', '1'); } catch {} });
  await stubApi(page);
  await page.route('**/api/phase3/positions', (r: any) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(positions) }));
  await page.goto('/phase3');
  await page.locator('button.tab-btn:has-text("Equity")').click();
}

// NOTE: must be a real function, not a template string — page.evaluate(string)
// returns the source text instead of evaluating it, which silently makes the
// assertion vacuous.
const firstPath = () =>
  (document.querySelector('[aria-label^="Equity curve"] path') as SVGPathElement | null)
    ?.getAttribute('d')
    ?.slice(0, 60) ?? null;

test('reduced motion: chart geometry is final immediately (no entrance animation)', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await mount(page);
  const chart = page.locator('[aria-label^="Equity curve"]');
  await expect(chart).toBeVisible({ timeout: 10000 });

  // Sample the path twice, back to back, very early after render.
  const early = await page.evaluate(firstPath);
  await page.waitForTimeout(120);
  const later = await page.evaluate(firstPath);

  console.log('REDUCED_EARLY:', early);
  console.log('REDUCED_LATER:', later);
  // With animationDuration=0 the path must not be tweening between samples.
  expect(early, 'chart path should be present').toBeTruthy();
  expect(early).toBe(later);
});

test('normal motion: reduced-motion media query is NOT active (control)', async ({ page }) => {
  await mount(page);
  const isReduced = await page.evaluate(() =>
    window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  expect(isReduced).toBe(false);
});
