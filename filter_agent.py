import logging
from db_manager import DBManager
from config import OLLAMA_BASE_URL
from ollama import Client
from pydantic import BaseModel
import json
import requests
import fitz
import os

logger = logging.getLogger(__name__)

class FilterSchema(BaseModel):
    relevance_score: int # Score from 1 to 10
    reasoning: str # Short explanation in Russian

class RollingSummarySchema(BaseModel):
    updated_summary: str

class FilterAgent:
    def __init__(self, db_manager: DBManager):
        self.db_manager = db_manager
        self.client = Client(host=OLLAMA_BASE_URL)
        self.model = "qwen2.5:14b"
        
    def _download_and_extract_pdf(self, article_id, pdf_url):
        if not pdf_url or pdf_url.lower() == "no pdf" or not pdf_url.startswith("http"):
            return None, None
            
        pdf_path = f"/app/downloads/article_{article_id}.pdf"
        
        if not os.path.exists(pdf_path):
            logger.info(f"Downloading PDF from {pdf_url}...")
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                response = requests.get(pdf_url, headers=headers, timeout=30)
                response.raise_for_status()
                with open(pdf_path, 'wb') as f:
                    f.write(response.content)
            except Exception as e:
                logger.error(f"Failed to download PDF from {pdf_url}: {e}")
                return None, None
                
        try:
            doc = fitz.open(pdf_path)
            text = ""
            for page in doc:
                text += page.get_text()
            
            return pdf_path, text
        except Exception as e:
            logger.error(f"Failed to extract text from {pdf_path}: {e}")
            return pdf_path, None

    def _create_rolling_summary(self, full_text, title):
        chunk_size = 12000
        chunks = [full_text[i:i+chunk_size] for i in range(0, len(full_text), chunk_size)]
        
        current_summary = "No summary yet."
        for idx, chunk in enumerate(chunks):
            logger.info(f"Processing chunk {idx+1}/{len(chunks)} for rolling summary...")
            prompt = f"""
            You are analyzing a scientific article titled "{title}".
            This is chunk {idx+1} out of {len(chunks)}.
            
            Previous Summary:
            {current_summary}
            
            Current Chunk:
            {chunk}
            
            Your task: Update the Previous Summary with new important information from the Current Chunk regarding water molecule dissociation, transport phenomena in electromembrane systems, methodology, and key findings. 
            Keep the updated summary concise (max 800 words), but highly informative. Retain all critical scientific details.
            Respond strictly with valid JSON conforming to the requested schema.
            """
            
            try:
                response = self.client.chat(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    format=RollingSummarySchema.model_json_schema(),
                    options={"temperature": 0.0}
                )
                
                result_content = response.get('message', {}).get('content', '')
                result = json.loads(result_content)
                current_summary = result.get('updated_summary', current_summary)
            except Exception as e:
                logger.error(f"Error processing chunk {idx+1}: {e}")
                
        return current_summary

    def run(self):
        logger.info("Filter agent starting...")
        articles = self.db_manager.get_articles_by_status('new')
        if not articles:
            logger.info("No new articles to filter.")
            return

        for article in articles:
            article_id, doi, title, authors, year, abstract, pdf_url, full_text_path, _ = article
            
            pdf_path, full_text = self._download_and_extract_pdf(article_id, pdf_url)
            if pdf_path and not full_text_path:
                self.db_manager.update_full_text_path(article_id, pdf_path)
                
            rolling_summary = None
            if full_text:
                logger.info(f"Generating rolling summary for {doi}")
                rolling_summary = self._create_rolling_summary(full_text, title)
                content_to_analyze = rolling_summary
                source_type = "FULL TEXT ROLLING SUMMARY"
            else:
                content_to_analyze = abstract
                source_type = "ABSTRACT"
            
            logger.info(f"Filtering article {doi} using {source_type}")
            
            prompt = f"""
            Analyze the following scientific article for relevance to the topic: 
            "The influence of water molecule dissociation and recombination on transport phenomena in electromembrane systems (EMS)".
            Key scientific terms: water splitting, second Wien effect, ion-exchange membranes, electrodialysis, overlimiting current, pH shift, Nernst-Planck-Poisson equations.
            
            Title: {title}
            {source_type}: {content_to_analyze}
            
            Provide a relevance score from 1 to 10 and a short reasoning in Russian.
            """
            
            try:
                response = self.client.chat(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    format=FilterSchema.model_json_schema(),
                    options={"temperature": 0.0}
                )
                
                result_content = response.get('message', {}).get('content', '')
                if not result_content:
                    raise ValueError("Empty response from Ollama")
                    
                result = json.loads(result_content)
                score = result.get('relevance_score', 0)
                reasoning = result.get('reasoning', '')
                
                logger.info(f"Article {article_id} scored {score}. Reasoning: {reasoning}")
                
                if score >= 7:
                    self.db_manager.update_article_status(article_id, 'approved', score, rolling_summary=rolling_summary)
                else:
                    self.db_manager.update_article_status(article_id, 'declined', score, rolling_summary=rolling_summary)
                    
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing JSON from Ollama for article {article_id}: {e}")
                self.db_manager.update_article_status(article_id, 'error')
            except Exception as e:
                logger.error(f"Error filtering article {article_id}: {e}")
                self.db_manager.update_article_status(article_id, 'error')
                
        logger.info("Filter agent finished.")
