namespace aios_dashboard_csharp.Models;

public class Order
{
    public long OrderId { get; set; }
    public string AccountId { get; set; } = string.Empty;
    public string Symbol { get; set; } = string.Empty;
    public string Action { get; set; } = string.Empty;
    public double Quantity { get; set; }
    public double RequestedPrice { get; set; }
    public double FilledPrice { get; set; }
    public double FilledQuantity { get; set; }
    public string Status { get; set; } = string.Empty;
    public string Reason { get; set; } = string.Empty;
    public string CreatedAt { get; set; } = string.Empty;
    public string UpdatedAt { get; set; } = string.Empty;
    public string? FilledAt { get; set; }
    public long? AnalysisSnapshotId { get; set; }
}