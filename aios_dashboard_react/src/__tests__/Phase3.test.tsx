import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import Phase3 from '../pages/Phase3';
import * as api from '../api/client';

vi.mock('../api/client', () => ({
  getPhase3Positions: vi.fn(),
  getPhase3Orders: vi.fn(),
  getPhase3Trades: vi.fn(),
  getPhase3Scheduler: vi.fn(),
  getPhase3Dedup: vi.fn(),
  getPhase3Audit: vi.fn(),
}));

const POS = [{
  positionId: 1, accountId: 'ACC', symbol: 'BBCA', quantity: 100, averagePrice: 9000,
  realizedPnl: 120000, status: 'CLOSED', direction: 'LONG', stopLoss: 8700, takeProfit: 9500,
  buyFeeAccumulated: 9000, createdAt: '2026-08-20T10:00:00Z',
}];

describe('Phase3 — Paper book', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.getPhase3Positions as ReturnType<typeof vi.fn>).mockResolvedValue(POS);
    (api.getPhase3Orders as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    (api.getPhase3Trades as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    (api.getPhase3Scheduler as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    (api.getPhase3Dedup as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    (api.getPhase3Audit as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  });

  it('smoke: renders page + default positions tab', async () => {
    render(<Phase3 />);
    expect(await screen.findByText(/Paper book/)).toBeInTheDocument();
    expect(await screen.findByText('Positions')).toBeInTheDocument();
    expect(await screen.findByText('BBCA')).toBeInTheDocument();
  });

  it('loading: shows spinner while positions pending', () => {
    (api.getPhase3Positions as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}));
    render(<Phase3 />);
    expect(document.querySelector('.spinner')).toBeInTheDocument();
  });

  it('error: failed positions fetch shows fallback, no crash', async () => {
    (api.getPhase3Positions as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('x'));
    render(<Phase3 />);
    expect(await screen.findByText(/Paper book/)).toBeInTheDocument();
  });

  it('interaction: switching to Equity/P&L tab shows animated equity chart', async () => {
    render(<Phase3 />);
    const tab = await screen.findByRole('button', { name: /Equity\/P&L/i });
    fireEvent.click(tab);
    const chart = await screen.findByLabelText('Equity curve', undefined, { timeout: 2000 });
    expect(chart).toBeInTheDocument();
    expect(chart.tagName.toLowerCase()).toBe('svg');
  });

  it('interaction: switching to Orders tab calls getPhase3Orders', async () => {
    render(<Phase3 />);
    const tab = await screen.findByRole('button', { name: /Orders/i });
    fireEvent.click(tab);
    await waitFor(() => expect(api.getPhase3Orders).toHaveBeenCalled());
  });
});
