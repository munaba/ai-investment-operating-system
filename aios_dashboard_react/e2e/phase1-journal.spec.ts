import { test, expect } from '@playwright/test';
import { stubApi, RequestLog } from './helpers';

// Phase1 — Journal & Briefs: list renders, filtering narrows the table, click opens
// detail panes. All read-only — no POST/PUT/DELETE ever.
test.describe('Phase1 — Journal & Briefs (read-only viewer)', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      try { localStorage.setItem('aios.session', '1'); } catch { /* ignore */ }
    });
    await stubApi(page);
  });

  test('journal table renders 3 entries', async ({ page }) => {
    await page.goto('/phase1');
    await expect(page.locator('h1:has-text("Journal")')).toBeVisible();
    await expect(page.locator('table.table')).toBeVisible();
    await expect(page.locator('tbody tr')).toHaveCount(3);
    await expect(page.locator('th:has-text("Symbol")')).toBeVisible();
  });

  test('clicking a row opens the journal + brief detail panes', async ({ page }) => {
    await page.goto('/phase1');
    await expect(page.locator('tbody tr').first()).toBeVisible();
    await page.locator('tbody tr').first().click();
    await expect(page.locator('text=Journal Entry Details')).toBeVisible();
    await expect(page.locator('text=Decision Brief Details')).toBeVisible();
    await expect(page.locator('pre code').first()).toContainText('"entry_id": 1001');
  });

  test('Symbol filter narrows the table', async ({ page }) => {
    await page.goto('/phase1');
    await expect(page.locator('tbody tr')).toHaveCount(3);
    await page.locator('select#journal-filter-symbol').selectOption('BBCA');
    await expect(page.locator('tbody tr')).toHaveCount(1);
    await expect(page.locator('td:has-text("BBCA")').first()).toBeVisible();
    await page.locator('select#journal-filter-symbol').selectOption('');
    await expect(page.locator('tbody tr')).toHaveCount(3);
  });

  test('Decision filter narrows the table', async ({ page }) => {
    await page.goto('/phase1');
    await page.locator('select#journal-filter-decision').selectOption('TAKE');
    await expect(page.locator('tbody tr')).toHaveCount(1);
    await expect(page.locator('td .badge:has-text("TAKE")')).toBeVisible();
  });

  test('Risk Policy filter narrows the table', async ({ page }) => {
    await page.goto('/phase1');
    await page.locator('select#journal-filter-risk').selectOption('ACCEPTED');
    await expect(page.locator('tbody tr')).toHaveCount(2);
  });

  test('From-Date filter narrows the table', async ({ page }) => {
    await page.goto('/phase1');
    await page.locator('input[type="date"]').fill('2026-08-30');
    await expect(page.locator('tbody tr')).toHaveCount(1);
    await expect(page.locator('td:has-text("ASII")').first()).toBeVisible();
  });

  test('no write API calls occur during normal Phase1 interaction', async ({ page }) => {
    const log = new RequestLog();
    log.attach(page);
    await page.goto('/phase1');
    await page.waitForLoadState('networkidle');

    await page.locator('select#journal-filter-symbol').selectOption('TLKM');
    await page.locator('select#journal-filter-decision').selectOption('SKIP');
    await page.locator('tbody tr').first().click();
    await page.locator('button:has-text("Refresh")').click();

    const writes = log.writeAttempts();
    expect(writes, `unexpected writes: ${writes.map((w) => `${w.method()} ${w.url()}`).join(', ')}`).toHaveLength(0);

    const methods = log.apiRequests().map((r) => `${r.method()} ${r.url()}`);
    for (const m of methods) {
      expect(m, `non-GET request observed: ${m}`).toMatch(/^GET /);
    }
  });
});
