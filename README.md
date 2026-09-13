# Audiobook Generator

A CLI prototype that turns a French EPUB into a narrated audiobook: one WAV file per
chapter, narrator and characters in distinct voices, dialogue spoken with emotion. TTS
synthesis runs entirely locally; OpenAI is used only to annotate dialogue (who's
speaking, their gender, and the tone to speak it with).

Currently scoped to one chapter of one test book (see [Scope](#scope-and-limitations)) as
a proof of concept before attempting a full-length novel.

## How it works

```
EPUB
  │  ebooklib + BeautifulSoup — chapter-boundary detection, whitespace normalization
  ▼
Chapter (title + ordered Passages, one per source paragraph or non-title heading)
  │  em-dash-prefixed lines flagged as dialogue-bearing (checked before whitespace
  │  collapse, so dialogue that opens on a wrapped source line isn't missed)
  ▼
Annotation Pass (OpenAI, gpt-4o, structured outputs — skipped for pure-narration
  │  Passages, which short-circuit straight to a Narrator Line at zero cost)
  ▼
Lines (speaker, gender, child-or-not, one-sentence tone instruction for dialogue)
  │  Cast: stateless role lookup (narrator/adult_male/adult_female/child) → Voice,
  │  4 configurable defaults via voices.json, per-character override via cast.json
  ▼
Chunks (consecutive Narrator Lines merged across Passages into one call each;
  │  each dialogue Line is its own Chunk) — content-hash-addressed audio caching
  ▼
TTS synthesis (Qwen3-TTS), one call per Chunk
  │  Narrator Chunks  → 0.6B-CustomVoice, no tone parameter
  │  Dialogue Chunks  → 1.7B-CustomVoice, one-sentence OpenAI-generated instruct string
  │  GPU auto-detected (CUDA + best-effort flash-attention); CPU float32 fallback
  ▼
Assembly (silence-padded concatenation between Chunks) → output/chapitre_NN_<title>.wav
```

Every step is checkpointed to a JSON manifest keyed by chapter/passage/content-hash, so
an interrupted run resumes from where it left off instead of re-annotating or
re-synthesizing anything already done.

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

python src/audiobook/main.py --chapter 1
```

The first real run downloads both TTS models (~7 GB total) into `HF_HOME` — this only
happens once. Pass `--gpu` to either setup script if you have a supported NVIDIA GPU and
want the CUDA-enabled build of PyTorch instead of the default CPU-only one.

A test book isn't included in the repo — grab a *Les Misérables* Tome I EPUB (public
domain, e.g. from Project Gutenberg) and place it at
`samples/Les misérables Tome I Fantine.epub`, or point `--book` at any EPUB with the same
"Chapitre N" heading convention.

## Usage

```bash
python src/audiobook/main.py --chapter 1 --workers 2
```

| Flag | Default | Meaning |
|---|---|---|
| `--book PATH` | `samples/Les misérables Tome I Fantine.epub` | EPUB to narrate |
| `--chapter N` | `1` | Chapter number to synthesize (1-indexed) |
| `--workers N` | `2` | Parallel TTS worker processes |
| `--skip-tts` | off | Parse + annotate only, no synthesis (useful to sanity-check annotation cost/output before committing to a full run) |
| `--openai-model NAME` | `gpt-5.6-luna` (or `$OPENAI_MODEL` if set) | Model used for the Annotation Pass — must support structured outputs (`response_format={"type": "json_schema", ...}`) |

Output lands in `output/`; per-chunk audio is cached in `audio_cache/` (content-hash
addressed — a chunk is a run of merged consecutive Narrator lines, or one dialogue line);
run state is in `checkpoints/` (annotation only). Re-running the same command resumes
automatically — already-annotated passages are skipped, and editing the source book only
invalidates the passages affected (and everything sequentially after them in that
chapter, since character-roster tracking depends on processing order); already-cached
chunk audio is skipped independently, since it's addressed by content hash rather than
passage position.

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

This is a proof of concept, not a general-purpose tool:

- **French only**, EPUB input only (no raw text, no other languages)
- **One chapter at a time** — no whole-book batch mode yet
- **Voice cloning is out of scope** — only Qwen3-TTS's built-in preset voices are used,
  none of which are natively French (cross-lingual synthesis)
- Chapter-boundary detection assumes a Gutenberg-style `<h2>`+`<h3>` "Chapitre N" /
  title heading pair — a different EPUB's structure (a different heading pattern, or
  chapters already split one-per-file) would need new parsing logic before this
  pipeline could handle it
- Synthesis batching is per-chunk (consecutive narrator lines merged, one call each;
  each dialogue line always its own call) — batching multiple *dialogue* lines from the
  same speaker together was deliberately deferred, for simplicity
