import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import GateStrip from '../components/GateStrip';

// Mock the API client module — provide REAL-shaped data so we test GateStrip's
// rendering logic, not the network. (testing-anti-patterns: mock the boundary,
// assert on real component behavior.)
vi.mock('../api/client', () => ({
  getPhase2Windows: vi.fn(),
  getPhase2Review: vi.fn(),
}));

import { getPhase2Windows, getPhase2Review } from '../api/client';

const activeWindow = {
  windowId: 12, status: 'ACTIVE', startAt: '2026-08-24T00:00:00', endAt: '2026-09-23T23:59:59',
  timezone: 'Asia/Jakarta', note: null, createdAt: '2026-08-23', closedAt: null,
};
const review = {
  reviewId: 1, observationWindowId: 12, reviewedAt: 'x', evidenceStatus: 'PARTIAL_EVIDENCE',
  knownLimitations: '[]', operatorFeedbackIds: '[]', humanDecision: 'PENDING',
  decisionNote: null, decidedAt: null, decidedBy: null, createdAt: 'x', updatedAt: 'x',
};

describe('GateStrip', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // jsdom doesn't implement matchMedia → Framer's useReducedMotion reads it.
    // Provide a default (motion allowed) so the component mounts cleanly.
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: (query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }),
    });
  });

  it('shows the pending (amber) decision state for a PENDING review', async () => {
    (getPhase2Windows as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([activeWindow]);
    (getPhase2Review as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(review);

    render(<GateStrip />);

    // async load → use waitFor (anti-flaky: never assert timing-dependent state synchronously)
    await waitFor(() => expect(screen.getByText((_, el) =>
      !!(el && el.tagName === 'SPAN' && el.textContent && el.textContent.includes('WINDOW') && el.textContent.includes('12'))
    )).toBeInTheDocument());
    // The signature element: "Menunggu kamu" only appears for PENDING decisions
    expect(screen.getAllByText((_, el) =>
      !!(el?.textContent && el.textContent.includes('Menunggu kamu'))
    ).length).toBeGreaterThan(0);
    // evidence status surfaced (text may be split across the evidence bar)
    expect(screen.getAllByText((_, el) =>
      !!(el?.textContent && el.textContent.includes('PARTIAL_EVIDENCE'))
    ).length).toBeGreaterThan(0);
  });

  it('shows empty state when no active window exists', async () => {
    (getPhase2Windows as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    (getPhase2Review as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(null);

    render(<GateStrip />);

    await waitFor(() => expect(screen.getByText(/no active observation window/i)).toBeInTheDocument());
  });

  it('does not crash on API failure (best-effort contract)', async () => {
    (getPhase2Windows as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('boom'));
    (getPhase2Review as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(null);

    render(<GateStrip />);
    // strip must still render something (empty/loading) and never throw
    await waitFor(() => expect(document.querySelector('.gate-strip')).toBeInTheDocument());
  });
});
