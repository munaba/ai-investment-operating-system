namespace aios_dashboard_csharp.Models;

public class SchedulerJobRun
{
    public string JobType { get; set; } = string.Empty;
    public string TradingDate { get; set; } = string.Empty;
    public string Status { get; set; } = string.Empty;
    public int Attempt { get; set; }
    public string StartedAt { get; set; } = string.Empty;
    public string? FinishedAt { get; set; }
    public string? NextRetryAt { get; set; }
    public string? Detail { get; set; }
}