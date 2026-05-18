import logging
import os
from db_manager import DBManager
from fetcher_agent import FetcherAgent
from filter_agent import FilterAgent
from analyst_agent import AnalystAgent
from exporter import Exporter

# Setup logging
os.makedirs('/app/logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/app/logs/agent.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

def main():
    logger.info("Starting Multi-Agent System...")
    
    try:
        db_manager = DBManager()
        
        # 1. Fetch new articles
        logger.info("--- PHASE 1: FETCHING ---")
        fetcher = FetcherAgent(db_manager)
        fetcher.run()
        
        # 2. Filter new articles (Uses llama3.1:8b)
        # We run this strictly sequentially to avoid OOM
        logger.info("--- PHASE 2: FILTERING ---")
        filter_agent = FilterAgent(db_manager)
        filter_agent.run()
        
        # 3. Analyze approved articles (Uses qwen2.5:14b)
        # Strict sequential execution continues
        logger.info("--- PHASE 3: ANALYZING ---")
        analyst = AnalystAgent(db_manager)
        analyst.run()
        
        # 4. Export results
        logger.info("--- PHASE 4: EXPORTING ---")
        exporter = Exporter(db_manager)
        exporter.run()
        
    except Exception as e:
        logger.error(f"System encountered a fatal error: {e}")
    finally:
        logger.info("Multi-Agent System finished its run.")

if __name__ == "__main__":
    main()
