"""
VibeVoice-Realtime-0.5B Streaming Prediction
=============================================
Process text in chunks and generate audio progressively.
Useful for real-time TTS or streaming from LLM outputs.

Usage:
    python predict_streaming.py --text "A long story to narrate in real-time..."
    python predict_streaming.py --text_file long_story.txt --chunk_size 200
"""

import argparse
import copy
import os
import sys
import time

import torch
import numpy as np


def load_model(model_path: str, device: str = "auto", ddpm_steps: int = 5):
    """Load model and processor with auto device detection."""
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

    print(f"[Model] Using device: {device}")

    # Load processor
    processor = VibeVoiceStreamingProcessor.from_pretrained(model_path)

    # Device-specific config
    if device == "cuda":
        dtype, attn = torch.bfloat16, "flash_attention_2"
    else:
        dtype, attn = torch.float32, "sdpa"

    # Load model with fallback
    try:
        if device == "mps":
            model = VibeVoiceStreamingForConditionalGenerationInference.from_pretrained(
                model_path, torch_dtype=dtype, attn_implementation=attn, device_map=None,
            )
            model.to("mps")
        else:
            model = VibeVoiceStreamingForConditionalGenerationInference.from_pretrained(
                model_path, torch_dtype=dtype, device_map=device, attn_implementation=attn,
            )
    except Exception as e:
        if attn == "flash_attention_2":
            print(f"[Warning] flash_attention_2 failed, falling back to SDPA: {e}")
            model = VibeVoiceStreamingForConditionalGenerationInference.from_pretrained(
                model_path, torch_dtype=dtype,
                device_map=(device if device != "mps" else None),
                attn_implementation="sdpa",
            )
            if device == "mps":
                model.to("mps")
        else:
            raise

    model.eval()
    model.set_ddpm_inference_steps(num_steps=ddpm_steps)
    return model, processor, device


def split_text_into_chunks(text: str, chunk_size: int = 200) -> list:
    """
    Split text into chunks, preferring sentence boundaries.

    Args:
        text: Input text.
        chunk_size: Approximate max characters per chunk.

    Returns:
        List of text chunks.
    """
    import re

    # Split by sentences first
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 <= chunk_size:
            current_chunk = (current_chunk + " " + sentence).strip()
        else:
            if current_chunk:
                chunks.append(current_chunk)
            # Handle sentences longer than chunk_size
            if len(sentence) > chunk_size:
                words = sentence.split()
                current_chunk = ""
                for word in words:
                    if len(current_chunk) + len(word) + 1 <= chunk_size:
                        current_chunk = (current_chunk + " " + word).strip()
                    else:
                        if current_chunk:
                            chunks.append(current_chunk)
                        current_chunk = word
            else:
                current_chunk = sentence

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def predict_streaming(
    text: str,
    model,
    processor,
    device: str,
    voice_preset_path: str,
    chunk_size: int = 200,
    cfg_scale: float = 1.5,
    output_dir: str = "outputs",
    save_chunks: bool = False,
):
    """
    Generate speech from text in streaming chunks.

    Each chunk is processed independently and audio segments are concatenated.

    Args:
        text: Full input text.
        model: Loaded model.
        processor: Loaded processor.
        device: Device string.
        voice_preset_path: Path to .pt voice file.
        chunk_size: Characters per chunk.
        cfg_scale: CFG scale.
        output_dir: Directory for output files.
        save_chunks: Whether to save individual chunk audio files.

    Yields:
        dict: Per-chunk result with 'audio', 'chunk_index', 'chunk_text', 'sample_rate'.
    """
    from scipy.io import wavfile

    SAMPLE_RATE = 24000

    chunks = split_text_into_chunks(text, chunk_size)
    print(f"[Streaming] Split text into {len(chunks)} chunks")

    target_device = device if device != "cpu" else "cpu"
    all_prefilled_outputs = torch.load(voice_preset_path, map_location=target_device, weights_only=False)

    all_audio = []
    total_gen_time = 0

    for i, chunk_text in enumerate(chunks):
        chunk_text_clean = chunk_text.replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')

        print(f"\n[Chunk {i+1}/{len(chunks)}] \"{chunk_text_clean[:80]}{'...' if len(chunk_text_clean) > 80 else ''}\"")

        inputs = processor.process_input_with_cached_prompt(
            text=chunk_text_clean,
            cached_prompt=all_prefilled_outputs,
            padding=True,
            return_tensors="pt",
            return_attention_mask=True,
        )

        for k, v in inputs.items():
            if torch.is_tensor(v):
                inputs[k] = v.to(target_device)

        start = time.time()
        outputs = model.generate(
            **inputs,
            max_new_tokens=None,
            cfg_scale=cfg_scale,
            tokenizer=processor.tokenizer,
            generation_config={"do_sample": False},
            verbose=False,
            all_prefilled_outputs=copy.deepcopy(all_prefilled_outputs),
        )
        gen_time = time.time() - start
        total_gen_time += gen_time

        if outputs.speech_outputs and outputs.speech_outputs[0] is not None:
            audio = outputs.speech_outputs[0]
            if torch.is_tensor(audio):
                audio_np = audio.cpu().numpy()
            else:
                audio_np = np.array(audio)

            duration = audio_np.shape[-1] / SAMPLE_RATE
            rtf = gen_time / duration if duration > 0 else float("inf")
            print(f"  ✓ {duration:.2f}s audio in {gen_time:.2f}s (RTF: {rtf:.3f}x)")

            # Save individual chunk
            if save_chunks:
                os.makedirs(output_dir, exist_ok=True)
                chunk_path = os.path.join(output_dir, f"chunk_{i:03d}.wav")
                audio_int16 = np.clip(audio_np.squeeze() * 32767, -32768, 32767).astype(np.int16)
                wavfile.write(chunk_path, SAMPLE_RATE, audio_int16)

            all_audio.append(audio_np.squeeze())

            yield {
                "audio": audio_np,
                "chunk_index": i,
                "chunk_text": chunk_text_clean,
                "sample_rate": SAMPLE_RATE,
                "duration": duration,
                "generation_time": gen_time,
            }
        else:
            print(f"  ✗ No audio generated for chunk {i+1}")

    # Concatenate all chunks and save final output
    if all_audio:
        combined = np.concatenate(all_audio)
        total_duration = combined.shape[-1] / SAMPLE_RATE
        overall_rtf = total_gen_time / total_duration if total_duration > 0 else float("inf")

        os.makedirs(output_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        final_path = os.path.join(output_dir, f"vibevoice_stream_{timestamp}.wav")
        audio_int16 = np.clip(combined * 32767, -32768, 32767).astype(np.int16)
        wavfile.write(final_path, SAMPLE_RATE, audio_int16)

        print(f"\n{'=' * 55}")
        print(f"  Streaming Generation Complete")
        print(f"{'=' * 55}")
        print(f"  Chunks processed:  {len(all_audio)}/{len(chunks)}")
        print(f"  Total gen time:    {total_gen_time:.2f}s")
        print(f"  Total audio:       {total_duration:.2f}s")
        print(f"  Overall RTF:       {overall_rtf:.3f}x")
        print(f"  Output:            {final_path}")
        print(f"{'=' * 55}")


def main():
    parser = argparse.ArgumentParser(description="VibeVoice Streaming TTS Prediction")

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--text", type=str, help="Text to synthesize")
    input_group.add_argument("--text_file", type=str, help="Text file to synthesize")

    parser.add_argument("--model_path", default="microsoft/VibeVoice-Realtime-0.5B")
    parser.add_argument("--voice_file", type=str, required=True, help="Path to .pt voice preset file")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "mps", "cpu"])
    parser.add_argument("--cfg_scale", type=float, default=1.5)
    parser.add_argument("--ddpm_steps", type=int, default=5)
    parser.add_argument("--chunk_size", type=int, default=200, help="Characters per chunk (default: 200)")
    parser.add_argument("--output_dir", default="outputs")
    parser.add_argument("--save_chunks", action="store_true", help="Also save individual chunk audio files")

    args = parser.parse_args()

    # Read text
    if args.text_file:
        with open(args.text_file, "r", encoding="utf-8") as f:
            text = f.read().strip()
    else:
        text = args.text

    if not text:
        print("Error: empty text")
        sys.exit(1)

    # Load model
    model, processor, device = load_model(args.model_path, args.device, args.ddpm_steps)

    # Run streaming prediction
    for chunk_result in predict_streaming(
        text=text,
        model=model,
        processor=processor,
        device=device,
        voice_preset_path=args.voice_file,
        chunk_size=args.chunk_size,
        cfg_scale=args.cfg_scale,
        output_dir=args.output_dir,
        save_chunks=args.save_chunks,
    ):
        pass  # Results are printed inside the generator


if __name__ == "__main__":
    main()
