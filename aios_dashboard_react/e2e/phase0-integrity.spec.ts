import { test, expect } from '@playwright/test';
import { stubApi, RequestLog } from './helpers';

// Phase0 — System Integrity: db-info (read), tables (read), no writes during interaction.
test.describe('Phase0 — System Integrity (read-only viewer)', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      try { localStorage.setItem('aios.session', '1'); } catch { /* ignore */ }
    });
    await stubApi(page);
  });

  test('db-info card renders with read-only mode badge', async ({ page }) => {
    await page.goto('/phase0');
    await expect(page.locator('h1:has-text("System integrity")')).toBeVisible();
    await expect(page.locator('text=Database Information')).toBeVisible();
    await expect(page.locator('text=Read from')).toBeVisible();
  });

  test('tables list renders', async ({ page }) => {
    await page.goto('/phase0');
    await expect(page.locator('text=Database Tables')).toBeVisible();
    await expect(page.locator('td:has-text("journal_entries")')).toBeVisible();
    await expect(page.locator('td:has-text("decision_briefs")')).toBeVisible();
    await expect(page.locator('td:has-text("positions")')).toBeVisible();
  });

  test('no write API calls during Phase0 interaction', async ({ page }) => {
    const log = new RequestLog();
    log.attach(page);
    await page.goto('/phase0');
    await page.waitForLoadState('networkidle');

    const writes = log.writeAttempts();
    expect(writes, `unexpected writes: ${writes.map((w) => `${w.method()} ${w.url()}`).join(', ')}`).toHaveLength(0);

    const methods = log.apiRequests().map((r) => `${r.method()} ${r.url()}`);
    for (const m of methods) {
      expect(m, `non-GET request observed: ${m}`).toMatch(/^GET /);
    }
  });
});
