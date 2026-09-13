#!/usr/bin/env bash
# Sets up a local Python virtual environment for the audiobook generator
# (Linux / macOS). Safe to re-run — reuses an existing .venv and skips
# work that's already done.
#
# Usage:
#   ./setup.sh          # CPU-only PyTorch (default, matches what's tested)
#   ./setup.sh --gpu    # CUDA-enabled PyTorch, for a supported NVIDIA GPU

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

VENV_DIR=".venv"
HF_HOME_DIR=".hf"
GPU=0
for arg in "$@"; do
    if [ "$arg" = "--gpu" ]; then
        GPU=1
    fi
done

PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ]; then
    for candidate in python3.12 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            PYTHON_BIN="$candidate"
            break
        fi
    done
fi
if [ -z "$PYTHON_BIN" ]; then
    echo "Error: no Python interpreter found. Install Python 3.10+ (3.12 recommended) and retry." >&2
    exit 1
fi

PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
echo "Using $PYTHON_BIN (Python $PY_VERSION)"
case "$PY_VERSION" in
    3.10|3.11|3.12|3.13) ;;
    *) echo "Warning: Python $PY_VERSION is untested (3.10+ required, 3.12 recommended). Continuing anyway." >&2 ;;
esac

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment at $VENV_DIR ..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
else
    echo "Reusing existing virtual environment at $VENV_DIR"
fi

PIP="$VENV_DIR/bin/pip"
"$PIP" install --upgrade pip >/dev/null

# torch/torchaudio need to land BEFORE the rest of requirements.txt: letting
# qwen-tts pull them in transitively (default index) grabs a CUDA-linked
# torchaudio build even on a CPU-only machine, which fails to import
# (missing libcudart) — installing them explicitly first, from the CPU
# wheel index unless --gpu was passed, avoids that.
if [ "$GPU" = "1" ]; then
    echo "Installing torch/torchaudio (CUDA build, --gpu requested) ..."
    "$PIP" install torch torchaudio
else
    echo "Installing torch/torchaudio (CPU-only build) ..."
    "$PIP" install --index-url https://download.pytorch.org/whl/cpu torch torchaudio
fi

echo "Installing remaining dependencies from requirements.txt ..."
"$PIP" install -r requirements.txt

mkdir -p "$HF_HOME_DIR"

echo
echo "Setup complete."
echo
echo "Next steps:"
echo "  source $VENV_DIR/bin/activate"
echo "  export OPENAI_API_KEY=sk-...          # your OpenAI API key"
echo "  export HF_HOME=\"\$(pwd)/$HF_HOME_DIR\"   # TTS model weights land here (~7GB, first run only)"
echo "  python src/audiobook/main.py --chapter 1"
echo
if [ "$GPU" != "1" ]; then
    echo "(Re-run this script with --gpu instead if you have a supported NVIDIA GPU.)"
fi
