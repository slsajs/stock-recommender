from src.utils.logger import setup_logger
from src.db.connection import init_pool, close_pool
from src.main import run_daily

setup_logger()
init_pool()
run_daily()
close_pool()
