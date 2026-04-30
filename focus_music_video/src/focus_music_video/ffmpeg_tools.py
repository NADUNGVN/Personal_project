from __future__ import annotations

import json
import subprocess
from pathlib import Path

from focus_music_video.models import BuildJob


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


def _run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        binary = command[0] if command else "command"
        raise RuntimeError(f"Required binary not found: {binary}") from exc


def probe_duration(media_path: str | Path) -> float:
    path = Path(media_path).resolve()
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ]
    )
    payload = json.loads(result.stdout)
    duration = float(payload["format"]["duration"])
    if duration <= 0:
        raise ValueError(f"Invalid duration read from ffprobe: {path}")
    return duration


def concat_audio_tracks(
    input_paths: list[str | Path],
    output_path: str | Path,
    audio_bitrate: str = "192k",
) -> None:
    resolved_inputs = [Path(path).resolve() for path in input_paths]
    if not resolved_inputs:
        raise ValueError("At least one audio input is required to concatenate tracks.")

    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    command = ["ffmpeg", "-y"]
    for path in resolved_inputs:
        command.extend(["-i", str(path)])

    if len(resolved_inputs) == 1:
        command.extend(
            [
                "-map",
                "0:a:0",
                "-c:a",
                "aac",
                "-b:a",
                audio_bitrate,
                "-movflags",
                "+faststart",
                str(output),
            ]
        )
        try:
            _run(command)
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() or exc.stdout.strip()
            raise RuntimeError(f"FFmpeg audio concat failed:\n{stderr}") from exc
        return

    filter_parts: list[str] = []
    concat_inputs: list[str] = []
    for index in range(len(resolved_inputs)):
        label = f"a{index}"
        filter_parts.append(
            (
                f"[{index}:a:0]"
                "aresample=48000,"
                "aformat=sample_fmts=fltp:channel_layouts=stereo"
                f"[{label}]"
            )
        )
        concat_inputs.append(f"[{label}]")

    filter_parts.append(
        "".join(concat_inputs) + f"concat=n={len(resolved_inputs)}:v=0:a=1[outa]"
    )
    command.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[outa]",
            "-c:a",
            "aac",
            "-b:a",
            audio_bitrate,
            "-movflags",
            "+faststart",
            str(output),
        ]
    )

    try:
        _run(command)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() or exc.stdout.strip()
        raise RuntimeError(f"FFmpeg audio concat failed:\n{stderr}") from exc


def _build_background_input_args(job: BuildJob) -> tuple[list[str], bool]:
    suffix = job.project.background_path.suffix.lower()

    if suffix in IMAGE_SUFFIXES:
        return (
            [
                "-loop",
                "1",
                "-framerate",
                str(job.project.video.fps),
                "-i",
                str(job.project.background_path),
            ],
            True,
        )

    if suffix in VIDEO_SUFFIXES:
        return (
            [
                "-stream_loop",
                "-1",
                "-i",
                str(job.project.background_path),
            ],
            False,
        )

    raise ValueError(
        f"Unsupported background format: {job.project.background_path.suffix}. "
        "Use an image or a video."
    )


def _normalize_color(value: str) -> str:
    clean = value.strip()
    if clean.startswith("#"):
        clean = clean[1:]
    if clean.lower().startswith("0x"):
        clean = clean[2:]
    return f"0x{clean.upper()}"


def _escape_filter_value(value: str) -> str:
    escaped = value.replace("\\", "/")
    escaped = escaped.replace(":", r"\:")
    escaped = escaped.replace("'", r"\'")
    escaped = escaped.replace("[", r"\[")
    escaped = escaped.replace("]", r"\]")
    return escaped


def _build_drawtext_filter(
    job: BuildJob,
    text_path: Path,
    font_size: int,
    font_color: str,
    x: str,
    y: str,
) -> str:
    parts = [
        f"textfile='{_escape_filter_value(text_path.name)}'",
        "reload=0",
        f"fontsize={font_size}",
        f"fontcolor={_normalize_color(font_color)}",
        f"line_spacing={job.project.text_overlay.line_spacing}",
        f"x={x}",
        f"y={y}",
        "shadowcolor=black@0.65",
        "shadowx=2",
        "shadowy=2",
    ]

    font_file = job.project.text_overlay.font_file
    if font_file:
        font_path = Path(font_file)
        if font_path.exists():
            parts.append(f"fontfile='{_escape_filter_value(str(font_path))}'")

    return "drawtext=" + ":".join(parts)


def _build_video_filter(job: BuildJob) -> str:
    visual = job.profile.visual
    filters = [
        (
            f"scale={job.project.video.width}:{job.project.video.height}:"
            "force_original_aspect_ratio=increase"
        ),
        f"crop={job.project.video.width}:{job.project.video.height}",
    ]

    if visual.dim_opacity > 0:
        filters.append(
            f"drawbox=x=0:y=0:w=iw:h=ih:color=black@{visual.dim_opacity:.2f}:t=fill"
        )

    if visual.brightness != 0 or visual.saturation != 1.0:
        filters.append(
            f"eq=brightness={visual.brightness:.2f}:saturation={visual.saturation:.2f}"
        )

    if job.project.text_overlay.enabled:
        if visual.box_opacity > 0:
            filters.append(
                (
                    "drawbox="
                    f"x={visual.box_x}:y={visual.box_y}:w={visual.box_width}:h={visual.box_height}:"
                    f"color={_normalize_color(visual.box_color)}@{visual.box_opacity:.2f}:t=fill"
                )
            )
        if visual.accent_height > 0:
            filters.append(
                (
                    "drawbox="
                    f"x={visual.accent_x}:y={visual.accent_y}:w={visual.accent_width}:h={visual.accent_height}:"
                    f"color={_normalize_color(visual.accent_color)}@0.90:t=fill"
                )
            )
        filters.append(
            _build_drawtext_filter(
                job=job,
                text_path=job.overlay_title_path,
                font_size=visual.title_font_size,
                font_color=visual.title_color,
                x=visual.title_x,
                y=visual.title_y,
            )
        )
        filters.append(
            _build_drawtext_filter(
                job=job,
                text_path=job.overlay_subtitle_path,
                font_size=visual.subtitle_font_size,
                font_color=visual.subtitle_color,
                x=visual.subtitle_x,
                y=visual.subtitle_y,
            )
        )

    return ",".join(filters)


def _build_audio_filter(job: BuildJob) -> str:
    filters: list[str] = []

    if job.project.audio.fade_in > 0:
        filters.append(f"afade=t=in:st=0:d={min(job.project.audio.fade_in, job.duration_seconds):.3f}")

    if job.project.audio.fade_out > 0 and job.duration_seconds > 0.25:
        fade_start = max(0.0, job.duration_seconds - job.project.audio.fade_out)
        fade_duration = min(job.project.audio.fade_out, job.duration_seconds)
        filters.append(f"afade=t=out:st={fade_start:.3f}:d={fade_duration:.3f}")

    if job.project.audio.volume != 1.0:
        filters.append(f"volume={job.project.audio.volume:.3f}")

    return ",".join(filters)


def render_video(job: BuildJob) -> None:
    job.output_dir.mkdir(parents=True, exist_ok=True)

    background_input_args, is_still_background = _build_background_input_args(job)
    video_filter = _build_video_filter(job)
    audio_filter = _build_audio_filter(job)

    command = [
        "ffmpeg",
        "-y",
        *background_input_args,
        "-i",
        str(job.project.music_path),
        "-vf",
        video_filter,
    ]

    if audio_filter:
        command.extend(["-af", audio_filter])

    command.extend(
        [
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            job.project.video.codec,
            "-r",
            str(job.project.video.fps),
        ]
    )

    if job.project.video.codec == "libx264":
        command.extend(["-preset", job.project.video.preset])
        if is_still_background:
            command.extend(["-tune", "stillimage"])
    elif job.project.video.preset:
        command.extend(["-preset", job.project.video.preset])

    command.extend(
        [
            "-c:a",
            "aac",
            "-b:a",
            job.project.video.audio_bitrate,
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-t",
            f"{job.duration_seconds:.3f}",
            "-shortest",
            str(job.video_path),
        ]
    )

    try:
        _run(command, cwd=job.output_dir)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() or exc.stdout.strip()
        raise RuntimeError(f"FFmpeg render failed:\n{stderr}") from exc
