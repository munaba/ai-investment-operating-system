namespace aios_dashboard_csharp.Models;

public class JournalEntry
{
    public long EntryId { get; set; }
    public long BriefId { get; set; }
    public string Symbol { get; set; } = string.Empty;
    public string Decision { get; set; } = string.Empty;
    public string DecidedAt { get; set; } = string.Empty;
    public string RiskPolicyStatus { get; set; } = string.Empty;
    public string? RiskPolicyReason { get; set; }
    public double? PlannedR { get; set; }
    public string? Note { get; set; }
    public string? BriefStatus { get; set; }
    public double? EntryPrice { get; set; }
    public double? StopLossPrice { get; set; }
    public double? TakeProfitPrice { get; set; }
    public double? RiskAmount { get; set; }
    public double? PositionSize { get; set; }
    public double? RiskRewardRatio { get; set; }
    public long? SourceSnapshotId { get; set; }
    public string? BriefGeneratedAt { get; set; }
    public string? BriefReason { get; set; }
}