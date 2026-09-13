"""Plain-assertion checks for tts._select_device_dtype_and_attn's three
branches. No pytest dependency (the project has none) — run directly:

    .venv-qwen-test/bin/python tests/test_tts_device_selection.py

Exists to close a real gap: ticket 01's amendment claims this logic is
"unverified beyond a unit test that monkeypatches torch.cuda.is_available" —
a code-review pass found no such test actually persisted in the repo. This
file is that test, for real, checked in.
"""

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import torch

from audiobook import tts


def test_no_gpu_falls_back_to_cpu_float32():
    with mock.patch("torch.cuda.is_available", return_value=False):
        kwargs = tts._select_device_dtype_and_attn()
    assert kwargs == {"device_map": "cpu", "dtype": torch.float32}, kwargs


def test_gpu_without_flash_attn_omits_attn_kwarg():
    with mock.patch("torch.cuda.is_available", return_value=True), mock.patch.dict(
        sys.modules, {"flash_attn": None}
    ):
        kwargs = tts._select_device_dtype_and_attn()
    assert kwargs == {"device_map": "cuda:0", "dtype": torch.bfloat16}, kwargs


def test_gpu_with_flash_attn_adds_attn_kwarg():
    fake_flash_attn = mock.MagicMock()
    with mock.patch("torch.cuda.is_available", return_value=True), mock.patch.dict(
        sys.modules, {"flash_attn": fake_flash_attn}
    ):
        kwargs = tts._select_device_dtype_and_attn()
    assert kwargs == {
        "device_map": "cuda:0",
        "dtype": torch.bfloat16,
        "attn_implementation": "flash_attention_2",
    }, kwargs


def test_attn_related_failure_is_retried_without_flash_attn():
    calls = []

    def fake_from_pretrained(model_id, **kwargs):
        calls.append(kwargs)
        if "attn_implementation" in kwargs:
            raise RuntimeError("FlashAttention2 requires a CUDA capability >= 8.0")
        return "loaded-model"

    with mock.patch("torch.cuda.is_available", return_value=True), mock.patch.dict(
        sys.modules, {"flash_attn": mock.MagicMock()}
    ), mock.patch.object(tts.Qwen3TTSModel, "from_pretrained", staticmethod(fake_from_pretrained)):
        result = tts.load_model("some/model")

    assert result == "loaded-model"
    assert len(calls) == 2, calls
    assert "attn_implementation" in calls[0] and "attn_implementation" not in calls[1], calls


def test_unrelated_failure_is_not_swallowed():
    """A from_pretrained failure that has nothing to do with attention
    (e.g. a bad HF cache, OOM, network error) must surface as itself, not
    get silently retried-and-masked as if it were a flash-attn problem."""

    def fake_from_pretrained(model_id, **kwargs):
        raise OSError("could not connect to huggingface.co")

    with mock.patch("torch.cuda.is_available", return_value=True), mock.patch.dict(
        sys.modules, {"flash_attn": mock.MagicMock()}
    ), mock.patch.object(tts.Qwen3TTSModel, "from_pretrained", staticmethod(fake_from_pretrained)):
        try:
            tts.load_model("some/model")
            raised = None
        except OSError as e:
            raised = e

    assert raised is not None, "expected the original OSError to propagate, not be swallowed"


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
