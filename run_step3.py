from src.utils.logger import setup_logger
from src.db.repository import StockRepository
from src.collector.index_collector import IndexCollector

setup_logger()
repo = StockRepository()
IndexCollector(repo).run('20260401', '20260402')