"""Counting words in titles and comments - by rule, so every figure can be checked.

Research numbers have to be the app's own: "38/150 comment mẫu đề cập 'giá'"
is a count anyone can redo from the sample, where a model's "most viewers
care about price" is not. Nothing here calls a model or the network.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any, Iterable

# Words that carry no subject on their own, Vietnamese first. Deliberately
# short: a longer list starts removing words that are the subject.
STOPWORDS = frozenset("""
và của là có không được cho các những một với này đó để thì mà như khi đã sẽ đang rất cũng
nhưng hay hoặc nên vì từ trong ngoài trên dưới lại ra vào về đến theo bị bởi do nếu thế
ai gì nào đâu sao bao nhiêu lắm quá rồi còn nữa đi thôi nha nhé ạ à ơi vậy luôn mình
bạn tôi em anh chị họ nó chúng ta người cái con chiếc việc điều lần mọi nhiều ít hơn nhất
the a an and or of to in on for with is are was were be this that it you i we they my your
video clip kênh channel xem like share sub subscribe
""".split())

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_MENTION = re.compile(r"@[\w.\-]{2,}", re.UNICODE)
_URL = re.compile(r"https?://\S+")
_QUESTION_MARKERS = re.compile(
    r"\?|\b(sao|tại sao|vì sao|làm sao|bao nhiêu|ở đâu|khi nào|thế nào|như nào|là gì|có .{1,30} không|được không|"
    r"how|why|what|where|when)\b",
    re.IGNORECASE,
)
_NEGATIVE_MARKERS = re.compile(
    r"\b(dở|chán|tệ|kém|lỗi|hỏng|sai|thất vọng|không hay|không thích|nhảm|vô lý|lừa|phí tiền|đắt quá|"
    r"bad|boring|wrong|worst|fake)\b",
    re.IGNORECASE,
)
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐⭕]")


def _plain(text: str) -> str:
    return unicodedata.normalize("NFC", str(text or ""))


def tokens(text: str) -> list[str]:
    """Lowercase words without stopwords, numbers or single letters."""
    words = [word.lower() for word in _WORD.findall(_plain(_URL.sub(" ", _MENTION.sub(" ", text))))]
    return [word for word in words if len(word) >= 2 and not word.isdigit() and word not in STOPWORDS]


def _terms(text: str) -> set[str]:
    """The words of one text, and the pairs of neighbouring words.

    Vietnamese writes one syllable per word, so "tai nghe" only means
    something as a pair.
    """
    words = [word.lower() for word in _WORD.findall(_plain(_URL.sub(" ", _MENTION.sub(" ", text))))]
    found: set[str] = set()
    for index, word in enumerate(words):
        usable = len(word) >= 2 and not word.isdigit() and word not in STOPWORDS
        if usable:
            found.add(word)
        if index + 1 < len(words):
            nxt = words[index + 1]
            if usable and len(nxt) >= 2 and not nxt.isdigit() and nxt not in STOPWORDS:
                found.add(f"{word} {nxt}")
    return found


def document_frequency(texts: Iterable[str], *, top: int = 10, min_count: int = 2) -> list[dict[str, Any]]:
    """In how many of the texts each term appears - not how often it is said.

    A pair wins over its single words when it covers most of their uses, so
    "tai nghe" is listed rather than "tai" and "nghe" separately.
    """
    counts: Counter[str] = Counter()
    total = 0
    for text in texts:
        total += 1
        counts.update(_terms(text))
    kept = {term: count for term, count in counts.items() if count >= min_count}
    for term, count in list(kept.items()):
        if " " in term:
            for part in term.split(" "):
                if part in kept and kept[part] <= count * 1.25:
                    kept.pop(part, None)
    ordered = sorted(kept.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))
    return [{"term": term, "count": count, "of": total} for term, count in ordered[:top]]


def is_question(text: str) -> bool:
    return bool(_QUESTION_MARKERS.search(_plain(text)))


def is_negative(text: str) -> bool:
    return bool(_NEGATIVE_MARKERS.search(_plain(text)))


def excerpt(text: str, limit: int = 160) -> str:
    """A short, anonymous quote: no @names, no links."""
    clean = " ".join(_URL.sub("", _MENTION.sub("@…", _plain(text))).split())
    return clean if len(clean) <= limit else clean[: limit - 1].rsplit(" ", 1)[0] + "…"


# Title shapes detectable by rule. Each is a count over the titles, with the
# titles that show it; none is a judgement of quality.
def _has_caps_word(title: str) -> bool:
    # isupper() knows Vietnamese capitals (Ố, Ạ…); a character range does not.
    return any(len(word) >= 3 and word.isalpha() and word.isupper() for word in _WORD.findall(title))


TITLE_PATTERNS: tuple[tuple[str, str, Any], ...] = (
    ("question", "Tiêu đề dạng câu hỏi", re.compile(r"\?|^(tại sao|vì sao|làm sao|có nên|why|how|what)\b", re.IGNORECASE).search),
    ("how_to", "Tiêu đề hướng dẫn / cách làm", re.compile(r"\b(cách|hướng dẫn|mẹo|how to|tutorial)\b", re.IGNORECASE).search),
    ("list", "Tiêu đề dạng danh sách (Top N, N điều…)", re.compile(r"\btop\s*\d+|\b\d+\s+(cách|lý do|điều|mẹo|bước|sự thật|loại)\b", re.IGNORECASE).search),
    ("number", "Tiêu đề có con số", re.compile(r"\d").search),
    ("separator", "Tiêu đề có dấu tách | hoặc ngoặc", re.compile(r"[|\[\]【】()]").search),
    ("caps", "Tiêu đề có từ VIẾT HOA nhấn mạnh", _has_caps_word),
    ("emoji", "Tiêu đề có emoji", _EMOJI.search),
)


def title_pattern_counts(titles: list[str]) -> list[dict[str, Any]]:
    """How many titles show each shape, with the indices of those titles."""
    found = []
    for key, label, test in TITLE_PATTERNS:
        matches = [index for index, title in enumerate(titles) if test(_plain(title))]
        found.append({"key": key, "label": label, "count": len(matches), "of": len(titles), "indices": matches})
    return found
