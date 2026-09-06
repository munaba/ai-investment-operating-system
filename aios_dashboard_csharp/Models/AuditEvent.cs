namespace aios_dashboard_csharp.Models;

public class AuditEvent
{
    public long? Id { get; set; }
    public string EventType { get; set; } = string.Empty;
    public string? Payload { get; set; }
    public string CreatedAt { get; set; } = string.Empty;
}