"""Parallel TTS synthesis scheduling.

Phase 1 (in main.py, sequential) does annotation + Voice assignment for
every Passage and accumulates the Chapter's full ordered Line list.
Chunk-building (`chunking.build_chunks`) then turns that Line list into an
ordered list of Chunks. Phase 2 (also in main.py) builds one SynthesisJob
per Chunk that doesn't already have cached audio, and submits those jobs to
a ProcessPoolExecutor whose workers use this module's `init_worker`/
`run_job` as the executor initializer/callable.

Worker processes only ever synthesize audio and write WAV files: they never
read or write the Checkpoint JSON, and (since 2026-09-13's Chunk-layer
amendment) there is no chunk-level checkpoint to write anyway — a Chunk's
audio_path is content-hash-addressed, so "already done" is just
`os.path.exists(audio_path)`, checked by main.py before a job is even
created.

Model routing: Narrator-model jobs (a Chunk of merged consecutive Narrator
Lines, `is_narrator=true`) always use `tts.NARRATOR_MODEL_ID` (0.6B, no
instruct); every other job (a dialogue Chunk, always exactly one Line) uses
`tts.DIALOGUE_MODEL_ID` (1.7B, with that Line's instruct string). Each
worker process lazily loads at most one copy of each model, the first time
it actually receives a job of that kind — never eagerly, and never reloaded
within the same worker's lifetime. A worker that only ever receives
narrator jobs never loads the 1.7B model at all, and vice versa.
"""

import os
from dataclasses import dataclass

import soundfile as sf

from . import tts

# Per-process cache, populated lazily by run_job() in each worker — at most
# one entry per model id, loaded the first time a job needing it arrives.
_worker_models: dict[str, object] = {}


def init_worker(threads_per_worker: int) -> None:
    """Executor initializer: runs once per worker process.

    Only sets this process's torch thread cap (so `workers *
    threads_per_worker` stays around the machine's core count) — model
    loading is intentionally NOT done here anymore. Each model (narrator
    0.6B / dialogue 1.7B) is loaded lazily by `run_job`, on the first job of
    that kind this worker actually receives, and cached in `_worker_models`
    for the rest of this process's lifetime.
    """
    import os

    import torch

    torch.set_num_threads(max(1, threads_per_worker))
    print(
        f"[worker pid={os.getpid()}] ready ({threads_per_worker} torch thread(s)); "
        f"models load lazily on first matching job.",
        flush=True,
    )


def _get_model(model_id: str):
    import os

    model = _worker_models.get(model_id)
    if model is None:
        print(f"[worker pid={os.getpid()}] loading TTS model {model_id} (first job needing it) ...", flush=True)
        model = tts.load_model(model_id)
        _worker_models[model_id] = model
        print(f"[worker pid={os.getpid()}] model {model_id} loaded.", flush=True)
    return model


@dataclass
class SynthesisJob:
    """One Chunk's worth of synthesis work (see `chunking.Chunk`) —
    `chunk_index` is this Chunk's position in the Chapter's ordered Chunk
    list, kept only for progress logging (it has no bearing on the
    audio_path, which is content-hash-addressed and computed by
    `chunking.build_chunks` before any SynthesisJob exists)."""

    chapter_number: int
    chunk_index: int
    text: str
    voice: str
    instruct: str | None
    audio_path: str
    is_narrator: bool

    @property
    def model_id(self) -> str:
        return tts.NARRATOR_MODEL_ID if self.is_narrator else tts.DIALOGUE_MODEL_ID


def run_job(job: SynthesisJob) -> tuple[int, str]:
    """Runs in a worker process. Synthesizes one Chunk and writes its WAV.

    Loads (or reuses, if already cached in this worker) the model that
    `job.is_narrator` routes to, then synthesizes. Returns (chunk_index,
    audio_path) so the coordinator can log progress. Raises on failure —
    the coordinator lets that propagate to abort the run (no silent
    fallback, per project philosophy: resumability makes it safe to just
    rerun — a content-hash-addressed Chunk audio file that never got
    written simply doesn't exist yet, so a rerun retries exactly it).
    """
    model = _get_model(job.model_id)
    wav, sr = tts.synthesize_line(model, job.text, job.voice, job.instruct)
    os.makedirs(os.path.dirname(job.audio_path), exist_ok=True)
    # Write to a temp file and rename into place atomically — a worker
    # killed mid-write (OOM, power loss, SIGKILL) must never leave a
    # truncated file sitting at the final audio_path, since a later run's
    # resumability check is just `os.path.exists(audio_path)`: a partial
    # file there would be wrongly treated as already-done and never
    # retried, and would corrupt assembly's read of it.
    tmp_path = f"{job.audio_path}.{os.getpid()}.tmp"
    sf.write(tmp_path, wav, sr, format="WAV")
    os.replace(tmp_path, job.audio_path)
    return job.chunk_index, job.audio_path


def default_threads_per_worker(workers: int) -> int:
    import os

    return max(1, (os.cpu_count() or 1) // max(1, workers))
