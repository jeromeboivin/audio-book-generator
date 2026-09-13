"""Regression test: main.py's Phase 1 must track the *last Line* of each
Passage as context for the next call, not the whole Passage's original
text — the exact bug the project owner's worked example exposed (a
Passage with several Lines was being passed to the NEXT Passage's
Annotation Pass call in full, over-including everything, not just what's
actually adjacent: its final Line).

No pytest dependency — run directly: python tests/test_prev_line_tracking.py
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audiobook import main as m
from audiobook.cast import Cast
from audiobook.checkpoint import Checkpoint
from audiobook.parsing import Passage

FIRST_PASSAGE_LINES = {
    "lines": [
        {
            "speaker": "Narrator",
            "is_narrator": True,
            "speaker_gender": "male",
            "speaker_is_child": False,
            "text": "Il faisait beau ce matin-la.",
            "instruct": None,
        },
        {
            "speaker": "Marc",
            "is_narrator": False,
            "speaker_gender": "male",
            "speaker_is_child": False,
            "text": "Quelle belle journee !",
            "instruct": "speak with cheerful energy.",
        },
    ]
}

SECOND_PASSAGE_LINES = {
    "lines": [
        {
            "speaker": "Lea",
            "is_narrator": False,
            "speaker_gender": "female",
            "speaker_is_child": False,
            "text": "Oui, magnifique.",
            "instruct": "speak with warm agreement.",
        },
    ]
}


def test_preceding_line_is_last_line_not_whole_passage():
    captured_preceding_lines = []

    def fake_annotate_passage(client, passage_text, roster, preceding_line=None):
        captured_preceding_lines.append(preceding_line)
        if passage_text == "PASSAGE_ONE":
            return FIRST_PASSAGE_LINES
        return SECOND_PASSAGE_LINES

    passages = [
        Passage(text="PASSAGE_ONE", has_dialogue=True),
        Passage(text="PASSAGE_TWO", has_dialogue=True),
    ]

    with tempfile.TemporaryDirectory() as tmp:
        checkpoint = Checkpoint(os.path.join(tmp, "test.checkpoint.json"))
        cast = Cast(overrides={})

        with mock.patch("audiobook.annotation.make_client", return_value=object()), mock.patch(
            "audiobook.annotation.annotate_passage", side_effect=fake_annotate_passage
        ):
            m._phase1_annotate_and_assign_voices(passages, 1, len(passages), checkpoint, [], cast)

    # First call (passage 0) has no predecessor.
    assert captured_preceding_lines[0] is None, captured_preceding_lines

    # Second call (passage 1) must receive PASSAGE_ONE's *last Line's text*
    # ("Quelle belle journee !"), not the original whole-passage text
    # ("PASSAGE_ONE") and not a concatenation of both its Lines.
    assert captured_preceding_lines[1] == "Quelle belle journee !", captured_preceding_lines


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
