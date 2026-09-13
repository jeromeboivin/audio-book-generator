"""Plain-assertion checks for the Cast redesign (ticket 05's 2026-09-13
amendment): 4 fixed, configurable role-voices instead of a gender-
partitioned pool with cycling. No pytest dependency (the project has
none) — run directly:

    .venv-qwen-test/bin/python tests/test_cast_roles.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audiobook.cast import DEFAULT_VOICES, Cast, load_voice_config


def test_narrator_always_resolves_to_configured_narrator_voice():
    cast = Cast()
    # Regardless of the Speaker's actual name/gender/child flag, a Line
    # marked is_narrator=True always resolves to the narrator role-voice.
    assert cast.voice_for("Narrator", "male", False, is_narrator=True) == "Ryan"
    assert cast.voice_for("Some Weird Name", "female", True, is_narrator=True) == "Ryan"


def test_adult_male_resolves_to_adult_male_voice():
    cast = Cast()
    assert cast.voice_for("Marc", "male", False, is_narrator=False) == "Ryan"


def test_adult_female_resolves_to_adult_female_voice():
    cast = Cast()
    assert cast.voice_for("Léa", "female", False, is_narrator=False) == "Serena"


def test_child_resolves_to_child_voice_regardless_of_gender():
    cast = Cast()
    assert cast.voice_for("Petit Garcon", "male", True, is_narrator=False) == "Vivian"
    assert cast.voice_for("Petite Fille", "female", True, is_narrator=False) == "Vivian"


def test_cast_json_override_wins_over_role_logic():
    cast = Cast(overrides={"Marc": "Aiden"})
    # Marc would otherwise be adult_male -> Ryan, but the override wins.
    assert cast.voice_for("Marc", "male", False, is_narrator=False) == "Aiden"
    # The override applies to the Narrator too, if someone really wants it.
    cast2 = Cast(overrides={"Narrator": "Dylan"})
    assert cast2.voice_for("Narrator", "male", False, is_narrator=True) == "Dylan"


def test_override_role_is_still_the_true_role_not_the_overridden_voice():
    """A cast.json override to some other voice (e.g. Aiden) must still be
    labeled by its actual ROLE (adult_male) in the Chunk filename, not by
    whatever voice the override happens to point at."""
    cast = Cast(overrides={"Marc": "Aiden"})
    assert cast.role_for("male", False, is_narrator=False) == "adult_male"


def test_role_for_all_four_roles():
    cast = Cast()
    assert cast.role_for("male", False, is_narrator=True) == "narrator"
    assert cast.role_for("female", False, is_narrator=True) == "narrator"
    assert cast.role_for("male", False, is_narrator=False) == "adult_male"
    assert cast.role_for("female", False, is_narrator=False) == "adult_female"
    assert cast.role_for("male", True, is_narrator=False) == "child"
    assert cast.role_for("female", True, is_narrator=False) == "child"


def test_load_voice_config_missing_file_gives_all_defaults():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "does_not_exist.json")
        assert load_voice_config(path) == DEFAULT_VOICES


def test_load_voice_config_empty_file_gives_all_defaults():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "voices.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({}, f)
        assert load_voice_config(path) == DEFAULT_VOICES


def test_load_voice_config_partial_file_falls_back_per_key():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "voices.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"adult_female": "Vivian"}, f)
        config = load_voice_config(path)
        assert config["adult_female"] == "Vivian"
        assert config["narrator"] == DEFAULT_VOICES["narrator"]
        assert config["adult_male"] == DEFAULT_VOICES["adult_male"]
        assert config["child"] == DEFAULT_VOICES["child"]


def test_cast_has_no_stateful_memory():
    """Two independently-built Cast instances from the same config must
    produce identical results for the same inputs, in any order — Cast is
    a pure function of (role, config), never a function of what's already
    been assigned (unlike the old pool/cycling design). This specifically
    guards against Cast accidentally still tracking per-Speaker
    assignments somewhere internally."""
    voice_config = {"adult_male": "Aiden"}
    cast_a = Cast(voice_config=voice_config)
    cast_b = Cast(voice_config=voice_config)

    # Feed cast_a a bunch of different male Speakers first (in the old
    # design this would have exhausted/cycled a sub-pool); cast_b never
    # sees any of them.
    for name in ["Marc", "Paul", "Jean", "Pierre", "Luc"]:
        cast_a.voice_for(name, "male", False, is_narrator=False)

    # Both must resolve a brand-new male Speaker identically.
    assert cast_a.voice_for("NouveauPersonnage", "male", False, is_narrator=False) == "Aiden"
    assert cast_b.voice_for("NouveauPersonnage", "male", False, is_narrator=False) == "Aiden"

    # And every one of the previously-seen Speakers still resolves the
    # same way from a fresh Cast instance that never saw them before.
    for name in ["Marc", "Paul", "Jean", "Pierre", "Luc"]:
        assert cast_b.voice_for(name, "male", False, is_narrator=False) == "Aiden"


def test_two_different_male_characters_get_the_same_voice():
    """The whole point of the redesign: no more distinct per-character
    voices within a gender/role — every adult male Speaker gets the SAME
    configured voice (Ryan by default), including the Narrator."""
    cast = Cast()
    assert cast.voice_for("Marc", "male", False, is_narrator=False) == "Ryan"
    assert cast.voice_for("Paul", "male", False, is_narrator=False) == "Ryan"
    assert cast.voice_for("Narrator", "male", False, is_narrator=True) == "Ryan"


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {t.__name__}: {e}")
    if failures:
        print(f"\n{failures}/{len(tests)} failed")
        sys.exit(1)
    print(f"\nall {len(tests)} passed")
