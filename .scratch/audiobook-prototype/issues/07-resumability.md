# Design resumability / checkpointing

Type: grilling
Status: resolved
Blocked by: (none)

## Question

Re-running the toolkit against the same Book/input must resume from where a
prior run left off, rather than regenerating completed work. Surfaced while
resolving [Design the OpenAI annotation contract](03-annotation-contract.md),
where the user wants Annotation Pass failures to abort the whole run rather
than silently degrade — resumability is what makes that safe (an aborted
run isn't a lost run). Applies to at least two kinds of expensive,
re-runnable work:

- **Annotation Pass results** (per dialogue-bearing Passage, from the OpenAI
  annotation contract) — a completed Passage's annotation shouldn't be
  re-requested from OpenAI on a subsequent run.
- **Synthesized audio** (per Line or per synthesis batch, from
  [Design chunking and audio assembly](06-chunking-and-assembly.md)) — given
  Qwen3-TTS's measured RTF≈10 on this CPU (~4.5-5hrs for Chapter 1 alone),
  losing partial synthesis progress to a crash or interruption would be
  costly.

Needs to settle:

- **Checkpoint granularity and key**: what uniquely identifies a unit of
  completed work (e.g. Chapter + Passage index + a content hash, so an
  edited source Passage is detected as needing redo rather than
  incorrectly treated as already done).
- **Storage format**: a simple local store (e.g. a JSON manifest per Book,
  or a SQLite file) tracking which Passages are annotated and which Lines/
  Chapters are synthesized, plus where their output (annotation JSON, audio
  file) lives on disk.
- **Resume behavior**: on startup, how the pipeline scans the checkpoint
  store to figure out what's already done vs what still needs to run, and
  how it detects "the source Book changed since last run" (does it
  invalidate everything, or only affected Chapters/Passages).
- **Interaction with the Annotation Pass's speaker-roster ordering**: ticket
  03 decided Passages must be annotated *in order* per Chapter (a running
  canonical-Speaker roster is built up sequentially) — resuming mid-Chapter
  means reconstructing that roster from already-completed Passages rather
  than starting empty.

## Answer

**Storage format**: a single JSON manifest file per Book, e.g.
`fantine_tome1.checkpoint.json`. Human-readable/editable, no new
dependency, and sufficient at this POC's scale (one Chapter, 16 Passages) —
SQLite's transactional guarantees aren't needed for a single-process
sequential run.

**Checkpoint key**: each entry keyed by `(chapter_number, passage_index)`,
storing a content hash of that Passage's own extracted (and now
whitespace-normalized — see ticket 04's amendment) text. On resume, a
Passage is skipped only if its hash still matches; if the source
extraction produced different text (EPUB changed, or the extraction logic
itself changed), that Passage — and everything checkpointed after it in
the same Chapter, since the roster is sequential — is treated as stale and
redone from that point forward.

**Checkpoint contents per Passage**: the Annotation Pass result (its full
`lines` array, so it's never re-sent to OpenAI) **and** the file path of
each Line's already-synthesized audio, once rendered (so CPU synthesis is
never redone either). A Passage counts as fully done only once both its
annotation and every one of its Lines' audio files exist on disk.

**Speaker-roster resume**: each Passage's checkpoint entry also stores a
snapshot of the canonical-Speaker roster as of that point (not just the
annotation result). On resume, the roster is loaded directly from the last
completed Passage's snapshot and continues from there — no need to re-walk
or re-derive it from scratch, and no OpenAI calls are needed just to
reconstruct in-memory state.

**Failure/abort interaction**: ties back to ticket 03's decision to abort
the whole run (not silently degrade) on an Annotation Pass failure — this
checkpoint design is exactly what makes that safe: an aborted run's
completed Passages remain valid and skippable, so a subsequent run picks
up from the first unresolved Passage rather than losing all prior work.

Status: resolved
