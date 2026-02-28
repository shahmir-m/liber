"""Headless review scraper for Goodreads and alternatives.

Uses Selenium with headless Chrome for scraping review text.
Rate-limited with retry/backoff.
"""

import asyncio
import time
from typing import Optional

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _create_driver() -> webdriver.Chrome:
    """Create a headless Chrome WebDriver."""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(settings.scraper_timeout)
    return driver


def _extract_goodreads_reviews(html: str, max_reviews: int) -> list[dict[str, str]]:
    """Extract review data from Goodreads HTML."""
    soup = BeautifulSoup(html, "html.parser")
    reviews = []

    # Try multiple selectors for Goodreads review containers
    review_elements = soup.select(".ReviewCard") or soup.select(
        "[data-testid='review']"
    )

    for element in review_elements[:max_reviews]:
        review_text_el = element.select_one(
            ".ReviewText__content span"
        ) or element.select_one(".reviewText")
        reviewer_el = element.select_one(
            ".ReviewerProfile__name"
        ) or element.select_one("a.user")
        rating_el = element.select_one(".RatingStars") or element.select_one(
            ".staticStar"
        )

        if review_text_el:
            text = review_text_el.get_text(strip=True)
            if len(text) > 20:  # Skip very short reviews
                review = {
                    "review_text": text[:2000],  # Limit text length
                    "reviewer": reviewer_el.get_text(strip=True)
                    if reviewer_el
                    else None,
                    "rating": _parse_rating(rating_el),
                    "raw_html": str(element),
                    "source": "goodreads",
                }
                reviews.append(review)

    return reviews


def _extract_storygraph_reviews(html: str, max_reviews: int) -> list[dict[str, str]]:
    """Extract review data from StoryGraph HTML."""
    soup = BeautifulSoup(html, "html.parser")
    reviews = []

    review_elements = soup.select(".review-card") or soup.select("[class*='review']")

    for element in review_elements[:max_reviews]:
        text_el = element.select_one(".review-text") or element.select_one("p")
        if text_el:
            text = text_el.get_text(strip=True)
            if len(text) > 20:
                reviews.append({
                    "review_text": text[:2000],
                    "reviewer": None,
                    "rating": None,
                    "raw_html": str(element),
                    "source": "storygraph",
                })

    return reviews


def _parse_rating(element: Optional[object]) -> Optional[float]:
    """Parse a star rating from an element."""
    if element is None:
        return None
    # Try aria-label like "Rating 4 out of 5"
    aria = element.get("aria-label", "") if hasattr(element, "get") else ""
    if aria:
        try:
            parts = aria.split()
            for i, part in enumerate(parts):
                if part.replace(".", "").isdigit():
                    return float(part)
        except (ValueError, IndexError):
            pass
    return None


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=2, max=10))
def _scrape_goodreads_sync(
    book_title: str, author: str, max_reviews: int
) -> list[dict[str, str]]:
    """Synchronously scrape Goodreads reviews for a book."""
    driver = _create_driver()
    try:
        search_query = f"{book_title} {author}".strip()
        search_url = f"https://www.goodreads.com/search?q={search_query.replace(' ', '+')}"

        logger.info("scraping_goodreads", query=search_query)
        driver.get(search_url)

        # Wait for search results
        try:
            WebDriverWait(driver, 10).until(
                expected_conditions.presence_of_element_located(
                    (By.CSS_SELECTOR, "a.bookTitle, [class*='bookTitle']")
                )
            )
        except Exception:
            logger.warning("goodreads_search_no_results", query=search_query)
            return []

        # Click first result
        first_result = driver.find_elements(By.CSS_SELECTOR, "a.bookTitle, [class*='bookTitle']")
        if not first_result:
            return []
        first_result[0].click()

        # Wait for page load
        time.sleep(settings.scraper_rate_limit)

        # Get page HTML and extract reviews
        html = driver.page_source
        reviews = _extract_goodreads_reviews(html, max_reviews)

        logger.info("goodreads_reviews_found", count=len(reviews), book=book_title)
        return reviews

    except Exception as e:
        logger.error("goodreads_scrape_error", error=str(e), book=book_title)
        raise
    finally:
        driver.quit()


async def scrape_reviews(
    book_title: str,
    author: str = "",
    max_reviews: Optional[int] = None,
) -> list[dict[str, str]]:
    """Scrape reviews for a book. Runs the sync scraper in a thread pool."""
    if max_reviews is None:
        max_reviews = settings.scraper_max_reviews

    # Run synchronous scraping in a thread to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    try:
        reviews = await loop.run_in_executor(
            None, _scrape_goodreads_sync, book_title, author, max_reviews
        )
    except Exception as e:
        logger.error("scrape_reviews_failed_after_retries", error=str(e), book=book_title)
        return []

    return reviews
