import json
import os

# The 4 fixed, configurable role-voices (see ticket 05's 2026-09-13
# amendment: the old gender-partitioned pool + cycling design is replaced
# entirely). Applied whenever `voices.json` is missing, or missing a given
# key (per-key fallback, not all-or-nothing).
DEFAULT_VOICES = {
    "narrator": "Ryan",
    "adult_male": "Ryan",
    "adult_female": "Serena",
    "child": "Vivian",
}


def load_voice_config(path: str) -> dict:
    """Loads the 4 role-voice config from `voices.json`.

    Missing file -> DEFAULT_VOICES, unchanged. Present file -> each of the
    4 keys is taken from the file if present, else falls back individually
    to its own default (a file overriding only one key, e.g.
    `{"adult_female": "Vivian"}`, leaves the other 3 at their defaults —
    not an all-or-nothing replacement)."""
    if not os.path.exists(path):
        return dict(DEFAULT_VOICES)
    with open(path, encoding="utf-8") as f:
        data = json.load(f) or {}
    return {key: data.get(key, default) for key, default in DEFAULT_VOICES.items()}


def role_for(gender: str, is_child: bool, is_narrator: bool) -> str:
    """Which of the 4 fixed roles (narrator/adult_male/adult_female/child)
    a Line falls into, independent of which actual voice string ends up
    used for it (a `cast.json` override can still pin the Line to some
    other voice entirely — the role is about categorization/filenames,
    not the resolved voice). Narrator takes priority over everything else
    (a Narrator Line's `speaker_gender`/`speaker_is_child` are not
    meaningful, per the annotation schema)."""
    if is_narrator:
        return "narrator"
    if is_child:
        return "child"
    return "adult_male" if gender == "male" else "adult_female"


class Cast:
    """Stateless, pure lookup: a Speaker's Voice is a pure function of its
    role (narrator / adult_male / adult_female / child) plus the current
    `voice_config` and any per-character `cast.json` override — never a
    function of assignment order or what's been handed out before. No more
    per-run memory of past assignments is kept at all (see ticket 05's
    2026-09-13 amendment), which is also what makes a `voices.json` change
    take effect on an already-annotated-but-not-yet-synthesized Passage
    without forcing any already-synthesized audio to be regenerated (see
    ticket 07's amendment): the resolved voice for a given (role, config)
    pair is always the same, in every Chapter, in every run, with nothing
    to restore/snapshot across a resumed run."""

    def __init__(self, voice_config: dict | None = None, overrides: dict[str, str] | None = None):
        self.voice_config = {**DEFAULT_VOICES, **(voice_config or {})}
        self.overrides: dict[str, str] = dict(overrides or {})

    @classmethod
    def load_overrides(cls, cast_json_path: str) -> dict[str, str]:
        if not os.path.exists(cast_json_path):
            return {}
        with open(cast_json_path, encoding="utf-8") as f:
            return json.load(f)

    def role_for(self, gender: str, is_child: bool, is_narrator: bool = False) -> str:
        return role_for(gender, is_child, is_narrator)

    def voice_for(self, speaker: str, gender: str, is_child: bool, is_narrator: bool = False) -> str:
        if speaker in self.overrides:
            return self.overrides[speaker]
        if is_narrator:
            return self.voice_config["narrator"]
        if is_child:
            return self.voice_config["child"]
        return self.voice_config["adult_male"] if gender == "male" else self.voice_config["adult_female"]
