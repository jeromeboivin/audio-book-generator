# Design chunking and audio assembly

Type: grilling
Status: resolved
Blocked by: 01

## Question

Design how annotated Lines within a Chapter become one output audio file,
given the selected TTS engine's (see the TTS engine selection ticket) input
constraints. Needs to settle:

- **Synthesis batching**: how Lines are grouped into individual TTS synth
  calls given the engine's max input length per call (a Line may need
  splitting, or several short Lines from the same Speaker may be batched
  together).
- **Concatenation**: the order and method for joining synthesized Line audio
  into one Chapter file, including any inter-Line pause/silence handling
  (e.g. a beat between dialogue and the next narration).
- **Output file spec**: exact format (MP3 vs WAV — already narrowed to
  "one file per Chapter", pick the concrete format), sample rate/bitrate,
  and the file naming/directory convention for a Book's Chapter files.

Note: this ticket's synthesis batching must produce checkpointable units —
see [Design resumability / checkpointing](07-resumability.md), surfaced
while resolving the annotation contract ticket. Coordinate with that
ticket's checkpoint-store design rather than inventing a separate one.

## Answer

**Synthesis batching**: one `generate_custom_voice` call per Line — no
batching of consecutive same-Speaker Lines. Simplest mapping, and each
call is naturally one checkpointable unit for the resumability ticket.
Empirically tested against Chapter 1's actual longest paragraph (332
words / 2045 chars, well above typical Line length since most Lines are
sub-paragraph): synthesized in one call with no truncation or error,
producing correctly-timed audio (161.8s for 332 words ≈ 123 wpm, a
plausible full read, not cut short) — confirms no chunking/splitting logic
is needed for Lines at this book's actual paragraph lengths. No documented
max-input-length was found for Qwen3-TTS, and none was hit in practice.

**Concatenation**: raw synthesized audio arrays (numpy) for a Chapter's
Lines, in order, joined with inserted silence — via `np.zeros` (no new
audio-library dependency; numpy/soundfile already in use) — of ~300-400ms
between consecutive Lines, ~600-800ms between Passages, before writing the
final concatenated array to one WAV file per Chapter with `soundfile`.

**Output file spec**: **WAV**, at Qwen3-TTS's native output sample rate —
empirically confirmed **24000 Hz** (measured directly from
`generate_custom_voice`'s returned `sr`) — no resampling needed since only
one engine/sample-rate is in play. Chapter files named by chapter number
and slugified title, e.g. `chapitre_01_monsieur_myriel.wav`. MP3 is a
possible later nice-to-have via a quick ffmpeg pass, not required for this
POC's "done" bar.

**Amendment (2026-09-13) — the Chunk concept: merge consecutive Narrator
Lines into fewer, larger synthesis calls**: a real gap found by the
project owner. This ticket's original "one `generate_custom_voice` call
per Line" answer meant every source paragraph always produced at least one
separate TTS call, even when nothing about the Speaker changed across
consecutive paragraphs — making narration unnaturally choppy and producing
far more, smaller calls than necessary (compounded by ticket 04's
2026-09-13 amendment, which turns non-title headings into passage-like
content too, adding even more potential per-element call boundaries if
left unmerged).

**New concept — Chunk** (added to [CONTEXT.md](../../../CONTEXT.md)'s
glossary): the actual unit sent to TTS synthesis — either a single
dialogue Line, or a run of consecutive Narrator Lines (possibly spanning
multiple Passages, and even the chapter-title/any-heading boundary) merged
into one call. A Chunk is a new, downstream concept from Passage and
Line, not a redefinition of either — Line stays scoped to one Speaker's
text within one Passage, from the Annotation Pass.

**Merge algorithm**: after Phase 1 (annotation, unchanged) produces the
Chapter's full ordered Line list, walk it once: buffer consecutive
`is_narrator=true` Lines' text, joined with a single space (never a raw
newline — ticket 04 already fixed a real audible-pause bug from embedded
newlines, this must not reintroduce anything like it); the moment a
dialogue Line is encountered, close the current buffer as one Chunk (if
non-empty), emit the dialogue Line as its own separate single-Line Chunk
immediately after, then start a fresh buffer. Close any remaining buffer
at the end of the Chapter. Implemented as a pure function,
`chunking.build_chunks`, taking the full ordered `AnnotatedLine` list and
returning the ordered `Chunk` list — kept in a new `chunking.py` module
rather than folded into `assembly.py`, which stays focused on raw audio
concatenation/silence/WAV-writing.

**Model routing moves to per-Chunk** (mechanically the same rule as
before, applied at the new unit): a Chunk with `is_narrator=true` routes
to `NARRATOR_MODEL_ID` (0.6B, no instruct); a dialogue Chunk (always
exactly one Line) routes to `DIALOGUE_MODEL_ID` (1.7B) with that Line's
instruct and Cast-assigned voice.

**Concatenation simplifies to a single inter-Chunk silence rule**: the old
two-tier "~300-400ms between Lines, ~600-800ms between Passages" rule no
longer cleanly applies — Line/Passage boundaries no longer align with
synthesis-call boundaries at all, now that consecutive Narrator Lines
(even across Passages) are merged into one Chunk. Replaced with a single
rule: insert ~600-800ms of silence between every consecutive pair of
Chunks in the final assembled Chapter WAV (`assembly.CHUNK_GAP_S = 0.7`),
and nowhere else — no silence within a Chunk, since it's one continuous
TTS call's output.

**Chunk audio file naming — content-hash-addressed, not
passage/line-index-addressed**: `audio_cache/chapter_NN/chunk_<hash>.wav`.
This is the resumability mechanism for the Chunk layer — see
[Design resumability / checkpointing](07-resumability.md)'s matching
amendment for the full reasoning, including one deliberate deviation from
this ticket's literal "sha256-of-chunk-text" phrasing: the hash also folds
in the Chunk's voice, instruct, and is_narrator flag, not just its raw
text, so two different Speakers who happen to say the exact same short
line (e.g. both say "Oui.") don't collide on one cached audio file and
wrongly reuse each other's synthesized voice.

**Verification**: the project owner's own worked example —
title="Chapter X" (Narrator) + body Passages in order ["Sub-title"
(Narrator, from a non-title heading), "Paragraph 1" (Narrator),
"Paragraph 2: —Dialog 1 —Dialog 2" (splitting via annotation into Narrator
"Paragraph 2:" + two dialogue Lines), "Paragraph 3" (Narrator)] — is
encoded as a real regression test (`tests/test_chunking.py`), confirming
exactly 4 Chunks: `["Chapter X Sub-title Paragraph 1 Paragraph 2:",
"Dialog 1", "Dialog 2", "Paragraph 3"]`. Also verified for real against a
real few-passage slice of *Fantine* Chapter 1 (the actual "—Sire, dit M.
Myriel..." exchange): merging a Narrator Passage with the chapter title
across the title/body boundary, keeping the real two-Line dialogue
exchange as two separate dialogue Chunks routed to the 1.7B model, and
assembling a valid 24000 Hz WAV from the resulting Chunk audio files.

Status: resolved
