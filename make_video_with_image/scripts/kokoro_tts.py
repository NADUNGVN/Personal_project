import os
import sys
import json
import csv
import soundfile as sf
import shutil
from datetime import datetime
from typing import Dict, List
import imageio_ffmpeg
from pydub import AudioSegment
from pydub.silence import detect_leading_silence

# Explicitly tell pydub where to find ffmpeg via imageio_ffmpeg
ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
AudioSegment.converter = ffmpeg_exe

# ================= GLOBAL CONFIGURATION# Define directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_DIR = os.path.join(BASE_DIR, "input")
DATA_DIR = r"d:\work\Personal_project\data" # Keep DATA_DIR as it's used later

# Read dynamic output directory if it exists, otherwise default to "output"
CURRENT_OUT_DIR_FILE = os.path.join(INPUT_DIR, "current_output_dir.txt")
if os.path.exists(CURRENT_OUT_DIR_FILE):
    with open(CURRENT_OUT_DIR_FILE, "r", encoding="utf-8") as f:
        OUTPUT_DIR = f.read().strip()
else:
    OUTPUT_DIR = os.path.join(BASE_DIR, "output")

TMP_AUDIO_DIR = os.path.join(OUTPUT_DIR, "tmp_kokoro") # Changed to be relative to OUTPUT_DIR
CURRENT_PDF_FILE = os.path.join(INPUT_DIR, "current_pdf.txt")
TOPICS_FILE = os.path.join(INPUT_DIR, "topics.txt")
DATASET_CSV = os.path.join(DATA_DIR, "dataset_metadata.csv")
# ========================================================

from kokoro import KPipeline

# ================= VOICE CONFIGURATION =================
VOICE_MAP = {
    "Alex": "am_puck",      # Host 1
    "Sarah": "af_bella",    # Host 2
    "Michael": "am_michael",# Roleplay Male 1
    "Nicole": "af_nicole",  # Roleplay Female 1
    "Adam": "am_adam",      # Roleplay Male 2
    "Sky": "af_sky"         # Roleplay Female 2
}
SPEED_MAP = {
    "Alex": 1.0,
    "Sarah": 0.85,
    "Michael": 1.0,
    "Nicole": 1.0,
    "Adam": 1.0,
    "Sky": 1.0
}
# Fallback voice if speaker not in map (should not happen with new prompt constraints)
DEFAULT_VOICE = "af_sky"
LANG_CODE = 'a' # 'a' for American English
# =======================================================
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
            writer.writerow(['wav_filename', 'speaker', 'text_display', 'phonemes'])

def cleanup_tmp_audio():
    """Removes the tmp_audio directory and all its contents"""
    print("Cleaning up temporary audio files...")
    if os.path.exists(TMP_AUDIO_DIR):
        try:
            shutil.rmtree(TMP_AUDIO_DIR)
        except Exception as e:
            print(f"Warning: Could not remove temporary directory {TMP_AUDIO_DIR}: {e}")

def get_voice_for_speaker(speaker: str) -> str:
    """Return the assigned voice for a speaker based on VOICE_MAP."""
    # Try an exact match first
    if speaker in VOICE_MAP:
        return VOICE_MAP[speaker]
    
    # Try loosely matching by checking if name is simply contained (e.g. Host Alex)
    for key, voice in VOICE_MAP.items():
        if key.lower() in speaker.lower():
            return voice
            
    return DEFAULT_VOICE

def process_topic_tts(topic: str, pipeline: KPipeline):
    # Lấy thông số timestamp gắn với cả quá trình xử lý topic
    current_time_str = datetime.now().strftime("%Y%m%d_%H%M")
    safe_topic_name = "".join([c for c in topic if c.isalnum() or c==' ']).rstrip().replace(" ", "_")
    json_filename = os.path.join(OUTPUT_DIR, f"{safe_topic_name}_script.json")
    
    if not os.path.exists(json_filename):
        print(f"Warning: JSON file {json_filename} not found. Skipping topic '{topic}'.")
        return
        
    print(f"\n[{topic}] Starting TTS Pipeline...")
    
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

    dialogues = [item for item in script if item.get("type", "") in ["dialogue", "heading"]]
    total_turns = len(dialogues)
    
    subtitles = []
    current_time_ms = 0
    final_audio = AudioSegment.empty()  # Master audio track
    
    print(f"Found {total_turns} dialogue turns to process.")
    
    for idx, item in enumerate(dialogues, start=1):
        item_type = item.get("type", "dialogue")
        speaker = item.get("speaker", "Unknown")
        # Phân tách 2 luồng text dựa trên JSON mới
        text_display = item.get("text_display", item.get("text", ""))
        text_tts = item.get("text_tts", text_display)
        
        turn_audio = AudioSegment.empty()
        turn_phonemes = []
        has_audio = False
        duration_ms = 0
        voice = None
        
        # BỎ QUA TẠO AUDIO NẾU LÀ HEADING ĐẦU TIÊN (Intro) HOẶC KHÔNG CÓ THOẠI
        if item_type == "heading" and (idx == 1 or not text_tts or speaker == "Unknown" or speaker == ""):
            print(f"  [{idx}/{total_turns}] Skipping audio generation for silent heading: '{text_display}'")
            # Vẫn ghi timestamp nhưng không cộng thời gian
            subtitles.append({
                "idx": idx,
                "type": item_type,
                "speaker": speaker,
                "text": text_display,
                "text_tts": text_tts,
                "phonemes": "",
                "start_time_sec": current_time_ms / 1000.0,
                "end_time_sec": current_time_ms / 1000.0,
                "duration_sec": 0,
                "voice_used": "None"
            })
            continue

        voice = get_voice_for_speaker(speaker)
        
        # Get custom speed (default to 1.0 if not in map, e.g. for fallback voices)
        speed = SPEED_MAP.get(speaker, 1.0)
        
        # 1. GENERATE WAV VIA KOKORO
        # Sử dụng text_tts (đã có đánh dấu trọng âm, nhịp độ) để render
        generator = pipeline(text_tts, voice=voice, speed=speed, split_pattern=r'\\n+')
        
        for i, (gs, ps, audio_data) in enumerate(generator):
            if audio_data is not None:
                has_audio = True
                if ps:
                    turn_phonemes.append(ps)
                # Audio_data is a numpy float array (usually 24000Hz)
                # Save small partial wav
                partial_wav = os.path.join(TMP_AUDIO_DIR, f"tmp_part_{idx}_{i}.wav")
                sf.write(partial_wav, audio_data, 24000)
                
                # Load via pydub and append to this turn's total audio
                partial_segment = AudioSegment.from_wav(partial_wav)
                turn_audio += partial_segment
                
                # Delete partial to keep tmp folder clean and safe
                os.remove(partial_wav)
        
        if not has_audio:
            print(f"  [{idx}/{total_turns}] Warning: No audio generated for this turn.")
            continue
            
        print(f"  [{idx}/{total_turns}] Generated voice '{voice}' for speaker: {speaker}")

        # Note: 'turn_audio' now contains the full spoken audio just for this dialogue turn
        # --- BƯỚC MỚI: CẮT BỎ KHOẢNG LẶNG ĐẦU VÀ CUỐI MẶC ĐỊNH CỦA TTS ---
        # Kokoro thường tự động chèn 300ms-500ms khoảng lặng bao quanh từng câu, làm mất tự nhiên.
        trim_start = detect_leading_silence(turn_audio, silence_threshold=-45.0)
        trim_end = detect_leading_silence(turn_audio.reverse(), silence_threshold=-45.0)
        end_idx = len(turn_audio) - trim_end
        
        # Chỉ áp dụng cắt xén nếu file audio có tiếng thực sự
        if trim_start < end_idx:
            turn_audio = turn_audio[trim_start:end_idx]
            
        # Thêm khoảng nghỉ: 300ms cho heading, 100ms cho dialogue
        pause_duration = 300 if item_type == "heading" else 100
        turn_audio += AudioSegment.silent(duration=pause_duration)
        # ----------------------------------------------------------------
        
        # --- BƯỚC MỚI: LƯU TRỮ AUDIO (VÀ TEXT DỮ LIỆU HUẤN LUYỆN) RIÊNG LẺ MỖI LẦN NÓI ---
        # Tạo thư mục theo cấu trúc: data/{Speaker}/{NgàyGiờ}_{TênTopic}/
        # Ví dụ: data/Alex/20260224_1045_Talking_About_Your_Week
        speaker_topic_dir = os.path.join(DATA_DIR, speaker, f"{current_time_str}_{safe_topic_name}")
        os.makedirs(speaker_topic_dir, exist_ok=True)
        
        # Bộ ID Tên (Ví dụ: alex_1, sarah_2) ngắn gọn
        base_filename = f"{speaker.lower()}_{idx}"
        
        # 1. Lưu file âm thanh riêng lẻ (.wav) vào thư mục chung của topic
        turn_wav_path = os.path.join(speaker_topic_dir, f"{base_filename}.wav")
        turn_audio.export(turn_wav_path, format="wav")
        
        # 2. Xây dữ liệu Train: Xuất transcript sạch (.txt) đi kèm nằm sát file .wav
        turn_txt_path = os.path.join(speaker_topic_dir, f"{base_filename}.txt")
        with open(turn_txt_path, "w", encoding="utf-8") as text_file:
            text_file.write(text_display)
            
        # 3. Ghi vào file CSV tổng hợp toàn bộ (Metadata for Machine Learning AI Model)
        # Format giống với chuẩn LJSpeech (audio_path, transcript)
        try:
            with open(DATASET_CSV, mode='a', newline='', encoding='utf-8') as csv_file:
                writer = csv.writer(csv_file)
                # Đổi đường dẫn tuyệt đối (D:\work\...) thành đường dẫn tương đối ("data/...") cho file CSV
                # Đồng thời đổi dấu \ thành / để tương thích chuẩn với mọi HĐH khi train AI
                relative_csv_path = f"data/{speaker}/{current_time_str}_{safe_topic_name}/{base_filename}.wav"
                writer.writerow([relative_csv_path, speaker, text_display, " ".join(turn_phonemes)])
        except Exception as e:
            print(f"Warning: Could not write to CSV: {e}")
        # ----------------------------------------------------------------
        
        # 2. TIMESTAMPING AND SUBTITLES
        duration_ms = len(turn_audio)
        
        subtitles.append({
            "idx": idx,
            "type": item_type,
            "speaker": speaker,
            "text": text_display,
            "text_tts": text_tts,
            "phonemes": " ".join(turn_phonemes), # Lưu token model kokoro
            "start_time_sec": current_time_ms / 1000.0,
            "end_time_sec": (current_time_ms + duration_ms) / 1000.0,
            "duration_sec": duration_ms / 1000.0,
            "voice_used": voice
        })
        
        # 3. ASSEMBLY
        # Add the audio block to final master track
        final_audio += turn_audio
        current_time_ms += duration_ms
        
        # Đã loại bỏ SILENCE_GAP! 
        # Nhịp độ ngắt quãng bây giờ hoàn toàn phụ thuộc vào dấu phẩy (,) và dấu chấm tắt (...) của LLM.

    # ================= OUTPUT FINAL ASSEMBLY =================
    if len(final_audio) > 0:
        print(f"[{topic}] Assembling and exporting {len(final_audio)/1000.0:.2f} seconds of audio...")
        mp3_filename = os.path.join(OUTPUT_DIR, f"{safe_topic_name}_podcast.mp3")
        
        # Export as standard mp3
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
    
    if not os.path.exists(TOPICS_FILE):
        print("No topics.txt found. Run make_youtube_video.py first.")
        sys.exit(1)

    with open(TOPICS_FILE, "r", encoding="utf-8") as f:
        topic_name = f.read().strip()

    if not topic_name:
        print("Topic is empty.")
        sys.exit(1)

    print("Initializing Kokoro TTS Pipeline... (this may take a moment)")
    # 'a' = American models
    pipeline = KPipeline(lang_code=LANG_CODE)
    
    process_topic_tts(topic_name, pipeline)
        
    cleanup_tmp_audio()
    print("\nTopic processed successfully via Kokoro TTS!")

if __name__ == "__main__":
    main()
