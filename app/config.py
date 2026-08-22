"""Application configuration loaded from environment variables."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/platform"

    # OpenSearch
    opensearch_url: str = "http://localhost:9200"
    opensearch_index: str = "chunks"

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "chunks"

    # Object cache — local filesystem (MinIO CE archived April 2026)
    # Mount ia_cache_data Docker volume to this path, or set to any writable dir locally
    object_cache_dir: str = "./ia_cache"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # LLM
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str = "https://api.openai.com/v1"

    # Embeddings
    embedding_model: str = "BAAI/bge-m3"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    # Internet Archive
    ia_base_url: str = "https://archive.org"
    cdx_rate_limit_rps: int = 1


settings = Settings()
