from functools import lru_cache

from sentence_transformers import SentenceTransformer

from ...config import settings


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    return SentenceTransformer(settings.embeddings.model_name, device=settings.embeddings.device)


def embed_row(question: str, answer: str) -> list[float]:
    model = get_embedding_model()
    vector = model.encode(f"{question}\n{answer}")
    return vector.tolist()
