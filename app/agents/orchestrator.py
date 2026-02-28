"""Agent Orchestrator.

Coordinates the 3-agent pipeline:
  1. Taste Profiler → taste profile
  2. Candidate Retriever → top-N candidates via vector search
  3. Explanation Generator → explainable recommendations

Tracks metrics throughout and caches results.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.candidate_retriever import retrieve_candidates
from app.agents.explanation_generator import generate_explanations
from app.agents.taste_profiler import profile_taste
from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import create_metrics, global_metrics
from app.models.schemas import (
    BookMetadata,
    RecommendationItem,
    RecommendationResponse,
)
from app.services.cache import cache_get, cache_set, make_recommendation_key

logger = get_logger(__name__)


async def get_recommendations(
    db: AsyncSession,
    favorite_books: list[str],
    num_recommendations: int = 10,
) -> RecommendationResponse:
    """Run the full recommendation pipeline.

    1. Check cache for existing recommendations
    2. Run Taste Profiler agent
    3. Run Candidate Retriever agent
    4. Run Explanation Generator agent
    5. Cache and return results
    """
    request_id = str(uuid.uuid4())[:8]
    metrics = create_metrics(request_id)

    # Check cache
    cache_key = make_recommendation_key(favorite_books, num_recommendations)
    cached = await cache_get(cache_key)
    if cached is not None:
        logger.info("recommendation_cache_hit", request_id=request_id)
        return RecommendationResponse(**cached)

    logger.info(
        "recommendation_pipeline_start",
        request_id=request_id,
        books=favorite_books,
        n=num_recommendations,
    )

    # Agent 1: Taste Profiler
    taste_profile = await profile_taste(db, favorite_books, metrics)

    # Agent 2: Candidate Retriever
    candidates = await retrieve_candidates(
        db,
        taste_profile,
        top_n=num_recommendations,
        exclude_titles=favorite_books,
        metrics=metrics,
    )

    # Agent 3: Explanation Generator
    explanations = await generate_explanations(taste_profile, candidates, metrics)

    # Build response
    recommendation_items: list[RecommendationItem] = []
    for book, score in candidates:
        book_meta = BookMetadata(
            id=book.id,
            title=book.title,
            authors=book.authors,
            subjects=book.subjects,
            description=book.description,
            isbn_13=book.isbn_13,
            isbn_10=book.isbn_10,
            open_library_key=book.open_library_key,
            google_books_id=book.google_books_id,
            cover_url=book.cover_url,
            publish_year=book.publish_year,
            page_count=book.page_count,
            average_rating=book.average_rating,
            created_at=book.created_at,
        )
        recommendation_items.append(
            RecommendationItem(
                book=book_meta,
                score=round(score, 4),
                explanation=explanations.get(book.id, "Recommended based on your taste profile."),
            )
        )

    response = RecommendationResponse(
        recommendations=recommendation_items,
        taste_profile=taste_profile,
        metrics=metrics.summary(),
    )

    # Cache the response
    await cache_set(
        cache_key,
        response.model_dump(),
        ttl=settings.recommendation_cache_ttl,
    )

    # Record global metrics
    global_metrics.record(metrics)

    logger.info(
        "recommendation_pipeline_complete",
        request_id=request_id,
        num_results=len(recommendation_items),
        latency=round(metrics.total_latency, 3),
        tokens=metrics.total_tokens,
    )

    return response
