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

**Amendment (2026-09-13) — the Chunk layer's resumability: annotation
checkpoint unchanged, audio caching moves to a new, deliberately
unpersisted, content-hash mechanism**: ticket 06's Chunk amendment (see
that ticket) means audio is no longer synthesized per-Line — a Chunk can
merge several Passages' Narrator Lines into one synthesis call — so this
ticket's original "a Passage counts as fully done only once ... every one
of its Lines' audio files exist on disk" no longer makes sense at the
Passage level at all.

**The annotation-level checkpoint is completely unaffected by this
change** and keeps working exactly as before — that's a separate,
already-correct concern. What changes:

- `Checkpoint.is_passage_done` is renamed `is_passage_annotated` (every
  call site updated) and now means exactly one thing: is this Passage's
  ANNOTATION cached and valid (stored text hash matches, `lines` non-empty)?
  Nothing about audio anymore.
- Per-Chunk audio caching is **not tracked in the Checkpoint JSON at all**.
  A Chunk's `audio_path` is content-hash-addressed
  (`audio_cache/chapter_NN/chunk_<hash>.wav`, hash over the Chunk's text +
  voice + instruct + is_narrator — see ticket 06's amendment for why voice/
  instruct/is_narrator are folded in too, not just text) and computed by
  the same pure `chunking.build_chunks` function every run. "Already
  synthesized" is simply `os.path.exists(chunk.audio_path)`, checked
  directly by `main.py` before a Chunk's SynthesisJob is even created — no
  separate manifest entry to read, write, or ever go stale.
- **Why this is still correctly resumable without a persisted chunk
  manifest**: chunk-building is a pure, deterministic function of the
  Chapter's full ordered Line list (same ordered Lines with the same
  resolved voices in -> same Chunk boundaries and text out -> same content
  hash out -> same audio_path out). On a resumed run, every unchanged
  upstream Passage's Lines are restored byte-for-byte from the (unchanged)
  annotation checkpoint, with the same Cast-assigned voices (Cast's
  assignments are themselves restored from the same per-Passage snapshot
  this ticket already specifies) — so `build_chunks` reconstructs
  identical Chunk boundaries and hashes for that unchanged stretch, and
  the corresponding audio file (from a prior run) is naturally found on
  disk and skipped. Verified for real (not just reasoned about): a
  same-input rerun against a real slice of *Fantine* Chapter 1 produced
  byte-identical Chunk audio_paths, left every cached file's mtime
  untouched, and completed in under a few seconds (vs. real CPU-bound
  synthesis time on the first run) — see the Chunk-layer test
  (`tests/test_chunking.py`) and the manual real-book verification script
  used for this change.
- `_clear_stale_audio` (which deleted per-Line-indexed audio files by
  passage-index prefix, keyed to the old `passage_NNN_line_NN.wav` naming)
  is **removed outright**, not merely simplified: content-hash-addressed
  files can't collide with stale ones in the first place — a changed
  upstream Passage naturally produces Lines that hash into a NEW Chunk
  filename, so the old Chunk's audio file is simply orphaned on disk
  (harmless leftover bytes, never mistakenly reused or in the way of the
  new file) rather than needing active cleanup. `invalidate_from` (the
  passage/annotation-level cascade-invalidation) is untouched — it's about
  a different, still-valid concern (the sequential-roster requirement).
- **Accepted, intentional inefficiency** (consistent with this project's
  existing "correctness/resumability over efficiency" philosophy — ticket
  07 [this ticket] already accepted a similar tradeoff for cascade
  invalidation, and this is the same shape of tradeoff one layer up): if a
  resumed run re-annotates a Passage whose immediately-preceding Passage
  was already-synthesized Narrator content as part of an OLD Chunk from a
  prior run, the new Chunk that results (extending the merge-run into the
  freshly re-annotated Passage) gets a NEW hash and is synthesized in
  full — including re-synthesizing the unchanged prior content that was
  already done. No extra machinery (e.g. partial-Chunk reuse, splitting a
  merged Chunk back apart to reuse a prefix) was built to avoid this;
  verified for real via a mutate-the-last-Passage-and-rerun test: the
  mutated Passage's Chunk got a new hash and was freshly (and
  measurably, non-trivially) resynthesized, while every earlier,
  unaffected Chunk's audio_path and on-disk file were left untouched.

Status: resolved

## Amendment (2026-09-13) — Cast no longer needs a persisted snapshot at all

Ticket 05's 2026-09-13 amendment replaced Cast's gender-partitioned
pool/cycling design with 4 fixed, configurable role-voices — Cast is now a
stateless, pure function of (role, current `voices.json` config), with no
per-run assignment memory to track at all. That removes the last reason
this ticket's checkpoint schema needed a per-Passage Cast snapshot:

- `Checkpoint.set_entry`'s `cast_snapshot` parameter is removed entirely
  (not made optional) — a Passage's checkpoint entry now stores only
  `text_hash`, `annotation`, and `roster` (the Speaker-name roster, which
  is unrelated and still needed for OpenAI Speaker-name-normalization
  continuity across a resumed run — see this ticket's original "Speaker-
  roster resume" answer above, completely unchanged). `main.py` now
  constructs exactly one `Cast` instance at the top of `run()`, from
  `cast.json` overrides and `voices.json`'s role-voice config, and reuses
  it for the whole run — no per-Passage restore/reconstruction
  (`Cast.from_snapshot`) exists anymore at all, in either the skip-and-
  restore branch or `_reconstruct_state`.

**This also settles, for real, something this ticket's design implicitly
depended on but never had to prove before: changing `voices.json` between
runs must NOT force regeneration of already-synthesized Chunk audio.**
This falls directly out of the existing content-hash-addressed Chunk
design (`chunking.py`'s hash is text+voice+instruct+is_narrator) now that
Cast is a stateless, config-driven lookup rather than something restored
from a per-run checkpoint snapshot: a Passage that was already annotated
(and checkpointed) before the config change is unaffected by the change at
the Passage/annotation level; when its Lines are turned into Chunks, the
NEWLY-resolved voice for each Line's role is looked up against whatever
`voices.json` says *right now* — so a role whose configured voice didn't
change resolves to the exact same voice, the exact same Chunk hash, and
the exact same (already-cached) audio_path, while a role whose configured
voice DID change resolves to a new hash and a new, not-yet-existing
audio_path — leaving the old file on disk, untouched, rather than
colliding with or overwriting it.

**Verified for real, not just reasoned about** (see this project's
end-to-end verification against `tests/fixtures/synthetic_book.epub`):
after a full run with `voices.json`'s `adult_female` set to `Serena`, then
changing only that one key to `Vivian` and rerunning the same Chapter —
the Narrator's and the adult male character's Chunk audio files were
neither resynthesized nor touched (same file, same mtime — their role's
voice didn't change, and their Passage's annotation was already cached),
the adult female character's dialogue Chunk WAS freshly synthesized under
a new `chunk_adult_female_<newhash>.wav` path, and the OLD
`chunk_adult_female_<oldhash>.wav` (Serena-voiced) file was left sitting
on disk, completely untouched.

**Chunk audio filenames now include a human-readable role prefix
specifically to support this workflow**: `chunk_{role}_{hash}.wav`, where
`role` is one of `narrator`/`adult_male`/`adult_female`/`child` (see
`chunking.chunk_audio_path`) — a filename-only addition, NOT folded into
the hash itself (the hash inputs are unchanged: text+voice+instruct+
is_narrator). This is what lets the project owner visually identify and
manually bulk-delete a whole category of cached chunk files (e.g. every
`chunk_adult_female_*.wav`) after changing that role's voice in
`voices.json`, if they want to force those specific files to regenerate,
without needing to compute or look up any hash by hand.

Status: resolved
