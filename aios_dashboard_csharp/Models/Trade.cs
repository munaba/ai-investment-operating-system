namespace aios_dashboard_csharp.Models;

public class Trade
{
    public long TradeId { get; set; }
    public long OrderId { get; set; }
    public string AccountId { get; set; } = string.Empty;
    public string Symbol { get; set; } = string.Empty;
    public string Action { get; set; } = string.Empty;
    public double Quantity { get; set; }
    public double FillPrice { get; set; }
    public double Fee { get; set; }
    public double Tax { get; set; }
    public string ExecutedAt { get; set; } = string.Empty;
}