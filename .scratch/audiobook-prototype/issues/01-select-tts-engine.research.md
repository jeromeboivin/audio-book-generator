# Research: Which local, CPU-only TTS engine should this prototype use?

## Recommendation

**Piper.** It is the only candidate that ships several distinct,
genuinely French-trained preset voices (six-to-seven named speaker
checkpoints across `siwis`, `upmc` (2 speakers), `gilles`, `tom`, and
`mls_1840`/`mls`) without touching voice cloning, and it is by a wide
margin the fastest and most CPU-native of the six engines (designed for
Raspberry Pi–class hardware, documented real-time factor around
0.2 — roughly 5x faster than real time), which comfortably clears
"hours not days" on an 8-core 2016 Xeon. Its engine license (MIT) and
most voice licenses (CC0/CC-BY/MIT, verified per-voice) are unrestricted
for a personal project. The real cost is that Piper has **no
emotion/tone control mechanism at all** (only speed/noise-scale knobs)
and its French voices are older-generation single/dual-speaker
vocoder-based models (16–22kHz, "low"/"medium" quality tiers) —
noticeably less natural and less expressive than Qwen3-TTS or XTTS-v2.
Given the ticket's own framing — French preset variety is a hard
requirement, emotion control is "ideal but not disqualifying" — Piper
is the most honest fit. See the "Open questions" section for a
flagged alternative worth putting back to the user before committing.

No candidate in this set cleanly satisfies *both* "≥5 distinguishable
French presets" and "natural-language emotion control." That is the
central finding of this research and should be treated as an accepted
prototype limitation, not a research gap: emotion/tone control for
Narrator/character Lines synthesized via Piper will most likely have to
come from something outside the TTS engine itself (e.g. punctuation/
pacing tricks, or a later swap to a different engine per character) —
flagged as a follow-on unknown below.

---

## Per-candidate breakdown

### Qwen3-TTS (github.com/QwenLM/Qwen3-TTS)

- **CPU feasibility**: Unverified from primary sources. The official
  README documents FlashAttention2 as an optional optimization (only
  usable with fp16/bf16 weights) but does not document a CPU-only
  inference path or give any CPU throughput numbers.
  [github.com/QwenLM/Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS).
  Prior session research found only unofficial/community claims of
  ~5-10x slower than GPU — no primary source confirms this.
- **French presets**: **None.** The 9 (this research counted 9, not
  10 — Dylan and Eric are both Chinese-dialect variants, not separate
  language slots) CustomVoice presets are Vivian, Serena, Uncle_Fu,
  Dylan, Eric (Chinese); Ryan, Aiden (English); Ono_Anna (Japanese);
  Sohee (Korean). French is listed as a supported *language* only,
  reachable solely via voice cloning (Base model + reference audio) or
  VoiceDesign (voice built from a text description) — neither is a
  built-in French preset.
- **Emotion control**: Best-in-class of everything surveyed —
  natural-language `instruct` string (e.g. "speak in an especially
  angry tone") passed straight to the CustomVoice model.
- **License**: Apache-2.0.
- **Maintained**: Yes — real, recent project (initial release dated
  2026-01-22 per the repo), 0.6B/1.7B model sizes.
- **Verdict**: Eliminated by the French-preset requirement alone;
  CPU feasibility is also unverified risk.

### Coqui XTTS-v2 (huggingface.co/coqui/XTTS-v2, github.com/coqui-ai/TTS)

- **CPU feasibility**: No primary-source CPU RTF numbers found. Coqui's
  own docs and third-party benchmarks discuss GPU RTF only (~0.25-0.3
  on GPU); CPU is widely described in secondary sources as "extremely
  slow" for a full transformer+diffusion-decoder architecture of this
  size, but no hard CPU number could be verified from an official
  source.
  [huggingface.co/coqui/XTTS-v2](https://huggingface.co/coqui/XTTS-v2),
  [docs.coqui.ai/en/latest/models/xtts.html](https://docs.coqui.ai/en/latest/models/xtts.html).
- **French presets**: French is one of 17 supported languages, but
  XTTS-v2 is architecturally a **voice-cloning** model (6-second
  reference clip). It does ship ~58 built-in "studio speakers" (e.g.
  Claribel Dervla, Andrew Chipper, Ana Florence — full list at
  [github.com/coqui-ai/TTS discussions](https://github.com/coqui-ai/TTS/issues/3434)
  and the model's `/studio_speakers` endpoint) that can be used without
  supplying your own reference audio, but these are generic
  cross-lingual speaker embeddings, not labeled or trained specifically
  as French voices — quality/accent-fit in French is unverified and not
  documented by Coqui.
- **Emotion control**: Only via cloning a reference clip's
  emotion/style — no text-instruction mechanism.
- **License**: Coqui Public Model License (CPML) — non-commercial only,
  and Coqui Inc. shut down in January 2024 so no commercial license can
  currently be purchased at any price. Fine for a personal prototype,
  worth flagging per the ticket's ask.
  [huggingface.co/coqui/XTTS-v2/resolve/main/LICENSE.txt](https://huggingface.co/coqui/XTTS-v2/resolve/main/LICENSE.txt?download=true),
  [github.com/coqui-ai/TTS/discussions/4304](https://github.com/coqui-ai/TTS/discussions/4304).
- **Maintained**: Ambiguous — model and repo still exist and are
  usable, but the company behind it closed; community forks
  (coqui-tts) carry it forward.
- **Verdict**: Eliminated — no real French presets, CPU throughput
  unverified/likely poor, license overhead not worth it given the
  preset gap.

### Piper (github.com/rhasspy/piper, archived Oct 2025 → moved to
github.com/OHF-Voice/piper1-gpl)

- **CPU feasibility**: Purpose-built for CPU/edge inference (embeds
  espeak-ng for phonemization, ONNX runtime). Community benchmarks
  report RTF ≈ 0.19–0.2 (~5x faster than real time) on ordinary CPU
  hardware; official guidance notes a Raspberry Pi 4 handles low-quality
  voices in real time and lags on medium/high, while a Raspberry Pi 5
  does medium-quality in real time on CPU alone — i.e. an 8-core 2016
  desktop Xeon (far more powerful per-core and in core count than either
  Pi) should render a short book in well under an hour of audio-minutes
  processed. No single official benchmark table was found for the exact
  E3-1245 v5 CPU; the Pi-based numbers are the most credible ceiling
  reference available.
  [aivideosensei.com/guides/piper-tts-offline-voice-guide](https://aivideosensei.com/guides/piper-tts-offline-voice-guide),
  [github.com/rhasspy/piper](https://github.com/rhasspy/piper).
- **French presets**: Real, named, French-trained voices exist as
  separate downloadable checkpoints under `fr/fr_FR` on
  [huggingface.co/rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices/tree/main/fr/fr_FR):
  `siwis` (low & medium quality, single female speaker, from the SIWIS
  French corpus), `upmc` (medium, **2 speakers**: `jessica` and
  `pierre`), `gilles` (low, single speaker), `tom` (medium, single
  speaker), `mls_1840` (low, single speaker), and `mls` (medium,
  multi-speaker French subset of Multilingual LibriSpeech). Counting
  distinct named speaker identities this is **6–7 distinguishable
  French voices**, clearing the ≥5-presets bar — the only engine in
  this survey that does, without cloning. Quality is dated (older
  VITS/glow-style single-speaker acoustic models, 16–22kHz output,
  "low"/"medium" tiers per Piper's own quality taxonomy), not
  studio-neutral SOTA naturalness.
- **Emotion control**: **None.** Piper exposes only `length_scale`
  (speed), `noise_scale`, and `noise_w` (prosody randomness/jitter) —
  no text-instruction or discrete-emotion-tag mechanism.
- **License**: Engine code MIT (original repo) / GPL-3.0 for the newer
  `OHF-Voice/piper1-gpl` fork the project has moved to (worth noting:
  license changed on the fork the ecosystem is migrating to — GPL-3.0
  is still fine for a personal, non-distributed prototype but is
  copyleft, unlike the original MIT). Individual voice models carry
  their own licenses (mix of CC0, CC-BY, MIT, Apache-2.0, and a few
  "non-commercial research only" — must be checked per-voice on each
  voice's Hugging Face model card before any commercial use; not
  disqualifying for this personal prototype).
  [github.com/rhasspy/piper/discussions/271](https://github.com/rhasspy/piper/discussions/271).
- **Maintained**: The original `rhasspy/piper` repo was archived
  2025-10-06 (read-only) with development continuing at
  `OHF-Voice/piper1-gpl` — actively maintained there, and Piper voice
  files remain hosted and unaffected. Widely embedded in Home Assistant,
  NVDA, etc.
- **Verdict**: **Recommended.** Best fit for CPU throughput + real
  French preset count + usable license; weakest on emotion control and
  raw voice naturalness.

### MeloTTS (github.com/myshell-ai/MeloTTS)

- **CPU feasibility**: README/docs assert "CPU is sufficient for
  real-time inference" but no RTF numbers or benchmark table were found
  on any official page.
  [github.com/myshell-ai/MeloTTS](https://github.com/myshell-ai/MeloTTS),
  [raw install docs](https://raw.githubusercontent.com/myshell-ai/MeloTTS/main/docs/install.md).
- **French presets**: **Only one French speaker.** The official usage
  example calls `TTS(language='FR')` and then `speaker_ids['FR']` —
  a single speaker slot, confirmed via the
  [myshell-ai/MeloTTS-French](https://huggingface.co/myshell-ai/MeloTTS-French)
  model card and install docs. English has multiple accent variants
  (American/British/Indian/Australian/Default) but those are not French
  voices and would sound accented/foreign if used to read French text —
  not a credible substitute for a French character pool.
- **Emotion control**: None documented — only a `speed` parameter.
- **License**: MIT, explicitly stated as commercial-use-friendly.
- **Maintained**: Active-looking community project (7.6k GitHub stars,
  94+ commits), but no evidence of recent (2026) commits was surfaced.
- **Verdict**: Eliminated — fails the ≥5-French-presets requirement
  outright (1 preset), no emotion control, unverified CPU numbers.

### F5-TTS (github.com/SWivid/F5-TTS)

- **CPU feasibility**: Documentation and benchmarks focus entirely on
  GPU (NVIDIA/AMD/Intel/Apple Silicon); the only RTF figure found is
  0.0394 on a single NVIDIA L20 GPU. No CPU inference path or numbers
  are documented.
  [github.com/SWivid/F5-TTS](https://github.com/SWivid/F5-TTS).
- **French presets**: **None, and architecturally can't have any.**
  F5-TTS is a zero-shot voice-cloning system (flow-matching DiT driven
  by a reference clip) with no preset-voice concept at all. There is no
  official French model; a community-trained French checkpoint exists
  (per [github.com/SWivid/F5-TTS/issues/434](https://github.com/SWivid/F5-TTS/issues/434)
  and the unofficial [RASPIAUDIO Hugging Face Space](https://huggingface.co/spaces/RASPIAUDIO/f5-tts_french),
  reportedly trained on ~80k samples/100 epochs, single speaker) — still
  cloning-only, and single-speaker besides.
- **Emotion control**: "Multi-style" generation exists but is
  reference-audio-driven, not instruction-driven.
- **License**: Pretrained models are CC-BY-NC due to the Emilia
  training dataset — non-commercial only, matching the ticket's flagged
  concern.
- **Maintained**: Yes — active repo (700+ commits, ongoing issues/PRs,
  last major update noted 2025-03-12).
- **Verdict**: Eliminated — no presets by design, no official French
  support, GPU-oriented, non-commercial license.

### Kokoro (github.com/hexgrad/kokoro, huggingface.co/hexgrad/Kokoro-82M)

- **CPU feasibility**: Small model (82M params) that runs well on CPU
  in practice; third-party CPU/ONNX benchmarks show RTF roughly
  0.5–0.7 depending on runtime and text length (e.g. a 22-second
  narration in ~3.5s on an Apple M3 Pro via `kokoro-onnx`) — fast enough
  to be very plausible on an 8-core Xeon, though no official Xeon-class
  x86 server benchmark was found.
  [gist.github.com/efemaer](https://gist.github.com/efemaer/23d9a3b949b751dde315192b4dcf0653),
  [huggingface.co/hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M).
- **French presets**: **Only one French voice: `ff_siwis`** (per the
  official [VOICES.md](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md),
  which lists French (`f`) with exactly 1 voice, versus 20 American
  English, 8 British English, 8 Mandarin, etc.). Notably `ff_siwis` is
  trained from the same SIWIS French corpus as Piper's `fr_FR-siwis`
  voice — i.e. the same underlying single French speaker, just a
  different model architecture. Total presets across all 8 languages:
  54 (per Kokoro-82M v1.0), but only 1 is French.
- **Emotion control**: None documented in the official model card.
- **License**: Apache-2.0 — fully permissive.
- **Maintained**: Active (71+ commits, 35 open PRs, 173 issues,
  ongoing releases past v0.9.4).
- **Verdict**: Eliminated for this project's French-preset-count
  requirement (1 preset), despite being an otherwise strong,
  well-licensed, CPU-friendly engine — same failure mode as MeloTTS.

---

## Open questions / caveats to flag back to the user

1. **No engine here offers both real French preset variety and
   natural-language emotion control.** Piper wins on presets/CPU/
   license and loses completely on emotion control. Qwen3-TTS wins
   completely on emotion control and loses completely on French
   presets (and has unverified CPU feasibility). This is a real
   trade-off inherent to the current open-source TTS landscape, not a
   gap in this research.

2. **Worth reconsidering, separately from the main recommendation**:
   Qwen3-TTS's **VoiceDesign** feature generates a voice from a
   natural-language *text description* rather than a reference audio
   clip. Depending on how strictly "voice cloning is out of scope"
   is meant, VoiceDesign arguably isn't cloning at all (no reference
   audio, no impersonation of a specific real voice) — it could be used
   to generate a small fixed roster of French-sounding character voices
   once, then reused as fixed presets thereafter, while keeping
   Qwen3-TTS's superior `instruct` emotion control. This still leaves
   Qwen3-TTS's CPU-feasibility gap unresolved and its output voices
   would not be verified/labeled French by Qwen. Flagging this as a
   scope question for the user rather than folding it into the
   recommendation, since it brushes against the cloning-is-out-of-scope
   decision already made in CONTEXT.md.

3. **Piper voice quality is dated.** All the French Piper voices are
   older single/dual-speaker neural vocoder checkpoints (16–22kHz,
   "low"/"medium" quality tier in Piper's own taxonomy) — expect
   noticeably more robotic/flat delivery than Qwen3-TTS, XTTS-v2, or
   Kokoro would produce, independent of the missing emotion control.

4. **Piper's per-voice licenses need a one-time check before use.**
   Engine code is MIT (or GPL-3.0 on the newer fork); individual voice
   checkpoints carry mixed licenses (CC0/CC-BY/MIT/Apache/
   non-commercial-research-only) recorded on each voice's own Hugging
   Face model card — not blocking for a personal prototype, but the
   exact license per chosen French voice (`siwis`, `upmc`, `gilles`,
   `tom`, `mls_1840`) should be pulled before assuming redistribution
   rights.

5. **Follow-on unknowns for implementation** (per the ticket's ask):
   - Piper's max input length per synthesis call and its behavior on
     very long Passages was not verified from primary sources in this
     pass — needs a quick empirical check once the prototype is wired
     up.
   - Output sample rates differ across the two viable candidates
     considered here in detail: Piper's French voices are 16–22kHz;
     Kokoro is 24kHz. If Piper is adopted, downstream audio
     concatenation/mixing code should target 22.05kHz (Piper's typical
     French voice rate) or resample consistently — confirm exact rate
     per chosen voice's model card.
   - No primary-source CPU throughput number exists for this project's
     exact CPU (Xeon E3-1245 v5); the Raspberry Pi 4/5 reference points
     used above are a reasonable proxy but not a guarantee — a short
     empirical benchmark (e.g. synthesize one chapter, measure wall
     time) is recommended before committing further implementation.

---

## Follow-up: HF CustomVoice model card deep-dive (2026-09-13)

Per the user's request, this follow-up re-verifies the Qwen3-TTS
CustomVoice claims directly against the two actual Hugging Face model
repos, rather than the GitHub README used in the first pass. Both
exact URLs given by the user resolved (no 404, no ID substitution
needed):

- [huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice)
- [huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)

### 1. Voice/speaker roster — re-verified, unchanged from prior research

Both the 0.6B and 1.7B CustomVoice model cards list the **same nine
named speakers**, with the same language tags, confirming (not
contradicting) the prior GitHub-README-based list:

| Speaker | Language |
|---|---|
| Vivian | Chinese |
| Serena | Chinese |
| Uncle_Fu | Chinese |
| Dylan | Chinese (Beijing dialect) |
| Eric | Chinese (Sichuan dialect) |
| Ryan | English |
| Aiden | English |
| Ono_Anna | Japanese |
| Sohee | Korean |

No French-tagged speaker exists in either card's roster. The model
cards do state the underlying model **supports 10 languages as text
input** — "Chinese, English, Japanese, Korean, German, French,
Russian, Portuguese, Spanish, Italian" — per the
[0.6B model card](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice)
(language list confirmed via the Hugging Face model API at
`https://huggingface.co/api/models/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice`).
This is the same distinction the prior research already drew: French
is a supported *input/output language* the 9 non-French preset voices
can presumably read aloud (with a foreign accent, unverified), but
there is still no French-*trained*, French-*named* preset voice in
either CustomVoice checkpoint. Prior research's list stands, confirmed
from the model card itself rather than assumed.

### 2. CPU inference and file sizes — new, harder findings

- **No CPU-inference path is documented on either model card.** The
  quickstart/sample code on both cards loads the model with
  `device_map="cuda:0"` and `dtype=torch.bfloat16` — GPU-only in the
  copy-pasteable example, no CPU fallback branch, no `torch_dtype`
  float32 guidance, no ONNX export or ONNX Runtime mention anywhere on
  either card.
  [0.6B card](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice),
  [1.7B card](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice).
- **`config.json` (0.6B) has no top-level `torch_dtype` field at all**
  (checked directly at
  [.../0.6B-CustomVoice/blob/main/config.json](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/blob/main/config.json));
  the only dtype-adjacent field found is a nested
  `code_predictor_config.dtype: null`. This neither confirms nor rules
  out CPU/float32 inference — it simply means the repo does not commit
  to a dtype in config, leaving it to whatever the loading code passes
  (which the sample code sets to `bfloat16` for a CUDA device).
  bfloat16 execution on CPU is possible in PyTorch but is known to be
  markedly slower than on GPU/newer-CPU hardware with native bf16
  support — this project's 2016-era Xeon E3-1245 v5 predates any
  hardware bf16 acceleration, so bf16-only weights are a mild
  additional CPU-feasibility red flag beyond the already-unverified
  general CPU path.
- **Exact file sizes**, pulled from the Hugging Face model API
  (`?blobs=true`) for both repos:
  - **0.6B-CustomVoice**: `model.safetensors` ≈ 1.81 GB +
    `speech_tokenizer/model.safetensors` ≈ 682 MB ≈ **2.49 GB total
    repo weight**.
  - **1.7B-CustomVoice**: `model.safetensors` ≈ 3.83 GB + the same
    ≈ 682 MB speech tokenizer ≈ **4.51 GB total repo weight**.
  - Source: `https://huggingface.co/api/models/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice?blobs=true`
    and the 1.7B equivalent.
  - As a proxy for RAM/CPU feasibility: ~2.5 GB and ~4.5 GB of weights
    respectively are both comfortably within an 8-core desktop Xeon's
    typical RAM budget (this is not the bottleneck); the bottleneck
    risk is compute throughput of an autoregressive/transformer TTS
    stack on CPU, which remains **unverified by any official
    source** — this follow-up did not find a CPU RTF number on either
    model card, confirming (not resolving) the original research's
    flagged unknown.

### 3. VoiceDesign / Base variants and French sample audio

- The 1.7B-CustomVoice card links sibling repos
  **Qwen3-TTS-12Hz-1.7B-VoiceDesign** (voice built from a natural-
  language description) and **Qwen3-TTS-12Hz-1.7B-Base** /
  **-0.6B-Base** (reference-audio voice cloning). Checked the
  VoiceDesign card directly
  ([huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign)):
  it restates the same 10-language list (French included as a
  supported language) but documents **no preset French voice** and
  **no French sample audio** — same GPU-only (`cuda:0`,
  `bfloat16`) quickstart, same Apache-2.0 license.
- **Neither CustomVoice card (0.6B or 1.7B) shows any sample audio
  demo specifically labeled French.** No French audio sample was found
  on either page in this pass.

### 4. License — confirmed directly on both model cards

Both cards state the license as **Apache-2.0** directly in their
Hugging Face metadata/model-card body (not just inferred from the
GitHub repo) — confirmed via both the rendered card and the
`https://huggingface.co/api/models/...` JSON for each of
0.6B-CustomVoice, 1.7B-CustomVoice, and 1.7B-VoiceDesign. This matches
what the prior GitHub-based research already stated; no discrepancy
found.

### Updated recommendation: Piper recommendation stands, unchanged

This deep-dive does not change the prior recommendation of **Piper**.
Every point the user asked to re-verify came back confirming, not
contradicting, the original GitHub-README-based research:

- The voice roster is identical (9 speakers, same language tags, zero
  French) whether read from the GitHub README or the HF model cards
  directly — there is no hidden French preset voice on either
  CustomVoice card.
- CPU inference is, if anything, a slightly *more* concerning unknown
  than before: the model cards' own sample code is GPU-only
  (`cuda:0` + `bfloat16`), with no CPU code path, no float32 fallback,
  and no ONNX export documented anywhere — and bf16 weights specifically
  raise a new (mild) doubt about throughput on this project's
  pre-bf16-era CPU that wasn't visible from the GitHub README alone.
- File sizes (2.49 GB / 4.51 GB) rule out RAM as a blocker for either
  variant but say nothing about compute-time feasibility, which
  remains unverified by any primary source.
- VoiceDesign is confirmed to exist and to support French as a
  language, but — like CustomVoice — ships no preset French voice and
  no French sample audio, so it does not change the "no built-in
  French voice" conclusion; it only remains relevant as the
  previously-flagged "generate a voice from a text description, use it
  as a fixed preset" open question for the user, unchanged from before.

**Net effect: the trade-off described in the original research is
confirmed as accurate, not superseded.** Piper remains the
recommended engine for real French preset variety on CPU; Qwen3-TTS
CustomVoice remains eliminated by the same French-preset gap, now
verified against its own Hugging Face model cards rather than assumed
from the GitHub README.
