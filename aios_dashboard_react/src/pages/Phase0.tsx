import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { getPhase0DbInfo, getPhase0Tables, testConnection } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import Icon from '../components/Icon';
import { PageReveal, fadeUp } from '../motion/Motion';
import { useReducedMotionSafe } from '../hooks/useReducedMotionSafe';

export default function Phase0() {
  const prefersReduced = useReducedMotionSafe();
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
    <PageReveal>
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
            <motion.button className="btn btn-primary w-100" onClick={onTest} disabled={testing} whileTap={{ scale: 0.97 }}>
              {testing ? <span className="spinner" /> : <Icon name="refresh-cw" />}
              {testing ? 'Testing' : 'Test Connection'}
            </motion.button>
            {connResult != null && (
              <AnimatePresence mode="wait">
                <motion.div key={connResult ? 'ok' : 'fail'} className="mt-3"
                  initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                  transition={{ duration: 0.18 }}>
                  {connResult
                    ? <div className="alert alert-success">✅ Connection successful! SELECT 1 = 1</div>
                    : <div className="alert alert-danger">❌ Connection failed</div>}
                </motion.div>
              </AnimatePresence>
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
              <motion.tbody initial="hidden" animate="show" variants={{ hidden: {}, show: { transition: { staggerChildren: prefersReduced ? 0 : 0.04 } } }}>
                {tables.map((t) => (
                  <motion.tr key={t} variants={fadeUp} whileHover={{ backgroundColor: 'rgba(212,255,63,.04)' }} transition={{ duration: 0.15 }}>
                    <td>{t}</td>
                  </motion.tr>
                ))}
              </motion.tbody>
            </table>
          ) : (
            <div className="alert alert-warning">
              <span className="d-flex align-items-center gap-2">
                <Icon name="database" size="sm" color="dim" />
                Gagal memuat daftar tabel — periksa koneksi database
              </span>
            </div>
          )}
        </div>
      </div>
    </PageReveal>
  );
}
