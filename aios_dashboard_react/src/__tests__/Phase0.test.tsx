import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import Phase0 from '../pages/Phase0';
import * as api from '../api/client';

vi.mock('../api/client', () => ({
  getPhase0DbInfo: vi.fn(),
  getPhase0Tables: vi.fn(),
  testConnection: vi.fn(),
}));

describe('Phase0 — System integrity', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.getPhase0DbInfo as ReturnType<typeof vi.fn>).mockResolvedValue({
      path: 'investment_platform.db', exists: true, sizeMb: 12.5,
    });
    (api.getPhase0Tables as ReturnType<typeof vi.fn>).mockResolvedValue(['positions', 'orders', 'trades']);
  });

  it('smoke: renders key headings without crashing', async () => {
    render(<Phase0 />);
    expect(await screen.findByText('System integrity')).toBeInTheDocument();
    expect(await screen.findByText('Database Information')).toBeInTheDocument();
    expect(await screen.findByText('Connection Test')).toBeInTheDocument();
  });

  it('loading: renders without crashing while data is pending', () => {
    (api.getPhase0DbInfo as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}));
    (api.getPhase0Tables as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}));
    render(<Phase0 />);
    expect(screen.getByText('System integrity')).toBeInTheDocument();
  });

  it('error: failed connection shows danger alert, no crash', async () => {
    (api.testConnection as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('boom'));
    render(<Phase0 />);
    const btn = await screen.findByRole('button', { name: /Test Connection/i });
    fireEvent.click(btn);
    expect(await screen.findByText(/Connection failed/)).toBeInTheDocument();
  });

  it('interaction: successful test connection shows success alert', async () => {
    (api.testConnection as ReturnType<typeof vi.fn>).mockResolvedValue({ success: true });
    render(<Phase0 />);
    const btn = await screen.findByRole('button', { name: /Test Connection/i });
    fireEvent.click(btn);
    expect(await screen.findByText(/Connection successful/i)).toBeInTheDocument();
    expect(api.testConnection).toHaveBeenCalledOnce();
  });
});
