import torch
from qwen_tts import Qwen3TTSModel

# Narrator Lines (is_narrator=true, chapter titles included) are always
# synthesized with the smaller 0.6B model and never receive an `instruct`
# string. Dialogue Lines (any non-Narrator Speaker) always use the larger
# 1.7B model with a one-sentence OpenAI-generated `instruct` string. This is
# a permanent model-routing rule, not a coincidence of what happened to be
# wired up first — see ticket 01's amendment: the official README only marks
# "Instruction Control" (its `instruct` parameter) as benchmarked/documented
# for the 1.7B CustomVoice/VoiceDesign variants, not the 0.6B.
NARRATOR_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
DIALOGUE_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
SAMPLE_RATE = 24000


def _select_device_dtype_and_attn() -> dict:
    """Decides the `from_pretrained` kwargs for either model size, uniformly.

    GPU present (`torch.cuda.is_available()`): `device_map="cuda:0"`,
    `dtype=torch.bfloat16`, and best-effort `attn_implementation=
    "flash_attention_2"` — only added if `import flash_attn` actually
    succeeds. No GPU: falls back to exactly the already-proven CPU path
    (`device_map="cpu"`, `dtype=torch.float32`, no attn kwarg at all).

    This never raises: GPU/flash-attn absence is always a silent, logged
    fallback, not an error, so a model load on a CPU-only or flash-attn-less
    machine always proceeds via the plain path.
    """
    if not torch.cuda.is_available():
        print("[tts] no CUDA device detected — loading on CPU (device_map=cpu, dtype=float32).", flush=True)
        return {"device_map": "cpu", "dtype": torch.float32}

    kwargs = {"device_map": "cuda:0", "dtype": torch.bfloat16}
    try:
        import flash_attn  # noqa: F401
    except ImportError:
        print(
            "[tts] CUDA device detected but flash-attn is not importable — loading on GPU "
            "(device_map=cuda:0, dtype=bfloat16) with the default attention implementation.",
            flush=True,
        )
        return kwargs

    kwargs["attn_implementation"] = "flash_attention_2"
    print(
        "[tts] CUDA device detected — loading on GPU "
        "(device_map=cuda:0, dtype=bfloat16, attn_implementation=flash_attention_2).",
        flush=True,
    )
    return kwargs


def load_model(model_id: str):
    """Loads a Qwen3-TTS model by id, using the shared device/dtype/attn
    selection above. Used for both NARRATOR_MODEL_ID and DIALOGUE_MODEL_ID —
    the routing decision (which id to load when) lives in synthesis.py, not
    here."""
    kwargs = _select_device_dtype_and_attn()
    try:
        return Qwen3TTSModel.from_pretrained(model_id, **kwargs)
    except Exception as e:
        if kwargs.get("attn_implementation") == "flash_attention_2":
            print(
                f"[tts] loading {model_id} with attn_implementation=flash_attention_2 failed "
                f"({e!r}) — retrying without it.",
                flush=True,
            )
            kwargs.pop("attn_implementation")
            return Qwen3TTSModel.from_pretrained(model_id, **kwargs)
        raise


def synthesize_line(model, text: str, speaker: str, instruct: str | None):
    wavs, sr = model.generate_custom_voice(
        text=text,
        language="French",
        speaker=speaker,
        instruct=instruct or "",
    )
    return wavs[0], sr
