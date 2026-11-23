# Archived sprint snapshot tests

These 56 `test_stage_l*.py` scripts were moved here on 2026-11-23. They are
kept for history, not run by pytest (see `collect_ignore_glob` in
`Tests/conftest.py`) and not picked up by script-test runners, which only
glob `Tests/test_*.py`.

Sprints archived: l5, l6, l45, l46, l48, l49, l51, l52, l60, l61, l62, l64,
l68–l97 (except l92), l99, l106–l110, l112, l113, l114, l117, l118,
l123, l126, l140, l152.

## Why

Each script froze the contract of one development sprint: the exact set of
public methods, the exact import set of a module, an exact key count in an
output dict, a stub that had to raise `NotImplementedError`, or a
constructor signature. Later sprints deliberately extended those contracts,
so the scripts now fail on the frozen shape rather than on behaviour.
Examples:

- `Executor`, `BaseSkill`, `GoalPlanner` gained public methods in later
  sprints (l45, l46, l68, l77, l94–l96).
- Market tools stopped raising `NotImplementedError` once implemented
  (l48, l49, l60–l62, l89–l91).
- `ToolContext(task=None)` no longer raises (l51, l52, l79, l82, l83, l97).
- Analysis outputs gained keys such as `status` (Activation 2.3.x), and
  `recommendation` is `None` unless status is `SUCCESS` (l112–l114, l117).
- `TradingDecisionAgent`, `MarketAnalysisAgent` and `CapabilityManager`
  now take additional required collaborators (l64, l118, l123, l126, l152).
- `nine_router` joined the provider registry (l6); the vision provider is
  no longer a fixed `WAITING` stub (l140).
- On Python 3.13+, dataclasses expose `__firstlineno__`/`__replace__`,
  which exact-member checks treat as new members (l71, l86, l93).

Rewriting their assertions to match today's code would only restate the
current implementation, not test it. Current behaviour is covered by the
pytest suite and by the later sprint scripts still in `Tests/`.

## Before reviving one

Run it from the repo root with `PYTHONPATH=.` and `DB_PATH` pointing at a
temporary database, update the frozen expectations to the current
contract, and move it back to `Tests/`.
