import json
import os

NARRATOR_VOICE = "Uncle_Fu"
NARRATOR_SPEAKER = "Narrator"

SUB_POOLS = {
    "male": ["Ryan", "Aiden"],
    "female": ["Serena", "Vivian"],
}


class Cast:
    def __init__(self, assignments: dict[str, str] | None = None, overrides: dict[str, str] | None = None):
        self.assignments: dict[str, str] = dict(assignments or {})
        self.overrides: dict[str, str] = dict(overrides or {})
        # per sub-pool, index of the next Voice to hand out on the *next*
        # cycle-around (so exhaustion reuses the least-recently-assigned
        # Voice first, per ticket 05).
        self._next_cycle_index: dict[str, int] = {"male": 0, "female": 0}
        self._assigned_count: dict[str, int] = {"male": 0, "female": 0}
        self.assignments.setdefault(NARRATOR_SPEAKER, NARRATOR_VOICE)

    @classmethod
    def load_overrides(cls, cast_json_path: str) -> dict[str, str]:
        if not os.path.exists(cast_json_path):
            return {}
        with open(cast_json_path, encoding="utf-8") as f:
            return json.load(f)

    def voice_for(self, speaker: str, gender: str, is_child: bool) -> str:
        if speaker in self.assignments:
            return self.assignments[speaker]
        if speaker in self.overrides:
            voice = self.overrides[speaker]
            self.assignments[speaker] = voice
            return voice

        pool_name = "female" if is_child else gender
        pool = SUB_POOLS[pool_name]
        count = self._assigned_count[pool_name]
        if count < len(pool):
            voice = pool[count]
        else:
            idx = self._next_cycle_index[pool_name] % len(pool)
            voice = pool[idx]
            self._next_cycle_index[pool_name] = idx + 1
        self._assigned_count[pool_name] += 1
        self.assignments[speaker] = voice
        return voice

    def to_snapshot(self) -> dict:
        return {
            "assignments": dict(self.assignments),
            "next_cycle_index": dict(self._next_cycle_index),
            "assigned_count": dict(self._assigned_count),
        }

    @classmethod
    def from_snapshot(cls, snapshot: dict, overrides: dict[str, str]) -> "Cast":
        cast = cls(assignments=snapshot.get("assignments"), overrides=overrides)
        cast._next_cycle_index = dict(snapshot.get("next_cycle_index", {"male": 0, "female": 0}))
        cast._assigned_count = dict(snapshot.get("assigned_count", {"male": 0, "female": 0}))
        return cast
