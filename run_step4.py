from src.utils.logger import setup_logger
from src.db.repository import StockRepository
from src.collector.finance_collector import FinanceCollector

setup_logger()
repo = StockRepository()
FinanceCollector(repo).run(years=[2024, 2025])