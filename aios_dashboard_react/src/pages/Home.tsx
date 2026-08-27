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
    <div className="home-gate">
      <Stagger className="hg-inner" gap={0.07}>
        <div className="hg-brand">AIOS<span style={{ color: 'var(--lime)' }}>.</span></div>
        <p className="hg-sub">Personal IDX decision &amp; support agent — read-only dashboard.</p>
        <div className="hg-links">
          {LINKS.map((l) => (
            <StaggerItem key={l.to}>
              <Link to={l.to} className="home-card">
                <span className="hc-icon"><Icon name={l.icon} color="lime" /></span>
                <span className="hc-title">{l.label}</span>
                <span className="hc-desc">{l.desc}</span>
              </Link>
            </StaggerItem>
          ))}
        </div>
        <div className="ro-pill">read-only · human-gated decisions only</div>
      </Stagger>
    </div>
  );
}
