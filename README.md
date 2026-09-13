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
Chapter (title + ordered Passages, one per source paragraph)
  │  em-dash-prefixed lines flagged as dialogue-bearing (checked before whitespace
  │  collapse, so dialogue that opens on a wrapped source line isn't missed)
  ▼
Annotation Pass (OpenAI, gpt-4o, structured outputs — skipped for pure-narration
  │  Passages, which short-circuit straight to a Narrator Line at zero cost)
  ▼
Lines (speaker, gender, child-or-not, one-sentence tone instruction for dialogue)
  │  Cast: persistent Speaker → Voice mapping, gender/child-partitioned voice pools,
  │  manual override via cast.json
  ▼
TTS synthesis (Qwen3-TTS)
  │  Narrator Lines  → 0.6B-CustomVoice, no tone parameter
  │  Dialogue Lines  → 1.7B-CustomVoice, one-sentence OpenAI-generated instruct string
  │  GPU auto-detected (CUDA + best-effort flash-attention); CPU float32 fallback
  ▼
Assembly (silence-padded concatenation) → output/chapitre_NN_<title>.wav
```

Every step is checkpointed to a JSON manifest keyed by chapter/passage/content-hash, so
an interrupted run resumes from where it left off instead of re-annotating or
re-synthesizing anything already done.

The full design record — why each of these decisions was made, what alternatives were
considered, and what's still open — lives in
[`.scratch/audiobook-prototype/`](.scratch/audiobook-prototype/map.md).

## Requirements

- Python 3.12
- An OpenAI API key (dialogue annotation only — TTS itself never leaves the machine)
- ~4-5 GB disk for the two Qwen3-TTS model weights (0.6B + 1.7B), downloaded on first run
- CPU-only works (validated at roughly 10x slower than real-time on an 8-core, 2016-era
  Xeon); a CUDA GPU is auto-detected and used instead when present, with
  [flash-attention](https://github.com/Dao-AILab/flash-attention) enabled automatically
  if that package is installed — this path is implemented per Qwen3-TTS's own docs but
  hasn't been exercised on real GPU hardware yet

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Optional, GPU only: enables flash-attention automatically when present
pip install flash-attn

export OPENAI_API_KEY=sk-...
export HF_HOME=.hf   # or any writable directory — this is where model weights land
```

A test book isn't included in the repo (see [`samples/README.md`](samples/README.md)) —
grab a *Les Misérables* Tome I EPUB (public domain, e.g. from Project Gutenberg) and
place it at `samples/Les misérables Tome I Fantine.epub`, or point `--book` at any EPUB
with the same "Chapitre N" heading convention.

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

Output lands in `output/`; per-line audio is cached in `audio_cache/`; run state is in
`checkpoints/`. Re-running the same command resumes automatically — already-completed
passages are skipped entirely, and editing the source book only invalidates the
passages affected (and everything sequentially after them in that chapter, since
character-roster tracking depends on processing order).

### Overriding voice casting

Auto-casting assigns each new character a voice from a small gender/age-partitioned
pool. To pin a specific character to a specific voice, create `cast.json` at the project
root:

```json
{
  "Jean Valjean": "Ryan",
  "Cosette": "Vivian"
}
```

Entries here are never touched by auto-casting.

## Scope and limitations

This is a proof of concept, not a general-purpose tool:

- **French only**, EPUB input only (no raw text, no other languages)
- **One chapter at a time** — no whole-book batch mode yet
- **Voice cloning is out of scope** — only Qwen3-TTS's built-in preset voices are used,
  none of which are natively French (cross-lingual synthesis)
- Chapter-boundary detection assumes a Gutenberg-style `<h2>`+`<h3>` "Chapitre N" /
  title heading pair — a different EPUB's structure may need new parsing logic
  (see the design notes on the real target book, *L'Autre Moi*, which needs exactly that)
  before this pipeline could handle it
- Batched TTS calls (multiple lines per model invocation) were deliberately deferred in
  favor of one call per line, for simplicity
