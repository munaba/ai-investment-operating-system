# AIOS Dashboard — Security Design Decisions

**Context:** Single-user LAN deployment (operator laptop + phone on home WiFi). No internet exposure. Threat model: prevent accidental misconfiguration, defend against physical device access (locked screen bypassed), and close XSS/CSRF surface area.

---

## M-05: HSTS + AllowedHosts

**Decision:** HSTS enabled in production (`UseHsts()` line 81 Program.cs, 6-month policy). `AllowedHosts` constrained to `localhost;192.168.*` (LAN-only).

**Reasoning:**
- HTTPS disabled for LAN HTTP-only (no cert). HSTS guards prod if HTTPS enabled later.
- AllowedHosts prevents Host header injection → cache poisoning / redirect attacks.
- `192.168.*` glob allows LAN discovery without hardcoding IPs.

**Prod upgrade path:** Obtain wildcard cert (Let's Encrypt DNS-01 for `*.lan.example`), enable `UseHttpsRedirection()`, update `AllowedHosts` to domain.

---

## M-06: CORS Whitelist

**Decision:** Explicit origin whitelist `http://localhost:5173` (dev), `http://192.168.44.47:5000` (LAN self-host). `AllowCredentials()` enabled (cookie auth).

**Reasoning:**
- React SPA dev server (5173) must send cookies cross-origin → explicit CORS.
- Prod serves React + API from same origin (5000) → CORS permits same-origin bypass.
- AllowAnyOrigin + AllowCredentials = runtime error (spec violation).
- Wildcard `http://192.168.*:*` rejected — attacker laptop on LAN could CSRF.

**Alternative rejected:** `AllowAnyOrigin()` without credentials → cookies blocked, auth broken.

---

## M-09: Session Storage — httpOnly Cookie + localStorage Optimistic Cache

**Decision:** Auth session stored in **httpOnly cookie** (server-side, inaccessible to JS). `localStorage` flag `aios.session=1` is an **optimistic UI cache** — NOT the auth mechanism.

**Implementation:**
1. **Backend** (`Program.cs:48`): Cookie `HttpOnly=true`, `SameSite=Lax`, `Secure=Always` (prod). Server validates cookie on every `/api/*` request.
2. **Frontend** (`client.ts:64-74`): `hasSession()` calls `/api/health` — server responds 200 (authed) or 401. Result updates localStorage hint.
3. **Spoofing blocked** (`auth.test.ts:20-26`): Test proves `localStorage.setItem('aios.session', '1')` attacker spoof → server 401 → `hasSession()` returns false. Server is source of truth.

**Reasoning:**
- **httpOnly cookie** = XSS cannot steal session token (even if script injected via CSP bypass, cookie inaccessible).
- **localStorage hint** = eliminates flash-of-login during route navigation (React reads flag, shows authed shell immediately; server validates async). If localStorage spoofed, server rejects next API call → user redirected to login.
- **SameSite=Lax** = CSRF blocked for state-changing requests (POST/PUT/DELETE). GET CSRF limited to top-level navigation (mitigated by POST-only logout).

**Alternatives considered:**
1. **localStorage-only session** (token in JS): ❌ XSS steals token → full compromise.
2. **sessionStorage**: Same risk as localStorage + lost on tab close.
3. **No localStorage hint, server-only**: ✅ More secure, but UX degrades (flash-of-login on every SPA route change while `/api/health` pending).

**Chosen:** httpOnly cookie (real auth) + localStorage (optimistic cache). Test coverage (`auth.test.ts`) proves spoofing ineffective.

---

## M-02: Rate Limiting (Login Brute-Force)

**Decision:** 5 attempts/min per IP (`FixedWindowRateLimiter` on `/api/auth/login`).

**Reasoning:** Single-user LAN → typo tolerance needed. 5/min blocks scripts, allows human retry. IP-based partition (not username) → attacker cannot DoS operator by failing their username.

---

## M-03 + M-08: Database Path Disclosure

**Decision:** API returns `{exists: bool, sizeMb: float}` — NOT `dbPath`. Server hardcodes path `IDatabaseService.DbPath`.

**Reasoning:** Path disclosure → attacker (physical access or XSS RCE) knows exact file to exfiltrate. Mitigated by never sending path to client.

---

## M-04: Error Message Sanitization

**Decision:** Exception stack traces logged server-side, client receives generic error: `"Gagal memuat daftar tabel."` (line 233 Program.cs).

**Reasoning:** Detailed error (e.g., `"SQLiteException: no such table 'admin_passwords'"`) leaks schema → attacker reconnaissance. Generic message safe.

---

## Additional Hardening (Defense in Depth)

- **CSP** (`Program.cs:109-119`): `default-src 'self'`, `frame-ancestors 'none'`, `object-src 'none'`. `wasm-unsafe-eval` required for Blazor.
- **X-Frame-Options: DENY**: Anti-clickjacking.
- **POST-only logout** (`Program.cs:188`): `SameSite=Lax` allows GET cookies on top-level nav → GET logout = CSRF. POST-only closes hole.
- **AuthContext navigation hardening** (`AuthContext.tsx:32-41`): `navigateToAppPath()` validates root-relative paths, blocks `javascript:`, `//attacker`, `data:` URLs.

---

**Last updated:** 2026-09-11  
**Audit refs:** `_AUDIT_SECURITY_CONTEXT.md` M-02, M-03, M-04, M-05, M-06, M-08, M-09
