"""Open Library + Google Books API clients for book metadata."""

from typing import Any, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

OPEN_LIBRARY_SEARCH_URL = "https://openlibrary.org/search.json"
OPEN_LIBRARY_WORKS_URL = "https://openlibrary.org/works"
GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def search_open_library(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search Open Library for books matching a query."""
    async with httpx.AsyncClient(timeout=settings.scraper_timeout) as client:
        response = await client.get(
            OPEN_LIBRARY_SEARCH_URL,
            params={
                "q": query,
                "limit": limit,
                "fields": (
                    "key,title,author_name,subject,isbn,"
                    "first_publish_year,cover_i,"
                    "number_of_pages_median,ratings_average"
                ),
            },
        )
        response.raise_for_status()
        data = response.json()
        results = []
        for doc in data.get("docs", []):
            results.append({
                "title": doc.get("title", ""),
                "authors": doc.get("author_name", []),
                "subjects": (doc.get("subject") or [])[:20],
                "isbn_13": _first_isbn13(doc.get("isbn", [])),
                "isbn_10": _first_isbn10(doc.get("isbn", [])),
                "open_library_key": doc.get("key", ""),
                "publish_year": doc.get("first_publish_year"),
                "page_count": doc.get("number_of_pages_median"),
                "average_rating": doc.get("ratings_average"),
                "cover_url": f"https://covers.openlibrary.org/b/id/{doc['cover_i']}-L.jpg"
                if doc.get("cover_i")
                else None,
                "source": "open_library",
            })
        return results


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def get_open_library_description(work_key: str) -> Optional[str]:
    """Fetch the description for a work from Open Library."""
    async with httpx.AsyncClient(timeout=settings.scraper_timeout) as client:
        url = f"https://openlibrary.org{work_key}.json"
        response = await client.get(url)
        if response.status_code != 200:
            return None
        data = response.json()
        desc = data.get("description")
        if isinstance(desc, dict):
            return desc.get("value", "")
        return desc if isinstance(desc, str) else None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def search_google_books(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search Google Books API as a fallback."""
    params: dict[str, Any] = {"q": query, "maxResults": limit}
    if settings.google_books_api_key:
        params["key"] = settings.google_books_api_key

    async with httpx.AsyncClient(timeout=settings.scraper_timeout) as client:
        response = await client.get(GOOGLE_BOOKS_URL, params=params)
        response.raise_for_status()
        data = response.json()
        results = []
        for item in data.get("items", []):
            vol = item.get("volumeInfo", {})
            identifiers = {
                i.get("type"): i.get("identifier")
                for i in vol.get("industryIdentifiers", [])
            }
            results.append({
                "title": vol.get("title", ""),
                "authors": vol.get("authors", []),
                "subjects": vol.get("categories", []),
                "description": vol.get("description"),
                "isbn_13": identifiers.get("ISBN_13"),
                "isbn_10": identifiers.get("ISBN_10"),
                "google_books_id": item.get("id"),
                "cover_url": vol.get("imageLinks", {}).get("thumbnail"),
                "publish_year": _parse_year(vol.get("publishedDate", "")),
                "page_count": vol.get("pageCount"),
                "average_rating": vol.get("averageRating"),
                "source": "google_books",
            })
        return results


async def search_books(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search for books using Open Library, falling back to Google Books."""
    try:
        results = await search_open_library(query, limit)
        if results:
            # Try to enrich with descriptions
            for r in results:
                if r.get("open_library_key") and not r.get("description"):
                    desc = await get_open_library_description(r["open_library_key"])
                    r["description"] = desc
            return results
    except Exception as e:
        logger.warning("open_library_search_failed", query=query, error=str(e))

    try:
        return await search_google_books(query, limit)
    except Exception as e:
        logger.error("all_book_search_failed", query=query, error=str(e))
        return []


def _first_isbn13(isbns: list[str]) -> Optional[str]:
    """Extract the first ISBN-13 from a list."""
    for isbn in isbns:
        if len(isbn) == 13 and isbn.isdigit():
            return isbn
    return None


def _first_isbn10(isbns: list[str]) -> Optional[str]:
    """Extract the first ISBN-10 from a list."""
    for isbn in isbns:
        if len(isbn) == 10:
            return isbn
    return None


def _parse_year(date_str: str) -> Optional[int]:
    """Parse a year from a date string like '2024' or '2024-01-15'."""
    if not date_str:
        return None
    try:
        return int(date_str[:4])
    except (ValueError, IndexError):
        return None
