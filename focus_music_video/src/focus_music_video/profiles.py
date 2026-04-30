from __future__ import annotations

import json
from pathlib import Path

from focus_music_video.models import ChannelProfile, VisualProfile


def _profiles_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "channel_profiles"


def _build_profile(payload: dict) -> ChannelProfile:
    return ChannelProfile(
        order=payload["order"],
        slug=payload["slug"],
        channel_name=payload["channel_name"],
        positioning=payload["positioning"],
        use_case=payload["use_case"],
        overlay_title_template=payload["overlay_title_template"],
        overlay_subtitle_template=payload["overlay_subtitle_template"],
        metadata_title_template=payload["metadata_title_template"],
        metadata_summary_template=payload["metadata_summary_template"],
        keywords=payload.get("keywords", []),
        hashtags=payload.get("hashtags", []),
        visual=VisualProfile(**payload.get("visual", {})),
    )


def list_profiles() -> list[ChannelProfile]:
    profiles: list[ChannelProfile] = []
    for path in sorted(_profiles_dir().glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        profiles.append(_build_profile(payload))
    return sorted(profiles, key=lambda item: (item.order, item.slug))


def load_profile(slug: str) -> ChannelProfile:
    path = _profiles_dir() / f"{slug}.json"
    if not path.exists():
        available = ", ".join(profile.slug for profile in list_profiles())
        raise FileNotFoundError(f"Unknown profile '{slug}'. Available: {available}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _build_profile(payload)


def load_profiles(slugs: list[str]) -> list[ChannelProfile]:
    return [load_profile(slug) for slug in slugs]
