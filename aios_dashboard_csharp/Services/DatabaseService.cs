using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using aios_dashboard_csharp.Data;
using aios_dashboard_csharp.Models;

namespace aios_dashboard_csharp.Services;

public interface IDatabaseService
{
    Task<bool> TestConnectionAsync();
    Task<List<JournalEntry>> GetJournalEntriesAsync(string? symbol = null, string? decision = null, string? riskPolicyStatus = null, DateTime? fromDate = null);
    Task<List<DecisionBrief>> GetDecisionBriefsAsync();
    Task<List<ObservationWindow>> GetObservationWindowsAsync();
    Task<FinalReviewRecord?> GetFinalReviewRecordAsync(long windowId);
    Task<List<OperatorFeedback>> GetOperatorFeedbackAsync(long windowId);
    Task<List<Position>> GetPositionsAsync();
    Task<List<Order>> GetOrdersAsync();
    Task<List<Trade>> GetTradesAsync();
    Task<List<SchedulerJobRun>> GetSchedulerJobRunsAsync();
    Task<List<NotificationDedupState>> GetNotificationDedupStateAsync();
    Task<List<AuditEvent>> GetAuditEventsAsync(int limit = 50);
}

public class DatabaseService : IDatabaseService
{
    private readonly string _connectionString;
    private readonly string _dbPath = @"F:\My Son\data\investment_platform.db";

    public DatabaseService()
    {
        // Read-only connection string using URI format with mode=ro
        _connectionString = $"Data Source={_dbPath};Mode=ReadOnly";
    }

    private ReadOnlyDbContext CreateContext()
    {
        var options = new DbContextOptionsBuilder<ReadOnlyDbContext>()
            .UseSqlite(_connectionString)
            .Options;
        return new ReadOnlyDbContext(_connectionString);
    }

    public async Task<bool> TestConnectionAsync()
    {
        try
        {
            using var connection = new SqliteConnection(_connectionString);
            await connection.OpenAsync();
            using var command = connection.CreateCommand();
            command.CommandText = "SELECT 1";
            var result = await command.ExecuteScalarAsync();
            return result != null && (long)result == 1;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[db] TestConnectionAsync failed: {ex.Message}");
            return false;
        }
    }

    public async Task<List<JournalEntry>> GetJournalEntriesAsync(string? symbol = null, string? decision = null, string? riskPolicyStatus = null, DateTime? fromDate = null)
    {
        using var context = CreateContext();
        var query = from je in context.JournalEntries
                    join db in context.DecisionBriefs on je.BriefId equals db.BriefId into dbGroup
                    from db in dbGroup.DefaultIfEmpty()
                    select new JournalEntry
                    {
                        EntryId = je.EntryId,
                        BriefId = je.BriefId,
                        Symbol = je.Symbol,
                        Decision = je.Decision,
                        DecidedAt = je.DecidedAt,
                        RiskPolicyStatus = je.RiskPolicyStatus,
                        RiskPolicyReason = je.RiskPolicyReason,
                        PlannedR = je.PlannedR,
                        Note = je.Note,
                        BriefStatus = db != null ? db.Status : null,
                        EntryPrice = db != null ? db.EntryPrice : null,
                        StopLossPrice = db != null ? db.StopLossPrice : null,
                        TakeProfitPrice = db != null ? db.TakeProfitPrice : null,
                        RiskAmount = db != null ? db.RiskAmount : null,
                        PositionSize = db != null ? db.PositionSize : null,
                        RiskRewardRatio = db != null ? db.RiskRewardRatio : null,
                        SourceSnapshotId = db != null ? db.SourceSnapshotId : null,
                        BriefGeneratedAt = db != null ? db.GeneratedAt : null,
                        BriefReason = db != null ? db.Reason : null
                    };

        if (!string.IsNullOrEmpty(symbol))
            query = query.Where(j => j.Symbol == symbol);

        if (!string.IsNullOrEmpty(decision))
            query = query.Where(j => j.Decision == decision);

        if (!string.IsNullOrEmpty(riskPolicyStatus))
            query = query.Where(j => j.RiskPolicyStatus == riskPolicyStatus);

        if (fromDate.HasValue)
            query = query.Where(j => DateTime.Parse(j.DecidedAt) >= fromDate.Value);

        return await query
            .OrderByDescending(j => j.DecidedAt)
            .Take(100)
            .ToListAsync();
    }

    public async Task<List<DecisionBrief>> GetDecisionBriefsAsync()
    {
        using var context = CreateContext();
        return await context.DecisionBriefs.ToListAsync();
    }

    public async Task<List<ObservationWindow>> GetObservationWindowsAsync()
    {
        using var context = CreateContext();
        return await context.ObservationWindows
            .OrderByDescending(w => w.CreatedAt)
            .ToListAsync();
    }

    public async Task<FinalReviewRecord?> GetFinalReviewRecordAsync(long windowId)
    {
        using var context = CreateContext();
        return await context.FinalReviewRecords
            .FirstOrDefaultAsync(r => r.ObservationWindowId == windowId);
    }

    public async Task<List<OperatorFeedback>> GetOperatorFeedbackAsync(long windowId)
    {
        using var context = CreateContext();
        return await context.OperatorFeedback
            .Where(f => f.ObservationWindowId == windowId)
            .OrderByDescending(f => f.RecordedAt)
            .ToListAsync();
    }

    public async Task<List<Position>> GetPositionsAsync()
    {
        using var context = CreateContext();
        return await context.Positions
            .OrderByDescending(p => p.CreatedAt)
            .ToListAsync();
    }

    public async Task<List<Order>> GetOrdersAsync()
    {
        using var context = CreateContext();
        return await context.Orders
            .OrderByDescending(o => o.CreatedAt)
            .Take(100)
            .ToListAsync();
    }

    public async Task<List<Trade>> GetTradesAsync()
    {
        using var context = CreateContext();
        return await context.Trades
            .OrderByDescending(t => t.ExecutedAt)
            .Take(100)
            .ToListAsync();
    }

    public async Task<List<SchedulerJobRun>> GetSchedulerJobRunsAsync()
    {
        using var context = CreateContext();
        return await context.SchedulerJobRuns
            .OrderByDescending(j => j.TradingDate)
            .ThenBy(j => j.JobType)
            .ToListAsync();
    }

    public async Task<List<NotificationDedupState>> GetNotificationDedupStateAsync()
    {
        using var context = CreateContext();
        return await context.NotificationDedupState
            .OrderByDescending(n => n.UpdatedAt)
            .ToListAsync();
    }

    public async Task<List<AuditEvent>> GetAuditEventsAsync(int limit = 50)
    {
        using var context = CreateContext();
        return await context.AuditEvents
            .OrderByDescending(a => a.CreatedAt)
            .Take(limit)
            .ToListAsync();
    }
}