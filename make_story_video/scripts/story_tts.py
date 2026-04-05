import csv
import json
import os
import re
import shutil
import sys
from datetime import datetime
from typing import Dict, List

import imageio_ffmpeg
import numpy as np
import soundfile as sf
from pydub import AudioSegment
from pydub.silence import detect_leading_silence

# Configure ffmpeg path for pydub
ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
AudioSegment.converter = ffmpeg_exe

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_DIR = os.path.join(BASE_DIR, "input")
TOPICS_FILE = os.path.join(INPUT_DIR, "topics.txt")
STORY_DETAILS_FILE = os.path.join(INPUT_DIR, "story_details.json")
CURRENT_OUT_DIR_FILE = os.path.join(INPUT_DIR, "current_output_dir.txt")

if os.path.exists(CURRENT_OUT_DIR_FILE):
    with open(CURRENT_OUT_DIR_FILE, "r", encoding="utf-8") as f:
        OUTPUT_DIR = f.read().strip()
else:
    OUTPUT_DIR = os.path.join(BASE_DIR, "output")

TMP_AUDIO_DIR = os.path.join(OUTPUT_DIR, "tmp_story_tts")
DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), "vibe-voice", "data")
DATASET_CSV = os.path.join(DATA_DIR, "dataset_metadata.csv")

VIBE_VOICE_ROOT = os.path.join(os.path.dirname(BASE_DIR), "vibe-voice")
sys.path.insert(0, VIBE_VOICE_ROOT)
from predict import load_model_and_processor, predict  # noqa: E402

VOICES_DIR = os.path.join(VIBE_VOICE_ROOT, "VibeVoice", "demo", "voices", "streaming_model")

# Only Davis is prioritized
DAVIS_CANDIDATES = ["en-Davis_man.pt", "en-Frank_man.pt"]
CFG_SCALE = 1.6 # A bit more expressive for storytelling
TESTING_MODE = False
TESTING_MAX_TURNS = 12


def setup_directories():
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(TMP_AUDIO_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    if not os.path.exists(DATASET_CSV):
        with open(DATASET_CSV, mode="w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["wav_filename", "speaker", "text_display"])


def cleanup_tmp_audio():
    print("Cleaning up temporary audio files...")
    if os.path.exists(TMP_AUDIO_DIR):
        try:
            shutil.rmtree(TMP_AUDIO_DIR)
        except Exception as exc:
            print(f"Warning: Could not remove temporary directory {TMP_AUDIO_DIR}: {exc}")


def resolve_voice_path(candidates: List[str]) -> str:
    for voice_file in candidates:
        candidate_path = os.path.join(VOICES_DIR, voice_file)
        if os.path.exists(candidate_path):
            return candidate_path
    raise FileNotFoundError(
        f"No matching voice preset found in {VOICES_DIR} for candidates: {candidates}"
    )


def strip_kokoro_markup(text: str) -> str:
    # Converts: [word](+2) or [word](-1) -> word
    return re.sub(r"\[([^\]]+)\]\([+-]?\d+\)", r"\1", text)


def normalize_audio_np(audio_np):
    import torch

    if isinstance(audio_np, torch.Tensor):
        audio_np = audio_np.cpu().float().numpy()
    elif hasattr(audio_np, "dtype"):
        audio_np = audio_np.astype(np.float32)

    if hasattr(audio_np, "ndim") and audio_np.ndim > 1:
        audio_np = audio_np.squeeze()

    return audio_np


def should_skip_audio(item: Dict, idx: int) -> bool:
    item_type = item.get("type", "dialogue")
    speaker = item.get("speaker", "")
    text_tts = item.get("text_tts", "")

    if item_type == "heading" and (not text_tts.strip() or not speaker.strip()):
        return True
    return False


def process_story_tts(topic: str, model, processor, device: str):
    current_time_str = datetime.now().strftime("%Y%m%d_%H%M")
    safe_topic_name = "".join([c for c in topic if c.isalnum() or c == " "]).rstrip().replace(" ", "_")
    json_filename = os.path.join(OUTPUT_DIR, f"{safe_topic_name}_script.json")

    if not os.path.exists(json_filename):
        print(f"Warning: JSON file {json_filename} not found. Skipping topic '{topic}'.")
        return

    print(f"\n[{topic}] Starting VibeVoice STORY TTS Pipeline...")

    with open(json_filename, "r", encoding="utf-8") as f:
        try:
            script_data = json.load(f)
        except json.JSONDecodeError as exc:
            print(f"Error reading JSON {json_filename}: {exc}")
            return

    script = script_data.get("script", [])
    if not script:
        print(f"Warning: Valid script structure not found in {json_filename}.")
        return

    if os.path.exists(TMP_AUDIO_DIR):
        shutil.rmtree(TMP_AUDIO_DIR)
    os.makedirs(TMP_AUDIO_DIR, exist_ok=True)

    items = [item for item in script if item.get("type", "") in ["dialogue", "heading"]]
    if TESTING_MODE:
        items = items[:TESTING_MAX_TURNS]

    total_turns = len(items)
    subtitles = []
    current_time_ms = 0
    final_audio = AudioSegment.empty()

    print(f"Found {total_turns} turns to process for Davis.")

    for idx, item in enumerate(items, start=1):
        item_type = item.get("type", "dialogue")
        speaker = item.get("speaker", "Davis")
        text_display = item.get("text_display", item.get("text", ""))
        text_tts = item.get("text_tts", text_display)

        if should_skip_audio(item, idx):
            print(f"  [{idx}/{total_turns}] Skipping mute heading: '{text_display}'")
            subtitles.append(
                {
                    "idx": idx,
                    "type": item_type,
                    "speaker": speaker,
                    "text": text_display,
                    "text_tts": text_tts,
                    "start_time_sec": current_time_ms / 1000.0,
                    "end_time_sec": current_time_ms / 1000.0,
                    "duration_sec": 0,
                    "voice_used": "None",
                }
            )
            continue

        text_tts_clean = strip_kokoro_markup(text_tts)

        try:
            voice_path = resolve_voice_path(DAVIS_CANDIDATES)

            result = predict(
                text=text_tts_clean,
                model=model,
                processor=processor,
                device=device,
                voice_preset_path=voice_path,
                cfg_scale=CFG_SCALE,
                verbose=False,
            )

            audio_np = normalize_audio_np(result["audio"])
            sample_rate = result["sample_rate"]

            tmp_wav_path = os.path.join(TMP_AUDIO_DIR, f"tmp_turn_{idx}.wav")
            sf.write(tmp_wav_path, audio_np, sample_rate)
            turn_audio = AudioSegment.from_wav(tmp_wav_path)
            os.remove(tmp_wav_path)

        except Exception as exc:
            import traceback

            print(f"  [{idx}/{total_turns}] ERROR generating audio: {exc}")
            traceback.print_exc()
            continue

        trim_start = detect_leading_silence(turn_audio, silence_threshold=-45.0)
        trim_end = detect_leading_silence(turn_audio.reverse(), silence_threshold=-45.0)
        end_idx_audio = len(turn_audio) - trim_end

        if trim_start < end_idx_audio:
            turn_audio = turn_audio[trim_start:end_idx_audio]

        pause_duration = 400 if item_type == "heading" else 200 # slightly longer pauses for storytelling
        turn_audio += AudioSegment.silent(duration=pause_duration)

        speaker_name = "Davis"
        speaker_safe = "davis"
        speaker_topic_dir = os.path.join(DATA_DIR, speaker_safe, f"{current_time_str}_{safe_topic_name}")
        os.makedirs(speaker_topic_dir, exist_ok=True)

        base_filename = f"{speaker_safe}_{idx}"
        turn_wav_path = os.path.join(speaker_topic_dir, f"{base_filename}.wav")
        turn_audio.export(turn_wav_path, format="wav")

        turn_txt_path = os.path.join(speaker_topic_dir, f"{base_filename}.txt")
        with open(turn_txt_path, "w", encoding="utf-8") as text_file:
            text_file.write(text_display)

        try:
            with open(DATASET_CSV, mode="a", newline="", encoding="utf-8") as csv_file:
                writer = csv.writer(csv_file)
                relative_csv_path = (
                    f"data/{speaker_safe}/{current_time_str}_{safe_topic_name}/{base_filename}.wav"
                )
                writer.writerow([relative_csv_path, speaker_name, text_display])
        except Exception as exc:
            print(f"Warning: Could not write to CSV: {exc}")

        duration_ms = len(turn_audio)
        subtitles.append(
            {
                "idx": idx,
                "type": item_type,
                "speaker": speaker_name,
                "text": text_display,
                "text_tts": text_tts_clean,
                "start_time_sec": current_time_ms / 1000.0,
                "end_time_sec": (current_time_ms + duration_ms) / 1000.0,
                "duration_sec": duration_ms / 1000.0,
                "voice_used": os.path.basename(voice_path),
            }
        )

        final_audio += turn_audio
        current_time_ms += duration_ms

        print(
            f"  [{idx}/{total_turns}] Generated '{os.path.basename(voice_path)}' "
            f"for Davis ({duration_ms / 1000.0:.1f}s)"
        )

    if len(final_audio) > 0:
        print(f"[{topic}] Assembling and exporting {len(final_audio) / 1000.0:.2f}s audio...")
        mp3_filename = os.path.join(OUTPUT_DIR, f"{safe_topic_name}_podcast.mp3")
        final_audio.export(mp3_filename, format="mp3", bitrate="192k")
        print(f"[{topic}] MP3 exported to: {mp3_filename}")

        subs_filename = os.path.join(OUTPUT_DIR, f"{safe_topic_name}_subtitles.json")
        with open(subs_filename, "w", encoding="utf-8") as f:
            json.dump(subtitles, f, ensure_ascii=False, indent=2)
        print(f"[{topic}] Subtitles saved to: {subs_filename}")
    else:
        print(f"[{topic}] Error: No audio could be assembled.")


def main():
    setup_directories()

    if not os.path.exists(STORY_DETAILS_FILE):
        print("No story_details.json found. Run make_story_video.py first.")
        sys.exit(1)

    with open(STORY_DETAILS_FILE, "r", encoding="utf-8-sig") as f:
        story_details = json.load(f)
        
    topic = story_details.get("title", "Unknown Story")

    print("Initializing VibeVoice-Realtime-0.5B Pipeline... (this may take a moment)")
    model, processor, device = load_model_and_processor(
        model_path="microsoft/VibeVoice-Realtime-0.5B",
        device="auto",
        num_ddpm_steps=5,
    )

    process_story_tts(topic, model, processor, device)

    cleanup_tmp_audio()
    print("\nStorytelling TTS processed successfully via VibeVoice!")


if __name__ == "__main__":
    main()
