#!/bin/sh
# Small-Music on CPU. Slow, but it does not need the GPU stack.
set -eu
cd "$(dirname "$0")/.."
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt
python -m pip install -e .
echo "CPU venv ready. huggingface-cli login, then: python -m liora download --model small-music"
