CREATE TABLE IF NOT EXISTS articles (
    id SERIAL PRIMARY KEY,
    doi TEXT UNIQUE,
    title TEXT,
    authors TEXT,
    year INTEGER,
    abstract TEXT,
    status TEXT DEFAULT 'new',
    relevance_score INTEGER,
    full_text_path TEXT,
    analysis_results JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
