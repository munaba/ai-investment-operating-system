from __future__ import annotations

import os

from Core.market_config import resolve_provider_symbol
from main import _compute_allocation_quantity, _configure_cli_market


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print(f"PASS: {name}")


def main():
    old = os.environ.get("AIOS_MARKET")
    old_lot = os.environ.get("EXECUTION_LOT_SIZE")
    try:
        os.environ["AIOS_MARKET"] = "crypto"
        check("crypto symbol passthrough", resolve_provider_symbol("BTC-USD") == "BTC-USD")
        check("crypto symbol passthrough ETH", resolve_provider_symbol("ETH-USD") == "ETH-USD")
        check("crypto allocation fractional", _compute_allocation_quantity(100_000_000, 0.01, 100_000.0, 1, market="crypto") == 10.0)
        check("crypto cli market accepted", _configure_cli_market(["--market", "crypto"]) == 0)
        check("crypto env configured", os.environ.get("AIOS_MARKET") == "crypto")
        check("crypto lot env safe", os.environ.get("EXECUTION_LOT_SIZE") == "1")
        os.environ["AIOS_MARKET"] = "idx"
        check("idx suffix preserved", resolve_provider_symbol("BBCA") == "BBCA.JK")
    finally:
        if old is None:
            os.environ.pop("AIOS_MARKET", None)
        else:
            os.environ["AIOS_MARKET"] = old
        if old_lot is None:
            os.environ.pop("EXECUTION_LOT_SIZE", None)
        else:
            os.environ["EXECUTION_LOT_SIZE"] = old_lot


if __name__ == "__main__":
    main()
