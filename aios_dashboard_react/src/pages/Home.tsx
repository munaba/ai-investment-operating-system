import { Link } from 'react-router-dom';
import Icon from '../components/Icon';

const LINKS = [
  { to: '/phase0', icon: 'terminal', label: 'System integrity' },
  { to: '/phase1', icon: 'book-open', label: 'Journal & briefs' },
  { to: '/phase2', icon: 'circle-dot', label: 'Observation window' },
  { to: '/phase3', icon: 'activity', label: 'Paper book' },
];

export default function Home() {
  return (
    <div className="home-gate">
      <div className="hg-inner">
        <div className="hg-brand">AIOS<span style={{ color: 'var(--lime)' }}>.</span></div>
        <p className="hg-sub">Personal IDX decision &amp; support agent — read-only dashboard.</p>
        <div className="hg-links">
          {LINKS.map((l) => (
            <Link key={l.to} to={l.to} className="hg-btn">
              <Icon name={l.icon} />
              {l.label}
            </Link>
          ))}
        </div>
        <div className="ro-pill">read-only · human-gated decisions only</div>
      </div>
    </div>
  );
}
