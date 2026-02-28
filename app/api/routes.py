"""FastAPI route definitions."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.orchestrator import get_recommendations
from app.core.logging import get_logger
from app.core.metrics import global_metrics
from app.db.models import Book, Review, ScrapeLog
from app.db.session import get_db
from app.models.schemas import (
    BookMetadata,
    BookSearchRequest,
    HealthResponse,
    MetricsResponse,
    RecommendationRequest,
    RecommendationResponse,
    ScrapeRequest,
)
from app.scrapers.reviews import scrape_reviews
from app.services.cache import redis_health_check
from app.services.embedding import get_or_create_embedding
from app.services.metadata import search_books

logger = get_logger(__name__)

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    """Health check endpoint."""
    # Check database
    db_status = "healthy"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_status = "unhealthy"

    # Check Redis
    redis_ok = await redis_health_check()

    return HealthResponse(
        status="healthy" if db_status == "healthy" and redis_ok else "degraded",
        version="0.1.0",
        database=db_status,
        redis="healthy" if redis_ok else "unhealthy",
    )


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics() -> MetricsResponse:
    """Return aggregate performance metrics."""
    summary = global_metrics.summary()
    return MetricsResponse(**summary)


@router.post("/recommendations", response_model=RecommendationResponse)
async def recommend_books(
    request: RecommendationRequest,
    db: AsyncSession = Depends(get_db),
) -> RecommendationResponse:
    """Get book recommendations based on favorite books.

    Runs the 3-agent pipeline:
    1. Taste Profiler
    2. Candidate Retriever
    3. Explanation Generator
    """
    try:
        response = await get_recommendations(
            db,
            request.favorite_books,
            request.num_recommendations,
        )
        return response
    except Exception as e:
        logger.error("recommendation_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Recommendation failed: {str(e)}")


@router.post("/books/search", response_model=list[BookMetadata])
async def search_and_ingest_books(
    request: BookSearchRequest,
    db: AsyncSession = Depends(get_db),
) -> list[BookMetadata]:
    """Search for books via APIs and ingest into the database."""
    api_results = await search_books(request.query, limit=5)

    ingested: list[BookMetadata] = []
    for result in api_results:
        # Check if book already exists
        existing = None
        if result.get("isbn_13"):
            stmt = select(Book).where(Book.isbn_13 == result["isbn_13"])
            res = await db.execute(stmt)
            existing = res.scalar_one_or_none()
        if not existing and result.get("open_library_key"):
            stmt = select(Book).where(Book.open_library_key == result["open_library_key"])
            res = await db.execute(stmt)
            existing = res.scalar_one_or_none()

        if existing:
            book = existing
        else:
            book = Book(
                title=result["title"],
                authors=result.get("authors", []),
                subjects=result.get("subjects", []),
                description=result.get("description"),
                isbn_13=result.get("isbn_13"),
                isbn_10=result.get("isbn_10"),
                open_library_key=result.get("open_library_key"),
                google_books_id=result.get("google_books_id"),
                cover_url=result.get("cover_url"),
                publish_year=result.get("publish_year"),
                page_count=result.get("page_count"),
                average_rating=result.get("average_rating"),
                raw_metadata=result,
            )
            db.add(book)
            await db.flush()

        ingested.append(BookMetadata(
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
        ))

    await db.commit()
    return ingested


@router.post("/books/{book_id}/scrape")
async def scrape_book_reviews(
    book_id: int,
    request: ScrapeRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Scrape reviews for a book and store them."""
    # Get book
    stmt = select(Book).where(Book.id == book_id)
    result = await db.execute(stmt)
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Scrape reviews
    author = book.authors[0] if book.authors else ""
    reviews_data = await scrape_reviews(book.title, author, request.max_reviews)

    # Store reviews
    stored_count = 0
    for review_data in reviews_data:
        review = Review(
            book_id=book.id,
            source=review_data["source"],
            review_text=review_data["review_text"],
            rating=review_data.get("rating"),
            reviewer=review_data.get("reviewer"),
            raw_html=review_data.get("raw_html"),
        )
        db.add(review)
        stored_count += 1

    # Log scrape operation
    scrape_log = ScrapeLog(
        book_id=book.id,
        source="goodreads",
        status="success" if stored_count > 0 else "partial",
        reviews_found=stored_count,
    )
    db.add(scrape_log)
    await db.commit()

    return {
        "book_id": book.id,
        "reviews_scraped": stored_count,
        "status": "success" if stored_count > 0 else "no_reviews_found",
    }


@router.post("/books/{book_id}/embed")
async def embed_book(
    book_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Generate and store an embedding for a book."""
    stmt = (
        select(Book)
        .options(selectinload(Book.reviews))
        .where(Book.id == book_id)
    )
    result = await db.execute(stmt)
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    embedding = await get_or_create_embedding(db, book)
    await db.commit()

    return {
        "book_id": book.id,
        "embedding_dimensions": len(embedding),
        "status": "success",
    }


@router.get("/books", response_model=list[BookMetadata])
async def list_books(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> list[BookMetadata]:
    """List books in the database."""
    stmt = select(Book).offset(offset).limit(limit).order_by(Book.created_at.desc())
    result = await db.execute(stmt)
    books = result.scalars().all()

    return [
        BookMetadata(
            id=b.id,
            title=b.title,
            authors=b.authors,
            subjects=b.subjects,
            description=b.description,
            isbn_13=b.isbn_13,
            isbn_10=b.isbn_10,
            open_library_key=b.open_library_key,
            google_books_id=b.google_books_id,
            cover_url=b.cover_url,
            publish_year=b.publish_year,
            page_count=b.page_count,
            average_rating=b.average_rating,
            created_at=b.created_at,
        )
        for b in books
    ]
