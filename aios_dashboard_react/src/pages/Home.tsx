import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import Icon from '../components/Icon';
import { Stagger, StaggerItem } from '../motion/Motion';
import { useReducedMotionSafe } from '../hooks/useReducedMotionSafe';
import { useVaultMotion } from '../hooks/useVaultMotion';
import { usePolling } from '../hooks/usePolling';
import { getPhase3Positions } from '../api/client';
import type { Position } from '../api/types';
import { formatIdr } from '../lib/format';
import NumberFlow from '@number-flow/react';
import EquityChartBklit from '../components/EquityChartBklit';

const LINKS = [
  { to: '/phase0', icon: 'terminal', label: 'System integrity', desc: 'Baca status & alert sistem' },
  { to: '/phase1', icon: 'book-open', label: 'Journal & briefs', desc: 'Catatan keputusan & brief harian' },
  { to: '/phase2', icon: 'circle-dot', label: 'Observation window', desc: 'Jendela observasi & evidence' },
  { to: '/phase3', icon: 'activity', label: 'Paper book', desc: 'Posisi & operasi paper trading' },
];

export default function Home() {
  const prefersReduced = useReducedMotionSafe();
  const scopeRef = useVaultMotion<HTMLDivElement>();
  const positionsP = usePolling<Position[]>(getPhase3Positions, 30_000);
  const positions = positionsP.data ?? [];

  // Realized P&L — the only real portfolio-level figure in the data model.
  // (There is no "total portfolio value" metric; see audit.)
  const totalPnl = useMemo(
    () => positions.reduce((s, p) => s + p.realizedPnl, 0),
    [positions],
  );

  // Cumulative P&L curve — same derivation as Phase3's equity useMemo, so the
  // hero chart and the Phase3 chart can never disagree.
  const equity = useMemo(() => {
    const closed = positions
      .filter((p) => p.status.toLowerCase() === 'closed' && p.realizedPnl !== 0)
      .sort((a, b) => a.createdAt.localeCompare(b.createdAt));
    const labels: string[] = [];
    const data: number[] = [];
    let cum = 0;
    for (const p of closed) {
      const d = new Date(p.createdAt);
      if (Number.isNaN(d.getTime())) continue;
      labels.push(
        `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ` +
        `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`,
      );
      cum += p.realizedPnl;
      data.push(cum);
    }
    return { labels, data };
  }, [positions]);

  return (
    <div ref={scopeRef} className="relative overflow-hidden">
      {/* hero-glow from mockup: radial gold/wine, behind title — static if reduced-motion */}
      <div aria-hidden data-motion="glow" className="home-hero-glow" style={prefersReduced ? { display: 'none' } : undefined} />
      {/* Decorative drifting word — no data, so it stays out of the a11y tree */}
      <div aria-hidden data-motion="giant" className="hero-giant">tercatat.</div>

      <div className="relative z-[2] mx-auto max-w-[920px] px-6 py-16 text-center">
        <div data-motion="kicker" className="hero-kicker">observasi pasar, dicatat sejelas buktinya</div>

        <h1 data-motion="headline" className="hero-headline">
          Setiap posisi paper trading,<br /><em className="accent-em">terlihat hasilnya</em> hari ini.
        </h1>

        <p data-motion="sub" className="hero-sub">
          Paper book IDX — simulasi, bukan dana sungguhan. Angka di bawah adalah
          realized P&amp;L yang benar-benar tercatat.
        </p>

        <div data-motion="number" className="mb-10">
          <div className="hero-number">
            {prefersReduced ? (
              formatIdr(totalPnl)
            ) : (
              <NumberFlow
                value={totalPnl}
                locales="id-ID"
                format={{ style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }}
              />
            )}
          </div>
          <div className="mt-2 font-mono text-[0.7rem] uppercase tracking-[0.12em] text-[var(--ink-faint)]">
            realized p&amp;l · {positions.length} posisi tercatat
          </div>
        </div>

        {/* Hero frame carries the REAL cumulative P&L area chart — replaces the
            mockup's gold-bar photo (no per-asset imagery in the data model). */}
        {/* P1-7: reserve the chart's height so the container does not jump when
            equity data arrives. The empty state mirrors the chart's own
            aspect-ratio (2/1) instead of a fixed px, so the reserved box tracks
            the real chart height at every width (560px -> 280px, 342px -> 171px)
            rather than over-reserving on mobile. Text is centered in that box. */}
        <div
          data-motion="frame"
          className="hero-frame mx-auto mb-12 grid w-full max-w-[560px] place-items-center p-3"
        >
          {equity.data.length > 0 ? (
            <EquityChartBklit labels={equity.labels} data={equity.data} />
          ) : (
            <div className="flex w-full items-center justify-center" style={{ aspectRatio: '2 / 1' }}>
              <p className="px-4 text-[0.85rem] text-[var(--ink-faint)]">
                Belum ada posisi closed — kurva P&amp;L kumulatif muncul setelah ada posisi ditutup.
              </p>
            </div>
          )}
        </div>
      </div>

      <Stagger className="relative z-[2] mx-auto max-w-[920px] px-6 pb-16 text-center" gap={0.07}>
        <h2 className="font-display text-[2.6rem] font-bold tracking-tight text-white">AIOS<span className="text-[var(--gold)]">.</span></h2>
        <p className="mb-6 text-[0.92rem] text-gray">Personal IDX decision &amp; support agent — <em className="accent-em">read-only</em> dashboard.</p>
        <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {LINKS.map((l) => (
            <StaggerItem key={l.to}>
              <Link to={l.to} className="flex flex-col gap-2 rounded-[10px] border border-[var(--bg-edge)] bg-[var(--bg-raised)] p-4 text-left no-underline text-white transition hover:border-[var(--gold)] hover:bg-[rgba(205,162,63,.08)] active:scale-[0.985]">
                <span className="inline-flex text-[var(--gold)]"><Icon name={l.icon} color="gold" /></span>
                <span className="font-display text-[1.05rem] font-bold leading-none">{l.label}</span>
                <span className="text-[0.85rem] leading-relaxed text-gray">{l.desc}</span>
              </Link>
            </StaggerItem>
          ))}
        </div>
        <div className="font-mono text-[0.68rem] uppercase tracking-[0.12em] text-gray">read-only · human-gated decisions only</div>
      </Stagger>
    </div>
  );
}
