"""SQLAlchemy ORM models for PostgreSQL + pgvector."""


from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, relationship

from app.core.config import settings


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class Book(Base):
    """Book metadata stored from Open Library / Google Books APIs."""

    __tablename__ = "books"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False, index=True)
    authors = Column(ARRAY(String), nullable=False, default=[])
    subjects = Column(ARRAY(String), nullable=False, default=[])
    description = Column(Text, nullable=True)
    isbn_13 = Column(String(13), nullable=True, unique=True, index=True)
    isbn_10 = Column(String(10), nullable=True, unique=True, index=True)
    open_library_key = Column(String(100), nullable=True, unique=True)
    google_books_id = Column(String(100), nullable=True, unique=True)
    cover_url = Column(String(500), nullable=True)
    publish_year = Column(Integer, nullable=True)
    page_count = Column(Integer, nullable=True)
    average_rating = Column(Float, nullable=True)
    raw_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    reviews = relationship("Review", back_populates="book", cascade="all, delete-orphan")
    embedding = relationship(
        "BookEmbedding", back_populates="book", uselist=False, cascade="all, delete-orphan"
    )


class Review(Base):
    """Scraped book reviews."""

    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, autoincrement=True)
    book_id = Column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    source = Column(String(50), nullable=False)  # e.g., "goodreads", "storygraph"
    review_text = Column(Text, nullable=False)
    rating = Column(Float, nullable=True)
    reviewer = Column(String(200), nullable=True)
    raw_html = Column(Text, nullable=True)  # stored for debugging
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    book = relationship("Book", back_populates="reviews")


class BookEmbedding(Base):
    """Vector embeddings for books (review summaries + metadata)."""

    __tablename__ = "book_embeddings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    book_id = Column(
        Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    embedding = Column(Vector(settings.embedding_dimensions), nullable=False)
    text_content = Column(Text, nullable=False)  # the text that was embedded
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    book = relationship("Book", back_populates="embedding")


class ScrapeLog(Base):
    """Log of scraping operations."""

    __tablename__ = "scrape_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    book_id = Column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    source = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False)  # "success", "failed", "partial"
    reviews_found = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
