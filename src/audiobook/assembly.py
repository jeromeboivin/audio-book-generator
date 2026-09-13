import os
import re
import unicodedata

import numpy as np
import soundfile as sf

from .tts import SAMPLE_RATE

LINE_GAP_S = 0.35
PASSAGE_GAP_S = 0.7


def slugify(title: str) -> str:
    s = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return s


def chapter_filename(chapter_number: int, title: str) -> str:
    return f"chapitre_{chapter_number:02d}_{slugify(title)}.wav"


def _silence(seconds: float, sample_rate: int) -> np.ndarray:
    return np.zeros(int(seconds * sample_rate), dtype=np.float32)


def assemble_chapter(
    passages_line_audio_paths: list[list[str]],
    chapter_number: int,
    title: str,
    output_dir: str,
    sample_rate: int = SAMPLE_RATE,
) -> str:
    chunks = []
    for p_idx, line_paths in enumerate(passages_line_audio_paths):
        if p_idx > 0:
            chunks.append(_silence(PASSAGE_GAP_S, sample_rate))
        for l_idx, path in enumerate(line_paths):
            if l_idx > 0:
                chunks.append(_silence(LINE_GAP_S, sample_rate))
            wav, _sr = sf.read(path, dtype="float32")
            chunks.append(wav)

    audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, chapter_filename(chapter_number, title))
    sf.write(out_path, audio, sample_rate)
    return out_path
