using aios_dashboard_csharp.Services;
using Microsoft.Extensions.Configuration;
using Xunit;

namespace aios_dashboard_csharp.Tests;

/// <summary>
/// Tests for AuthService. Validates BCrypt credential check against in-memory config.
/// No seam needed — IConfiguration injected directly via ConfigurationBuilder.
/// </summary>
public class AuthServiceTests
{
    private static IConfiguration BuildConfig(string username = "admin", string passwordHash = "", string? sessionTimeout = null)
    {
        var dict = new Dictionary<string, string?>
        {
            ["DashboardAuth:Username"] = username,
            ["DashboardAuth:PasswordHash"] = passwordHash
        };
        if (sessionTimeout != null)
            dict["DashboardAuth:SessionTimeoutMinutes"] = sessionTimeout;
        return new ConfigurationBuilder().AddInMemoryCollection(dict!).Build();
    }

    // ---- Valid credentials ----

    [Fact]
    public void ValidCredentials_ReturnsTrue()
    {
        // hash for "correct-password" (BCrypt cost 11)
        var hash = BCrypt.Net.BCrypt.HashPassword("correct-password");
        var config = BuildConfig(passwordHash: hash);
        var svc = new AuthService(config);

        var result = svc.ValidateCredentials("admin", "correct-password");

        Assert.True(result);
    }

    [Fact]
    public void ValidCredentials_CaseSensitiveUsername_ReturnsFalse()
    {
        var hash = BCrypt.Net.BCrypt.HashPassword("correct-password");
        var config = BuildConfig(passwordHash: hash);
        var svc = new AuthService(config);

        var result = svc.ValidateCredentials("Admin", "correct-password"); // capital A

        Assert.False(result);
    }

    // ---- Invalid credentials ----

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData(null)]
    public void EmptyOrWhitespacePassword_ReturnsFalse(string? password)
    {
        var hash = BCrypt.Net.BCrypt.HashPassword("correct-password");
        var config = BuildConfig(passwordHash: hash);
        var svc = new AuthService(config);

        var result = svc.ValidateCredentials("admin", password!);

        Assert.False(result);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData(null)]
    public void EmptyOrWhitespaceUsername_ReturnsFalse(string? username)
    {
        var hash = BCrypt.Net.BCrypt.HashPassword("correct-password");
        var config = BuildConfig(passwordHash: hash);
        var svc = new AuthService(config);

        var result = svc.ValidateCredentials(username!, "correct-password");

        Assert.False(result);
    }

    [Fact]
    public void WrongPassword_ReturnsFalse()
    {
        var hash = BCrypt.Net.BCrypt.HashPassword("correct-password");
        var config = BuildConfig(passwordHash: hash);
        var svc = new AuthService(config);

        var result = svc.ValidateCredentials("admin", "wrong-password");

        Assert.False(result);
    }

    [Fact]
    public void NonExistentUser_ReturnsFalse()
    {
        var hash = BCrypt.Net.BCrypt.HashPassword("correct-password");
        var config = BuildConfig(username: "admin", passwordHash: hash);
        var svc = new AuthService(config);

        var result = svc.ValidateCredentials("nobody", "correct-password");

        Assert.False(result);
    }

    // ---- Missing hash configuration (fail-closed) ----

    [Fact]
    public void MissingPasswordHash_ReturnsFalse_FailClosed()
    {
        var config = BuildConfig(passwordHash: ""); // empty string
        var svc = new AuthService(config);

        var result = svc.ValidateCredentials("admin", "anything");

        Assert.False(result);
    }

    [Fact]
    public void NullPasswordHash_ReturnsFalse_FailClosed()
    {
        var dict = new Dictionary<string, string?>
        {
            ["DashboardAuth:Username"] = "admin"
            // DashboardAuth:PasswordHash omitted entirely
        };
        var config = new ConfigurationBuilder().AddInMemoryCollection(dict).Build();
        var svc = new AuthService(config);

        var result = svc.ValidateCredentials("admin", "anything");

        Assert.False(result);
    }

    // ---- Username / SessionTimeout config ----

    [Fact]
    public void Username_FromConfig_DefaultsToAdmin()
    {
        var config = BuildConfig(passwordHash: "dummy");
        var svc = new AuthService(config);

        Assert.Equal("admin", svc.Username);
    }

    [Fact]
    public void Username_FromConfig_RespectsOverride()
    {
        var config = BuildConfig(username: "custom-user", passwordHash: "dummy");
        var svc = new AuthService(config);

        Assert.Equal("custom-user", svc.Username);
    }

    [Fact]
    public void SessionTimeoutMinutes_DefaultsTo60()
    {
        var config = BuildConfig(passwordHash: "dummy");
        var svc = new AuthService(config);

        Assert.Equal(60, svc.SessionTimeoutMinutes);
    }

    [Fact]
    public void SessionTimeoutMinutes_ParsesFromConfig()
    {
        var config = BuildConfig(passwordHash: "dummy", sessionTimeout: "30");
        var svc = new AuthService(config);

        Assert.Equal(30, svc.SessionTimeoutMinutes);
    }

    [Fact]
    public void SessionTimeoutMinutes_InvalidValue_DefaultsTo60()
    {
        var config = BuildConfig(passwordHash: "dummy", sessionTimeout: "not-a-number");
        var svc = new AuthService(config);

        Assert.Equal(60, svc.SessionTimeoutMinutes);
    }
}