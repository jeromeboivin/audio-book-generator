"""Plain-assertion checks for the experimental --narrator-tone feature:
guessing a single, chapter-wide Narrator instruct string from a small
sample of the Chapter's opening, applied uniformly to every Narrator
Chunk, off by default.

No pytest dependency — run directly: python tests/test_narrator_tone.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audiobook import annotation
from audiobook.cast import Cast
from audiobook.checkpoint import Checkpoint
from audiobook.chunking import build_chunks
from audiobook.main import NARRATOR_TONE_SAMPLE_PASSAGES, _narrator_tone_sample, _resolve_line
from audiobook.parsing import Passage


class _FakeChapter:
    def __init__(self, heading, title, passages):
        self.heading = heading
        self.title = title
        self.passages = passages


def test_no_narrator_instruct_means_none_not_a_default_string():
    """When narrator_instruct is None (--no-narrator-tone, or the Chapter's
    tone hasn't been guessed yet), _resolve_line must not silently
    substitute anything — Narrator Lines get instruct=None, exactly like
    before this feature existed."""
    narrator_line = {
        "speaker": "Narrator",
        "is_narrator": True,
        "speaker_gender": "male",
        "speaker_is_child": False,
        "text": "Il faisait beau.",
        "instruct": None,
    }
    cast = Cast()
    resolved = _resolve_line(narrator_line, cast)
    assert resolved.instruct is None, resolved.instruct


def test_narrator_tone_applied_only_to_narrator_lines():
    narrator_line = {
        "speaker": "Narrator",
        "is_narrator": True,
        "speaker_gender": "male",
        "speaker_is_child": False,
        "text": "Il faisait beau.",
        "instruct": None,
    }
    dialogue_line = {
        "speaker": "Marc",
        "is_narrator": False,
        "speaker_gender": "male",
        "speaker_is_child": False,
        "text": "Bonjour.",
        "instruct": "speak warmly.",
    }
    cast = Cast()
    tone = "Read in a calm, wistful, reflective tone throughout."

    resolved_narrator = _resolve_line(narrator_line, cast, tone)
    resolved_dialogue = _resolve_line(dialogue_line, cast, tone)

    assert resolved_narrator.instruct == tone
    # The chapter-wide tone must never leak into a dialogue Line's own
    # per-Line instruct.
    assert resolved_dialogue.instruct == "speak warmly."


def test_merged_narrator_chunk_carries_the_chapter_tone():
    """Once _resolve_line has applied the same tone to every Narrator
    Line, build_chunks must carry that same instruct through to the
    merged Chunk — not silently drop it back to None."""
    lines = [
        _resolve_line(
            {
                "speaker": "Narrator",
                "is_narrator": True,
                "speaker_gender": "male",
                "speaker_is_child": False,
                "text": "Chapitre I",
                "instruct": None,
            },
            Cast(),
            "Read in a calm, wistful tone.",
        ),
        _resolve_line(
            {
                "speaker": "Narrator",
                "is_narrator": True,
                "speaker_gender": "male",
                "speaker_is_child": False,
                "text": "Le Matin",
                "instruct": None,
            },
            Cast(),
            "Read in a calm, wistful tone.",
        ),
    ]
    chunks = build_chunks(lines, audio_cache_dir="/tmp/x", chapter_number=1)
    assert len(chunks) == 1
    assert chunks[0].instruct == "Read in a calm, wistful tone.", chunks[0].instruct
    assert chunks[0].text == "Chapitre I. Le Matin.", chunks[0].text


def test_narrator_tone_changes_chunk_hash_vs_no_tone():
    """A chunk with a narrator_instruct must NOT collide with the same
    text/voice synthesized with no instruct at all — otherwise turning
    --narrator-tone on or off between runs could wrongly reuse the other
    mode's cached audio."""
    line_no_tone = _resolve_line(
        {
            "speaker": "Narrator",
            "is_narrator": True,
            "speaker_gender": "male",
            "speaker_is_child": False,
            "text": "Il faisait beau.",
            "instruct": None,
        },
        Cast(),
        None,
    )
    line_with_tone = _resolve_line(
        {
            "speaker": "Narrator",
            "is_narrator": True,
            "speaker_gender": "male",
            "speaker_is_child": False,
            "text": "Il faisait beau.",
            "instruct": None,
        },
        Cast(),
        "Read in a calm, wistful tone.",
    )
    chunk_no_tone = build_chunks([line_no_tone], audio_cache_dir="/tmp/x", chapter_number=1)[0]
    chunk_with_tone = build_chunks([line_with_tone], audio_cache_dir="/tmp/x", chapter_number=1)[0]
    assert chunk_no_tone.audio_path != chunk_with_tone.audio_path


def test_sample_includes_heading_title_and_first_few_passages_only():
    passages = [Passage(text=f"Paragraph {i}", has_dialogue=False) for i in range(10)]
    chapter = _FakeChapter(heading="Chapitre I", title="Le Matin", passages=passages)
    sample = _narrator_tone_sample(chapter)
    assert sample.startswith("Chapitre I\nLe Matin\n")
    for i in range(NARRATOR_TONE_SAMPLE_PASSAGES):
        assert f"Paragraph {i}" in sample
    # Passages beyond the fixed sample size must not be included — this
    # is meant to be a cheap, quick guess, not a full read of the Chapter.
    assert f"Paragraph {NARRATOR_TONE_SAMPLE_PASSAGES}" not in sample


def test_sample_truncates_a_very_long_passage():
    huge_passage = Passage(text="x" * 5000, has_dialogue=False)
    chapter = _FakeChapter(heading="Chapitre I", title="Le Matin", passages=[huge_passage])
    sample = _narrator_tone_sample(chapter)
    assert len(sample) < 5000


def _fake_response(narrator_instruct):
    msg = mock.MagicMock()
    msg.content = json.dumps({"narrator_instruct": narrator_instruct})
    choice = mock.MagicMock()
    choice.message = msg
    resp = mock.MagicMock()
    resp.choices = [choice]
    return resp


def test_guess_narrator_tone_returns_the_instruct_string():
    client = mock.MagicMock()
    client.chat.completions.create.return_value = _fake_response("Calm and wistful throughout.")
    result = annotation.guess_narrator_tone(client, "Chapitre I\nLe Matin\nIl faisait beau.")
    assert result == "Calm and wistful throughout."


def test_guess_narrator_tone_retries_once_then_raises():
    client = mock.MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("API down")
    try:
        annotation.guess_narrator_tone(client, "sample")
        raised = False
    except annotation.AnnotationError:
        raised = True
    assert raised
    assert client.chat.completions.create.call_count == 2


def test_checkpoint_narrator_instruct_round_trip_and_persistence():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "test.checkpoint.json")
        ckpt = Checkpoint(path)
        assert ckpt.get_narrator_instruct(1) is None

        ckpt.set_narrator_instruct(1, "Calm and wistful throughout.")
        assert ckpt.get_narrator_instruct(1) == "Calm and wistful throughout."
        # A different chapter must not see chapter 1's tone.
        assert ckpt.get_narrator_instruct(2) is None

        # Reload from disk (simulates a resumed run) -- must still be there,
        # so a resumed run reuses the exact same tone rather than a fresh
        # (possibly different) guess.
        reloaded = Checkpoint(path)
        assert reloaded.get_narrator_instruct(1) == "Calm and wistful throughout."


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
