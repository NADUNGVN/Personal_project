from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from proglog import ProgressBarLogger

from dotenv import load_dotenv

import imageio_ffmpeg
ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

# MoviePy compatibility imports
try:
    from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
    from moviepy.video.compositing.CompositeVideoClip import concatenate_videoclips
    from moviepy.video.VideoClip import ColorClip, ImageClip
    from moviepy.video.io.VideoFileClip import VideoFileClip
    from moviepy.audio.io.AudioFileClip import AudioFileClip
    from moviepy.audio.AudioClip import CompositeAudioClip, concatenate_audioclips
except ImportError:
    try:
        from moviepy import (
            CompositeVideoClip,
            ColorClip,
            ImageClip,
            VideoFileClip,
            AudioFileClip,
            CompositeAudioClip,
            concatenate_audioclips,
            concatenate_videoclips,
        )
    except ImportError:
        from moviepy.editor import (
            CompositeVideoClip,
            ColorClip,
            ImageClip,
            VideoFileClip,
            AudioFileClip,
            CompositeAudioClip,
            concatenate_audioclips,
            concatenate_videoclips,
        )

APP_NAME = "SocialHarvester CopyIdea"
APP_STEP = "Step 3: Render Long Videos (16:9 + 9:16)"
APP_VERSION = "1.0.0"

LONG_LANDSCAPE_SIZE = (1920, 1080)
LONG_PORTRAIT_SIZE = (1080, 1920)

DEFAULT_FONT_PATH = "arialbd.ttf"
DEFAULT_TITLE_COLOR = "white"
DEFAULT_TEXT_COLOR = "white"

DEFAULT_BGM_VOLUME = 0.18

# TODO(copy-idea): implement karaoke logic for long-form based on
# D:/work/Personal_project/make_video_with_image/scripts/video_renderer.py
AUDIO_DISPLAY_STYLE = "pending_video_renderer_tuning"


class SingleLineRenderLogger(ProgressBarLogger):
    def __init__(self, label: str = "RENDER", width: int = 36, progress_callback=None):
        super().__init__()
        self.label = label
        self.width = width
        self._last_percent = -1
        self._active_bar: str | None = None
        self._bar_totals: dict[str, float] = {}
        self._progress_callback = progress_callback

    def _print_progress(self, percent: int) -> None:
        percent = max(0, min(100, int(percent)))
        filled = int(self.width * percent / 100)
        bar = "#" * filled + "-" * (self.width - filled)
        print(f"\r[{self.label}] [{bar}] {percent:3d}%", end="", flush=True)
        if self._progress_callback is not None:
            self._progress_callback(percent)

    def start(self) -> None:
        self._last_percent = 0
        self._print_progress(0)

    def bars_callback(self, bar, attr, value, old_value=None):
        if attr == "total":
            try:
                total = float(value)
            except Exception:
                return
            if total > 0:
                self._bar_totals[bar] = total
                if self._active_bar is None or bar in {"frame_index", "t"}:
                    self._active_bar = bar
            return

        if attr != "index":
            return

        if self._active_bar is None:
            self._active_bar = bar
        elif bar != self._active_bar:
            if bar in {"frame_index", "t"} and self._active_bar not in {"frame_index", "t"}:
                self._active_bar = bar
            elif self._active_bar not in self._bar_totals and bar in self._bar_totals:
                self._active_bar = bar
            else:
                return

        total = self._bar_totals.get(self._active_bar)
        if not total:
            info = self.bars.get(self._active_bar, {})
            try:
                total = float(info.get("total") or 0.0)
            except Exception:
                total = 0.0
            if total <= 0:
                return
            self._bar_totals[self._active_bar] = total

        try:
            index = float(value)
        except Exception:
            return

        percent = int((index / total) * 100)
        if percent != self._last_percent:
            self._last_percent = percent
            self._print_progress(percent)

    def finish(self) -> None:
        if self._last_percent < 100:
            self._print_progress(100)
        print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render long videos from manual content and generated narration audio.")
    parser.add_argument("--project-dir", type=Path, help="Path to the specific project directory")
    parser.add_argument("--media-path", type=Path, help="Path to source media (image/gif/video)")
    parser.add_argument("--music-path", type=Path, help="Optional path to background music")
    parser.add_argument("--font", default=DEFAULT_FONT_PATH, help="Path to TrueType font file")
    return parser.parse_args()


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def is_nonempty_file(path: Path) -> bool:
    try:
        return path.exists() and path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def normalize_text(text: str) -> str:
    return " ".join((text or "").split())


def prompt_existing_file(prompt_text: str, allow_empty: bool = False) -> Path | None:
    while True:
        value = input(prompt_text).strip()
        if not value and allow_empty:
            return None
        if not value:
            print("Input cannot be empty. Please try again.")
            continue

        path = Path(value.strip().strip('"').strip("'"))
        if path.exists() and path.is_file():
            return path.resolve()

        print(f"File not found: {path}")


def resolve_latest_project_dir(base_output_dir: Path) -> Path:
    candidates = []
    if base_output_dir.exists():
        for date_dir in base_output_dir.iterdir():
            if not date_dir.is_dir():
                continue
            for proj_dir in date_dir.iterdir():
                if proj_dir.is_dir() and (proj_dir / "01_content" / "content.json").exists() and (proj_dir / "02_audio" / "audio.wav").exists():
                    candidates.append(proj_dir)

    if not candidates:
        raise RuntimeError(f"No valid project directories found with Step 1 & 2 completed in {base_output_dir}")

    candidates.sort(key=lambda p: p.stat().st_ctime, reverse=True)
    return candidates[0]


def fit_cover_clip(clip, target_w: int, target_h: int):
    ratio_clip = clip.w / clip.h
    ratio_target = target_w / target_h

    if ratio_clip > ratio_target:
        resized = clip.resized(height=target_h)
        x = max(0, int((resized.w - target_w) // 2))
        return resized.cropped(x1=x, width=target_w)

    resized = clip.resized(width=target_w)
    y = max(0, int((resized.h - target_h) // 2))
    return resized.cropped(y1=y, height=target_h)


def fit_contain_clip(clip, target_w: int, target_h: int):
    ratio_clip = clip.w / clip.h
    ratio_target = target_w / target_h

    if ratio_clip > ratio_target:
        return clip.resized(width=target_w)
    return clip.resized(height=target_h)


def clip_without_audio(clip):
    if hasattr(clip, "without_audio"):
        return clip.without_audio()
    if hasattr(clip, "set_audio"):
        return clip.set_audio(None)
    return clip


def ensure_video_duration(clip, duration: float):
    duration = float(duration)
    clip_duration = float(getattr(clip, "duration", 0.0) or 0.0)

    if clip_duration <= 0:
        return clip.with_duration(duration)

    if clip_duration >= duration:
        return clip.subclipped(0, duration)

    parts = []
    remaining = duration
    while remaining > 0:
        take = min(clip_duration, remaining)
        parts.append(clip.subclipped(0, take))
        remaining -= take

    merged = concatenate_videoclips(parts)
    return merged.with_duration(duration)


def ensure_audio_duration(clip, duration: float):
    duration = float(duration)
    clip_duration = float(getattr(clip, "duration", 0.0) or 0.0)

    if clip_duration <= 0:
        return clip.with_duration(duration)

    if clip_duration >= duration:
        return clip.subclipped(0, duration)

    parts = []
    remaining = duration
    while remaining > 0:
        take = min(clip_duration, remaining)
        parts.append(clip.subclipped(0, take))
        remaining -= take

    merged = concatenate_audioclips(parts)
    return merged.with_duration(duration)


def make_text_overlay(
    text: str,
    frame_size: tuple[int, int],
    box_size: tuple[int, int],
    top_left: tuple[int, int],
    font_path: str,
    font_size: int,
    text_color: str,
    fill_color: tuple[int, int, int, int] | None = None,
    rounded_radius: int = 0,
    center: bool = True,
):
    width, height = frame_size
    box_w, box_h = box_size
    x0, y0 = top_left

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    try:
        font = ImageFont.truetype(font_path, font_size)
    except Exception:
        font = ImageFont.load_default()

    if fill_color is not None:
        shape = (x0, y0, x0 + box_w, y0 + box_h)
        if rounded_radius > 0:
            draw.rounded_rectangle(shape, radius=rounded_radius, fill=fill_color)
        else:
            draw.rectangle(shape, fill=fill_color)

    max_text_width = max(100, box_w - 40)
    words = normalize_text(text).split()
    lines: list[str] = []
    current_line: list[str] = []
    for w in words:
        trial = " ".join(current_line + [w])
        box = draw.textbbox((0, 0), trial, font=font)
        trial_width = box[2] - box[0]
        if trial_width <= max_text_width or not current_line:
            current_line.append(w)
        else:
            lines.append(" ".join(current_line))
            current_line = [w]
    if current_line:
        lines.append(" ".join(current_line))

    if not lines:
        lines = [""]

    line_h = font_size + 10
    total_h = line_h * len(lines)
    text_y = y0 + max(12, int((box_h - total_h) / 2))

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        if center:
            text_x = x0 + max(10, int((box_w - line_w) / 2))
        else:
            text_x = x0 + 20
        draw.text((text_x, text_y), line, font=font, fill=text_color)
        text_y += line_h

    return ImageClip(np.array(image))


def make_preview_caption(text: str, max_words: int = 28) -> str:
    words = normalize_text(text).split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]) + "..."


def apply_volume(clip, factor: float):
    if hasattr(clip, "with_volume_scaled"):
        return clip.with_volume_scaled(factor)
    if hasattr(clip, "volumex"):
        return clip.volumex(factor)
    return clip


def build_media_clip(media_path: Path, duration: float):
    ext = media_path.suffix.lower()
    image_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

    if ext in image_exts:
        return ImageClip(str(media_path)).with_duration(duration)

    clip = VideoFileClip(str(media_path))
    clip = clip_without_audio(clip)
    return ensure_video_duration(clip, duration)


def build_final_audio(voice_audio_path: Path, music_path: Path | None, duration: float):
    voice_audio = AudioFileClip(str(voice_audio_path))
    voice_audio = ensure_audio_duration(voice_audio, duration)

    if music_path is None:
        return voice_audio

    music_audio = AudioFileClip(str(music_path))
    music_audio = ensure_audio_duration(music_audio, duration)
    music_audio = apply_volume(music_audio, DEFAULT_BGM_VOLUME)

    mixed = CompositeAudioClip([voice_audio, music_audio])
    return mixed.with_duration(duration)


def validate_rendered_video(video_path: Path) -> tuple[bool, float, str]:
    if not video_path.exists():
        return False, 0.0, "Missing output video file."

    try:
        file_size = video_path.stat().st_size
    except OSError as exc:
        return False, 0.0, f"Cannot read output file metadata: {exc}"

    if file_size <= 0:
        return False, 0.0, "Output video file is empty."

    clip = None
    try:
        clip = VideoFileClip(str(video_path))
        duration = float(clip.duration or 0.0)
    except Exception as exc:
        return False, 0.0, f"Cannot open rendered video: {exc}"
    finally:
        if clip is not None:
            clip.close()

    if duration <= 0.0:
        return False, duration, "Rendered video duration is invalid."

    return True, duration, ""


def render_clip(final_clip, out_path: Path, label: str, progress_callback=None):
    logger = SingleLineRenderLogger(label=label, progress_callback=progress_callback)
    logger.start()
    final_clip.write_videofile(
        str(out_path),
        fps=30,
        codec="libx264",
        audio_codec="aac",
        threads=4,
        logger=logger,
    )
    logger.finish()


def build_long_landscape_video(media_clip, final_audio, title: str, caption: str, font_path: str):
    width, height = LONG_LANDSCAPE_SIZE
    duration = float(final_audio.duration or 0.0)

    media_layer = fit_cover_clip(media_clip, width, height).with_duration(duration).with_position(("center", "center"))

    title_overlay = make_text_overlay(
        text=title,
        frame_size=(width, height),
        box_size=(1400, 120),
        top_left=(260, 40),
        font_path=font_path,
        font_size=56,
        text_color=DEFAULT_TITLE_COLOR,
        fill_color=(0, 0, 0, 120),
        rounded_radius=26,
    ).with_duration(duration)

    caption_overlay = make_text_overlay(
        text=caption,
        frame_size=(width, height),
        box_size=(1560, 180),
        top_left=(180, 860),
        font_path=font_path,
        font_size=42,
        text_color=DEFAULT_TEXT_COLOR,
        fill_color=(0, 0, 0, 150),
        rounded_radius=20,
    ).with_duration(duration)

    final = CompositeVideoClip([media_layer, title_overlay, caption_overlay], size=(width, height))
    return final.with_audio(final_audio).with_duration(duration)


def build_long_portrait_video(media_clip, final_audio, title: str, caption: str, font_path: str):
    width, height = LONG_PORTRAIT_SIZE
    duration = float(final_audio.duration or 0.0)

    bg = ColorClip(size=(width, height), color=(0, 0, 0)).with_duration(duration)

    media_box_w = 1000
    media_box_h = 760
    media_y = 560
    media_centered = fit_contain_clip(media_clip, media_box_w, media_box_h)
    media_x = int((width - media_centered.w) // 2)
    media_layer = media_centered.with_duration(duration).with_position((media_x, media_y))

    title_overlay = make_text_overlay(
        text=title,
        frame_size=(width, height),
        box_size=(860, 180),
        top_left=(110, 180),
        font_path=font_path,
        font_size=62,
        text_color="black",
        fill_color=(255, 255, 255, 240),
        rounded_radius=24,
    ).with_duration(duration)

    # Placeholder caption area for long-form karaoke style.
    caption_overlay = make_text_overlay(
        text=caption,
        frame_size=(width, height),
        box_size=(940, 180),
        top_left=(70, 1400),
        font_path=font_path,
        font_size=48,
        text_color=DEFAULT_TEXT_COLOR,
        fill_color=(0, 0, 0, 180),
        rounded_radius=18,
    ).with_duration(duration)

    final = CompositeVideoClip([bg, media_layer, title_overlay, caption_overlay], size=(width, height))
    return final.with_audio(final_audio).with_duration(duration)


def main() -> None:
    print(f"{APP_NAME} - {APP_STEP} (v{APP_VERSION})")
    args = parse_args()

    script_dir = Path(__file__).resolve().parent
    base_output_dir = script_dir / "output" / "long_video"

    proj_dir = args.project_dir
    if not proj_dir:
        print("[INFO] No --project-dir provided. Resolving latest valid project...")
        proj_dir = resolve_latest_project_dir(base_output_dir)

    proj_dir = proj_dir.resolve()
    print(f"[INFO] Target Project: {proj_dir}")

    content_file = proj_dir / "01_content" / "content.json"
    audio_file = proj_dir / "02_audio" / "audio.wav"

    if not content_file.exists() or not audio_file.exists():
        raise SystemExit("Missing content.json or audio.wav. Ensure Step 1 and Step 2 completed.")

    content_data = json.loads(content_file.read_text(encoding="utf-8"))
    title = normalize_text(content_data.get("title_en") or content_data.get("topic") or "Untitled")
    text = normalize_text(content_data.get("text_en", ""))
    if not text:
        raise SystemExit("content.json has empty text_en.")

    vid_dir = proj_dir / "03_video"
    vid_dir.mkdir(parents=True, exist_ok=True)

    render_status_path = vid_dir / "render_status.json"
    sources_path = vid_dir / "sources.json"

    previous_sources = {}
    if sources_path.exists():
        try:
            previous_sources = json.loads(sources_path.read_text(encoding="utf-8"))
        except Exception:
            previous_sources = {}

    media_path = args.media_path or (Path(previous_sources.get("media_path")) if previous_sources.get("media_path") else None)
    if media_path is None or not media_path.exists():
        media_path = prompt_existing_file("Enter media path (image/gif/video): ")

    music_path = args.music_path
    if music_path is None and previous_sources.get("music_path"):
        candidate = Path(previous_sources.get("music_path"))
        if candidate.exists():
            music_path = candidate

    if music_path is None:
        music_path = prompt_existing_file("Enter background music path (optional, ENTER to skip): ", allow_empty=True)

    if music_path is not None and not music_path.exists():
        print(f"[WARN] music path not found, skipping BGM: {music_path}")
        music_path = None

    media_path = media_path.resolve()
    if music_path is not None:
        music_path = music_path.resolve()

    write_json(
        sources_path,
        {
            "media_path": str(media_path),
            "music_path": str(music_path) if music_path else "",
            "audio_display_style": AUDIO_DISPLAY_STYLE,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        },
    )

    voice_audio = AudioFileClip(str(audio_file))
    duration = float(voice_audio.duration or 0.0)
    voice_audio.close()

    if duration <= 0:
        raise SystemExit("Invalid audio duration in 02_audio/audio.wav")

    status = {
        "status": "rendering",
        "success": False,
        "progress_percent": 0,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "project_dir": str(proj_dir),
        "outputs": {},
    }
    write_json(render_status_path, status)

    long_16_path = vid_dir / "long_video_16x9.mp4"
    long_9_path = vid_dir / "long_video_9x16.mp4"

    media_clip = None
    final_audio = None
    landscape = None
    portrait = None

    try:
        media_clip = build_media_clip(media_path, duration)
        final_audio = build_final_audio(audio_file, music_path, duration)

        caption = make_preview_caption(text)

        landscape = build_long_landscape_video(media_clip, final_audio, title, caption, args.font)
        render_clip(
            landscape,
            long_16_path,
            label="LONG-16:9",
            progress_callback=lambda p: status.update({"progress_percent": min(49, int(p // 2))}),
        )
        ok16, dur16, err16 = validate_rendered_video(long_16_path)
        if not ok16:
            raise RuntimeError(f"16:9 render failed validation: {err16}")
        status["outputs"]["16x9"] = {
            "path": str(long_16_path),
            "duration_sec": round(dur16, 3),
            "file_size_bytes": long_16_path.stat().st_size,
        }
        status["updated_at"] = datetime.now().isoformat(timespec="seconds")
        status["progress_percent"] = 50
        write_json(render_status_path, status)

        portrait = build_long_portrait_video(media_clip, final_audio, title, caption, args.font)
        render_clip(
            portrait,
            long_9_path,
            label="LONG-9:16",
            progress_callback=lambda p: status.update({"progress_percent": 50 + int(p // 2)}),
        )
        ok9, dur9, err9 = validate_rendered_video(long_9_path)
        if not ok9:
            raise RuntimeError(f"9:16 render failed validation: {err9}")
        status["outputs"]["9x16"] = {
            "path": str(long_9_path),
            "duration_sec": round(dur9, 3),
            "file_size_bytes": long_9_path.stat().st_size,
        }

        status.update(
            {
                "status": "completed",
                "success": True,
                "progress_percent": 100,
                "completed_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        write_json(render_status_path, status)
    except Exception as exc:
        status.update(
            {
                "status": "failed",
                "success": False,
                "error": str(exc),
                "failed_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        write_json(render_status_path, status)
        raise
    finally:
        for clip in (landscape, portrait, final_audio, media_clip):
            if clip is not None:
                try:
                    clip.close()
                except Exception:
                    pass

    print(f"\n[DONE] Long videos rendered:")
    print(f"- {long_16_path}")
    print(f"- {long_9_path}")


if __name__ == "__main__":
    main()
