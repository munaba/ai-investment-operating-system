using aios_dashboard_csharp.Models;
using aios_dashboard_csharp.Services;
using Xunit;

namespace aios_dashboard_csharp.Tests;

/// <summary>
/// Tests for AlertService. Exercises the three alert branches (pending-decision
/// near deadline, external-blocked evidence, scheduler job failed) using a fake
/// IDatabaseService + controllable ITimeProvider. No static TestMode flag used
/// (it is a production backdoor — see docs/verification portability/TestMode finding).
/// </summary>
public class AlertServiceTests
{
    // ---- PendingDecisionNearDeadline ----

    [Fact]
    public async Task WindowNearDeadline_WithPendingDecision_ReturnsPendingAlert()
    {
        var now = new DateTime(2026, 8, 27, 0, 0, 0);
        var windows = new List<ObservationWindow>
        {
            new() { WindowId = 10, Status = "ACTIVE", EndAt = now.AddDays(3).ToString("o") }
        };
        var reviews = new Dictionary<long, FinalReviewRecord?>
        {
            [10] = new FinalReviewRecord { ObservationWindowId = 10, HumanDecision = "PENDING" }
        };
        var db = new FakeDatabaseService(windows, reviews);
        var time = new FixedTimeProvider(now);
        var svc = new AlertService(db, time);

        var alerts = await svc.GetActiveAlertsAsync();

        var pending = alerts.Single(a => a.Type == AlertType.PendingDecisionNearDeadline);
        Assert.Equal(AlertSeverity.Warning, pending.Severity);
        Assert.Equal(10, pending.RelatedId);
        Assert.Contains("3", pending.Message); // 3 hari lagi
    }

    [Fact]
    public async Task WindowPastDeadline_WithPendingDecision_NoPendingAlert()
    {
        var now = new DateTime(2026, 8, 27, 0, 0, 0);
        var windows = new List<ObservationWindow>
        {
            new() { WindowId = 11, Status = "ACTIVE", EndAt = now.AddDays(-2).ToString("o") }
        };
        var reviews = new Dictionary<long, FinalReviewRecord?>
        {
            [11] = new FinalReviewRecord { ObservationWindowId = 11, HumanDecision = "PENDING" }
        };
        var db = new FakeDatabaseService(windows, reviews);
        var svc = new AlertService(db, new FixedTimeProvider(now));

        var alerts = await svc.GetActiveAlertsAsync();

        Assert.DoesNotContain(alerts, a => a.Type == AlertType.PendingDecisionNearDeadline);
    }

    [Fact]
    public async Task WindowNearDeadline_ButDecisionNotPending_NoPendingAlert()
    {
        var now = new DateTime(2026, 8, 27, 0, 0, 0);
        var windows = new List<ObservationWindow>
        {
            new() { WindowId = 12, Status = "ACTIVE", EndAt = now.AddDays(1).ToString("o") }
        };
        var reviews = new Dictionary<long, FinalReviewRecord?>
        {
            [12] = new FinalReviewRecord { ObservationWindowId = 12, HumanDecision = "CONTINUE" }
        };
        var db = new FakeDatabaseService(windows, reviews);
        var svc = new AlertService(db, new FixedTimeProvider(now));

        var alerts = await svc.GetActiveAlertsAsync();

        Assert.DoesNotContain(alerts, a => a.Type == AlertType.PendingDecisionNearDeadline);
    }

    [Fact]
    public async Task WindowFarFromDeadline_NoPendingAlert()
    {
        var now = new DateTime(2026, 8, 27, 0, 0, 0);
        var windows = new List<ObservationWindow>
        {
            new() { WindowId = 13, Status = "ACTIVE", EndAt = now.AddDays(30).ToString("o") }
        };
        var reviews = new Dictionary<long, FinalReviewRecord?>
        {
            [13] = new FinalReviewRecord { ObservationWindowId = 13, HumanDecision = "PENDING" }
        };
        var db = new FakeDatabaseService(windows, reviews);
        var svc = new AlertService(db, new FixedTimeProvider(now));

        var alerts = await svc.GetActiveAlertsAsync();

        Assert.DoesNotContain(alerts, a => a.Type == AlertType.PendingDecisionNearDeadline);
    }

    [Fact]
    public async Task WindowNotActive_NoPendingAlert()
    {
        var now = new DateTime(2026, 8, 27, 0, 0, 0);
        var windows = new List<ObservationWindow>
        {
            new() { WindowId = 14, Status = "CLOSED", EndAt = now.AddDays(2).ToString("o") }
        };
        var reviews = new Dictionary<long, FinalReviewRecord?>
        {
            [14] = new FinalReviewRecord { ObservationWindowId = 14, HumanDecision = "PENDING" }
        };
        var db = new FakeDatabaseService(windows, reviews);
        var svc = new AlertService(db, new FixedTimeProvider(now));

        var alerts = await svc.GetActiveAlertsAsync();

        Assert.DoesNotContain(alerts, a => a.Type == AlertType.PendingDecisionNearDeadline);
    }

    // ---- ExternalBlockedEvidence ----

    [Fact]
    public async Task WindowWithExternalBlockedEvidence_ReturnsBlockedAlert()
    {
        var windows = new List<ObservationWindow>
        {
            new() { WindowId = 20, Status = "ACTIVE", EndAt = DateTime.MaxValue.ToString("o") }
        };
        var reviews = new Dictionary<long, FinalReviewRecord?>
        {
            [20] = new FinalReviewRecord { ObservationWindowId = 20, EvidenceStatus = "EXTERNAL_BLOCKED" }
        };
        var db = new FakeDatabaseService(windows, reviews);
        var svc = new AlertService(db, new FixedTimeProvider(new DateTime(2026, 8, 27)));

        var alerts = await svc.GetActiveAlertsAsync();

        var blocked = alerts.Single(a => a.Type == AlertType.ExternalBlockedEvidence);
        Assert.Equal(AlertSeverity.Error, blocked.Severity);
        Assert.Equal(20, blocked.RelatedId);
    }

    [Fact]
    public async Task WindowWithNormalEvidence_NoBlockedAlert()
    {
        var windows = new List<ObservationWindow>
        {
            new() { WindowId = 21, Status = "ACTIVE", EndAt = DateTime.MaxValue.ToString("o") }
        };
        var reviews = new Dictionary<long, FinalReviewRecord?>
        {
            [21] = new FinalReviewRecord { ObservationWindowId = 21, EvidenceStatus = "OK" }
        };
        var db = new FakeDatabaseService(windows, reviews);
        var svc = new AlertService(db, new FixedTimeProvider(new DateTime(2026, 8, 27)));

        var alerts = await svc.GetActiveAlertsAsync();

        Assert.DoesNotContain(alerts, a => a.Type == AlertType.ExternalBlockedEvidence);
    }

    // ---- SchedulerJobFailed ----

    [Fact]
    public async Task LatestJobFailed_ReturnsSchedulerAlert_ErrorSeverity()
    {
        var jobRuns = new List<SchedulerJobRun>
        {
            new() { JobType = "daily-ingest", TradingDate = "2026-08-27", Status = "FAILED", StartedAt = "2026-08-27T09:00:00" }
        };
        var db = new FakeDatabaseService(new List<ObservationWindow>(), new Dictionary<long, FinalReviewRecord?>(), jobRuns);
        var svc = new AlertService(db, new FixedTimeProvider(new DateTime(2026, 8, 27)));

        var alerts = await svc.GetActiveAlertsAsync();

        var job = alerts.Single(a => a.Type == AlertType.SchedulerJobFailed);
        Assert.Equal(AlertSeverity.Error, job.Severity);
        Assert.Equal(0, job.RelatedId);
        Assert.Contains("daily-ingest", job.Message);
    }

    [Fact]
    public async Task LatestJobRunning_ReturnsSchedulerAlert_WarningSeverity()
    {
        var jobRuns = new List<SchedulerJobRun>
        {
            new() { JobType = "nightly", TradingDate = "2026-08-27", Status = "RUNNING", StartedAt = "2026-08-27T23:00:00" }
        };
        var db = new FakeDatabaseService(new List<ObservationWindow>(), new Dictionary<long, FinalReviewRecord?>(), jobRuns);
        var svc = new AlertService(db, new FixedTimeProvider(new DateTime(2026, 8, 27)));

        var alerts = await svc.GetActiveAlertsAsync();

        var job = alerts.Single(a => a.Type == AlertType.SchedulerJobFailed);
        Assert.Equal(AlertSeverity.Warning, job.Severity);
    }

    [Fact]
    public async Task LatestJobSuccess_NoSchedulerAlert()
    {
        var jobRuns = new List<SchedulerJobRun>
        {
            new() { JobType = "daily-ingest", TradingDate = "2026-08-27", Status = "SUCCESS", StartedAt = "2026-08-27T09:00:00" }
        };
        var db = new FakeDatabaseService(new List<ObservationWindow>(), new Dictionary<long, FinalReviewRecord?>(), jobRuns);
        var svc = new AlertService(db, new FixedTimeProvider(new DateTime(2026, 8, 27)));

        var alerts = await svc.GetActiveAlertsAsync();

        Assert.DoesNotContain(alerts, a => a.Type == AlertType.SchedulerJobFailed);
    }

    [Fact]
    public async Task NoJobRuns_NoSchedulerAlert()
    {
        var db = new FakeDatabaseService(new List<ObservationWindow>(), new Dictionary<long, FinalReviewRecord?>(), new List<SchedulerJobRun>());
        var svc = new AlertService(db, new FixedTimeProvider(new DateTime(2026, 8, 27)));

        var alerts = await svc.GetActiveAlertsAsync();

        Assert.DoesNotContain(alerts, a => a.Type == AlertType.SchedulerJobFailed);
    }

    // ---- Combination ----

    [Fact]
    public async Task AllThreeConditions_AllAlertsReturned()
    {
        var now = new DateTime(2026, 8, 27, 0, 0, 0);
        var windows = new List<ObservationWindow>
        {
            new() { WindowId = 30, Status = "ACTIVE", EndAt = now.AddDays(2).ToString("o") }
        };
        var reviews = new Dictionary<long, FinalReviewRecord?>
        {
            [30] = new FinalReviewRecord { ObservationWindowId = 30, HumanDecision = "PENDING", EvidenceStatus = "EXTERNAL_BLOCKED" }
        };
        var jobRuns = new List<SchedulerJobRun>
        {
            new() { JobType = "x", TradingDate = "2026-08-27", Status = "FAILED", StartedAt = "2026-08-27T09:00:00" }
        };
        var db = new FakeDatabaseService(windows, reviews, jobRuns);
        var svc = new AlertService(db, new FixedTimeProvider(now));

        var alerts = await svc.GetActiveAlertsAsync();

        Assert.Contains(alerts, a => a.Type == AlertType.PendingDecisionNearDeadline);
        Assert.Contains(alerts, a => a.Type == AlertType.ExternalBlockedEvidence);
        Assert.Contains(alerts, a => a.Type == AlertType.SchedulerJobFailed);
        Assert.Equal(3, alerts.Count);
    }

    [Fact]
    public async Task NoConditions_EmptyAlertList()
    {
        var windows = new List<ObservationWindow>
        {
            new() { WindowId = 40, Status = "ACTIVE", EndAt = DateTime.MaxValue.ToString("o") }
        };
        var reviews = new Dictionary<long, FinalReviewRecord?>
        {
            [40] = new FinalReviewRecord { ObservationWindowId = 40, HumanDecision = "CONTINUE", EvidenceStatus = "OK" }
        };
        var jobRuns = new List<SchedulerJobRun>
        {
            new() { JobType = "x", TradingDate = "2026-08-27", Status = "SUCCESS", StartedAt = "2026-08-27T09:00:00" }
        };
        var db = new FakeDatabaseService(windows, reviews, jobRuns);
        var svc = new AlertService(db, new FixedTimeProvider(new DateTime(2026, 8, 27)));

        var alerts = await svc.GetActiveAlertsAsync();

        Assert.Empty(alerts);
    }
}

/// <summary>
/// In-memory fake of IDatabaseService — returns controlled data per scenario.
/// Only the three methods AlertService uses are meaningfully driven.
/// </summary>
file sealed class FakeDatabaseService : IDatabaseService
{
    private readonly List<ObservationWindow> _windows;
    private readonly Dictionary<long, FinalReviewRecord?> _reviews;
    private readonly List<SchedulerJobRun> _jobRuns;

    public FakeDatabaseService(
        List<ObservationWindow> windows,
        Dictionary<long, FinalReviewRecord?> reviews,
        List<SchedulerJobRun>? jobRuns = null)
    {
        _windows = windows;
        _reviews = reviews;
        _jobRuns = jobRuns ?? new List<SchedulerJobRun>();
    }

    public Task<List<ObservationWindow>> GetObservationWindowsAsync() => Task.FromResult(_windows);
    public Task<FinalReviewRecord?> GetFinalReviewRecordAsync(long windowId) =>
        Task.FromResult(_reviews.GetValueOrDefault(windowId));
    public Task<List<SchedulerJobRun>> GetSchedulerJobRunsAsync() => Task.FromResult(_jobRuns);

    // Unused by AlertService — throw to catch accidental coupling.
    public string DbPath => throw new NotImplementedException();
    public Task<bool> TestConnectionAsync() => throw new NotImplementedException();
    public Task<List<JournalEntry>> GetJournalEntriesAsync(string? s = null, string? d = null, string? r = null, DateTime? f = null) => throw new NotImplementedException();
    public Task<List<DecisionBrief>> GetDecisionBriefsAsync() => throw new NotImplementedException();
    public Task<List<OperatorFeedback>> GetOperatorFeedbackAsync(long w) => throw new NotImplementedException();
    public Task<List<Position>> GetPositionsAsync() => throw new NotImplementedException();
    public Task<List<Order>> GetOrdersAsync() => throw new NotImplementedException();
    public Task<List<Trade>> GetTradesAsync() => throw new NotImplementedException();
    public Task<List<NotificationDedupState>> GetNotificationDedupStateAsync() => throw new NotImplementedException();
    public Task<List<AuditEvent>> GetAuditEventsAsync(int limit = 50) => throw new NotImplementedException();
}

/// <summary>
/// Controllable clock for AlertService time-based thresholds.
/// </summary>
file sealed class FixedTimeProvider : ITimeProvider
{
    public FixedTimeProvider(DateTime now) => Now = now;
    public DateTime Now { get; }
}
