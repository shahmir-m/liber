"""Agent 3: Explanation Generator.

Generates concise 2-3 sentence explanations for why each candidate
book matches the user's taste profile. Uses structured JSON prompts
for token efficiency.
"""

import json
from typing import Optional

from openai import AsyncOpenAI

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import MetricsCollector
from app.db.models import Book
from app.models.schemas import TasteProfile

logger = get_logger(__name__)

EXPLANATION_PROMPT = """Given this reader's taste profile and candidate books, \
write a concise 2-3 sentence explanation for each book \
explaining why it's a good match.

Taste Profile:
{taste_json}

Candidate Books:
{candidates_json}

Return a JSON object with book titles as keys and explanation strings as values.
Return ONLY valid JSON, no other text."""


async def generate_explanations(
    taste_profile: TasteProfile,
    candidates: list[tuple[Book, float]],
    metrics: Optional[MetricsCollector] = None,
) -> dict[int, str]:
    """Generate explanations for top-N candidate books.

    Returns a dict mapping book_id -> explanation string.
    """
    if not candidates:
        return {}

    if metrics:
        metrics.start_timer("explanation_generator")

    # Limit to explanation_top_n candidates
    top_candidates = candidates[: settings.explanation_top_n]

    # Build compact JSON representations
    taste_json = json.dumps({
        "genres": taste_profile.preferred_genres,
        "themes": taste_profile.preferred_themes,
        "authors": taste_profile.preferred_authors,
        "summary": taste_profile.summary,
    })

    candidates_json = json.dumps([
        {
            "title": book.title,
            "authors": book.authors,
            "subjects": book.subjects[:5],
            "description": (book.description or "")[:200],
            "score": round(score, 3),
        }
        for book, score in top_candidates
    ])

    client = AsyncOpenAI(api_key=settings.openai_api_key)

    response = await client.chat.completions.create(
        model=settings.reasoning_model,
        messages=[
            {
                "role": "system",
                "content": "You are a book recommendation explainer. Return only valid JSON.",
            },
            {
                "role": "user",
                "content": EXPLANATION_PROMPT.format(
                    taste_json=taste_json,
                    candidates_json=candidates_json,
                ),
            },
        ],
        temperature=0.5,
        max_tokens=1000,
        response_format={"type": "json_object"},
    )

    if metrics:
        metrics.record_token_usage(
            model=settings.reasoning_model,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
        )

    # Parse response and map to book IDs
    raw = response.choices[0].message.content or "{}"
    explanations_by_title = json.loads(raw)

    explanations: dict[int, str] = {}
    for book, _score in top_candidates:
        # Match by title (case-insensitive)
        explanation = ""
        for title, exp in explanations_by_title.items():
            if title.lower().strip() == book.title.lower().strip():
                explanation = exp
                break
        if not explanation:
            # Fallback: try partial match
            for title, exp in explanations_by_title.items():
                if title.lower() in book.title.lower() or book.title.lower() in title.lower():
                    explanation = exp
                    break
        explanations[book.id] = explanation or "Recommended based on your taste profile."

    if metrics:
        metrics.stop_timer("explanation_generator")

    logger.info("explanations_generated", count=len(explanations))
    return explanations
