# Audiobook Generator

A CLI toolkit that turns a French EPUB into a narrated audiobook, one chapter at a time:
narrator and characters in distinct voices, dialogue spoken with emotion. TTS synthesis
runs entirely locally; OpenAI is used only to annotate dialogue (who's speaking, their
gender, and the tone to speak it with).

## How it works

```
EPUB
  │  ebooklib + BeautifulSoup — chapter-boundary detection (two supported
  │  conventions, see "Chapter-boundary detection" below), whitespace normalization
  ▼
Chapter (heading + optional title + ordered Passages, one per source paragraph or
  │  non-title heading)
  │  em-dash-prefixed lines flagged as dialogue-bearing (checked before whitespace
  │  collapse, so dialogue that opens on a wrapped source line isn't missed)
  ▼
Annotation Pass (OpenAI, structured outputs — skipped for pure-narration Passages,
  │  which short-circuit straight to a Narrator Line at zero cost)
  ▼
Lines (speaker, gender, child-or-not, multi-dimensional tone instruction for dialogue —
  │  emotion, pace, volume, delivery quality, even an emotional arc within one Line)
  │  Cast: stateless role lookup (narrator/adult_male/adult_female/child) → Voice,
  │  4 configurable defaults via voices.json, per-character override via cast.json
  ▼
Chunks (consecutive Narrator Lines merged across Passages into one call each;
  │  each dialogue Line is its own Chunk) — content-hash-addressed audio caching
  ▼
TTS synthesis (Qwen3-TTS), one call per Chunk
  │  Narrator Chunks  → 0.6B-CustomVoice, one chapter-wide tone (guessed once, cached)
  │  Dialogue Chunks  → 1.7B-CustomVoice, rich OpenAI-generated instruct string
  │  GPU auto-detected (CUDA + best-effort flash-attention); CPU float32 fallback
  ▼
Assembly (silence-padded concatenation between Chunks) → output/chapitre_NN_<title>.wav
```

Every step is checkpointed to a JSON manifest keyed by chapter/passage/content-hash, so
an interrupted run resumes from where it left off instead of re-annotating or
re-synthesizing anything already done.

See [CONTEXT.md](CONTEXT.md) for precise definitions of the terms above (Book, Chapter,
Passage, Line, Voice, Cast, Chunk, ...).

## Requirements

- Python 3.10+ (3.12 tested)
- An OpenAI API key (dialogue annotation only — TTS itself never leaves the machine)
- ~7 GB disk for the two Qwen3-TTS model weights (0.6B ≈ 2.4 GB, 1.7B ≈ 4.3 GB),
  downloaded automatically on first run
- CPU-only works (validated at roughly 10x slower than real-time on an 8-core, 2016-era
  Xeon); a CUDA GPU is auto-detected and used instead when present, with
  [flash-attention](https://github.com/Dao-AILab/flash-attention) enabled automatically
  if that package is installed — this path is implemented per Qwen3-TTS's own docs but
  hasn't been exercised on real GPU hardware yet
- [`tqdm`](https://github.com/tqdm/tqdm) for CLI progress bars (installed via
  `requirements.txt` like everything else — no separate setup step)

## Quickstart

```bash
# Linux / macOS
./setup.sh
source .venv/bin/activate

# Windows (PowerShell)
.\setup.ps1
.venv\Scripts\Activate.ps1
```

Then, in the activated environment:

```bash
export OPENAI_API_KEY=sk-...          # $env:OPENAI_API_KEY = "sk-..." on Windows
export HF_HOME="$(pwd)/.hf"           # $env:HF_HOME = "$(Resolve-Path .hf)" on Windows

python src/audiobook/main.py --book /path/to/your-book.epub --chapter 1
```

The first real run downloads both TTS models (~7 GB total) into `HF_HOME` — this only
happens once. Pass `--gpu` to either setup script if you have a supported NVIDIA GPU and
want the CUDA-enabled build of PyTorch instead of the default CPU-only one.

`--book` is required and points at your own EPUB — there's no bundled test book in the
repo. For a quick trial, grab a *Les Misérables* Tome I EPUB (public domain, e.g. from
Project Gutenberg), which matches the "Chapitre N" heading convention this pipeline was
built against; a different book's heading structure may need new parsing logic (see
[Scope and limitations](#scope-and-limitations)).

## Usage

```bash
python src/audiobook/main.py --book /path/to/your-book.epub --chapter 1 --workers 2
```

| Flag | Default | Meaning |
|---|---|---|
| `--book PATH` | *(required)* | EPUB to narrate |
| `--chapter N` | `1` | Chapter number to synthesize (1-indexed). Mutually exclusive with `--all-chapters` |
| `--all-chapters` | off | Process every chapter in the book, in order (1..N — see "Chapter-boundary detection" below for how N is determined). Mutually exclusive with `--chapter` |
| `--workers N` | `2` | Parallel TTS worker processes |
| `--skip-tts` | off | Parse + annotate only, no synthesis (useful to sanity-check annotation cost/output before committing to a full run) |
| `--openai-model NAME` | `gpt-5.6-luna` (or `$OPENAI_MODEL` if set) | Model used for the Annotation Pass — must support structured outputs (`response_format={"type": "json_schema", ...}`) |
| `--narrator-tone` / `--no-narrator-tone` | on | Guess the Chapter's overall narrative tone from its opening (one extra OpenAI call, cached per Chapter) and give every Narrator Chunk that same instruct string; `--no-narrator-tone` goes back to Narrator Chunks carrying no instruct at all |

Output lands in `output/`; per-chunk audio is cached in `audio_cache/` (content-hash
addressed — a chunk is a run of merged consecutive Narrator lines, or one dialogue line);
run state is in `checkpoints/` (annotation only). Re-running the same command resumes
automatically — already-annotated passages are skipped, and editing the source book only
invalidates the passages affected (and everything sequentially after them in that
chapter, since character-roster tracking depends on processing order); already-cached
chunk audio is skipped independently, since it's addressed by content hash rather than
passage position.

Progress bars (via `tqdm`) show passage-annotation progress within the current chapter,
chunk-synthesis progress within the current chapter, and (with `--all-chapters`) overall
chapter progress across the book; the same detailed per-passage/per-chunk status lines
print alongside the bars as before, just routed through `tqdm.write` so they don't
garble the bar's redraw.

### Whole-book batch mode (`--all-chapters`)

```bash
python src/audiobook/main.py --book /path/to/your-book.epub --all-chapters --workers 2
```

Loops chapters 1..N (N from `parsing.count_chapters`), calling the same per-chapter
pipeline as `--chapter` for each — this is purely an outer loop around the existing
single-chapter `run()`, so every existing per-Passage/per-Chunk resumability guarantee
still applies within each chapter. Two behaviors are specific to `--all-chapters`:

- **Chapter-level resumability**: a chapter is skipped ENTIRELY (no annotation, no
  synthesis, just a log line) if its output WAV already exists in `output/`. Combined
  with the existing per-Passage/per-Chunk resumability, this means a whole-book run can
  be interrupted and resumed at any point — already-finished chapters aren't touched at
  all, a partially-finished chapter picks up from its last checkpointed Passage/Chunk.
- **Stop on first failure**: the batch aborts immediately on the first chapter that
  raises (an Annotation Pass or synthesis failure, say) rather than silently skipping it
  and moving on — consistent with this project's "abort loudly, resumability makes it
  safe to just rerun" philosophy. The error message names which chapter failed; simply
  re-running the exact same `--all-chapters` command resumes from there (already-done
  chapters are skipped via the output-file check above; already-annotated Passages and
  already-synthesized Chunks within the chapter that failed are skipped via the existing
  checkpoint/content-hash caches).

### Overriding voice casting

Voice casting is driven by 4 fixed, configurable **role**-voices — a Speaker's voice is
looked up from its role (`narrator`, `adult_male`, `adult_female`, or `child`, derived
from `is_narrator` + `speaker_gender` + `speaker_is_child`), not assigned per-character.
By default:

| Role | Default voice |
|---|---|
| `narrator` | Ryan |
| `adult_male` | Ryan (same as the narrator — intentional) |
| `adult_female` | Serena |
| `child` (either stated gender) | Vivian |

To change any of these, create `voices.json` at the project root with just the keys you
want to override — any key you omit falls back to its own default individually:

```json
{
  "adult_female": "Vivian"
}
```

Since a Chunk's audio filename is content-hash-addressed over its text/voice/instruct
(see [How it works](#how-it-works)), changing a role's voice in `voices.json` does not
force any already-synthesized audio to be regenerated — only Chunks whose resolved voice
actually changed get a new file. Chunk filenames are `chunk_{role}_{hash}.wav` (e.g.
`chunk_adult_female_3f9a...wav`), where `{role}` is a human-readable prefix (not part of
the hash) so you can find and manually delete a whole category of cached chunks — e.g.
`rm audio_cache/<book>/chapter_01/chunk_adult_female_*.wav` — to force just those to
resynthesize after changing that role's voice.

To pin one specific named character to a specific voice regardless of its role, create
`cast.json` at the project root:

```json
{
  "Jean Valjean": "Ryan",
  "Cosette": "Vivian"
}
```

`cast.json` entries are checked before the role-based default and always win (this
includes overriding "Narrator" itself, if you want).

## Scope and limitations

- **French only**, EPUB input only (no raw text, no other languages)
- **Voice cloning is out of scope** — only Qwen3-TTS's built-in preset voices are used,
  none of which are natively French (cross-lingual synthesis)
- Synthesis batching is per-chunk (consecutive narrator lines merged, one call each;
  each dialogue line always its own call) — batching multiple *dialogue* lines from the
  same speaker together was deliberately deferred, for simplicity
- **Guillemets (« ») are never treated as a dialogue-turn marker** — only a leading
  em-dash (—) triggers the Annotation Pass (`has_dialogue`/`_has_dialogue_line` in
  `parsing.py`). This is a deliberate, accepted limitation, not an oversight: investigated
  directly against a real book (L'Autre Moi) where guillemets appear in most chapters,
  they're overwhelmingly used as scare-quotes around a single term (e.g. `«Longepin»`) or
  short quoted written notes (e.g. `«Te voilà au courant de tout.»`), not to open a
  spoken dialogue turn the way em-dash is used in that same book. Extending detection to
  guillemets would likely cause many false-positive OpenAI calls on pure narration that
  merely quotes a term, without reliably catching genuinely missed dialogue — the
  evidence doesn't support guillemets marking dialogue turns in this kind of book. A
  chapter with dialogue conventions this pipeline doesn't recognize may occasionally
  narrate a dialogue line in the Narrator's voice instead of a character's — an accepted
  imprecision for a personal tool, same spirit as the occasional speaker misattribution
  already accepted elsewhere in this codebase.

### Chapter-boundary detection

Two conventions are supported (tried in this order, `parsing.extract_chapter` /
`parsing.count_chapters`):

1. **EPUB3 semantic section** (tried first): any `<section epub:type="chapter">`
   found anywhere in the book, walked in spine order. If one or more are found, that's
   this book's convention — the Nth such section is chapter N. Within a section,
   `heading` is the text of the first heading element (`h1`-`h6`) found inside it —
   narrated verbatim even when it's just a bare number (e.g. "1", as in L'Autre Moi,
   which has no separate subtitle at all) — and `title` is a second, distinct heading if
   one exists, else `""` (never fabricated; an empty title produces no title Passage).
   Passages are every `<p>` found anywhere inside the section (recursively, so a
   paragraph nested inside a wrapper `<div>` is still found). A book can exclude a
   section from the count entirely just by giving it a different `epub:type` (e.g.
   L'Autre Moi's Préface is `epub:type="preface"` — correctly not counted as a chapter).
2. **Gutenberg-style** (fallback, used only when no `epub:type="chapter"` sections exist
   anywhere in the book): an `<h2>` matching `"Chapitre \w+"` immediately followed by an
   `<h3>` (the title) — the original convention this pipeline was built against. A
   different EPUB's structure (a different heading pattern, chapters already split
   one-per-file without EPUB3 semantic markup, etc.) matching neither convention would
   need new parsing logic before this pipeline could handle it.
