import logging
import json
import os
from db_manager import DBManager

logger = logging.getLogger(__name__)

class Exporter:
    def __init__(self, db_manager: DBManager):
        self.db_manager = db_manager

    def run(self):
        logger.info("Exporter starting...")
        
        os.makedirs('/app/downloads', exist_ok=True)
        export_path = '/app/downloads/analyzed_articles.json'
        
        conn = self.db_manager.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT doi, title, authors, year, abstract, relevance_score, analysis_results 
                    FROM articles 
                    WHERE status = 'analyzed'
                """)
                
                columns = [desc[0] for desc in cursor.description]
                results = []
                for row in cursor.fetchall():
                    results.append(dict(zip(columns, row)))
                    
                with open(export_path, 'w', encoding='utf-8') as f:
                    json.dump(results, f, ensure_ascii=False, indent=4)
                    
                logger.info(f"Exported {len(results)} articles to {export_path}")
        except Exception as e:
            logger.error(f"Error exporting articles: {e}")
        finally:
            self.db_manager.release_connection(conn)
            
        logger.info("Exporter finished.")
