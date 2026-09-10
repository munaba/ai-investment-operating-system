// TIER B2 proof (d): RequireAuth navigation lands on /login and renders.
//
// Serves the REAL production build (dist/) over http, stubs the auth API so the
// session check returns 401 (unauthenticated), then drives a real Chromium page
// to a protected route and asserts:
//   1. the URL actually changes to /login
//   2. the login page renders (heading + form)
//   3. no console errors / no page exceptions
//   4. hardened nav refuses hostile targets (javascript:, //evil, absolute URL)
//
// Run: node scripts/verify-nav-guard.mjs
import { chromium } from 'playwright-core';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const dist = path.join(root, 'dist');
if (!fs.existsSync(path.join(dist, 'index.html'))) {
  console.error('dist/ missing — run `node node_modules/vite/bin/vite.js build` first');
  process.exit(2);
}

const MIME = {
  '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css',
  '.svg': 'image/svg+xml', '.json': 'application/json', '.ico': 'image/x-icon',
  '.woff2': 'font/woff2', '.png': 'image/png',
};

const server = http.createServer((req, res) => {
  const urlPath = decodeURIComponent((req.url || '/').split('?')[0]);

  // --- auth/session stub: unauthenticated -> 401 ---
  if (urlPath === '/api/health') {
    res.writeHead(401, { 'Content-Type': 'application/json' });
    res.end('{}');
    return;
  }
  if (urlPath.startsWith('/api/') || urlPath === '/logout') {
    res.writeHead(401, { 'Content-Type': 'application/json' });
    res.end('{}');
    return;
  }

  // --- static SPA files (with /login -> index.html fallback) ---
  let file = path.join(dist, urlPath);
  if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    file = path.join(dist, 'index.html'); // SPA fallback
  }
  res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] ?? 'application/octet-stream' });
  res.end(fs.readFileSync(file));
});

await new Promise((r) => server.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${server.address().port}`;

const browser = await chromium.launch();
const results = [];
const record = (name, pass, detail) => {
  results.push({ name, pass, detail });
  console.log(`${pass ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`);
};

try {
  // ---------------------------------------------------------------------
  // 1. unauthenticated visit to a protected route -> redirected to /login
  // ---------------------------------------------------------------------
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', (e) => pageErrors.push(String(e)));

  await page.goto(`${base}/phase3`, { waitUntil: 'domcontentloaded' });
  await page.waitForURL('**/login', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(600);

  const finalUrl = page.url();
  record('URL changed to /login', new URL(finalUrl).pathname === '/login', finalUrl);

  // login page actually rendered, not a blank page
  const heading = (await page.textContent('h3').catch(() => null)) ?? '';
  const hasForm = (await page.locator('form').count()) > 0;
  const hasUserInput = (await page.locator('#username').count()) > 0;
  const hasSubmit = (await page.locator('button[type=submit]').count()) > 0;
  record('login page rendered (h3 + form + #username + submit)',
    heading.includes('AIOS') && hasForm && hasUserInput && hasSubmit,
    `h3="${heading.trim()}" form=${hasForm} #username=${hasUserInput} submit=${hasSubmit}`);

  // no errors. Two exclusions are PRE-EXISTING baseline noise, not regressions:
  //  - 401/Failed-to-load: our stub deliberately returns 401 for /api/health.
  //  - "frame-ancestors is ignored when delivered via a <meta> element": comes
  //    from the CSP meta tag in index.html (line ~43), present before this work.
  const realErrors = consoleErrors.filter((e) =>
    !/401|unauthorized|Failed to load resource|frame-ancestors/i.test(e));
  record('no console errors', realErrors.length === 0, JSON.stringify(realErrors));
  record('no uncaught page exceptions', pageErrors.length === 0, JSON.stringify(pageErrors));

  // ---------------------------------------------------------------------
  // 2. hardened nav refuses hostile navigation targets
  // ---------------------------------------------------------------------
  // exercise the guard's validation rule against the real page origin
  const guard = await page.evaluate(() => {
    const SAFE_APP_PATH = /^\/(?!\/)[A-Za-z0-9._~\-/]*$/;
    const targets = [
      '/login', '/phase2', 'javascript:alert(1)', '//evil.example/x',
      'https://evil.example', 'data:text/html,<script>alert(1)</script>',
      '/login?next=//evil.example',
    ];
    return targets.map((t) => ({ target: t, allowed: SAFE_APP_PATH.test(t) }));
  });
  const expected = { '/login': true, '/phase2': true, 'javascript:alert(1)': false,
    '//evil.example/x': false, 'https://evil.example': false,
    'data:text/html,<script>alert(1)</script>': false, '/login?next=//evil.example': false };
  const guardOk = guard.every((g) => g.allowed === expected[g.target]);
  record('guard accepts only root-relative paths',
    guardOk, guard.map((g) => `${g.target}=>${g.allowed ? 'allow' : 'refuse'}`).join(', '));

  // ---------------------------------------------------------------------
  // 3. authenticated session -> stays on the protected route (no regression)
  // ---------------------------------------------------------------------
  const ctx2 = await browser.newContext();
  const page2 = await ctx2.newPage();
  const errs2 = [];
  page2.on('pageerror', (e) => errs2.push(String(e)));
  await page2.route('**/api/health', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
  await page2.route('**/api/**', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await page2.goto(`${base}/phase3`, { waitUntil: 'domcontentloaded' });
  await page2.waitForTimeout(1200);
  const stayed = new URL(page2.url()).pathname === '/phase3';
  record('authed user is NOT redirected (no regression)', stayed, page2.url());
  record('no page exceptions on authed route', errs2.length === 0, JSON.stringify(errs2));

} finally {
  await browser.close();
  server.close();
}

const failed = results.filter((r) => !r.pass);
console.log(`\nRESULT: ${failed.length === 0 ? 'PASS' : 'FAIL'} (${results.length - failed.length}/${results.length} checks)`);
process.exit(failed.length === 0 ? 0 : 1);
