import os
import tomllib
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parent / "config.toml"

with _CONFIG_PATH.open("rb") as f:
    _raw = tomllib.load(f)

_llm = _raw.get("llm", {})
_chunking = _raw.get("chunking", {})
_embeddings = _raw.get("embeddings", {})
_elasticsearch = _raw.get("elasticsearch", {})

LLM_CONFIG = {
    "id": _llm.get("id", "gemma_4_31b"),
    "name": _llm.get("name", "Gemma-4 31B (vLLM)"),
    "base_url": os.environ.get("LLM_BASE_URL", _llm.get("base_url")),
    "api_key": os.environ.get("LLM_API_KEY", _llm.get("api_key")),
    "model_name": os.environ.get("LLM_MODEL", _llm.get("model_name")),
    "max_tokens": _llm.get("max_tokens", 1024),
    "temperature": _llm.get("temperature", 0.2),
    "timeout": _llm.get("timeout", 60.0),
}

CHUNK_MAX_CHARS = _chunking.get("chunk_max_chars", 3000)
QUESTIONS_PER_CHUNK = _chunking.get("questions_per_chunk", 3)
METADATA_SAMPLE_CHARS = _chunking.get("metadata_sample_chars", 4000)

EMBEDDINGS_CONFIG = {
    "model_name": _embeddings.get("model_name", "sentence-transformers/all-MiniLM-L6-v2"),
    "dimension": _embeddings.get("dimension", 384),
    "device": _embeddings.get("device", "cpu"),
}

ELASTICSEARCH_CONFIG = {
    "enabled": _elasticsearch.get("enabled", False),
    "host": os.environ.get("ELASTICSEARCH__HOST", _elasticsearch.get("host", "https://localhost:9200")),
    "api_key": os.environ.get("ELASTICSEARCH__API_KEY", _elasticsearch.get("api_key", "")),
    "index_name": _elasticsearch.get("index_name", "docs-qa"),
    "index_mode": _elasticsearch.get("index_mode", "create"),
    "fields": _elasticsearch.get("fields", []),
    "request_timeout": _elasticsearch.get("request_timeout", 30),
    "max_retries": _elasticsearch.get("max_retries", 3),
    "retry_on_timeout": _elasticsearch.get("retry_on_timeout", True),
    "verify_certs": _elasticsearch.get("verify_certs", True),
    "connections_per_node": _elasticsearch.get("connections_per_node", 10),
}
