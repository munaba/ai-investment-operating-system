import GateStrip from './GateStrip';
import AlertBanner from './AlertBanner';
import Navbar from './Navbar';
import { Outlet } from 'react-router-dom';

export default function MainLayout() {
  return (
    <div className="app-shell">
      <Navbar />
      <GateStrip />
      <main className="main-content" style={{ maxWidth: 1200, width: '100%' }}>
        <AlertBanner />
        <Outlet />
      </main>
    </div>
  );
}
