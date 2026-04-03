from src.utils.logger import setup_logger
from src.db.repository import StockRepository
from src.collector.disclosure_collector import DisclosureCollector

setup_logger()
repo = StockRepository()
DisclosureCollector(repo).run('2026-04-01', '2026-04-02')