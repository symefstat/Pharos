import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    # ── Supabase ────────────────────────────────────────────────────────────────
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_KEY')          # service-role key (read + write)

    # ── Toqan API ────────────────────────────────────────────────────────────────
    # Per-feed agent API keys + names live in feeds.py (the Feed registry); only
    # the shared base URL stays here.
    TOQAN_API_URL = os.getenv("TOQAN_API_URL", "https://api.toqan.ai")

    # ── MOT knowledge base (RAG) ──────────────────────────────────────────────────
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large")
    EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "2000"))  # fits pgvector HNSW
    MOT_KB_TABLE = "mot_knowledge_base"
    MOT_CHUNK_CHARS = 2400
    MOT_CHUNK_OVERLAP = 240
    NEWS_EMB_TABLE = "news_embeddings"  # pgvector store for recent-news retrieval (Ask)

    # ── Home News storage / pruning ───────────────────────────────────────────────
    HOME_NEWS_TABLE = "home_news_articles"
    HOME_NEWS_MAX_AGE_DAYS = 14  # prune rows older than this on each run
    HOME_NEWS_IMAGE_BUCKET = "home-news-images"  # Supabase Storage bucket for proxied article images
    HOME_NEWS_IMAGE_MAX_BYTES = 2 * 1024 * 1024  # 2 MB cap per image

    @classmethod
    def validate(cls):
        """Validate that all required config values are present."""
        required = ['SUPABASE_URL', 'SUPABASE_KEY']
        missing = [key for key in required if not getattr(cls, key)]
        if missing:
            raise ValueError(f"Missing required configuration: {', '.join(missing)}")
        return True
