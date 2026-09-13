# Design the OpenAI annotation contract

Type: grilling
Status: resolved
Blocked by: (none)

## Question

Design the Annotation Pass: the OpenAI call made per dialogue-bearing
Passage. Needs to settle:

- **Input/output schema**: a Passage's raw text in; a structured, ordered
  list of Lines out, each either a pass-through Narrator Line or a dialogue
  Line carrying a Speaker name and an Instruct String. Use OpenAI structured
  outputs (JSON schema) rather than free-text parsing.
- **Model choice**: which OpenAI model (cost vs quality trade-off, given
  cost is "reasonable for personal use" not a hard budget).
- **Speaker identity normalization**: how "Marie", "she", "the old woman"
  across different Lines resolve to the same canonical Speaker (needed for
  the Cast to stay consistent per character across the whole book) —
  likely needs some running context/memory passed into later calls, not
  just per-Passage isolation.
- **Cost short-circuit**: Passages that are pure narration (no dialogue)
  should skip the OpenAI call entirely and go straight to synthesis as a
  Narrator Line, to avoid wasting calls.
- **Failure handling**: what happens when OpenAI's attribution is
  ambiguous, wrong, or the structured output doesn't validate — sketch the
  fallback (e.g. default to Narrator, retry once, flag for manual review)
  even if full robustness is deferred.

Note: the Instruct String's exact phrasing/format may need to match
whatever the chosen TTS engine expects (see the TTS engine selection
ticket) — note that dependency in the answer if it applies, but don't block
this ticket on it; the schema and general approach can be decided
independently.

## Answer

- **Schema**: OpenAI structured outputs (`response_format` JSON schema),
  one call per Passage, returning an ordered array of Lines:
  `{lines: [{speaker: string, is_narrator: bool, speaker_gender: "male"|"female", speaker_is_child: bool, text: string, instruct: string|null}]}`.
  Narrator Lines have `is_narrator: true`, `instruct: null` (`speaker_gender`
  is ignored for Narrator Lines since the Narrator's Voice is fixed, not
  cast from the gendered pool — see the Cast ticket's amendment). Every Line
  always has exactly one committed Speaker — no ambiguous/unknown value in
  the schema (accept occasional POC misattribution rather than add a
  review-queue case every downstream ticket has to handle).
  **Amendment**: `speaker_gender` added after the fact — the Cast (ticket
  05) needs each Speaker's gender to pick a matching Voice (male characters
  get male-preset Voices, female get female-preset), so OpenAI reports it
  directly per dialogue Line rather than it being inferred locally from
  French grammatical cues (titles, pronouns) — OpenAI already has full
  context and this is a near-zero-cost schema addition.
  **Second amendment**: `speaker_is_child` added — voice casting for a
  child character (of either stated gender) conventionally uses an adult
  female voice (pitch/register convention from radio drama and animation
  dubbing), so gender alone isn't a sufficient casting signal. OpenAI
  reports whether the Speaker is a child directly, same rationale as
  `speaker_gender`.
- **Model**: `gpt-4o` — cost is a non-issue at this Chapter's scale (~171
  Passages, a fraction actually needing a call after the short-circuit
  below), so optimize for attribution quality over cost.
- **Cost short-circuit**: confirmed against the actual Chapter 1 text —
  French dialogue here is marked with an em-dash (—) at the start of a
  paragraph (87 occurrences in Chapter 1; no guillemets used for real
  dialogue, only one scare-quote pair). A Passage is sent to the Annotation
  Pass only if it contains an em-dash-prefixed line; otherwise it's treated
  as 100% Narrator with zero API cost.
- **Speaker normalization**: a running canonical-Speaker roster is
  maintained and passed into every Annotation Pass call ("known speakers so
  far: X, Y") — OpenAI either matches an existing name or introduces a new
  one. This requires processing a Chapter's Passages **in order**
  (sequential, not parallelizable across Passages) so the roster is
  accurate at each call.
- **Failure handling**: retry once on any API error or schema-validation
  failure; if it fails again, **abort the run** (not silently degrade to
  Narrator) — the user wants failures to be visible, not swallowed. See the
  new resumability ticket below for how a subsequent run picks back up
  without redoing completed work.

**Addendum — mid-quote narrator attribution (French *incise*)**: French
dialogue often embeds a narrator attribution tag mid-utterance without a
new em-dash, e.g.:

> —Quel bon dos a la mort! s'écria-t-il. Quelle admirable charge de titres
> on lui fait allègrement porter, et comme il faut que les hommes aient de
> l'esprit pour employer ainsi la tombe à la vanité!

This is **three Lines in one Passage**: dialogue (the character), narrator
("s'écria-t-il" — "he exclaimed"), dialogue continuing (same character, no
leading — since it's a continuation, not a new utterance). The
already-decided schema (ordered array of Lines per Passage) structurally
supports this without changes — it was designed for multiple Lines per
Passage, not one classification per whole paragraph. What needs adding is
an explicit few-shot example like this one in the Annotation Pass prompt,
so gpt-4o reliably splits this way instead of either swallowing the
attribution tag into the character's dialogue Line or missing that the
dialogue resumes (with the same Speaker, no new em-dash) after the tag.
Flagged here as an implementation requirement for whoever writes the
prompt, not a new open decision.

**Amendment (2026-09-13) — incise reversed: kept in the character's Line,
not split out**: the three-Line split decided above was implemented, and
the user listened to the actual synthesized audio. Verdict: it sounds bad
— switching Qwen3-TTS voices for just the 2-3 words of a mid-utterance
attribution tag ("dit M. Myriel", "s'écria-t-il") is audibly jarring, not
a subtle imperfection. Decision reversed to the opposite: an incise stays
inline, as part of the SAME dialogue Line as the surrounding quote, spoken
entirely by the character — never split into a separate Narrator Line.
`SYSTEM_PROMPT` and its few-shot example in `annotation.py` were rewritten
accordingly: the example sentence "—Sire, dit M. Myriel, vous regardez un
bonhomme, et moi je regarde un grand homme." is now shown producing exactly
ONE Line (`speaker=M. Myriel, is_narrator=false`, full text verbatim,
incise included), not three. The general rule that a genuinely new
dialogue turn (a new em-dash, or a different Speaker actually starting to
talk) still starts a new Line is unchanged — this reversal is scoped
specifically to mid-quote attribution tags, not to dialogue-turn splitting
generally. `needs_annotation_call`/`_has_em_dash_line` were also removed
from this module as part of a related parsing-side fix — see
[Design Book parsing](04-parsing-design.md)'s amendment: the has-dialogue
decision is now made once in `parsing.py` (from the raw pre-whitespace-
collapse text) and passed in as `Passage.has_dialogue`, not re-derived
here from already-collapsed text.

**New cross-cutting requirement surfaced**: the user wants any run of the
pipeline against the same Book/input to **resume** from where a prior run
left off — skip Passages already annotated and Chapters already
synthesized, rather than regenerating them. This affects both the
Annotation Pass (this ticket) and audio synthesis/assembly (ticket 06), so
it's being split out as its own ticket rather than decided piecemeal here:
see [Design resumability / checkpointing](07-resumability.md). This
ticket's Annotation Pass results are expected to be written to whatever
per-Passage checkpoint store that ticket designs, keyed so a repeat run can
detect "already annotated" and skip straight to synthesis.

**Amendment (2026-09-13, same day) — preceding-Passage context**: the
project owner pointed out that annotating a Passage in complete isolation
makes it hard to judge tone correctly — a line of dialogue read with no
idea what just happened often gets the wrong emotional register, the same
problem a human reading it cold would have. Grilled on scope (immediately
preceding Passage only vs. the whole chapter-so-far vs. a fixed window):
decided on **the immediately preceding Passage only** — cheap (one extra
Passage of tokens per call), simple, and sufficient for the immediate
situational tone in practice.

`annotate_passage` now takes an optional `preceding_context: str | None`
(the previous Passage's text, or `None` for the Chapter's first Passage).
When present, the user message is split into a labeled
"Preceding context (for tone/situation only):" block followed by
"Passage to annotate:" — the system prompt explicitly instructs the model
to use the context only for tone/gender/child judgments and never annotate
or reproduce it in the response. `main.py`'s Phase 1 loop tracks the
previous Passage's text across both the skip-and-restore branch and the
fresh-annotation branch, so this is correct even when resuming mid-chapter
(the previous Passage's text is always known locally from the parsed
Chapter, independent of whether this run re-annotates it or restores it
from checkpoint). Verified with two real API calls against the same
dialogue Passage from `tests/fixtures/synthetic_book.epub`, with and
without context — both succeeded and produced sensibly different
`instruct` wording. Covered by `tests/test_annotation_context.py`.

Status: resolved
