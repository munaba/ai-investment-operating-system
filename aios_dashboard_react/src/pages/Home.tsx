import { Link } from 'react-router-dom';
import Icon from '../components/Icon';
import { Stagger, StaggerItem } from '../motion/Motion';

const LINKS = [
  { to: '/phase0', icon: 'terminal', label: 'System integrity' },
  { to: '/phase1', icon: 'book-open', label: 'Journal & briefs' },
  { to: '/phase2', icon: 'circle-dot', label: 'Observation window' },
  { to: '/phase3', icon: 'activity', label: 'Paper book' },
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
              <Link to={l.to} className="hg-btn">
                <Icon name={l.icon} />
                {l.label}
              </Link>
            </StaggerItem>
          ))}
        </div>
        <div className="ro-pill">read-only · human-gated decisions only</div>
      </Stagger>
    </div>
  );
}
