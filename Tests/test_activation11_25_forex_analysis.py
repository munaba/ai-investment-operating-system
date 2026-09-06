from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.market_config import resolve_provider_symbol
from Orchestration.market_analysis_skill import MarketAnalysisSkill
from Orchestration.skill_context import SkillContext
from Orchestration.tool_result import ToolResult
import main

PASS = 0
FAIL = 0

def check(ok, msg):
    global PASS, FAIL
    if ok:
        PASS += 1
    else:
        FAIL += 1
    print(("PASS" if ok else "FAIL") + " - " + msg)

class Tool:
    def __init__(self, price=None, news=None):
        self.price = price or {}
        self.news = news or {}
        self.calls = []
    def execute(self, context):
        symbol = context.parameters.get("symbol")
        self.calls.append(symbol)
        if self.price:
            return ToolResult(True, self.price.get(symbol, {"trend": "neutral"}), None, {})
        return ToolResult(True, self.news.get(symbol, {"overall_sentiment": "neutral"}), None, {})

class Resolver:
    def __init__(self, tools): self.tools = tools
    def __call__(self, name): return self.tools[name]

def test_skill():
    price = Tool(price={"EUR/USD": {"trend": "bullish"}, "GBP/USD": {"trend": "bearish"}})
    news = Tool(news={"EUR/USD": {"overall_sentiment": "positive"}, "GBP/USD": {"overall_sentiment": "negative"}})
    fundamental = Tool()
    skill = MarketAnalysisSkill()
    skill._resolve_tool = Resolver({"market_price": price, "market_news": news, "market_fundamental": fundamental})
    ctx = SkillContext(task=None, parameters={"symbols": ["EUR/USD", "GBP/USD", "BBCA"]}, metadata={}, tool_context_factory=None)
    result = skill.execute(ctx)
    by = {x["symbol"]: x for x in result.output["stocks"]}
    check(by["EUR/USD"]["analysis"]["recommendation"] == "BUY", "EUR/USD routes to ForexAnalysisSkill BUY")
    check(by["GBP/USD"]["analysis"]["recommendation"] == "SELL", "GBP/USD routes to ForexAnalysisSkill SELL")
    check("EUR/USD" in price.calls and "GBP/USD" in price.calls, "Forex symbols hit market_price")
    check("EUR/USD" in news.calls and "GBP/USD" in news.calls, "Forex symbols hit market_news")
    check("EUR/USD" not in fundamental.calls and "GBP/USD" not in fundamental.calls, "Forex avoids stock fundamental tool")

def test_scan_dispatch():
    class Scanner:
        def scan(self): return {}
    class App:
        def __init__(self): self.manual_scan_service = Scanner()
    prev = os.environ.get("AIOS_MARKET")
    seen = []
    old_print_report = main._print_manual_scan_report
    old_print_rows = main._print_scan_snapshot_rows
    def run_scan(self, ts):
        seen.append(os.environ.get("AIOS_MARKET")); return type("R", (), {"recommendations": []})()
    App.manual_scan_service = None
    app = App(); app.manual_scan_service = type("S", (), {"run_scan": run_scan})()
    main._print_manual_scan_report = lambda r: None
    main._print_scan_snapshot_rows = lambda *a: None
    try:
        rc = main._run_scan_command(app, ["--market", "forex"])
    finally:
        main._print_manual_scan_report = old_print_report
        main._print_scan_snapshot_rows = old_print_rows
        if prev is None: os.environ.pop("AIOS_MARKET", None)
        else: os.environ["AIOS_MARKET"] = prev
    check(rc == 0, "scan --market forex accepted")
    check(seen == ["forex"], "AIOS_MARKET=forex during scan")

def test_provider_resolution():
    old = os.environ.get("AIOS_MARKET")
    os.environ["AIOS_MARKET"] = "forex"
    try:
        check(resolve_provider_symbol("EUR/USD") == "EURUSD=X", "EUR/USD resolves to EURUSD=X")
        check(resolve_provider_symbol("GBP/USD") == "GBPUSD=X", "GBP/USD resolves to GBPUSD=X")
    finally:
        if old is None: os.environ.pop("AIOS_MARKET", None)
        else: os.environ["AIOS_MARKET"] = old

if __name__ == "__main__":
    test_skill(); test_scan_dispatch(); test_provider_resolution()
    print(f"\nACTIVATION 11.25 FOREX ANALYSIS: {PASS} PASS / {FAIL} FAIL (total {PASS+FAIL})")
    raise SystemExit(0 if FAIL == 0 else 1)
