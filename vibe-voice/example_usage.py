"""
Example: Using VibeVoice Predict as a Python Module
====================================================
Demonstrates how to import and use the predict functions directly.
"""

from predict import load_model_and_processor, predict, save_audio

# ─────────────────────────────────────────────────
# 1. Load model (only once — reuse for many calls)
# ─────────────────────────────────────────────────
model, processor, device = load_model_and_processor(
    model_path="microsoft/VibeVoice-Realtime-0.5B",
    device="auto",        # auto-detect CUDA / MPS / CPU
    num_ddpm_steps=5,     # quality vs speed tradeoff
)

# ─────────────────────────────────────────────────
# 2. Generate speech
# ─────────────────────────────────────────────────
voice_file = "path/to/your/voice.pt"  # ← change this to your voice file

result = predict(
    text="Hello! Welcome to VibeVoice. This is a test of the real-time text-to-speech system.",
    model=model,
    processor=processor,
    device=device,
    voice_preset_path=voice_file,
    cfg_scale=1.5,        # 1.0-3.0 range; higher = more faithful to voice prompt
    verbose=True,
)

# ─────────────────────────────────────────────────
# 3. Save the output
# ─────────────────────────────────────────────────
save_audio(result["audio"], "output.wav", result["sample_rate"])

print(f"Audio duration: {result['duration_seconds']:.2f}s")
print(f"Generation took: {result['generation_time']:.2f}s")
print(f"Real-time factor: {result['rtf']:.3f}x")


# ─────────────────────────────────────────────────
# 4. Generate multiple outputs (model stays loaded)
# ─────────────────────────────────────────────────
texts = [
    "The quick brown fox jumps over the lazy dog.",
    "In a world of infinite possibilities, every voice matters.",
    "VibeVoice enables natural, expressive speech synthesis.",
]

for i, text in enumerate(texts):
    result = predict(
        text=text,
        model=model,
        processor=processor,
        device=device,
        voice_preset_path=voice_file,
        cfg_scale=1.5,
        verbose=False,
    )
    save_audio(result["audio"], f"output_{i+1}.wav")
    print(f"[{i+1}] \"{text[:50]}...\" → {result['duration_seconds']:.1f}s audio")
