import re
from dataclasses import dataclass

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

CHAPTER_HEADING_RE = re.compile(r"Chapitre \w+", re.IGNORECASE)


@dataclass
class Passage:
    """One paragraph's worth of narration.

    `text` is whitespace-collapsed (single spaces, no embedded newlines) —
    this is what's sent to the Annotation Pass and to TTS (see ticket 04's
    whitespace-normalization amendment: Qwen3-TTS reads a raw embedded
    newline as an unwanted mid-sentence pause).

    `has_dialogue` is computed once, here, from the RAW pre-collapse text
    (which still has real line breaks) by checking every physical source
    line for one whose stripped content starts with an em-dash (—) —  not
    just whether the whole (already-collapsed) Passage starts with one.
    That distinction matters: dialogue that opens on a new line partway
    through a `<p>` (e.g. a narration sentence ending in a colon, followed
    by an em-dash-led line of dialogue within the same paragraph) is
    invisible to a "does the collapsed text start with —" check, since by
    the time that check runs the newline that marked the new line is
    already gone. See ticket 04's amendment for the concrete bug this
    fixes. Downstream (main.py), `has_dialogue` is what decides whether a
    Passage gets an Annotation Pass call or short-circuits straight to a
    Narrator Line — not any re-derivation from the normalized text.
    """

    text: str
    has_dialogue: bool


class Chapter:
    """`heading` is the `<h2>` text (e.g. "Chapitre I") and `title` is the
    `<h3>` text (e.g. "Monsieur Myriel") — the two elements that together
    define this Chapter's boundary (see `extract_chapter`). Both are real
    narration content and must be narrated as such, not just consulted for
    boundary detection and discarded — a real bug found in production: the
    `<h2>` chapter-number heading was never making it into the narrated
    output at all, only `title` was (see main.py's
    `_build_narration_passages`)."""

    def __init__(self, number: int, heading: str, title: str, passages: list[Passage]):
        self.number = number
        self.heading = heading
        self.title = title
        self.passages = passages


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _has_dialogue_line(raw_text: str) -> bool:
    """True if any physical source line (split on real `\\n`, before
    whitespace collapse) is a dialogue opening — its stripped content
    starts with an em-dash (—). Must be called on the RAW text; the
    normalized/collapsed text has already destroyed the line-break signal
    this needs."""
    return any(line.strip().startswith("—") for line in raw_text.split("\n"))


def _iter_body_elements(soup: BeautifulSoup):
    """Yields every element that can plausibly participate in a chapter's
    structure: any heading level (h1-h6) plus paragraphs.

    Only h2 (chapter number) + h3 (title) are ever consulted as the
    chapter-boundary pair (see `extract_chapter`). Every OTHER heading
    level is yielded here purely so it becomes ordinary passage-like
    content within a chapter's body instead of being invisible to the
    whole pipeline — see ticket 04's 2026-09-13 amendment (non-title
    headings must be narrated, not silently dropped). The real test EPUB
    (`samples/Les misérables Tome I Fantine.epub`) was checked directly:
    it uses h1 (title-page only, e.g. "Les Misérables" / "Victor Hugo",
    entirely outside any chapter boundary), h2, and h3 — no h4/h5/h6 occur
    anywhere in the file. h1/h4/h5/h6 are included here anyway so this
    stays correct for headings this book doesn't happen to use, rather
    than encoding "only ever h2/h3" as an assumption."""
    body = soup.find("body")
    if body is None:
        return
    for el in body.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p"]):
        yield el


def extract_chapter(epub_path: str, chapter_number: int) -> Chapter:
    book = epub.read_epub(epub_path)

    elements = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        # ebooklib's auto-generated EpubNav (the EPUB3 table-of-contents
        # document) reports the same item type (ITEM_DOCUMENT) as real
        # content — get_items_of_type can't tell them apart. It must still
        # be excluded here: its <nav><h2>book title</h2>...</nav> structure
        # is never narration, and since the h1-h6 broadening above (ticket
        # 04's amendment) no longer skips non-<p> elements, a nav document's
        # heading would otherwise silently leak into whichever chapter's
        # slice runs unbounded to the end of `elements` (typically the last
        # chapter in the book) — found via a synthetic test fixture, not
        # present in the real test EPUB only because that book's structure
        # happens not to trigger it.
        if isinstance(item, epub.EpubNav):
            continue
        soup = BeautifulSoup(item.get_content(), "html.parser")
        elements.extend(_iter_body_elements(soup))

    # A real chapter boundary is an <h2> matching "Chapitre \w+" immediately
    # followed by an <h3> (the title) — this is what distinguishes a real
    # body chapter from Gutenberg's TOC block (its <a class="pginternal">
    # links are never immediately followed by an <h3>), and taking chapter
    # boundaries in document order (rather than deduping by heading text)
    # is what correctly handles chapter numbers resetting per Livre/Part.
    boundaries = []
    for i, el in enumerate(elements):
        if el.name != "h2":
            continue
        heading_text = el.get_text().strip()
        if not CHAPTER_HEADING_RE.fullmatch(heading_text):
            continue
        nxt = elements[i + 1] if i + 1 < len(elements) else None
        if nxt is not None and nxt.name == "h3":
            boundaries.append((i, heading_text, nxt.get_text().strip()))

    if chapter_number < 1 or chapter_number > len(boundaries):
        raise ValueError(
            f"chapter {chapter_number} not found; {len(boundaries)} chapter "
            f"boundaries detected in {epub_path}"
        )

    start_idx, heading, title = boundaries[chapter_number - 1]
    end_idx = (
        boundaries[chapter_number][0]
        if chapter_number < len(boundaries)
        else len(elements)
    )

    # Every element in this slice other than the two boundary-defining
    # elements themselves (already excluded by starting at start_idx + 2)
    # is treated uniformly as passage-like content — a <p> and any other
    # heading level (e.g. a subtitle or epigraph heading between this
    # chapter's title and its first paragraph, or a "Livre N" heading that
    # sometimes trails a chapter's last paragraph in the real test EPUB —
    # see ticket 04's amendment) get the exact same treatment: `.get_text()`,
    # the same whitespace normalization, and the same has_dialogue check. No
    # special-casing by tag name here is intentional — nothing should be
    # silently skipped just because it isn't a <p>. `end_idx` already stops
    # before the next real chapter boundary's own <h2>+<h3> pair, so this
    # can't accidentally swallow the start of the next chapter (verified
    # against the real EPUB: every one of its 70 chapter boundaries is an
    # <h2> matching "Chapitre \\w+" immediately followed by an <h3>, and
    # `end_idx` is exactly that next boundary's index).
    passages = []
    for el in elements[start_idx + 2 : end_idx]:
        raw_text = el.get_text()
        text = _normalize(raw_text)
        if text:
            passages.append(Passage(text=text, has_dialogue=_has_dialogue_line(raw_text)))

    return Chapter(number=chapter_number, heading=heading, title=title, passages=passages)
