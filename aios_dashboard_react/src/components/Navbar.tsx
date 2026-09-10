import { useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { motion } from 'framer-motion';
import Icon from './Icon';

const NAV = [
  { to: '/phase0', label: 'System integrity', icon: 'terminal' },
  { to: '/phase1', label: 'Journal & briefs', icon: 'book-open' },
  { to: '/phase2', label: 'Observation window', icon: 'circle-dot' },
  { to: '/phase3', label: 'Paper book', icon: 'activity' },
  { to: '/atrium', label: 'Atrium', icon: 'brain' },
  { to: '/atlas', label: 'Atlas', icon: 'chart-bar' },
  { to: '/arc', label: 'Arc', icon: 'database' },
  { to: '/materi', label: 'Materi', icon: 'wallet' },
  { to: '/jejak', label: 'Jejak', icon: 'clock' },
  { to: '/ikhtisar', label: 'Ikhtisar', icon: 'shield-check' },
  { to: '/profil', label: 'Profil', icon: 'file-text' },
];

export default function Navbar() {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  return (
    <nav className="navbar">
      <NavLink to="/" className="navbar-brand" onClick={() => setOpen(false)}>AIOS</NavLink>
      <button
        type="button"
        className="navbar-toggle"
        aria-label={open ? 'Close navigation' : 'Open navigation'}
        aria-expanded={open}
        aria-controls="main-nav"
        onClick={() => setOpen((v) => !v)}
      >
        <span aria-hidden="true">{open ? '✕' : '☰'}</span>
      </button>
      <div id="main-nav" className={`navbar-nav${open ? ' is-open' : ''}`}>
        {NAV.map((n) => {
          const isActive = location.pathname === n.to;
          return (
            <NavLink
              key={n.to}
              to={n.to}
              className={`nav-link${isActive ? ' active' : ''}`}
              aria-current={isActive ? 'page' : undefined}
              onClick={() => setOpen(false)}
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
