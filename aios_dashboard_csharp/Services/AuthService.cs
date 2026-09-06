using Microsoft.AspNetCore.Authentication.Cookies;
using Microsoft.AspNetCore.Authentication;
using System.Security.Claims;

namespace aios_dashboard_csharp.Services;

/// <summary>
/// Single-user credential check against BCrypt hash stored in appsettings.json.
/// Deliberately NOT ASP.NET Core Identity — too heavy for a single-user LAN dashboard.
/// </summary>
public interface IAuthService
{
    string Username { get; }
    int SessionTimeoutMinutes { get; }
    bool ValidateCredentials(string username, string password);
}

public class AuthService : IAuthService
{
    private readonly IConfiguration _config;

    public AuthService(IConfiguration config)
    {
        _config = config;
    }

    public string Username => _config["DashboardAuth:Username"] ?? "admin";
    public int SessionTimeoutMinutes => int.TryParse(_config["DashboardAuth:SessionTimeoutMinutes"], out var m) ? m : 60;

    public bool ValidateCredentials(string username, string password)
    {
        if (string.IsNullOrWhiteSpace(username) || string.IsNullOrWhiteSpace(password))
            return false;

        var storedHash = _config["DashboardAuth:PasswordHash"];
        if (string.IsNullOrEmpty(storedHash))
            return false; // fail-closed: no hash configured = no login

        if (!string.Equals(username, Username, StringComparison.Ordinal))
            return false;

        return BCrypt.Net.BCrypt.Verify(password, storedHash);
    }
}
