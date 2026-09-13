# Design the Cast

Type: grilling
Status: resolved
Blocked by: 01

## Question

Design how the Cast (the persistent Speaker → Voice mapping for a Book) is
built, given whatever Preset Voices the selected TTS engine (see the TTS
engine selection ticket) actually ships. Needs to settle:

- **Voice pool**: which of the engine's Preset Voices become the narrator
  Voice and the 4-8-voice character pool; how they're picked if the engine
  offers more than needed, or a fallback if it offers fewer than needed.
- **Auto-casting**: how a new Speaker (first time attributed by the
  Annotation Pass) gets assigned the next free Voice from the pool, and what
  happens once the pool is exhausted (reuse from the pool vs some other
  rule).
- **Manual override**: the file format for a casting override (map a
  specific Speaker name to a specific Voice by hand) and how it's merged
  with the auto-casting.

## Answer

**Pool size**: a fixed pool of **4 Voices** (Narrator + 3 reserved for
characters), even though Chapter 1 ("Monsieur Myriel") only actually
surfaces 3 Speakers total (Narrator, M. Myriel, and an unnamed "Sire" —
implied Napoleon — in one brief exchange). Reserving headroom beyond what
this one chapter needs keeps the Cast design valid if later chapters (out
of this POC's scope, but plausible future work) introduce more characters,
without redesigning the pool.

**Amendment — gender-matched voices**: a constraint surfaced after the
initial resolution — male characters must get a male Voice, female
characters a female Voice. The character pool is **gender-partitioned**,
not one flat list (from the 9 Qwen3-TTS CustomVoice presets — see
[Select the TTS engine](01-select-tts-engine.md), which splits as
female = Vivian, Serena, Ono_Anna, Sohee; male = Uncle_Fu, Dylan, Eric,
Ryan, Aiden):
- **Male character sub-pool**: `Ryan`, `Aiden`.
- **Female character sub-pool**: `Serena`, `Vivian`.
- **Narrator**: `Uncle_Fu` — fixed, not cast from either sub-pool, so its
  gender doesn't need to match anything (the Narrator is a Speaker with a
  pre-assigned Voice, per CONTEXT.md).

For Chapter 1 specifically, both speaking characters are male, so the
concrete assignment is: **M. Myriel** (elderly bishop) → `Ryan`
("dynamic male voice, strong rhythmic drive"); **Sire/Napoleon** → `Aiden`
("sunny American male voice, clear midrange"). The female sub-pool
(`Serena`, `Vivian`) is reserved, unused by this specific chapter but
available the moment a female Speaker is introduced. This depends on the
Annotation Pass reporting each Speaker's gender — see the corresponding
amendment to [Design the OpenAI annotation contract](03-annotation-contract.md)
(`speaker_gender` field added to its schema).

These are a starting assignment, not precision-tuned by ear (none of the
sub-pool presets are natively French, per ticket 01's known gap) — easy to
swap in the Cast config once the actual synthesized samples are heard.

**Auto-casting**: when the Annotation Pass introduces a Speaker not yet in
the Cast, determine its target sub-pool from **both** `speaker_gender` and
`speaker_is_child` (ticket 03's schema): a child Speaker — regardless of
stated gender — is cast from the **female** sub-pool (the standard
radio-drama/animation convention: child voices, including boys, are
conventionally played by adult women, since pitch/register matters more
than the character's actual gender). A non-child Speaker uses the
gender-matched sub-pool as before. Within whichever sub-pool is selected,
assign the next unused Voice in the fixed earmarked order above. If a
sub-pool is exhausted (more than 2 distinct Speakers routed to the same
sub-pool in a Chapter), cycle back to reusing that sub-pool's Voices
starting from the least-recently-assigned one — accepted as an imperfect
fallback for a POC rather than growing the pool dynamically.

**Manual override**: a hand-editable `cast.json` file,
`{"Speaker Name": "Voice"}`, loaded before auto-casting runs each session.
Auto-casting only assigns Voices to Speakers not already present in this
file — a manual entry always wins and is never reassigned.

Status: resolved
