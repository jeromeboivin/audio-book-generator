import argparse
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audiobook import annotation, assembly, chunking, synthesis
from audiobook.cast import Cast, load_voice_config
from audiobook.checkpoint import Checkpoint, hash_passage
from audiobook.chunking import AnnotatedLine
from audiobook.parsing import Passage, extract_chapter
from audiobook.synthesis import SynthesisJob

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_BOOK = os.path.join(PROJECT_ROOT, "samples", "Les misérables Tome I Fantine.epub")
CAST_JSON_PATH = os.path.join(PROJECT_ROOT, "cast.json")
VOICES_JSON_PATH = os.path.join(PROJECT_ROOT, "voices.json")
CHECKPOINT_DIR = os.path.join(PROJECT_ROOT, "checkpoints")
AUDIO_CACHE_DIR = os.path.join(PROJECT_ROOT, "audio_cache")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")

DEFAULT_WORKERS = 2


def _book_slug(book_path: str) -> str:
    """Derives a per-Book identifier from its file path, so the checkpoint
    manifest and chunk-audio cache are genuinely scoped per Book (ticket 07:
    "a single JSON manifest file per Book") rather than always writing to a
    single hardcoded slug regardless of --book — found as a real bug during
    the first-ever full end-to-end run, against a book other than the
    original Fantine test file."""
    stem = os.path.splitext(os.path.basename(book_path))[0]
    slug = re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_")
    return slug or "book"


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


def _reconstruct_state(checkpoint, chapter_number, n_passages, first_pending):
    """Only the running Speaker roster needs restoring on resume — Cast is
    stateless now (see ticket 05's 2026-09-13 amendment), so there is no
    Cast snapshot to reconstruct here anymore; the single `Cast` instance
    built once at the top of `run()` is reused as-is."""
    if first_pending is None:
        idx_to_check = n_passages - 1
    else:
        idx_to_check = first_pending - 1
    if idx_to_check < 0:
        return []
    entry = checkpoint.get_entry(chapter_number, idx_to_check)
    if entry is None:
        return []
    return list(entry.get("roster", []))


def _resolve_line(line: dict, cast: Cast) -> AnnotatedLine:
    """Turns one raw annotation Line dict (as returned by an Annotation
    Pass call, a Narrator short-circuit, or restored verbatim from a
    checkpointed Passage) into an AnnotatedLine ready for chunk-building —
    i.e. resolves its Cast-assigned Voice and role. `cast.voice_for`/
    `cast.role_for` are pure, stateless lookups (see ticket 05's
    2026-09-13 amendment) applied uniformly to both Narrator and dialogue
    Lines, so calling this on a restored (already-checkpointed) Passage's
    lines against the same single `Cast` instance used for the whole run
    is always correct and deterministic."""
    voice = cast.voice_for(line["speaker"], line["speaker_gender"], line["speaker_is_child"], is_narrator=line["is_narrator"])
    role = cast.role_for(line["speaker_gender"], line["speaker_is_child"], is_narrator=line["is_narrator"])
    return AnnotatedLine(
        text=line["text"],
        is_narrator=line["is_narrator"],
        voice=voice,
        instruct=None if line["is_narrator"] else line.get("instruct"),
        role=role,
    )


def _phase1_annotate_and_assign_voices(passages, chapter_number, n_passages, checkpoint, roster, cast):
    """Sequential pass, unchanged in spirit from before the Chunk-layer
    refactor: skip already-annotated passages (restoring the roster; Cast
    needs no restoring at all anymore — see ticket 05's 2026-09-13
    amendment, it's the single stateless instance passed in), otherwise
    annotate-or-short-circuit + assign each Line's Voice via Cast, exactly
    as before. Checkpoints each Passage's annotation
    immediately once it's done — no longer waits on audio synthesis, since
    audio caching moved one layer up to Chunks (see ticket 07's
    2026-09-13 amendment) and is no longer a Passage-level concern at all.

    Returns the Chapter's full ordered list of AnnotatedLine (whether
    restored from checkpoint or freshly annotated this run) — this is what
    `chunking.build_chunks` consumes to produce Chunks.

    `passages` is the full narration list (title at index 0, body Passages
    after — see `_build_narration_passages`); each is a `parsing.Passage`
    carrying its own `has_dialogue` flag, which is what decides whether this
    Passage gets an Annotation Pass call or short-circuits to a Narrator
    Line — not any re-check of the (already whitespace-collapsed) text.
    """
    client = None
    all_lines: list[AnnotatedLine] = []
    # The immediately preceding *Line's* text (whoever spoke it — Narrator
    # or a character), not the whole previous Passage: if speaker B speaks
    # right after speaker A, rendering B's Line correctly needs what A just
    # said, not the whole cumulative chapter-so-far (too much) and not
    # necessarily the whole previous Passage either, if that Passage itself
    # had several Lines (its own narration-then-dialogue mix, say) — only
    # its LAST Line is what's actually adjacent to whatever comes next.
    # Tracked across both branches below (skip-and-restore included) so
    # it's correct even when resuming mid-chapter.
    prev_line_text = None

    for idx, passage in enumerate(passages):
        passage_text = passage.text
        h = hash_passage(passage_text)

        if checkpoint.is_passage_annotated(chapter_number, idx, h):
            print(f"Passage {idx + 1}/{n_passages}: already annotated, skipping")
            entry = checkpoint.get_entry(chapter_number, idx)
            roster = list(entry.get("roster", roster))
            for line in entry["annotation"]["lines"]:
                all_lines.append(_resolve_line(line, cast))
            prev_line_text = entry["annotation"]["lines"][-1]["text"]
            continue

        if passage.has_dialogue:
            if client is None:
                client = annotation.make_client()
            print(f"Passage {idx + 1}/{n_passages}: annotating via OpenAI ({annotation.MODEL}) ...")
            result = annotation.annotate_passage(client, passage_text, roster, prev_line_text)
        else:
            result = annotation.short_circuit_narrator(passage_text)

        annotation.update_roster(roster, result["lines"])
        for line in result["lines"]:
            all_lines.append(_resolve_line(line, cast))

        checkpoint.set_entry(chapter_number, idx, h, result, list(roster))
        print(f"Passage {idx + 1}/{n_passages}: annotated ({len(result['lines'])} lines)")
        prev_line_text = result["lines"][-1]["text"]

    return all_lines


def _phase2_synthesize_chunks(chapter_number, chunks, workers):
    """Parallel pass: builds one SynthesisJob per Chunk whose audio file
    doesn't already exist on disk (content-hash-addressed — see
    `chunking.py` — so this is a plain `os.path.exists` check, no
    Checkpoint involvement at all), then synthesizes them across worker
    processes. Chunks are independent of each other (unlike the old
    per-Line jobs, nothing here needs to track "all of this Passage's
    Lines are done" — each Chunk's audio file existing IS it being done).

    Deliberately does not create any directory itself: each Chunk's
    `audio_path` was already computed by `chunking.build_chunks` against
    whatever `audio_cache_dir` the caller passed it (not necessarily this
    module's own `AUDIO_CACHE_DIR` constant — e.g. a test harness may use
    an isolated directory), and `synthesis.run_job` already creates
    `os.path.dirname(job.audio_path)` itself before writing. Deriving a
    directory from the module-level constant here instead would silently
    create the wrong (or an extra, unused) directory whenever chunks were
    built against a different audio_cache_dir."""
    jobs: list[SynthesisJob] = []
    for i, c in enumerate(chunks):
        if os.path.exists(c.audio_path):
            continue
        jobs.append(
            SynthesisJob(
                chapter_number=chapter_number,
                chunk_index=i,
                text=c.text,
                voice=c.voice,
                instruct=c.instruct,
                audio_path=c.audio_path,
                is_narrator=c.is_narrator,
            )
        )

    total_chunks = len(chunks)
    if not jobs:
        print(f"No audio synthesis needed (all {total_chunks} chunk(s) already cached).")
        return

    total_jobs = len(jobs)
    threads_per_worker = synthesis.default_threads_per_worker(workers)
    print(
        f"Starting {workers} worker process(es) (each loading its own Qwen3-TTS model copy, "
        f"{threads_per_worker} torch thread(s) each) for {total_jobs}/{total_chunks} chunk(s) "
        f"needing synthesis ..."
    )

    completed = 0
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
                        f"Synthesis failed for chapter {job.chapter_number} chunk "
                        f"{job.chunk_index} (aborting run; already-synthesized chunk "
                        f"audio files remain valid, rerun to resume): {e}"
                    ) from e

                completed += 1
                print(f"Chunk {job.chunk_index + 1}/{total_chunks} synthesized ({completed}/{total_jobs}) -> {job.audio_path}")
        except Exception:
            # Let already-running jobs finish (can't preempt a running
            # process), but don't start any more that were merely queued.
            executor.shutdown(wait=True, cancel_futures=True)
            raise


def run(book_path: str, chapter_number: int, skip_tts: bool = False, workers: int = DEFAULT_WORKERS):
    overrides = Cast.load_overrides(CAST_JSON_PATH)
    voice_config = load_voice_config(VOICES_JSON_PATH)
    # A single Cast instance for the entire run — Cast is stateless (a
    # pure function of role + current config, see ticket 05's 2026-09-13
    # amendment), so there's no per-Passage restore/reconstruction needed
    # anymore, unlike before that amendment.
    cast = Cast(voice_config=voice_config, overrides=overrides)

    book_slug = _book_slug(book_path)
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)
    checkpoint = Checkpoint(os.path.join(CHECKPOINT_DIR, f"{book_slug}.checkpoint.json"))

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
        if not checkpoint.is_passage_annotated(chapter_number, idx, h):
            first_pending = idx
            break

    if first_pending is not None:
        # A stale/invalidated passage invalidates every checkpoint entry after it too:
        # the roster/cast snapshots from here on were built on top of it, so they can't
        # be trusted (ticket 07's sequential-roster requirement). Runs once here, before
        # Phase 1 begins. Note: unlike before the Chunk-layer refactor, there is no
        # separate stale-audio-file cleanup step here anymore (see ticket 07's amendment
        # on why `_clear_stale_audio` was removed) — a re-annotated Passage naturally
        # produces Lines whose merged Chunk(s) hash differently, so any old Chunk audio
        # file is simply orphaned on disk, never collided with or mistakenly reused.
        checkpoint.invalidate_from(chapter_number, first_pending)

    roster = _reconstruct_state(checkpoint, chapter_number, n_passages, first_pending)
    if first_pending is None:
        print("All passages already annotated — nothing to (re-)annotate.")
    elif first_pending == 0:
        print("Starting fresh (no prior checkpoint progress).")
    else:
        print(f"Resuming from passage {first_pending + 1}/{n_passages} (roster so far: {roster})")

    # Phase 1 (sequential): annotate + assign Voices for every passage, and
    # accumulate the Chapter's full ordered Line list.
    all_lines = _phase1_annotate_and_assign_voices(passages, chapter_number, n_passages, checkpoint, roster, cast)

    if skip_tts:
        print("skip_tts=True: not building chunks or assembling the final chapter WAV.")
        return None

    # Chunk-building: a pure, deterministic function of the Chapter's full
    # ordered Line list (see chunking.py). Merges consecutive Narrator
    # Lines (even across Passage/heading boundaries) into single Chunks,
    # breaking only at real dialogue Lines.
    chunks = chunking.build_chunks(all_lines, os.path.join(AUDIO_CACHE_DIR, book_slug), chapter_number)
    print(f"Built {len(chunks)} chunk(s) from {len(all_lines)} line(s).")

    # Phase 2 (parallel): synthesize every Chunk whose audio isn't already
    # cached, across worker processes.
    _phase2_synthesize_chunks(chapter_number, chunks, workers)

    print("Assembling chapter WAV from chunk audio ...")
    out_path = assembly.assemble_chapter([c.audio_path for c in chunks], chapter_number, chapter.title, OUTPUT_DIR)
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
