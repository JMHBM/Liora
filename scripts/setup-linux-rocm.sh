#!/bin/sh
# Liora on Linux for an RX 6600M (gfx1032).
# ROCm does not always list this mobile GPU. The override below is the practical path.
set -eu
cd "$(dirname "$0")/.."

echo "Liora Linux setup — ROCm for gfx1032"
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip

# Install the ROCm torch wheel that matches your ROCm install (6.3 shown).
# Do this BEFORE stable-audio-3 so the CUDA index in that project cannot replace it.
echo "Installing a ROCm PyTorch wheel. Adjust the index if your ROCm is not 6.3."
python -m pip install torch==2.7.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/rocm6.3 \
  || echo "Pinned 2.7.1 ROCm wheel missing — install the closest ROCm torch manually, then continue."

python -m pip install -r requirements.txt
python -m pip install -e .

cat <<'EOF'

Add this to the shell that launches Liora (gfx1032 is not always a first-class target):

  export HSA_OVERRIDE_GFX_VERSION=10.3.0
  export PYTORCH_ROCM_ARCH=gfx1030

Then:

  huggingface-cli login
  python -m liora download --model small-music
  python -m liora doctor
  python -m liora serve

Medium wants flash-attention-style kernels for SAME-L. If doctor says flash-attn is
missing, generate with small-music. Forcing Medium is:

  python -m liora generate -p "..." --model medium --duration 30

OOM falls back to Small-Music automatically.
EOF
