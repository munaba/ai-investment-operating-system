
# AIOS Architecture Decisions

## Current Status

- Foundation complete
- AutonomousAgent complete
- AutonomousHost complete
- AutonomousScheduler complete

## Do NOT extend

- AutonomousAgent lifecycle
- Scheduler API
- Host API

## Next Priority

1. Event Bus
2. Task Manager
3. Workflow Engine
4. Memory Engine
5. Plugin Runtime

Rule:
Do not add new methods to existing autonomous classes unless absolutely required.
Prefer building new subsystems over extending existing ones.
