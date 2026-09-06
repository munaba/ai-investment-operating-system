import { test, expect } from '@playwright/test';
import { stubApi, RequestLog } from './helpers';

// Phase3 — Paper Book: positions, orders, trades, scheduler, dedup, audit. All read.
// TableCard uses <h2 class="mb-0 h5"> so select by visible text, not element name.
test.describe('Phase3 — Paper Book (read-only viewer)', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      try { localStorage.setItem('aios.session', '1'); } catch { /* ignore */ }
    });
    await stubApi(page);
  });

  test('positions table renders by default', async ({ page }) => {
    await page.goto('/phase3');
    await expect(page.locator('h1:has-text("Paper book")')).toBeVisible();
    await expect(page.locator('.card-header:has-text("Paper Positions")')).toBeVisible();
    await expect(page.locator('table.table-striped')).toBeVisible();
    await expect(page.locator('td:has-text("BBCA")').first()).toBeVisible();
  });

  test('orders table renders when Orders tab is active', async ({ page }) => {
    await page.goto('/phase3');
    await page.locator('button.tab-btn:has-text("Orders")').click();
    await expect(page.locator('.card-header:has-text("Paper Orders")')).toBeVisible();
    await expect(page.locator('td:has-text("BBCA")').first()).toBeVisible();
  });

  test('trades table renders when Trades tab is active', async ({ page }) => {
    await page.goto('/phase3');
    await page.locator('button.tab-btn:has-text("Trades")').click();
    await expect(page.locator('.card-header:has-text("Paper Trades")')).toBeVisible();
    await expect(page.locator('td:has-text("BBCA")').first()).toBeVisible();
  });

  test('scheduler + dedup + audit render in one card stack', async ({ page }) => {
    await page.goto('/phase3');
    await page.locator('button.tab-btn:has-text("Scheduler")').click();
    await expect(page.locator('.card-header:has-text("Latest Job Runs")')).toBeVisible();
    await expect(page.locator('td:has-text("decide")').first()).toBeVisible();
    await expect(page.locator('.card-header:has-text("Notification Dedup")')).toBeVisible();
    await expect(page.locator('td:has-text("gap-up")').first()).toBeVisible();
    await expect(page.locator('.card-header:has-text("Recent Audit Events")')).toBeVisible();
    await expect(page.locator('td:has-text("snapshot.created")').first()).toBeVisible();
  });

  test('no write API calls during Phase3 interaction', async ({ page }) => {
    const log = new RequestLog();
    log.attach(page);
    await page.goto('/phase3');
    await page.waitForLoadState('networkidle');

    await page.locator('button.tab-btn:has-text("Orders")').click();
    await page.locator('button.tab-btn:has-text("Trades")').click();
    await page.locator('button.tab-btn:has-text("Scheduler")').click();
    await page.waitForTimeout(500);

    const writes = log.writeAttempts();
    expect(writes, `unexpected writes: ${writes.map((w) => `${w.method()} ${w.url()}`).join(', ')}`).toHaveLength(0);

    const methods = log.apiRequests().map((r) => `${r.method()} ${r.url()}`);
    for (const m of methods) {
      expect(m, `non-GET request observed: ${m}`).toMatch(/^GET /);
    }
  });
});
