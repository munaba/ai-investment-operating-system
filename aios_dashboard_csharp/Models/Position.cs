namespace aios_dashboard_csharp.Models;

public class Position
{
    public long PositionId { get; set; }
    public string AccountId { get; set; } = string.Empty;
    public string Symbol { get; set; } = string.Empty;
    public double Quantity { get; set; }
    public double AveragePrice { get; set; }
    public double RealizedPnl { get; set; }
    public string Status { get; set; } = string.Empty;
    public string Direction { get; set; } = "LONG";
    public double? StopLoss { get; set; }
    public double? TakeProfit { get; set; }
    public double BuyFeeAccumulated { get; set; }
    public string CreatedAt { get; set; } = string.Empty;
    public string UpdatedAt { get; set; } = string.Empty;
}