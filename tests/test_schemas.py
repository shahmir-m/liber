"""Tests for Pydantic schemas."""

import pytest
from pydantic import ValidationError

from app.models.schemas import RecommendationRequest, TasteProfile


def test_recommendation_request_valid():
    req = RecommendationRequest(
        favorite_books=["Book A", "Book B", "Book C"],
        num_recommendations=5,
    )
    assert len(req.favorite_books) == 3
    assert req.num_recommendations == 5


def test_recommendation_request_too_few_books():
    with pytest.raises(ValidationError):
        RecommendationRequest(
            favorite_books=["Book A"],
            num_recommendations=5,
        )


def test_recommendation_request_too_many_books():
    with pytest.raises(ValidationError):
        RecommendationRequest(
            favorite_books=["A", "B", "C", "D", "E", "F"],
            num_recommendations=5,
        )


def test_recommendation_request_defaults():
    req = RecommendationRequest(
        favorite_books=["Book A", "Book B", "Book C"],
    )
    assert req.num_recommendations == 10


def test_taste_profile():
    profile = TasteProfile(
        preferred_genres=["sci-fi", "fantasy"],
        preferred_themes=["adventure", "dystopia"],
        preferred_authors=["Author A"],
        reading_style="Prefers long, immersive novels",
        summary="Enjoys speculative fiction with deep world-building.",
    )
    assert len(profile.preferred_genres) == 2
    assert profile.reading_style != ""
