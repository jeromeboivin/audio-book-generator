# Context: Audiobook Generator

## Destination

A working prototype: given one full short French public-domain Book (EPUB or
raw text), produce one audio file per Chapter, narrated with distinct Voices
per Speaker and audible emotional variation in dialogue. TTS synthesis runs
entirely locally on CPU; the OpenAI API is the only network dependency
(used for dialogue annotation only). CLI/script, no UI. Voice cloning is out
of scope — Preset Voices only.

## Glossary

- **Book**: the input work, supplied as an EPUB file or raw text.
- **Chapter**: a top-level division of a Book. The unit of output: one audio
  file is produced per Chapter.
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
- **Instruct String**: the natural-language tone/emotion directive OpenAI
  generates for a dialogue Line (e.g. "speak with hesitant relief"), passed
  to the TTS engine alongside the Line's text. Narrator Lines never have one.
- **Voice**: a concrete TTS-engine voice (one of its Preset Voices) that can
  be assigned to a Speaker.
- **Cast** *(redesigned 2026-09-13, see [Design the
  Cast](../.scratch/audiobook-prototype/issues/05-design-cast.md)'s
  amendment)*: a stateless, pure lookup from a Line's **role** — one of
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
  claimed cross-Chapter consistency the old pool/cycling design didn't
  actually implement — see the ticket amendment for the full story).
- **Annotation Pass**: one OpenAI call over a Passage, returning a structured
  breakdown into Lines — Narrator Lines passed through as-is, dialogue Lines
  each tagged with a Speaker and an Instruct String.
- **Chunk** *(added 2026-09-13, see [Design chunking and audio
  assembly](../.scratch/audiobook-prototype/issues/06-chunking-and-assembly.md)'s
  amendment)*: the actual unit sent to TTS synthesis — either a single
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

- No CONTEXT-MAP.md — single context, this is the whole project so far.
- No code exists yet; this file precedes any implementation.
