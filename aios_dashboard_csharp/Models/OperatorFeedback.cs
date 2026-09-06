namespace aios_dashboard_csharp.Models;

public class OperatorFeedback
{
    public long FeedbackId { get; set; }
    public long ObservationWindowId { get; set; }
    public string RecordedAt { get; set; } = string.Empty;
    public int? OperatorRating { get; set; }
    public string? AlertUsefulness { get; set; }
    public string? DataReliabilityFeedback { get; set; }
    public string? DecisionQualityFeedback { get; set; }
    public string? WorkflowUsabilityFeedback { get; set; }
    public string? FreeText { get; set; }
    public string Concerns { get; set; } = "[]";
    public string? OperatorLabel { get; set; }
}