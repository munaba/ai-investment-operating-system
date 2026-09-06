"""Public API for the ``Repository.external`` subpackage."""

from Repository.external.base_external_repository import BaseExternalRepository
from Repository.external.stock_data_repository import StockDataRepository
from Repository.external.news_repository import NewsRepository

__all__ = [
    "BaseExternalRepository",
    "StockDataRepository",
    "NewsRepository",
]