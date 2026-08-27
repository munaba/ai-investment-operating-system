import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, act } from '@testing-library/react';
import { usePolling } from '../hooks/usePolling';

// usePolling must be safe to unmount mid-fetch: after unmount, no setState may
// fire (would throw "can't update unmounted component"). The cancelledRef guard
// inside run.current() must suppress setData/setError/setLoading after unmount.
describe('usePolling — unmount during fetch does not crash', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('unmounts cleanly while the loader promise is still pending', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});

    // Controllable loader: holds the resolver so we can settle it after unmount.
    let resolveLoader: (v: string) => void = () => {};
    const loader = () =>
      new Promise<string>((resolve) => {
        resolveLoader = resolve;
      });

    function Probe() {
      usePolling(loader, 1000);
      return <div>probe</div>;
    }

    const { unmount } = render(<Probe />);

    // Give the mount-time run.current() a tick to call the loader (so resolveLoader is set)
    await act(async () => {
      await Promise.resolve();
    });

    // Unmount BEFORE the loader resolves
    unmount();

    // Resolve the pending loader AFTER unmount — must not setState
    await act(async () => {
      resolveLoader('done');
      await Promise.resolve();
    });

    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});
