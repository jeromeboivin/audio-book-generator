#Requires -Version 5.0
<#
.SYNOPSIS
    Sets up a local Python virtual environment for the audiobook generator (Windows).
    Safe to re-run -- reuses an existing .venv and skips work that's already done.

.PARAMETER Gpu
    Install the CUDA-enabled build of PyTorch instead of the default CPU-only one
    (only useful if you have a supported NVIDIA GPU).

.EXAMPLE
    .\setup.ps1
.EXAMPLE
    .\setup.ps1 -Gpu
#>
param(
    [switch]$Gpu
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$VenvDir = ".venv"
$HfHomeDir = ".hf"

function Find-Python {
    foreach ($candidate in @("python3.12", "python", "py")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) { return $candidate }
    }
    return $null
}

$PythonBin = Find-Python
if (-not $PythonBin) {
    Write-Error "No Python interpreter found. Install Python 3.10+ (3.12 recommended) and retry."
    exit 1
}

$PyVersion = & $PythonBin -c "import sys; print('%d.%d' % sys.version_info[:2])"
Write-Host "Using $PythonBin (Python $PyVersion)"
if ($PyVersion -notin @("3.10", "3.11", "3.12", "3.13")) {
    Write-Warning "Python $PyVersion is untested (3.10+ required, 3.12 recommended). Continuing anyway."
}

if (-not (Test-Path $VenvDir)) {
    Write-Host "Creating virtual environment at $VenvDir ..."
    & $PythonBin -m venv $VenvDir
} else {
    Write-Host "Reusing existing virtual environment at $VenvDir"
}

$Pip = Join-Path $VenvDir "Scripts\pip.exe"
& $Pip install --upgrade pip | Out-Null

# torch/torchaudio need to land BEFORE the rest of requirements.txt: letting
# qwen-tts pull them in transitively (default index) grabs a CUDA-linked
# torchaudio build even on a CPU-only machine, which fails to import
# (missing libcudart) -- installing them explicitly first, from the CPU
# wheel index unless -Gpu was passed, avoids that.
if ($Gpu) {
    Write-Host "Installing torch/torchaudio (CUDA build, -Gpu requested) ..."
    & $Pip install torch torchaudio
} else {
    Write-Host "Installing torch/torchaudio (CPU-only build) ..."
    & $Pip install --index-url https://download.pytorch.org/whl/cpu torch torchaudio
}

Write-Host "Installing remaining dependencies from requirements.txt ..."
& $Pip install -r requirements.txt

New-Item -ItemType Directory -Force -Path $HfHomeDir | Out-Null

Write-Host ""
Write-Host "Setup complete."
Write-Host ""
Write-Host "Next steps:"
Write-Host "  $VenvDir\Scripts\Activate.ps1"
Write-Host "  `$env:OPENAI_API_KEY = 'sk-...'                   # your OpenAI API key"
Write-Host "  `$env:HF_HOME = (Resolve-Path $HfHomeDir).Path      # TTS model weights land here (~7GB, first run only)"
Write-Host "  python src/audiobook/main.py --chapter 1"
Write-Host ""
if (-not $Gpu) {
    Write-Host "(Re-run this script with -Gpu instead if you have a supported NVIDIA GPU.)"
}
Write-Host ""
Write-Host "If running this script is blocked by execution policy, use:"
Write-Host "  powershell -ExecutionPolicy Bypass -File setup.ps1"
