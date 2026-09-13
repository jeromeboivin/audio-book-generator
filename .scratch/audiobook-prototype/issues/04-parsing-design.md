# Design Book parsing (EPUB and raw text)

Type: grilling
Status: resolved
Blocked by: (none)

## Question

Design how a Book (EPUB or raw text) becomes structured Chapters made of
Passages. Needs to settle:

- **EPUB parsing approach**: which library (e.g. ebooklib), how Chapter
  boundaries are detected (spine/TOC vs heading heuristics), how HTML markup
  is stripped down to plain paragraphs, how footnotes and front/back matter
  (title page, copyright, table of contents itself) are excluded from the
  narration.
- **Raw text parsing approach**: how Chapter boundaries are detected in
  plain text (e.g. a heading convention like "Chapitre X", blank-line-delimited
  sections, or a required manual marker) when there's no EPUB structure to
  lean on.
- **Passage extraction**: confirm/refine that one paragraph = one Passage
  (already settled during destination-setting) and define what counts as a
  paragraph boundary in each source format.

## Answer

**Library**: `ebooklib` (read the EPUB, get spine document items via
`get_items_of_type(ebooklib.ITEM_DOCUMENT)`) + `BeautifulSoup` (parse each
item's HTML).

**Chapter boundary detection**: confirmed structurally on the actual test
file (`samples/Les misérables Tome I Fantine.epub`, a Project
Gutenberg-sourced EPUB). Its table of contents is NOT built from duplicate
chapter headings — it's a visually/structurally distinct block using
`<p class="dent">` wrapping `<a class="pginternal">` links formatted as
"Chapitre I--Monsieur Myriel", entirely separate from the real body
headings. A real chapter boundary is: **an `<h2>` whose text matches a
chapter-heading pattern (e.g. `Chapitre \w+`), immediately followed by an
`<h3>`** (the chapter's title, e.g. "Monsieur Myriel"). This naturally
skips the TOC (which never puts an `<h3>` right after its `<a>` links)
without needing to special-case Gutenberg's CSS class names, and is
robust against chapter numbering resetting per *Livre* (Book/Part) — which
is exactly what caused an earlier bug (see
[Pick the test book](02-pick-test-book.md)'s correction): a naive "find all
headings matching 'Chapitre I'" hit two real chapters (one per Livre), not
a TOC duplicate. The fix is to take **the next matching heading in document
order after the current chapter's start**, not to filter/dedupe by heading
text.

**Front/back matter exclusion**: falls out of the same rule — only content
between a valid chapter-boundary heading and the next one is ever
processed. The title page, "TABLE DES MATIÈRES" block, and the Project
Gutenberg license boilerplate item are all outside any such boundary and
excluded automatically, with no separate special-casing needed for this
book.

**Passage extraction**: every `<p>` tag within a chapter's boundary becomes
one Passage, `.get_text()`'d to plain text (inline markup like `<i>`/
`<em>`/`<strong>` is stripped, not preserved — no clean equivalent in
either the Instruct String or TTS input, and not needed for this POC).

**Amendment — whitespace normalization**: found via an empirical test (see
[Design chunking and audio assembly](06-chunking-and-assembly.md)'s longest-
paragraph test) that this EPUB's source HTML soft-wraps paragraph text at
~70-80 characters — `.get_text()` faithfully preserves those as literal
`\n` characters embedded *within* a Passage, not just between paragraphs.
Qwen3-TTS was audibly treating each embedded newline as a pause point,
inserting unwanted mid-sentence pauses. Fix: after `.get_text()`, collapse
every run of whitespace (including embedded newlines/tabs) to a single
space, and strip leading/trailing whitespace, before a Passage's text is
used for the em-dash dialogue check, sent to the Annotation Pass, or sent
to TTS — e.g. `" ".join(p.get_text().split())`.

**Raw text (non-EPUB) parsing**: deferred out of this ticket's scope —
moved to the map's "Not yet specified" fog. Not required to reach this
POC's destination (the actual test input is this one EPUB file); revisit
only if a future effort needs raw-text input.

**Amendment (2026-09-13) — chapter title now narrated; dialogue-detection
bug fixed**: two real, user-reported defects addressed.

(a) *Chapter title never narrated*: `extract_chapter` already extracted
`Chapter.title` (e.g. "Monsieur Myriel") but only `<p>` tags became
Passages, so the title itself was never turned into audio. Fixed at the
call site (`main.py`'s `_build_narration_passages`): the title is now
prepended as narration-item index 0 — always a plain Narrator Line
(`has_dialogue` hard-set `False`, never sent to the Annotation Pass) —
ahead of the Chapter's body Passages, which now sit at indices 1..N
(shifted by one from this ticket's original per-`<p>` indexing). No
checkpoint migration was needed since no real checkpoint data existed yet.

(b) *Dialogue-detection only checked the start of the whole (already
whitespace-collapsed) Passage, missing embedded mid-paragraph dialogue*:
the whitespace-collapsing fix above (see this ticket's prior amendment)
destroyed the very newline information needed to detect a dialogue line
that opens partway through a `<p>` rather than at its very start — e.g. a
narration sentence ending in a colon, followed on a new source line
(within the same `<p>`) by an em-dash-led line of dialogue. The old check
(`annotation._has_em_dash_line`, `passage_text.strip().startswith("—")`)
ran against the collapsed text and could never see this. Fixed by moving
the has-dialogue decision here, to parsing, where the raw pre-collapse
text (with real line breaks) is still available: `Chapter.passages` is now
`list[Passage]` (see `Passage` dataclass, this file) with `text` (normalized,
unchanged) and `has_dialogue` (bool, computed once from the RAW text by
checking every physical line — split on `\n` — for one whose stripped
content starts with "—", not just the first line of the whole Passage).
`main.py` now branches on `passage.has_dialogue` directly; `annotation.py`'s
`needs_annotation_call`/`_has_em_dash_line` were removed as redundant/wrong.
Verified against the real *Fantine* Chapter 1 EPUB: still 16 body passages,
963 words; the line-based check flags the same 2 passages as the old
passage-start check (indices 5 and 6 once the title occupies index 0) —
this chapter's dialogue happens to always open at the start of its `<p>`,
so no additional passage was newly flagged here, but the bug the fix
targets (embedded mid-paragraph dialogue) is real and independently
confirmed against a synthetic repro.

**Amendment (2026-09-13) — non-title headings now narrated, not dropped**:
a real gap found by the project owner. `_iter_body_elements` only ever
yielded `h2`/`h3`/`p`, and the passage-building loop did
`if el.name != "p": continue` — so any OTHER heading-level element inside
a chapter's body (a subtitle, an epigraph, or a "Livre N" section heading
that happens to trail a chapter's last paragraph) was invisible to
narration entirely: not merged, not chunked, just silently never read,
with zero trace.

Fixed by broadening what counts as passage-like content: `_iter_body_elements`
now yields `h1`-`h6` in addition to `p` (checked directly against the real
test EPUB, `samples/Les misérables Tome I Fantine.epub`: it uses h1 — title
page only, "Les Misérables" / "Victor Hugo", entirely outside any chapter
boundary — h2, and h3; no h4/h5/h6 occur anywhere in the file, but the code
handles them generally rather than assuming they'll never appear), and the
passage-building loop no longer special-cases by tag name at all — every
element in `elements[start_idx + 2 : end_idx]` (i.e. everything except the
two boundary-defining elements themselves) becomes a Passage, run through
the exact same `.get_text()` + whitespace-normalization + has_dialogue
logic uniformly, whether it's a `<p>` or a heading.

This can't accidentally swallow the start of the next real chapter:
`end_idx` is still exactly the next chapter boundary's own `<h2>` index,
unchanged by this amendment. Verified directly against the real EPUB: all
70 chapter boundaries are still exactly an `<h2>` matching `Chapitre \w+`
immediately followed by an `<h3>`, and `end_idx` still stops at exactly
that next boundary in every case.

Confirmed against the real book: **Chapter 1 itself has no non-title
headings inside its body** — its slice is exactly the same 16 `<p>`
elements as before this amendment, so the parsing sanity check is
unchanged: 16 body passages, 963 words, same 2 dialogue-flagged passages
(indices 5 and 6 with the title occupying index 0). The gap is real
elsewhere in the same book, though: 8 of the other 69 chapters (e.g.
Chapter 14, "Ce qu'il pensait") have exactly one extra `<h2>` inside their
body — a "Livre N—<title>" section heading (e.g. "Livre deuxième—La
chute") that trails the chapter's last paragraph, immediately before the
next real chapter's own `<h2>`+`<h3>` pair. Before this amendment, that
heading's text was silently dropped for those 8 chapters; after it, it's
narrated as an ordinary trailing Passage. This doesn't change this map's
Chapter-1-only destination, but confirms the fix targets a real defect in
this same EPUB, not a hypothetical one.

**Amendment (2026-09-13, same day) — exclude the EPUB3 nav document**:
found while building a synthetic 2-chapter test fixture
(`tests/fixtures/synthetic_book.epub`) to validate a full end-to-end run
without using either real book. `ebooklib`'s auto-generated `EpubNav`
(table-of-contents) document reports the same item type
(`ebooklib.ITEM_DOCUMENT`) as real content — `get_items_of_type` cannot
tell them apart — so once the amendment above stopped skipping non-`<p>`
elements, the nav document's own `<nav><h2>book title</h2>...</nav>`
heading started leaking into whichever chapter's Passage slice runs
unbounded to the end of `elements` (the last chapter in the book, which
has no following chapter boundary to stop at). Not a problem in the real
test EPUB only because that book's structure happens not to trigger it —
a latent risk there too. Fixed: `extract_chapter` now skips any
`isinstance(item, epub.EpubNav)` item outright before collecting
elements from it. Covered by `tests/test_parsing_nav_exclusion.py`.

Status: resolved
