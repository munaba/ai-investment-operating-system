# AI Agent Framework

A modular AI Agent Framework built with SOLID architecture.

## Features

- Multi Provider
- Tool Registry
- Service Layer
- Planner
- Memory
- Conversation
- Stock Analysis
- News
- Chart
- Backtesting

## Run

```bash
pip install -r requirements.txt
python main.py
```

`requirements.txt` installs only the core dependencies (needed just to
start the app). Add the provider(s) and/or feature(s) you actually need:

```bash
pip install -r requirements.txt -r requirements-gemini.txt      # Gemini provider
pip install -r requirements.txt -r requirements-ollama.txt      # Ollama provider
pip install -r requirements.txt -r requirements-optional.txt    # chart / backtest / market data / notifications
```

Or install everything at once:

```bash
pip install -r requirements-full.txt
```

To run the test suite (adds `pytest`, needed by 3 of 246 test files; the
rest are standalone scripts with no extra dependency):

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

```bash
python Tests/test_stock_agent_smoke.py
python Tests/integration_test.py
python Tests/E2e_test.py
```

Architecture

Core
