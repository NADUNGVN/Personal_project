import os
import sys
import json
import soundfile as sf
from pathlib import Path
from pydub import AudioSegment

# ==============================================================================
# Helper to set up environment for loading original scripts
# ==============================================================================
BASE_DIR = Path(r"d:\work\Personal_project")

# Add paths to sys.path to allow imports
sys.path.append(str(BASE_DIR / "make_video_with_image"))
sys.path.append(str(BASE_DIR / "vibe-voice"))

# Import Kokoro
import scripts.kokoro_tts as kokoro_module
from kokoro import KPipeline

# Import VibeVoice
from predict import load_model_and_processor, predict
import imageio_ffmpeg
import numpy as np

# Override ffmpeg for pydub to be safe
ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
AudioSegment.converter = ffmpeg_exe

# ==============================================================================
# Configs
# ==============================================================================
OUTPUT_DIR = BASE_DIR / "make_short_video_youtube" / "output" / "tts_test"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Test content
TEST_TEXT = "After a long day at work, I really look forward to my evening wind-down routine. First, I like to kick off my shoes and just, you know, relax for a bit."

# All available English Kokoro voices
KOKORO_VOICES = [
    'af_alloy', 'af_aoede', 'af_bella', 'af_heart', 'af_jessica', 'af_kore', 
    'af_nicole', 'af_nova', 'af_river', 'af_sarah', 'af_sky', 'am_adam', 
    'am_echo', 'am_eric', 'am_fenrir', 'am_liam', 'am_michael', 'am_onyx', 
    'am_puck', 'am_santa', 'bf_alice', 'bf_emma', 'bf_isabella', 'bf_lily', 
    'bm_daniel', 'bm_fable', 'bm_george', 'bm_lewis'
]

# VibeVoice configured voices
# The main VibeVoice root directory
VIBEVOICE_DIR = BASE_DIR / "vibe-voice" / "VibeVoice" / "demo" / "voices" / "streaming_model"

VIBEVOICE_VOICES = [
    "en-Davis_man.pt", 
    "en-Frank_man.pt", 
    "en-Mike_man.pt", 
    "en-Carter_man.pt",
    "en-Emma_woman.pt", 
    "en-Grace_woman.pt"
]

def normalize_audio_np(audio_np):
    import torch
    if isinstance(audio_np, torch.Tensor):
        audio_np = audio_np.cpu().float().numpy()
    elif hasattr(audio_np, "dtype"):
        audio_np = audio_np.astype(np.float32)

    if hasattr(audio_np, "ndim") and audio_np.ndim > 1:
        audio_np = audio_np.squeeze()
    return audio_np

def run_kokoro_tests():
    print("--- Running Kokoro Tests ---")
    
    for voice_code in KOKORO_VOICES:
        # Determine language code based on prefix
        lang_code = voice_code[0]
        pipeline = KPipeline(lang_code=lang_code) 
        
        print(f"Testing Kokoro Voice: {voice_code}")
        
        try:
            generator = pipeline(TEST_TEXT, voice=voice_code, speed=1.0, split_pattern=r'\\n+')
            
            full_audio = AudioSegment.empty()
            for i, (gs, ps, audio_data) in enumerate(generator):
                if audio_data is not None:
                    tmp_wav = OUTPUT_DIR / "kokoro_tmp.wav"
                    sf.write(str(tmp_wav), audio_data, 24000)
                    full_audio += AudioSegment.from_wav(str(tmp_wav))
                    tmp_wav.unlink()
            
            if len(full_audio) > 0:
                out_path = OUTPUT_DIR / f"kokoro_{voice_code}.mp3"
                full_audio.export(str(out_path), format="mp3", bitrate="192k")
                print(f"  -> Saved to {out_path.name}")
            else:
                print("  -> Failed to generate audio.")
        except Exception as e:
            print(f"  -> Failed to generate audio: {e}")


def run_vibevoice_tests():
    print("\n--- Running VibeVoice Tests ---")
    model, processor, device = load_model_and_processor(
        model_path="microsoft/VibeVoice-Realtime-0.5B",
        device="auto",
        num_ddpm_steps=5,
    )
    
    for voice_file in VIBEVOICE_VOICES:
        voice_preset_path = str(VIBEVOICE_DIR / voice_file)
        print(f"Testing VibeVoice Voice: {voice_file}")
        
        if not os.path.exists(voice_preset_path):
            print(f"  -> Warning: Voice preset {voice_preset_path} not found. Skipping.")
            continue
            
        try:
            result = predict(
                text=TEST_TEXT,
                model=model,
                processor=processor,
                device=device,
                voice_preset_path=voice_preset_path,
                cfg_scale=1.5,
                verbose=False,
            )
            
            audio_np = normalize_audio_np(result["audio"])
            sample_rate = result["sample_rate"]
            
            tmp_wav = OUTPUT_DIR / "vibevoice_tmp.wav"
            sf.write(str(tmp_wav), audio_np, sample_rate)
            
            audio_segment = AudioSegment.from_wav(str(tmp_wav))
            tmp_wav.unlink()
            
            out_path = OUTPUT_DIR / f"vibevoice_{voice_file.replace('.pt', '')}.mp3"
            audio_segment.export(str(out_path), format="mp3", bitrate="192k")
            print(f"  -> Saved to {out_path.name}")
            
        except Exception as e:
            print(f"  -> Failed to generate audio: {e}")

def main():
    print(f"Test output directory: {OUTPUT_DIR}")
    print(f"Test text: '{TEST_TEXT}'\n")
    
    run_kokoro_tests()
    run_vibevoice_tests()
    
    print("\nAll tests completed! Check the output directory for the generated audio files.")

if __name__ == "__main__":
    main()
