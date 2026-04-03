from src.utils.logger import setup_logger
from src.db.repository import StockRepository
from src.collector.price_collector import PriceCollector

setup_logger()
repo = StockRepository()
PriceCollector(repo).run('20260401', '20260402')