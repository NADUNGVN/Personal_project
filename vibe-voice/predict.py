"""
VibeVoice-Realtime-0.5B Prediction Script
==========================================
Text-to-Speech generation using Microsoft's VibeVoice-Realtime-0.5B model.

Setup:
    git clone https://github.com/microsoft/VibeVoice.git
    cd VibeVoice
    pip install -e .[streamingtts]
    # Optional: pip install flash-attn --no-build-isolation

Usage:
    python predict.py --text "Hello, this is a test."
    python predict.py --text_file input.txt --speaker_name Carter
    python predict.py --text "Hello world" --output output.wav --cfg_scale 2.0
"""

import argparse
import copy
import glob
import os
import sys
import time
import traceback
from pathlib import Path

import torch
import numpy as np


# ─────────────────────────────────────────────────────────────
# Voice Preset Manager
# ─────────────────────────────────────────────────────────────
class VoicePresetManager:
    """Manages voice preset files (.pt) for speaker voice cloning."""

    # Default voices directory (inside VibeVoice repo)
    DEFAULT_VOICES_DIR = None

    def __init__(self, voices_dir: str = None):
        self.voices = {}
        self._scan_voices(voices_dir)

    def _scan_voices(self, voices_dir: str = None):
        """Scan for .pt voice preset files."""
        search_dirs = []
        if voices_dir:
            search_dirs.append(voices_dir)

        # Try common locations
        search_dirs.extend([
            os.path.join(os.path.dirname(__file__), "voices", "streaming_model"),
            os.path.join(os.getcwd(), "demo", "voices", "streaming_model"),
            os.path.join(os.getcwd(), "voices", "streaming_model"),
        ])

        # Also check if VibeVoice is installed as package
        try:
            import vibevoice
            pkg_dir = os.path.dirname(vibevoice.__file__)
            parent = os.path.dirname(pkg_dir)
            search_dirs.append(os.path.join(parent, "demo", "voices", "streaming_model"))
        except ImportError:
            pass

        for d in search_dirs:
            if os.path.exists(d):
                pt_files = glob.glob(os.path.join(d, "**", "*.pt"), recursive=True)
                for f in pt_files:
                    name = os.path.splitext(os.path.basename(f))[0].lower()
                    self.voices[name] = os.path.abspath(f)

        if self.voices:
            self.voices = dict(sorted(self.voices.items()))
            print(f"[VoicePresetManager] Found {len(self.voices)} voices: {', '.join(self.voices.keys())}")
        else:
            print("[VoicePresetManager] No voice presets found. "
                  "Please provide a --voice_file or ensure voices are in the expected directory.")

    def get_voice(self, name: str) -> str:
        """Get voice file path by speaker name (case-insensitive, supports partial matching)."""
        name_lower = name.lower()

        # Exact match
        if name_lower in self.voices:
            return self.voices[name_lower]

        # Partial match
        matches = [
            (k, v) for k, v in self.voices.items()
            if name_lower in k or k in name_lower
        ]
        if len(matches) == 1:
            return matches[0][1]
        elif len(matches) > 1:
            names = [m[0] for m in matches]
            raise ValueError(f"Multiple voices match '{name}': {names}. Please be more specific.")

        # Default to first voice
        if self.voices:
            default = list(self.voices.values())[0]
            print(f"[Warning] No voice found for '{name}', using default: {os.path.basename(default)}")
            return default

        raise FileNotFoundError(
            f"No voice preset found for '{name}' and no default voices available. "
            "Use --voice_file to specify a .pt voice file directly."
        )

    def list_voices(self) -> list:
        """List all available voice names."""
        return list(self.voices.keys())


# ─────────────────────────────────────────────────────────────
# Model Loader
# ─────────────────────────────────────────────────────────────
def load_model_and_processor(
    model_path: str = "microsoft/VibeVoice-Realtime-0.5B",
    device: str = "auto",
    num_ddpm_steps: int = 5,
):
    """
    Load the VibeVoice-Realtime model and processor.

    Args:
        model_path: HuggingFace model ID or local path.
        device: Device to use ('auto', 'cuda', 'mps', 'cpu').
        num_ddpm_steps: Number of DDPM inference steps (default: 5).

    Returns:
        tuple: (model, processor, device_str)
    """
    from vibevoice.modular.modeling_vibevoice_streaming_inference import (
        VibeVoiceStreamingForConditionalGenerationInference,
    )
    from vibevoice.processor.vibevoice_streaming_processor import (
        VibeVoiceStreamingProcessor,
    )

    # Auto-detect device
    if device == "auto":
        if torch.cuda.is_available():
            device = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"

    print(f"[Model] Device: {device}")

    # Load processor
    print(f"[Model] Loading processor from: {model_path}")
    processor = VibeVoiceStreamingProcessor.from_pretrained(model_path)

    # Select dtype and attention implementation
    if device == "cuda":
        load_dtype = torch.bfloat16
        attn_impl = "flash_attention_2"
    elif device == "mps":
        load_dtype = torch.float32
        attn_impl = "sdpa"
    else:  # cpu
        load_dtype = torch.float32
        attn_impl = "sdpa"

    print(f"[Model] dtype={load_dtype}, attn_implementation={attn_impl}")
    print(f"[Model] Loading model from: {model_path} ...")

    # Load model with fallback for flash_attention_2
    try:
        if device == "mps":
            model = VibeVoiceStreamingForConditionalGenerationInference.from_pretrained(
                model_path,
                torch_dtype=load_dtype,
                attn_implementation=attn_impl,
                device_map=None,
            )
            model.to("mps")
        else:
            model = VibeVoiceStreamingForConditionalGenerationInference.from_pretrained(
                model_path,
                torch_dtype=load_dtype,
                device_map=device,
                attn_implementation=attn_impl,
            )
    except Exception as e:
        if attn_impl == "flash_attention_2":
            print(f"[Warning] flash_attention_2 failed: {e}")
            print("[Warning] Falling back to SDPA. Audio quality may differ slightly.")
            model = VibeVoiceStreamingForConditionalGenerationInference.from_pretrained(
                model_path,
                torch_dtype=load_dtype,
                device_map=(device if device in ("cuda", "cpu") else None),
                attn_implementation="sdpa",
            )
            if device == "mps":
                model.to("mps")
        else:
            raise

    model.eval()
    model.set_ddpm_inference_steps(num_steps=num_ddpm_steps)

    print(f"[Model] Model loaded successfully!")
    if hasattr(model.model, "language_model"):
        print(f"[Model] LM attention: {model.model.language_model.config._attn_implementation}")

    return model, processor, device


# ─────────────────────────────────────────────────────────────
# Prediction Function
# ─────────────────────────────────────────────────────────────
def predict(
    text: str,
    model,
    processor,
    device: str,
    voice_preset_path: str,
    cfg_scale: float = 1.5,
    max_new_tokens: int = None,
    verbose: bool = True,
) -> dict:
    """
    Generate speech from text using VibeVoice-Realtime.

    Args:
        text: Input text to synthesize.
        model: Loaded VibeVoice model.
        processor: Loaded VibeVoice processor.
        device: Device string ('cuda', 'mps', 'cpu').
        voice_preset_path: Path to the .pt voice preset file.
        cfg_scale: Classifier-Free Guidance scale (default: 1.5).
        max_new_tokens: Max tokens to generate (None for auto).
        verbose: Whether to print progress info.

    Returns:
        dict with keys:
            - 'audio': numpy array of generated audio (24kHz)
            - 'sample_rate': 24000
            - 'duration_seconds': float
            - 'generation_time': float
            - 'rtf': Real-Time Factor
    """
    SAMPLE_RATE = 24000

    # Clean up text
    text = text.replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')

    # Load voice preset
    target_device = device if device != "cpu" else "cpu"
    if verbose:
        print(f"[Predict] Loading voice preset: {os.path.basename(voice_preset_path)}")
    all_prefilled_outputs = torch.load(voice_preset_path, map_location=target_device, weights_only=False)

    # Process input
    inputs = processor.process_input_with_cached_prompt(
        text=text,
        cached_prompt=all_prefilled_outputs,
        padding=True,
        return_tensors="pt",
        return_attention_mask=True,
    )

    # Move tensors to device
    for k, v in inputs.items():
        if torch.is_tensor(v):
            inputs[k] = v.to(target_device)

    if verbose:
        input_tokens = inputs["tts_text_ids"].shape[1]
        print(f"[Predict] Input text tokens: {input_tokens}")
        print(f"[Predict] CFG scale: {cfg_scale}")
        print(f"[Predict] Generating speech...")

    # Generate
    start_time = time.time()
    outputs = model.generate(
        **inputs,
        max_new_tokens=max_new_tokens,
        cfg_scale=cfg_scale,
        tokenizer=processor.tokenizer,
        generation_config={"do_sample": False},
        verbose=verbose,
        all_prefilled_outputs=copy.deepcopy(all_prefilled_outputs),
    )
    generation_time = time.time() - start_time

    # Extract audio
    if outputs.speech_outputs and outputs.speech_outputs[0] is not None:
        audio = outputs.speech_outputs[0]
        if torch.is_tensor(audio):
            audio_np = audio.cpu().float().numpy()  # .float() converts bfloat16 → float32
        else:
            audio_np = np.array(audio, dtype=np.float32)

        audio_samples = audio_np.shape[-1] if len(audio_np.shape) > 0 else len(audio_np)
        audio_duration = audio_samples / SAMPLE_RATE
        rtf = generation_time / audio_duration if audio_duration > 0 else float("inf")

        if verbose:
            print(f"[Predict] Generation time: {generation_time:.2f}s")
            print(f"[Predict] Audio duration: {audio_duration:.2f}s")
            print(f"[Predict] RTF (Real-Time Factor): {rtf:.3f}x")

        return {
            "audio": audio_np,
            "sample_rate": SAMPLE_RATE,
            "duration_seconds": audio_duration,
            "generation_time": generation_time,
            "rtf": rtf,
        }
    else:
        raise RuntimeError("Model generated no audio output.")


def save_audio(audio_np: np.ndarray, output_path: str, sample_rate: int = 24000):
    """Save audio numpy array to WAV file."""
    from scipy.io import wavfile

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    # Ensure audio is in the right format
    if audio_np.dtype == np.float32 or audio_np.dtype == np.float64:
        # Normalize to int16 range
        audio_int16 = np.clip(audio_np * 32767, -32768, 32767).astype(np.int16)
    else:
        audio_int16 = audio_np.astype(np.int16)

    # Handle multi-dimensional arrays
    if audio_int16.ndim > 1:
        audio_int16 = audio_int16.squeeze()

    wavfile.write(output_path, sample_rate, audio_int16)
    print(f"[Save] Audio saved to: {output_path}")


# ─────────────────────────────────────────────────────────────
# CLI Entry Point
# ─────────────────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(
        description="VibeVoice-Realtime-0.5B Text-to-Speech Prediction",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python predict.py --text "Hello, this is a test of VibeVoice."
  python predict.py --text_file story.txt --speaker_name Carter --output story.wav
  python predict.py --text "Good morning!" --voice_file my_voice.pt --cfg_scale 2.0
  python predict.py --list_voices
        """,
    )

    # Input options
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("--text", type=str, help="Text to synthesize")
    input_group.add_argument("--text_file", type=str, help="Path to a text file to synthesize")

    # Voice options
    parser.add_argument(
        "--speaker_name", type=str, default="Wayne",
        help="Speaker name from available presets (default: Wayne)",
    )
    parser.add_argument(
        "--voice_file", type=str, default=None,
        help="Direct path to a .pt voice preset file (overrides --speaker_name)",
    )
    parser.add_argument(
        "--voices_dir", type=str, default=None,
        help="Custom directory to scan for voice presets",
    )

    # Model options
    parser.add_argument(
        "--model_path", type=str, default="microsoft/VibeVoice-Realtime-0.5B",
        help="HuggingFace model ID or local path (default: microsoft/VibeVoice-Realtime-0.5B)",
    )
    parser.add_argument(
        "--device", type=str, default="auto",
        choices=["auto", "cuda", "mps", "cpu"],
        help="Device for inference (default: auto)",
    )

    # Generation options
    parser.add_argument(
        "--cfg_scale", type=float, default=1.5,
        help="Classifier-Free Guidance scale (default: 1.5, higher = more prompt adherence)",
    )
    parser.add_argument(
        "--ddpm_steps", type=int, default=5,
        help="Number of DDPM inference steps (default: 5, more = better quality but slower)",
    )

    # Output options
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output WAV file path (default: outputs/<timestamp>.wav)",
    )

    # Utility
    parser.add_argument(
        "--list_voices", action="store_true",
        help="List all available voice presets and exit",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    # ── List voices mode ──
    if args.list_voices:
        vm = VoicePresetManager(args.voices_dir)
        voices = vm.list_voices()
        if voices:
            print("\n🎤 Available Voice Presets:")
            for v in voices:
                print(f"  • {v}")
        else:
            print("No voice presets found.")
        return

    # ── Validate input ──
    if not args.text and not args.text_file:
        print("Error: Please provide --text or --text_file")
        print("Use --help for usage information.")
        sys.exit(1)

    # Read text
    if args.text_file:
        if not os.path.exists(args.text_file):
            print(f"Error: Text file not found: {args.text_file}")
            sys.exit(1)
        with open(args.text_file, "r", encoding="utf-8") as f:
            text = f.read().strip()
        print(f"[Input] Read {len(text)} characters from: {args.text_file}")
    else:
        text = args.text

    if not text:
        print("Error: Input text is empty.")
        sys.exit(1)

    # ── Resolve voice preset ──
    if args.voice_file:
        if not os.path.exists(args.voice_file):
            print(f"Error: Voice file not found: {args.voice_file}")
            sys.exit(1)
        voice_path = args.voice_file
    else:
        vm = VoicePresetManager(args.voices_dir)
        voice_path = vm.get_voice(args.speaker_name)

    print(f"[Voice] Using: {voice_path}")

    # ── Load model ──
    model, processor, device = load_model_and_processor(
        model_path=args.model_path,
        device=args.device,
        num_ddpm_steps=args.ddpm_steps,
    )

    # ── Run prediction ──
    result = predict(
        text=text,
        model=model,
        processor=processor,
        device=device,
        voice_preset_path=voice_path,
        cfg_scale=args.cfg_scale,
        verbose=True,
    )

    # ── Save output ──
    if args.output:
        output_path = args.output
    else:
        os.makedirs("outputs", exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join("outputs", f"vibevoice_{timestamp}.wav")

    save_audio(result["audio"], output_path, result["sample_rate"])

    # ── Summary ──
    print("\n" + "=" * 55)
    print("  VibeVoice Generation Summary")
    print("=" * 55)
    print(f"  Text length:      {len(text)} characters")
    print(f"  Voice preset:     {os.path.basename(voice_path)}")
    print(f"  CFG scale:        {args.cfg_scale}")
    print(f"  DDPM steps:       {args.ddpm_steps}")
    print(f"  Device:           {device}")
    print(f"  Generation time:  {result['generation_time']:.2f}s")
    print(f"  Audio duration:   {result['duration_seconds']:.2f}s")
    print(f"  RTF:              {result['rtf']:.3f}x")
    print(f"  Output:           {output_path}")
    print("=" * 55)


if __name__ == "__main__":
    main()
