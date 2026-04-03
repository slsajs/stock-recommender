from src.utils.logger import setup_logger
from src.db.repository import StockRepository
from src.collector.investor_collector import InvestorCollector

setup_logger()
repo = StockRepository()
InvestorCollector(repo).run('20260401', '20260402')
