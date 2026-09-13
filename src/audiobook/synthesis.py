"""Parallel TTS synthesis scheduling.

Phase 1 (in main.py, sequential) does annotation + Voice assignment and
produces a list of SynthesisJob instances. Phase 2 (also in main.py) submits
those jobs to a ProcessPoolExecutor whose workers use this module's
`init_worker`/`run_job` as the executor initializer/callable.

Worker processes only ever synthesize audio and write WAV files: they never
read or write the Checkpoint JSON. Only the main process touches Checkpoint.

Model routing: Narrator-model jobs (title Lines and any other
`is_narrator=true` Line) always use `tts.NARRATOR_MODEL_ID` (0.6B, no
instruct); every other job (dialogue, any non-Narrator Speaker) always uses
`tts.DIALOGUE_MODEL_ID` (1.7B, with an instruct string). Each worker process
lazily loads at most one copy of each model, the first time it actually
receives a job of that kind — never eagerly, and never reloaded within the
same worker's lifetime. A worker that only ever receives narrator jobs never
loads the 1.7B model at all, and vice versa.
"""

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
    chapter_number: int
    passage_index: int
    line_index: int
    text: str
    voice: str
    instruct: str | None
    audio_path: str
    is_narrator: bool

    @property
    def model_id(self) -> str:
        return tts.NARRATOR_MODEL_ID if self.is_narrator else tts.DIALOGUE_MODEL_ID


def run_job(job: SynthesisJob) -> tuple[int, int, str]:
    """Runs in a worker process. Synthesizes one Line and writes its WAV.

    Loads (or reuses, if already cached in this worker) the model that
    `job.is_narrator` routes to, then synthesizes. Returns (passage_index,
    line_index, audio_path) so the coordinator can track per-passage
    completion. Raises on failure — the coordinator lets that propagate to
    abort the run (no silent fallback, per project philosophy: resumability
    makes it safe to just rerun).
    """
    model = _get_model(job.model_id)
    wav, sr = tts.synthesize_line(model, job.text, job.voice, job.instruct)
    sf.write(job.audio_path, wav, sr)
    return job.passage_index, job.line_index, job.audio_path


def default_threads_per_worker(workers: int) -> int:
    import os

    return max(1, (os.cpu_count() or 1) // max(1, workers))
