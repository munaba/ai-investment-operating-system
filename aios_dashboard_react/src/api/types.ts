// TypeScript mirrors of the C# models in aios_dashboard_csharp/Models/*.cs.
// ASP.NET Core serializes to camelCase by default, so property names are camelCase here.

export interface JournalEntry {
  entryId: number;
  briefId: number;
  symbol: string;
  decision: string;
  decidedAt: string;
  riskPolicyStatus: string;
  riskPolicyReason?: string | null;
  plannedR?: number | null;
  note?: string | null;
  briefStatus?: string | null;
  entryPrice?: number | null;
  stopLossPrice?: number | null;
  takeProfitPrice?: number | null;
  riskAmount?: number | null;
  positionSize?: number | null;
  riskRewardRatio?: number | null;
  sourceSnapshotId?: number | null;
  briefGeneratedAt?: string | null;
  briefReason?: string | null;
}

export interface DecisionBrief {
  briefId: number;
  symbol: string;
  generatedAt: string;
  status: string;
  sourceSnapshotId?: number | null;
  reason?: string | null;
  entryPrice?: number | null;
  stopLossPrice?: number | null;
  takeProfitPrice?: number | null;
  riskAmount?: number | null;
  positionSize?: number | null;
  riskRewardRatio?: number | null;
}

export interface ObservationWindow {
  windowId: number;
  startAt: string;
  endAt: string;
  timezone: string;
  note?: string | null;
  status: string;
  createdAt: string;
  closedAt?: string | null;
}

export interface FinalReviewRecord {
  reviewId: number;
  observationWindowId: number;
  reviewedAt: string;
  evidenceStatus: string;
  // Stored in DB as a JSON array string; parse on the client when needed.
  knownLimitations: string;
  operatorFeedbackIds: string;
  humanDecision: string;
  decisionNote?: string | null;
  decidedAt?: string | null;
  decidedBy?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface OperatorFeedback {
  feedbackId: number;
  observationWindowId: number;
  recordedAt: string;
  operatorRating?: number | null;
  alertUsefulness?: string | null;
  dataReliabilityFeedback?: string | null;
  decisionQualityFeedback?: string | null;
  workflowUsabilityFeedback?: string | null;
  freeText?: string | null;
  concerns: string;
  operatorLabel?: string | null;
}

export interface Position {
  positionId: number;
  accountId: string;
  symbol: string;
  quantity: number;
  averagePrice: number;
  realizedPnl: number;
  status: string;
  direction: string;
  stopLoss?: number | null;
  takeProfit?: number | null;
  buyFeeAccumulated: number;
  createdAt: string;
  updatedAt: string;
}

export interface Order {
  orderId: number;
  accountId: string;
  symbol: string;
  action: string;
  quantity: number;
  requestedPrice: number;
  filledPrice: number;
  filledQuantity: number;
  status: string;
  reason: string;
  createdAt: string;
  updatedAt: string;
  filledAt?: string | null;
  analysisSnapshotId?: number | null;
}

export interface Trade {
  tradeId: number;
  orderId: number;
  accountId: string;
  symbol: string;
  action: string;
  quantity: number;
  fillPrice: number;
  fee: number;
  tax: number;
  executedAt: string;
}

export interface SchedulerJobRun {
  jobType: string;
  tradingDate: string;
  status: string;
  attempt: number;
  startedAt: string;
  finishedAt?: string | null;
  nextRetryAt?: string | null;
  detail?: string | null;
}

export interface NotificationDedupState {
  alertType: string;
  lastSignature?: string | null;
  lastSentAt?: string | null;
  lastStatus: string;
  updatedAt: string;
}

export interface AuditEvent {
  id?: number | null;
  eventType: string;
  payload?: string | null;
  createdAt: string;
}

export type AlertType =
  | 'PendingDecisionNearDeadline'
  | 'ExternalBlockedEvidence'
  | 'SchedulerJobFailed';

export type AlertSeverity = 'Info' | 'Warning' | 'Error';

export interface AlertBannerItem {
  type: AlertType;
  message: string;
  severity: AlertSeverity;
  relatedId: number;
}

export interface DecisionSubmitRequest {
  decision: string;
  windowId: number;
  note?: string | null;
  decidedBy?: string | null;
}

export interface Phase0DbInfo {
  path: string;
  exists: boolean;
  sizeMb: number;
}
