"""
story_tts.py — Story TTS using VibeVoice (Davis voice)

Reads the synopsis directly from story_details.json,
splits it into paragraphs, synthesises each paragraph with
VibeVoice and writes:
  - {safe_title}_podcast.mp3
  - {safe_title}_subtitles.json  (segment-level timestamps)
"""

import csv
import json
import os
import re
import shutil
import sys
from datetime import datetime
from typing import List

import imageio_ffmpeg
import numpy as np
import soundfile as sf
from pydub import AudioSegment
from pydub.silence import detect_leading_silence

# ---------------------------------------------------------------------------
# Configure ffmpeg path for pydub
# ---------------------------------------------------------------------------
ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
AudioSegment.converter = ffmpeg_exe

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR             = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_DIR            = os.path.join(BASE_DIR, "input")
STORY_DETAILS_FILE   = os.path.join(INPUT_DIR, "story_details.json")
CURRENT_OUT_DIR_FILE = os.path.join(INPUT_DIR, "current_output_dir.txt")

if os.path.exists(CURRENT_OUT_DIR_FILE):
    with open(CURRENT_OUT_DIR_FILE, "r", encoding="utf-8") as _f:
        OUTPUT_DIR = _f.read().strip()
else:
    OUTPUT_DIR = os.path.join(BASE_DIR, "output")

TMP_AUDIO_DIR = os.path.join(OUTPUT_DIR, "tmp_story_tts")

# ---------------------------------------------------------------------------
# VibeVoice
# ---------------------------------------------------------------------------
VIBE_VOICE_ROOT  = os.path.join(os.path.dirname(BASE_DIR), "vibe-voice")
sys.path.insert(0, VIBE_VOICE_ROOT)
from predict import load_model_and_processor, predict  # noqa: E402

VOICES_DIR       = os.path.join(VIBE_VOICE_ROOT, "VibeVoice", "demo", "voices", "streaming_model")
DAVIS_CANDIDATES = ["en-Davis_man.pt", "en-Frank_man.pt"]
CFG_SCALE        = 1.6   # slightly expressive for storytelling

# ---------------------------------------------------------------------------
# Dataset CSV (kept for training compatibility)
# ---------------------------------------------------------------------------
DATA_DIR    = os.path.join(os.path.dirname(BASE_DIR), "vibe-voice", "data")
DATASET_CSV = os.path.join(DATA_DIR, "dataset_metadata.csv")


# ===========================================================================
# Helpers
# ===========================================================================

def make_safe_name(text: str) -> str:
    return "".join(c for c in text if c.isalnum() or c == " ").rstrip().replace(" ", "_")


def setup_directories():
    os.makedirs(INPUT_DIR,    exist_ok=True)
    os.makedirs(OUTPUT_DIR,   exist_ok=True)
    os.makedirs(TMP_AUDIO_DIR, exist_ok=True)
    os.makedirs(DATA_DIR,     exist_ok=True)
    if not os.path.exists(DATASET_CSV):
        with open(DATASET_CSV, mode="w", newline="", encoding="utf-8") as csv_file:
            csv.writer(csv_file).writerow(["wav_filename", "speaker", "text_display"])


def cleanup_tmp():
    if os.path.exists(TMP_AUDIO_DIR):
        try:
            shutil.rmtree(TMP_AUDIO_DIR)
        except Exception as exc:
            print(f"Warning: could not remove {TMP_AUDIO_DIR}: {exc}")


def resolve_voice(candidates: List[str]) -> str:
    for name in candidates:
        path = os.path.join(VOICES_DIR, name)
        if os.path.exists(path):
            return path
    raise FileNotFoundError(
        f"No voice preset found in {VOICES_DIR} for candidates: {candidates}"
    )


def normalise_audio(audio_np):
    """Convert tensor / multi-dim array → float32 mono numpy array."""
    try:
        import torch
        if isinstance(audio_np, torch.Tensor):
            audio_np = audio_np.cpu().float().numpy()
    except ImportError:
        pass
    if hasattr(audio_np, "dtype"):
        audio_np = np.array(audio_np, dtype=np.float32)
    if audio_np.ndim > 1:
        audio_np = audio_np.squeeze()
    return audio_np


def split_synopsis_to_paragraphs(synopsis: str) -> List[str]:
    """
    Split story synopsis into natural reading chunks.

    Strategy:
      1. Split on blank lines (paragraph breaks).
      2. If a paragraph is very long (> MAX_CHARS) split further at sentence
         boundaries so TTS doesn't receive an enormous string.
    """
    MAX_CHARS = 400

    raw_paras = [p.strip() for p in re.split(r"\n\s*\n", synopsis)]
    raw_paras = [p for p in raw_paras if p]

    chunks: List[str] = []
    for para in raw_paras:
        if len(para) <= MAX_CHARS:
            chunks.append(para)
        else:
            # Split at sentence-ending punctuation
            sentences = re.split(r"(?<=[.!?])\s+", para)
            current = ""
            for sent in sentences:
                if not current:
                    current = sent
                elif len(current) + 1 + len(sent) <= MAX_CHARS:
                    current += " " + sent
                else:
                    chunks.append(current)
                    current = sent
            if current:
                chunks.append(current)

    return chunks


# ===========================================================================
# Core TTS pipeline
# ===========================================================================

def process_story_tts(title: str, synopsis: str, model, processor, device: str):
    safe_name = make_safe_name(title)
    chunks    = split_synopsis_to_paragraphs(synopsis)

    print(f"\n[TTS] '{title}' — {len(chunks)} paragraphs to synthesise")

    voice_path = resolve_voice(DAVIS_CANDIDATES)
    print(f"[TTS] Voice: {os.path.basename(voice_path)}")

    current_time_str = datetime.now().strftime("%Y%m%d_%H%M")
    speaker_safe     = "davis"
    speaker_dir      = os.path.join(DATA_DIR, speaker_safe, f"{current_time_str}_{safe_name}")
    os.makedirs(speaker_dir, exist_ok=True)

    # Re-create tmp dir fresh
    if os.path.exists(TMP_AUDIO_DIR):
        shutil.rmtree(TMP_AUDIO_DIR)
    os.makedirs(TMP_AUDIO_DIR, exist_ok=True)

    subtitles: list  = []
    final_audio      = AudioSegment.empty()
    current_ms       = 0

    for idx, chunk in enumerate(chunks, start=1):
        print(f"  [{idx}/{len(chunks)}] {chunk[:60]}{'...' if len(chunk) > 60 else ''}")

        try:
            result   = predict(
                text               = chunk,
                model              = model,
                processor          = processor,
                device             = device,
                voice_preset_path  = voice_path,
                cfg_scale          = CFG_SCALE,
                verbose            = False,
            )
            audio_np    = normalise_audio(result["audio"])
            sample_rate = result["sample_rate"]
        except Exception as exc:
            import traceback
            print(f"  [{idx}] ERROR: {exc}")
            traceback.print_exc()
            continue

        # Write temp WAV, load as AudioSegment
        tmp_wav = os.path.join(TMP_AUDIO_DIR, f"chunk_{idx}.wav")
        sf.write(tmp_wav, audio_np, sample_rate)
        seg = AudioSegment.from_wav(tmp_wav)
        os.remove(tmp_wav)

        # Trim leading / trailing silence
        t_start = detect_leading_silence(seg, silence_threshold=-45.0)
        t_end   = detect_leading_silence(seg.reverse(), silence_threshold=-45.0)
        end_idx = len(seg) - t_end
        if t_start < end_idx:
            seg = seg[t_start:end_idx]

        # Add short pause between paragraphs
        seg += AudioSegment.silent(duration=350)

        # Persist WAV for dataset
        base_fn   = f"{speaker_safe}_{idx}"
        wav_path  = os.path.join(speaker_dir, f"{base_fn}.wav")
        txt_path  = os.path.join(speaker_dir, f"{base_fn}.txt")
        seg.export(wav_path, format="wav")
        with open(txt_path, "w", encoding="utf-8") as tf:
            tf.write(chunk)

        # Append to CSV
        try:
            rel_csv = f"data/{speaker_safe}/{current_time_str}_{safe_name}/{base_fn}.wav"
            with open(DATASET_CSV, mode="a", newline="", encoding="utf-8") as cf:
                csv.writer(cf).writerow([rel_csv, "Davis", chunk])
        except Exception as exc:
            print(f"Warning: CSV write failed: {exc}")

        duration_ms = len(seg)
        subtitles.append({
            "idx":            idx,
            "type":           "dialogue",
            "speaker":        "Davis",
            "text":           chunk,
            "start_time_sec": current_ms / 1000.0,
            "end_time_sec":   (current_ms + duration_ms) / 1000.0,
            "duration_sec":   duration_ms / 1000.0,
            "voice_used":     os.path.basename(voice_path),
        })

        final_audio  += seg
        current_ms   += duration_ms
        print(f"         → {duration_ms / 1000.0:.1f}s  (total {current_ms / 1000.0:.1f}s)")

    if len(final_audio) == 0:
        print("[TTS] ERROR: no audio could be assembled — check VibeVoice installation.")
        sys.exit(1)

    total_sec = len(final_audio) / 1000.0
    print(f"\n[TTS] Assembling {total_sec:.1f}s audio …")

    mp3_path  = os.path.join(OUTPUT_DIR, f"{safe_name}_podcast.mp3")
    subs_path = os.path.join(OUTPUT_DIR, f"{safe_name}_subtitles.json")

    final_audio.export(mp3_path, format="mp3", bitrate="192k")
    print(f"[TTS] MP3  → {mp3_path}")

    with open(subs_path, "w", encoding="utf-8") as f:
        json.dump(subtitles, f, ensure_ascii=False, indent=2)
    print(f"[TTS] Subs → {subs_path}")


# ===========================================================================
# Entry point
# ===========================================================================

def main():
    setup_directories()

    if not os.path.exists(STORY_DETAILS_FILE):
        print("No story_details.json found. Run make_story_video.py first.")
        sys.exit(1)

    with open(STORY_DETAILS_FILE, "r", encoding="utf-8-sig") as f:
        story = json.load(f)

    title   = story.get("title",   "Unknown Story")
    synopsis = story.get("synopsis", "")

    if not synopsis.strip():
        print("ERROR: synopsis is empty in story_details.json")
        sys.exit(1)

    print(f"[TTS] Story  : {title}")
    print(f"[TTS] Length : {len(synopsis)} chars")
    print("Initialising VibeVoice-Realtime-0.5B … (first run may take a moment)")

    model, processor, device = load_model_and_processor(
        model_path     = "microsoft/VibeVoice-Realtime-0.5B",
        device         = "auto",
        num_ddpm_steps = 5,
    )

    process_story_tts(title, synopsis, model, processor, device)

    cleanup_tmp()
    print("\n[TTS] Done — all paragraphs synthesised via VibeVoice!\n")


if __name__ == "__main__":
    main()
