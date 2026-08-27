import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Login from '../pages/Login';

vi.mock('../auth/AuthContext', () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  useAuth: vi.fn(),
  RequireAuth: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

import { useAuth } from '../auth/AuthContext';

describe('Login page', () => {
  beforeEach(() => vi.clearAllMocks());

  it('shows an error message when credentials are wrong', async () => {
    let err: string | null = null;
    const login = vi.fn().mockImplementation(async () => {
      err = 'username atau password salah';
      return false;
    });
    (useAuth as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      login,
      get loginError() {
        return err;
      },
    });
    render(<MemoryRouter><Login /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: 'nabil' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'bad' } });
    fireEvent.click(screen.getByRole('button', { name: /login/i }));
    await waitFor(() => expect(screen.getAllByText((_, el) =>
      !!(el?.textContent && el.textContent.toLowerCase().includes('username atau password salah'))
    ).length).toBeGreaterThan(0));
  });

  it('calls login with the entered credentials', async () => {
    const login = vi.fn().mockResolvedValue(false);
    (useAuth as unknown as ReturnType<typeof vi.fn>).mockReturnValue({ login, loginError: null });
    render(<MemoryRouter><Login /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: 'nabil' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'pw' } });
    fireEvent.click(screen.getByRole('button', { name: /login/i }));
    await waitFor(() => expect(login).toHaveBeenCalledWith('nabil', 'pw'));
  });
});
