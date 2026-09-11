import { describe, it, expect, vi, afterEach } from 'vitest';
import { hasSession } from '../api/client';

// M-09: hasSession() must derive truth ONLY from the server (/api/health).
// localStorage is never read nor written by auth code — a spoofed
// 'aios.session' value must have zero effect on the result.
describe('client.hasSession — server is source of truth (M-09)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('returns true on /api/health 200 and writes NOTHING to localStorage', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200 } as Response));
    const ok = await hasSession();
    expect(ok).toBe(true);
    expect(localStorage.getItem('aios.session')).toBeNull();
  });

  it('returns false on /api/health 401 even if localStorage was spoofed to "1"', async () => {
    localStorage.setItem('aios.session', '1'); // attacker spoof
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401 } as Response));
    const ok = await hasSession();
    expect(ok).toBe(false); // server wins — spoofed flag is ignored
  });

  it('returns false on /api/health 200=false path (ok:false) with spoofed flag present', async () => {
    localStorage.setItem('aios.session', '1');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 403 } as Response));
    const ok = await hasSession();
    expect(ok).toBe(false);
  });

  it('returns false when the network call throws', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network')));
    const ok = await hasSession();
    expect(ok).toBe(false);
  });
});
