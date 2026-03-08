# VibeVoice Podcast/Video Pipeline

Text-to-Speech and karaoke video generation using Microsoft's `VibeVoice-Realtime-0.5B`.

## What This Project Can Do

- Generate a long podcast script from a topic (multi-segment, validated JSON)
- Export script to JSON + PDF ebook
- Generate multi-speaker audio with VibeVoice
- Build timed subtitles JSON
- Render karaoke-style MP4 with waveform visualizer
- Generate YouTube title/description/tags metadata from the final script + timestamps

## Setup

1. Clone and install VibeVoice:

```bash
git clone https://github.com/microsoft/VibeVoice.git
cd VibeVoice
pip install -e ".[streamingtts]"
```

2. Install dependencies used by this repo:

```bash
pip install openai python-dotenv fpdf2 pydub imageio-ffmpeg faster-whisper moviepy soundfile scipy
```

3. Add `OPENROUTER_API_KEY` to `.env` (supported locations):

- `vibe-voice/.env`
- or workspace root `.env` (`D:\work\Personal_project\.env`)

## End-to-End Run (Recommended)

```bash
cd d:\work\Personal_project\vibe-voice
python make_youtube_video.py --topic "Talking About Your Week: Boring vs. Brilliant"
```

This runs:

1. `scripts/podcast_generator.py`
2. `scripts/vibevoice_tts.py`
3. `scripts/video_renderer.py`
4. YouTube metadata generation

Outputs are written to dynamic folder:

`output/<DD_MM_YYYY>/<SAFE_TOPIC_NAME>/`

and tracked by:

`input/current_output_dir.txt`

## Standalone Scripts

```bash
python scripts/podcast_generator.py
python scripts/vibevoice_tts.py
python scripts/video_renderer.py
```

Note: standalone scripts read topic from `input/topics.txt` and output directory from `input/current_output_dir.txt` when present.

## Core Files

- `make_youtube_video.py`: Orchestrates the whole pipeline
- `scripts/podcast_generator.py`: Multi-segment script generation + PDF export
- `scripts/vibevoice_tts.py`: VibeVoice TTS + subtitle timestamping + training data export
- `scripts/video_renderer.py`: Whisper alignment + karaoke + visualizer rendering
- `predict.py`: Reusable VibeVoice prediction API + CLI
- `predict_streaming.py`: Chunked streaming prediction for very long text
