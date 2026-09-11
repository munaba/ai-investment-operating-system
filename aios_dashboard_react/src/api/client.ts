import type {
  AlertBannerItem,
  AuditEvent,
  DecisionBrief,
  DecisionSubmitRequest,
  FinalReviewRecord,
  JournalEntry,
  NotificationDedupState,
  ObservationWindow,
  OperatorFeedback,
  Order,
  Phase0DbInfo,
  Position,
  SchedulerJobRun,
  Trade,
} from './types';

// M-09: Session is httpOnly cookie (server source of truth).
// localStorage is NOT used for auth — only /api/health indicates auth state.

// Cross-origin in dev is solved by the Vite proxy (see vite.config.ts): every
// /api, /login, /logout request hits the ASP.NET host through the same origin,
// so the auth cookie is first-party and sent with credentials: 'include'.
const BASE = '';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    credentials: 'include',
    headers: { Accept: 'application/json', ...(init?.headers ?? {}) },
    ...init,
  });

  if (res.status === 401) {
    // Auth lost (cookie expired / not logged in) — server cookie is source of truth.
    throw new ApiError(401, 'unauthorized');
  }
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new ApiError(res.status, text || res.statusText);
  }
  // 204 / empty body
  const contentType = res.headers.get('content-type') ?? '';
  // Non-JSON (or empty) body means "no payload" — e.g. 204 No Content.
  // Previously `undefined as T` asserted "undefined is a T", which is unsound
  // whenever T isn't nullable. We keep the same runtime contract (the caller's
  // declared T is still what it gets back) but move the single unavoidable
  // assertion to the function's return type instead of lying per-branch.
  if (!contentType.includes('application/json')) {
    return undefined as unknown as T;
  }
  return (await res.json()) as T;
}

// Verify session with server (GET /api/health) — source of truth.
// httpOnly cookie is NOT accessible to JS; /api/health response indicates auth state.
export async function hasSession(): Promise<boolean> {
  try {
    const res = await fetch(BASE + '/api/health', { credentials: 'include' });
    return res.ok;
  } catch {
    return false;
  }
}

// ---- Auth ----
export async function login(username: string, password: string): Promise<void> {
  const res = await fetch(BASE + '/api/auth/login', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    throw new ApiError(res.status, 'invalid credentials');
  }
  // M-09: no localStorage write — server sets httpOnly cookie via Set-Cookie header.
}

export async function logout(): Promise<void> {
  await fetch(BASE + '/logout', { method: 'POST', credentials: 'include' }).catch(() => {});
  // M-09: no localStorage clear — server clears cookie via SignOutAsync.
}

// ---- Phase 0 ----
export const getPhase0DbInfo = () => request<Phase0DbInfo>('/api/phase0/db-info');
export const getPhase0Tables = () => request<string[]>('/api/phase0/tables');
export const testConnection = () =>
  request<{ success: boolean }>('/api/phase0/test-connection', { method: 'POST' });

// ---- Phase 1 ----
export const getPhase1Journal = (params: {
  symbol?: string;
  decision?: string;
  riskPolicy?: string;
  fromDate?: string;
} = {}) => {
  const q = new URLSearchParams();
  if (params.symbol) q.set('symbol', params.symbol);
  if (params.decision) q.set('decision', params.decision);
  if (params.riskPolicy) q.set('riskPolicy', params.riskPolicy);
  if (params.fromDate) q.set('fromDate', params.fromDate);
  const qs = q.toString();
  return request<JournalEntry[]>(`/api/phase1/journal${qs ? `?${qs}` : ''}`);
};
export const getPhase1Symbols = () => request<string[]>('/api/phase1/symbols');

// ---- Phase 2 ----
export const getPhase2Windows = () =>
  request<ObservationWindow[]>('/api/phase2/windows');
export const getPhase2Review = (windowId: number) =>
  request<FinalReviewRecord>(`/api/phase2/review/${windowId}`);
export const getPhase2Feedback = (windowId: number) =>
  request<OperatorFeedback[]>(`/api/phase2/feedback/${windowId}`);

// ---- Phase 3 ----
export const getPhase3Positions = () => request<Position[]>('/api/phase3/positions');
export const getPhase3Orders = () => request<Order[]>('/api/phase3/orders');
export const getPhase3Trades = () => request<Trade[]>('/api/phase3/trades');
export const getPhase3Scheduler = () => request<SchedulerJobRun[]>('/api/phase3/scheduler');
export const getPhase3Dedup = () =>
  request<NotificationDedupState[]>('/api/phase3/dedup');
export const getPhase3Audit = (limit = 50) =>
  request<AuditEvent[]>(`/api/phase3/audit?limit=${limit}`);

// ---- Alerts ----
export const getAlerts = () => request<AlertBannerItem[]>('/api/alerts');

// ---- Human decision (POST; mutates via external CLI only) ----
export const submitDecision = (req: DecisionSubmitRequest) =>
  request<{ success: boolean; output?: string; error?: string }>('/api/decision/submit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
