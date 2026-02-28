"""Redis cache layer for recommendations, embeddings, and taste profiles."""

import json
from typing import Any, Optional

import redis.asyncio as redis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_redis_client: Optional[redis.Redis] = None


async def get_redis() -> redis.Redis:
    """Get or create the Redis client."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
    return _redis_client


async def close_redis() -> None:
    """Close the Redis connection."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None


async def cache_get(key: str) -> Optional[dict[str, Any]]:
    """Get a cached value by key."""
    client = await get_redis()
    try:
        value = await client.get(key)
        if value is not None:
            return json.loads(value)
    except Exception as e:
        logger.warning("cache_get_error", key=key, error=str(e))
    return None


async def cache_set(key: str, value: dict[str, Any], ttl: int = 3600) -> None:
    """Set a cached value with TTL in seconds."""
    client = await get_redis()
    try:
        await client.set(key, json.dumps(value, default=str), ex=ttl)
    except Exception as e:
        logger.warning("cache_set_error", key=key, error=str(e))


async def cache_delete(key: str) -> None:
    """Delete a cached value."""
    client = await get_redis()
    try:
        await client.delete(key)
    except Exception as e:
        logger.warning("cache_delete_error", key=key, error=str(e))


def make_taste_profile_key(book_titles: list[str]) -> str:
    """Generate a cache key for a taste profile."""
    sorted_titles = sorted(t.lower().strip() for t in book_titles)
    return f"taste_profile:{'|'.join(sorted_titles)}"


def make_recommendation_key(book_titles: list[str], n: int) -> str:
    """Generate a cache key for recommendations."""
    sorted_titles = sorted(t.lower().strip() for t in book_titles)
    return f"recommendations:{n}:{'|'.join(sorted_titles)}"


def make_embedding_key(book_id: int) -> str:
    """Generate a cache key for a book embedding."""
    return f"embedding:{book_id}"


async def redis_health_check() -> bool:
    """Check if Redis is reachable."""
    try:
        client = await get_redis()
        await client.ping()
        return True
    except Exception:
        return False
