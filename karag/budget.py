"""Cost control: a monthly model budget per tenant and a per-user rate limit.

Metering existed already (``usage.py``) and pricing too (``pricing.py``); what
was missing is a *cap*. Without one, any account in any tenant could run up the
model bill without limit — a looping script, a curious user pasting a 300-page
contract twenty times. Two independent checks, both run before a turn starts:

* **Rate limit** — at most ``per_minute`` turns per user in any 60-second
  window (sliding). Per process; enough to stop a runaway client.
* **Monthly budget** — the tenant's spend this calendar month (UTC), priced
  from metered usage with the same rate table as the dashboard. A tenant's own
  setting (``settings.monthly_budget_usd``, set by a platform operator) wins
  over the deployment default; no budget means no cap. A turn that would start
  after the budget is spent is refused with a plain explanation; the turn in
  flight when it is crossed is allowed to finish.

The check is wired into the orchestrator, so the console, the API, assistants
and the messenger bots are all covered by the same code.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from .domain import Principal
from .errors import BudgetExceeded, RateLimited
from .pricing import PriceList
from .usage import month_key

# The spend total is recomputed at most this often per tenant; a few seconds
# of staleness is nothing against a monthly budget.
_SPEND_TTL_S = 10.0


class UsageGuard:
    def __init__(
        self,
        usage,
        prices: PriceList,
        *,
        directory=None,
        default_budget_usd: float | None = None,
        per_minute: int = 30,
        clock=time.time,
    ) -> None:
        self._usage = usage
        self._prices = prices
        self._directory = directory
        self._default_budget = default_budget_usd
        self._per_minute = max(0, int(per_minute))
        self._clock = clock
        self._recent: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._spend_cache: dict[str, tuple[float, str, float]] = {}

    # ------------------------------------------------------------- checks

    def check(self, principal: Principal) -> None:
        """Raise if this principal may not start a turn right now."""
        self._check_rate(principal)
        status = self.status(principal.tenant_id)
        budget = status["budget_usd"]
        if budget is not None and status["spent_usd"] >= budget:
            raise BudgetExceeded(
                f"the monthly AI budget for this organisation (${budget:,.2f}) is spent "
                f"for {status['month']}; an administrator can raise it"
            )

    def _check_rate(self, principal: Principal) -> None:
        if not self._per_minute:
            return
        now = self._clock()
        window = self._recent[(principal.tenant_id, principal.user_id)]
        while window and now - window[0] >= 60:
            window.popleft()
        if len(window) >= self._per_minute:
            retry = max(1, int(60 - (now - window[0])) + 1)
            raise RateLimited(
                f"too many requests: at most {self._per_minute} per minute, "
                f"try again in {retry} s",
                retry_after=retry,
            )
        window.append(now)

    # ------------------------------------------------------------- status

    def budget_for(self, tenant_id: str) -> float | None:
        if self._directory is not None:
            tenant = self._directory.get_tenant(tenant_id)
            if tenant is not None:
                value = (tenant.settings or {}).get("monthly_budget_usd")
                if value is not None:
                    return float(value)
        return self._default_budget

    def spent(self, tenant_id: str, month: str | None = None) -> float:
        month = month or month_key(self._clock())
        cached = self._spend_cache.get(tenant_id)
        now = self._clock()
        if cached and cached[1] == month and now - cached[0] < _SPEND_TTL_S:
            return cached[2]
        total = 0.0
        for model, totals in self._usage.tenant_month_by_model(tenant_id, month).items():
            total += self._prices.cost(model, totals.input_tokens, totals.output_tokens).total_usd
        self._spend_cache[tenant_id] = (now, month, total)
        return total

    def status(self, tenant_id: str) -> dict:
        month = month_key(self._clock())
        budget = self.budget_for(tenant_id)
        spent = self.spent(tenant_id, month)
        return {
            "month": month,
            "budget_usd": budget,
            "spent_usd": round(spent, 4),
            "remaining_usd": None if budget is None else round(max(0.0, budget - spent), 4),
        }

    def forget_spend(self, tenant_id: str) -> None:
        """Drop the cached total (after the budget itself changed)."""
        self._spend_cache.pop(tenant_id, None)
