import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// Verify GateStrip honors prefers-reduced-motion WITHOUT throwing and still renders
// data. The app uses Framer Motion's useReducedMotion() (a hook, not callable here
// directly) — here we assert the visible behavior under a reduced-motion media query.
vi.mock('../api/client', () => ({ getPhase2Windows: vi.fn(), getPhase2Review: vi.fn() }));
import GateStrip from '../components/GateStrip';
import { getPhase2Windows, getPhase2Review } from '../api/client';

function setReducedMotion(on: boolean) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: on && query.includes('prefers-reduced-motion'),
      media: query,
      onchange: null,
      addListener: vi.fn(), removeListener: vi.fn(),
      addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
    }),
  });
}

describe('GateStrip — prefers-reduced-motion', () => {
  beforeEach(() => vi.clearAllMocks());

  it('still renders the data correctly when reduced motion is requested', async () => {
    setReducedMotion(true);
    (getPhase2Windows as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([
      { windowId: 7, status: 'ACTIVE', startAt: 'x', endAt: '2026-09-30T00:00:00', timezone: 'Asia/Jakarta', note: null, createdAt: 'x', closedAt: null },
    ]);
    (getPhase2Review as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      reviewId: 1, observationWindowId: 7, reviewedAt: 'x', evidenceStatus: 'COMPLETE_EVIDENCE',
      knownLimitations: '[]', operatorFeedbackIds: '[]', humanDecision: 'CONTINUE',
      decisionNote: null, decidedAt: null, decidedBy: null, createdAt: 'x', updatedAt: 'x',
    });

    render(<GateStrip />);
    await waitFor(() => expect(screen.getByText((_, el) =>
      !!(el && el.tagName === 'SPAN' && el.textContent && el.textContent.includes('WINDOW') && el.textContent.includes('7'))
    )).toBeInTheDocument());
    // With reduced motion the amber "Menunggu kamu" branch (PENDING) is NOT used here,
    // but the CONTINUE decision must still show without throwing.
    expect(screen.getAllByText((_, el) => !!(el?.textContent && el.textContent.includes('CONTINUE'))).length).toBeGreaterThan(0);
  });
});
