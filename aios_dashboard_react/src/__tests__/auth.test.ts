import { describe, it, expect, vi, afterEach } from 'vitest';
import { hasSession } from '../api/client';

// hasSession() must derive truth from the SERVER (/api/health), never from a
// client-controlled localStorage flag. These tests prove the spoofing hole is closed.
describe('client.hasSession — server is source of truth', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('returns true on /api/health 200 and sets the optimistic flag', async () => {
    localStorage.setItem('aios.session', '0'); // no local flag present
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200 } as Response));
    const ok = await hasSession();
    expect(ok).toBe(true);
    expect(localStorage.getItem('aios.session')).toBe('1');
  });

  it('returns false on /api/health 401 even if localStorage was spoofed to "1"', async () => {
    localStorage.setItem('aios.session', '1'); // attacker spoof
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401 } as Response));
    const ok = await hasSession();
    expect(ok).toBe(false); // server wins — spoofed flag is ignored
    expect(localStorage.getItem('aios.session')).toBeNull();
  });

  it('returns false when the network call throws', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network')));
    const ok = await hasSession();
    expect(ok).toBe(false);
  });
});
