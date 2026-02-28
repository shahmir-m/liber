"""Agent 2: Candidate Retriever.

Uses vector similarity search in pgvector to find top-N book candidates
that match the user's taste profile. Only top candidates are sent to the
explanation agent.
"""

from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import MetricsCollector
from app.db.models import Book
from app.models.schemas import TasteProfile
from app.services.embedding import generate_embedding

logger = get_logger(__name__)


async def retrieve_candidates(
    db: AsyncSession,
    taste_profile: TasteProfile,
    top_n: Optional[int] = None,
    exclude_titles: Optional[list[str]] = None,
    metrics: Optional[MetricsCollector] = None,
) -> list[tuple[Book, float]]:
    """Find top-N candidate books using vector similarity search.

    1. Build a query embedding from the taste profile
    2. Search pgvector for nearest neighbors
    3. Filter out input books
    4. Return ranked (book, score) pairs
    """
    if top_n is None:
        top_n = settings.candidate_top_n
    if exclude_titles is None:
        exclude_titles = []

    if metrics:
        metrics.start_timer("candidate_retriever")

    # Build a text representation of the taste profile for embedding
    profile_text = (
        f"Genres: {', '.join(taste_profile.preferred_genres)}. "
        f"Themes: {', '.join(taste_profile.preferred_themes)}. "
        f"Authors: {', '.join(taste_profile.preferred_authors)}. "
        f"{taste_profile.summary}"
    )

    # Generate embedding for the taste profile
    profile_embedding = await generate_embedding(profile_text, metrics)

    # Vector similarity search using pgvector's cosine distance
    # Lower distance = more similar; we convert to similarity score
    embedding_str = "[" + ",".join(str(x) for x in profile_embedding) + "]"

    query = text("""
        SELECT
            be.book_id,
            1 - (be.embedding <=> :embedding::vector) as similarity
        FROM book_embeddings be
        JOIN books b ON b.id = be.book_id
        ORDER BY be.embedding <=> :embedding::vector
        LIMIT :limit
    """)

    result = await db.execute(
        query,
        {"embedding": embedding_str, "limit": top_n + len(exclude_titles)},
    )
    rows = result.fetchall()

    # Load full book objects and filter exclusions
    candidates: list[tuple[Book, float]] = []
    exclude_lower = {t.lower().strip() for t in exclude_titles}

    for row in rows:
        book_id = row[0]
        similarity = float(row[1])

        stmt = (
            select(Book)
            .options(selectinload(Book.reviews))
            .where(Book.id == book_id)
        )
        book_result = await db.execute(stmt)
        book = book_result.scalar_one_or_none()

        if book and book.title.lower().strip() not in exclude_lower:
            candidates.append((book, similarity))

        if len(candidates) >= top_n:
            break

    if metrics:
        metrics.stop_timer("candidate_retriever")

    logger.info(
        "candidates_retrieved",
        count=len(candidates),
        top_n=top_n,
    )
    return candidates
