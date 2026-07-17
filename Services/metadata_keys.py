"""Shared ``ServiceContext.metadata`` key names, used across all services.

Every service previously read/wrote its metadata keys as inline string
literals (e.g. ``context.get_metadata("history", None)``). This module
centralizes those literal key names as class attributes on
:class:`MetadataKeys`, so a key is spelled once and typos become import-time
(attribute) errors instead of silent metadata-lookup misses.

This module only centralizes key *names*. Default *values* (e.g. the
default ticker or period) live in ``Core.request_defaults`` -- a separate
concern (see Core.analysis_pipeline / Agents.stock_agent for how the two
are used together).

Behavior is unchanged: these are the exact same string values every
service already used.
"""

from __future__ import annotations


class MetadataKeys:
    """Canonical ``ServiceContext.metadata`` key names.

    Grouped by the service that principally produces each key, in pipeline
    execution order. A key produced by one service is frequently consumed
    by a later one (e.g. ``HISTORY`` is produced by ``StockService`` and
    consumed by ``TechnicalIndicatorService``, ``MovingAverageService``,
    ``ChartService``, and ``BacktestService``).
    """

    # --- Request-level / seeded by StockAgent (Core.request_defaults) ---
    TICKER = "ticker"
    PERIOD = "period"
    INTERVAL = "interval"
    MAX_NEWS = "max_news"

    # --- StockService ---
    HISTORY = "history"
    INFO = "info"
    PRICE = "harga"
    PER = "per"
    ROE = "roe"
    DIVIDEND_YIELD = "dividend_yield"

    # --- TechnicalIndicatorService ---
    RSI = "rsi"
    MACD = "macd"
    MACD_SIGNAL = "macd_signal"
    BOLLINGER_UPPER = "bollinger_upper"
    BOLLINGER_LOWER = "bollinger_lower"
    ATR = "atr"
    OBV = "obv"

    # --- MovingAverageService ---
    MA20 = "ma20"
    MA50 = "ma50"
    MA200 = "ma200"

    # --- TechnicalScoreService ---
    TECHNICAL_SCORE = "technical_score"

    # --- FundamentalService ---
    PER_SECTOR_AVG = "per_rata_sektor"
    ROE_SECTOR_AVG = "roe_rata_sektor"
    FUNDAMENTAL_SCORE = "fundamental_score"

    # --- BacktestService ---
    STRATEGY = "strategy"
    INITIAL_CAPITAL = "initial_capital"
    FAST_PERIOD = "fast_period"
    SLOW_PERIOD = "slow_period"
    TOTAL_RETURN = "total_return"
    FINAL_CAPITAL = "final_capital"
    TOTAL_TRADE = "total_trade"
    WIN_RATE = "win_rate"
    TRADE_HISTORY = "trade_history"

    # --- PatternService ---
    AVG_RETURN = "rata_rata_return"
    PATTERN_SCORE = "pattern_score"

    # --- ChartService ---
    INDICATORS = "indicators"
    IMAGE_PATH = "image_path"
    FIGURE = "figure"
    CHART_METADATA = "metadata"

    # --- NewsService ---
    NEWS = "news"
    TOTAL_NEWS = "total_news"

    # --- RiskManagementService ---
    ENTRY_PRICE = "entry_price"
    STOP_LOSS_PERCENT = "stop_loss_percent"
    TAKE_PROFIT_PERCENT = "take_profit_percent"
    RISK_PER_TRADE_PERCENT = "risk_per_trade_percent"
    ACCOUNT_BALANCE = "account_balance"
    STOP_LOSS_PRICE = "stop_loss_price"
    TAKE_PROFIT_PRICE = "take_profit_price"
    RISK_AMOUNT = "risk_amount"
    POSITION_SIZE = "position_size"
    RISK_REWARD_RATIO = "risk_reward_ratio"

    # --- ScoringService ---
    OVERALL_SCORE = "overall_score"
    LABEL = "label"

    # --- NotificationService (unwired from the pipeline, see architecture.md SS3.3) ---
    CHANNEL = "channel"
    MESSAGE = "message"
    TITLE = "title"
    WEBHOOK_URL = "webhook_url"
    TELEGRAM_BOT_TOKEN = "telegram_bot_token"
    TELEGRAM_CHAT_ID = "telegram_chat_id"
