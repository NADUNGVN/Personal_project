# VibeVoice-Realtime-0.5B Prediction

Text-to-Speech generation using Microsoft's [VibeVoice-Realtime-0.5B](https://huggingface.co/microsoft/VibeVoice-Realtime-0.5B).

## Setup

### 1. Clone & Install VibeVoice

```bash
git clone https://github.com/microsoft/VibeVoice.git
cd VibeVoice
pip install -e ".[streamingtts]"

# Optional (recommended for CUDA): install Flash Attention for better performance
pip install flash-attn --no-build-isolation
```

### 2. First Run (Auto-downloads model from HuggingFace)

```bash
cd d:\vibe-voice
python predict.py --text "Hello, this is a test." --voice_file VibeVoice/demo/voices/streaming_model/Wayne.pt
```

## Usage

### Basic Text-to-Speech

```bash
# Simple text
python predict.py --text "Hello world, this is VibeVoice!" --voice_file path/to/voice.pt

# From a text file
python predict.py --text_file sample.txt --voice_file path/to/voice.pt

# Custom output path
python predict.py --text "Hello" --voice_file voice.pt --output my_output.wav
```

### Using Voice Presets

```bash
# If voices are in the expected directory structure, use speaker names
python predict.py --text "Hello" --speaker_name Wayne

# Or specify a .pt voice file directly
python predict.py --text "Hello" --voice_file VibeVoice/demo/voices/streaming_model/Carter.pt

# List available voices
python predict.py --list_voices
```

### Streaming Mode (Long Text)

```bash
# Process long text in chunks
python predict_streaming.py --text_file long_story.txt --voice_file voice.pt

# Adjust chunk size
python predict_streaming.py --text "Very long text..." --voice_file voice.pt --chunk_size 300

# Save individual chunks too
python predict_streaming.py --text_file story.txt --voice_file voice.pt --save_chunks
```

### Generation Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--cfg_scale` | 1.5 | Classifier-Free Guidance (1.0-3.0). Higher = more voice prompt adherence |
| `--ddpm_steps` | 5 | Denoising steps. More = better quality, slower |
| `--device` | auto | `auto`, `cuda`, `mps`, `cpu` |

### Python API

```python
from predict import load_model_and_processor, predict, save_audio

# Load once
model, processor, device = load_model_and_processor()

# Generate many times
result = predict(
    text="Hello world!",
    model=model, processor=processor, device=device,
    voice_preset_path="path/to/voice.pt",
)

save_audio(result["audio"], "output.wav")
print(f"Duration: {result['duration_seconds']:.1f}s, RTF: {result['rtf']:.3f}x")
```

## Files

| File | Description |
|------|-------------|
| `predict.py` | Main prediction script (CLI + importable module) |
| `predict_streaming.py` | Streaming prediction for long texts |
| `example_usage.py` | Python API usage example |
| `sample.txt` | Sample text for testing |

## Requirements

- Python ≥ 3.9
- PyTorch with CUDA (recommended) / MPS / CPU
- transformers == 4.51.3
- vibevoice package (from GitHub)
- GPU with ≥6GB VRAM recommended (model is 0.5B parameters)
