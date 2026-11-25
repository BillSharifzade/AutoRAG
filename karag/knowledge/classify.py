"""Auto-classification — a *suggestion*, never a decision.

§7 is explicit about the hierarchy: "admin per source; uploader per document;
auto-classification only as a suggestion". This module implements the third
rung and nothing more. It returns a proposed :class:`DataClass` with the
evidence behind it; applying it is always an explicit human act.

Two properties matter more than accuracy here:

1. **It never lowers a class by itself.** The caller decides; the ingestion
   path still defaults to the most restrictive class when nothing is chosen.
   A wrong "public" guess that auto-applied would be exactly the §7 leak.
2. **It is deterministic and offline.** Sending a document to a model to ask
   "is this financial?" would send the very content whose sensitivity is
   unknown to an external API — backwards. Keyword evidence is stdlib, fast,
   auditable, and works for Russian, Tajik and English (§2's languages).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from ..domain import DataClass

# Evidence stems per class, lower-cased. Russian and Tajik are heavily
# inflected — "выручка / выручке / выручки" are one word — so Cyrillic entries
# are *stems* matched as substrings rather than whole words. English entries are
# stemmed the same way where the inflection matters ("invoic" covers
# invoice/invoices/invoicing).
_SIGNALS: dict[DataClass, tuple[str, ...]] = {
    DataClass.FINANCIAL: (
        # en
        "revenue", "profit", "invoic", "budget", "ebitda",
        "balance sheet", "cash flow", "margin", "turnover", "p&l", "receivable",
        # ru
        "выручк", "прибыл", "убыт", "счёт-фактур", "счет-фактур",
        "бюджет", "баланс", "оборот", "марж", "дебиторск", "финанс",
        "себестоимост", "налог", "наценк",
        # tg
        "даромад", "фоида", "буҷет", "андоз", "хароҷот",
    ),
    DataClass.HR: (
        # en
        "employee record", "personnel", "hiring", "termination", "performance review",
        "disciplinar", "sick leave", "vacation request", "resume", "onboarding",
        "grievance",
        # pay by person or position is personnel data, not company finance
        "salar", "payroll", "compensation",
        # ru
        "кадров", "кадры", "персонал", "трудовой договор", "увольнен",
        "приём на работу", "прием на работу", "отпуск", "больничн", "аттестац",
        "резюме", "дисциплинарн", "штатное расписание",
        "зарплат", "оклад", "оплате труда", "оплаты труда",
        # tg
        "кадрҳо", "кормандон", "шартномаи меҳнат", "рухсат", "таъинот", "маош",
    ),
    DataClass.REGULATED: (
        # en
        # Not "SOP", "deviation" or "good practice": every pharmacy procedure
        # uses them, and a cold-chain SOP is an everyday staff document.
        "gmp", "gxp", "capa", "batch record", "validation protocol",
        "audit finding", "regulator", "pharmacovigilance",
        "controlled substance", "narcotic", "psychotropic", "licence", "license",
        # ru
        "корректирующ", "досье на серию", "валидац", "регулятор", "лиценз",
        "фармаконадзор", "наркотическ", "психотропн", "прекурсор",
        # tg
        "иҷозатнома", "танзим", "нашъадор",
    ),
    DataClass.OPERATIONAL: (
        # en
        "procedure", "process", "workflow", "inventory", "stock", "logistic",
        "supplier", "shipment", "maintenance", "schedule", "internal",
        # ru
        "процедур", "процесс", "регламент", "склад", "остатк", "логистик",
        "поставщик", "заказ", "отгрузк", "обслуживан", "график", "внутренн",
        # tg
        "тартиб", "раванд", "анбор", "таъминот", "фармоиш", "ҷадвал",
    ),
    DataClass.PUBLIC: (
        # en
        "press release", "public announcement", "marketing", "brochure",
        "published", "for publication", "website", "faq",
        # ru
        "пресс-релиз", "объявлен", "маркетинг", "брошюр", "опубликован",
        "для публикации", "публичн", "часто задаваемые",
        # tg
        "эълон", "оммавӣ", "нашрия",
    ),
}

# When several classes match, the more restrictive wins. Ordered least → most
# sensitive; ties resolve to the later entry.
_PRECEDENCE: tuple[DataClass, ...] = (
    DataClass.PUBLIC,
    DataClass.OPERATIONAL,
    DataClass.HR,
    DataClass.FINANCIAL,
    DataClass.REGULATED,
)

# How much of a long document to scan. Sensitivity markers cluster in titles and
# headers, and a bounded scan keeps this predictable on a 200-page SOP.
_SCAN_CHARS = 20_000


@dataclass
class Classification:
    """A proposed class plus the evidence, for a human to accept or override."""

    suggested: DataClass
    confidence: float  # 0.0–1.0, evidence strength — not a probability
    matched: dict[str, list[str]] = field(default_factory=dict)
    rationale: str = ""

    def to_dict(self) -> dict:
        return {
            "suggested": self.suggested.value,
            "confidence": round(self.confidence, 2),
            "matched": self.matched,
            "rationale": self.rationale,
            # Stated in the payload so no client can mistake this for a decision.
            "advisory": True,
        }


def _normalise(text: str) -> str:
    """Case-fold and strip diacritics so Tajik ҳ/Ҳ and Cyrillic ё/е match alike."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", folded)


def suggest_data_class(
    title: str = "", text: str = "", *, filename: str = ""
) -> Classification:
    """Propose a data class from keyword evidence in the title, name and body.

    The title and filename are weighted more heavily than the body: "Payroll
    2026.xlsx" is a stronger signal than one stray mention of "salary" on page
    40.
    """
    haystack_title = _normalise(f"{title} {filename}")
    haystack_body = _normalise(text[:_SCAN_CHARS])

    scores: dict[DataClass, float] = {}
    matched: dict[str, list[str]] = {}
    title_hits: dict[DataClass, int] = {}

    for data_class, terms in _SIGNALS.items():
        hits = [t for t in terms if t in haystack_title or t in haystack_body]
        if not hits:
            continue
        in_title = [t for t in hits if t in haystack_title]
        # A title/filename match counts triple: "Payroll 2026.xlsx" says more
        # than one stray "salary" on page 40.
        scores[data_class] = 3.0 * len(in_title) + (len(hits) - len(in_title))
        title_hits[data_class] = len(in_title)
        matched[data_class.value] = sorted(hits)[:8]

    if not scores:
        # No evidence at all — fail closed, exactly as ingestion does.
        return Classification(
            suggested=DataClass.most_restrictive(),
            confidence=0.0,
            rationale=(
                "No classifying terms found. Defaulting to the most restrictive "
                "class; please classify this document explicitly."
            ),
        )

    best = max(scores, key=lambda dc: (scores[dc], _PRECEDENCE.index(dc)))
    total = sum(scores.values())
    confidence = min(scores[best] / total, 0.95) if total else 0.0

    # Substantial evidence of a *more* restrictive class pulls the suggestion
    # up, even when a chattier class scores higher overall: a warehouse process
    # doc that also mentions batch records and GMP should be proposed as
    # regulated. The test is absolute (a title hit, or three distinct body
    # terms) rather than a ratio, so common operational vocabulary cannot drown
    # out a smaller number of genuinely sensitive markers. Two was too few: a
    # leave policy granting extra days to staff "working with narcotic and
    # psychotropic drugs" was proposed as regulated on that one sentence.
    for other in _PRECEDENCE[_PRECEDENCE.index(best) + 1:]:
        if other not in scores:
            continue
        substantial = title_hits.get(other, 0) >= 1 or len(matched.get(other.value, [])) >= 3
        if substantial:
            best = other
            confidence = min(confidence, 0.6)

    return Classification(
        suggested=best,
        confidence=confidence,
        matched=matched,
        rationale=(
            f"Matched {len(matched.get(best.value, []))} {best.value} term(s): "
            + ", ".join(matched.get(best.value, [])[:5])
            + ". Suggestion only — confirm or override before ingesting."
        ),
    )
