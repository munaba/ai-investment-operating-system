using aios_dashboard_csharp.Services;
using System.Diagnostics;
using Xunit;

namespace aios_dashboard_csharp.Tests;

/// <summary>
/// Tests for HumanDecisionService. The valid-decision path shells out to python
/// (side effects), so we cover: (a) pure validation/arg-building, (b) the
/// exit-code -> Success mapping via a fake IProcessRunner (no python spawned).
/// </summary>
public class HumanDecisionServiceTests
{
    // ---- Validation (no side effects, hit before any process spawn) ----

    [Theory]
    [InlineData("PENDING")]
    [InlineData("CONTINUE")]
    [InlineData("SIMPLIFY")]
    [InlineData("AUTHORIZE_FUTURE_INVESTIGATION")]
    public async Task ValidDecisions_AreNotRejected(string decision)
    {
        var svc = new HumanDecisionService(new FakeRunner(exitCode: 0));
        var result = await svc.SubmitDecisionAsync(decision, windowId: 1);
        Assert.True(result.Success);
        Assert.Equal(string.Empty, result.Error);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("pending")]            // case-sensitive
    [InlineData("APPROVE")]            // not in set
    [InlineData("CONTINUE ")]          // trailing space
    [InlineData("AUTHORIZE_FUTURE")]   // truncated
    public async Task InvalidDecisions_ReturnFailureWithNoProcessSpawn(string decision)
    {
        var runner = new FakeRunner(exitCode: 0);
        var svc = new HumanDecisionService(runner);
        var result = await svc.SubmitDecisionAsync(decision, windowId: 1);

        Assert.False(result.Success);
        Assert.False(string.IsNullOrEmpty(result.Error));
        Assert.Contains("Invalid decision", result.Error);
        Assert.Equal(0, runner.CallCount);   // process never spawned for invalid input
    }

    // ---- Arg-building (pure helper, single source of truth) ----

    [Fact]
    public void BuildArguments_BaseShape_IsCorrect()
    {
        var args = HumanDecisionService.BuildArguments("CONTINUE", windowId: 0);
        Assert.Equal(new[] { "main.py", "sustained-use-final", "decide", "--decision", "CONTINUE" }, args);
    }

    [Fact]
    public void BuildArguments_WithWindowId_AddsFlag()
    {
        var args = HumanDecisionService.BuildArguments("SIMPLIFY", windowId: 42);
        Assert.Contains("--window-id", args);
        Assert.Contains("42", args);
    }

    [Fact]
    public void BuildArguments_ZeroWindowId_OmitsFlag()
    {
        var args = HumanDecisionService.BuildArguments("SIMPLIFY", windowId: 0);
        Assert.DoesNotContain("--window-id", args);
    }

    [Fact]
    public void BuildArguments_WithNote_AddsFlag()
    {
        var args = HumanDecisionService.BuildArguments("CONTINUE", 1, note: "looks risky");
        Assert.Contains("--note", args);
        Assert.Contains("looks risky", args);
    }

    [Fact]
    public void BuildArguments_WithDecidedBy_AddsFlag()
    {
        var args = HumanDecisionService.BuildArguments("CONTINUE", 1, decidedBy: "nabil");
        Assert.Contains("--decided-by", args);
        Assert.Contains("nabil", args);
    }

    [Fact]
    public void BuildArguments_WhitespaceNote_OmitsFlag()
    {
        var args = HumanDecisionService.BuildArguments("CONTINUE", 1, note: "   ");
        Assert.DoesNotContain("--note", args);
    }

    // ---- Exit-code mapping via fake runner (no python) ----

    [Fact]
    public async Task ZeroExitCode_MapsToSuccess()
    {
        var svc = new HumanDecisionService(new FakeRunner(exitCode: 0, output: "ok"));
        var r = await svc.SubmitDecisionAsync("CONTINUE", 1);
        Assert.True(r.Success);
        Assert.Equal("ok", r.Output);
    }

    [Fact]
    public async Task NonZeroExitCode_MapsToFailure()
    {
        var svc = new HumanDecisionService(new FakeRunner(exitCode: 1, error: "boom"));
        var r = await svc.SubmitDecisionAsync("CONTINUE", 1);
        Assert.False(r.Success);
        Assert.Equal("boom", r.Error);
    }

    [Fact]
    public async Task ValidDecision_RunsPythonMainPy_WithSustainedUseFinal()
    {
        var runner = new FakeRunner(exitCode: 0);
        var svc = new HumanDecisionService(runner);
        await svc.SubmitDecisionAsync("PENDING", 7);

        Assert.Equal(1, runner.CallCount);
        Assert.Equal("python", runner.LastStartInfo!.FileName);
        Assert.Contains("main.py", runner.LastStartInfo.Arguments);
        Assert.Contains("sustained-use-final", runner.LastStartInfo.Arguments);
        Assert.Contains("decide", runner.LastStartInfo.Arguments);
        Assert.Contains("--window-id 7", runner.LastStartInfo.Arguments);
        Assert.True(runner.LastStartInfo.RedirectStandardOutput);
        Assert.True(runner.LastStartInfo.RedirectStandardError);
        Assert.False(runner.LastStartInfo.UseShellExecute);
    }
}

/// <summary>
/// In-memory fake of IProcessRunner — records the spawn and returns a canned
/// result, so we never touch the real python environment in unit tests.
/// </summary>
file sealed class FakeRunner : IProcessRunner
{
    private readonly int _exitCode;
    private readonly string _output;
    private readonly string _error;

    public FakeRunner(int exitCode, string output = "", string error = "")
    {
        _exitCode = exitCode;
        _output = output;
        _error = error;
    }

    public int CallCount { get; private set; }
    public ProcessStartInfo? LastStartInfo { get; private set; }

    public Task<(int ExitCode, string Output, string Error)> RunAsync(ProcessStartInfo startInfo)
    {
        CallCount++;
        LastStartInfo = startInfo;
        return Task.FromResult((_exitCode, _output, _error));
    }
}
