using System.Diagnostics;
using aios_dashboard_csharp.Models;

namespace aios_dashboard_csharp.Services;

public interface IHumanDecisionService
{
    Task<(bool Success, string Output, string Error)> SubmitDecisionAsync(string decision, long windowId, string? note = null, string? decidedBy = null);
}

/// <summary>
/// Additive test seam (no behavior change): isolates the Process spawn so the
/// decision -> args -> exit-code mapping is unit-testable without a live python run.
/// </summary>
public interface IProcessRunner
{
    Task<(int ExitCode, string Output, string Error)> RunAsync(ProcessStartInfo startInfo);
}

public sealed class RealProcessRunner : IProcessRunner
{
    public async Task<(int ExitCode, string Output, string Error)> RunAsync(ProcessStartInfo startInfo)
    {
        using var process = new Process { StartInfo = startInfo };
        process.Start();

        var outputTask = process.StandardOutput.ReadToEndAsync();
        var errorTask = process.StandardError.ReadToEndAsync();

        await process.WaitForExitAsync();

        var output = await outputTask;
        var error = await errorTask;

        return (process.ExitCode, output.Trim(), error.Trim());
    }
}

public class HumanDecisionService : IHumanDecisionService
{
    private readonly string _workingDirectory = @"F:\My Son";
    private readonly IProcessRunner _runner;

    // Default ctor preserves existing DI registration (AddSingleton<...> with no args).
    public HumanDecisionService(IProcessRunner? runner = null)
    {
        _runner = runner ?? new RealProcessRunner();
    }


    public async Task<(bool Success, string Output, string Error)> SubmitDecisionAsync(string decision, long windowId, string? note = null, string? decidedBy = null)
    {
        var validDecisions = new[] { "PENDING", "CONTINUE", "SIMPLIFY", "AUTHORIZE_FUTURE_INVESTIGATION" };
        if (!validDecisions.Contains(decision))
        {
            return (false, string.Empty, $"Invalid decision: {decision}. Must be one of: {string.Join(", ", validDecisions)}");
        }

        var args = BuildArguments(decision, windowId, note, decidedBy);
        var processInfo = new ProcessStartInfo
        {
            FileName = "python",
            Arguments = string.Join(" ", args.Select(a => a.Contains(' ') ? $"\"{a}\"" : a)),
            WorkingDirectory = _workingDirectory,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true
        };

        var (exitCode, output, error) = await _runner.RunAsync(processInfo);
        return (exitCode == 0, output, error);
    }

    /// <summary>
    /// Pure helper: builds the exact argument list passed to python main.py.
    /// Exposed for unit testing the decision -> args mapping without spawning a process.
    /// </summary>
    public static IReadOnlyList<string> BuildArguments(string decision, long windowId, string? note = null, string? decidedBy = null)
    {
        var args = new List<string> { "main.py", "sustained-use-final", "decide", "--decision", decision };
        if (windowId > 0)
            args.AddRange(new[] { "--window-id", windowId.ToString() });
        if (!string.IsNullOrWhiteSpace(note))
            args.AddRange(new[] { "--note", note });
        if (!string.IsNullOrWhiteSpace(decidedBy))
            args.AddRange(new[] { "--decided-by", decidedBy });
        return args;
    }
}