import psycopg2
from psycopg2 import pool
from psycopg2.extras import Json
import logging
from config import DATABASE_URL

logger = logging.getLogger(__name__)

class DBManager:
    def __init__(self):
        try:
            self.connection_pool = psycopg2.pool.ThreadedConnectionPool(1, 10, DATABASE_URL)
            logger.info("Connection pool created successfully")
        except Exception as e:
            logger.error(f"Error creating connection pool: {e}")
            raise

    def get_connection(self):
        return self.connection_pool.getconn()

    def release_connection(self, conn):
        self.connection_pool.putconn(conn)

    def insert_article(self, doi, title, authors, year, abstract):
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO articles (doi, title, authors, year, abstract, status)
                    VALUES (%s, %s, %s, %s, %s, 'new')
                    ON CONFLICT (doi) DO NOTHING
                    RETURNING id;
                """, (doi, title, authors, year, abstract))
                conn.commit()
                return cursor.fetchone()
        except Exception as e:
            conn.rollback()
            logger.error(f"Error inserting article: {e}")
        finally:
            self.release_connection(conn)

    def get_articles_by_status(self, status):
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id, doi, title, authors, year, abstract, full_text_path, analysis_results FROM articles WHERE status = %s", (status,))
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error fetching articles: {e}")
            return []
        finally:
            self.release_connection(conn)

    def update_article_status(self, article_id, status, relevance_score=None, rolling_summary=None):
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                if rolling_summary is not None:
                    json_data = Json({"rolling_summary": rolling_summary})
                    if relevance_score is not None:
                        cursor.execute("""
                            UPDATE articles SET status = %s, relevance_score = %s, analysis_results = %s WHERE id = %s
                        """, (status, relevance_score, json_data, article_id))
                    else:
                        cursor.execute("""
                            UPDATE articles SET status = %s, analysis_results = %s WHERE id = %s
                        """, (status, json_data, article_id))
                else:
                    if relevance_score is not None:
                        cursor.execute("""
                            UPDATE articles SET status = %s, relevance_score = %s WHERE id = %s
                        """, (status, relevance_score, article_id))
                    else:
                        cursor.execute("""
                            UPDATE articles SET status = %s WHERE id = %s
                        """, (status, article_id))
                conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Error updating article status: {e}")
        finally:
            self.release_connection(conn)

    def update_analysis_results(self, article_id, analysis_results):
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE articles SET analysis_results = %s, status = 'analyzed' WHERE id = %s
                """, (Json(analysis_results), article_id))
                conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Error updating analysis results: {e}")
        finally:
            self.release_connection(conn)

    def update_full_text_path(self, article_id, path):
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE articles SET full_text_path = %s WHERE id = %s", (path, article_id))
                conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Error updating full text path: {e}")
        finally:
            self.release_connection(conn)
