"""Regression test: EPUB3 semantic-section chapter detection (added
2026-09-13 to unblock a real target book, L'Autre Moi - Franck Thilliez,
whose chapters are each their own file wrapped in
`<section epub:type="chapter">` with a bare-number heading and no separate
subtitle — a structure the original Gutenberg-style `<h2>`+`<h3>`
"Chapitre N" / title detection never matches at all).

Uses `tests/fixtures/synthetic_semantic_book.epub`: 2 tiny chapters built
with this convention (bare "1"/"2" headings, no subtitle, one dialogue
exchange each, matching the style of the original
`tests/fixtures/synthetic_book.epub`), plus a differently-typed
`<section epub:type="preface">` section that must NOT be counted as a
chapter.

No pytest dependency — run directly:
python tests/test_semantic_section_parsing.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audiobook.main import _build_narration_passages
from audiobook.parsing import count_chapters, extract_chapter

FIXTURE = str(Path(__file__).resolve().parent / "fixtures" / "synthetic_semantic_book.epub")


def test_count_chapters_excludes_the_preface():
    # The fixture has 3 <section> elements total (preface + 2 chapters) but
    # only 2 carry epub:type="chapter" — the preface section
    # (epub:type="preface") must not be counted.
    assert count_chapters(FIXTURE) == 2, count_chapters(FIXTURE)


def test_chapter_one_found_via_semantic_section():
    ch = extract_chapter(FIXTURE, 1)
    assert ch.heading == "1", ch.heading
    # This book's chapters have no separate subtitle at all — title must
    # be empty, never fabricated.
    assert ch.title == "", ch.title
    assert len(ch.passages) == 3, [p.text for p in ch.passages]


def test_chapter_two_found_via_semantic_section():
    ch = extract_chapter(FIXTURE, 2)
    assert ch.heading == "2", ch.heading
    assert ch.title == "", ch.title
    assert len(ch.passages) == 3, [p.text for p in ch.passages]


def test_third_chapter_does_not_exist():
    try:
        extract_chapter(FIXTURE, 3)
        raise AssertionError("expected ValueError for chapter 3")
    except ValueError as e:
        assert "2 chapter" in str(e), e


def test_dialogue_exchange_flagged_in_each_chapter():
    ch1 = extract_chapter(FIXTURE, 1)
    ch2 = extract_chapter(FIXTURE, 2)
    assert sum(1 for p in ch1.passages if p.has_dialogue) == 1
    assert sum(1 for p in ch2.passages if p.has_dialogue) == 1


def test_empty_title_produces_no_spurious_title_passage():
    ch = extract_chapter(FIXTURE, 1)
    passages = _build_narration_passages(ch)
    # heading passage + 3 body passages, no title passage in between since
    # chapter.title == "".
    assert len(passages) == len(ch.passages) + 1, [p.text for p in passages]
    assert passages[0].text == "1", passages[0].text
    assert passages[0].has_dialogue is False
    assert passages[1:] == ch.passages
    assert not any(p.text == "" for p in passages)


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
