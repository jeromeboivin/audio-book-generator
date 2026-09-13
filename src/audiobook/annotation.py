import json
import os

from openai import OpenAI

DEFAULT_MODEL = "gpt-5.6-luna"

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
telling the TTS engine (Qwen3-TTS CustomVoice) how to perform it.

Qwen3-TTS's own published examples show a single generic adjective ("Very happy.") works
but under-uses what the model actually follows — richer instructions covering MULTIPLE
performance dimensions produce noticeably more controlled, expressive speech. Cover, when
relevant to this specific Line (don't pad mechanically if a dimension genuinely doesn't
apply):
  - **emotion** — the core feeling (required every time)
  - **pace** — fast/slow/hesitant/rushed, and whether it changes during the Line
  - **volume** — loud/quiet/whispered, and whether it changes during the Line
  - **delivery quality** — trembling, breathless, laughing, choked up, sharp, clipped, etc.
  - **trajectory** — if the Line's own text shows the character's feeling shift partway
    through (e.g. calm opening, anger by the end), describe that arc rather than only the
    Line's final tone — Qwen3-TTS supports this "gradual control" pattern directly.
Do NOT describe gender, age, accent, or vocal identity/timbre in `instruct` — the Voice
(and therefore that identity) is already fixed by which character is speaking, not by this
string; only describe HOW to perform the line, never WHO is speaking it.
Match length to what the Line actually needs: a short, simple exclamation is well served by
one clause ("Speak with quiet dread."); a longer or emotionally complex Line is well served
by two or three clauses combining several of the dimensions above. Never restate the
Line's own words, only how to perform them. Examples (both are valid `instruct` strings,
depending on what the Line calls for):
  - "Speak with quiet dread."
  - "A hushed, urgent whisper — quiet almost to the point of being inaudible, tense and
    secretive, words clipped short."
  - "Start measured and controlled, then let volume and pace rise sharply as anger takes
    over, voice growing sharper and more clipped toward the end."

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

The user message may begin with a block labeled "Immediately preceding line (for
tone/situation only):" containing the single Line that came right before this Passage
(whatever was last said or narrated — from earlier in the Chapter, not necessarily this
Passage), followed by a block labeled "Passage to annotate:" containing the actual
Passage. This is a recency window, not a running history: if speaker B speaks right
after speaker A, judging B's tone needs what A just said, not the whole chapter so far.
Use it ONLY to inform the `instruct` strings and gender/child judgments you produce;
never annotate it, never include any of its text in your response — your `lines` output
must reconstruct only the "Passage to annotate" block, exactly as before. If there is no
such block, this is the Chapter's first Passage — annotate normally.

The SAME recency principle applies within this Passage's own breakdown, if it contains
more than one Line: judge each Line's tone primarily against whatever came immediately
before it (the "Immediately preceding line" block for the first Line in your output; the
previous Line in your OWN output for every Line after that) — not against the Passage's
overall narrative arc or anything further back.

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


def _build_user_message(passage_text: str, preceding_line: str | None) -> str:
    if not preceding_line:
        return passage_text
    return (
        f"Immediately preceding line (for tone/situation only):\n{preceding_line}\n\n"
        f"Passage to annotate:\n{passage_text}"
    )


def _call_openai(
    client: OpenAI, passage_text: str, roster: list[str], preceding_line: str | None, model: str
) -> dict:
    roster_str = ", ".join(roster) if roster else "(none yet)"
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT.format(roster=roster_str)},
            {"role": "user", "content": _build_user_message(passage_text, preceding_line)},
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
    preceding_line: str | None = None,
    model: str = DEFAULT_MODEL,
) -> dict:
    """Runs the Annotation Pass (OpenAI call, retried once) for a Passage
    that's already been determined to need one (`passage.has_dialogue`,
    computed by parsing.py from the raw pre-collapse text — this function
    no longer re-derives that decision from `passage_text`). Callers that
    don't need an Annotation Pass call `short_circuit_narrator` instead.

    `preceding_line`: the text of the single Line that immediately preceded
    this Passage (or None for the Chapter's first Passage) — NOT the whole
    previous Passage's text, and NOT everything narrated so far. A recency
    window of exactly one: if speaker B speaks right after speaker A,
    judging B's tone needs what A just said, not the whole chapter-so-far
    (too much) and not necessarily the whole previous Passage either, if
    that Passage itself had several Lines — only its last one is what's
    actually adjacent. This is situational context only: the model must not
    annotate it, only the Passage this call is actually about (see the
    system prompt).

    `model`: the OpenAI model id to use, configurable (see main.py's
    `--openai-model` flag / `OPENAI_MODEL` env var) — defaults to
    `DEFAULT_MODEL`. Any model used here must support structured outputs
    (`response_format={"type": "json_schema", ...}`)."""
    last_error = None
    for attempt in range(2):
        try:
            return _call_openai(client, passage_text, roster, preceding_line, model)
        except Exception as e:
            last_error = e
    raise AnnotationError(
        f"Annotation Pass failed twice for passage (aborting run, no silent Narrator fallback): {last_error}"
    ) from last_error


NARRATOR_TONE_SCHEMA = {
    "name": "narrator_tone",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "narrator_instruct": {"type": "string"},
        },
        "required": ["narrator_instruct"],
        "additionalProperties": False,
    },
}

NARRATOR_TONE_SYSTEM_PROMPT = """You read a short sample of a Chapter from a French
novel: its heading/title plus its first few paragraphs (not the whole Chapter).

Produce a SHORT natural-language `instruct` string describing the overall tone/mood/pace
the Narrator should maintain while reading this ENTIRE Chapter aloud — one or two clauses,
in the same style as a Qwen3-TTS instruct string (e.g. "Read in a calm, wistful, reflective
tone throughout." or "Maintain a brisk, matter-of-fact narrative pace with an undercurrent
of tension.").

This is a SINGLE, Chapter-wide instruction, not a per-moment one: describe the general
atmosphere/register the whole Chapter's narration should sit in, not any single sentence's
specific emotion — that's decided separately, per dialogue Line, elsewhere. Keep it short."""


def guess_narrator_tone(client: OpenAI, sample_text: str, model: str = DEFAULT_MODEL) -> str:
    """One extra OpenAI call, made once per Chapter — not per Passage/Line
    — that asks the model to guess the Chapter's overall narrative tone
    from a small, fixed sample of its opening (heading/title + first few
    Passages) and produce a single short `instruct` string. That one
    string is then applied to EVERY Narrator Chunk in the Chapter (see
    main.py's `_resolve_line`), for consistency — a Chapter's narration
    shouldn't randomly shift register from one Chunk to the next. On by
    default (see main.py's `--narrator-tone`/`--no-narrator-tone` flag) —
    validated by ear against the sample book and judged an improvement
    over no instruct at all.

    Retried once then raises, same "fail loudly, no silent fallback"
    policy as `annotate_passage` — silently degrading to "no tone" would
    be a worse surprise than the run just stopping."""
    last_error = None
    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": NARRATOR_TONE_SYSTEM_PROMPT},
                    {"role": "user", "content": sample_text},
                ],
                response_format={"type": "json_schema", "json_schema": NARRATOR_TONE_SCHEMA},
            )
            data = json.loads(resp.choices[0].message.content)
            instruct = data.get("narrator_instruct")
            if not instruct:
                raise AnnotationError("narrator tone response missing non-empty 'narrator_instruct'")
            return instruct
        except Exception as e:
            last_error = e
    raise AnnotationError(f"Narrator tone guess failed twice (aborting run): {last_error}") from last_error


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
