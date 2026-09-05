import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import Phase2 from '../pages/Phase2';
import * as api from '../api/client';

// FULL mock of api/client — submitDecision is a vi.fn() that NEVER calls the
// real implementation (which would shell out to `python main.py ... decide`).
vi.mock('../api/client', () => ({
  getPhase2Windows: vi.fn(),
  getPhase2Review: vi.fn(),
  getPhase2Feedback: vi.fn(),
  submitDecision: vi.fn(),
}));

const WINDOW = {
  windowId: 1, status: 'ACTIVE', startAt: '2026-08-20T00:00:00Z', endAt: '2026-08-27T00:00:00Z',
  timezone: 'Asia/Jakarta', createdAt: '2026-08-20T00:00:00Z', closedAt: null, note: null,
};
const REVIEW = {
  observationWindowId: 1, humanDecision: 'PENDING', evidenceStatus: 'PARTIAL_EVIDENCE',
  decisionNote: null, knownLimitations: '[]', operatorFeedbackIds: '[]',
};

describe('Phase2 — Observation window & evidence', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.getPhase2Windows as ReturnType<typeof vi.fn>).mockResolvedValue([WINDOW]);
    (api.getPhase2Review as ReturnType<typeof vi.fn>).mockResolvedValue(REVIEW);
    (api.getPhase2Feedback as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    (api.submitDecision as ReturnType<typeof vi.fn>).mockResolvedValue({ success: true, output: 'decided' });
  });

  it('smoke: renders windows table + active window details', async () => {
    render(<Phase2 />);
    expect(await screen.findByText(/Observation window/)).toBeInTheDocument();
    expect(await screen.findByText('PARTIAL_EVIDENCE')).toBeInTheDocument();
  });

  it('loading: shows spinner while windows pending', () => {
    (api.getPhase2Windows as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}));
    render(<Phase2 />);
    expect(document.querySelector('.spinner')).toBeInTheDocument();
  });

  it('error: failed windows fetch shows nothing crashing', async () => {
    (api.getPhase2Windows as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('x'));
    render(<Phase2 />);
    // page header still renders (component does not throw)
    expect(await screen.findByText(/Observation window/)).toBeInTheDocument();
  });

  it('interaction: clicking a window row selects and shows details', async () => {
    render(<Phase2 />);
    const row = (await screen.findAllByText('ACTIVE'))[0];
    fireEvent.click(row);
    expect(await screen.findByText('Sustained-Use Review Evidence')).toBeInTheDocument();
  });

  it('modal: opens decision dialog with role=dialog + aria-modal', async () => {
    render(<Phase2 />);
    const row = (await screen.findAllByText('ACTIVE'))[0];
    fireEvent.click(row);
    const openBtn = await screen.findByRole('button', { name: /Set Human Decision/i });
    fireEvent.click(openBtn);
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toHaveAttribute('aria-labelledby', 'decisionModalTitle');
  });

  it('validation: submit without confirm checkbox shows error, no API call', async () => {
    render(<Phase2 />);
    const row = (await screen.findAllByText('ACTIVE'))[0];
    fireEvent.click(row);
    const openBtn = await screen.findByRole('button', { name: /Set Human Decision/i });
    fireEvent.click(openBtn);
    const submit = await screen.findByRole('button', { name: /Submit Decision/i });
    fireEvent.click(submit);
    expect(await screen.findByText(/Please confirm the submission/i)).toBeInTheDocument();
    expect(api.submitDecision).not.toHaveBeenCalled();
  });

  it('submit flow: valid submit calls mocked submitDecision with correct payload, shows success', async () => {
    // Explicit guard: the real submitDecision shells out to `python main.py ... decide`.
    // Prove the mock fully replaces it (no fallthrough to the real CLI/fetch).
    expect(vi.isMockFunction(api.submitDecision)).toBe(true);
    render(<Phase2 />);
    const row = (await screen.findAllByText('ACTIVE'))[0];
    fireEvent.click(row);
    const openBtn = await screen.findByRole('button', { name: /Set Human Decision/i });
    fireEvent.click(openBtn);
    // confirm checkbox
    const confirm = await screen.findByLabelText(/Saya yakin ingin mengirim/i);
    fireEvent.click(confirm);
    const submit = await screen.findByRole('button', { name: /Submit Decision/i });
    fireEvent.click(submit);
    await waitFor(() => expect(api.submitDecision).toHaveBeenCalledOnce());
    expect(api.submitDecision).toHaveBeenCalledWith(expect.objectContaining({
      decision: 'PENDING', windowId: 1, note: null, decidedBy: null,
    }));
    expect(await screen.findByText(/Success/i)).toBeInTheDocument();
  });

  it('submit flow: mocked reject shows error state, does NOT crash', async () => {
    (api.submitDecision as ReturnType<typeof vi.fn>).mockResolvedValue({ success: false, error: 'rejected', output: '' });
    render(<Phase2 />);
    const row = (await screen.findAllByText('ACTIVE'))[0];
    fireEvent.click(row);
    const openBtn = await screen.findByRole('button', { name: /Set Human Decision/i });
    fireEvent.click(openBtn);
    const confirm = await screen.findByLabelText(/Saya yakin ingin mengirim/i);
    fireEvent.click(confirm);
    const submit = await screen.findByRole('button', { name: /Submit Decision/i });
    fireEvent.click(submit);
    expect(await screen.findByText(/Error/i)).toBeInTheDocument();
  });

  it('a11y: Escape closes dialog (not while submitting), focus returns to opener', async () => {
    render(<Phase2 />);
    const row = (await screen.findAllByText('ACTIVE'))[0];
    fireEvent.click(row);
    const openBtn = await screen.findByRole('button', { name: /Set Human Decision/i });
    openBtn.focus();
    fireEvent.click(openBtn);
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape', code: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    // focus returns to opener
    expect(document.activeElement).toBe(openBtn);
  });

  it('a11y: focus trap — Tab on last cycles to first, Shift+Tab on first cycles to last', async () => {
    render(<Phase2 />);
    const row = (await screen.findAllByText('ACTIVE'))[0];
    fireEvent.click(row);
    const openBtn = await screen.findByRole('button', { name: /Set Human Decision/i });
    fireEvent.click(openBtn);
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toBeInTheDocument();
    // collect focusable nodes inside dialog
    const nodes = Array.from(dialog.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ));
    expect(nodes.length).toBeGreaterThan(1);
    const first = nodes[0] as HTMLElement;
    const last = nodes[nodes.length - 1] as HTMLElement;
    // Tab on last wraps to first
    last.focus();
    expect(document.activeElement).toBe(last);
    fireEvent.keyDown(document, { key: 'Tab', code: 'Tab' });
    expect(document.activeElement).toBe(first);
    // Shift+Tab on first wraps to last
    first.focus();
    expect(document.activeElement).toBe(first);
    fireEvent.keyDown(document, { key: 'Tab', code: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(last);
  });

  it('a11y: normal Tab inside dialog moves focus (no spurious trap)', async () => {
    render(<Phase2 />);
    const row = (await screen.findAllByText('ACTIVE'))[0];
    fireEvent.click(row);
    const openBtn = await screen.findByRole('button', { name: /Set Human Decision/i });
    fireEvent.click(openBtn);
    const dialog = await screen.findByRole('dialog');
    const select = dialog.querySelector('select') as HTMLElement;
    // jsdom focus: manually focus select, then Tab should NOT wrap if not on edge
    select.focus();
    expect(document.activeElement).toBe(select);
    fireEvent.keyDown(document, { key: 'Tab', code: 'Tab' });
    // handler only wraps at edges, so no preventDefault — jsdom keeps focus on select
    // (real browser would advance; we just assert trap did not misfire)
    expect(document.activeElement).toBe(select);
  });
});
