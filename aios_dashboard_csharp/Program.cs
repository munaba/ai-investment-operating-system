using aios_dashboard_csharp.Components;
using aios_dashboard_csharp.Services;
using System.Threading.RateLimiting;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Cookies;
using Microsoft.AspNetCore.Mvc;
using System.Security.Claims;

var builder = WebApplication.CreateBuilder(args);

// Configure logging to show Information level in console
builder.Logging.ClearProviders();
builder.Logging.AddConsole();
builder.Logging.SetMinimumLevel(LogLevel.Information);

// Add services to the container.
builder.Services.AddRazorComponents()
    .AddInteractiveServerComponents();

// Register DatabaseService as singleton (connection string is fixed)
builder.Services.AddSingleton<IDatabaseService, DatabaseService>();

// Register HumanDecisionService
builder.Services.AddSingleton<IHumanDecisionService, HumanDecisionService>();

// Register AlertService
builder.Services.AddSingleton<IAlertService, AlertService>();

// Register AuthService
builder.Services.AddSingleton<IAuthService, AuthService>();

// Register TimeProvider (for AlertService)
builder.Services.AddSingleton<ITimeProvider, RealTimeProvider>();

// Add HttpClient for any external calls
builder.Services.AddHttpClient();
builder.Services.AddHttpContextAccessor();
builder.Services.AddCascadingAuthenticationState();
builder.Services
    .AddAuthentication(CookieAuthenticationDefaults.AuthenticationScheme)
    .AddCookie(options =>
    {
        options.LoginPath = "/login";
        options.AccessDeniedPath = "/login";
        options.ExpireTimeSpan = TimeSpan.FromMinutes(
            int.TryParse(builder.Configuration["DashboardAuth:SessionTimeoutMinutes"], out var m) ? m : 60);
        options.SlidingExpiration = true;      // 30-60 min inactivity → re-login
        options.Cookie.HttpOnly = true;
        options.Cookie.SameSite = SameSiteMode.Lax;
        // LAN-only HTTP in development → allow plain HTTP cookies; everywhere else
        // require HTTPS so the cookie is never sent in clear text.
        options.Cookie.SecurePolicy = builder.Environment.IsDevelopment()
            ? CookieSecurePolicy.SameAsRequest
            : CookieSecurePolicy.Always;
    });
builder.Services.AddAuthorization();

// M-06: CORS whitelist for React SPA dev (5173) + prod self-host (5000)
builder.Services.AddCors(options =>
{
    options.AddDefaultPolicy(policy =>
    {
        policy.WithOrigins("http://localhost:5173", "http://192.168.44.47:5000")
              .AllowAnyMethod()
              .AllowAnyHeader()
              .AllowCredentials();
    });
});

// M-02: brute-force guard on the public login endpoint (single-user LAN:
// 5 attempts/min per client IP; legit mistypes unaffected, bots throttled).
builder.Services.AddRateLimiter(options =>
{
    options.RejectionStatusCode = StatusCodes.Status429TooManyRequests;
    options.AddPolicy("login", context =>
        RateLimitPartition.GetFixedWindowLimiter(
            context.Connection.RemoteIpAddress?.ToString() ?? "unknown",
            _ => new FixedWindowRateLimiterOptions
            {
                PermitLimit = 5,
                Window = TimeSpan.FromMinutes(1),
                QueueProcessingOrder = QueueProcessingOrder.OldestFirst,
                QueueLimit = 0
            }));
});

var app = builder.Build();

// Configure the HTTP request pipeline.
if (!app.Environment.IsDevelopment())
{
    app.UseExceptionHandler("/Error", createScopeForErrors: true);
    // M-05: HSTS in production (15768000s = 6 months, includeSubDomains off for LAN wildcard cert)
    app.UseHsts();
}

// HTTPS redirection disabled for LAN HTTP-only access from phones/other devices.
// Re-enable if you set up a proper certificate:
// app.UseHttpsRedirection();

app.UseStaticFiles();

app.UseRouting();
app.UseCors();  // M-06: apply CORS policy before auth

app.UseRateLimiter();

// ===== Security response headers (defence in depth) =====
// 'wasm-unsafe-eval' is required by Blazor Server's blazor.web.js runtime;
// 'unsafe-inline' for styles is required by Blazor's own scoped-CSS injection.
app.Use(async (context, next) =>
{
    var headers = context.Response.Headers;

    headers["X-Frame-Options"] = "DENY";
    headers["X-Content-Type-Options"] = "nosniff";
    headers["Referrer-Policy"] = "strict-origin-when-cross-origin";
    headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=(), payment=(), usb=()";
    headers["Cross-Origin-Opener-Policy"] = "same-origin";

    if (!headers.ContainsKey("Content-Security-Policy"))
    {
        headers["Content-Security-Policy"] =
            "default-src 'self'; " +
            "script-src 'self' 'wasm-unsafe-eval'; " +
            "style-src 'self' 'unsafe-inline'; " +
            "img-src 'self' data: https:; " +
            "font-src 'self' data:; " +
            "connect-src 'self' https:; " +
            "frame-ancestors 'none'; " +
            "base-uri 'self'; " +
            "form-action 'self'; " +
            "object-src 'none'";
    }

    await next();
});

app.UseAuthentication();
app.UseAuthorization();

// LAN gate: every request must be authenticated OR hit a public path (/login etc.)
// This is the hard wall — Razor components never render for unauthenticated users.
app.Use(async (context, next) =>
{
    var path = context.Request.Path.Value?.ToLowerInvariant() ?? "/";

    var isPublic =
        path.StartsWith("/login") ||            // Blazor login page (GET /login-direct removed)
        path.StartsWith("/api/auth/login") ||   // SPA login endpoint (must be reachable pre-auth)
        path.StartsWith("/logout") ||
        path.StartsWith("/atrium") ||           // Public: marketing/foyer pages
        path.StartsWith("/atlas") ||
        path.StartsWith("/arc") ||
        path.StartsWith("/materi") ||
        path.StartsWith("/jejak") ||
        path.StartsWith("/profil") ||
        path.StartsWith("/_blazor") ||
        path.StartsWith("/_framework") ||
        path.StartsWith("/css") ||
        path.StartsWith("/js") ||
        path.StartsWith("/lib") ||
        path.StartsWith("/icons") ||
        path.StartsWith("/favicon") ||
        path.StartsWith("/_content");

    if (isPublic || context.User.Identity?.IsAuthenticated == true)
    {
        await next();
    }
    else
    {
        context.Response.Redirect("/login");
    }
});

app.UseAntiforgery();

app.MapRazorComponents<App>()
    .AddInteractiveServerRenderMode();

// NOTE: GET /login-direct?u=...&p=... was REMOVED (password travelled in the query
// string and leaked into access logs). Blazor Login.razor now signs in in-process
// via IAuthService + HttpContext.SignInAsync; the React SPA uses the POST endpoint
// below. Both paths use cookie auth, so subsequent /api calls are authenticated.
app.MapPost("/api/auth/login", async (HttpContext ctx, [FromServices] IAuthService auth) =>
{
    var req = await ctx.Request.ReadFromJsonAsync<LoginRequest>();
    if (req is null || !auth.ValidateCredentials(req.Username, req.Password))
        return Results.Json(new { success = false, error = "Invalid username or password" }, statusCode: 401);

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

    return Results.Json(new { success = true });
}).RequireRateLimiting("login");

// Logout is POST-only: a GET logout sends its cookie on every top-level
// navigation (CSRF-able under SameSite=Lax). Lax already blocks cross-site
// POST cookies, so POST-only logout + Lax closes the hole with no token infra.
app.MapPost("/logout", async (HttpContext ctx) =>
{
    await ctx.SignOutAsync(CookieAuthenticationDefaults.AuthenticationScheme);
    ctx.Response.Redirect("/login");
});

// ===== Minimal REST API for React frontend (read-only, mirrors DatabaseService) =====
var api = app.MapGroup("/api").RequireAuthorization();

api.MapGet("/health", () => Results.Ok(new { status = "ok", timestamp = DateTime.UtcNow }));

// M-03+M-08: db-info hanya {exists,sizeMb} (tanpa path); path tunggal dari IDatabaseService.DbPath.
api.MapGet("/phase0/db-info", async (IDatabaseService db) =>
{
    var dbPath = db.DbPath;
    var exists = System.IO.File.Exists(dbPath);
    var sizeMb = exists ? Math.Round(new System.IO.FileInfo(dbPath).Length / (1024.0 * 1024.0), 2) : 0;
    return Results.Ok(new { exists, sizeMb });
});

api.MapPost("/phase0/test-connection", async (IDatabaseService db) =>
{
    var ok = await db.TestConnectionAsync();
    return Results.Ok(new { success = ok });
});

api.MapGet("/phase0/tables", async (IDatabaseService db) =>
{
    var dbPath = db.DbPath;
    if (!System.IO.File.Exists(dbPath)) return Results.Ok(new List<string>());
    try
    {
        using var conn = new Microsoft.Data.Sqlite.SqliteConnection($"Data Source={dbPath};Mode=ReadOnly");
        await conn.OpenAsync();
        using var cmd = conn.CreateCommand();
        cmd.CommandText = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name";
        using var reader = await cmd.ExecuteReaderAsync();
        var tables = new List<string>();
        while (await reader.ReadAsync()) tables.Add(reader.GetString(0));
        return Results.Ok(tables);
    }
    catch (Exception ex)
    {
        // M-04: pesan exception mentah tidak ke client; detail hanya di log server.
        app.Logger.LogError(ex, "[phase0] GET /api/phase0/tables failed");
        return Results.Problem("Gagal memuat daftar tabel.");
    }
});

// Phase 1: Journal entries
api.MapGet("/phase1/journal", async (IDatabaseService db, string? symbol, string? decision, string? riskPolicy, DateTime? fromDate) =>
{
    var entries = await db.GetJournalEntriesAsync(symbol, decision, riskPolicy, fromDate);
    return Results.Ok(entries);
});

api.MapGet("/phase1/symbols", async (IDatabaseService db) =>
{
    var entries = await db.GetJournalEntriesAsync();
    var symbols = entries.Select(e => e.Symbol).Distinct().OrderBy(s => s).ToList();
    return Results.Ok(symbols);
});

// Phase 2: Observation windows + reviews + feedback
api.MapGet("/phase2/windows", async (IDatabaseService db) =>
{
    var windows = await db.GetObservationWindowsAsync();
    return Results.Ok(windows);
});

api.MapGet("/phase2/review/{windowId:long}", async (IDatabaseService db, long windowId) =>
{
    var review = await db.GetFinalReviewRecordAsync(windowId);
    return review is null ? Results.NotFound() : Results.Ok(review);
});

api.MapGet("/phase2/feedback/{windowId:long}", async (IDatabaseService db, long windowId) =>
{
    var feedback = await db.GetOperatorFeedbackAsync(windowId);
    return Results.Ok(feedback);
});

// Phase 3: Positions, orders, trades, scheduler, dedup, audit
api.MapGet("/phase3/positions", async (IDatabaseService db) =>
{
    var positions = await db.GetPositionsAsync();
    return Results.Ok(positions);
});

api.MapGet("/phase3/orders", async (IDatabaseService db) =>
{
    var orders = await db.GetOrdersAsync();
    return Results.Ok(orders);
});

api.MapGet("/phase3/trades", async (IDatabaseService db) =>
{
    var trades = await db.GetTradesAsync();
    return Results.Ok(trades);
});

api.MapGet("/phase3/scheduler", async (IDatabaseService db) =>
{
    var jobs = await db.GetSchedulerJobRunsAsync();
    return Results.Ok(jobs);
});

api.MapGet("/phase3/dedup", async (IDatabaseService db) =>
{
    var dedup = await db.GetNotificationDedupStateAsync();
    return Results.Ok(dedup);
});

api.MapGet("/phase3/audit", async (IDatabaseService db, int limit = 50) =>
{
    var audit = await db.GetAuditEventsAsync(limit);
    return Results.Ok(audit);
});

// Alerts (for AlertBanner)
api.MapGet("/alerts", async (IAlertService alerts) =>
{
    var items = await alerts.GetActiveAlertsAsync();
    return Results.Ok(items);
});

// Human decision submission (mirrors HumanDecisionService.SubmitDecisionAsync)
// M-04: output/error mentah proses CLI hanya di log server; client terima status + pesan aman.
api.MapPost("/decision/submit", async (IHumanDecisionService svc, DecisionSubmitRequest req) =>
{
    var (success, output, error) = await svc.SubmitDecisionAsync(req.Decision, req.WindowId, req.Note, req.DecidedBy);
    if (!success)
    {
        app.Logger.LogWarning("[decision] submit failed for window {WindowId}: {Error} {Output}", req.WindowId, error, output);
        return Results.BadRequest(new { success = false, error = "Pengajuan keputusan gagal." });
    }
    return Results.Ok(new { success = true });
});

app.Run();

// Request DTOs declared after top-level statements (C# requires type declarations
// to follow the last top-level statement).
record LoginRequest(string Username, string Password);
record DecisionSubmitRequest(string Decision, long WindowId, string? Note = null, string? DecidedBy = null);
