using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Cookies;
using System.Security.Claims;

namespace aios_dashboard_csharp.Services;

/// <summary>
/// Minimal server-side endpoint that performs the actual cookie sign-in.
/// Blazor Server circuits cannot set HTTP cookies directly, so the login page
/// redirects here with credentials; this endpoint validates, signs in, and
/// redirects to the dashboard. Credentials are never logged or persisted.
/// </summary>
public static class LoginEndpoints
{
    public static void MapLoginEndpoints(this WebApplication app)
    {
        // GET /login-direct?u=...&p=... — used by Login.razor after client-side validation.
        // Accepts credentials only from localhost-originated circuits in practice because
        // the page itself is only reachable pre-auth; still validates via AuthService.
        // TODO: remove once Blazor login page is retired (use POST /api/auth/login instead).
        app.MapGet("/login-direct", async (HttpContext ctx, IAuthService auth) =>
        {
            var u = ctx.Request.Query["u"].ToString();
            var p = ctx.Request.Query["p"].ToString();

            if (!auth.ValidateCredentials(u, p))
            {
                ctx.Response.Redirect("/login?error=1");
                return;
            }

            var claims = new List<Claim> { new Claim(ClaimTypes.Name, auth.Username) };
            var identity = new ClaimsIdentity(claims, CookieAuthenticationDefaults.AuthenticationScheme);

            await ctx.SignInAsync(
                CookieAuthenticationDefaults.AuthenticationScheme,
                new ClaimsPrincipal(identity),
                new AuthenticationProperties
                {
                    IsPersistent = false,
                    ExpiresUtc = DateTimeOffset.UtcNow.AddMinutes(auth.SessionTimeoutMinutes),
                });

            ctx.Response.Redirect("/");
        });
    }
}
