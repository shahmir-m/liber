"""Seed script: search, ingest, and embed books to populate the database.

Usage:
    poetry run python scripts/seed.py

Searches Open Library for a curated list of popular books,
stores metadata in PostgreSQL, and generates embeddings in pgvector.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger, setup_logging
from app.db.models import Book
from app.db.session import async_session_factory, init_db
from app.services.embedding import get_or_create_embedding
from app.services.metadata import search_books

logger = get_logger(__name__)

# Curated seed list covering diverse genres
SEED_QUERIES = [
    "1984 George Orwell",
    "Pride and Prejudice Jane Austen",
    "The Great Gatsby F. Scott Fitzgerald",
    "To Kill a Mockingbird Harper Lee",
    "One Hundred Years of Solitude Gabriel Garcia Marquez",
    "The Hitchhiker's Guide to the Galaxy Douglas Adams",
    "Dune Frank Herbert",
    "The Name of the Wind Patrick Rothfuss",
    "Sapiens Yuval Noah Harari",
    "Thinking Fast and Slow Daniel Kahneman",
    "The Catcher in the Rye J.D. Salinger",
    "Brave New World Aldous Huxley",
    "The Lord of the Rings J.R.R. Tolkien",
    "Harry Potter and the Sorcerer's Stone J.K. Rowling",
    "Crime and Punishment Fyodor Dostoevsky",
    "The Road Cormac McCarthy",
    "Neuromancer William Gibson",
    "The Left Hand of Darkness Ursula K. Le Guin",
    "Beloved Toni Morrison",
    "The Alchemist Paulo Coelho",
    "Slaughterhouse-Five Kurt Vonnegut",
    "Fahrenheit 451 Ray Bradbury",
    "The Handmaid's Tale Margaret Atwood",
    "Blood Meridian Cormac McCarthy",
    "Norwegian Wood Haruki Murakami",
    "The Brothers Karamazov Fyodor Dostoevsky",
    "Catch-22 Joseph Heller",
    "The Color Purple Alice Walker",
    "Ender's Game Orson Scott Card",
    "The Martian Andy Weir",
]


async def seed() -> None:
    """Run the seed process."""
    setup_logging()
    await init_db()

    async with async_session_factory() as db:
        total_ingested = 0
        total_embedded = 0

        for query in SEED_QUERIES:
            logger.info("seeding_book", query=query)
            try:
                results = await search_books(query, limit=1)
                if not results:
                    logger.warning("no_results", query=query)
                    continue

                r = results[0]

                # Check if already exists
                existing = None
                if r.get("isbn_13"):
                    stmt = select(Book).where(Book.isbn_13 == r["isbn_13"])
                    res = await db.execute(stmt)
                    existing = res.scalar_one_or_none()

                if existing:
                    book = existing
                    logger.info("book_already_exists", title=book.title)
                else:
                    book = Book(
                        title=r["title"],
                        authors=r.get("authors", []),
                        subjects=r.get("subjects", []),
                        description=r.get("description"),
                        isbn_13=r.get("isbn_13"),
                        isbn_10=r.get("isbn_10"),
                        open_library_key=r.get("open_library_key"),
                        google_books_id=r.get("google_books_id"),
                        cover_url=r.get("cover_url"),
                        publish_year=r.get("publish_year"),
                        page_count=r.get("page_count"),
                        average_rating=r.get("average_rating"),
                        raw_metadata=r,
                    )
                    db.add(book)
                    await db.flush()
                    total_ingested += 1
                    logger.info("book_ingested", title=book.title)

                # Generate embedding
                stmt = (
                    select(Book)
                    .options(selectinload(Book.reviews))
                    .where(Book.id == book.id)
                )
                res = await db.execute(stmt)
                book_with_reviews = res.scalar_one()
                await get_or_create_embedding(db, book_with_reviews)
                total_embedded += 1

            except Exception as e:
                logger.error("seed_error", query=query, error=str(e))
                continue

        await db.commit()
        logger.info(
            "seed_complete",
            total_ingested=total_ingested,
            total_embedded=total_embedded,
        )


if __name__ == "__main__":
    asyncio.run(seed())
