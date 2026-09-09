import GateStrip from './GateStrip';
import AlertBanner from './AlertBanner';
import Navbar from './Navbar';
import { Outlet, useLocation } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { EASE_OUT } from '../motion/Motion';

const STATIC_ROUTES = ['/atrium', '/atlas', '/arc', '/materi', '/jejak', '/ikhtisar', '/ime', '/profil'];

export default function MainLayout() {
  const location = useLocation();
  const isStatic = STATIC_ROUTES.includes(location.pathname);
  return (
    <div className="app-shell">
      <Navbar />
      <GateStrip />
      <main className={isStatic ? 'main-content w-full' : 'main-content mx-auto w-full max-w-[1200px] px-6'}>
        <AlertBanner />
        <AnimatePresence mode="wait">
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.24, ease: EASE_OUT }}
          >
            <Outlet />
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}
