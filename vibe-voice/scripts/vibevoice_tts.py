import os
import sys
import re
import json
import csv
import shutil
import numpy as np
import soundfile as sf
from datetime import datetime
from typing import Dict, List
import imageio_ffmpeg
from pydub import AudioSegment
from pydub.silence import detect_leading_silence

# Explicitly tell pydub where to find ffmpeg via imageio_ffmpeg
ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
AudioSegment.converter = ffmpeg_exe

# ================= GLOBAL CONFIGURATION =================
BASE_DIR = r"d:\work\Personal_project\vibe-voice"
INPUT_DIR = os.path.join(BASE_DIR, "input")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = r"d:\work\Personal_project\data"
TMP_AUDIO_DIR = os.path.join(BASE_DIR, "tmp_audio")
TOPICS_FILE = os.path.join(INPUT_DIR, "topics.txt")
DATASET_CSV = os.path.join(DATA_DIR, "dataset_metadata.csv")
# ========================================================

# Import VibeVoice predict API
sys.path.insert(0, BASE_DIR)
from predict import load_model_and_processor, predict

# ================= VOICE CONFIGURATION =================
VOICES_DIR = os.path.join(BASE_DIR, "VibeVoice", "demo", "voices", "streaming_model")
VOICE_MAP = {
    "Davis": os.path.join(VOICES_DIR, "en-Davis_man.pt"),   # Davis Male Voice
    "Emma": os.path.join(VOICES_DIR, "en-Emma_woman.pt"), # Emma Female Voice
}
DEFAULT_VOICE = os.path.join(VOICES_DIR, "en-Davis_man.pt")
CFG_SCALE = 1.5  # Classifier-Free Guidance (1.0-3.0)

TESTING_MODE = False              # Đặt = True để chỉ render vài câu xem trước!
TESTING_MAX_TURNS = 10            # Số câu thoại tối đa khi test
# =======================================================


def setup_directories():
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(TMP_AUDIO_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    # Initialize the Training Data CSV if it doesn't exist yet
    if not os.path.exists(DATASET_CSV):
        with open(DATASET_CSV, mode='w', newline='', encoding='utf-8') as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(['wav_filename', 'speaker', 'text_display'])


def cleanup_tmp_audio():
    """Removes the tmp_audio directory and all its contents"""
    print("Cleaning up temporary audio files...")
    if os.path.exists(TMP_AUDIO_DIR):
        try:
            shutil.rmtree(TMP_AUDIO_DIR)
        except Exception as e:
            print(f"Warning: Could not remove temporary directory {TMP_AUDIO_DIR}: {e}")


def get_voice_for_speaker(speaker: str) -> str:
    """Return the assigned voice preset path for a speaker based on VOICE_MAP."""
    # Try an exact match first
    if speaker in VOICE_MAP:
        return VOICE_MAP[speaker]

    # Try loosely matching by checking if name is simply contained (e.g. Host Alex)
    for key, voice_path in VOICE_MAP.items():
        if key.lower() in speaker.lower():
            return voice_path

    return DEFAULT_VOICE


def strip_kokoro_markup(text: str) -> str:
    """Strip Kokoro-specific markup like [word](+2) or [word](-1) from text.
    Returns clean text that VibeVoice can read naturally."""
    # Pattern: [word](+N) or [word](-N) → word
    cleaned = re.sub(r'\[([^\]]+)\]\([+-]?\d+\)', r'\1', text)
    return cleaned


def process_topic_tts(topic: str, model, processor, device):
    # Lấy thông số timestamp gắn với cả quá trình xử lý topic
    current_time_str = datetime.now().strftime("%Y%m%d_%H%M")
    safe_topic_name = "".join([c for c in topic if c.isalnum() or c==' ']).rstrip().replace(" ", "_")
    json_filename = os.path.join(OUTPUT_DIR, f"{safe_topic_name}_script.json")

    if not os.path.exists(json_filename):
        print(f"Warning: JSON file {json_filename} not found. Skipping topic '{topic}'.")
        return

    print(f"\n[{topic}] Starting VibeVoice TTS Pipeline...")

    with open(json_filename, "r", encoding="utf-8") as f:
        try:
            script_data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error reading JSON {json_filename}: {e}")
            return

    script = script_data.get("script", [])
    if not script:
        print(f"Warning: Valid script structure not found in {json_filename}.")
        return

    # Clear and recreate tmp_audio to avoid dirty state between topics
    if os.path.exists(TMP_AUDIO_DIR):
        shutil.rmtree(TMP_AUDIO_DIR)
    os.makedirs(TMP_AUDIO_DIR, exist_ok=True)

    dialogues = [item for item in script if item.get("type", "") == "dialogue"]
    total_turns = len(dialogues)

    subtitles = []
    current_time_ms = 0
    final_audio = AudioSegment.empty()  # Master audio track

    if TESTING_MODE:
        dialogues = dialogues[:TESTING_MAX_TURNS]
        total_turns = len(dialogues)
        print(f"[TESTING MODE] Processing only {total_turns} dialogue turns (out of {len([item for item in script if item.get('type', '') == 'dialogue'])}).")
    else:
        print(f"Found {total_turns} dialogue turns to process.")

    for idx, item in enumerate(dialogues, start=1):
        speaker = item.get("speaker", "Unknown")
        # Phân tách 2 luồng text dựa trên JSON
        text_display = item.get("text_display", item.get("text", ""))
        text_tts = item.get("text_tts", text_display)
        voice_path = get_voice_for_speaker(speaker)

        # Strip any leftover Kokoro markup from text_tts
        text_tts_clean = strip_kokoro_markup(text_tts)

        # 1. GENERATE WAV VIA VIBEVOICE
        try:
            result = predict(
                text=text_tts_clean,
                model=model,
                processor=processor,
                device=device,
                voice_preset_path=voice_path,
                cfg_scale=CFG_SCALE,
                verbose=False,
            )
            audio_np = result["audio"]
            sample_rate = result["sample_rate"]

            # VibeVoice may return bfloat16 or torch tensor — convert to float32 numpy
            import torch
            if isinstance(audio_np, torch.Tensor):
                audio_np = audio_np.cpu().float().numpy()
            elif hasattr(audio_np, 'dtype'):
                audio_np = audio_np.astype(np.float32)
            
            # Squeeze multi-dimensional arrays (e.g., [1, N] -> [N])
            if audio_np.ndim > 1:
                audio_np = audio_np.squeeze()

            # Save to tmp WAV and load via pydub for manipulation
            tmp_wav_path = os.path.join(TMP_AUDIO_DIR, f"tmp_turn_{idx}.wav")
            sf.write(tmp_wav_path, audio_np, sample_rate)
            turn_audio = AudioSegment.from_wav(tmp_wav_path)
            os.remove(tmp_wav_path)

        except Exception as e:
            import traceback
            print(f"  [{idx}/{total_turns}] ERROR generating audio: {e}")
            traceback.print_exc()
            continue

        print(f"  [{idx}/{total_turns}] Generated VibeVoice '{os.path.basename(voice_path)}' for speaker: {speaker} ({result['duration_seconds']:.1f}s)")

        # --- CẮT BỎ KHOẢNG LẶNG ĐẦU VÀ CUỐI ---
        trim_start = detect_leading_silence(turn_audio, silence_threshold=-45.0)
        trim_end = detect_leading_silence(turn_audio.reverse(), silence_threshold=-45.0)
        end_idx_audio = len(turn_audio) - trim_end

        # Chỉ áp dụng cắt xén nếu file audio có tiếng thực sự
        if trim_start < end_idx_audio:
            turn_audio = turn_audio[trim_start:end_idx_audio]

        # Thêm 1 khoảng thở ổn định 100ms vào cuối câu
        turn_audio += AudioSegment.silent(duration=100)

        # --- LƯU TRỮ AUDIO (VÀ TEXT DỮ LIỆU HUẤN LUYỆN) RIÊNG LẺ ---
        speaker_topic_dir = os.path.join(DATA_DIR, speaker, f"{current_time_str}_{safe_topic_name}")
        os.makedirs(speaker_topic_dir, exist_ok=True)

        base_filename = f"{speaker.lower()}_{idx}"

        # 1. Lưu file âm thanh riêng lẻ (.wav) vào thư mục chung của topic
        turn_wav_path = os.path.join(speaker_topic_dir, f"{base_filename}.wav")
        turn_audio.export(turn_wav_path, format="wav")

        # 2. Xây dữ liệu Train: Xuất transcript sạch (.txt)
        turn_txt_path = os.path.join(speaker_topic_dir, f"{base_filename}.txt")
        with open(turn_txt_path, "w", encoding="utf-8") as text_file:
            text_file.write(text_display)

        # 3. Ghi vào file CSV tổng hợp
        try:
            with open(DATASET_CSV, mode='a', newline='', encoding='utf-8') as csv_file:
                writer = csv.writer(csv_file)
                relative_csv_path = f"data/{speaker}/{current_time_str}_{safe_topic_name}/{base_filename}.wav"
                writer.writerow([relative_csv_path, speaker, text_display])
        except Exception as e:
            print(f"Warning: Could not write to CSV: {e}")

        # 2. TIMESTAMPING AND SUBTITLES
        duration_ms = len(turn_audio)

        subtitles.append({
            "idx": idx,
            "speaker": speaker,
            "text": text_display,
            "text_tts": text_tts_clean,
            "start_time_sec": current_time_ms / 1000.0,
            "end_time_sec": (current_time_ms + duration_ms) / 1000.0,
            "duration_sec": duration_ms / 1000.0,
            "voice_used": os.path.basename(voice_path)
        })

        # 3. ASSEMBLY
        final_audio += turn_audio
        current_time_ms += duration_ms

    # ================= OUTPUT FINAL ASSEMBLY =================
    if len(final_audio) > 0:
        print(f"[{topic}] Assembling and exporting {len(final_audio)/1000.0:.2f} seconds of audio...")
        mp3_filename = os.path.join(OUTPUT_DIR, f"{safe_topic_name}_podcast.mp3")

        final_audio.export(mp3_filename, format="mp3", bitrate="192k")
        print(f"[{topic}] MP3 successfully exported to: {mp3_filename}")

        # Save subtitles.json
        subs_filename = os.path.join(OUTPUT_DIR, f"{safe_topic_name}_subtitles.json")
        with open(subs_filename, "w", encoding="utf-8") as f:
            json.dump(subtitles, f, ensure_ascii=False, indent=2)
        print(f"[{topic}] Subtitles and Timestamps saved to: {subs_filename}")
    else:
        print(f"[{topic}] Error: No audio could be assembled.")


def main():
    setup_directories()

    with open(TOPICS_FILE, "r", encoding="utf-8-sig") as f:
        topics = [line.strip() for line in f.readlines() if line.strip()]

    if not topics:
        print("No topics found in input/topics.txt.")
        sys.exit(0)

    print("Initializing VibeVoice-Realtime-0.5B Pipeline... (this may take a moment)")
    model, processor, device = load_model_and_processor(
        model_path="microsoft/VibeVoice-Realtime-0.5B",
        device="auto",
        num_ddpm_steps=5,
    )

    for topic in topics:
        process_topic_tts(topic, model, processor, device)

    cleanup_tmp_audio()
    print("\nAll topics processed successfully via VibeVoice TTS!")


if __name__ == "__main__":
    main()
