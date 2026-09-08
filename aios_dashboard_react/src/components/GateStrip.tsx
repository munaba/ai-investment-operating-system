import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import './GateStrip.css';
import { getPhase2Windows, getPhase2Review } from '../api/client';
import { useReducedMotionSafe } from '../hooks/useReducedMotionSafe';

// Mirrors Models/ObservationWindow.cs + Models/FinalReviewRecord.cs
interface ObservationWindow {
  windowId: number;
  status: string;
  endAt: string | null;
}
interface FinalReviewRecord {
  observationWindowId: number;
  humanDecision: string | null;
  evidenceStatus: string | null;
}

interface GateStripData {
  window: ObservationWindow | null;
  review: FinalReviewRecord | null;
}

// Real fetch contract — backs onto the ASP.NET /api minimal API (read-only
// mirror of DatabaseService.GetObservationWindowsAsync / GetFinalReviewRecordAsync).
async function loadGateData(): Promise<GateStripData> {
  const windows = await getPhase2Windows();
  // `operator_observation_windows.status` is 'ACTIVE' today (DB source), but
  // `positions.status` lives in the same UI in lowercase ('closed'). Normalise
  // here so a future casing drift does not silently orphan the gate.
  const window = windows.find((w) => w.status.toUpperCase() === 'ACTIVE') ?? null;
  const review = window ? await getPhase2Review(window.windowId) : null;
  return { window, review };
}

const evidencePct = (status: string | null | undefined): number => {
  switch (status) {
    case 'COMPLETE_EVIDENCE': return 100;
    case 'PARTIAL_EVIDENCE': return 60;
    case 'INSUFFICIENT_DATA': return 30;
    case 'NOT_VERIFIABLE': return 15;
    default: return 0;
  }
};

const evidenceStatusClass = (status: string | null | undefined): string => {
  switch (status) {
    case 'COMPLETE_EVIDENCE':
    case 'PARTIAL_EVIDENCE':
      return 'badge-status-available';
    case 'INSUFFICIENT_DATA':
      return 'badge-status-insufficient-data';
    case 'NO_DATA':
      return 'badge-status-no-data';
    case 'NOT_VERIFIABLE':
      return 'badge-status-not-verifiable';
    default:
      return '';
  }
};

const decisionColor = (decision: string): string => {
  switch (decision) {
    case 'CONTINUE': return 'var(--lime)';
    case 'SIMPLIFY': return 'var(--amber)';
    case 'AUTHORIZE_FUTURE_INVESTIGATION': return 'var(--gray)';
    default: return 'var(--gray-dim)';
  }
};

const daysLeft = (endAt: string | null): number | null => {
  if (!endAt) return null;
  const end = new Date(endAt);
  if (Number.isNaN(end.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  end.setHours(0, 0, 0, 0);
  return Math.round((end.getTime() - today.getTime()) / 86_400_000);
};

const staggerItem = {
  hidden: { opacity: 0, x: -6 },
  show: { opacity: 1, x: 0 },
};

export default function GateStrip() {
  const [data, setData] = useState<GateStripData | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  // Signature moment only animates when the user allows motion.
  const prefersReduced = useReducedMotionSafe();

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | undefined;

    async function tick() {
      try {
        const next = await loadGateData();
        if (!cancelled) {
          setData(next);
          setLastRefresh(new Date());
        }
      } catch {
        // strip is best-effort; body must always render — same contract as Blazor
        if (!cancelled) setData(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    // 60s refresh — same cadence as PeriodicTimer in GateStrip.razor
    const start = () => {
      if (timer !== undefined) return;
      timer = setInterval(tick, 60_000);
    };
    const stop = () => {
      if (timer !== undefined) {
        clearInterval(timer);
        timer = undefined;
      }
    };

    // P1-6a: pause while hidden, resume on return. Resume only re-arms the
    // interval — no immediate tick(), so returning never double-fetches.
    const onVisibilityChange = () => {
      if (document.hidden) stop();
      else start();
    };

    tick();
    if (!document.hidden) start();
    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      cancelled = true;
      stop();
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, []);

  const window_ = data?.window ?? null;
  const review = data?.review ?? null;
  const decision = review?.humanDecision ?? 'NO_REVIEW';
  const isPending = decision === 'PENDING';
  const pct = evidencePct(review?.evidenceStatus);
  const left = window_ ? daysLeft(window_.endAt) : null;

  const formatTime = (d: Date) => d.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

  return (
    <div className="gate-strip">
      <AnimatePresence mode="wait">
        {loading ? (
          <motion.span
            key="loading"
            className="gate-item"
            initial={prefersReduced ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={prefersReduced ? undefined : { opacity: 0 }}
          >
            ◇ loading window…
          </motion.span>
        ) : !window_ ? (
          <motion.div
            key="empty"
            style={{ display: 'contents' }}
            initial="hidden"
            animate="show"
            variants={{ show: { transition: { staggerChildren: prefersReduced ? 0 : 0.05 } } }}
          >
            <motion.span className="gate-item" variants={staggerItem}>◆ no active observation window</motion.span>
            <span className="gate-sep">│</span>
            <motion.span className="gate-item" variants={staggerItem}>evidence —</motion.span>
            <span className="gate-sep">│</span>
            <motion.span className="gate-item" variants={staggerItem}>
              decision <span className="decision-dot" />
            </motion.span>
          </motion.div>
        ) : (
          <motion.div
            key={window_.windowId}
            style={{ display: 'contents' }}
            initial="hidden"
            animate="show"
            variants={{ show: { transition: { staggerChildren: prefersReduced ? 0 : 0.06 } } }}
          >
            <motion.span className="gate-item" variants={staggerItem}>
              ◆ WINDOW <b>#{window_.windowId}</b> {window_.status.toUpperCase()}
            </motion.span>
            <span className="gate-sep gate-hide-sm">│</span>
            <motion.span className="gate-hide-sm" variants={staggerItem}>
              {left != null ? `sisa ${left} hari` : window_.endAt}
            </motion.span>
            <span className="gate-sep">│</span>
            <motion.span className="gate-item accent" variants={staggerItem}>
              evidence
              <span className="evidence-bar">
                <motion.span
                  initial={prefersReduced ? false : { width: 0 }}
                  animate={{ width: `${pct}%` }}
                  transition={{ duration: prefersReduced ? 0 : 0.6, ease: 'easeOut' }}
                />
              </span>
              <span className={`badge ${evidenceStatusClass(review?.evidenceStatus)} ms-2`}>
                {review?.evidenceStatus ?? 'NO_REVIEW'}
              </span>
            </motion.span>
            <span className="gate-sep gate-hide-sm">│</span>
            <motion.span className="gate-item" variants={staggerItem}>
              decision
              <motion.span
                className={`decision-dot${isPending ? ' pending' : ''}`}
                style={!isPending ? { background: decisionColor(decision) } : undefined}
                // Amber pulse (human-gate state indicator) — the ONLY intentional
                // animation loop. Suppressed under prefers-reduced-motion.
                animate={isPending && !prefersReduced
                  ? { boxShadow: ['0 0 0 3px rgba(255,200,60,.12)', '0 0 0 7px rgba(255,200,60,0)'] }
                  : undefined}
                transition={isPending && !prefersReduced
                  ? { duration: 2.4, repeat: Infinity, ease: 'easeInOut' }
                  : undefined}
              />
              {isPending ? 'Menunggu kamu' : decision}
            </motion.span>
            <span className="gate-sep">│</span>
            <span className="polling-indicator" aria-live="polite" aria-atomic="true">
              <span className="visually-hidden">Auto-refresh active</span>
              {lastRefresh ? `last ${formatTime(lastRefresh)}` : 'initializing…'}
            </span>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
