import os
import tomllib
from pathlib import Path

from pydantic import BaseModel

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.toml"


class LLMConfig(BaseModel):
    id: str = "gemma_4_31b"
    name: str = "Gemma-4 31B (vLLM)"
    base_url: str
    api_key: str
    model_name: str
    max_tokens: int = 1024
    temperature: float = 0.2
    timeout: float = 60.0


class ChunkingConfig(BaseModel):
    chunk_max_chars: int = 3000
    questions_per_chunk: int = 3
    metadata_sample_chars: int = 4000
    concurrency: int = 4


class EmbeddingsConfig(BaseModel):
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    dimension: int = 384
    device: str = "cpu"


class ElasticsearchConfig(BaseModel):
    enabled: bool = False
    host: str = "https://localhost:9200"
    api_key: str = ""
    index_name: str = "docs-qa"
    index_mode: str = "create"
    fields: list[str] = []
    request_timeout: int = 30
    max_retries: int = 3
    retry_on_timeout: bool = True
    verify_certs: bool = True
    connections_per_node: int = 10


class LoggingConfig(BaseModel):
    level: str = "INFO"
    dir: str = "logs"
    filename: str = "ingestion.log"
    max_bytes: int = 5_000_000
    backup_count: int = 3


class Settings(BaseModel):
    llm: LLMConfig
    chunking: ChunkingConfig = ChunkingConfig()
    embeddings: EmbeddingsConfig = EmbeddingsConfig()
    elasticsearch: ElasticsearchConfig = ElasticsearchConfig()
    logging: LoggingConfig = LoggingConfig()


def _load_settings() -> Settings:
    with _CONFIG_PATH.open("rb") as f:
        raw = tomllib.load(f)

    llm = dict(raw.get("llm", {}))
    llm["base_url"] = os.environ.get("LLM_BASE_URL", llm.get("base_url"))
    llm["api_key"] = os.environ.get("LLM_API_KEY", llm.get("api_key"))
    llm["model_name"] = os.environ.get("LLM_MODEL", llm.get("model_name"))

    elasticsearch = dict(raw.get("elasticsearch", {}))
    elasticsearch["host"] = os.environ.get("ELASTICSEARCH__HOST", elasticsearch.get("host", "https://localhost:9200"))
    elasticsearch["api_key"] = os.environ.get("ELASTICSEARCH__API_KEY", elasticsearch.get("api_key", ""))

    return Settings(
        llm=llm,
        chunking=raw.get("chunking", {}),
        embeddings=raw.get("embeddings", {}),
        elasticsearch=elasticsearch,
        logging=raw.get("logging", {}),
    )


settings = _load_settings()

# Repo root, for resolving paths (e.g. the logs/ folder) relative to the project rather than cwd.
PROJECT_ROOT = _CONFIG_PATH.parent
