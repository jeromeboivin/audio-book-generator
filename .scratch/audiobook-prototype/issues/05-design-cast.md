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

## Amendment (2026-09-13) — pool + cycling replaced with 4 fixed, configurable role-voices

The gender-partitioned pool + cycling design above was implemented, and a
full-pipeline test run against a real multi-chapter book surfaced a
concrete problem with it: **auto-casting assigns Voices in the order
Speakers are first attributed by the Annotation Pass**, so which specific
Voice a given character lands on isn't a property of the character at
all — it's a property of assignment order. Two different male characters
in the same Chapter reliably get two DIFFERENT Voices (Ryan, then Aiden,
per the fixed earmarked order), which sounds right within one Chapter run,
but nothing about this design persists "Speaker X always gets Voice Y"
*across Chapters* of the same Book — a fresh `main.py` invocation for a
later Chapter starts auto-casting from scratch, so the same character
could land on a different Voice than in an earlier Chapter's run purely
because of a different attribution order that time. (CONTEXT.md's Cast
glossary entry had actually been asserting this cross-Chapter consistency
all along — "kept consistent across every Chapter" — which was aspirational,
not actually true of the implemented pool/cycling design; corrected as
part of this same amendment.)

**Decision: replace the whole pool/cycling/auto-casting model with exactly
4 fixed, configurable role-voices, uniformly applied — no more per-character
assignment at all.** A Line's Voice is now a pure function of its **role**:

1. **Narrator** → **Ryan** (was `Uncle_Fu` — changed as part of this same
   redesign, since the Narrator's Voice is now just one of the 4
   configurable roles rather than a separate hardcoded constant).
2. **Adult male characters** (any non-Narrator Speaker with
   `speaker_gender="male"`, `speaker_is_child=false`) → **also Ryan** —
   intentional, not a bug: every adult male character in the Book, and the
   Narrator, share one Voice under the defaults.
3. **Adult female characters** (`speaker_gender="female"`,
   `speaker_is_child=false`) → **Serena**.
4. **Child characters** (`speaker_is_child=true`, either stated gender —
   the existing radio-drama convention from this ticket's original
   answer, that child voices don't follow the character's own gender, is
   kept) → **Vivian**.

All 9 Qwen3-TTS presets remain available (female: Vivian, Serena,
Ono_Anna, Sohee; male: Uncle_Fu, Dylan, Eric, Ryan, Aiden) — only 3 of them
(Ryan, Serena, Vivian) are used by the new defaults, the rest stay
reachable via `cast.json`'s per-character override (unchanged) or by
editing `voices.json`.

**Configurability — new `voices.json` file**, parallel to the existing
`cast.json`, at the project root:

```json
{"narrator": "Ryan", "adult_male": "Ryan", "adult_female": "Serena", "child": "Vivian"}
```

Missing file → all 4 defaults apply. Present but partial (e.g. only
`adult_female` overridden) → the other 3 keys fall back to their own
defaults individually — not an all-or-nothing replacement.

**`cast.json`'s per-character override is completely unchanged in format
and behavior** — still `{"Speaker Name": "Voice"}`, still checked before
the role-based default, still a full escape hatch (including, if someone
really wants it, overriding "Narrator" itself — no special-casing needed
to allow that).

**Cast becomes stateless — this is the core of the redesign, not a side
effect of it**: `Cast.assignments`, the per-sub-pool cycling counters, and
`Cast.to_snapshot()`/`from_snapshot()` are all removed outright. A Voice
lookup (`Cast.voice_for(speaker, gender, is_child, is_narrator)`) is now a
pure function of its inputs and the current `voice_config`/`overrides` —
no per-run memory of "what has this Speaker already been assigned" is kept
or needed, because the answer is always the same for the same role. One
`Cast` instance is now constructed once per `main.py` run and reused
throughout, rather than being reconstructed/restored per Passage.

**This incidentally resolves the cross-chapter consistency gap this
amendment opened with — as a side effect of the redesign, not a
separately-built feature.** Since a Voice is now purely `f(role, config)`
with no order-dependence at all, every adult male character in every
Chapter of every Book resolves to the same configured Voice (Ryan by
default) with zero persisted state needed to make that true — there is no
"memory" to lose or fail to carry across a fresh `main.py` invocation for
a later Chapter, because there was never anything to remember in the
first place.

**Regeneration semantics**: changing a role-voice in `voices.json` between
runs does not, by itself, force regeneration of already-synthesized Chunk
audio — see ticket 07's matching amendment for why, and for the Chunk
filename convention (`chunk_{role}_{hash}.wav`) this depends on. Verified
for real, not just reasoned about — see ticket 07's amendment.

Status: resolved
