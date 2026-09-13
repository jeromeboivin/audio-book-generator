# Context: Audiobook Generator

## Destination

Given a French EPUB, produce one audio file per Chapter (one Chapter per run),
narrated with distinct Voices per Speaker and audible emotional variation in
dialogue. TTS synthesis runs entirely locally (CPU or GPU); the OpenAI API is
the only network dependency (used for dialogue annotation only). CLI/script,
no UI. Voice cloning is out of scope — Preset Voices only. See
[README.md](README.md) for setup and usage, and its "Scope and limitations"
section for the real constraints on what kind of EPUB this works against
today.

## Glossary

- **Book**: the input work, supplied as an EPUB file (raw-text input was
  considered early on but was never built — EPUB is the only supported
  format).
- **Chapter**: a top-level division of a Book. The unit of output: one audio
  file is produced per Chapter. Detected via one of two supported
  conventions *(second one added 2026-09-13)*: a Gutenberg-style `<h2>`
  "Chapitre N" + `<h3>` title heading pair, or an EPUB3-semantic
  `<section epub:type="chapter">` (tried first; whichever the Book
  actually uses is auto-detected, see `parsing.extract_chapter`/
  `parsing.count_chapters`) — a semantic-section Chapter's `title` may be
  `""` when the Book has no separate subtitle at all (e.g. L'Autre Moi -
  Franck Thilliez, whose chapters carry only a bare-number heading).
- **Passage**: one paragraph of a Chapter's text — the unit sent to OpenAI in
  a single annotation call. A Passage may be pure narration, pure dialogue,
  or a mix (e.g. a line of dialogue with an attribution tag like "said Marie").
- **Speaker**: whoever a piece of text is attributed to. The Narrator is a
  Speaker like any other character Speaker — every Line has exactly one
  Speaker. Narrator Lines skip the OpenAI annotation step (see Line); the
  Narrator's Voice is fixed and pre-assigned rather than inferred.
- **Line**: one Speaker's contiguous piece of text within a Passage, after
  narration/dialogue splitting. A Narrator Line is passed straight to
  synthesis unchanged. A dialogue Line (any non-Narrator Speaker) carries a
  generated Instruct String.
- **Instruct String**: the natural-language performance directive passed to
  the TTS engine alongside a Line's text — for a dialogue Line, OpenAI
  generates one per Line covering emotion, pace, volume, and delivery
  quality (e.g. "Speak with quiet dread."); a Narrator Line gets the SAME
  chapter-wide Instruct String as every other Narrator Line in that
  Chapter (see main.py's `--narrator-tone`/`--no-narrator-tone` flag, on
  by default), guessed once from the Chapter's opening — or none at all
  if that flag is disabled.
- **Voice**: a concrete TTS-engine voice (one of its Preset Voices) that can
  be assigned to a Speaker.
- **Cast** *(redesigned 2026-09-13)*: a stateless, pure lookup from a Line's **role** — one of
  `narrator` / `adult_male` / `adult_female` / `child`, derived from
  `is_narrator` + `speaker_gender` + `speaker_is_child` — to a Voice,
  via 4 fixed, configurable role-voices (`voices.json`, defaults
  Narrator=Ryan, adult male=Ryan, adult female=Serena, child=Vivian) plus
  a `cast.json` per-Speaker-name override that always wins. Not built
  automatically/LLM-inferred and not a per-run assignment memory (no more
  pool, no more cycling, nothing to snapshot across a resumed run) — the
  same role always resolves to the same Voice, in every Chapter of every
  Book, as long as the config doesn't change. This is what actually makes
  Cast consistent across Chapters (an earlier version of this entry
  claimed cross-Chapter consistency an older pool/cycling design didn't
  actually implement).
- **Annotation Pass**: one OpenAI call over a Passage, returning a structured
  breakdown into Lines — Narrator Lines passed through as-is, dialogue Lines
  each tagged with a Speaker and an Instruct String.
- **Chunk** *(added 2026-09-13)*: the actual unit sent to TTS synthesis — either a single
  dialogue Line, or a run of consecutive Narrator Lines (possibly spanning
  multiple Passages, and even the chapter-title/heading boundary) merged
  into one `generate_custom_voice` call. A downstream, separate concept
  from Passage and Line, not a redefinition of either: a Passage is still
  one source paragraph (or, since the same amendment, one other heading
  element within a chapter's body); a Line is still one Speaker's
  contiguous text within a Passage, from the Annotation Pass. Chunks are
  built once per Chapter, after every Passage has been annotated, by
  walking the Chapter's full ordered Line list and merging consecutive
  `is_narrator=true` Lines together, breaking only at a dialogue Line.

## Notes

- No CONTEXT-MAP.md — single context, this is the whole project.
- This is a working implementation, not just a spec — see `src/audiobook/`
  and [README.md](README.md) for how to run it.
