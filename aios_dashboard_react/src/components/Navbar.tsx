import { NavLink } from 'react-router-dom';
import Icon from './Icon';

const NAV = [
  { to: '/phase0', label: 'System integrity', icon: 'terminal' },
  { to: '/phase1', label: 'Journal & briefs', icon: 'book-open' },
  { to: '/phase2', label: 'Observation window', icon: 'circle-dot' },
  { to: '/phase3', label: 'Paper book', icon: 'activity' },
];

export default function Navbar() {
  return (
    <nav className="navbar">
      <NavLink to="/" className="navbar-brand">AIOS</NavLink>
      <div className="navbar-nav">
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
          >
            <Icon name={n.icon} />
            {n.label}
          </NavLink>
        ))}
      </div>
      <span className="ro-plate">read-only</span>
    </nav>
  );
}
