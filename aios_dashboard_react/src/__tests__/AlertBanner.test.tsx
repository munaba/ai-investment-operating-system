import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import AlertBanner from '../components/AlertBanner';

vi.mock('../api/client', () => ({ getAlerts: vi.fn() }));
import { getAlerts } from '../api/client';

describe('AlertBanner', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders nothing when there are no alerts', async () => {
    (getAlerts as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    const { container } = render(<AlertBanner />);
    await waitFor(() => expect(container.querySelectorAll('.alert-banner-container')).toHaveLength(0));
  });

  it('renders an alert with title + message for a pending-decision condition', async () => {
    (getAlerts as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([
      {
        type: 'PendingDecisionNearDeadline',
        message: 'Window #1 mendekati batas waktu (3 hari lagi), keputusan masih PENDING',
        severity: 'Warning',
        relatedId: 1,
      },
    ]);
    render(<AlertBanner />);
    await waitFor(() => expect(screen.getByText('Keputusan Mendekati Batas Waktu')).toBeInTheDocument());
    expect(screen.getByText(/keputusan masih PENDING/)).toBeInTheDocument();
  });

  it('renders an error-class alert for EXTERNAL_BLOCKED evidence', async () => {
    (getAlerts as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([
      { type: 'ExternalBlockedEvidence', message: 'Window #2: Evidence status = EXTERNAL_BLOCKED', severity: 'Error', relatedId: 2 },
    ]);
    const { container } = render(<AlertBanner />);
    await waitFor(() => expect(screen.getByText('Evidence Terblokir Eksternal')).toBeInTheDocument());
    expect(container.querySelector('.alert-danger')).toBeInTheDocument();
  });
});
