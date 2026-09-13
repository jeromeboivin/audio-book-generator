import os
import re
import unicodedata

import numpy as np
import soundfile as sf

from .tts import SAMPLE_RATE

# Single inter-Chunk silence rule (replaces the old two-tier ~300-400ms
# between Lines / ~600-800ms between Passages rule — see ticket 06's
# 2026-09-13 amendment). A Chunk boundary is now the only kind of boundary
# that exists between separately-synthesized audio (Line/Passage boundaries
# no longer align with synthesis-call boundaries at all, since consecutive
# Narrator Lines — even across Passages — are merged into one Chunk). No
# silence is inserted WITHIN a Chunk; it's one continuous TTS call's output.
CHUNK_GAP_S = 0.7


def slugify(title: str) -> str:
    s = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return s


def chapter_filename(chapter_number: int, title: str) -> str:
    return f"chapitre_{chapter_number:02d}_{slugify(title)}.wav"


def _silence(seconds: float, sample_rate: int) -> np.ndarray:
    return np.zeros(int(seconds * sample_rate), dtype=np.float32)


def assemble_chapter(
    chunk_audio_paths: list[str],
    chapter_number: int,
    title: str,
    output_dir: str,
    sample_rate: int = SAMPLE_RATE,
) -> str:
    """Concatenates a Chapter's already-synthesized Chunk audio files, in
    order, inserting `CHUNK_GAP_S` of silence between every consecutive
    pair (and nowhere else), then writes the result as one WAV file."""
    pieces = []
    for idx, path in enumerate(chunk_audio_paths):
        if idx > 0:
            pieces.append(_silence(CHUNK_GAP_S, sample_rate))
        wav, _sr = sf.read(path, dtype="float32")
        pieces.append(wav)

    audio = np.concatenate(pieces) if pieces else np.zeros(0, dtype=np.float32)

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, chapter_filename(chapter_number, title))
    sf.write(out_path, audio, sample_rate)
    return out_path
