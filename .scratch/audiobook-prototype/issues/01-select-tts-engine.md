# Select the TTS engine

Type: research
Status: resolved
Blocked by: (none)

## Question

Which local, CPU-only TTS engine should this prototype use? Validate
Qwen3-TTS (github.com/QwenLM/Qwen3-TTS) against alternatives — Coqui
XTTS-v2, Piper, MeloTTS, F5-TTS, Kokoro — on:

- **CPU-only feasibility and realistic throughput** on an 8-core Xeon
  E3-1245 v5 (Skylake, ~2016), 23GB RAM, no GPU. Prior research found
  Qwen3-TTS's README assumes CUDA and only has unofficial/community reports
  of CPU inference at 5-10x slower than GPU — treat that as unverified and
  test or find harder evidence.
- **French audio quality** — actual quality, not just "French listed as
  supported" (Qwen3-TTS lists French among 10 languages but has no French
  preset voice).
- **Distinct Preset Voices available** — need at least ~5 (1 narrator + a
  4-8 character pool), with genuinely distinguishable timbres, and usable
  in French. Voice cloning is out of scope, so an engine's cloning quality
  doesn't count in its favor unless it also ships usable presets.
- **Emotion/instruct control** — natural-language tone control (like
  Qwen3-TTS's `instruct` parameter) is strongly preferred over no control at
  all, but note whatever mechanism each alternative actually offers.
- **License** — commercial-use-friendly is a plus but not a hard requirement
  for a personal prototype; note it regardless (e.g. Coqui XTTS-v2 and
  F5-TTS have non-commercial-flavored licensing to double check).

Produce a decision (which engine) with the rationale, and flag any
follow-on unknowns the choice creates (e.g. actual preset voice roster,
max input length per synthesis call, output sample rate).

## Answer

**Qwen3-TTS-12Hz-0.6B-CustomVoice**, run on CPU in `torch.float32`
(`device_map="cpu"`, no flash-attn, no bf16/CUDA).

Written research (`01-select-tts-engine.research.md`) initially recommended
Piper: it's the only engine surveyed with several real French-native preset
voices and is CPU-native/fast, but has zero emotion/tone control. Qwen3-TTS
has best-in-class natural-language `instruct`-string emotion control but no
French-native preset voices (its 9 presets are Chinese/English/Japanese/
Korean; French is a supported *language* any preset can speak, just not a
labeled native French voice) and an undocumented CPU story (README only
shows `device_map="cuda:0"`, bf16/FlashAttention2).

Rather than accept the write-up's recommendation on paper, we ran an
empirical CPU test on this machine (8-core Xeon E3-1245 v5, 23GB RAM):
`Qwen3-TTS-12Hz-0.6B-CustomVoice` loads and runs successfully in plain
float32 on CPU (no CUDA needed at all, contrary to what the README implies).
Measured **RTF ≈ 10** (10x slower than real-time) synthesizing French text
with the `Vivian` and `Ryan` presets, including a working `instruct` string
on the Ryan sample. User listened to the resulting WAV output directly and
judged the quality "awesome."

Given the actual test book is now scoped to just Chapter 1 of *Fantine*
(see [Pick the test book](02-pick-test-book.md)), RTF≈10 implies real
compute time for that chapter's narration. **Correction**: the word count
used here originally was wrong — a chapter-extraction bug (see ticket 02's
answer) grabbed a different, much longer chapter. The real Chapter 1
("Monsieur Myriel," Livre premier) is **963 words, ~16 paragraphs**, i.e.
roughly **7 minutes of narrated audio** at a normal pace, implying **~70
minutes of CPU compute at RTF≈10** — not the ~4.5-5 hours originally
estimated. Still a non-trivial offline batch run, but far more comfortable
than first thought. User had already accepted the original (worse) estimate
as a non-issue for an offline/unattended POC run — "Wav file time is not a
problem" — so this correction only makes the decision easier, not harder.

**Decision: Qwen3-TTS over Piper.** Emotion control (the project's core
differentiator) outweighs the missing native-French-preset gap and the long
but tolerable CPU runtime. French is handled cross-lingually via the
existing 9 presets (no French-native accent, but functional and, per this
test, high quality).

Follow-on unknowns still open for later tickets:
- Final preset-voice pool selection out of the 9 available (see
  [Design the Cast](05-design-cast.md)) — need to pick which ~5 sound
  distinguishable and acceptable for French narration/characters.
- Max input length per `generate_custom_voice` call and Piper-style
  chunking needs (see [Design chunking and audio assembly](06-chunking-and-assembly.md)) —
  not yet empirically tested beyond single short sentences.
- Output sample rate and audio format from `model.generate_custom_voice`
  (observed `sr` value should be recorded when chunking/assembly is
  designed).
- This EPUB's actual chapter structure doesn't map 1:1 to spine items —
  Project Gutenberg bundled multiple chapters per XHTML file with heading
  tags (`<h2>Chapitre I</h2>`) marking real boundaries — relevant for
  [Design Book parsing](04-parsing-design.md).

**Amendment (2026-09-13) — dual-model architecture: 0.6B for Narrator,
1.7B for dialogue**: re-reading the official Qwen3-TTS README's own feature
table (not the model cards checked in the research follow-up above) surfaced
that "Instruction Control" is marked ✅ only for the **1.7B**-CustomVoice and
1.7B-VoiceDesign models — the **0.6B**-CustomVoice model this ticket
originally chose has no checkmark there, and the InstructTTSEval benchmark
table only scores 1.7B variants. In other words: the `instruct` parameter
this ticket picked Qwen3-TTS *for* (over Piper, per the decision above) is
not actually documented/benchmarked as working on the 0.6B model at all —
only on 1.7B.

Decision: **route by Line kind, not one fixed model for the whole book**.
- **Narrator Lines** (`is_narrator=true`, chapter titles included — always
  Narrator Lines) → **`Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice`**, `instruct=None`
  always. This was already true of the code (Narrator Lines never carried an
  Instruct String), so nothing behavioral changes here — it's now an
  explicit, permanent model-routing rule rather than an incidental fact of
  which model happened to be loaded.
- **Dialogue Lines** (any non-Narrator Speaker) →
  **`Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice`**, with the one-sentence
  OpenAI-generated `instruct` string (see
  [Design the OpenAI annotation contract](03-annotation-contract.md), prompt
  tightened to say "exactly ONE SENTENCE").

**Device auto-detection + best-effort flash-attention**: model loading now
detects `torch.cuda.is_available()` at load time (shared by both model
sizes, one function). GPU present → `device_map="cuda:0"`,
`dtype=torch.bfloat16`, and `attn_implementation="flash_attention_2"` added
only if `import flash_attn` succeeds (checked live, never assumed) — if it
doesn't import, or if passing it to `from_pretrained` ever raises, the load
silently falls back to the default attention implementation on GPU rather
than failing. No GPU → falls back to exactly this ticket's already-proven
CPU path (`device_map="cpu"`, `dtype=torch.float32`, no attn kwarg). This
logic is never allowed to hard-fail the pipeline over a missing GPU or
missing flash-attn.

**This dev machine has no GPU.** Only the CPU-fallback branch is verified
for real on this hardware; the CUDA + flash-attention branch is implemented
per the README's documented pattern but is unverified beyond a unit test
that monkeypatches `torch.cuda.is_available()` to confirm the right
`from_pretrained` kwargs get constructed (real GPU execution untested). That
test is checked in at `tests/test_tts_device_selection.py` — a review pass
found the original implementation claimed this coverage without it actually
being persisted to the repo; it's a real file now, runnable directly
(`python tests/test_tts_device_selection.py`, no pytest dependency).

**Amendment (2026-09-13, same day) — narrowed the flash-attn failure
catch**: the same review pass found `load_model`'s retry-without-flash-attn
`except Exception` was unfiltered — it would silently retry (and
misattribute to flash-attn) *any* `from_pretrained` failure, including ones
with nothing to do with attention (bad HF cache, OOM, a network error
fetching weights), permanently and silently forfeiting flash-attention
acceleration for an unrelated transient problem, and discarding the original
(possibly more informative) exception if the retry also failed. Fixed:
`_looks_like_attn_implementation_failure` checks the exception message for
attention/flash-related wording before deciding to retry without the kwarg;
anything else propagates immediately as itself. Covered by
`tests/test_tts_device_selection.py`'s two failure-path cases.

**Model loading is now lazy, per model, per worker process**: a
`ProcessPoolExecutor` worker loads the 0.6B model the first time it actually
receives a narrator-kind job, and separately loads the 1.7B model the first
time it receives a dialogue-kind job — each cached for that worker's
lifetime, never reloaded. A worker that only ever gets narrator jobs never
loads 1.7B, and vice versa. (Previously, `init_worker` eagerly loaded one
fixed model per worker at pool startup; this is now deferred to first-use,
per-model.)

**Batching remains explicitly deferred** — one `generate_custom_voice` call
per Line, as before; this amendment only changes which model a Line's call
goes to and when each model gets loaded.

Informally (no formal write-up file for this): paired 0.6B-vs-1.7B
instruct-following audio samples from an earlier benchmarking pass are kept
at `.venv-qwen-test/instruct_comparison/` (with a manifest README) for the
project owner's own listening comparison — not part of this ticket's formal
answer, just supporting listening evidence for the decision above.
