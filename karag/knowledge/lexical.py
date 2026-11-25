"""Keyword side of hybrid retrieval: tokenising, stemming and BM25.

Embeddings find passages that *mean* the same thing; they are weak on exact
strings — a product code (``АМК-875``), a form number (``107/у-НП``), a
surname, a street. People at a pharmacy ask about exactly those, so retrieval
runs a keyword search next to the vector search and fuses the two rankings.

Everything here is stdlib and deterministic, and the same ``terms()`` is used
when a chunk is indexed and when a question is searched, so both sides always
agree on what a "word" is:

* lower-case, ``ё`` → ``е``, Unicode-normalised;
* codes and numbers are kept whole (``амк-875``) *and* split into their parts;
* Russian words go through the Snowball (Porter) stemmer, Tajik words through
  a light suffix stripper (plural ``-ҳо``, object ``-ро``, izofat ``-и``…),
  Latin words through a light English stemmer — "логгеры" finds "логгеров",
  "шикоятҳо" finds "шикоят";
* stop-words in all three languages are dropped.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

# A run of letters/digits, optionally joined by - / . to keep codes whole.
_TOKEN = re.compile(r"[^\W_]+(?:[-/.][^\W_]+)*", re.UNICODE)
_CYRILLIC = re.compile(r"[а-яёӣӯҳқғҷ]")
_TAJIK_LETTERS = re.compile(r"[ӣӯҳқғҷ]")
_DIGIT = re.compile(r"\d")

_STOP = frozenset("""
и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по
только ее её мне было вот от меня еще ещё нет о из ему теперь когда даже ну ли если
уже или ни быть был него до вас нибудь опять уж вам ведь там потом себя ничего ей
может они тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз
тоже себе под будет ж тогда кто этот того потому этого какой какая какие какую каким
какое совсем ним здесь этом один почти мой тем чтобы нее сейчас были куда зачем всех
никогда можно при наконец об другой хоть после над больше тот через эти нас про всего
них много разве эту моя впрочем хорошо свою этой перед иногда лучше чуть том такой им
более всегда конечно всю между сколько это наш наша наше наши нужно ли весь вся
the a an of to in is are was were do does did i how what which who whom and or for on
with by be it its this that these those have has had my our we you your should must
can could would at as from not no if then than so me us they them there here when
ва дар ба аз бо ки то ин он аст мешавад мешаванд чанд чӣ кадом ё ҳам барои низ
""".split())


# --------------------------------------------------------------- Russian

_RU_VOWELS = "аеиоуыэюя"
_PERFECTIVE_1 = ("ившись", "ывшись", "вшись", "ивши", "ывши", "вши", "ив", "ыв", "в")
_PERFECTIVE_GROUP1 = ("вшись", "вши", "в")  # must follow а or я
_REFLEXIVE = ("ся", "сь")
_ADJECTIVE = (
    "ими", "ыми", "его", "ого", "ему", "ому", "ее", "ие", "ые", "ое", "ей", "ий",
    "ый", "ой", "ем", "им", "ым", "ом", "их", "ых", "ую", "юю", "ая", "яя", "ою", "ею",
)
_PARTICIPLE_GROUP1 = ("ем", "нн", "вш", "ющ", "щ")  # must follow а or я
_PARTICIPLE_GROUP2 = ("ивш", "ывш", "ующ")
_VERB_GROUP1 = (
    "ете", "йте", "ешь", "нно", "ла", "на", "ли", "ем", "ло", "но", "ет", "ют",
    "ны", "ть", "й", "л", "н",
)  # must follow а or я
_VERB_GROUP2 = (
    "ейте", "уйте", "ила", "ыла", "ена", "ите", "или", "ыли", "ило", "ыло", "ено",
    "ует", "уют", "ены", "ить", "ыть", "ишь", "ей", "уй", "ил", "ыл", "им", "ым",
    "ен", "ят", "ит", "ыт", "ую", "у", "ю",
)
_NOUN = (
    "иями", "ями", "ами", "ией", "иям", "ием", "иях", "ев", "ов", "ие", "ье", "еи",
    "ии", "ей", "ой", "ий", "ям", "ем", "ам", "ом", "ах", "ях", "ию", "ью", "ия",
    "ья", "иям", "а", "е", "и", "й", "о", "у", "ы", "ь", "ю", "я",
)
_SUPERLATIVE = ("ейше", "ейш")
_DERIVATIONAL = ("ость", "ост")


def _sorted(endings: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(set(endings), key=len, reverse=True))


_PERFECTIVE_1 = _sorted(_PERFECTIVE_1)
_ADJECTIVE = _sorted(_ADJECTIVE)
_VERB_GROUP1 = _sorted(_VERB_GROUP1)
_VERB_GROUP2 = _sorted(_VERB_GROUP2)
_NOUN = _sorted(_NOUN)


def _rv(word: str) -> int:
    for i, ch in enumerate(word):
        if ch in _RU_VOWELS:
            return i + 1
    return len(word)


def _r2(word: str) -> int:
    # R1: after the first non-vowel following a vowel; R2: the same within R1.
    def region(start: int) -> int:
        for i in range(start + 1, len(word)):
            if word[i] not in _RU_VOWELS and word[i - 1] in _RU_VOWELS:
                return i + 1
        return len(word)

    return region(region(0))


def _strip(word: str, start: int, endings, group1=(), *, needs_a_ya=False) -> str | None:
    """Remove the longest ending found in word[start:]; None when none fits."""
    region = word[start:]
    for e in endings:
        if region.endswith(e):
            before = word[: len(word) - len(e)]
            if needs_a_ya or e in group1:
                if not before or before[-1] not in "ая" or len(before) - 1 < start:
                    continue
            return before
    return None


def stem_ru(word: str) -> str:
    """Snowball Russian stemmer (Porter, 2002), compact form."""
    if len(word) <= 3:
        return word
    rv = _rv(word)

    # Step 1: perfective gerund, else reflexive + adjectival / verb / noun.
    res = _strip(word, rv, _PERFECTIVE_1, _PERFECTIVE_GROUP1)
    if res is not None:
        word = res
    else:
        res = _strip(word, rv, _sorted(_REFLEXIVE))
        if res is not None:
            word = res
        res = _strip(word, rv, _ADJECTIVE)
        if res is not None:
            word = res
            part = _strip(word, rv, _sorted(_PARTICIPLE_GROUP2))
            if part is None:
                part = _strip(word, rv, _sorted(_PARTICIPLE_GROUP1), needs_a_ya=True)
            if part is not None:
                word = part
        else:
            res = _strip(word, rv, _VERB_GROUP1, needs_a_ya=True)
            if res is None:
                res = _strip(word, rv, _VERB_GROUP2)
            if res is None:
                res = _strip(word, rv, _NOUN)
            if res is not None:
                word = res

    # Step 2: и
    if word[rv:].endswith("и"):
        word = word[:-1]
    # Step 3: derivational ость / ост in R2
    r2 = _r2(word)
    res = _strip(word, r2, _DERIVATIONAL)
    if res is not None:
        word = res
    # Step 4: нн → н, superlative, soft sign
    res = _strip(word, rv, _SUPERLATIVE)
    if res is not None:
        word = res
    if word.endswith("нн"):
        word = word[:-1]
    elif word.endswith("ь"):
        word = word[:-1]
    return word


# ---------------------------------------------------------------- Tajik

_TJ_SUFFIXES = (
    "ҳоямон", "ҳоятон", "ҳояшон", "ҳои", "ҳоро", "ҳоям", "ҳоят", "ҳояш", "ҳо",
    "ҳое", "ониро", "онро", "они", "он", "ёни", "ён", "гон", "ро", "ам", "ат",
    "аш", "амон", "атон", "ашон", "ӣ", "и", "е",
)
_TJ_SUFFIXES = _sorted(_TJ_SUFFIXES)


def stem_tj(word: str) -> str:
    """Light Tajik suffix stripping: plural, object, izofat, possessive."""
    for _ in range(2):  # шикоятҳои → шикоятҳо → шикоят
        for suf in _TJ_SUFFIXES:
            if word.endswith(suf) and len(word) - len(suf) >= 3:
                word = word[: -len(suf)]
                break
        else:
            break
    return word


# --------------------------------------------------------------- English

def stem_en(word: str) -> str:
    """A light English stemmer: plurals and the common verb endings."""
    if len(word) <= 3:
        return word
    for suf, rep in (("ies", "y"), ("sses", "ss"), ("ing", ""), ("ed", ""),
                     ("ly", ""), ("es", ""), ("s", "")):
        if word.endswith(suf) and len(word) - len(suf) >= 3:
            if suf == "s" and word.endswith("ss"):
                return word
            return word[: -len(suf)] + rep
    return word


# ----------------------------------------------------------------- terms

def normalise(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower().replace("ё", "е")


def _stem(word: str) -> str:
    if _DIGIT.search(word):
        return word
    if _CYRILLIC.search(word):
        return stem_tj(word) if _TAJIK_LETTERS.search(word) else stem_ru(word)
    return stem_en(word)


def terms(text: str) -> list[str]:
    """Index/search terms for ``text`` — repeated terms are kept (BM25 tf)."""
    out: list[str] = []
    for tok in _TOKEN.findall(normalise(text)):
        compound = any(sep in tok for sep in "-/.")
        if compound:
            # Keep the code whole, and its parts so "АМК 875" still matches.
            out.append(tok)
            parts = [p for p in re.split(r"[-/.]", tok) if p]
        else:
            parts = [tok]
        for part in parts:
            if part in _STOP or (len(part) < 2 and not part.isdigit()):
                continue
            out.append(_stem(part))
    return out


def query_terms(text: str) -> list[str]:
    """Distinct terms of a question, in order of first appearance."""
    seen: dict[str, None] = {}
    for t in terms(text):
        seen.setdefault(t, None)
    return list(seen)


# ------------------------------------------------------------------ BM25

class BM25:
    """Okapi BM25 over an in-memory list of term lists (k1=1.2, b=0.75)."""

    def __init__(self, docs: list[list[str]], *, k1: float = 1.2, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.tfs = [Counter(d) for d in docs]
        self.lens = [len(d) for d in docs]
        self.avg = (sum(self.lens) / len(self.lens)) if self.lens else 0.0
        df: Counter = Counter()
        for tf in self.tfs:
            df.update(tf.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def score(self, i: int, query: list[str]) -> float:
        tf, length = self.tfs[i], self.lens[i]
        total = 0.0
        for t in query:
            f = tf.get(t)
            if not f:
                continue
            norm = f + self.k1 * (1 - self.b + self.b * length / (self.avg or 1.0))
            total += self.idf.get(t, 0.0) * f * (self.k1 + 1) / norm
        return total
