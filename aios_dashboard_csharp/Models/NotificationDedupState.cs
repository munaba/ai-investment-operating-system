namespace aios_dashboard_csharp.Models;

public class NotificationDedupState
{
    public string AlertType { get; set; } = string.Empty;
    public string? LastSignature { get; set; }
    public string? LastSentAt { get; set; }
    public string LastStatus { get; set; } = string.Empty;
    public string UpdatedAt { get; set; } = string.Empty;
}