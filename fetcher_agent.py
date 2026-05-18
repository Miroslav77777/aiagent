import logging
from bs4 import BeautifulSoup
from db_manager import DBManager
from config import SEARCH_TERMS, OLLAMA_BASE_URL
from ollama import Client
from pydantic import BaseModel
import json
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)

class ArticleSchema(BaseModel):
    title: str
    authors: str
    doi: str
    year: int
    abstract: str
    pdf_url: str

class ArticleListSchema(BaseModel):
    articles: list[ArticleSchema]

class FetcherAgent:
    def __init__(self, db_manager: DBManager):
        self.db_manager = db_manager
        self.client = Client(host=OLLAMA_BASE_URL)
        self.model = "qwen2.5:7b" # Fast model for HTML parsing
        self.total_extracted = 0

    def _ai_parse_html(self, html_content: str, source_name: str):
        logger.info(f"AI is parsing HTML from {source_name}...")
        
        soup = BeautifulSoup(html_content, 'html.parser')
        for data in soup(['style', 'script', 'nav', 'footer', 'header']):
            data.decompose()
            
        # Preserve links so the LLM can extract PDF URLs
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('/'):
                if source_name == "arXiv":
                    href = f"https://arxiv.org{href}"
                elif source_name == "Scopus":
                    href = f"https://www.scopus.com{href}"
                elif source_name == "Web of Science":
                    href = f"https://www.webofscience.com{href}"
            a.replace_with(f"{a.text} [URL: {href}]")
            
        cleaned_html = ' '.join(soup.stripped_strings)
        text_content = cleaned_html[:15000] 

        prompt = f"""
        You are a web scraping AI. I will provide you with the raw text extracted from a search results page on {source_name}.
        Your task is to extract all the scientific articles you can find in the text.
        For each article, extract:
        - title
        - authors (comma separated)
        - doi (or article ID if DOI is missing)
        - year of publication (integer)
        - abstract (the summary of the text). If not found, output "No Abstract".
        - pdf_url (the direct URL to download the PDF, if available). If not found, output "No PDF".
        
        Respond ONLY with valid JSON conforming to the requested schema.
        
        TEXT:
        {text_content}
        """
        
        try:
            response = self.client.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                format=ArticleListSchema.model_json_schema(),
                options={"temperature": 0.0}
            )
            
            result_content = response.get('message', {}).get('content', '')
            if not result_content:
                raise ValueError("Empty response from Ollama")
                
            parsed_data = json.loads(result_content)
            articles = parsed_data.get('articles', [])
            
            logger.info(f"AI extracted {len(articles)} articles from {source_name}.")
            self.total_extracted += len(articles)
            
            for art in articles:
                if art.get('doi') and art.get('title'):
                    self.db_manager.insert_article(
                        art.get('doi'), 
                        art.get('title'), 
                        art.get('authors', 'Unknown'), 
                        art.get('year', 0), 
                        art.get('abstract', 'No Abstract'),
                        art.get('pdf_url', 'No PDF')
                    )
        except Exception as e:
            logger.error(f"Error during AI parsing of {source_name}: {e}")

    def fetch_arxiv(self, page):
        base_url = "https://arxiv.org/search/advanced"
        for term in SEARCH_TERMS:
            query = term.replace(" ", "+")
            url = f"{base_url}?advanced=&terms-0-operator=AND&terms-0-term={query}&terms-0-field=all&classification-physics_archives=all&classification-include_cross_list=include&date-filter_by=all_dates&date-year=&date-from_date=&date-to_date=&date-date_type=submitted_date&abstracts=show&size=50&order=-announced_date_first"
            
            logger.info(f"Fetching arXiv HTML for term: {term}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)
                self._ai_parse_html(page.content(), "arXiv")
                time.sleep(3) 
            except PlaywrightTimeoutError:
                logger.error(f"Timeout loading arXiv page for term: {term}")
            except Exception as e:
                logger.error(f"Error fetching HTML from arXiv: {e}")

    def fetch_scopus(self, page):
        base_url = "https://www.scopus.com/results/results.uri"
        for term in SEARCH_TERMS:
            logger.info(f"Fetching Scopus HTML for term: {term}")
            query = term.replace(" ", "+")
            url = f"{base_url}?sort=plf-f&src=s&sot=b&sdt=b&s=TITLE-ABS-KEY({query})"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)
                self._ai_parse_html(page.content(), "Scopus")
                time.sleep(3)
            except PlaywrightTimeoutError:
                logger.error(f"Timeout loading Scopus page for term: {term}")
            except Exception as e:
                logger.error(f"Error fetching HTML from Scopus: {e}")

    def fetch_wos(self, page):
        base_url = "https://www.webofscience.com/wos/woscc/summary"
        for term in SEARCH_TERMS:
            logger.info(f"Fetching Web of Science HTML for term: {term}")
            query = term.replace(" ", "+")
            url = f"{base_url}?search_mode=GeneralSearch&query={query}"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                # Sometimes WoS requires extra time to render React elements
                page.wait_for_timeout(3000)
                self._ai_parse_html(page.content(), "Web of Science")
                time.sleep(3)
            except PlaywrightTimeoutError:
                logger.error(f"Timeout loading WoS page for term: {term}")
            except Exception as e:
                logger.error(f"Error fetching HTML from WoS: {e}")

    def fetch_elibrary(self, page):
        base_url = "https://elibrary.ru/query_results.asp"
        logger.info("Fetching eLibrary HTML...")
        try:
            page.goto(base_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            self._ai_parse_html(page.content(), "eLibrary")
            time.sleep(3)
        except PlaywrightTimeoutError:
            logger.error("Timeout loading eLibrary page")
        except Exception as e:
            logger.error(f"Error fetching HTML from eLibrary: {e}")

    def run(self):
        logger.info("Fetcher agent (Playwright + AI Parser Mode) starting...")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    viewport={"width": 1920, "height": 1080}
                )
                page = context.new_page()
                
                self.fetch_arxiv(page)
                self.fetch_scopus(page)
                self.fetch_wos(page)
                self.fetch_elibrary(page)
                
                browser.close()
        except Exception as e:
            logger.error(f"Fatal error running Playwright: {e}")
            
        logger.info("=" * 60)
        logger.info(f"🎯 FETCHING PHASE COMPLETE")
        logger.info(f"📊 TOTAL ARTICLES EXTRACTED IN THIS RUN: {self.total_extracted}")
        logger.info("=" * 60)
        logger.info("Fetcher agent finished.")
