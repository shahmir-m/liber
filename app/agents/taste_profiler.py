"""Agent 1: Taste Profiler.

Takes 3-5 favorite books and generates a structured taste profile
using cached embeddings and API metadata. Optional LLM call to summarize.
"""

import json
from typing import Optional

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import MetricsCollector
from app.db.models import Book
from app.models.schemas import TasteProfile
from app.services.cache import cache_get, cache_set, make_taste_profile_key
from app.services.metadata import search_books

logger = get_logger(__name__)

TASTE_PROFILE_PROMPT = """Analyze these favorite books and create a concise taste profile.

Books:
{books_json}

Return a JSON object with exactly these fields:
- preferred_genres: list of 3-5 genres
- preferred_themes: list of 3-5 themes
- preferred_authors: list of author names from the input
- reading_style: one sentence describing reading preferences
- summary: 2-3 sentence summary of overall taste

Return ONLY valid JSON, no other text."""


async def profile_taste(
    db: AsyncSession,
    favorite_books: list[str],
    metrics: Optional[MetricsCollector] = None,
) -> TasteProfile:
    """Generate a taste profile from favorite book titles.

    1. Check cache for existing profile
    2. Look up books via API metadata
    3. Use LLM to summarize taste profile
    4. Cache and return
    """
    # Check cache
    cache_key = make_taste_profile_key(favorite_books)
    cached = await cache_get(cache_key)
    if cached is not None:
        logger.info("taste_profile_cache_hit", books=favorite_books)
        return TasteProfile(**cached)

    if metrics:
        metrics.start_timer("taste_profiler")

    # Resolve books: search DB first, then APIs
    resolved_books: list[dict] = []
    for title in favorite_books:
        # Check DB
        stmt = select(Book).where(Book.title.ilike(f"%{title}%")).limit(1)
        result = await db.execute(stmt)
        book = result.scalar_one_or_none()

        if book:
            resolved_books.append({
                "title": book.title,
                "authors": book.authors,
                "subjects": book.subjects[:10],
                "description": (book.description or "")[:300],
            })
        else:
            # Search via APIs
            api_results = await search_books(title, limit=1)
            if api_results:
                r = api_results[0]
                resolved_books.append({
                    "title": r["title"],
                    "authors": r.get("authors", []),
                    "subjects": (r.get("subjects") or [])[:10],
                    "description": (r.get("description") or "")[:300],
                })
            else:
                resolved_books.append({
                    "title": title,
                    "authors": [],
                    "subjects": [],
                    "description": "",
                })

    # Generate taste profile via LLM
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    books_json = json.dumps(resolved_books, indent=2)

    response = await client.chat.completions.create(
        model=settings.summarization_model,
        messages=[
            {"role": "system", "content": "You are a book taste analyst. Return only valid JSON."},
            {"role": "user", "content": TASTE_PROFILE_PROMPT.format(books_json=books_json)},
        ],
        temperature=0.3,
        max_tokens=500,
        response_format={"type": "json_object"},
    )

    if metrics:
        metrics.record_token_usage(
            model=settings.summarization_model,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
        )

    # Parse response
    raw = response.choices[0].message.content or "{}"
    profile_data = json.loads(raw)
    profile = TasteProfile(
        preferred_genres=profile_data.get("preferred_genres", []),
        preferred_themes=profile_data.get("preferred_themes", []),
        preferred_authors=profile_data.get("preferred_authors", []),
        reading_style=profile_data.get("reading_style", ""),
        summary=profile_data.get("summary", ""),
    )

    # Cache the profile
    await cache_set(cache_key, profile.model_dump(), ttl=settings.taste_profile_cache_ttl)

    if metrics:
        metrics.stop_timer("taste_profiler")

    logger.info("taste_profile_generated", books=favorite_books)
    return profile
