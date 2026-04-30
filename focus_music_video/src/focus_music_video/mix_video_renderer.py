from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from focus_music_video.ffmpeg_tools import IMAGE_SUFFIXES, VIDEO_SUFFIXES, probe_duration


@dataclass(slots=True)
class MixVideoRenderResult:
    source_name: str
    mix_name: str
    duration_seconds: float
    prepared_background_path: Path
    visualizer_path: Path | None
    video_path: Path


def _run(command: list[str]) -> None:
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        binary = command[0] if command else "command"
        raise RuntimeError(f"Required binary not found: {binary}") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() or exc.stdout.strip()
        raise RuntimeError(f"FFmpeg command failed:\n{stderr}") from exc


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _default_font_file() -> str:
    bahnschrift = Path("C:/Windows/Fonts/bahnschrift.ttf")
    if bahnschrift.exists():
        return str(bahnschrift)

    segoe_semibold = Path("C:/Windows/Fonts/seguisb.ttf")
    if segoe_semibold.exists():
        return str(segoe_semibold)

    bold = Path("C:/Windows/Fonts/arialbd.ttf")
    if bold.exists():
        return str(bold)

    regular = Path("C:/Windows/Fonts/arial.ttf")
    if regular.exists():
        return str(regular)

    return "C:/Windows/Fonts/arial.ttf"


def _escape_filter_value(value: str) -> str:
    escaped = value.replace("\\", "/")
    escaped = escaped.replace(":", r"\:")
    escaped = escaped.replace("'", r"\'")
    escaped = escaped.replace("[", r"\[")
    escaped = escaped.replace("]", r"\]")
    escaped = escaped.replace(",", r"\,")
    return escaped


def _build_pingpong_background(
    background_path: Path,
    output_path: Path,
    width: int,
    height: int,
    fps: int,
    slowdown_factor: float,
    codec: str = "libx264",
    preset: str = "slow",
    quality_value: int = 14,
) -> None:
    if slowdown_factor <= 0:
        raise ValueError("slowdown_factor must be greater than 0")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    slow_multiplier = 1.0 / slowdown_factor
    interpolation_fps = max(fps * 2, 60)

    filter_graph = (
        f"[0:v]"
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"minterpolate=fps={interpolation_fps},"
        f"setpts={slow_multiplier:.3f}*PTS,"
        "split[fwd][revsrc];"
        "[revsrc]reverse[rev];"
        f"[fwd][rev]concat=n=2:v=1:a=0,fps={fps},format=yuv420p[v]"
    )

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(background_path),
        "-filter_complex",
        filter_graph,
        "-map",
        "[v]",
        "-an",
        "-c:v",
        codec,
        "-movflags",
        "+faststart",
    ]

    if codec.endswith("_nvenc"):
        command.extend(["-preset", preset, "-cq", str(quality_value), "-b:v", "0"])
    else:
        command.extend(["-preset", preset, "-crf", str(quality_value)])

    command.append(str(output_path))
    _run(command)


def _build_image_background(
    background_path: Path,
    output_path: Path,
    width: int,
    height: int,
    fps: int,
    duration_seconds: float,
    codec: str = "libx264",
    preset: str = "slow",
    quality_value: int = 14,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    filter_graph = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},fps={fps},format=yuv420p"
    )
    command = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-framerate",
        str(fps),
        "-i",
        str(background_path),
        "-vf",
        filter_graph,
        "-t",
        f"{duration_seconds:.3f}",
        "-an",
        "-c:v",
        codec,
        "-movflags",
        "+faststart",
    ]

    if codec.endswith("_nvenc"):
        command.extend(["-preset", preset, "-cq", str(quality_value), "-b:v", "0"])
    else:
        command.extend(["-preset", preset, "-crf", str(quality_value)])
        if codec == "libx264":
            command.extend(["-tune", "stillimage"])

    command.append(str(output_path))
    _run(command)


def _prepare_background_layer(
    background_path: Path,
    output_path: Path,
    width: int,
    height: int,
    fps: int,
    duration_seconds: float,
    slowdown_factor: float,
    codec: str,
    preset: str,
    quality_value: int,
) -> None:
    suffix = background_path.suffix.lower()
    if suffix in VIDEO_SUFFIXES:
        _build_pingpong_background(
            background_path=background_path,
            output_path=output_path,
            width=width,
            height=height,
            fps=fps,
            slowdown_factor=slowdown_factor,
            codec=codec,
            preset=preset,
            quality_value=quality_value,
        )
        return

    if suffix in IMAGE_SUFFIXES:
        _build_image_background(
            background_path=background_path,
            output_path=output_path,
            width=width,
            height=height,
            fps=fps,
            duration_seconds=duration_seconds,
            codec=codec,
            preset=preset,
            quality_value=quality_value,
        )
        return

    raise ValueError(
        f"Unsupported background format: {background_path.suffix}. Use an image or a video."
    )


def _decode_audio_mono(audio_path: Path, sample_rate: int) -> np.ndarray:
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(audio_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "s16le",
        "-",
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Required binary not found: ffmpeg") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="ignore").strip()
        raise RuntimeError(f"FFmpeg audio decode failed:\n{stderr}") from exc

    samples = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        raise RuntimeError(f"Decoded audio is empty: {audio_path}")
    return samples / 32768.0


def _build_band_index_groups(
    sample_rate: int,
    fft_size: int,
    band_count: int,
    min_frequency: float,
    max_frequency: float,
) -> list[np.ndarray]:
    frequencies = np.fft.rfftfreq(fft_size, d=1.0 / sample_rate)
    edges = np.geomspace(min_frequency, max_frequency, num=band_count + 1)
    groups: list[np.ndarray] = []

    for index in range(band_count):
        mask = np.where(
            (frequencies >= edges[index]) & (frequencies < edges[index + 1])
        )[0]
        if mask.size == 0:
            target = (edges[index] + edges[index + 1]) / 2.0
            nearest = int(np.argmin(np.abs(frequencies - target)))
            mask = np.array([nearest], dtype=np.int32)
        groups.append(mask)

    return groups


def _compute_visualizer_levels(
    audio_samples: np.ndarray,
    sample_rate: int,
    fps: int,
    duration_seconds: float,
    band_count: int = 10,
) -> np.ndarray:
    frame_count = max(1, int(math.ceil(duration_seconds * fps)))
    fft_size = 4096
    half_window = fft_size // 2
    window = np.hanning(fft_size).astype(np.float32)
    padded = np.pad(audio_samples, (half_window, half_window))
    groups = _build_band_index_groups(
        sample_rate=sample_rate,
        fft_size=fft_size,
        band_count=band_count,
        min_frequency=65.0,
        max_frequency=7200.0,
    )

    band_energy = np.zeros((frame_count, band_count), dtype=np.float32)
    envelopes = np.zeros(frame_count, dtype=np.float32)
    samples_per_frame = sample_rate / float(fps)

    for frame_index in range(frame_count):
        center = int(round(frame_index * samples_per_frame))
        segment = padded[center : center + fft_size]
        if segment.shape[0] < fft_size:
            segment = np.pad(segment, (0, fft_size - segment.shape[0]))

        segment = segment.astype(np.float32, copy=False)
        envelopes[frame_index] = float(np.sqrt(np.mean(segment * segment) + 1e-8))
        spectrum = np.abs(np.fft.rfft(segment * window)).astype(np.float32)

        for group_index, group in enumerate(groups):
            values = spectrum[group]
            band_energy[frame_index, group_index] = float(
                np.sqrt(np.mean(values * values) + 1e-8)
            )

    band_scale = np.percentile(band_energy, 95, axis=0)
    band_scale = np.where(band_scale > 1e-6, band_scale, 1.0)
    envelope_scale = float(np.percentile(envelopes, 95))
    if envelope_scale <= 1e-6:
        envelope_scale = 1.0

    band_norm = np.clip(band_energy / band_scale, 0.0, 1.0) ** 0.90
    envelope_norm = np.clip(envelopes / envelope_scale, 0.0, 1.0) ** 0.75

    shape = 1.06 - 0.14 * np.abs(np.linspace(-1.0, 1.0, band_count, dtype=np.float32))
    targets = np.clip(
        0.05 + (band_norm * 0.72 + envelope_norm[:, None] * 0.38) * shape,
        0.0,
        1.0,
    )

    smoothed = np.zeros_like(targets)
    previous = np.zeros(band_count, dtype=np.float32)
    attack = 0.34
    release = 0.12

    for frame_index in range(frame_count):
        target = targets[frame_index]
        rising = target > previous
        previous = np.where(
            rising,
            previous + attack * (target - previous),
            previous + release * (target - previous),
        )
        smoothed[frame_index] = previous

    return np.concatenate([smoothed[:, ::-1], smoothed], axis=1)


def _render_visualizer_video(
    audio_path: Path,
    output_path: Path,
    duration_seconds: float,
    fps: int,
    width: int = 760,
    height: int = 168,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sample_rate = 22050
    levels = _compute_visualizer_levels(
        audio_samples=_decode_audio_mono(audio_path, sample_rate),
        sample_rate=sample_rate,
        fps=fps,
        duration_seconds=duration_seconds,
        band_count=20,
    )

    frame_count, bar_count = levels.shape
    bar_width = 10
    gap = 9
    total_width = bar_count * bar_width + (bar_count - 1) * gap
    start_x = max(0, (width - total_width) // 2)
    bottom_padding = 10
    max_height = 128
    min_height = 4
    bar_color = np.array([255, 244, 207], dtype=np.uint8)
    x_positions = [start_x + index * (bar_width + gap) for index in range(bar_count)]

    command = [
        "ffmpeg",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(fps),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264rgb",
        "-preset",
        "veryfast",
        "-crf",
        "0",
        "-pix_fmt",
        "rgb24",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise RuntimeError("Required binary not found: ffmpeg") from exc

    assert process.stdin is not None
    try:
        for frame_index in range(frame_count):
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            for bar_index, level in enumerate(levels[frame_index]):
                bar_height = int(round(min_height + level * max_height))
                left = x_positions[bar_index]
                right = left + bar_width
                top = max(0, height - bottom_padding - bar_height)
                bottom = height - bottom_padding
                frame[top:bottom, left:right] = bar_color
            process.stdin.write(frame.tobytes())
    finally:
        process.stdin.close()

    stderr = process.stderr.read().decode("utf-8", errors="ignore").strip()
    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"FFmpeg visualizer encode failed:\n{stderr}")


def _drawtext_filter(
    input_label: str,
    output_label: str,
    *,
    text: str,
    x: str,
    y: str,
    font_file: str,
    font_size: int,
    font_color: str,
    border_color: str,
    border_width: int,
    shadow_color: str,
) -> str:
    return (
        f"[{input_label}]drawtext="
        f"fontfile='{_escape_filter_value(font_file)}':"
        f"text='{text}':"
        f"x={x}:"
        f"y={y}:"
        f"fontsize={font_size}:"
        f"fontcolor={font_color}:"
        f"borderw={border_width}:"
        f"bordercolor={border_color}:"
        f"shadowcolor={shadow_color}:"
        "shadowx=0:"
        "shadowy=0"
        f"[{output_label}]"
    )


def _build_filter_complex(
    duration_seconds: float,
    font_file: str,
    visualizer_bottom_margin: int,
    show_countdown: bool,
    show_visualizer: bool,
) -> str | None:
    countdown_expr = (
        f"%{{eif\\:max(0\\,floor(({duration_seconds:.3f}-t)/60))\\:d\\:2}}"
        r"\:"
        f"%{{eif\\:max(0\\,mod(floor({duration_seconds:.3f}-t)\\,60))\\:d\\:2}}"
    )

    filters: list[str] = []
    current_label = "0:v"

    if show_countdown:
        filters.append(
            (
                "[0:v]drawtext="
                f"fontfile='{_escape_filter_value(font_file)}':"
                f"text='{countdown_expr}':"
                "x=(w-text_w)/2:"
                "y=30:"
                "fontsize=108:"
                "fontcolor=0xFFD54A:"
                "borderw=0:"
                "shadowcolor=0x091019@0.22:"
                "shadowx=0:"
                "shadowy=2[vcount]"
            )
        )
        current_label = "vcount"

    if show_visualizer:
        filters.append("[2:v]colorkey=0x000000:0.08:0.0[visualizer]")
        filters.append(
            (
                f"[{current_label}][visualizer]overlay="
                "x=(W-w)/2:"
                f"y=H-h-{visualizer_bottom_margin}:"
                "format=auto[outv]"
            )
        )
        current_label = "outv"

    if not filters:
        return None
    if current_label != "outv":
        filters.append(f"[{current_label}]null[outv]")
    return ";".join(filters)


def render_mix_video(
    source_name: str,
    mix_name: str,
    background_path: str | Path,
    output_root: str | Path,
    preview_seconds: float | None = None,
    codec: str = "h264_nvenc",
    preset: str = "p1",
    cq: int = 23,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    slowdown_factor: float = 0.5,
    background_codec: str = "libx264",
    background_preset: str = "slow",
    background_quality: int = 14,
    show_countdown: bool = True,
    show_visualizer: bool = True,
) -> MixVideoRenderResult:
    base_output_root = Path(output_root).resolve()
    mix_root = base_output_root / source_name / mix_name
    manifest_path = mix_root / "metadata" / "mix_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing mix manifest: {manifest_path}")

    manifest = _read_json(manifest_path)
    audio_path = Path(manifest["output"]["audio"]).resolve()
    if not audio_path.exists():
        raise FileNotFoundError(f"Missing mix audio: {audio_path}")

    video_dir = mix_root / "video"
    video_dir.mkdir(parents=True, exist_ok=True)

    full_duration_seconds = probe_duration(audio_path)
    duration_seconds = (
        min(full_duration_seconds, max(1.0, preview_seconds))
        if preview_seconds is not None
        else full_duration_seconds
    )
    prepared_background_path = video_dir / "prepared_background.mp4"
    _prepare_background_layer(
        background_path=Path(background_path).resolve(),
        output_path=prepared_background_path,
        width=width,
        height=height,
        fps=fps,
        duration_seconds=duration_seconds,
        slowdown_factor=slowdown_factor,
        codec=background_codec,
        preset=background_preset,
        quality_value=background_quality,
    )

    visualizer_path: Path | None = None
    visualizer_bottom_margin = 44
    if show_visualizer:
        visualizer_name = "visualizer_overlay_full.mp4"
        if preview_seconds is not None:
            visualizer_name = f"visualizer_overlay_{int(round(duration_seconds))}s.mp4"
        visualizer_path = video_dir / visualizer_name
        visualizer_width = 760
        visualizer_height = 168
        _render_visualizer_video(
            audio_path=audio_path,
            output_path=visualizer_path,
            duration_seconds=duration_seconds,
            fps=fps,
            width=visualizer_width,
            height=visualizer_height,
        )

    output_name = "final_video_focus_ui.mp4"
    if preview_seconds is not None:
        output_name = f"preview_focus_ui_{int(round(duration_seconds))}s.mp4"
    video_path = video_dir / output_name

    filter_complex = _build_filter_complex(
        duration_seconds=duration_seconds,
        font_file=_default_font_file(),
        visualizer_bottom_margin=visualizer_bottom_margin,
        show_countdown=show_countdown,
        show_visualizer=show_visualizer,
    )
    command = [
        "ffmpeg",
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(prepared_background_path),
        "-i",
        str(audio_path),
        "-c:v",
        codec,
    ]

    if show_visualizer and visualizer_path is not None:
        command.extend(["-i", str(visualizer_path)])

    if filter_complex:
        command.extend(
            [
                "-filter_complex",
                filter_complex,
                "-map",
                "[outv]",
                "-map",
                "1:a:0",
            ]
        )
    else:
        command.extend(
            [
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
            ]
        )

    if codec.endswith("_nvenc"):
        command.extend(["-preset", preset, "-cq", str(cq), "-b:v", "0"])
    elif codec == "libx264":
        command.extend(["-preset", preset, "-crf", str(cq)])
    elif preset:
        command.extend(["-preset", preset])

    command.extend(
        [
            "-c:a",
            "copy",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-t",
            f"{duration_seconds:.3f}",
            str(video_path),
        ]
    )
    _run(command)
    rendered_duration = probe_duration(video_path)
    if rendered_duration + 1.0 < duration_seconds:
        raise RuntimeError(
            "Rendered video is shorter than the expected audio duration. "
            f"Expected about {duration_seconds:.3f}s but got {rendered_duration:.3f}s: {video_path}"
        )

    return MixVideoRenderResult(
        source_name=source_name,
        mix_name=mix_name,
        duration_seconds=duration_seconds,
        prepared_background_path=prepared_background_path,
        visualizer_path=visualizer_path,
        video_path=video_path,
    )
