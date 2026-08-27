import { useState } from 'react';
import { getPhase0DbInfo, getPhase0Tables, testConnection } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import Icon from '../components/Icon';

export default function Phase0() {
  const [testing, setTesting] = useState(false);
  const [connResult, setConnResult] = useState<boolean | null>(null);

  const { data: dbInfo } = usePolling(() => getPhase0DbInfo(), 60_000, { immediate: true });
  const { data: tables } = usePolling(() => getPhase0Tables(), 60_000, { immediate: true });

  const onTest = async () => {
    setTesting(true);
    setConnResult(null);
    try {
      const r = await testConnection();
      setConnResult(r.success);
    } catch {
      setConnResult(false);
    } finally {
      setTesting(false);
    }
  };

  return (
    <>
      <h1 className="display-serif">System integrity</h1>
      <p className="page-sub">
        Read from <code>investment_platform.db</code> via a read-only connection. Nothing here can change your data.
      </p>

      <div className="row mb-4" style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        <div className="card" style={{ flex: '2 1 420px' }}>
          <div className="card-header"><h5><Icon name="database" /> Database Information</h5></div>
          <div className="card-body">
            <p><strong>Database Path:</strong> <code>{dbInfo?.path ?? '—'}</code></p>
            <p><strong>Exists:</strong> {dbInfo ? (dbInfo.exists ? 'true' : 'false') : '—'}</p>
            {dbInfo?.exists && <p><strong>Size:</strong> {dbInfo.sizeMb} MB</p>}
          </div>
        </div>
        <div className="card" style={{ flex: '1 1 280px' }}>
          <div className="card-header"><h5><Icon name="terminal" /> Connection Test</h5></div>
          <div className="card-body">
            <button className="btn btn-primary w-100" onClick={onTest} disabled={testing}>
              {testing ? <span className="spinner" /> : <Icon name="refresh-cw" />}
              {testing ? 'Testing' : 'Test Connection'}
            </button>
            {connResult != null && (
              <div className="mt-3">
                {connResult
                  ? <div className="alert alert-success">✅ Connection successful! SELECT 1 = 1</div>
                  : <div className="alert alert-danger">❌ Connection failed</div>}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="card mt-4">
        <div className="card-header"><h5><Icon name="book-open" /> Database Tables</h5></div>
        <div className="card-body">
          {tables && tables.length > 0 ? (
            <table className="table table-striped">
              <thead><tr><th>Table Name</th></tr></thead>
              <tbody>
                {tables.map((t) => (
                  <tr key={t}><td>{t}</td></tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="alert alert-warning">No tables found or connection failed</div>
          )}
        </div>
      </div>
    </>
  );
}
