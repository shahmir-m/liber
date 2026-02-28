"""Embedding generation and storage using OpenAI + pgvector."""

from typing import Optional

import numpy as np
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import MetricsCollector
from app.db.models import Book, BookEmbedding
from app.services.cache import cache_get, cache_set, make_embedding_key

logger = get_logger(__name__)

_openai_client: Optional[AsyncOpenAI] = None


def _get_openai() -> AsyncOpenAI:
    """Get or create the OpenAI client."""
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client


def build_embedding_text(book: Book) -> str:
    """Build the text to embed for a book (metadata + review summaries)."""
    parts = [f"Title: {book.title}"]
    if book.authors:
        parts.append(f"Authors: {', '.join(book.authors)}")
    if book.subjects:
        parts.append(f"Subjects: {', '.join(book.subjects[:10])}")
    if book.description:
        # Truncate description to save tokens
        parts.append(f"Description: {book.description[:500]}")
    if book.reviews:
        review_texts = [r.review_text[:300] for r in book.reviews[:5]]
        parts.append(f"Reviews: {' | '.join(review_texts)}")
    return " ".join(parts)


async def generate_embedding(
    text: str,
    metrics: Optional[MetricsCollector] = None,
) -> list[float]:
    """Generate an embedding vector for the given text."""
    client = _get_openai()
    response = await client.embeddings.create(
        model=settings.embedding_model,
        input=text,
    )
    if metrics:
        metrics.record_token_usage(
            model=settings.embedding_model,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=0,
        )
    return response.data[0].embedding


async def generate_embeddings_batch(
    texts: list[str],
    metrics: Optional[MetricsCollector] = None,
) -> list[list[float]]:
    """Generate embeddings for a batch of texts."""
    if not texts:
        return []
    client = _get_openai()
    response = await client.embeddings.create(
        model=settings.embedding_model,
        input=texts,
    )
    if metrics:
        metrics.record_token_usage(
            model=settings.embedding_model,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=0,
        )
    return [item.embedding for item in response.data]


async def get_or_create_embedding(
    db: AsyncSession,
    book: Book,
    metrics: Optional[MetricsCollector] = None,
) -> list[float]:
    """Get a cached embedding or create a new one."""
    # Check Redis cache first
    cache_key = make_embedding_key(book.id)
    cached = await cache_get(cache_key)
    if cached is not None:
        if metrics:
            metrics.record_embedding_hit()
        return cached["embedding"]

    # Check database
    stmt = select(BookEmbedding).where(BookEmbedding.book_id == book.id)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing is not None:
        if isinstance(existing.embedding, np.ndarray):
            embedding_list = existing.embedding.tolist()
        else:
            embedding_list = list(existing.embedding)
        await cache_set(cache_key, {"embedding": embedding_list}, ttl=86400)
        if metrics:
            metrics.record_embedding_hit()
        return embedding_list

    # Generate new embedding
    if metrics:
        metrics.record_embedding_miss()
    text = build_embedding_text(book)
    embedding = await generate_embedding(text, metrics)

    # Store in database
    book_embedding = BookEmbedding(
        book_id=book.id,
        embedding=embedding,
        text_content=text,
    )
    db.add(book_embedding)
    await db.flush()

    # Cache in Redis
    await cache_set(cache_key, {"embedding": embedding}, ttl=86400)

    return embedding
