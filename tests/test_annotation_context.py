"""Regression test: the Annotation Pass must include the immediately
preceding Passage's text as situational context when annotating a
dialogue-bearing Passage, per the project owner's feedback that a Passage
read in isolation (no idea what just happened) makes it hard even for a
human to judge the correct tone.

No pytest dependency — run directly: python tests/test_annotation_context.py
"""

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audiobook import annotation


def _fake_response(lines):
    import json

    msg = mock.MagicMock()
    msg.content = json.dumps({"lines": lines})
    choice = mock.MagicMock()
    choice.message = msg
    resp = mock.MagicMock()
    resp.choices = [choice]
    return resp


SAMPLE_LINE = {
    "speaker": "Marc",
    "is_narrator": False,
    "speaker_gender": "male",
    "speaker_is_child": False,
    "text": "Bonjour.",
    "instruct": "Speak warmly.",
}


def test_no_preceding_context_sends_plain_passage():
    client = mock.MagicMock()
    client.chat.completions.create.return_value = _fake_response([SAMPLE_LINE])

    annotation.annotate_passage(client, "—Bonjour. dit Marc.", roster=[], preceding_context=None)

    sent = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert sent == "—Bonjour. dit Marc.", sent
    assert "Preceding context" not in sent


def test_preceding_context_is_included_and_labeled():
    client = mock.MagicMock()
    client.chat.completions.create.return_value = _fake_response([SAMPLE_LINE])

    annotation.annotate_passage(
        client,
        "—Bonjour. dit Marc.",
        roster=["Marc"],
        preceding_context="Léa venait d'apprendre une terrible nouvelle.",
    )

    sent = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "Preceding context (for tone/situation only):" in sent
    assert "Léa venait d'apprendre une terrible nouvelle." in sent
    assert "Passage to annotate:" in sent
    assert sent.index("Preceding context") < sent.index("Passage to annotate"), sent
    assert sent.rstrip().endswith("—Bonjour. dit Marc."), sent


def test_system_prompt_explains_the_context_block():
    normalized = " ".join(annotation.SYSTEM_PROMPT.split())
    assert "Preceding context (for tone/situation only):" in normalized
    assert "never annotate it" in normalized


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
