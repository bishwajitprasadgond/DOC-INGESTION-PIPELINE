from functools import lru_cache

from sentence_transformers import SentenceTransformer

import config


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    return SentenceTransformer(config.EMBEDDINGS_CONFIG["model_name"], device=config.EMBEDDINGS_CONFIG["device"])


def embed_row(question: str, answer: str) -> list[float]:
    model = get_embedding_model()
    vector = model.encode(f"{question}\n{answer}")
    return vector.tolist()
