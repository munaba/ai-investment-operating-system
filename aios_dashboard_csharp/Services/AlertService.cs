using aios_dashboard_csharp.Models;

namespace aios_dashboard_csharp.Services;

/// <summary>
/// Additive test seam (no behavior change): isolates DateTime.Now so alert
/// logic with time-based thresholds is unit-testable without faking the system clock.
/// </summary>
public interface ITimeProvider
{
    DateTime Now { get; }
}

public sealed class RealTimeProvider : ITimeProvider
{
    public DateTime Now => DateTime.Now;
}

public interface IAlertService
{
    Task<List<AlertBannerItem>> GetActiveAlertsAsync();
}

public class AlertService : IAlertService
{
    private readonly IDatabaseService _databaseService;
    private readonly ITimeProvider _timeProvider;
    private readonly int _pendingDecisionWarningDays = 7; // ASUMPSI: 7 hari, bisa diubah via config nanti

    // Default ctor preserves existing DI registration (AddSingleton<IAlertService, AlertService> with single arg).
    public AlertService(IDatabaseService databaseService, ITimeProvider? timeProvider = null)
    {
        _databaseService = databaseService;
        _timeProvider = timeProvider ?? new RealTimeProvider();
    }

    public async Task<List<AlertBannerItem>> GetActiveAlertsAsync()
    {
        var alerts = new List<AlertBannerItem>();
        var now = _timeProvider.Now;

        try
        {
            // 1. human_decision masih PENDING DAN window end_at tinggal <= 7 hari
            var windows = await _databaseService.GetObservationWindowsAsync();
            foreach (var window in windows)
            {
                if (window.Status == "ACTIVE" && DateTime.TryParse(window.EndAt, out var endAt))
                {
                    var daysUntilEnd = (endAt - now).TotalDays;
                    if (daysUntilEnd <= _pendingDecisionWarningDays && daysUntilEnd >= 0)
                    {
                        var review = await _databaseService.GetFinalReviewRecordAsync(window.WindowId);
                        if (review != null && review.HumanDecision == "PENDING")
                        {
                            alerts.Add(new AlertBannerItem
                            {
                                Type = AlertType.PendingDecisionNearDeadline,
                                Message = $"Window #{window.WindowId} mendekati batas waktu ({daysUntilEnd:F0} hari lagi), keputusan masih PENDING",
                                Severity = AlertSeverity.Warning,
                                RelatedId = window.WindowId
                            });
                        }
                    }
                }
            }

            // 2. Ada evidence_status = EXTERNAL_BLOCKED di final_review_records
            foreach (var window in windows)
            {
                var review = await _databaseService.GetFinalReviewRecordAsync(window.WindowId);
                if (review != null && review.EvidenceStatus == "EXTERNAL_BLOCKED")
                {
                    alerts.Add(new AlertBannerItem
                    {
                        Type = AlertType.ExternalBlockedEvidence,
                        Message = $"Window #{window.WindowId}: Evidence status = EXTERNAL_BLOCKED",
                        Severity = AlertSeverity.Error,
                        RelatedId = window.WindowId
                    });
                }
            }

            // 3. scheduler_job_runs - job terakhir (terbaru) bukan SUCCESS
            var jobRuns = await _databaseService.GetSchedulerJobRunsAsync();
            if (jobRuns.Count > 0)
            {
                var latestJob = jobRuns.OrderByDescending(j => j.StartedAt).First();
                if (latestJob.Status != "SUCCESS")
                {
                    alerts.Add(new AlertBannerItem
                    {
                        Type = AlertType.SchedulerJobFailed,
                        Message = $"Scheduler job '{latestJob.JobType}' ({latestJob.TradingDate}) status: {latestJob.Status}",
                        Severity = latestJob.Status == "FAILED" ? AlertSeverity.Error : AlertSeverity.Warning,
                        RelatedId = 0
                    });
                }
            }
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[alerts] GetActiveAlertsAsync failed: {ex}");
        }

        return alerts;
    }
}

public class AlertBannerItem
{
    public AlertType Type { get; set; }
    public string Message { get; set; } = "";
    public AlertSeverity Severity { get; set; }
    public long RelatedId { get; set; }
}

public enum AlertType
{
    PendingDecisionNearDeadline,
    ExternalBlockedEvidence,
    SchedulerJobFailed
}

public enum AlertSeverity
{
    Info,
    Warning,
    Error
}