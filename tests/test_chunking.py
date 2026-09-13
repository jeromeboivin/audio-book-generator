"""Plain-assertion checks for chunking.build_chunks. No pytest dependency
(the project has none) — run directly:

    .venv-qwen-test/bin/python tests/test_chunking.py

Encodes the project owner's own worked example from the Chunk design
decision (ticket 06's 2026-09-13 amendment) as a real regression test:
consecutive Narrator Lines must merge into one Chunk, even across
Passage boundaries and even across the chapter-title/heading boundary,
breaking only where a real dialogue Line occurs.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audiobook.cast import Cast
from audiobook.chunking import AnnotatedLine, _ensure_sentence_end, build_chunks


def test_ensure_sentence_end_adds_period_only_when_unpunctuated():
    """Regression test: the project owner reported that a chapter heading,
    subtitle, or any paragraph not ending in a punctuation character (or an
    ellipsis) produced no pause when merged with adjacent Narrator text,
    because Qwen3-TTS reads straight through with no sentence-boundary cue.
    Only text with NO trailing punctuation at all should get a period
    appended; anything already ending in punctuation (including a colon or
    ellipsis) is left untouched."""
    assert _ensure_sentence_end("Chapitre I") == "Chapitre I."
    assert _ensure_sentence_end("Monsieur Myriel") == "Monsieur Myriel."
    assert _ensure_sentence_end("Already punctuated.") == "Already punctuated."
    assert _ensure_sentence_end("An exclamation!") == "An exclamation!"
    assert _ensure_sentence_end("A question?") == "A question?"
    assert _ensure_sentence_end("Trailing colon:") == "Trailing colon:"
    assert _ensure_sentence_end("Trailing comma,") == "Trailing comma,"
    assert _ensure_sentence_end("An ellipsis...") == "An ellipsis..."
    assert _ensure_sentence_end("Unicode ellipsis…") == "Unicode ellipsis…"
    assert _ensure_sentence_end("Trailing whitespace   ") == "Trailing whitespace."
    assert _ensure_sentence_end("") == ""


def test_owner_worked_example():
    """Title="Chapter X" (Narrator); body Passages in order:
    "Sub-title" (Narrator, from a non-title heading), "Paragraph 1"
    (Narrator), "Paragraph 2: —Dialog 1 —Dialog 2" (splits via annotation
    into Narrator "Paragraph 2:", Dialogue "Dialog 1", Dialogue "Dialog 2"),
    "Paragraph 3" (Narrator). Expected Chunks: exactly
    ["Chapter X. Sub-title. Paragraph 1. Paragraph 2:", "Dialog 1.",
    "Dialog 2.", "Paragraph 3."] — 4 Chunks. Each unpunctuated segment gets
    a period appended before merging (see `_ensure_sentence_end`) so
    Qwen3-TTS actually pauses at each internal boundary instead of reading
    straight through; "Paragraph 2:" already ends in punctuation (a colon)
    so it's left alone, not given a redundant second one."""
    lines = [
        AnnotatedLine(text="Chapter X", is_narrator=True, voice="Ryan", instruct=None, role="narrator"),
        AnnotatedLine(text="Sub-title", is_narrator=True, voice="Ryan", instruct=None, role="narrator"),
        AnnotatedLine(text="Paragraph 1", is_narrator=True, voice="Ryan", instruct=None, role="narrator"),
        AnnotatedLine(text="Paragraph 2:", is_narrator=True, voice="Ryan", instruct=None, role="narrator"),
        AnnotatedLine(text="Dialog 1", is_narrator=False, voice="Ryan", instruct="speak boldly.", role="adult_male"),
        AnnotatedLine(text="Dialog 2", is_narrator=False, voice="Serena", instruct="speak softly.", role="adult_female"),
        AnnotatedLine(text="Paragraph 3", is_narrator=True, voice="Ryan", instruct=None, role="narrator"),
    ]

    chunks = build_chunks(lines, audio_cache_dir="/tmp/does-not-matter", chapter_number=1)

    assert [c.text for c in chunks] == [
        "Chapter X. Sub-title. Paragraph 1. Paragraph 2:",
        "Dialog 1.",
        "Dialog 2.",
        "Paragraph 3.",
    ], [c.text for c in chunks]
    assert len(chunks) == 4
    assert [c.is_narrator for c in chunks] == [True, False, False, True]
    assert chunks[1].voice == "Ryan" and chunks[1].instruct == "speak boldly."
    assert chunks[2].voice == "Serena" and chunks[2].instruct == "speak softly."
    assert chunks[0].instruct is None and chunks[3].instruct is None
    assert chunks[0].voice == "Ryan" and chunks[3].voice == "Ryan"
    assert [c.role for c in chunks] == ["narrator", "adult_male", "adult_female", "narrator"]


def test_no_dialogue_produces_one_merged_chunk():
    lines = [
        AnnotatedLine(text="A", is_narrator=True, voice="Ryan", instruct=None, role="narrator"),
        AnnotatedLine(text="B", is_narrator=True, voice="Ryan", instruct=None, role="narrator"),
        AnnotatedLine(text="C", is_narrator=True, voice="Ryan", instruct=None, role="narrator"),
    ]
    chunks = build_chunks(lines, audio_cache_dir="/tmp/x", chapter_number=1)
    assert len(chunks) == 1, chunks
    assert chunks[0].text == "A. B. C."
    assert chunks[0].role == "narrator"


def test_no_raw_newline_ever_joins_merged_lines():
    """Ticket 04 already fixed a real audible-pause bug from embedded
    newlines being read as unwanted mid-sentence pauses; merging Lines
    into a Chunk must not reintroduce anything like it — join with a
    single space, never '\\n'."""
    lines = [
        AnnotatedLine(text="First.", is_narrator=True, voice="Ryan", instruct=None, role="narrator"),
        AnnotatedLine(text="Second.", is_narrator=True, voice="Ryan", instruct=None, role="narrator"),
    ]
    chunks = build_chunks(lines, audio_cache_dir="/tmp/x", chapter_number=1)
    assert "\n" not in chunks[0].text
    assert chunks[0].text == "First. Second."


def test_leading_and_trailing_dialogue():
    lines = [
        AnnotatedLine(text="Bonjour", is_narrator=False, voice="Ryan", instruct="warmly.", role="adult_male"),
        AnnotatedLine(text="Middle narration", is_narrator=True, voice="Ryan", instruct=None, role="narrator"),
        AnnotatedLine(text="Au revoir", is_narrator=False, voice="Serena", instruct="sadly.", role="adult_female"),
    ]
    chunks = build_chunks(lines, audio_cache_dir="/tmp/x", chapter_number=1)
    assert [c.text for c in chunks] == ["Bonjour.", "Middle narration.", "Au revoir."]
    assert [c.is_narrator for c in chunks] == [False, True, False]
    assert [c.role for c in chunks] == ["adult_male", "narrator", "adult_female"]


def test_all_dialogue_produces_one_chunk_per_line():
    lines = [
        AnnotatedLine(text="Un", is_narrator=False, voice="Ryan", instruct="a.", role="adult_male"),
        AnnotatedLine(text="Deux", is_narrator=False, voice="Serena", instruct="b.", role="adult_female"),
    ]
    chunks = build_chunks(lines, audio_cache_dir="/tmp/x", chapter_number=1)
    assert len(chunks) == 2
    assert chunks[0].text == "Un." and chunks[1].text == "Deux."


def test_empty_input_produces_no_chunks():
    assert build_chunks([], audio_cache_dir="/tmp/x", chapter_number=1) == []


def test_determinism_same_input_same_audio_path():
    lines = [AnnotatedLine(text="Hello world", is_narrator=True, voice="Ryan", instruct=None, role="narrator")]
    c1 = build_chunks(lines, audio_cache_dir="/tmp/x", chapter_number=1)
    c2 = build_chunks(lines, audio_cache_dir="/tmp/x", chapter_number=1)
    assert c1[0].audio_path == c2[0].audio_path


def test_same_text_different_voice_gets_different_audio_path():
    """Deviation from the ticket's literal wording ("sha256-of-chunk-text"):
    the hash also folds in voice/instruct/is_narrator, not just raw text,
    to avoid two different Speakers who happen to say the exact same short
    line (e.g. both say "Oui.") colliding on one cached audio file and
    incorrectly reusing each other's synthesized voice."""
    a = AnnotatedLine(text="Oui.", is_narrator=False, voice="Ryan", instruct="curtly.", role="adult_male")
    b = AnnotatedLine(text="Oui.", is_narrator=False, voice="Serena", instruct="curtly.", role="adult_female")
    ca = build_chunks([a], audio_cache_dir="/tmp/x", chapter_number=1)
    cb = build_chunks([b], audio_cache_dir="/tmp/x", chapter_number=1)
    assert ca[0].audio_path != cb[0].audio_path


def test_audio_filename_has_role_prefix_then_hash():
    """Filename shape: `chunk_{role}_{hash}.wav` — role is a human-readable
    PREFIX only (not a hash input, see cast.py/chunking.py's 2026-09-13
    amendment for ticket 05), so the project owner can visually identify
    and bulk-delete a category of cached chunk files (e.g.
    `chunk_adult_female_*.wav`) after changing that role's voice in
    voices.json."""
    narrator_line = AnnotatedLine(text="Il faisait beau.", is_narrator=True, voice="Ryan", instruct=None, role="narrator")
    male_line = AnnotatedLine(text="Bonjour.", is_narrator=False, voice="Ryan", instruct="warmly.", role="adult_male")
    female_line = AnnotatedLine(text="Bonjour.", is_narrator=False, voice="Serena", instruct="warmly.", role="adult_female")
    child_line = AnnotatedLine(text="Coucou !", is_narrator=False, voice="Vivian", instruct="playfully.", role="child")

    n_chunk = build_chunks([narrator_line], audio_cache_dir="/tmp/x", chapter_number=1)[0]
    m_chunk = build_chunks([male_line], audio_cache_dir="/tmp/x", chapter_number=1)[0]
    f_chunk = build_chunks([female_line], audio_cache_dir="/tmp/x", chapter_number=1)[0]
    c_chunk = build_chunks([child_line], audio_cache_dir="/tmp/x", chapter_number=1)[0]

    assert os.path.basename(n_chunk.audio_path).startswith("chunk_narrator_")
    assert os.path.basename(m_chunk.audio_path).startswith("chunk_adult_male_")
    assert os.path.basename(f_chunk.audio_path).startswith("chunk_adult_female_")
    assert os.path.basename(c_chunk.audio_path).startswith("chunk_child_")
    for chunk in (n_chunk, m_chunk, f_chunk, c_chunk):
        assert chunk.audio_path.endswith(".wav")


def test_voices_json_change_orphans_old_chunk_instead_of_colliding():
    """Regression test for ticket 07's amendment: changing a role-voice in
    voices.json must NOT force regeneration of already-synthesized Chunk
    audio, and must never collide with or overwrite the old file — the old
    Chunk's audio_path stays a distinct, valid, if now-orphaned, path.

    Builds two Chunks with the same text/is_narrator but two different
    `adult_female` Cast configs (simulating a `voices.json` edit between
    runs), and confirms they resolve to two DIFFERENT audio_paths."""
    cast_before = Cast(voice_config={"adult_female": "Serena"})
    cast_after = Cast(voice_config={"adult_female": "Vivian"})

    line_before = AnnotatedLine(
        text="Bonjour, comment ca va ?",
        is_narrator=False,
        voice=cast_before.voice_for("Léa", "female", False, is_narrator=False),
        instruct="warmly.",
        role=cast_before.role_for("female", False, is_narrator=False),
    )
    line_after = AnnotatedLine(
        text="Bonjour, comment ca va ?",
        is_narrator=False,
        voice=cast_after.voice_for("Léa", "female", False, is_narrator=False),
        instruct="warmly.",
        role=cast_after.role_for("female", False, is_narrator=False),
    )

    chunk_before = build_chunks([line_before], audio_cache_dir="/tmp/x", chapter_number=1)[0]
    chunk_after = build_chunks([line_after], audio_cache_dir="/tmp/x", chapter_number=1)[0]

    assert chunk_before.voice == "Serena" and chunk_after.voice == "Vivian"
    assert chunk_before.audio_path != chunk_after.audio_path
    # Both are still labeled by the same ROLE prefix (adult_female) — only
    # the hash differs, since the resolved voice differs.
    assert os.path.basename(chunk_before.audio_path).startswith("chunk_adult_female_")
    assert os.path.basename(chunk_after.audio_path).startswith("chunk_adult_female_")


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
