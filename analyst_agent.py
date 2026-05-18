import logging
from db_manager import DBManager
from config import OLLAMA_BASE_URL
from ollama import Client
from pydantic import BaseModel
import json
import fitz
import os

logger = logging.getLogger(__name__)

class AnalystSchema(BaseModel):
    key_findings: str
    methodology: str
    relevance_to_water_splitting: str
    limitations: str
    russian_translation_of_abstract: str
    russian_analysis_summary: str

class AnalystAgent:
    def __init__(self, db_manager: DBManager):
        self.db_manager = db_manager
        self.client = Client(host=OLLAMA_BASE_URL)
        self.model = "qwen2.5:14b" # Larger model for translation and deep analysis

    def run(self):
        logger.info("Analyst agent starting...")
        articles = self.db_manager.get_articles_by_status('approved')
        if not articles:
            logger.info("No approved articles to analyze.")
            return

        for article in articles:
            article_id, doi, title, authors, year, abstract, pdf_url, full_text_path, analysis_results = article
            
            rolling_summary = analysis_results.get("rolling_summary") if analysis_results else None
            
            if rolling_summary:
                content_to_analyze = rolling_summary
                source_type = "FULL TEXT ROLLING SUMMARY"
                logger.info(f"Using rolling summary for deep analysis of {doi}")
            else:
                content_to_analyze = abstract
                source_type = "ABSTRACT"
            
            prompt = f"""
            You are an expert scientific analyst and professional translator. 
            Deeply analyze the following {source_type} (and title) regarding "water molecule dissociation and recombination on transport phenomena in electromembrane systems".
            
            Title: {title}
            {source_type}: {content_to_analyze}
            
            Extract the key findings, methodology used, specific relevance to water splitting/electromembrane systems, and any mentioned limitations.
            Additionally, provide a full professional Russian translation of the abstract (or the summary if full text summary is provided), and a short summary of your analysis in Russian.
            
            Respond strictly with valid JSON conforming to the requested schema.
            """
            
            try:
                response = self.client.chat(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    format=AnalystSchema.model_json_schema(),
                    options={"temperature": 0.2}
                )
                
                result_content = response.get('message', {}).get('content', '')
                if not result_content:
                    raise ValueError("Empty response from Ollama")
                    
                final_results = json.loads(result_content)
                logger.info(f"Article {article_id} analyzed and translated successfully.")
                
                # Merge rolling summary back into the final results if it existed
                if rolling_summary:
                    final_results["rolling_summary"] = rolling_summary
                    
                self.db_manager.update_analysis_results(article_id, final_results)
                    
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing JSON from Ollama for article {article_id}: {e}")
                self.db_manager.update_article_status(article_id, 'error')
            except Exception as e:
                logger.error(f"Error analyzing article {article_id}: {e}")
                self.db_manager.update_article_status(article_id, 'error')
                
        logger.info("Analyst agent finished.")
