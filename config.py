import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://admin:admin_password@localhost:5432/papers_db")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# Search terms for arXiv and other platforms
SEARCH_TERMS = [
    'water dissociation membrane',
    'water splitting electrodialysis',
    'overlimiting current',
    'second Wien effect'
]
