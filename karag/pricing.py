"""Token pricing — turning usage into money (§15's "usage & cost dashboard").

§17's business model bills three ways: onboarding, subscription, and
*consumption* — "by volume of LLM queries". Counting tokens is only half of
that; a tenant's dashboard has to show what those tokens cost, and KIT has to
be able to see margin before invoicing.

Rates are per **million** tokens in USD and are configuration, not code: a
deployment overrides them with ``KARAG_PRICING`` (``model:input:output,…``)
when a provider changes its price list. An unknown model costs 0 rather than
guessing — a wrong number on an invoice is worse than a missing one, and the
dashboard shows which models were unpriced.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# model id -> (USD per 1M input tokens, USD per 1M output tokens)
DEFAULT_RATES: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-opus-4-8": (15.00, 75.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    # OpenAI (fallback path)
    "gpt-5.5": (1.25, 10.00),
    "gpt-5.4": (1.25, 10.00),
    "gpt-4o": (2.50, 10.00),
    # embeddings
    "text-embedding-3-large": (0.13, 0.0),
    # local inference has no per-token cost — that is the Phase 2 argument
    "ollama": (0.0, 0.0),
    "fake": (0.0, 0.0),
}

_PER_MILLION = 1_000_000


@dataclass(frozen=True)
class Cost:
    input_usd: float = 0.0
    output_usd: float = 0.0
    priced: bool = True  # False when the model had no rate

    @property
    def total_usd(self) -> float:
        return self.input_usd + self.output_usd

    def to_dict(self) -> dict:
        return {
            "input_usd": round(self.input_usd, 6),
            "output_usd": round(self.output_usd, 6),
            "total_usd": round(self.total_usd, 6),
            "priced": self.priced,
        }


class PriceList:
    def __init__(self, rates: dict[str, tuple[float, float]] | None = None) -> None:
        self._rates = dict(rates if rates is not None else DEFAULT_RATES)

    @classmethod
    def from_env(cls, var: str = "KARAG_PRICING") -> "PriceList":
        """Defaults overlaid with ``model:in:out`` entries from the environment."""
        rates = dict(DEFAULT_RATES)
        for entry in os.environ.get(var, "").split(","):
            entry = entry.strip()
            if not entry:
                continue
            try:
                model, inp, out = entry.rsplit(":", 2)
                rates[model.strip()] = (float(inp), float(out))
            except ValueError:
                continue  # a malformed entry must not take pricing down
        return cls(rates)

    def rate_for(self, model: str) -> tuple[float, float] | None:
        """Exact match first, then the longest matching prefix.

        Providers version model ids (``claude-sonnet-5-20260214``); a prefix
        match keeps a dated snapshot priced as its family instead of silently
        falling to zero.
        """
        if model in self._rates:
            return self._rates[model]
        candidates = [k for k in self._rates if model.startswith(k)]
        if not candidates:
            return None
        return self._rates[max(candidates, key=len)]

    def cost(self, model: str, input_tokens: int, output_tokens: int) -> Cost:
        rate = self.rate_for(model or "")
        if rate is None:
            return Cost(priced=False)
        rate_in, rate_out = rate
        return Cost(
            input_usd=input_tokens * rate_in / _PER_MILLION,
            output_usd=output_tokens * rate_out / _PER_MILLION,
        )

    def known_models(self) -> list[str]:
        return sorted(self._rates)
