import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { MotionConfig } from 'framer-motion';
import { AuthProvider, RequireAuth } from './auth/AuthContext';
import MainLayout from './components/MainLayout';
import Home from './pages/Home';
import Login from './pages/Login';
import Phase0 from './pages/Phase0';
import Phase1 from './pages/Phase1';
import Phase2 from './pages/Phase2';
import Phase3 from './pages/Phase3';
import './styles/tokens.css';
import './styles/theme.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MotionConfig reducedMotion="user">
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<RequireAuth><MainLayout /></RequireAuth>}>
            <Route path="/" element={<Home />} />
            <Route path="/phase0" element={<Phase0 />} />
            <Route path="/phase1" element={<Phase1 />} />
            <Route path="/phase2" element={<Phase2 />} />
            <Route path="/phase3" element={<Phase3 />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
    </MotionConfig>
  </React.StrictMode>,
);
