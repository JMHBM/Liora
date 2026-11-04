# Liora on Windows for an RX 6600M (gfx1032) via ZLUDA.
# Run from an elevated PowerShell if you want the venv outside the repo:
#   Set-ExecutionPolicy -Scope Process Bypass
#   .\scripts\setup-windows.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "Liora Windows setup — ZLUDA path for RDNA2"
Write-Host "Python 3.10 or 3.11 is the safe range for the pinned torch in stable-audio-3."

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  throw "Python is not on PATH."
}

python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip

Write-Host ""
Write-Host "1. Install a CUDA 12.6 PyTorch build that matches stable-audio-3 (torch==2.7.1 if that wheel exists):"
Write-Host "   .\.venv\Scripts\python.exe -m pip install torch==2.7.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu126"
Write-Host "   If 2.7.1 is not on that index, install the newest cu126 pair and keep stable-audio-3's pin in mind."
Write-Host ""
Write-Host "2. Install ZLUDA (v3+) and always launch through it so AMD sees CUDA calls:"
Write-Host "   zluda -- .\.venv\Scripts\python.exe -m liora doctor"
Write-Host "   The device name should mention the Radeon, not Microsoft Basic Render."
Write-Host ""
Write-Host "3. flash-attn wheels are NVIDIA-only. If `import flash_attn` fails, stay on small-music."
Write-Host "   Medium is an explicit opt-in: zluda -- python -m liora generate -p `"...`" --model medium"
Write-Host ""

& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -m pip install -e .

Write-Host ""
Write-Host "Next, after `huggingface-cli login` and accepting the model license:"
Write-Host "  zluda -- .\.venv\Scripts\python.exe -m liora download --model small-music"
Write-Host "  zluda -- .\.venv\Scripts\python.exe -m liora doctor"
Write-Host "  zluda -- .\.venv\Scripts\python.exe -m liora serve"
