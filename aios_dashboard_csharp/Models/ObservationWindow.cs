namespace aios_dashboard_csharp.Models;

public class ObservationWindow
{
    public long WindowId { get; set; }
    public string StartAt { get; set; } = string.Empty;
    public string EndAt { get; set; } = string.Empty;
    public string Timezone { get; set; } = string.Empty;
    public string? Note { get; set; }
    public string Status { get; set; } = string.Empty;
    public string CreatedAt { get; set; } = string.Empty;
    public string? ClosedAt { get; set; }
}