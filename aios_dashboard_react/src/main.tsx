import React, { Suspense, lazy } from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { MotionConfig } from 'framer-motion';
import { AuthProvider, RequireAuth } from './auth/AuthContext';
import { ErrorBoundary } from './components/ErrorBoundary';
import MainLayout from './components/MainLayout';

// Route-level code splitting: Home + Login are eager (they are the entry and the
// auth gate), every other page loads on demand so the initial bundle shrinks.
import Home from './pages/Home';
import Login from './pages/Login';

const Phase0 = lazy(() => import('./pages/Phase0'));
const Phase1 = lazy(() => import('./pages/Phase1'));
const Phase2 = lazy(() => import('./pages/Phase2'));
const Phase3 = lazy(() => import('./pages/Phase3'));
const StaticFrame = lazy(() => import('./pages/StaticFrame'));
const NotFound = lazy(() => import('./pages/NotFound'));

import './styles/tokens.css';
import './styles/theme.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
    <MotionConfig reducedMotion="user">
    <BrowserRouter>
      <AuthProvider>
        <Suspense fallback={null}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<RequireAuth><MainLayout /></RequireAuth>}>
            <Route path="/" element={<Home />} />
            <Route path="/phase0" element={<Phase0 />} />
            <Route path="/phase1" element={<Phase1 />} />
            <Route path="/phase2" element={<Phase2 />} />
            <Route path="/phase3" element={<Phase3 />} />
            <Route path="/atrium" element={<StaticFrame src="/static/atrium.html" title="AIOS — Atrium" />} />
            <Route path="/atlas" element={<StaticFrame src="/static/atlas.html" title="AIOS — Atlas" />} />
            <Route path="/arc" element={<StaticFrame src="/static/arc.html" title="AIOS — Arc" />} />
            <Route path="/materi" element={<StaticFrame src="/static/materi.html" title="AIOS — Materi" />} />
            <Route path="/jejak" element={<StaticFrame src="/static/jejak.html" title="AIOS — Jejak" />} />
            <Route path="/ime" element={<StaticFrame src="/static/ikhtisar.html" title="AIOS — Ikhtisar" />} />
            <Route path="/ikhtisar" element={<StaticFrame src="/static/ikhtisar.html" title="AIOS — Ikhtisar" />} />
            <Route path="/profil" element={<StaticFrame src="/static/profil.html" title="AIOS — Profil" />} />
          </Route>
          <Route path="*" element={<NotFound />} />
        </Routes>
        </Suspense>
      </AuthProvider>
    </BrowserRouter>
    </MotionConfig>
    </ErrorBoundary>
  </React.StrictMode>,
);
