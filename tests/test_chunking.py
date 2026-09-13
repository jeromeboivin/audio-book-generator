"""Plain-assertion checks for chunking.build_chunks. No pytest dependency
(the project has none) — run directly:

    .venv-qwen-test/bin/python tests/test_chunking.py

Encodes the project owner's own worked example from the Chunk design
decision (ticket 06's 2026-09-13 amendment) as a real regression test:
consecutive Narrator Lines must merge into one Chunk, even across
Passage boundaries and even across the chapter-title/heading boundary,
breaking only where a real dialogue Line occurs.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audiobook.chunking import AnnotatedLine, build_chunks


def test_owner_worked_example():
    """Title="Chapter X" (Narrator); body Passages in order:
    "Sub-title" (Narrator, from a non-title heading), "Paragraph 1"
    (Narrator), "Paragraph 2: —Dialog 1 —Dialog 2" (splits via annotation
    into Narrator "Paragraph 2:", Dialogue "Dialog 1", Dialogue "Dialog 2"),
    "Paragraph 3" (Narrator). Expected Chunks: exactly
    ["Chapter X Sub-title Paragraph 1 Paragraph 2:", "Dialog 1", "Dialog 2",
    "Paragraph 3"] — 4 Chunks."""
    lines = [
        AnnotatedLine(text="Chapter X", is_narrator=True, voice="Uncle_Fu", instruct=None),
        AnnotatedLine(text="Sub-title", is_narrator=True, voice="Uncle_Fu", instruct=None),
        AnnotatedLine(text="Paragraph 1", is_narrator=True, voice="Uncle_Fu", instruct=None),
        AnnotatedLine(text="Paragraph 2:", is_narrator=True, voice="Uncle_Fu", instruct=None),
        AnnotatedLine(text="Dialog 1", is_narrator=False, voice="Ryan", instruct="speak boldly."),
        AnnotatedLine(text="Dialog 2", is_narrator=False, voice="Serena", instruct="speak softly."),
        AnnotatedLine(text="Paragraph 3", is_narrator=True, voice="Uncle_Fu", instruct=None),
    ]

    chunks = build_chunks(lines, audio_cache_dir="/tmp/does-not-matter", chapter_number=1)

    assert [c.text for c in chunks] == [
        "Chapter X Sub-title Paragraph 1 Paragraph 2:",
        "Dialog 1",
        "Dialog 2",
        "Paragraph 3",
    ], [c.text for c in chunks]
    assert len(chunks) == 4
    assert [c.is_narrator for c in chunks] == [True, False, False, True]
    assert chunks[1].voice == "Ryan" and chunks[1].instruct == "speak boldly."
    assert chunks[2].voice == "Serena" and chunks[2].instruct == "speak softly."
    assert chunks[0].instruct is None and chunks[3].instruct is None
    assert chunks[0].voice == "Uncle_Fu" and chunks[3].voice == "Uncle_Fu"


def test_no_dialogue_produces_one_merged_chunk():
    lines = [
        AnnotatedLine(text="A", is_narrator=True, voice="Uncle_Fu", instruct=None),
        AnnotatedLine(text="B", is_narrator=True, voice="Uncle_Fu", instruct=None),
        AnnotatedLine(text="C", is_narrator=True, voice="Uncle_Fu", instruct=None),
    ]
    chunks = build_chunks(lines, audio_cache_dir="/tmp/x", chapter_number=1)
    assert len(chunks) == 1, chunks
    assert chunks[0].text == "A B C"


def test_no_raw_newline_ever_joins_merged_lines():
    """Ticket 04 already fixed a real audible-pause bug from embedded
    newlines being read as unwanted mid-sentence pauses; merging Lines
    into a Chunk must not reintroduce anything like it — join with a
    single space, never '\\n'."""
    lines = [
        AnnotatedLine(text="First.", is_narrator=True, voice="Uncle_Fu", instruct=None),
        AnnotatedLine(text="Second.", is_narrator=True, voice="Uncle_Fu", instruct=None),
    ]
    chunks = build_chunks(lines, audio_cache_dir="/tmp/x", chapter_number=1)
    assert "\n" not in chunks[0].text
    assert chunks[0].text == "First. Second."


def test_leading_and_trailing_dialogue():
    lines = [
        AnnotatedLine(text="Bonjour", is_narrator=False, voice="Ryan", instruct="warmly."),
        AnnotatedLine(text="Middle narration", is_narrator=True, voice="Uncle_Fu", instruct=None),
        AnnotatedLine(text="Au revoir", is_narrator=False, voice="Serena", instruct="sadly."),
    ]
    chunks = build_chunks(lines, audio_cache_dir="/tmp/x", chapter_number=1)
    assert [c.text for c in chunks] == ["Bonjour", "Middle narration", "Au revoir"]
    assert [c.is_narrator for c in chunks] == [False, True, False]


def test_all_dialogue_produces_one_chunk_per_line():
    lines = [
        AnnotatedLine(text="Un", is_narrator=False, voice="Ryan", instruct="a."),
        AnnotatedLine(text="Deux", is_narrator=False, voice="Serena", instruct="b."),
    ]
    chunks = build_chunks(lines, audio_cache_dir="/tmp/x", chapter_number=1)
    assert len(chunks) == 2
    assert chunks[0].text == "Un" and chunks[1].text == "Deux"


def test_empty_input_produces_no_chunks():
    assert build_chunks([], audio_cache_dir="/tmp/x", chapter_number=1) == []


def test_determinism_same_input_same_audio_path():
    lines = [AnnotatedLine(text="Hello world", is_narrator=True, voice="Uncle_Fu", instruct=None)]
    c1 = build_chunks(lines, audio_cache_dir="/tmp/x", chapter_number=1)
    c2 = build_chunks(lines, audio_cache_dir="/tmp/x", chapter_number=1)
    assert c1[0].audio_path == c2[0].audio_path


def test_same_text_different_voice_gets_different_audio_path():
    """Deviation from the ticket's literal wording ("sha256-of-chunk-text"):
    the hash also folds in voice/instruct/is_narrator, not just raw text,
    to avoid two different Speakers who happen to say the exact same short
    line (e.g. both say "Oui.") colliding on one cached audio file and
    incorrectly reusing each other's synthesized voice."""
    a = AnnotatedLine(text="Oui.", is_narrator=False, voice="Ryan", instruct="curtly.")
    b = AnnotatedLine(text="Oui.", is_narrator=False, voice="Serena", instruct="curtly.")
    ca = build_chunks([a], audio_cache_dir="/tmp/x", chapter_number=1)
    cb = build_chunks([b], audio_cache_dir="/tmp/x", chapter_number=1)
    assert ca[0].audio_path != cb[0].audio_path


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
