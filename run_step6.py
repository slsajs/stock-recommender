from src.utils.logger import setup_logger
from src.db.connection import init_pool, close_pool
from src.db.repository import StockRepository
from src.collector.macro_collector import MacroCollector

setup_logger()
init_pool()
repo = StockRepository()
MacroCollector(repo).run(
    indicator_codes=['BASE_RATE', 'USD_KRW', 'KTB_10Y'],
    start_date='20260101',
    end_date='20261231',
)
close_pool()