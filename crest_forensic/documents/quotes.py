"""Quote normalization and verbatim-quote verification.

A quote the model returns is only trusted if it appears word for word in the
saved text of the cited page. Matching ignores differences the PDF text layer
introduces on its own: line breaks, spacing, ligatures, and the replacement
character (U+FFFD) it substitutes for curly quotes and apostrophes. It ignores
nothing else, so a paraphrase never matches.
"""
from __future__ import annotations

import re
import unicodedata

_QUOTE_CHARS = "‘’‚‛“”„‟′″´`\"�"
_DASHES = "‐‑‒–—―−"
_QUOTE_RE = re.compile("[" + re.escape(_QUOTE_CHARS) + "]")
_DASH_RE = re.compile("[" + re.escape(_DASHES) + "]")
MIN_QUOTE_CHARS = 20


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("­", "")  # soft hyphen
    text = _QUOTE_RE.sub("'", text)  # every quote / apostrophe / U+FFFD -> '
    text = _DASH_RE.sub("-", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def quote_in_page(quote: str, page_text: str) -> bool:
    """True if the whole quote appears verbatim (after normalization) in the page."""
    q = normalize(quote)
    return len(q) >= MIN_QUOTE_CHARS and q in normalize(page_text)


def find_quote_page(quote: str, pages: dict[int, str]) -> int | None:
    """The first page in `pages` that contains the quote, or None."""
    for number in sorted(pages):
        if quote_in_page(quote, pages[number]):
            return number
    return None
