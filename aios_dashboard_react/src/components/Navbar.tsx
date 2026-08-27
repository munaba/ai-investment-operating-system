import { NavLink, useLocation } from 'react-router-dom';
import { motion } from 'framer-motion';
import Icon from './Icon';

const NAV = [
  { to: '/phase0', label: 'System integrity', icon: 'terminal' },
  { to: '/phase1', label: 'Journal & briefs', icon: 'book-open' },
  { to: '/phase2', label: 'Observation window', icon: 'circle-dot' },
  { to: '/phase3', label: 'Paper book', icon: 'activity' },
];

export default function Navbar() {
  const location = useLocation();
  return (
    <nav className="navbar">
      <NavLink to="/" className="navbar-brand">AIOS</NavLink>
      <div className="navbar-nav">
        {NAV.map((n) => {
          const isActive = location.pathname === n.to;
          return (
            <NavLink
              key={n.to}
              to={n.to}
              className={`nav-link${isActive ? ' active' : ''}`}
              aria-current={isActive ? 'page' : undefined}
            >
              <Icon name={n.icon} />
              {n.label}
              {isActive && (
                <motion.span className="nav-underline" layoutId="navbar-underline" transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }} />
              )}
            </NavLink>
          );
        })}
      </div>
      <span className="ro-plate">read-only</span>
    </nav>
  );
}
