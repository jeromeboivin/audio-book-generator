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
    def __init__(self, number: int, title: str, passages: list[Passage]):
        self.number = number
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
    body = soup.find("body")
    if body is None:
        return
    for el in body.find_all(["h2", "h3", "p"]):
        yield el


def extract_chapter(epub_path: str, chapter_number: int) -> Chapter:
    book = epub.read_epub(epub_path)

    elements = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
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
        if not CHAPTER_HEADING_RE.fullmatch(el.get_text().strip()):
            continue
        nxt = elements[i + 1] if i + 1 < len(elements) else None
        if nxt is not None and nxt.name == "h3":
            boundaries.append((i, nxt.get_text().strip()))

    if chapter_number < 1 or chapter_number > len(boundaries):
        raise ValueError(
            f"chapter {chapter_number} not found; {len(boundaries)} chapter "
            f"boundaries detected in {epub_path}"
        )

    start_idx, title = boundaries[chapter_number - 1]
    end_idx = (
        boundaries[chapter_number][0]
        if chapter_number < len(boundaries)
        else len(elements)
    )

    passages = []
    for el in elements[start_idx + 2 : end_idx]:
        if el.name != "p":
            continue
        raw_text = el.get_text()
        text = _normalize(raw_text)
        if text:
            passages.append(Passage(text=text, has_dialogue=_has_dialogue_line(raw_text)))

    return Chapter(number=chapter_number, title=title, passages=passages)
