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

// NOTE: `status` is lowercase here on purpose. The backend returns DB values
// verbatim and `positions.status` really is 'closed' — these fixtures used to
// say 'CLOSED', which is exactly why the lowercase/uppercase bug went
// uncaught. Keep them matching production.
const POS = [{
  positionId: 1, accountId: 'ACC', symbol: 'BBCA', quantity: 100, averagePrice: 9000,
  realizedPnl: 120000, status: 'closed', direction: 'LONG', stopLoss: 8700, takeProfit: 9500,
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
    const chart = await screen.findByRole('img', { name: /Equity curve/i }, { timeout: 2000 });
    expect(chart).toBeInTheDocument();
  });

  // Brief 5 §1 — the chart is div-based (EquityChartBklit), so the old
  // `tagName === 'svg'` assertion no longer describes it. The chart carries
  // its value on the accessible name, which lets the assertion test the DATA
  // rather than the tag — strictly stronger than what it replaced.
  it('equity chart exposes the final P&L value on its accessible name', async () => {
    render(<Phase3 />);
    const tab = await screen.findByRole('button', { name: /Equity\/P&L/i });
    fireEvent.click(tab);
    // POS is a single CLOSED position with realizedPnl 120000 -> cumulative +120.000
    const chart = await screen.findByLabelText('Equity curve, +120.000 IDR', undefined, { timeout: 2000 });
    expect(chart).toHaveAttribute('role', 'img');
  });

  it('equity chart: negative P&L renders a signed negative value', async () => {
    (api.getPhase3Positions as ReturnType<typeof vi.fn>).mockResolvedValue([{
      ...POS[0], realizedPnl: -450000,
    }]);
    render(<Phase3 />);
    const tab = await screen.findByRole('button', { name: /Equity\/P&L/i });
    fireEvent.click(tab);
    const chart = await screen.findByLabelText('Equity curve, -450.000 IDR', undefined, { timeout: 2000 });
    expect(chart).toBeInTheDocument();
  });

  // Regression: the backend returns `positions.status` lowercase ('closed'),
  // but the UI compared against 'CLOSED'. Both casings must produce a chart,
  // otherwise the equity tab silently shows the empty state.
  it('equity chart: lowercase status (as the API returns it) still renders', async () => {
    (api.getPhase3Positions as ReturnType<typeof vi.fn>).mockResolvedValue([{
      ...POS[0], status: 'closed', realizedPnl: 120000,
    }]);
    render(<Phase3 />);
    const tab = await screen.findByRole('button', { name: /Equity\/P&L/i });
    fireEvent.click(tab);
    const chart = await screen.findByLabelText('Equity curve, +120.000 IDR', undefined, { timeout: 2000 });
    expect(chart).toBeInTheDocument();
  });

  it('equity chart: UPPERCASE status also renders (casing must not matter)', async () => {
    (api.getPhase3Positions as ReturnType<typeof vi.fn>).mockResolvedValue([{
      ...POS[0], status: 'CLOSED', realizedPnl: 120000,
    }]);
    render(<Phase3 />);
    const tab = await screen.findByRole('button', { name: /Equity\/P&L/i });
    fireEvent.click(tab);
    const chart = await screen.findByLabelText('Equity curve, +120.000 IDR', undefined, { timeout: 2000 });
    expect(chart).toBeInTheDocument();
  });

  it('equity chart: no closed positions shows empty state, not a chart', async () => {
    (api.getPhase3Positions as ReturnType<typeof vi.fn>).mockResolvedValue([{
      ...POS[0], status: 'open', realizedPnl: 0,
    }]);
    (api.getPhase3Trades as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    render(<Phase3 />);
    const tab = await screen.findByRole('button', { name: /Equity\/P&L/i });
    fireEvent.click(tab);
    expect(await screen.findByText(/Belum ada data trade/)).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: /Equity curve/i })).not.toBeInTheDocument();
  });

  it('interaction: switching to Orders tab calls getPhase3Orders', async () => {
    render(<Phase3 />);
    const tab = await screen.findByRole('button', { name: /Orders/i });
    fireEvent.click(tab);
    await waitFor(() => expect(api.getPhase3Orders).toHaveBeenCalled());
  });
});
