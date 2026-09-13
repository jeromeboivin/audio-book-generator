import hashlib
import json
import os


def hash_passage(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Checkpoint:
    def __init__(self, path: str):
        self.path = path
        self.data = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        return {"passages": {}}

    def save(self) -> None:
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.path)

    @staticmethod
    def _key(chapter_number: int, passage_index: int) -> str:
        return f"{chapter_number}:{passage_index}"

    def get_entry(self, chapter_number: int, passage_index: int) -> dict | None:
        return self.data["passages"].get(self._key(chapter_number, passage_index))

    def is_passage_annotated(self, chapter_number: int, passage_index: int, text_hash: str) -> bool:
        """True if this Passage's ANNOTATION is cached and still valid
        (its stored text hash matches, and it has a non-empty `lines`
        array) — nothing about audio anymore.

        Renamed from `is_passage_done` (2026-09-13, see ticket 07's
        amendment): Lines no longer have their own individual audio files
        — multiple Passages' Narrator Lines can now share one Chunk's
        audio file (see `chunking.py`), so "every Line has an existing
        audio file" no longer means anything at the Passage level. Audio
        caching now lives one layer up, at the Chunk level, and is purely
        content-hash-addressed (a Chunk's audio_path already encodes
        everything that determines its content) rather than tracked here —
        main.py checks chunk audio existence directly with `os.path.exists`
        instead of asking the Checkpoint about it."""
        entry = self.get_entry(chapter_number, passage_index)
        if entry is None or entry.get("text_hash") != text_hash:
            return False
        lines = entry.get("annotation", {}).get("lines", [])
        return bool(lines)

    def set_entry(
        self,
        chapter_number: int,
        passage_index: int,
        text_hash: str,
        annotation: dict,
        roster_snapshot: list[str],
        cast_snapshot: dict,
    ) -> None:
        self.data["passages"][self._key(chapter_number, passage_index)] = {
            "text_hash": text_hash,
            "annotation": annotation,
            "roster": roster_snapshot,
            "cast": cast_snapshot,
        }
        self.save()

    def invalidate_from(self, chapter_number: int, from_passage_index: int) -> None:
        prefix = f"{chapter_number}:"
        stale_keys = [
            key
            for key in self.data["passages"]
            if key.startswith(prefix) and int(key.split(":", 1)[1]) >= from_passage_index
        ]
        if not stale_keys:
            return
        for key in stale_keys:
            del self.data["passages"][key]
        self.save()
