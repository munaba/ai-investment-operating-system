import { useEffect, useRef, useState } from 'react';

// The React equivalent of Blazor's PeriodicTimer + IDisposable auto-refresh:
// fire an async loader on mount, then every `intervalMs`, with proper
// cancellation on unmount. Mirrors the skill's "fire-and-forget _ = LoopAsync()"
// pattern but in effect-cleanup form.
export function usePolling<T>(
  loader: () => Promise<T>,
  intervalMs: number,
  options?: { immediate?: boolean; enabled?: boolean },
): { data: T | null; loading: boolean; error: Error | null; refresh: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const cancelledRef = useRef(false);

  const run = useRef(async () => {
    if (cancelledRef.current) return;
    try {
      const next = await loaderRef.current();
      if (cancelledRef.current) return;
      setData(next);
      setError(null);
    } catch (e) {
      if (cancelledRef.current) return;
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      if (!cancelledRef.current) setLoading(false);
    }
  });

  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | undefined;
    cancelledRef.current = false;

    const start = () => {
      if (timer !== undefined) return;
      timer = setInterval(() => void run.current(), intervalMs);
    };
    const stop = () => {
      if (timer !== undefined) {
        clearInterval(timer);
        timer = undefined;
      }
    };

    // P1-6a: pause polling while the tab is hidden, resume on return.
    // Resume only re-arms the interval — it does NOT fire run.current()
    // immediately, so returning to the tab never double-fetches.
    const onVisibilityChange = () => {
      if (document.hidden) {
        stop();
        return;
      }
      if (options?.immediate === false) return;
      start();
    };

    const enabled = options?.enabled !== false;

    void (async () => {
      if (options?.immediate === false || !enabled) {
        if (!enabled) setLoading(false);
        return;
      }
      await run.current();
      if (cancelledRef.current) return;
      if (!document.hidden) start();
    })();

    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      cancelledRef.current = true;
      stop();
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, options?.enabled]);

  // P1-6b: when a disabled poller is re-enabled (e.g. its tab becomes active
  // again), fetch once immediately instead of leaving the user looking at data
  // that may be up to one full interval stale.
  const wasEnabled = useRef(options?.enabled !== false);
  useEffect(() => {
    const enabled = options?.enabled !== false;
    if (enabled && !wasEnabled.current) {
      void run.current();
    }
    wasEnabled.current = enabled;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options?.enabled]);

  return { data, loading, error, refresh: () => void run.current() };
}
