import { usePolling } from '../hooks/usePolling';
import { getAlerts } from '../api/client';
import type { AlertBannerItem, AlertSeverity, AlertType } from '../api/types';
import Icon from './Icon';

function alertClass(severity: AlertSeverity): string {
  switch (severity) {
    case 'Error': return 'alert alert-danger';
    case 'Warning': return 'alert alert-warning';
    case 'Info': return 'alert alert-info';
    default: return 'alert alert-secondary';
  }
}

function alertIcon(type: AlertType): string {
  switch (type) {
    case 'PendingDecisionNearDeadline': return 'clock';
    case 'ExternalBlockedEvidence': return 'shield-check';
    case 'SchedulerJobFailed': return 'settings';
    default: return 'circle-dot';
  }
}

function alertTitle(type: AlertType): string {
  switch (type) {
    case 'PendingDecisionNearDeadline': return 'Keputusan Mendekati Batas Waktu';
    case 'ExternalBlockedEvidence': return 'Evidence Terblokir Eksternal';
    case 'SchedulerJobFailed': return 'Scheduler Job Gagal';
    default: return 'Peringatan';
  }
}

// Top-level alert banner. Mounted EXACTLY ONCE (in MainLayout) — never twice,
// or two independent 60s timers double the query load (Blazor skill pitfall).
export default function AlertBanner() {
  const { data: alerts, loading } = usePolling<AlertBannerItem[]>(
    () => getAlerts(),
    60_000,
  );

  if (loading && (!alerts || alerts.length === 0)) return null;
  if (!alerts || alerts.length === 0) return null;

  return (
    <div className="alert-banner-container" style={{ padding: '0 24px' }}>
      {alerts.map((alert) => (
        <div key={`${alert.type}-${alert.relatedId}`} className={`${alertClass(alert.severity)} m-3`} role="alert">
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
            <span style={{ marginTop: 2 }}>
              <Icon
                name={alertIcon(alert.type)}
                color={alert.severity === 'Error' ? 'lime' : ''}
              />
            </span>
            <div style={{ flex: 1 }}>
              <strong>{alertTitle(alert.type)}</strong>
              <div className="small">{alert.message}</div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
