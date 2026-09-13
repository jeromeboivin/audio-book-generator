import argparse
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audiobook import annotation, assembly, chunking, parsing, synthesis
from audiobook.cast import Cast, load_voice_config
from audiobook.checkpoint import Checkpoint, hash_passage
from audiobook.chunking import AnnotatedLine
from audiobook.parsing import Passage, extract_chapter
from audiobook.synthesis import SynthesisJob

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
    """The full list of things to narrate for a Chapter: its own heading
    (e.g. "Chapitre I", or just "1" for an EPUB3-semantic-section book)
    first, then its title (e.g. "Monsieur Myriel") IF it has one, then its
    body Passages.

    Both heading and title are real narration content, not just boundary
    markers to be discarded — a real bug found in production: `heading`
    (the <h2> "Chapitre N" text) was never narrated at all, only `title`
    (the <h3>) was. Their Passages' `has_dialogue` is hard-set False, not
    computed — neither is ever dialogue, and both must always
    short-circuit straight to a Narrator Line via
    `annotation.short_circuit_narrator`, never sent to OpenAI and never
    subject to the has_dialogue/em-dash check at all.

    `chapter.title` is `""` for a book whose semantic-section chapters have
    no separate subtitle at all (e.g. L'Autre Moi — see
    `parsing._extract_semantic_chapter`) — an empty title must NOT produce
    an empty/pointless Narrator Passage, so the title Passage is only built
    when `chapter.title` is non-empty. The heading Passage is always built
    (it's never empty for a valid Chapter)."""
    passages = [Passage(text=chapter.heading, has_dialogue=False)]
    if chapter.title:
        passages.append(Passage(text=chapter.title, has_dialogue=False))
    passages.extend(chapter.passages)
    return passages


NARRATOR_TONE_SAMPLE_PASSAGES = 5
NARRATOR_TONE_SAMPLE_MAX_CHARS_PER_PASSAGE = 800


def _narrator_tone_sample(chapter) -> str:
    """A small, fixed sample of the Chapter's opening — its heading and
    title plus its first few body Passages — for
    `annotation.guess_narrator_tone` (see main.py's `--narrator-tone`
    flag). Deliberately NOT the whole Chapter: this is meant to be a
    cheap, quick "what's the overall register here" guess, not a full
    read. Each sampled Passage is truncated defensively (some books'
    paragraphs can be very long) so one giant paragraph can't blow up the
    sample's size."""
    parts = [chapter.heading, chapter.title]
    for passage in chapter.passages[:NARRATOR_TONE_SAMPLE_PASSAGES]:
        parts.append(passage.text[:NARRATOR_TONE_SAMPLE_MAX_CHARS_PER_PASSAGE])
    return "\n".join(parts)


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


def _resolve_line(line: dict, cast: Cast, narrator_instruct: str | None = None) -> AnnotatedLine:
    """Turns one raw annotation Line dict (as returned by an Annotation
    Pass call, a Narrator short-circuit, or restored verbatim from a
    checkpointed Passage) into an AnnotatedLine ready for chunk-building —
    i.e. resolves its Cast-assigned Voice and role. `cast.voice_for`/
    `cast.role_for` are pure, stateless lookups (see ticket 05's
    2026-09-13 amendment) applied uniformly to both Narrator and dialogue
    Lines, so calling this on a restored (already-checkpointed) Passage's
    lines against the same single `Cast` instance used for the whole run
    is always correct and deterministic.

    `narrator_instruct`: the chapter-wide instruct string every Narrator
    Line gets (see `annotation.guess_narrator_tone`), or None if
    `--no-narrator-tone` disabled the feature for this run. Ignored for
    non-Narrator Lines, which always use their own per-Line `instruct`."""
    voice = cast.voice_for(line["speaker"], line["speaker_gender"], line["speaker_is_child"], is_narrator=line["is_narrator"])
    role = cast.role_for(line["speaker_gender"], line["speaker_is_child"], is_narrator=line["is_narrator"])
    return AnnotatedLine(
        text=line["text"],
        is_narrator=line["is_narrator"],
        voice=voice,
        instruct=narrator_instruct if line["is_narrator"] else line.get("instruct"),
        role=role,
    )


def _phase1_annotate_and_assign_voices(
    passages, chapter_number, n_passages, checkpoint, roster, cast, openai_model, narrator_instruct=None
):
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

    for idx, passage in tqdm(
        list(enumerate(passages)),
        total=n_passages,
        desc=f"Chapter {chapter_number}: annotating passages",
        unit="passage",
    ):
        passage_text = passage.text
        h = hash_passage(passage_text)

        if checkpoint.is_passage_annotated(chapter_number, idx, h):
            tqdm.write(f"Passage {idx + 1}/{n_passages}: already annotated, skipping")
            entry = checkpoint.get_entry(chapter_number, idx)
            roster = list(entry.get("roster", roster))
            for line in entry["annotation"]["lines"]:
                all_lines.append(_resolve_line(line, cast, narrator_instruct))
            prev_line_text = entry["annotation"]["lines"][-1]["text"]
            continue

        if passage.has_dialogue:
            if client is None:
                client = annotation.make_client()
            tqdm.write(f"Passage {idx + 1}/{n_passages}: annotating via OpenAI ({openai_model}) ...")
            result = annotation.annotate_passage(client, passage_text, roster, prev_line_text, model=openai_model)
        else:
            result = annotation.short_circuit_narrator(passage_text)

        annotation.update_roster(roster, result["lines"])
        for line in result["lines"]:
            all_lines.append(_resolve_line(line, cast, narrator_instruct))

        checkpoint.set_entry(chapter_number, idx, h, result, list(roster))
        tqdm.write(f"Passage {idx + 1}/{n_passages}: annotated ({len(result['lines'])} lines)")
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
        tqdm.write(f"No audio synthesis needed (all {total_chunks} chunk(s) already cached).")
        return

    total_jobs = len(jobs)
    threads_per_worker = synthesis.default_threads_per_worker(workers)
    tqdm.write(
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
            for future in tqdm(
                as_completed(futures),
                total=total_jobs,
                desc=f"Chapter {chapter_number}: synthesizing chunks",
                unit="chunk",
            ):
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
                tqdm.write(f"Chunk {job.chunk_index + 1}/{total_chunks} synthesized ({completed}/{total_jobs}) -> {job.audio_path}")
        except Exception:
            # Let already-running jobs finish (can't preempt a running
            # process), but don't start any more that were merely queued.
            executor.shutdown(wait=True, cancel_futures=True)
            raise


def run(
    book_path: str,
    chapter_number: int,
    skip_tts: bool = False,
    workers: int = DEFAULT_WORKERS,
    openai_model: str = annotation.DEFAULT_MODEL,
    narrator_tone: bool = True,
):
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

    tqdm.write(f"Parsing {book_path} ...")
    chapter = extract_chapter(book_path, chapter_number)
    # Passage 0 is always the chapter's own title, narrated first (Narrator
    # voice, no Annotation Pass call); passages 1..N are the chapter's body
    # Passages, shifted by one from parsing.extract_chapter's own indexing.
    passages = _build_narration_passages(chapter)
    n_passages = len(passages)
    tqdm.write(f"Chapter {chapter_number}: '{chapter.title}', {n_passages} passages (incl. title)")

    narrator_instruct = None
    if narrator_tone:
        narrator_instruct = checkpoint.get_narrator_instruct(chapter_number)
        if narrator_instruct is not None:
            tqdm.write(f"--narrator-tone: reusing cached tone for this Chapter: {narrator_instruct!r}")
        else:
            tqdm.write("--narrator-tone: guessing this Chapter's overall narrative tone via OpenAI ...")
            sample = _narrator_tone_sample(chapter)
            client = annotation.make_client()
            narrator_instruct = annotation.guess_narrator_tone(client, sample, model=openai_model)
            checkpoint.set_narrator_instruct(chapter_number, narrator_instruct)
            tqdm.write(f"--narrator-tone: guessed and cached: {narrator_instruct!r}")

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
        tqdm.write("All passages already annotated — nothing to (re-)annotate.")
    elif first_pending == 0:
        tqdm.write("Starting fresh (no prior checkpoint progress).")
    else:
        tqdm.write(f"Resuming from passage {first_pending + 1}/{n_passages} (roster so far: {roster})")

    # Phase 1 (sequential): annotate + assign Voices for every passage, and
    # accumulate the Chapter's full ordered Line list.
    all_lines = _phase1_annotate_and_assign_voices(
        passages, chapter_number, n_passages, checkpoint, roster, cast, openai_model, narrator_instruct
    )

    if skip_tts:
        tqdm.write("skip_tts=True: not building chunks or assembling the final chapter WAV.")
        return None

    # Chunk-building: a pure, deterministic function of the Chapter's full
    # ordered Line list (see chunking.py). Merges consecutive Narrator
    # Lines (even across Passage/heading boundaries) into single Chunks,
    # breaking only at real dialogue Lines.
    chunks = chunking.build_chunks(all_lines, os.path.join(AUDIO_CACHE_DIR, book_slug), chapter_number)
    tqdm.write(f"Built {len(chunks)} chunk(s) from {len(all_lines)} line(s).")

    # Phase 2 (parallel): synthesize every Chunk whose audio isn't already
    # cached, across worker processes.
    _phase2_synthesize_chunks(chapter_number, chunks, workers)

    tqdm.write("Assembling chapter WAV from chunk audio ...")
    out_path = assembly.assemble_chapter([c.audio_path for c in chunks], chapter_number, chapter.title, OUTPUT_DIR)
    tqdm.write(f"Wrote {out_path}")
    return out_path


def run_all_chapters(
    book_path: str,
    skip_tts: bool = False,
    workers: int = DEFAULT_WORKERS,
    openai_model: str = annotation.DEFAULT_MODEL,
    narrator_tone: bool = True,
):
    """Whole-book batch mode (`--all-chapters`): loops chapters 1..N,
    calling `run()` unchanged for each — this function is purely an outer
    loop, all per-chapter logic (annotation/chunking/synthesis/assembly,
    and their own resumability) stays entirely inside `run()`.

    Chapter-level resumability: a chapter is skipped ENTIRELY (no
    annotation, no synthesis work, just a log line) if its output WAV
    already exists in `OUTPUT_DIR` — computed via `assembly.chapter_filename`
    (shared with `assembly.assemble_chapter` itself, not re-derived here)
    from the chapter's number and title. This needs the chapter's title
    ahead of running it, so this function parses the chapter (cheap — no
    OpenAI/TTS calls) once for the pre-check; `run()` then parses it again
    itself when it actually runs — a deliberate, accepted duplication
    rather than changing `run()`'s own signature/logic to accept a
    pre-parsed Chapter, per this feature's "reuse run() completely
    unchanged" requirement.

    Stops the whole batch on the first chapter that raises — consistent
    with this project's "abort loudly, resumability makes it safe to just
    rerun" philosophy (see e.g. `_phase2_synthesize_chunks`'s matching
    comment): a failed chapter is never silently skipped so the batch can
    continue, since that would risk an unnoticed gap in the finished
    audiobook. The exception is re-raised after printing which chapter
    failed and how re-running the same command resumes, so main() still
    exits non-zero exactly like a single-chapter run's uncaught error
    would."""
    total = parsing.count_chapters(book_path)
    tqdm.write(f"--all-chapters: {total} chapter(s) detected in {book_path}")

    completed = 0
    skipped = 0
    outer = tqdm(range(1, total + 1), desc="Book: chapters", unit="chapter")
    try:
        for chapter_number in outer:
            outer.set_description(f"Book: chapter {chapter_number}/{total}")

            chapter = extract_chapter(book_path, chapter_number)
            out_path = os.path.join(OUTPUT_DIR, assembly.chapter_filename(chapter_number, chapter.title))
            if os.path.exists(out_path):
                tqdm.write(f"Chapter {chapter_number}/{total}: output already exists ({out_path}) — skipping entirely.")
                skipped += 1
                continue

            try:
                run(
                    book_path,
                    chapter_number,
                    skip_tts=skip_tts,
                    workers=workers,
                    openai_model=openai_model,
                    narrator_tone=narrator_tone,
                )
            except Exception as e:
                tqdm.write(f"\n--all-chapters: chapter {chapter_number}/{total} FAILED: {e}")
                tqdm.write(
                    f"Progress so far: {completed} completed, {skipped} skipped (already done), "
                    f"{total} total — re-running the same --all-chapters command will skip "
                    "everything already done (already-assembled chapters via the output-file "
                    "check, already-annotated passages and already-synthesized chunks within "
                    "this chapter via the existing checkpoint/content-hash caches) and resume "
                    "from here."
                )
                raise

            completed += 1
    finally:
        outer.close()

    print(
        f"\n--all-chapters summary: {completed} chapter(s) completed, {skipped} skipped "
        f"(already done), {total} total."
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--book", required=True, help="path to the EPUB file to narrate")
    chapter_group = parser.add_mutually_exclusive_group()
    chapter_group.add_argument(
        "--chapter", type=int, default=1, help="chapter number to synthesize (1-indexed, default 1)"
    )
    chapter_group.add_argument(
        "--all-chapters",
        action="store_true",
        help="process every chapter in the book, in order (1..N, via parsing.count_chapters) — "
        "resumable at the chapter level: a chapter whose output WAV already exists in the output "
        "directory is skipped entirely, and the batch stops on the first chapter that raises "
        "(rerun the same command to resume). Mutually exclusive with --chapter.",
    )
    parser.add_argument("--skip-tts", action="store_true", help="parse+annotate only, no synthesis")
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"number of parallel TTS worker processes (default {DEFAULT_WORKERS})",
    )
    parser.add_argument(
        "--openai-model",
        default=os.environ.get("OPENAI_MODEL", annotation.DEFAULT_MODEL),
        help=f"OpenAI model for the Annotation Pass (default {annotation.DEFAULT_MODEL}, "
        "or set via the OPENAI_MODEL env var) — must support structured outputs (json_schema)",
    )
    parser.add_argument(
        "--narrator-tone",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="guess this Chapter's overall narrative tone from its opening (one extra "
        "OpenAI call, cached per Chapter) and apply it as a single, chapter-wide instruct "
        "string to every Narrator Chunk. On by default; pass --no-narrator-tone to go back "
        "to Narrator Lines carrying no instruct at all",
    )
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be >= 1")
    if args.all_chapters:
        run_all_chapters(
            args.book,
            skip_tts=args.skip_tts,
            workers=args.workers,
            openai_model=args.openai_model,
            narrator_tone=args.narrator_tone,
        )
    else:
        run(
            args.book,
            args.chapter,
            skip_tts=args.skip_tts,
            workers=args.workers,
            openai_model=args.openai_model,
            narrator_tone=args.narrator_tone,
        )


if __name__ == "__main__":
    main()
