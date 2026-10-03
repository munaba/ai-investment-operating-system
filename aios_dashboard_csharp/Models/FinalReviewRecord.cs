namespace aios_dashboard_csharp.Models;

public class FinalReviewRecord
{
    public long ReviewId { get; set; }
    public long ObservationWindowId { get; set; }
    public string ReviewedAt { get; set; } = string.Empty;
    public string EvidenceStatus { get; set; } = string.Empty;
    public string KnownLimitations { get; set; } = "[]";
    public string OperatorFeedbackIds { get; set; } = "[]";
    public string HumanDecision { get; set; } = "PENDING";
    public string? DecisionNote { get; set; }
    public string? DecidedAt { get; set; }
    public string? DecidedBy { get; set; }
    public string CreatedAt { get; set; } = string.Empty;
    public string UpdatedAt { get; set; } = string.Empty;
}