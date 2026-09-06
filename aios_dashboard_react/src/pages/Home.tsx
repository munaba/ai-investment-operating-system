import { Link } from 'react-router-dom';
import Icon from '../components/Icon';
import { Stagger, StaggerItem } from '../motion/Motion';

const LINKS = [
  { to: '/phase0', icon: 'terminal', label: 'System integrity', desc: 'Baca status & alert sistem' },
  { to: '/phase1', icon: 'book-open', label: 'Journal & briefs', desc: 'Catatan keputusan & brief harian' },
  { to: '/phase2', icon: 'circle-dot', label: 'Observation window', desc: 'Jendela observasi & evidence' },
  { to: '/phase3', icon: 'activity', label: 'Paper book', desc: 'Posisi & operasi paper trading' },
];

export default function Home() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center px-6 py-10">
      <Stagger className="w-full max-w-[920px] text-center" gap={0.07}>
        <h1 className="font-display text-[2.6rem] font-bold tracking-tight text-white">AIOS<span className="text-lime">.</span></h1>
        <p className="mb-6 text-[0.92rem] text-gray">Personal IDX decision &amp; support agent — read-only dashboard.</p>
        <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {LINKS.map((l) => (
            <StaggerItem key={l.to}>
              <Link to={l.to} className="flex flex-col gap-2 rounded-[10px] border border-edge bg-panel p-4 text-left no-underline text-white transition hover:border-lime hover:bg-[rgba(212,255,63,.04)] active:scale-[0.985]">
                <span className="inline-flex text-lime"><Icon name={l.icon} color="lime" /></span>
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
