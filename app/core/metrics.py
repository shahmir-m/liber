"""Performance tracking for latency, cost, and token usage."""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class TokenUsage:
    """Track token usage for a single LLM call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    cost_usd: float = 0.0


@dataclass
class MetricsCollector:
    """Collect and aggregate performance metrics for a request."""

    request_id: str = ""
    start_time: float = field(default_factory=time.time)
    latencies: dict[str, float] = field(default_factory=dict)
    token_usages: list[TokenUsage] = field(default_factory=list)
    embedding_cache_hits: int = 0
    embedding_cache_misses: int = 0
    _timers: dict[str, float] = field(default_factory=dict)

    def start_timer(self, name: str) -> None:
        """Start a named timer."""
        self._timers[name] = time.time()

    def stop_timer(self, name: str) -> float:
        """Stop a named timer and record latency."""
        if name not in self._timers:
            return 0.0
        elapsed = time.time() - self._timers.pop(name)
        self.latencies[name] = elapsed
        return elapsed

    def record_token_usage(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        """Record token usage from an LLM call."""
        cost = _estimate_cost(model, prompt_tokens, completion_tokens)
        usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            model=model,
            cost_usd=cost,
        )
        self.token_usages.append(usage)

    def record_embedding_hit(self) -> None:
        """Record an embedding cache hit."""
        self.embedding_cache_hits += 1

    def record_embedding_miss(self) -> None:
        """Record an embedding cache miss."""
        self.embedding_cache_misses += 1

    @property
    def total_latency(self) -> float:
        """Total elapsed time since metrics collection started."""
        return time.time() - self.start_time

    @property
    def total_tokens(self) -> int:
        """Total tokens used across all LLM calls."""
        return sum(u.total_tokens for u in self.token_usages)

    @property
    def total_cost_usd(self) -> float:
        """Total estimated cost in USD."""
        return sum(u.cost_usd for u in self.token_usages)

    def summary(self) -> dict:
        """Return a summary of all collected metrics."""
        return {
            "request_id": self.request_id,
            "total_latency_s": round(self.total_latency, 3),
            "latencies": {k: round(v, 3) for k, v in self.latencies.items()},
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "token_breakdown": [
                {
                    "model": u.model,
                    "prompt_tokens": u.prompt_tokens,
                    "completion_tokens": u.completion_tokens,
                    "cost_usd": round(u.cost_usd, 6),
                }
                for u in self.token_usages
            ],
            "embedding_cache_hits": self.embedding_cache_hits,
            "embedding_cache_misses": self.embedding_cache_misses,
        }


# Global metrics store for aggregate tracking
class GlobalMetrics:
    """Aggregate metrics across all requests."""

    def __init__(self) -> None:
        self.total_requests: int = 0
        self.total_tokens: int = 0
        self.total_cost_usd: float = 0.0
        self.total_latency: float = 0.0
        self.model_usage: dict[str, int] = defaultdict(int)

    def record(self, collector: MetricsCollector) -> None:
        """Record metrics from a completed request."""
        self.total_requests += 1
        self.total_tokens += collector.total_tokens
        self.total_cost_usd += collector.total_cost_usd
        self.total_latency += collector.total_latency
        for usage in collector.token_usages:
            self.model_usage[usage.model] += usage.total_tokens

    def summary(self) -> dict:
        """Return aggregate metrics summary."""
        avg_latency = self.total_latency / max(self.total_requests, 1)
        return {
            "total_requests": self.total_requests,
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "avg_latency_s": round(avg_latency, 3),
            "model_usage": dict(self.model_usage),
        }


global_metrics = GlobalMetrics()


# Cost estimation per model (approximate pricing as of 2024)
_COST_PER_1K: dict[str, dict[str, float]] = {
    "gpt-4-turbo": {"prompt": 0.01, "completion": 0.03},
    "gpt-3.5-turbo": {"prompt": 0.0005, "completion": 0.0015},
    "text-embedding-3-small": {"prompt": 0.00002, "completion": 0.0},
}


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate cost in USD for a given model and token usage."""
    rates = _COST_PER_1K.get(model, {"prompt": 0.001, "completion": 0.002})
    return (prompt_tokens / 1000 * rates["prompt"]) + (
        completion_tokens / 1000 * rates["completion"]
    )


def create_metrics(request_id: Optional[str] = None) -> MetricsCollector:
    """Create a new metrics collector for a request."""
    return MetricsCollector(request_id=request_id or "")
