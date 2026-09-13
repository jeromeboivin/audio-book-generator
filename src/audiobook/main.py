import argparse
import glob
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audiobook import annotation, assembly, synthesis
from audiobook.cast import Cast
from audiobook.checkpoint import Checkpoint, hash_passage
from audiobook.parsing import Passage, extract_chapter
from audiobook.synthesis import SynthesisJob

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_BOOK = os.path.join(PROJECT_ROOT, "samples", "Les misérables Tome I Fantine.epub")
CAST_JSON_PATH = os.path.join(PROJECT_ROOT, "cast.json")
CHECKPOINT_DIR = os.path.join(PROJECT_ROOT, "checkpoints")
AUDIO_CACHE_DIR = os.path.join(PROJECT_ROOT, "audio_cache")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
BOOK_SLUG = "fantine_tome1"

DEFAULT_WORKERS = 2


def line_audio_path(chapter_number: int, passage_index: int, line_index: int) -> str:
    d = os.path.join(AUDIO_CACHE_DIR, f"chapter_{chapter_number:02d}")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"passage_{passage_index:03d}_line_{line_index:02d}.wav")


def _clear_stale_audio(chapter_number: int, from_passage_index: int) -> None:
    d = os.path.join(AUDIO_CACHE_DIR, f"chapter_{chapter_number:02d}")
    for path in glob.glob(os.path.join(d, "passage_*_line_*.wav")):
        base = os.path.basename(path)
        idx = int(base.split("_")[1])
        if idx >= from_passage_index:
            os.remove(path)


def _build_narration_passages(chapter) -> list[Passage]:
    """The full list of things to narrate for a Chapter: the chapter's own
    title first (passage index 0), followed by its body Passages (index
    1..N — shifted by one from parsing.extract_chapter's own indexing).

    The title Passage's `has_dialogue` is hard-set False, not computed —
    a title is never dialogue and must always short-circuit straight to a
    Narrator Line via `annotation.short_circuit_narrator`, never sent to
    OpenAI and never subject to the has_dialogue/em-dash check at all."""
    title_passage = Passage(text=chapter.title, has_dialogue=False)
    return [title_passage] + chapter.passages


def _reconstruct_state(checkpoint, chapter_number, n_passages, first_pending, overrides):
    if first_pending is None:
        idx_to_check = n_passages - 1
    else:
        idx_to_check = first_pending - 1
    if idx_to_check < 0:
        return [], Cast(overrides=overrides)
    entry = checkpoint.get_entry(chapter_number, idx_to_check)
    if entry is None:
        return [], Cast(overrides=overrides)
    roster = list(entry.get("roster", []))
    cast = Cast.from_snapshot(entry.get("cast", {}), overrides)
    return roster, cast


@dataclass
class _PendingPassage:
    """A passage that has been annotated (Phase 1) but whose Lines' audio
    hasn't all been synthesized yet (Phase 2). Everything needed to write
    this passage's checkpoint entry is captured here up front; the entry
    itself is only written once `remaining` drops to zero."""

    text_hash: str
    annotation: dict
    roster_snapshot: list
    cast_snapshot: dict
    total_lines: int
    remaining: int = 0


def _phase1_annotate_and_assign_voices(
    passages,
    chapter_number,
    n_passages,
    checkpoint,
    roster,
    cast,
    overrides,
    first_pending,
    skip_tts,
):
    """Sequential pass: skip already-done passages (restoring roster/cast),
    otherwise annotate + assign Voices exactly as before. Does NOT
    synthesize audio. Returns (pending_passages, jobs) where pending_passages
    maps passage_index -> _PendingPassage for passages awaiting synthesis,
    and jobs is the flat list of SynthesisJob to run in Phase 2. In
    --skip-tts mode, jobs is always [] and passages are checkpointed
    immediately (no audio to wait for), matching prior behavior.

    `passages` is the full narration list (title at index 0, body Passages
    after — see `_build_narration_passages`); each is a `parsing.Passage`
    carrying its own `has_dialogue` flag, which is what decides whether this
    Passage gets an Annotation Pass call or short-circuits to a Narrator
    Line — not any re-check of the (already whitespace-collapsed) text.
    """
    client = None
    pending_passages: dict[int, _PendingPassage] = {}
    jobs: list[SynthesisJob] = []

    for idx, passage in enumerate(passages):
        passage_text = passage.text
        h = hash_passage(passage_text)
        if checkpoint.is_passage_done(chapter_number, idx, h):
            print(f"Passage {idx + 1}/{n_passages}: already done, skipping")
            entry = checkpoint.get_entry(chapter_number, idx)
            roster = list(entry.get("roster", roster))
            cast = Cast.from_snapshot(entry.get("cast", {}), overrides)
            continue

        if passage.has_dialogue:
            if client is None:
                client = annotation.make_client()
            print(f"Passage {idx + 1}/{n_passages}: annotating via OpenAI ({annotation.MODEL}) ...")
            result = annotation.annotate_passage(client, passage_text, roster)
        else:
            result = annotation.short_circuit_narrator(passage_text)

        annotation.update_roster(roster, result["lines"])

        passage_jobs: list[SynthesisJob] = []
        for l_idx, line in enumerate(result["lines"]):
            audio_path = line_audio_path(chapter_number, idx, l_idx)
            line["audio_path"] = audio_path
            if skip_tts or os.path.exists(audio_path):
                continue
            if line["is_narrator"]:
                voice = "Uncle_Fu"
                instruct = None
            else:
                voice = cast.voice_for(line["speaker"], line["speaker_gender"], line["speaker_is_child"])
                instruct = line.get("instruct")
            passage_jobs.append(
                SynthesisJob(
                    chapter_number=chapter_number,
                    passage_index=idx,
                    line_index=l_idx,
                    text=line["text"],
                    voice=voice,
                    instruct=instruct,
                    audio_path=audio_path,
                    is_narrator=line["is_narrator"],
                )
            )

        if skip_tts:
            # No synthesis will ever happen this run; checkpoint immediately,
            # same as before the parallel-synthesis refactor.
            checkpoint.set_entry(chapter_number, idx, h, result, list(roster), cast.to_snapshot())
            print(f"Passage {idx + 1}/{n_passages} done ({len(result['lines'])} lines)")
        else:
            pending_passages[idx] = _PendingPassage(
                text_hash=h,
                annotation=result,
                roster_snapshot=list(roster),
                cast_snapshot=cast.to_snapshot(),
                total_lines=len(result["lines"]),
                remaining=len(passage_jobs),
            )
            jobs.extend(passage_jobs)
            print(
                f"Passage {idx + 1}/{n_passages}: annotated, "
                f"{len(passage_jobs)}/{len(result['lines'])} lines queued for synthesis"
            )

    return pending_passages, jobs


def _phase2_synthesize_parallel(chapter_number, n_passages, checkpoint, pending_passages, jobs, workers):
    """Parallel pass: synthesize every queued Line's audio across worker
    processes, and checkpoint each passage the moment ALL of its Lines are
    done (which may happen in any passage order). Only this (main) process
    ever touches the Checkpoint/JSON file."""

    # Passages that already had every Line's audio on disk need no worker at
    # all — checkpoint them immediately.
    for idx in list(pending_passages.keys()):
        pp = pending_passages[idx]
        if pp.remaining == 0:
            checkpoint.set_entry(chapter_number, idx, pp.text_hash, pp.annotation, pp.roster_snapshot, pp.cast_snapshot)
            print(f"Passage {idx + 1}/{n_passages} done ({pp.total_lines} lines, already cached)")
            del pending_passages[idx]

    if not jobs:
        print("No audio synthesis needed (all pending passages already had cached audio).")
        return

    total_jobs = len(jobs)
    total_pending_passages = len(pending_passages)
    threads_per_worker = synthesis.default_threads_per_worker(workers)
    print(
        f"Starting {workers} worker process(es) (each loading its own Qwen3-TTS model copy, "
        f"{threads_per_worker} torch thread(s) each) for {total_jobs} synthesis job(s) "
        f"across {total_pending_passages} passage(s) ..."
    )

    completed_jobs = 0
    completed_passages = 0
    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=synthesis.init_worker,
        initargs=(threads_per_worker,),
    ) as executor:
        futures = {executor.submit(synthesis.run_job, job): job for job in jobs}
        try:
            for future in as_completed(futures):
                job = futures[future]
                try:
                    future.result()
                except Exception as e:
                    raise RuntimeError(
                        f"Synthesis failed for chapter {job.chapter_number} passage "
                        f"{job.passage_index} line {job.line_index} (aborting run; "
                        f"already-checkpointed passages remain valid, rerun to resume): {e}"
                    ) from e

                completed_jobs += 1
                pp = pending_passages[job.passage_index]
                pp.remaining -= 1
                if pp.remaining == 0:
                    checkpoint.set_entry(
                        chapter_number,
                        job.passage_index,
                        pp.text_hash,
                        pp.annotation,
                        pp.roster_snapshot,
                        pp.cast_snapshot,
                    )
                    completed_passages += 1
                    print(
                        f"Passage {job.passage_index + 1}/{n_passages} done ({pp.total_lines} lines) "
                        f"— {completed_passages}/{total_pending_passages} passages complete, "
                        f"{completed_jobs}/{total_jobs} lines synthesized"
                    )
        except Exception:
            # Let already-running jobs finish (can't preempt a running
            # process), but don't start any more that were merely queued.
            executor.shutdown(wait=True, cancel_futures=True)
            raise


def run(book_path: str, chapter_number: int, skip_tts: bool = False, workers: int = DEFAULT_WORKERS):
    overrides = Cast.load_overrides(CAST_JSON_PATH)

    os.makedirs(CHECKPOINT_DIR, exist_ok=True)
    checkpoint = Checkpoint(os.path.join(CHECKPOINT_DIR, f"{BOOK_SLUG}.checkpoint.json"))

    print(f"Parsing {book_path} ...")
    chapter = extract_chapter(book_path, chapter_number)
    # Passage 0 is always the chapter's own title, narrated first (Narrator
    # voice, no Annotation Pass call); passages 1..N are the chapter's body
    # Passages, shifted by one from parsing.extract_chapter's own indexing.
    passages = _build_narration_passages(chapter)
    n_passages = len(passages)
    print(f"Chapter {chapter_number}: '{chapter.title}', {n_passages} passages (incl. title)")

    first_pending = None
    for idx, passage in enumerate(passages):
        h = hash_passage(passage.text)
        if not checkpoint.is_passage_done(chapter_number, idx, h):
            first_pending = idx
            break

    if first_pending is not None:
        # A stale/invalidated passage invalidates every checkpoint entry after it too:
        # the roster/cast snapshots from here on were built on top of it, so they can't
        # be trusted (ticket 07's sequential-roster requirement). Runs once here, before
        # Phase 1 begins — not per-worker, and unaffected by parallel synthesis below.
        checkpoint.invalidate_from(chapter_number, first_pending)
        _clear_stale_audio(chapter_number, first_pending)

    roster, cast = _reconstruct_state(checkpoint, chapter_number, n_passages, first_pending, overrides)
    if first_pending is None:
        print("All passages already checkpointed — nothing to annotate or synthesize.")
    elif first_pending == 0:
        print("Starting fresh (no prior checkpoint progress).")
    else:
        print(f"Resuming from passage {first_pending + 1}/{n_passages} (roster so far: {roster})")

    # Phase 1 (sequential): annotate + assign Voices for every pending passage.
    pending_passages, jobs = _phase1_annotate_and_assign_voices(
        passages, chapter_number, n_passages, checkpoint, roster, cast, overrides, first_pending, skip_tts
    )

    if skip_tts:
        print("skip_tts=True: not assembling final chapter WAV (no audio synthesized).")
        return None

    # Phase 2 (parallel): synthesize every queued Line's audio across worker
    # processes; checkpoint each passage as soon as all its Lines are done.
    _phase2_synthesize_parallel(chapter_number, n_passages, checkpoint, pending_passages, jobs, workers)

    print("Assembling chapter WAV from cached line audio ...")
    passages_line_paths = []
    for idx in range(n_passages):
        entry = checkpoint.get_entry(chapter_number, idx)
        lines = entry["annotation"]["lines"] if entry else []
        passages_line_paths.append([l["audio_path"] for l in lines])

    out_path = assembly.assemble_chapter(passages_line_paths, chapter_number, chapter.title, OUTPUT_DIR)
    print(f"Wrote {out_path}")
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--book", default=DEFAULT_BOOK)
    parser.add_argument("--chapter", type=int, default=1)
    parser.add_argument("--skip-tts", action="store_true", help="parse+annotate only, no synthesis")
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"number of parallel TTS worker processes (default {DEFAULT_WORKERS})",
    )
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be >= 1")
    run(args.book, args.chapter, skip_tts=args.skip_tts, workers=args.workers)


if __name__ == "__main__":
    main()
