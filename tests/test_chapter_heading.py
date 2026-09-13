"""Regression test: the chapter-number heading (the <h2> "Chapitre N" text,
e.g. "Chapitre I") must be captured and narrated, not just consulted for
chapter-boundary detection and then discarded.

Found in production: main.py's _build_narration_passages only ever narrated
`chapter.title` (the <h3> subtitle, e.g. "Monsieur Myriel") — the <h2>
heading text itself was read only to check the "Chapitre \\w+" boundary
regex, then thrown away. The audio never said "Chapitre I" at all.

No pytest dependency — run directly: python tests/test_chapter_heading.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audiobook.main import _build_narration_passages
from audiobook.parsing import extract_chapter

FIXTURE = str(Path(__file__).resolve().parent / "fixtures" / "synthetic_book.epub")


def test_chapter_exposes_both_heading_and_title():
    ch = extract_chapter(FIXTURE, 1)
    assert ch.heading == "Chapitre I", ch.heading
    assert ch.title == "Le Matin", ch.title


def test_second_chapter_heading():
    ch = extract_chapter(FIXTURE, 2)
    assert ch.heading == "Chapitre II", ch.heading
    assert ch.title == "Le Soir", ch.title


def test_narration_passages_include_heading_then_title_then_body():
    ch = extract_chapter(FIXTURE, 1)
    passages = _build_narration_passages(ch)
    assert passages[0].text == "Chapitre I", passages[0].text
    assert passages[1].text == "Le Matin", passages[1].text
    assert passages[0].has_dialogue is False
    assert passages[1].has_dialogue is False
    # Body passages follow, unchanged, shifted by two (heading + title).
    assert len(passages) == len(ch.passages) + 2
    assert passages[2:] == ch.passages


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
