import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import Icon from '../components/Icon';

export default function Login() {
  const { login, loginError } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    const ok = await login(username, password);
    setSubmitting(false);
    if (ok) navigate('/', { replace: true });
  };

  return (
    <div className="flex min-h-[70vh] items-center justify-center px-4 py-10">
      <div className="card w-[420px] max-w-[92vw]">
        <div className="card-body">
          <h3 className="font-display text-center text-xl font-bold">
            AIOS<span className="text-lime">.</span>
          </h3>
          <p className="page-sub text-center">
            Akses terbatas — jaringan rumah saja
          </p>

          {loginError && (
            <div className="alert alert-danger py-2 text-[0.82rem]">
              {loginError}
            </div>
          )}
          <form onSubmit={onSubmit}>
            <div className="mb-3.5">
              <label className="form-label" htmlFor="username">Username</label>
              <input
                id="username"
                className="form-control"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                autoComplete="username"
              />
            </div>
            <div className="mb-[18px]">
              <label className="form-label" htmlFor="password">Password</label>
              <input
                id="password"
                className="form-control"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
              />
            </div>
            <button type="submit" className="btn btn-primary w-100" disabled={submitting}>
              {submitting ? <span className="spinner" /> : <Icon name="lock" />}
              {submitting ? 'Memeriksa…' : 'Login'}
            </button>
          </form>

          <p className="page-sub mt-4 text-center text-[0.78rem]">
            Session timeout: 60 menit tidak aktif
          </p>
        </div>
      </div>
    </div>
  );
}
