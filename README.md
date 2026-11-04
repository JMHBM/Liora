# Liora

Offline instrumental studio for [Stable Audio 3](https://github.com/Stability-AI/stable-audio-3).
Built for a MinisForum HX99G: Ryzen 9 6900HX and a Radeon RX 6600M (8 GB, gfx1032).

## Windows installer

`LioraSetup.exe` is the installable app. It does not contain the multi-gigabyte weights.
During setup it downloads what the machine is missing:

| Step | What it fetches |
| --- | --- |
| Python 3.11 | python.org, into the install folder, not your system PATH |
| PyTorch CUDA 12.6 | the build ZLUDA translates |
| Liora + stable-audio-3 | this app and Stability’s library |
| ZLUDA (checked by default) | latest Windows zip from the lshqqytiger fork |
| Small-Music (optional) | gated Hugging Face weights, needs a token |

Default folder is `%LOCALAPPDATA%\Liora`. A desktop shortcut and a Start menu shortcut launch the studio.
Uninstall is listed in Apps & Features.

You still need the AMD Adrenalin driver already installed. ZLUDA also needs the AMD HIP SDK, which is AMD’s own installer and is not silent-bundled here. After setup, run **Liora Doctor** in the install folder. If it reports a Radeon, you are on the GPU path.

Accept the Stability community license and the Gemma terms on the Small-Music model card before the weight download. The token box is only used for that download and the file is deleted when the download starts.

## What the studio looks like

The local studio (`python -m liora serve`, opened by the shortcut) is a dark synthwave panel: magenta actions, cyan labels, grid horizon. The same face is the browser studio.

After the weights are on disk, generation does not use the network. Outputs are yours.
The app does not try to sing — prompts are instrumental, and the negative prompt keeps vocals out.

Liora’s code is MIT. The weights are not. Read [NOTICE.md](NOTICE.md) before a commercial project.

## Architecture

```
prompt + duration + seed
        │
        ▼
StableAudioEngine            ← this repo, swappable
        │  device policy, chunked decode, OOM fallback, LoRA, inpaint
        ▼
stable_audio_3.StableAudioModel
        │
        ├─ frozen T5Gemma          text → conditioning
        ├─ Diffusion Transformer   8-step sample in 256-d SAME latents
        └─ SAME decoder            latents → 44.1 kHz stereo
                │
                ▼
         WAV  +  local library (~/.liora/takes)
```

SAME downsamples stereo 44.1 kHz by 4096×. Length is a first-class input, not a crop of a fixed window.
Post-trained checkpoints are the adversarial models: **8 steps, CFG 1**. Turning steps up past 8 does not
buy much. Base checkpoints (for LoRA training) want ~50 steps; those weights are in Stability’s extra collection.

Two model ids:

| Id | What it is | Max | Peak VRAM (H200) |
| --- | --- | --- | --- |
| `small-music` | 433M DiT + SAME-S | 120 s | 1.7–2.4 GB |
| `medium` | 1.4B DiT + SAME-L | 380 s (6 min 20 s) | 6.49 GB unchunked, ~5.14 GB chunked at 120 s |

Large (2.7B) is API-only. Liora does not call it.

### Why this shape

The official inference stack is Python. ZLUDA and ROCm live in that process. A Rust/Tauri shell would still
have to spawn it, and flash-attn failures would be harder to see. Liora is the process:

- `python -m liora doctor` — backend, VRAM, whether Medium is worth trying
- `python -m liora generate` — one WAV
- `python -m liora serve` — local studio at `http://127.0.0.1:8765`

The engine is one class (`liora/engine.py`). Swap it later for an ONNX runtime if a real export appears.
There isn’t one in the official repo today, so DirectML is documented as unsupported instead of half-wired.

## Presets

[`presets/presets.json`](presets/presets.json) is the starter pack (cinematic, ambient, electronic, jazz,
lo-fi, acoustic, world, orchestral, rock, folk). Edit it. The studio and `python -m liora presets` both read it.

```bash
python -m liora generate --preset cin-amber-dawn -o dawn.wav
```

## Setup

Python 3.10 or 3.11. Create the venv from the scripts, then accept both gates on Hugging Face:

- [stabilityai/stable-audio-3-small-music](https://huggingface.co/stabilityai/stable-audio-3-small-music)
- [stabilityai/stable-audio-3-medium](https://huggingface.co/stabilityai/stable-audio-3-medium)

T5Gemma sits inside those checkpoints, so the Gemma terms come with them. Then `huggingface-cli login`.

### Windows — ZLUDA (RX 6600M)

```powershell
.\scripts\setup-windows.ps1
.\.venv\Scripts\python.exe -m pip install torch==2.7.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu126
.\.venv\Scripts\python.exe -m pip install --no-deps https://github.com/Stability-AI/stable-audio-3/archive/refs/heads/main.zip
.\.venv\Scripts\python.exe -m pip install "einops>=0.8.2" "einops-exts>=0.0.4" "safetensors>=0.7.0" "transformers>=5.8.0" "numpy>=2.2.6" "packaging>=26.0"
```

Launch **through ZLUDA** so CUDA calls hit the 6600M:

```powershell
zluda -- .\.venv\Scripts\python.exe -m liora doctor
zluda -- .\.venv\Scripts\python.exe -m liora download --model small-music
zluda -- .\.venv\Scripts\python.exe -m liora serve
```

`doctor` should print a Radeon device name and `backend: zluda`. If it says CPU, ZLUDA is not in front of the process.

flash-attn wheels are built for NVIDIA. When that import fails, Liora recommends Small-Music. You can still pass
`--model medium`. If SAME-L cannot allocate, the engine empties the cache and reruns the take on Small-Music
(capped at 120 s).

### Linux — ROCm

```bash
sh scripts/setup-linux-rocm.sh
export HSA_OVERRIDE_GFX_VERSION=10.3.0
export PYTORCH_ROCM_ARCH=gfx1030
python -m liora doctor
```

gfx1032 is not always on the official ROCm target list. The override reports it as gfx1030, which is the
usual way RDNA2 cards that “almost” match get a kernel image. If `rocminfo` itself cannot see the GPU,
the override will not invent a device — fix ROCm before debugging Liora.

Install `stable-audio-3` from git **after** the ROCm torch wheel, and do not let its CUDA index replace torch.

### CPU

```bash
sh scripts/setup-cpu.sh
python -m liora download --model small-music
python -m liora generate -p "soft felt piano, 72 BPM, key of F major, instrumental" --duration 20 -o sketch.wav
```

Small-Music is the only CPU target. Medium is refused unless a GPU with enough memory is visible.

## First generate

```bash
python -m liora doctor
python -m liora download --model small-music
python -m liora generate \
  -p "Dusty lo-fi instrumental, rhodes, swung drums, 84 BPM, key of C minor" \
  --duration 30 --seed 7 -o take.wav
```

Score mode is just duration: pass the length you need, up to the model max.

```bash
# audio-to-audio
python -m liora generate -p "bossa nova bassline, instrumental" \
  --init-audio take.wav --init-noise 0.85 --duration 30 -o restyle.wav

# replace a region
python -m liora generate -p "soft brush fill, no vocals" \
  --inpaint-audio take.wav --inpaint-start 8 --inpaint-end 12 -o fixed.wav

# continue past the end of a 10 s file
python -m liora generate -p "same motif, quieter outro" \
  --inpaint-audio take.wav --inpaint-start 10 --inpaint-end 18 --duration 18 -o longer.wav

# LoRA, if you have a .safetensors adapter trained on a base checkpoint
python -m liora generate -p "..." --lora path/to/style.safetensors --lora-strength 0.8 -o styled.wav
```

Batch from the shell is a loop with `--seed`. The engine keeps batch size at 1 on Medium so the 8 GB card
is not asked for two latents at once.

## Performance on 8 GB

Treat Stability’s table as a **memory budget**, not a timer. Their numbers are an H200. A 6600M will not
match them. What you can count on:

- Small-Music at any length up to 2 minutes fits easily (about 2.4 GB at 120 s).
- Medium only with `chunked_decode=True` (forced), fp16, and batch 1.
- Peak still climbs toward 6 GB before activations. Quit the browser first. If the card is already half full, stay on Small.
- Long Medium jobs (several minutes) are the risky ones. Render a 20 s proof before a 6 minute score.
- There is no practical INT8/INT4 path in the official runtime. Don’t bolt bitsandbytes onto the DiT and hope the SAME decoder agrees.
- fp16 is the speed/memory win that exists today. If a ROCm build NaNs, rerun with the engine dtype set to float32 on Small only.
- CPU Small is the floor. It will be minutes, not seconds, for a half-minute piece. That’s still a result.

`doctor` is the gate. Recommended model is what `generate` uses when you pass `--model auto`.

## Project layout

```
liora/engine.py      model load, kwargs filtering, OOM fallback
liora/devices.py     ROCm / ZLUDA / CUDA / CPU
liora/cli.py         doctor, download, generate, serve
liora/server.py      localhost studio
liora/web/studio.html
presets/presets.json
scripts/             setup-windows.ps1, setup-linux-rocm.sh, setup-cpu.sh
```

## Tests

```bash
PYTHONPATH=. python -m unittest tests.test_devices tests.test_audio
```

Those tests do not download weights.
