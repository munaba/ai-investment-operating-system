using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using aios_dashboard_csharp.Models;

namespace aios_dashboard_csharp.Data;

public class ReadOnlyDbContext : DbContext
{
    private readonly string _connectionString;

    public ReadOnlyDbContext(string connectionString)
    {
        _connectionString = connectionString;
    }

    public DbSet<JournalEntry> JournalEntries { get; set; } = null!;
    public DbSet<DecisionBrief> DecisionBriefs { get; set; } = null!;
    public DbSet<ObservationWindow> ObservationWindows { get; set; } = null!;
    public DbSet<FinalReviewRecord> FinalReviewRecords { get; set; } = null!;
    public DbSet<OperatorFeedback> OperatorFeedback { get; set; } = null!;
    public DbSet<Position> Positions { get; set; } = null!;
    public DbSet<Order> Orders { get; set; } = null!;
    public DbSet<Trade> Trades { get; set; } = null!;
    public DbSet<SchedulerJobRun> SchedulerJobRuns { get; set; } = null!;
    public DbSet<NotificationDedupState> NotificationDedupState { get; set; } = null!;
    public DbSet<AuditEvent> AuditEvents { get; set; } = null!;

    protected override void OnConfiguring(DbContextOptionsBuilder optionsBuilder)
    {
        optionsBuilder.UseSqlite(_connectionString);
    }

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);

        // Configure JournalEntry
        modelBuilder.Entity<JournalEntry>(entity =>
        {
            entity.ToTable("journal_entries");
            entity.HasKey(e => e.EntryId);
            entity.Property(e => e.EntryId).HasColumnName("entry_id");
            entity.Property(e => e.BriefId).HasColumnName("brief_id");
            entity.Property(e => e.Symbol).HasColumnName("symbol");
            entity.Property(e => e.Decision).HasColumnName("decision");
            entity.Property(e => e.DecidedAt).HasColumnName("decided_at");
            entity.Property(e => e.RiskPolicyStatus).HasColumnName("risk_policy_status");
            entity.Property(e => e.RiskPolicyReason).HasColumnName("risk_policy_reason");
            entity.Property(e => e.PlannedR).HasColumnName("planned_r");
            entity.Property(e => e.Note).HasColumnName("note");
        });

        // Configure DecisionBrief
        modelBuilder.Entity<DecisionBrief>(entity =>
        {
            entity.ToTable("decision_briefs");
            entity.HasKey(e => e.BriefId);
            entity.Property(e => e.BriefId).HasColumnName("brief_id");
            entity.Property(e => e.Symbol).HasColumnName("symbol");
            entity.Property(e => e.GeneratedAt).HasColumnName("generated_at");
            entity.Property(e => e.Status).HasColumnName("status");
            entity.Property(e => e.SourceSnapshotId).HasColumnName("source_snapshot_id");
            entity.Property(e => e.Reason).HasColumnName("reason");
            entity.Property(e => e.EntryPrice).HasColumnName("entry_price");
            entity.Property(e => e.StopLossPrice).HasColumnName("stop_loss_price");
            entity.Property(e => e.TakeProfitPrice).HasColumnName("take_profit_price");
            entity.Property(e => e.RiskAmount).HasColumnName("risk_amount");
            entity.Property(e => e.PositionSize).HasColumnName("position_size");
            entity.Property(e => e.RiskRewardRatio).HasColumnName("risk_reward_ratio");
        });

        // Configure ObservationWindow
        modelBuilder.Entity<ObservationWindow>(entity =>
        {
            entity.ToTable("operator_observation_windows");
            entity.HasKey(e => e.WindowId);
            entity.Property(e => e.WindowId).HasColumnName("window_id");
            entity.Property(e => e.StartAt).HasColumnName("start_at");
            entity.Property(e => e.EndAt).HasColumnName("end_at");
            entity.Property(e => e.Timezone).HasColumnName("timezone");
            entity.Property(e => e.Note).HasColumnName("note");
            entity.Property(e => e.Status).HasColumnName("status");
            entity.Property(e => e.CreatedAt).HasColumnName("created_at");
            entity.Property(e => e.ClosedAt).HasColumnName("closed_at");
        });

        // Configure FinalReviewRecord
        modelBuilder.Entity<FinalReviewRecord>(entity =>
        {
            entity.ToTable("final_review_records");
            entity.HasKey(e => e.ReviewId);
            entity.Property(e => e.ReviewId).HasColumnName("review_id");
            entity.Property(e => e.ObservationWindowId).HasColumnName("observation_window_id");
            entity.Property(e => e.ReviewedAt).HasColumnName("reviewed_at");
            entity.Property(e => e.EvidenceStatus).HasColumnName("evidence_status");
            entity.Property(e => e.KnownLimitations).HasColumnName("known_limitations");
            entity.Property(e => e.OperatorFeedbackIds).HasColumnName("operator_feedback_ids");
            entity.Property(e => e.HumanDecision).HasColumnName("human_decision");
            entity.Property(e => e.DecisionNote).HasColumnName("decision_note");
            entity.Property(e => e.DecidedAt).HasColumnName("decided_at");
            entity.Property(e => e.DecidedBy).HasColumnName("decided_by");
            entity.Property(e => e.CreatedAt).HasColumnName("created_at");
            entity.Property(e => e.UpdatedAt).HasColumnName("updated_at");
        });

        // Configure OperatorFeedback
        modelBuilder.Entity<OperatorFeedback>(entity =>
        {
            entity.ToTable("operator_feedback");
            entity.HasKey(e => e.FeedbackId);
            entity.Property(e => e.FeedbackId).HasColumnName("feedback_id");
            entity.Property(e => e.ObservationWindowId).HasColumnName("observation_window_id");
            entity.Property(e => e.RecordedAt).HasColumnName("recorded_at");
            entity.Property(e => e.OperatorRating).HasColumnName("operator_rating");
            entity.Property(e => e.AlertUsefulness).HasColumnName("alert_usefulness");
            entity.Property(e => e.DataReliabilityFeedback).HasColumnName("data_reliability_feedback");
            entity.Property(e => e.DecisionQualityFeedback).HasColumnName("decision_quality_feedback");
            entity.Property(e => e.WorkflowUsabilityFeedback).HasColumnName("workflow_usability_feedback");
            entity.Property(e => e.FreeText).HasColumnName("free_text");
            entity.Property(e => e.Concerns).HasColumnName("concerns");
            entity.Property(e => e.OperatorLabel).HasColumnName("operator_label");
        });

        // Configure Position
        modelBuilder.Entity<Position>(entity =>
        {
            entity.ToTable("positions");
            entity.HasKey(e => e.PositionId);
            entity.Property(e => e.PositionId).HasColumnName("position_id");
            entity.Property(e => e.AccountId).HasColumnName("account_id");
            entity.Property(e => e.Symbol).HasColumnName("symbol");
            entity.Property(e => e.Quantity).HasColumnName("quantity");
            entity.Property(e => e.AveragePrice).HasColumnName("average_price");
            entity.Property(e => e.RealizedPnl).HasColumnName("realized_pnl");
            entity.Property(e => e.Status).HasColumnName("status");
            entity.Property(e => e.Direction).HasColumnName("direction");
            entity.Property(e => e.StopLoss).HasColumnName("stop_loss");
            entity.Property(e => e.TakeProfit).HasColumnName("take_profit");
            entity.Property(e => e.BuyFeeAccumulated).HasColumnName("buy_fee_accumulated");
            entity.Property(e => e.CreatedAt).HasColumnName("created_at");
            entity.Property(e => e.UpdatedAt).HasColumnName("updated_at");
        });

        // Configure Order
        modelBuilder.Entity<Order>(entity =>
        {
            entity.ToTable("orders");
            entity.HasKey(e => e.OrderId);
            entity.Property(e => e.OrderId).HasColumnName("order_id");
            entity.Property(e => e.AccountId).HasColumnName("account_id");
            entity.Property(e => e.Symbol).HasColumnName("symbol");
            entity.Property(e => e.Action).HasColumnName("action");
            entity.Property(e => e.Quantity).HasColumnName("quantity");
            entity.Property(e => e.RequestedPrice).HasColumnName("requested_price");
            entity.Property(e => e.FilledPrice).HasColumnName("filled_price");
            entity.Property(e => e.FilledQuantity).HasColumnName("filled_quantity");
            entity.Property(e => e.Status).HasColumnName("status");
            entity.Property(e => e.Reason).HasColumnName("reason");
            entity.Property(e => e.CreatedAt).HasColumnName("created_at");
            entity.Property(e => e.UpdatedAt).HasColumnName("updated_at");
            entity.Property(e => e.FilledAt).HasColumnName("filled_at");
            entity.Property(e => e.AnalysisSnapshotId).HasColumnName("analysis_snapshot_id");
        });

        // Configure Trade
        modelBuilder.Entity<Trade>(entity =>
        {
            entity.ToTable("trades");
            entity.HasKey(e => e.TradeId);
            entity.Property(e => e.TradeId).HasColumnName("trade_id");
            entity.Property(e => e.OrderId).HasColumnName("order_id");
            entity.Property(e => e.AccountId).HasColumnName("account_id");
            entity.Property(e => e.Symbol).HasColumnName("symbol");
            entity.Property(e => e.Action).HasColumnName("action");
            entity.Property(e => e.Quantity).HasColumnName("quantity");
            entity.Property(e => e.FillPrice).HasColumnName("fill_price");
            entity.Property(e => e.Fee).HasColumnName("fee");
            entity.Property(e => e.Tax).HasColumnName("tax");
            entity.Property(e => e.ExecutedAt).HasColumnName("executed_at");
        });

        // Configure SchedulerJobRun
        modelBuilder.Entity<SchedulerJobRun>(entity =>
        {
            entity.ToTable("scheduler_job_runs");
            entity.HasKey(e => new { e.JobType, e.TradingDate });
            entity.Property(e => e.JobType).HasColumnName("job_type");
            entity.Property(e => e.TradingDate).HasColumnName("trading_date");
            entity.Property(e => e.Status).HasColumnName("status");
            entity.Property(e => e.Attempt).HasColumnName("attempt");
            entity.Property(e => e.StartedAt).HasColumnName("started_at");
            entity.Property(e => e.FinishedAt).HasColumnName("finished_at");
            entity.Property(e => e.NextRetryAt).HasColumnName("next_retry_at");
            entity.Property(e => e.Detail).HasColumnName("detail");
        });

        // Configure NotificationDedupState
        modelBuilder.Entity<NotificationDedupState>(entity =>
        {
            entity.ToTable("notification_dedup_state");
            entity.HasKey(e => e.AlertType);
            entity.Property(e => e.AlertType).HasColumnName("alert_type");
            entity.Property(e => e.LastSignature).HasColumnName("last_signature");
            entity.Property(e => e.LastSentAt).HasColumnName("last_sent_at");
            entity.Property(e => e.LastStatus).HasColumnName("last_status");
            entity.Property(e => e.UpdatedAt).HasColumnName("updated_at");
        });

        // Configure AuditEvent
        modelBuilder.Entity<AuditEvent>(entity =>
        {
            entity.ToTable("audit_events");
            entity.HasKey(e => e.Id);
            entity.Property(e => e.Id).HasColumnName("id");
            entity.Property(e => e.EventType).HasColumnName("event_type");
            entity.Property(e => e.Payload).HasColumnName("payload");
            entity.Property(e => e.CreatedAt).HasColumnName("created_at");
        });
    }

    // Prevent any writes - override SaveChanges to throw
    public override int SaveChanges()
    {
        throw new InvalidOperationException("This is a read-only context. Write operations are not permitted.");
    }

    public override Task<int> SaveChangesAsync(CancellationToken cancellationToken = default)
    {
        throw new InvalidOperationException("This is a read-only context. Write operations are not permitted.");
    }
}