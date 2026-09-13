# Map: Audiobook Prototype

## Destination

A working prototype: feed in the first Chapter of *Fantine* (Tome I of
*Les Misérables*, Victor Hugo — see `samples/`), precisely *Livre premier,
Chapitre I: "Monsieur Myriel"* (963 words, 16 paragraphs — corrected after
an earlier extraction bug grabbed the wrong "Chapitre I", see
[Pick the test book](issues/02-pick-test-book.md)), and get back one audio
file for that Chapter, with the Narrator and each character Speaker in a
distinct Voice, and audible emotional variation in dialogue Lines. TTS
synthesis runs entirely on CPU, locally; the OpenAI API is the only network
dependency, used solely to annotate dialogue (Speaker attribution +
Instruct String). CLI/script only, no UI. Voice cloning is out of scope —
Preset Voices only. See [CONTEXT.md](../../CONTEXT.md) for the glossary
(Book, Chapter, Passage, Speaker, Line, Instruct String, Voice, Cast,
Annotation Pass).

Scope note: the rest of *Fantine* beyond Chapter 1, and the rest of
*Les Misérables* beyond Tome I, are not part of this POC's "done" bar —
narrowed down from "one full short book" once the actual test file turned
out to be a full tome (see [Pick the test book](issues/02-pick-test-book.md)).

## Notes

- **Real motivating target, beyond this map's destination**: the user's
  actual goal is generating a full audiobook of *L'Autre Moi* (Franck
  Thilliez), a contemporary novel — `samples/L'Autre Moi - Franck Thilliez.epub`.
  This map's destination (Chapter 1 of *Fantine* only) is a POC to prove
  the pipeline design before attempting that much larger, still-copyrighted
  book. Do not expand this map's tickets to cover *L'Autre Moi* — it's a
  separate future effort once this POC's design is validated. Relevant to
  the whole-book runtime-budget fog item below: a modern novel is far
  longer than one chapter of *Fantine*, so RTF≈10 CPU throughput will
  matter far more there than it does for this POC.
  **Pre-analyzed *L'Autre Moi*'s actual EPUB structure and it differs from
  Fantine's in ways that would break the current design if reused as-is**:
  68 chapters already one-file-per-chapter (`chap1.xhtml`...), heading is
  `<h1 class="hi_chap">` with a bare number, not "Chapitre N" — ticket 04's
  h2-followed-by-h3 rule would not fire on it at all. Dialogue uses
  **both** em-dash and guillemets « » (Fantine used em-dash only) — ticket
  03's em-dash-only cost short-circuit would silently miss guillemet
  dialogue. Also has a real 506-word Préface (editorial call: narrate or
  skip?) and Kobo-specific nested-span paragraph markup. None of this
  changes this map's resolved tickets (scoped to Fantine only) — it's
  captured here so the future *L'Autre Moi* effort starts from facts, not
  an assumption that the Fantine-tuned parsing/annotation design transfers.
- Destination is a working prototype, not a spec, so this map's tickets are
  not decisions-only: once the design tickets below resolve, expect
  follow-on implementation ("task") tickets for parsing, annotation calls,
  TTS synthesis, audio assembly, and CLI wiring.
- Consult [CONTEXT.md](../../CONTEXT.md) before working any ticket — it's
  the canonical vocabulary.
- Test hardware for CPU-feasibility questions: 8-core Xeon E3-1245 v5
  (Skylake, ~2016), 23GB RAM, no GPU, Python 3.12.
- Settled already (not reopened): Python stack; MP3/WAV per Chapter (not a
  merged M4B); OpenAI cost is "reasonable for personal use", not a hard
  budget; narrator Lines never get an Instruct String; one paragraph = one
  Passage; Narrator is a Speaker like any other.

## Decisions so far

- [Pick the test book](issues/02-pick-test-book.md): *Fantine* (Tome I of
  *Les Misérables*, Victor Hugo), already downloaded as
  `samples/Les misérables Tome I Fantine.epub` — a full tome, not a short
  story, which raises the stakes on the runtime-budget fog item below.
- [Select the TTS engine](issues/01-select-tts-engine.md): **dual-model
  Qwen3-TTS-12Hz**: Narrator Lines → **0.6B-CustomVoice** (no `instruct`,
  as always); dialogue Lines → **1.7B-CustomVoice** (one-sentence
  OpenAI-generated `instruct`) — amended after the README's own feature
  table turned out to mark "Instruction Control" ✅ for 1.7B variants only,
  not 0.6B. Device auto-detected (CUDA+bf16+best-effort flash-attn if a GPU
  is present, else the original CPU float32 path); this dev machine has no
  GPU, so only CPU is verified for real, RTF≈10. Chosen over Piper for its
  emotion/`instruct`-string control despite no native French preset voice.
  Estimated render time for Chapter 1 corrected from ~5hrs to **~70 min**
  after fixing a chapter-extraction bug (see the test-book ticket) — user
  judged even the original worse estimate acceptable, and heard the output
  quality firsthand.
- [Design the OpenAI annotation contract](issues/03-annotation-contract.md):
  gpt-4o with structured outputs, one call per Passage; `Passage.has_dialogue`
  (computed by parsing from raw pre-collapse text) skips OpenAI entirely for
  pure-narration Passages; running canonical-Speaker roster passed into each
  call (Passages processed in order per Chapter); retry once then abort the
  whole run on failure (no silent Narrator fallback) — surfaced a new
  cross-cutting resumability requirement, split into its own ticket. Schema
  later amended to add `speaker_gender` per Line, needed for gender-matched
  Cast voices. **Amended 2026-09-13**: mid-quote narrator attribution
  (French *incise*) reversed from a 3-Line split back to ONE Line spoken
  entirely by the character — the 3-Line version was implemented, heard,
  and judged bad (jarring mid-utterance voice-switch on Qwen3-TTS). Amended
  again same day: each call now includes tone/situation-only context (a
  Passage read in isolation makes correct tone judgment hard, for the
  model or a human) — corrected same day, after a worked example, from
  "the whole preceding Passage" down to a one-Line recency window (the
  immediately preceding Line's text): "if speaker B speaks after speaker
  A, render B using what A just said," not the whole previous Passage
  (over-includes if it had several Lines) and not the whole chapter so far.
- [Design Book parsing](issues/04-parsing-design.md): ebooklib + BeautifulSoup;
  a real chapter boundary is an `<h2>` chapter heading immediately followed
  by an `<h3>` title (distinguishes real chapters from Gutenberg's
  differently-structured TOC, and correctly handles chapter numbering that
  resets per Livre/Part — the exact bug that produced the wrong-chapter
  correction on the test-book ticket). `<p>` tags = Passages, plain text,
  markup stripped, and **all whitespace collapsed to single spaces**
  (fixes an audible bug: the source HTML's soft-wrapped line breaks were
  otherwise preserved as literal newlines inside a Passage, which
  Qwen3-TTS read as unwanted mid-sentence pauses). Raw-text parsing
  deferred to fog. **Amended 2026-09-13**: the chapter title is now
  narrated first (Narrator Line, always short-circuited, no Annotation
  Pass call), and `Chapter.passages` is now `list[Passage]` carrying a
  `has_dialogue` flag computed from the raw pre-collapse text (fixes
  embedded/mid-paragraph dialogue being invisible to the old
  passage-start-only em-dash check). **Amended 2026-09-13**: any heading
  level other than the `<h2>`+`<h3>` chapter-boundary pair (`h1`, `h4`-`h6`
  handled generally; the real book only ever uses `h1` — outside any
  chapter — plus `h2`/`h3`) is now treated as passage-like content, same as
  a `<p>` — fixes non-title headings (e.g. a "Livre N" section heading
  found trailing 8 of the book's other 69 chapters) being silently dropped
  with zero trace. Chapter 1 itself is unaffected (still 16 body passages,
  963 words) since it has no such headings.
- [Design the Cast](issues/05-design-cast.md): **amended 2026-09-13** —
  the original gender-partitioned 4-Voice pool + cycling design (fixed
  Narrator=Uncle_Fu; male sub-pool Ryan/Aiden; female sub-pool
  Serena/Vivian, also used for child characters of either gender) was
  replaced with exactly **4 fixed, configurable role-voices** applied
  uniformly, no more per-character auto-casting at all: Narrator=Ryan,
  adult male=Ryan (same as Narrator, intentional), adult female=Serena,
  child (either gender)=Vivian, configured via a new `voices.json` file
  (per-key fallback to defaults if partial). `cast.json`'s per-character
  override stays unchanged. Cast is now a stateless, pure function of
  (role, current config) — no per-run assignment memory — which
  incidentally makes every same-role character consistent across every
  Chapter of a Book, for free (see the ticket amendment: the old design's
  claimed cross-Chapter consistency wasn't actually implemented; this
  redesign genuinely delivers it, as a side effect, not a separately-built
  feature).
- [Design chunking and audio assembly](issues/06-chunking-and-assembly.md):
  one TTS call per Line (empirically confirmed no truncation up to this
  Chapter's longest paragraph, 332 words); numpy-silence-padded
  concatenation (~300-400ms between Lines, ~600-800ms between Passages);
  WAV output at Qwen3-TTS's confirmed native 24000 Hz, one file per
  Chapter. **Amended 2026-09-13**: introduced the **Chunk** concept (see
  [CONTEXT.md](../../CONTEXT.md)) — the actual synthesis unit is no longer
  one call per Line, but consecutive Narrator Lines (even across
  Passage/heading/title boundaries) merged into one call, breaking only at
  a dialogue Line; model routing (0.6B/1.7B) moves to per-Chunk; the old
  two-tier silence rule collapses to a single ~600-800ms gap between every
  pair of Chunks (`assembly.CHUNK_GAP_S`); Chunk audio files are now
  content-hash-addressed (`chunk_<hash>.wav`, hash over text+voice+
  instruct+is_narrator) instead of passage/line-indexed.
- [Design resumability / checkpointing](issues/07-resumability.md): single
  JSON manifest per Book, keyed by (chapter, passage index) + a content
  hash to detect source changes; caches both the Annotation Pass result
  and each Line's synthesized audio path; also snapshots the running
  Speaker roster per Passage so a resumed run doesn't need to re-derive it.
  **Amended 2026-09-13**: the annotation checkpoint (this ticket's original
  design) is unchanged; `is_passage_done` renamed `is_passage_annotated`
  and now checks annotation validity only (no more per-Line audio-file
  existence check, since Lines no longer have individual audio files after
  ticket 06's Chunk amendment). Chunk audio caching is deliberately NOT
  persisted anywhere — it's purely content-hash-addressed and
  reconstructed identically every run by the same pure `build_chunks`
  function, so a resumed run naturally finds and skips already-synthesized
  Chunk files with no separate manifest; `_clear_stale_audio` was removed
  (content-hash files can't collide with stale ones — an orphaned old file
  is harmless). Accepted inefficiency: re-annotating a Passage can force a
  full resynthesis of the newly-extended Chunk it now belongs to, including
  content that was already synthesized before — not engineered around, per
  this project's existing resumability-over-efficiency philosophy.
  This is what makes ticket 03's "abort the whole run on failure" decision
  safe — nothing already done is lost. **Amended again 2026-09-13**
  (following ticket 05's Cast redesign): Cast no longer needs a persisted
  snapshot at all — `Checkpoint.set_entry`'s `cast_snapshot` param is
  removed, one stateless `Cast` instance is built once per run and reused.
  Verified for real that changing `voices.json` between runs does NOT
  force regeneration of already-synthesized Chunk audio (unaffected roles'
  Chunks are untouched, same file/mtime; only the changed role's Chunk gets
  a new hash/path, and the old file is simply left orphaned on disk) — see
  the ticket amendment. Chunk audio filenames now carry a human-readable
  role prefix (`chunk_{role}_{hash}.wav`) specifically so a category of
  cached chunks can be found and manually deleted after a voice-config
  change.

## Not yet specified

(none — every decision needed to reach this destination has been resolved;
see Decisions so far. The map's frontier is empty.)

## Out of scope

- Voice cloning (cloning a specific real/reference voice) — ruled out during
  destination-setting; Preset Voices only.
- A UI (web or desktop) — ruled out; CLI/script is sufficient for the
  prototype.
- Non-French language support — destination is scoped to French; other
  languages would be a fresh effort if wanted later.
- Raw-text (non-EPUB) input parsing — this POC's destination is EPUB-only
  (see [Design Book parsing](issues/04-parsing-design.md)); would belong to
  a future effort if raw-text input is ever needed.
- Whole-book / multi-chapter performance budgeting — this POC's destination
  is one Chapter only. Real CPU-throughput planning at book scale belongs
  to the future *L'Autre Moi* effort (see Notes), not this map.
- Anything beyond Chapter 1 of *Fantine* — the rest of *Fantine*, the rest
  of *Les Misérables*, and the eventual *L'Autre Moi* full-book generation
  are all separate future efforts once this POC's design is implemented and
  validated.
