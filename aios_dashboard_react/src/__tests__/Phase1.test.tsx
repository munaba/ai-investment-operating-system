import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import Phase1 from '../pages/Phase1';
import * as api from '../api/client';

vi.mock('../api/client', () => ({
  getPhase1Journal: vi.fn(),
  getPhase1Symbols: vi.fn(),
}));

const SAMPLE = [
  {
    entryId: 1, briefId: 10, symbol: 'BBCA', decision: 'TAKE', decidedAt: '2026-08-20T10:00:00Z',
    riskPolicyStatus: 'ACCEPTED', riskPolicyReason: 'ok', plannedR: 2.5, note: 'entry plan',
    briefStatus: 'GENERATED', briefGeneratedAt: '2026-08-20T09:00:00Z', sourceSnapshotId: 5,
    briefReason: 'r', entryPrice: 9000, stopLossPrice: 8700, takeProfitPrice: 9500,
    riskAmount: 300, positionSize: 100, riskRewardRatio: 2.5,
  },
];

describe('Phase1 — Journal & briefs', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.getPhase1Symbols as ReturnType<typeof vi.fn>).mockResolvedValue(['BBCA', 'TLKM']);
    (api.getPhase1Journal as ReturnType<typeof vi.fn>).mockResolvedValue(SAMPLE);
  });

  it('smoke: renders key headings + journal entries', async () => {
    render(<Phase1 />);
    expect(await screen.findByText('Journal & briefs')).toBeInTheDocument();
    expect(await screen.findByText(/Journal Entries/)).toBeInTheDocument();
    // BBCA appears in the symbol <select> option AND the table row
    expect((await screen.findAllByText('BBCA')).length).toBeGreaterThanOrEqual(1);
  });

  it('loading: shows spinner while journal is pending', () => {
    (api.getPhase1Journal as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}));
    render(<Phase1 />);
    expect(document.querySelector('.spinner')).toBeInTheDocument();
  });

  it('error: failed journal fetch shows fallback, no crash', async () => {
    (api.getPhase1Journal as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('db down'));
    render(<Phase1 />);
    expect(await screen.findByText(/No journal entries match the filters/)).toBeInTheDocument();
  });

  it('interaction: clicking a row reveals journal detail JSON', async () => {
    const { container } = render(<Phase1 />);
    await screen.findByText(/Journal Entries/);
    const row = container.querySelector('tbody tr')!;
    fireEvent.click(row);
    expect(await screen.findByText(/"entry_id": 1/)).toBeInTheDocument();
  });

  it('interaction: symbol filter + Refresh calls getPhase1Journal with param', async () => {
    render(<Phase1 />);
    await screen.findByText(/Journal Entries/);
    const select = screen.getAllByRole('combobox')[0] as HTMLSelectElement;
    fireEvent.change(select, { target: { value: 'TLKM' } });
    const refresh = screen.getByRole('button', { name: /Refresh/i });
    fireEvent.click(refresh);
    await waitFor(() => expect(api.getPhase1Journal).toHaveBeenCalledWith(
      expect.objectContaining({ symbol: 'TLKM' }),
    ));
  });
});
