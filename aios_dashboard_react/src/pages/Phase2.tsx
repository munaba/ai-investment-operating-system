import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import type { FinalReviewRecord, ObservationWindow, OperatorFeedback } from '../api/types';
import { getPhase2Feedback, getPhase2Review, getPhase2Windows, submitDecision } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import Icon from '../components/Icon';
import { PageReveal, EASE_OUT } from '../motion/Motion';
import { useReducedMotionSafe } from '../hooks/useReducedMotionSafe';
import { formatDateTime, parseJsonList, downloadCsv, downloadMarkdown } from '../lib/format';

function statusBadgeClass(status: string): string {
  switch (status) {
    case 'ACTIVE': return 'badge bg-success';
    case 'CLOSED': return 'badge bg-primary';
    default: return 'badge bg-secondary';
  }
}
function evidenceBadgeClass(status: string): string {
  switch (status) {
    case 'COMPLETE_EVIDENCE': return 'badge bg-success';
    case 'PARTIAL_EVIDENCE': return 'badge bg-warning';
    case 'INSUFFICIENT_DATA': return 'badge bg-warning';
    case 'NO_DATA': return 'badge bg-danger';
    case 'NOT_VERIFIABLE': return 'badge bg-secondary';
    default: return 'badge bg-secondary';
  }
}
function decisionBadgeClass(decision: string): string {
  switch (decision) {
    case 'PENDING': return 'badge bg-secondary';
    case 'CONTINUE': return 'badge bg-success';
    case 'SIMPLIFY': return 'badge bg-warning';
    case 'AUTHORIZE_FUTURE_INVESTIGATION': return 'badge bg-primary';
    default: return 'badge bg-secondary';
  }
}

const VALID_DECISIONS = ['PENDING', 'CONTINUE', 'SIMPLIFY', 'AUTHORIZE_FUTURE_INVESTIGATION'];

// Mirrors GateStrip.evidencePct — keeps the evidence-bar scale consistent across the app.
const evidencePct = (status: string | null | undefined): number => {
  switch (status) {
    case 'COMPLETE_EVIDENCE': return 100;
    case 'PARTIAL_EVIDENCE': return 60;
    case 'INSUFFICIENT_DATA': return 30;
    case 'NOT_VERIFIABLE': return 15;
    default: return 0;
  }
};

export default function Phase2() {
  const prefersReduced = useReducedMotionSafe();
  const windowsPoll = usePolling<ObservationWindow[]>(() => getPhase2Windows(), 30_000, { immediate: true });
  const windows = windowsPoll.data ?? [];
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [review, setReview] = useState<FinalReviewRecord | null>(null);
  const [feedback, setFeedback] = useState<OperatorFeedback[]>([]);
  const [closedId, setClosedId] = useState<number>(0);
  const [closedReview, setClosedReview] = useState<FinalReviewRecord | null>(null);

  // Auto-select ACTIVE window once data arrives (mirrors Blazor LoadDataAsync)
  const selected = selectedId != null ? windows.find((w) => w.windowId === selectedId) ?? null : windows.find((w) => w.status === 'ACTIVE') ?? null;

  const loadDetails = async (id: number) => {
    setReview(await getPhase2Review(id));
    setFeedback(await getPhase2Feedback(id));
  };

  // Reload details when selection changes (replaces setState-during-render anti-pattern)
  useEffect(() => {
    if (selected) {
      void loadDetails(selected.windowId);
    }
  }, [selected?.windowId]);

  // ---- Decision modal ----
  const [showForm, setShowForm] = useState(false);
  const [formDecision, setFormDecision] = useState('PENDING');
  const [formNote, setFormNote] = useState('');
  const [formBy, setFormBy] = useState('');
  const [formConfirmed, setFormConfirmed] = useState(false);
  const [formResult, setFormResult] = useState('');
  const [formSubmitting, setFormSubmitting] = useState(false);

  const openForm = (id: number) => {
    setSelectedId(id);
    setFormDecision('PENDING');
    setFormNote(''); setFormBy(''); setFormConfirmed(false); setFormResult('');
    setShowForm(true);
  };

  // ---- Modal a11y (effect 1): save opener, initial focus, restore on close ----
  // Depends ONLY on showForm so it never re-runs while formSubmitting toggles
  // (otherwise focus would jump back to the opener mid-submit).
  const modalRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<Element | null>(null);

  useEffect(() => {
    if (!showForm) return;
    // Save the element that opened the modal so we can restore focus on close.
    openerRef.current = document.activeElement;
    // Move focus into the modal (first interactive control: the Decision select).
    const firstField = modalRef.current?.querySelector<HTMLElement>(
      'select, textarea, input, button',
    );
    firstField?.focus();
    return () => {
      // Restore focus to the opener when the modal closes.
      (openerRef.current as HTMLElement | null)?.focus?.();
    };
  }, [showForm]);

  // ---- Modal a11y (effect 2): Escape-to-close, skips while submitting ----
  useEffect(() => {
    if (!showForm) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !formSubmitting) {
        e.preventDefault();
        setShowForm(false);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [showForm, formSubmitting]);

  const submit = async () => {
    if (!formConfirmed) { setFormResult('❌ Please confirm the submission by checking the checkbox.'); return; }
    if (selected == null) return;
    setFormSubmitting(true);
    setFormResult('');
    try {
      const r = await submitDecision({
        decision: formDecision,
        windowId: selected.windowId,
        note: formNote || null,
        decidedBy: formBy || null,
      });
      if (r.success) {
        setFormResult(`✅ Success:\n${r.output ?? ''}`);
        await loadDetails(selected.windowId);
      } else {
        setFormResult(`❌ Error:\n${r.error ?? ''}\n\nOutput:\n${r.output ?? ''}`);
      }
    } catch (e) {
      setFormResult(`❌ Exception: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setFormSubmitting(false);
    }
  };

  const onSelectClosed = async (id: number) => {
    setClosedId(id);
    setClosedReview(id > 0 ? await getPhase2Review(id) : null);
  };

  return (
    <PageReveal>
      <h1 className="display-serif page-title">Observation window &amp; evidence</h1>
      {windowsPoll.loading && !windowsPoll.data ? (
        <div className="text-center py-4"><span className="spinner" /> <p>Loading observation windows…</p></div>
      ) : (
        <div className="card mb-4">
          <div className="card-header d-flex justify-content-between align-items-center">
            <h5 className="mb-0"><Icon name="clock" /> Observation Windows</h5>
            <div>
              <button className="btn btn-sm btn-outline-primary me-2" onClick={() => downloadCsv(windows, `observation_windows_${new Date().toISOString().slice(0,10)}.csv`)}>
                <Icon name="arrow-down-right" /> CSV
              </button>
              <button className="btn btn-sm btn-outline-secondary" onClick={() => downloadMarkdown(
                [
                  { header: 'Window ID', render: (w: ObservationWindow) => String(w.windowId) },
                  { header: 'Start At', render: (w) => formatDateTime(w.startAt) },
                  { header: 'End At', render: (w) => formatDateTime(w.endAt) },
                  { header: 'Timezone', render: (w) => w.timezone },
                  { header: 'Status', render: (w) => w.status },
                  { header: 'Created At', render: (w) => formatDateTime(w.createdAt) },
                  { header: 'Closed At', render: (w) => formatDateTime(w.closedAt) },
                  { header: 'Note', render: (w) => (w.note ?? '') },
                ],
                windows,
                `observation_windows_${new Date().toISOString().slice(0,10)}.md`,
              )}>
                <Icon name="copy" /> Markdown
              </button>
            </div>
          </div>
          <div className="card-body p-0">
            {windows.length > 0 ? (
              <div className="table-responsive">
                <table className="table table-striped table-hover mb-0">
                  <thead>
                    <tr>
                      <th>Window ID</th><th>Start At</th><th>End At</th><th>Timezone</th>
                      <th>Status</th><th>Created At</th><th>Closed At</th><th>Note</th>
                    </tr>
                  </thead>
                  <motion.tbody initial="hidden" animate="show" variants={{ hidden: {}, show: { transition: { staggerChildren: prefersReduced ? 0 : 0.04 } } }}>
                    {windows.map((w) => (
                      <motion.tr key={w.windowId} style={{ cursor: 'pointer' }}
                          className={(selected?.windowId === w.windowId) ? 'table-primary' : ''}
                          onClick={() => setSelectedId(w.windowId)}
                          whileHover={{ backgroundColor: 'rgba(212,255,63,.04)' }}
                          transition={{ duration: 0.15 }}>
                        <td>{w.windowId}</td>
                        <td>{formatDateTime(w.startAt)}</td>
                        <td>{formatDateTime(w.endAt)}</td>
                        <td>{w.timezone}</td>
                        <td><AnimatePresence mode="wait"><motion.span key={w.status} className={`badge ${statusBadgeClass(w.status)}`}
                          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }}>
                          {w.status}
                        </motion.span></AnimatePresence></td>
                        <td>{formatDateTime(w.createdAt)}</td>
                        <td>{formatDateTime(w.closedAt)}</td>
                        <td>{w.note ?? ''}</td>
                      </motion.tr>
                    ))}
                  </motion.tbody>
                </table>
              </div>
            ) : (
              <div className="p-3 text-center text-muted">No observation windows recorded yet</div>
            )}
          </div>
        </div>
      )}

      {selected && (
        <div className="row g-4" style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          <div className="card" style={{ flex: '1 1 360px' }}>
            <div className="card-header d-flex justify-content-between align-items-center">
              <h5 className="mb-0"><Icon name="circle-dot" /> Active Window Details</h5>
              <span className={`badge ${statusBadgeClass(selected.status)}`}>{selected.status}</span>
            </div>
            <div className="card-body">
              <dl className="row">
                <dt className="col-sm-4">Window ID</dt><dd className="col-sm-8">{selected.windowId}</dd>
                <dt className="col-sm-4">Start</dt><dd className="col-sm-8">{formatDateTime(selected.startAt)}</dd>
                <dt className="col-sm-4">End</dt><dd className="col-sm-8">{formatDateTime(selected.endAt)}</dd>
                <dt className="col-sm-4">Timezone</dt><dd className="col-sm-8">{selected.timezone}</dd>
                <dt className="col-sm-4">Status</dt><dd className="col-sm-8"><span className={`badge ${statusBadgeClass(selected.status)}`}>{selected.status}</span></dd>
                <dt className="col-sm-4">Note</dt><dd className="col-sm-8">{selected.note ?? '—'}</dd>
              </dl>
            </div>
          </div>
          <div className="card" style={{ flex: '1 1 360px' }}>
            <div className="card-header"><h5 className="mb-0"><Icon name="shield-check" /> Sustained-Use Review Evidence</h5></div>
            <div className="card-body">
              {review ? (
                <>
                  <div className="mb-3"><strong>Overall Evidence Status:</strong> <AnimatePresence mode="wait"><motion.span key={review.evidenceStatus} className={`badge ${evidenceBadgeClass(review.evidenceStatus)} ms-2`}
                    initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }}>
                    {review.evidenceStatus}
                  </motion.span></AnimatePresence></div>
                  <div className="mb-3"><strong>Human Decision:</strong> <AnimatePresence mode="wait"><motion.span key={review.humanDecision} className={`badge ${decisionBadgeClass(review.humanDecision)} ms-2`}
                    initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }}>
                    {review.humanDecision}
                  </motion.span></AnimatePresence></div>
                  {review.decisionNote && <div className="mb-3"><strong>Decision Note:</strong><p className="mt-1">{review.decisionNote}</p></div>}
                  <div className="mb-3">
                    <strong>Evidence:</strong>
                    <span className="evidence-bar" style={{ display: 'inline-block', width: '140px', height: '6px', borderRadius: '3px', background: 'rgba(255,255,255,.1)', verticalAlign: 'middle', marginLeft: 8, overflow: 'hidden' }}>
                      <motion.span style={{ display: 'block', height: '100%', background: 'var(--lime)', borderRadius: '3px' }}
                        initial={prefersReduced ? false : { width: 0 }}
                        animate={{ width: `${evidencePct(review.evidenceStatus)}%` }}
                        transition={{ duration: prefersReduced ? 0 : 0.6, ease: 'easeOut' }} />
                    </span>
                  </div>
                  <div className="mb-3"><strong>Known Limitations:</strong>
                    <ul className="limit-list">{parseJsonList(review.knownLimitations).map((l, i) => <li key={i}>{l}</li>)}</ul>
                  </div>
                  <div className="mb-3"><strong>Operator Feedback IDs:</strong> <span className="mono" style={{ color: 'var(--gray)' }}>{parseJsonList(review.operatorFeedbackIds).join(', ') || 'none yet'}</span></div>
                  <div className="d-flex justify-content-end">
                    <motion.button type="button" className="btn btn-outline-primary" onClick={() => openForm(selected.windowId)} whileTap={{ scale: 0.97 }}>
                      <Icon name="lock" color="amber" /> Set Human Decision
                    </motion.button>
                  </div>
                </>
              ) : (
                <div className="alert alert-warning">Sustained-use review not generated yet for this window.</div>
              )}
            </div>
          </div>
        </div>
      )}

      {selected && review && (
        <div className="card mt-4">
          <div className="card-header"><h5 className="mb-0"><Icon name="file-text" /> Operator Feedback</h5></div>
          <div className="card-body">
            {feedback.length > 0 ? (
              <>
                <div className="table-responsive mb-3">
                  <table className="table table-striped table-hover">
                    <thead>
                      <tr>
                        <th>Feedback ID</th><th>Recorded At</th><th>Rating</th><th>Alert Usefulness</th>
                        <th>Data Reliability</th><th>Decision Quality</th><th>Workflow Usability</th>
                        <th>Free Text</th><th>Concerns</th><th>Operator Label</th>
                      </tr>
                    </thead>
                    <tbody>
                      {feedback.map((fb) => (
                        <tr key={fb.feedbackId}>
                          <td>{fb.feedbackId}</td>
                          <td>{formatDateTime(fb.recordedAt)}</td>
                          <td>{fb.operatorRating?.toString() ?? '—'}</td>
                          <td>{fb.alertUsefulness ?? '—'}</td>
                          <td>{fb.dataReliabilityFeedback ?? '—'}</td>
                          <td>{fb.decisionQualityFeedback ?? '—'}</td>
                          <td>{fb.workflowUsabilityFeedback ?? '—'}</td>
                          <td>{fb.freeText ?? '—'}</td>
                          <td>{fb.concerns}</td>
                          <td>{fb.operatorLabel ?? '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div>
                  <button className="btn btn-sm btn-outline-primary me-2" onClick={() => downloadCsv(feedback, `operator_feedback_window_${selected.windowId}_${new Date().toISOString().slice(0,10)}.csv`)}>
                    <Icon name="arrow-down-right" /> CSV
                  </button>
                  <button className="btn btn-sm btn-outline-secondary" onClick={() => downloadMarkdown(
                    [
                      { header: 'Feedback ID', render: (f: OperatorFeedback) => String(f.feedbackId) },
                      { header: 'Recorded At', render: (f) => formatDateTime(f.recordedAt) },
                      { header: 'Rating', render: (f) => f.operatorRating?.toString() ?? '—' },
                      { header: 'Alert Usefulness', render: (f) => f.alertUsefulness ?? '—' },
                      { header: 'Data Reliability', render: (f) => f.dataReliabilityFeedback ?? '—' },
                      { header: 'Decision Quality', render: (f) => f.decisionQualityFeedback ?? '—' },
                      { header: 'Workflow Usability', render: (f) => f.workflowUsabilityFeedback ?? '—' },
                      { header: 'Free Text', render: (f) => f.freeText ?? '—' },
                      { header: 'Concerns', render: (f) => f.concerns },
                      { header: 'Operator Label', render: (f) => f.operatorLabel ?? '—' },
                    ],
                    feedback,
                    `operator_feedback_window_${selected.windowId}_${new Date().toISOString().slice(0,10)}.md`,
                  )}>
                    <Icon name="copy" /> Markdown
                  </button>
                </div>
              </>
            ) : (
              <div className="text-muted">No operator feedback recorded for this window</div>
            )}
          </div>
        </div>
      )}

      {windows.some((w) => w.status !== 'ACTIVE') && (
        <div className="card mt-4">
          <div className="card-header"><h5 className="mb-0"><Icon name="lock" /> Closed Window Reviews</h5></div>
          <div className="card-body">
            <div className="row mb-3" style={{ display: 'flex', gap: 12, alignItems: 'flex-end' }}>
              <div style={{ flex: '1 1 280px' }}>
                <label className="form-label">Select Closed Window</label>
                <select className="form-select" value={closedId} onChange={(e) => onSelectClosed(Number(e.target.value))}>
                  <option value={0}>-- Select --</option>
                  {windows.filter((w) => w.status !== 'ACTIVE').map((w) => (
                    <option key={w.windowId} value={w.windowId}>Window #{w.windowId} ({formatDateTime(w.startAt)} → {formatDateTime(w.endAt)})</option>
                  ))}
                </select>
              </div>
            </div>
            {closedReview && (
              <div className="card">
                <div className="card-body">
                  <div className="row" style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                    <div className="col" style={{ flex: '1 1 240px' }}>
                      <strong>Evidence Status:</strong> <AnimatePresence mode="wait"><motion.span key={closedReview.evidenceStatus} className={`badge ${evidenceBadgeClass(closedReview.evidenceStatus)} ms-2`}
                        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }}>
                        {closedReview.evidenceStatus}
                      </motion.span></AnimatePresence>
                    </div>
                    <div className="col" style={{ flex: '1 1 240px' }}>
                      <strong>Human Decision:</strong> <AnimatePresence mode="wait"><motion.span key={closedReview.humanDecision} className={`badge ${decisionBadgeClass(closedReview.humanDecision)} ms-2`}
                        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }}>
                        {closedReview.humanDecision}
                      </motion.span></AnimatePresence>
                    </div>
                  </div>
                  <hr />
                  <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
                    <code>{JSON.stringify(closedReview, null, 2)}</code>
                  </pre>
                  <hr />
                  <div className="d-flex justify-content-end">
                    <motion.button type="button" className="btn btn-outline-primary" onClick={() => openForm(closedReview.observationWindowId)} whileTap={{ scale: 0.97 }}>
                      <Icon name="lock" color="amber" /> Set Human Decision
                    </motion.button>
                  </div>
                </div>
              </div>
            )}
            {closedId > 0 && !closedReview && <div className="text-muted">No review record for this window</div>}
          </div>
        </div>
      )}

      {showForm && selected && (
        <AnimatePresence>
          <motion.div
            className="modal-overlay"
            onClick={() => setShowForm(false)}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
          >
            <motion.div
              className="modal"
              ref={modalRef}
              role="dialog"
              aria-modal="true"
              aria-labelledby="decisionModalTitle"
              onClick={(e) => e.stopPropagation()}
              initial={{ opacity: 0, scale: 0.96, y: 8 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.97, y: 8 }}
              transition={{ duration: 0.22, ease: EASE_OUT }}
            >
            <div className="modal-header">
              <h5 className="display-serif" id="decisionModalTitle">Set Human Decision — Window #{selected.windowId}</h5>
              <button className="btn btn-sm" onClick={() => setShowForm(false)}>✕</button>
            </div>
            <div className="modal-body">
              <div className="alert alert-warning">
                <strong>Konfirmasi Wajib:</strong> Form ini akan menjalankan command CLI <code>python main.py sustained-use-final decide</code> dari <code>F:\My Son</code>.
                Proses ini <strong>tidak</strong> menulis langsung ke database dari C# — C# hanya memanggil proses eksternal yang sama persis dengan manual ketik CLI.
              </div>
              <div className="mb-3">
                <label className="form-label">Decision *</label>
                <select className="form-select" value={formDecision} onChange={(e) => setFormDecision(e.target.value)}>
                  {VALID_DECISIONS.map((d) => <option key={d} value={d}>{d}</option>)}
                </select>
              </div>
              <div className="mb-3">
                <label className="form-label">Note (opsional)</label>
                <textarea className="form-control" rows={3} value={formNote} onChange={(e) => setFormNote(e.target.value)} placeholder="Catatan keputusan..." />
              </div>
              <div className="mb-3">
                <label className="form-label">Decided By (opsional)</label>
                <input className="form-control" value={formBy} onChange={(e) => setFormBy(e.target.value)} placeholder="Nama operator..." />
              </div>
              <div className="mb-3 form-check">
                <input className="form-check-input" type="checkbox" id="confirmDecision" checked={formConfirmed} onChange={(e) => setFormConfirmed(e.target.checked)} />
                <label className="form-check-label" htmlFor="confirmDecision">
                  Saya yakin ingin mengirim keputusan ini via CLI <code>python main.py sustained-use-final decide</code>
                </label>
              </div>
              <div className="d-flex gap-2">
                <button className="btn btn-primary" onClick={submit} disabled={formSubmitting}>
                  {formSubmitting ? <span className="spinner" /> : <Icon name="check" />}
                  {formSubmitting ? 'Submitting...' : 'Submit Decision'}
                </button>
                <button className="btn btn-outline-secondary" onClick={() => setShowForm(false)} disabled={formSubmitting}>Batal</button>
              </div>
              {formResult && (
                <div className="mt-3 p-3 rounded" style={{ background: formResult.startsWith('✅') ? 'rgba(212,255,63,.06)' : 'rgba(255,92,92,.06)', border: `1px solid ${formResult.startsWith('✅') ? 'var(--lime)' : 'var(--red)'}` }}>
                  <pre className="mb-0" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{formResult}</pre>
                </div>
              )}
            </div>
          </motion.div>
        </motion.div>
        </AnimatePresence>
      )}
    </PageReveal>
  );
}
