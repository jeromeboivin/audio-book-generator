# Design chunking and audio assembly

Type: grilling
Status: resolved
Blocked by: 01

## Question

Design how annotated Lines within a Chapter become one output audio file,
given the selected TTS engine's (see the TTS engine selection ticket) input
constraints. Needs to settle:

- **Synthesis batching**: how Lines are grouped into individual TTS synth
  calls given the engine's max input length per call (a Line may need
  splitting, or several short Lines from the same Speaker may be batched
  together).
- **Concatenation**: the order and method for joining synthesized Line audio
  into one Chapter file, including any inter-Line pause/silence handling
  (e.g. a beat between dialogue and the next narration).
- **Output file spec**: exact format (MP3 vs WAV — already narrowed to
  "one file per Chapter", pick the concrete format), sample rate/bitrate,
  and the file naming/directory convention for a Book's Chapter files.

Note: this ticket's synthesis batching must produce checkpointable units —
see [Design resumability / checkpointing](07-resumability.md), surfaced
while resolving the annotation contract ticket. Coordinate with that
ticket's checkpoint-store design rather than inventing a separate one.

## Answer

**Synthesis batching**: one `generate_custom_voice` call per Line — no
batching of consecutive same-Speaker Lines. Simplest mapping, and each
call is naturally one checkpointable unit for the resumability ticket.
Empirically tested against Chapter 1's actual longest paragraph (332
words / 2045 chars, well above typical Line length since most Lines are
sub-paragraph): synthesized in one call with no truncation or error,
producing correctly-timed audio (161.8s for 332 words ≈ 123 wpm, a
plausible full read, not cut short) — confirms no chunking/splitting logic
is needed for Lines at this book's actual paragraph lengths. No documented
max-input-length was found for Qwen3-TTS, and none was hit in practice.

**Concatenation**: raw synthesized audio arrays (numpy) for a Chapter's
Lines, in order, joined with inserted silence — via `np.zeros` (no new
audio-library dependency; numpy/soundfile already in use) — of ~300-400ms
between consecutive Lines, ~600-800ms between Passages, before writing the
final concatenated array to one WAV file per Chapter with `soundfile`.

**Output file spec**: **WAV**, at Qwen3-TTS's native output sample rate —
empirically confirmed **24000 Hz** (measured directly from
`generate_custom_voice`'s returned `sr`) — no resampling needed since only
one engine/sample-rate is in play. Chapter files named by chapter number
and slugified title, e.g. `chapitre_01_monsieur_myriel.wav`. MP3 is a
possible later nice-to-have via a quick ffmpeg pass, not required for this
POC's "done" bar.

Status: resolved
