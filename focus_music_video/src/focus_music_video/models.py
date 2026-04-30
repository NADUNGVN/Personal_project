from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class VideoSettings:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    codec: str = "libx264"
    preset: str = "medium"
    audio_bitrate: str = "192k"


@dataclass(slots=True)
class AudioSettings:
    volume: float = 1.0
    fade_in: float = 2.5
    fade_out: float = 4.0


@dataclass(slots=True)
class TextOverlaySettings:
    enabled: bool = True
    font_file: str | None = "C:/Windows/Fonts/arial.ttf"
    line_spacing: int = 10


@dataclass(slots=True)
class ProjectConfig:
    project_file: Path
    title: str
    concept: str
    music_path: Path
    background_path: Path
    output_root: Path
    profiles: list[str]
    shared_keywords: list[str] = field(default_factory=list)
    shared_hashtags: list[str] = field(default_factory=list)
    shared_description_lines: list[str] = field(default_factory=list)
    video: VideoSettings = field(default_factory=VideoSettings)
    audio: AudioSettings = field(default_factory=AudioSettings)
    text_overlay: TextOverlaySettings = field(default_factory=TextOverlaySettings)
    channel_overrides: dict[str, dict] = field(default_factory=dict)


@dataclass(slots=True)
class VisualProfile:
    dim_opacity: float = 0.18
    brightness: float = -0.02
    saturation: float = 1.0
    box_color: str = "#10151B"
    box_opacity: float = 0.32
    accent_color: str = "#E6C07B"
    title_color: str = "#FFFFFF"
    subtitle_color: str = "#D9E7F2"
    box_x: str = "(w*0.06)"
    box_y: str = "(h*0.68)"
    box_width: str = "(w*0.46)"
    box_height: str = "(h*0.20)"
    accent_x: str = "(w*0.06)"
    accent_y: str = "(h*0.66)"
    accent_width: str = "(w*0.14)"
    accent_height: int = 10
    title_x: str = "(w*0.09)"
    title_y: str = "(h*0.72)"
    subtitle_x: str = "(w*0.09)"
    subtitle_y: str = "(h*0.82)"
    title_font_size: int = 58
    subtitle_font_size: int = 30


@dataclass(slots=True)
class ChannelProfile:
    order: int
    slug: str
    channel_name: str
    positioning: str
    use_case: str
    overlay_title_template: str
    overlay_subtitle_template: str
    metadata_title_template: str
    metadata_summary_template: str
    keywords: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    visual: VisualProfile = field(default_factory=VisualProfile)


@dataclass(slots=True)
class BuildJob:
    profile: ChannelProfile
    project: ProjectConfig
    output_dir: Path
    video_path: Path
    manifest_path: Path
    metadata_json_path: Path
    metadata_md_path: Path
    overlay_title_path: Path
    overlay_subtitle_path: Path
    duration_seconds: float
    duration_label: str
    overlay_title: str
    overlay_subtitle: str
    metadata_title: str
    metadata_summary: str
    keywords: list[str]
    hashtags: list[str]
    is_preview: bool = False
