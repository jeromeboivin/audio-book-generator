"""Regression test: ebooklib's auto-generated EpubNav (table-of-contents)
document must never leak into a chapter's Passages.

Found via `tests/fixtures/synthetic_book.epub` (2 chapters, no chapter
after the last one to bound its passage slice): the nav document's
<nav><h2>book title</h2>...</nav> heading was silently appended to the
last chapter's Passages once parsing.py started treating every heading
level (not just h2/h3) as passage-like content (ticket 04's 2026-09-13
amendment, for narrating genuine subtitles). Fixed in extract_chapter by
skipping any `epub.EpubNav` item outright.

No pytest dependency — run directly: python tests/test_parsing_nav_exclusion.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audiobook.parsing import extract_chapter

FIXTURE = str(Path(__file__).resolve().parent / "fixtures" / "synthetic_book.epub")
BOOK_TITLE = "Léa et Marc (livre de test synthétique)"


def test_last_chapter_has_no_nav_leakage():
    ch = extract_chapter(FIXTURE, 2)
    assert len(ch.passages) == 3, [p.text for p in ch.passages]
    assert not any(BOOK_TITLE in p.text for p in ch.passages), [p.text for p in ch.passages]


def test_first_chapter_unaffected():
    ch = extract_chapter(FIXTURE, 1)
    assert len(ch.passages) == 3, [p.text for p in ch.passages]
    assert ch.title == "Le Matin"


def test_second_chapter_title():
    ch = extract_chapter(FIXTURE, 2)
    assert ch.title == "Le Soir"


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {t.__name__}: {e}")
    if failures:
        print(f"\n{failures}/{len(tests)} failed")
        sys.exit(1)
    print(f"\nall {len(tests)} passed")
