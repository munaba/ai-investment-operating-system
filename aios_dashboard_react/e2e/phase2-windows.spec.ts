import { test, expect } from '@playwright/test';
import { stubApi, RequestLog } from './helpers';

// Phase2 — Observation Window: read paths only. /decision/submit is the ONLY write
// path (POST → external CLI), intentionally not exercised by these tests.
test.describe('Phase2 — Observation Window (read-only viewer)', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      try { localStorage.setItem('aios.session', '1'); } catch { /* ignore */ }
    });
    await stubApi(page);
  });

  test('windows list renders with status badges', async ({ page }) => {
    await page.goto('/phase2');
    await expect(page.locator('h1:has-text("Observation window")')).toBeVisible();
    await expect(page.locator('text=Observation Windows')).toBeVisible();
    await expect(page.locator('tbody tr').first()).toBeVisible();
    // Fixture windows: 7001 ACTIVE, 7002 CLOSED
    await expect(page.locator('td:has-text("7001")').first()).toBeVisible();
    await expect(page.locator('td:has-text("ACTIVE")').first()).toBeVisible();
    await expect(page.locator('td:has-text("7002")').first()).toBeVisible();
    await expect(page.locator('td:has-text("CLOSED")').first()).toBeVisible();
  });

  test('selecting a row loads review via GET', async ({ page }) => {
    await page.goto('/phase2');
    await expect(page.locator('tbody tr').first()).toBeVisible();
    // Page auto-selects ACTIVE window (7001) on load and fetches its review.
    // Wait for that auto-fetch to settle before asserting the evidence panel.
    await expect(page.locator('text=Sustained-Use Review Evidence')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('text=COMPLETE_EVIDENCE').first()).toBeVisible();
    // Clicking the closed-window row should fetch that window's review instead.
    // We assert the request actually fires.
    const reviewResp = page.waitForResponse((r) => r.url().includes('/api/phase2/review/7002'));
    await page.locator('tbody tr').nth(1).click();
    await reviewResp;
    await expect(page.locator('text=Sustained-Use Review Evidence')).toBeVisible();
  });

  test('no write API calls during Phase2 read interaction', async ({ page }) => {
    const log = new RequestLog();
    log.attach(page);
    await page.goto('/phase2');
    await page.waitForLoadState('networkidle');

    await page.locator('tbody tr').nth(1).click();
    await page.waitForTimeout(500);

    const writes = log.writeAttempts();
    expect(writes, `unexpected writes: ${writes.map((w) => `${w.method()} ${w.url()}`).join(', ')}`).toHaveLength(0);

    const methods = log.apiRequests().map((r) => `${r.method()} ${r.url()}`);
    for (const m of methods) {
      expect(m, `non-GET request observed: ${m}`).toMatch(/^GET /);
    }
  });
});
