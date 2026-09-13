"""Chunk-building: turns a Chapter's full ordered list of annotated Lines
into the ordered list of Chunks that Phase 2 actually synthesizes.

A Chunk (see CONTEXT.md's glossary, amended 2026-09-13, and ticket 06's
2026-09-13 amendment) is the actual unit sent to TTS synthesis — either a
single dialogue Line, or a run of consecutive Narrator Lines (possibly
spanning multiple Passages, and even the chapter-title/any-heading
boundary) merged into one `generate_custom_voice` call. This replaces the
old one-call-per-Line design: today, every source paragraph always produced
at least one separate synthesis call even when nothing about the speaker
changed across consecutive paragraphs, which made narration unnaturally
choppy.

`build_chunks` is a pure, deterministic function: the same ordered list of
AnnotatedLine in always produces the same list of Chunk out (same text,
same boundaries, same audio_path). That determinism is the whole
resumability mechanism for this layer — see ticket 07's 2026-09-13
amendment: a resumed run naturally reconstructs identical Chunk boundaries
for any unchanged upstream Passages, so their Chunk audio file already
exists on disk and is correctly skipped, with no separate persisted
"chunk checkpoint" manifest needed.
"""

import hashlib
import os
from dataclasses import dataclass


@dataclass
class AnnotatedLine:
    """One fully-resolved Line, ready for chunk-building.

    This is whatever main.py's Phase 1 already has per Line (`is_narrator`,
    `text`, `instruct`) plus that Line's Cast-assigned `voice`. Not
    persisted anywhere on its own — built fresh every run (in-memory only),
    either from a freshly-run Annotation Pass result or restored from a
    checkpointed Passage's cached annotation, in both cases re-resolving
    the Line's voice via Cast (deterministically — Cast's assignments are
    themselves either freshly built or restored from the same checkpoint
    snapshot ticket 07 already relies on)."""

    text: str
    is_narrator: bool
    voice: str
    instruct: str | None


@dataclass
class Chunk:
    """The actual unit sent to TTS synthesis: either a single dialogue
    Line, or a run of consecutive Narrator Lines (possibly spanning
    multiple Passages) merged into one call. See this module's docstring
    and ticket 06's 2026-09-13 amendment."""

    text: str
    is_narrator: bool
    voice: str
    instruct: str | None
    audio_path: str


def _chunk_hash(text: str, is_narrator: bool, voice: str, instruct: str | None) -> str:
    """Content hash used to derive a Chunk's audio filename.

    Deviation from the ticket's literal wording ("sha256-of-chunk-text"):
    this folds in `voice`, `instruct`, and `is_narrator` too, not just the
    raw text. Hashing text alone would let two Chunks with coincidentally
    identical text but a DIFFERENT voice or instruct (e.g. two different
    Speakers who both happen to say exactly "Oui.") collide on the same
    cache filename — the second one would then wrongly be treated as
    "already synthesized" and would play back the first Speaker's voice.
    Folding in every input that actually affects the synthesized audio
    keeps content-hash-addressing correct while still satisfying the same
    "same inputs -> same file" determinism the ticket asks for.
    """
    h = hashlib.sha256()
    h.update(text.encode("utf-8"))
    h.update(b"\x00")
    h.update(voice.encode("utf-8"))
    h.update(b"\x00")
    h.update((instruct or "").encode("utf-8"))
    h.update(b"\x00")
    h.update(b"1" if is_narrator else b"0")
    return h.hexdigest()


def chunk_audio_path(
    audio_cache_dir: str,
    chapter_number: int,
    text: str,
    is_narrator: bool,
    voice: str,
    instruct: str | None,
) -> str:
    """Content-hash-addressed path for a Chunk's audio file:
    `audio_cache/chapter_NN/chunk_<hash>.wav`. Takes the raw fields (rather
    than a built `Chunk`) so `build_chunks` can compute a Chunk's own path
    before the `Chunk` object exists yet."""
    h = _chunk_hash(text, is_narrator, voice, instruct)
    d = os.path.join(audio_cache_dir, f"chapter_{chapter_number:02d}")
    return os.path.join(d, f"chunk_{h}.wav")


def build_chunks(lines: list[AnnotatedLine], audio_cache_dir: str, chapter_number: int) -> list[Chunk]:
    """Walks a Chapter's full ordered Line list ONCE, merging consecutive
    Narrator Lines into one Chunk and breaking only where a real dialogue
    Line occurs:

    - Buffer consecutive `is_narrator=True` Lines' text, joined with a
      single space (never a raw newline — ticket 04 already fixed a real
      audible-pause bug from embedded newlines; this must not reintroduce
      anything like it).
    - The moment a non-Narrator (dialogue) Line is encountered: close the
      current buffer as one finished Chunk (if non-empty), emit that
      dialogue Line as its own separate, single-Line Chunk immediately
      after, then start a fresh empty buffer.
    - At the end of the Chapter, close any remaining open buffer as a
      final Chunk.

    All Narrator Lines share the fixed Narrator voice, so the buffered
    Chunk's `voice` is simply whatever the buffered Lines' (constant)
    voice is; a dialogue Chunk's voice/instruct are exactly its one Line's.
    """
    chunks: list[Chunk] = []
    buffer_texts: list[str] = []
    buffer_voice: str | None = None

    def flush() -> None:
        nonlocal buffer_voice
        if not buffer_texts:
            return
        text = " ".join(buffer_texts)
        chunks.append(
            Chunk(
                text=text,
                is_narrator=True,
                voice=buffer_voice,
                instruct=None,
                audio_path=chunk_audio_path(
                    audio_cache_dir, chapter_number, text, True, buffer_voice, None
                ),
            )
        )
        buffer_texts.clear()
        buffer_voice = None

    for line in lines:
        if line.is_narrator:
            buffer_texts.append(line.text)
            buffer_voice = line.voice
        else:
            flush()
            chunks.append(
                Chunk(
                    text=line.text,
                    is_narrator=False,
                    voice=line.voice,
                    instruct=line.instruct,
                    audio_path=chunk_audio_path(
                        audio_cache_dir, chapter_number, line.text, False, line.voice, line.instruct
                    ),
                )
            )
    flush()
    return chunks
