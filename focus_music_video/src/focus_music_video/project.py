from __future__ import annotations

import json
from pathlib import Path

from focus_music_video.models import AudioSettings, ProjectConfig, TextOverlaySettings, VideoSettings
from focus_music_video.utils import resolve_path, slugify


DEFAULT_PROFILES = [
    "lofi_hiphop_jazz",
    "study_with_me_work_with_me",
    "ambient_aesthetic_video",
    "deep_sleep_relax",
]


def build_project_payload(title: str) -> dict:
    return {
        "title": title,
        "concept": "Warm rain, gentle lights and calm instrumental energy for long study or rest sessions.",
        "music": "input/audio/main_track.mp3",
        "background": "input/background/background.jpg",
        "output_root": "output",
        "profiles": DEFAULT_PROFILES,
        "shared_keywords": [
            "focus music",
            "study music",
            "relaxing background music",
            "music for deep work",
        ],
        "shared_hashtags": [
            "#focusmusic",
            "#studymusic",
            "#relaxingmusic",
            "#deepwork",
        ],
        "shared_description_lines": [
            "Use this package for study, reading, coding, journaling and slow work blocks.",
            "Keep each channel distinct in positioning even when the source track is shared.",
        ],
        "video": {
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "codec": "libx264",
            "preset": "medium",
            "audio_bitrate": "192k",
        },
        "audio": {
            "volume": 1.0,
            "fade_in": 2.5,
            "fade_out": 4.0,
        },
        "text_overlay": {
            "enabled": True,
            "font_file": "C:/Windows/Fonts/arial.ttf",
            "line_spacing": 10,
        },
        "channel_overrides": {},
    }


def load_project(project_file: str | Path) -> ProjectConfig:
    project_path = Path(project_file).resolve()
    if not project_path.exists():
        raise FileNotFoundError(f"Project file not found: {project_path}")

    payload = json.loads(project_path.read_text(encoding="utf-8"))
    base_dir = project_path.parent

    return ProjectConfig(
        project_file=project_path,
        title=payload.get("title", base_dir.name),
        concept=payload.get("concept", ""),
        music_path=resolve_path(base_dir, payload["music"]),
        background_path=resolve_path(base_dir, payload["background"]),
        output_root=resolve_path(base_dir, payload.get("output_root", "output")),
        profiles=payload.get("profiles", DEFAULT_PROFILES.copy()),
        shared_keywords=payload.get("shared_keywords", []),
        shared_hashtags=payload.get("shared_hashtags", []),
        shared_description_lines=payload.get("shared_description_lines", []),
        video=VideoSettings(**payload.get("video", {})),
        audio=AudioSettings(**payload.get("audio", {})),
        text_overlay=TextOverlaySettings(**payload.get("text_overlay", {})),
        channel_overrides=payload.get("channel_overrides", {}),
    )


def scaffold_project(project_root: str | Path, name: str, title: str | None = None) -> Path:
    project_root_path = Path(project_root).resolve()
    safe_name = slugify(name)
    project_dir = project_root_path / safe_name
    input_audio_dir = project_dir / "input" / "audio"
    input_background_dir = project_dir / "input" / "background"
    output_dir = project_dir / "output"

    if project_dir.exists() and any(project_dir.iterdir()):
        raise FileExistsError(f"Project directory already exists and is not empty: {project_dir}")

    input_audio_dir.mkdir(parents=True, exist_ok=True)
    input_background_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    project_title = title or name.strip() or safe_name
    project_payload = build_project_payload(project_title)

    (project_dir / "project.json").write_text(
        json.dumps(project_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (project_dir / "input" / "README.txt").write_text(
        "\n".join(
            [
                "Put your shared assets here:",
                "- input/audio/main_track.mp3",
                "- input/background/background.jpg",
                "",
                "Then update project.json if the filenames or paths differ.",
                "Use one source package and let the pipeline create four channel outputs.",
            ]
        ),
        encoding="utf-8",
    )

    return project_dir
