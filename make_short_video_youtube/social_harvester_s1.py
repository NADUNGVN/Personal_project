from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yt_dlp


APP_NAME = "SocialHarvester"
APP_STEP = "Step 1: Ingest"
APP_VERSION = "1.0.0"

SUPPORTED_PLATFORMS = ("youtube", "facebook", "instagram", "other")

MEDIA_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".webm",
    ".mov",
    ".m4v",
    ".m4a",
    ".mp3",
    ".aac",
    ".wav",
    ".flac",
    ".opus",
    ".ogg",
}
SUBTITLE_EXTENSIONS = {
    ".srt",
    ".vtt",
    ".ass",
    ".ssa",
    ".lrc",
    ".ttml",
    ".sbv",
    ".json3",
}
THUMBNAIL_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".gif",
    ".avif",
}


@dataclass(frozen=True)
class PlatformFeatures:
    writesubtitles: bool
    writeautomaticsub: bool
    writecomments: bool
    subtitleslangs: list[str]


PLATFORM_FEATURES = {
    "youtube": PlatformFeatures(
        writesubtitles=True,
        writeautomaticsub=True,
        writecomments=True,
        subtitleslangs=["vi", "en", "-live_chat"],
    ),
    "facebook": PlatformFeatures(
        writesubtitles=True,
        writeautomaticsub=True,
        writecomments=False,
        subtitleslangs=["vi", "en"],
    ),
    "instagram": PlatformFeatures(
        writesubtitles=False,
        writeautomaticsub=False,
        writecomments=False,
        subtitleslangs=[],
    ),
    "other": PlatformFeatures(
        writesubtitles=True,
        writeautomaticsub=False,
        writecomments=False,
        subtitleslangs=["vi", "en"],
    ),
}


def parse_args() -> argparse.Namespace:
    base_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Download and organize media data from Facebook, YouTube, Instagram.",
    )
    parser.add_argument("url", nargs="?", help="URL of video/reel/post")
    parser.add_argument(
        "--output",
        type=Path,
        default=base_dir / "output",
        help="Base output directory (default: ./output)",
    )
    parser.add_argument(
        "--allow-playlist",
        action="store_true",
        help="Allow playlist/channel style URL to download multiple entries.",
    )
    return parser.parse_args()


def detect_platform(url: str, extractor: str = "") -> str:
    host = urlparse(url).netloc.lower()
    extractor = extractor.lower()

    if "youtube" in host or "youtu.be" in host or "youtube" in extractor:
        return "youtube"
    if "facebook" in host or "fb.watch" in host or "facebook" in extractor:
        return "facebook"
    if "instagram" in host or "instagram" in extractor:
        return "instagram"
    return "other"


def pre_extract_info(url: str) -> dict[str, Any]:
    probe_opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "skip_download": True,
        "extract_flat": False,
    }
    with yt_dlp.YoutubeDL(probe_opts) as ydl:
        return ydl.extract_info(url, download=False)


def build_ydl_options(platform_root: Path, platform: str, allow_playlist: bool) -> dict[str, Any]:
    features = PLATFORM_FEATURES.get(platform, PLATFORM_FEATURES["other"])

    ydl_opts: dict[str, Any] = {
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "restrictfilenames": True,
        "windowsfilenames": True,
        "outtmpl": str(platform_root / "%(id)s" / "%(id)s.%(ext)s"),
        "writethumbnail": True,
        "writeinfojson": True,
        "writedescription": True,
        "writesubtitles": features.writesubtitles,
        "writeautomaticsub": features.writeautomaticsub,
        "writecomments": features.writecomments,
        "subtitleslangs": features.subtitleslangs,
        "ignoreerrors": True,
        "noplaylist": not allow_playlist,
    }
    return ydl_opts


def classify_file(file_path: Path) -> str:
    lower_name = file_path.name.lower()
    ext = file_path.suffix.lower()

    if ext in MEDIA_EXTENSIONS:
        return "media"
    if ext in SUBTITLE_EXTENSIONS:
        return "subtitles"
    if ext in THUMBNAIL_EXTENSIONS:
        return "thumbnails"

    if lower_name.endswith(".info.json"):
        return "metadata"
    if lower_name.endswith(".description"):
        return "metadata"
    if ext in {".json", ".txt", ".xml", ".csv"}:
        return "metadata"

    return "other"


def organize_item_directory(item_dir: Path) -> None:
    if not item_dir.is_dir():
        return

    for path in list(item_dir.iterdir()):
        if not path.is_file():
            continue
        category = classify_file(path)
        target_dir = item_dir / category
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / path.name
        if target_path.exists():
            target_path.unlink()
        path.replace(target_path)


def iter_entry_dicts(info: dict[str, Any]) -> list[dict[str, Any]]:
    if info.get("_type") == "playlist":
        entries = []
        for entry in info.get("entries", []) or []:
            if isinstance(entry, dict):
                entries.append(entry)
        return entries
    return [info]


def build_manifest(item_dir: Path, platform: str, source_url: str, entry: dict[str, Any]) -> dict[str, Any]:
    files = []
    for path in sorted(item_dir.rglob("*")):
        if path.is_file():
            files.append(str(path.relative_to(item_dir)))

    grouped_files: dict[str, list[str]] = {}
    for category in ("media", "metadata", "subtitles", "thumbnails", "other"):
        category_dir = item_dir / category
        if not category_dir.exists():
            grouped_files[category] = []
            continue
        grouped_files[category] = [
            str(path.relative_to(item_dir))
            for path in sorted(category_dir.rglob("*"))
            if path.is_file()
        ]

    return {
        "platform": platform,
        "source_url": source_url,
        "id": entry.get("id"),
        "title": entry.get("title"),
        "uploader": entry.get("uploader"),
        "channel": entry.get("channel"),
        "webpage_url": entry.get("webpage_url"),
        "duration_seconds": entry.get("duration"),
        "downloaded_at": datetime.now().isoformat(timespec="seconds"),
        "grouped_files": grouped_files,
        "files": files,
    }


def write_manifests(platform_root: Path, platform: str, source_url: str, info: dict[str, Any]) -> None:
    for entry in iter_entry_dicts(info):
        entry_id = entry.get("id")
        if not entry_id:
            continue

        item_dir = platform_root / str(entry_id)
        if not item_dir.exists():
            continue

        organize_item_directory(item_dir)
        metadata_dir = item_dir / "metadata"
        metadata_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = metadata_dir / "manifest.json"
        manifest = build_manifest(item_dir, platform, source_url, entry)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    print(f"{APP_NAME} - {APP_STEP} (v{APP_VERSION})")
    args = parse_args()
    url = (args.url or input("Nhap link video/reel/post: ").strip()).strip()
    if not url:
        raise SystemExit("Ban chua nhap URL.")

    output_root = args.output.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    try:
        probe_info = pre_extract_info(url)
        extractor_name = str(probe_info.get("extractor_key") or probe_info.get("extractor") or "")
    except Exception:
        probe_info = {}
        extractor_name = ""

    platform = detect_platform(url, extractor_name)
    if platform not in SUPPORTED_PLATFORMS:
        platform = "other"

    platform_root = output_root / platform
    platform_root.mkdir(parents=True, exist_ok=True)

    ydl_opts = build_ydl_options(platform_root, platform, args.allow_playlist)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
        if not isinstance(info, dict):
            raise RuntimeError("Khong trich xuat duoc metadata tu URL.")
        write_manifests(platform_root, platform, url, info)
        print(f"Tai xuong thanh cong. Du lieu luu tai: {platform_root}")
    except Exception as exc:
        raise SystemExit(f"Co loi xay ra: {exc}") from exc


if __name__ == "__main__":
    main()
