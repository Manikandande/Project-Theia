from pathlib import Path
from pydantic_settings import BaseSettings


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # Paths
    data_dir: Path = BASE_DIR / "data"
    chroma_dir: Path = BASE_DIR / "chroma_store"
    audit_log_path: Path = BASE_DIR / "audit.db"

    # Database files
    chinook_db: Path = BASE_DIR / "data" / "chinook.db"
    northwind_db: Path = BASE_DIR / "data" / "northwind.db"
    sakila_db: Path = BASE_DIR / "data" / "sakila.db"
    world_db: Path = BASE_DIR / "data" / "world.db"
    healthcare_db: Path = BASE_DIR / "data" / "healthcare.db"

    # Schema aliases (used in cross-database queries and Theia responses)
    schema_aliases: dict = {
        "music": "chinook.db",
        "sales": "northwind.db",
        "rental": "sakila.db",
        "geography": "world.db",
        "healthcare": "healthcare.db",
    }

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    llm_model: str = "llama3.1:8b"
    embed_model: str = "nomic-embed-text"

    # RAG
    retriever_top_k: int = 5
    chunk_size: int = 512
    chunk_overlap: int = 64

    # Security
    max_sql_rows: int = 1000
    read_only: bool = True

    class Config:
        env_prefix = "THEIA_"
        env_file = BASE_DIR / ".env"
        env_file_encoding = "utf-8"


settings = Settings()
