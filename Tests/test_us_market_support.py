import os
import subprocess
import sys
from pathlib import Path

from Core.market_config import resolve_provider_symbol


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    old_market = os.environ.get("AIOS_MARKET")
    try:
        os.environ["AIOS_MARKET"] = "idx"
        check(resolve_provider_symbol("BBCA") == "BBCA.JK", "IDX should append .JK")
        os.environ["AIOS_MARKET"] = "us"
        check(resolve_provider_symbol("AAPL") == "AAPL", "US should keep bare ticker")
        check(resolve_provider_symbol("AAPL.US") == "AAPL.US", "explicit suffix must remain unchanged")

        proc = subprocess.run(
            [sys.executable, "main.py", "scan", "--market", "us"],
            capture_output=True,
            text=True,
            env={**os.environ, "AIOS_MARKET": "idx", "EXECUTION_LOT_SIZE": "100"},
        )
        check("Unsupported market" not in proc.stdout, "CLI must accept --market us")
        check(proc.returncode == 0, f"scan --market us failed: {proc.stdout}\n{proc.stderr}")
        print("US MARKET SUPPORT TESTS: PASS")
    finally:
        if old_market is None:
            os.environ.pop("AIOS_MARKET", None)
        else:
            os.environ["AIOS_MARKET"] = old_market


if __name__ == "__main__":
    main()
