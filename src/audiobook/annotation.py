import json
import os

from openai import OpenAI

MODEL = "gpt-4o"

SCHEMA = {
    "name": "passage_lines",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "speaker": {"type": "string"},
                        "is_narrator": {"type": "boolean"},
                        "speaker_gender": {"type": "string", "enum": ["male", "female"]},
                        "speaker_is_child": {"type": "boolean"},
                        "text": {"type": "string"},
                        "instruct": {"type": ["string", "null"]},
                    },
                    "required": [
                        "speaker",
                        "is_narrator",
                        "speaker_gender",
                        "speaker_is_child",
                        "text",
                        "instruct",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["lines"],
        "additionalProperties": False,
    },
}

SYSTEM_PROMPT = """You annotate one Passage (one paragraph) of a French novel for audiobook narration.

Break the Passage into an ordered list of Lines. Each Line has exactly one Speaker.
The Narrator is a Speaker like any other (is_narrator=true, speaker="Narrator", instruct=null).
A dialogue Line (any non-Narrator speaker) must carry a natural-language `instruct` string
describing the tone/emotion to speak it with, expressed as exactly ONE SENTENCE (e.g. "speak
with hesitant relief.").

French dialogue is marked with a leading em-dash (—). A common pattern is a mid-quote
narrator attribution tag (an "incise") that interrupts a single character's utterance
without a new em-dash, e.g. "dit M. Myriel" ("said M. Myriel") or "s'écria-t-il" ("he
exclaimed"). Keep an incise as part of the SAME dialogue Line as the quote around it —
do NOT split it out into a separate Narrator Line. The whole utterance, incise included,
is spoken by the character in one Line (switching TTS voices for just the 2-3 words of
an attribution tag produces bad, jarring audio). Example input:

  —Sire, dit M. Myriel, vous regardez un bonhomme, et moi je regarde un grand homme.

This must be exactly ONE Line:
  1. speaker=<the character>, is_narrator=false, text="Sire, dit M. Myriel, vous regardez un bonhomme, et moi je regarde un grand homme."
(the incise "dit M. Myriel" stays inline, verbatim, spoken by the character — not pulled
out into a separate Narrator Line)

Only a genuinely NEW dialogue turn — a new leading em-dash, or a different Speaker
actually starting to talk — begins a new Line. A mid-quote attribution tag by itself
never does; it's absorbed into the surrounding character's Line as shown above.

Maintain consistent Speaker names: known speakers so far in this Chapter are: {roster}.
If a Line refers to one of these speakers (by name, pronoun, title, or description), use
that exact canonical name. Only introduce a new name if the Passage clearly introduces a
new Speaker not in that list.

The user message may begin with a block labeled "Preceding context (for tone/situation
only):" containing the immediately preceding Passage's text, followed by a block labeled
"Passage to annotate:" containing the actual Passage. The preceding context is there
purely so you can judge tone correctly — dialogue read in isolation, with no idea what
just happened, often gets the wrong emotional register (a human reading it cold would
have the same problem). Use it ONLY to inform the `instruct` strings and gender/child
judgments you produce; never annotate it, never include any of its text in your response
— your `lines` output must reconstruct only the "Passage to annotate" block, exactly as
before. If there is no such block, there was no preceding Passage (this is the first
Passage of the Chapter) — annotate normally.

Every Line must have speaker_gender ("male" or "female") and speaker_is_child (bool) filled
in based on context, even for the Narrator (ignored for Narrator Lines downstream, but still
required by the schema).

Preserve the Passage's text content across all Lines exactly (concatenating all Lines'
text, in order, with whitespace normalized, reproduces the original Passage)."""


class AnnotationError(Exception):
    pass


def short_circuit_narrator(passage_text: str) -> dict:
    return {
        "lines": [
            {
                "speaker": "Narrator",
                "is_narrator": True,
                "speaker_gender": "male",
                "speaker_is_child": False,
                "text": passage_text,
                "instruct": None,
            }
        ]
    }


def _build_user_message(passage_text: str, preceding_context: str | None) -> str:
    if not preceding_context:
        return passage_text
    return (
        f"Preceding context (for tone/situation only):\n{preceding_context}\n\n"
        f"Passage to annotate:\n{passage_text}"
    )


def _call_openai(
    client: OpenAI, passage_text: str, roster: list[str], preceding_context: str | None
) -> dict:
    roster_str = ", ".join(roster) if roster else "(none yet)"
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT.format(roster=roster_str)},
            {"role": "user", "content": _build_user_message(passage_text, preceding_context)},
        ],
        response_format={"type": "json_schema", "json_schema": SCHEMA},
    )
    content = resp.choices[0].message.content
    data = json.loads(content)
    _validate(data)
    return data


def _validate(data: dict) -> None:
    if "lines" not in data or not isinstance(data["lines"], list) or not data["lines"]:
        raise AnnotationError("annotation response missing non-empty 'lines' array")
    for line in data["lines"]:
        for key in ("speaker", "is_narrator", "speaker_gender", "speaker_is_child", "text", "instruct"):
            if key not in line:
                raise AnnotationError(f"line missing required key '{key}': {line}")
        if line["speaker_gender"] not in ("male", "female"):
            raise AnnotationError(f"invalid speaker_gender: {line}")


def annotate_passage(
    client: OpenAI,
    passage_text: str,
    roster: list[str],
    preceding_context: str | None = None,
) -> dict:
    """Runs the Annotation Pass (OpenAI call, retried once) for a Passage
    that's already been determined to need one (`passage.has_dialogue`,
    computed by parsing.py from the raw pre-collapse text — this function
    no longer re-derives that decision from `passage_text`). Callers that
    don't need an Annotation Pass call `short_circuit_narrator` instead.

    `preceding_context`: the immediately preceding Passage's text (or None
    for the Chapter's first Passage), included so the model can judge tone
    correctly — a line of dialogue read with no idea what just happened
    often gets the wrong emotional register, the same problem a human cold
    reader would have. This is situational context only: the model must not
    annotate it, only the Passage this call is actually about (see the
    system prompt)."""
    last_error = None
    for attempt in range(2):
        try:
            return _call_openai(client, passage_text, roster, preceding_context)
        except Exception as e:
            last_error = e
    raise AnnotationError(
        f"Annotation Pass failed twice for passage (aborting run, no silent Narrator fallback): {last_error}"
    ) from last_error


def make_client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise AnnotationError("OPENAI_API_KEY not set in environment")
    return OpenAI(api_key=api_key)


def update_roster(roster: list[str], lines: list[dict]) -> list[str]:
    for line in lines:
        name = line["speaker"]
        if name not in roster:
            roster.append(name)
    return roster
