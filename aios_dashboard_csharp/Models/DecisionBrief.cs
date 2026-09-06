namespace aios_dashboard_csharp.Models;

public class DecisionBrief
{
    public long BriefId { get; set; }
    public string Symbol { get; set; } = string.Empty;
    public string GeneratedAt { get; set; } = string.Empty;
    public string Status { get; set; } = string.Empty;
    public long? SourceSnapshotId { get; set; }
    public string? Reason { get; set; }
    public double? EntryPrice { get; set; }
    public double? StopLossPrice { get; set; }
    public double? TakeProfitPrice { get; set; }
    public double? RiskAmount { get; set; }
    public double? PositionSize { get; set; }
    public double? RiskRewardRatio { get; set; }
}