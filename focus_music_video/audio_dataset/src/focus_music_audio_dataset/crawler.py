from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from shutil import which
from typing import Any

import yt_dlp
from yt_dlp.networking.impersonate import ImpersonateTarget

from focus_music_audio_dataset.models import SourceConfig
from focus_music_audio_dataset.utils import short_url_key, slugify


AUDIO_EXTENSIONS = {
    ".m4a",
    ".mp3",
    ".aac",
    ".wav",
    ".flac",
    ".opus",
    ".ogg",
    ".webm",
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

YOUTUBE_LIMIT_RATE_BYTES = 1 * 1024 * 1024
YOUTUBE_THROTTLED_RATE_BYTES = 100 * 1024
YOUTUBE_SLEEP_REQUESTS_SECONDS = 0.75
YOUTUBE_SLEEP_INTERVAL_SECONDS = 10
YOUTUBE_MAX_SLEEP_INTERVAL_SECONDS = 20
YOUTUBE_AUDIO_FORMAT_SELECTOR = "bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]/bestaudio/best"


def dataset_root(tool_root: Path) -> Path:
    return tool_root / "dataset"


def state_root(tool_root: Path) -> Path:
    return tool_root / "state"


def channel_root(tool_root: Path, source: SourceConfig) -> Path:
    return dataset_root(tool_root) / source.dataset_type / slugify(source.name)


def source_entry_key(source: SourceConfig) -> str:
    return short_url_key(source.url)


def download_archive_path(tool_root: Path, source: SourceConfig) -> Path:
    return state_root(tool_root) / "download_archives" / f"{source.dataset_type}_{slugify(source.name)}.txt"


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


def build_ydl_options(tool_root: Path, source: SourceConfig) -> dict[str, Any]:
    root = channel_root(tool_root, source)
    archive_path = download_archive_path(tool_root, source)

    root.mkdir(parents=True, exist_ok=True)
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    ydl_opts: dict[str, Any] = {
        "format": YOUTUBE_AUDIO_FORMAT_SELECTOR,
        "restrictfilenames": True,
        "windowsfilenames": True,
        "ignoreerrors": True,
        "noplaylist": False,
        "writethumbnail": True,
        "writeinfojson": True,
        "writedescription": True,
        "outtmpl": str(root / "items" / "%(id)s" / "%(id)s.%(ext)s"),
        "download_archive": str(archive_path),
        "impersonate": ImpersonateTarget(),
        "ratelimit": YOUTUBE_LIMIT_RATE_BYTES,
        "throttledratelimit": YOUTUBE_THROTTLED_RATE_BYTES,
        "sleep_interval_requests": YOUTUBE_SLEEP_REQUESTS_SECONDS,
        "sleep_interval": YOUTUBE_SLEEP_INTERVAL_SECONDS,
        "max_sleep_interval": YOUTUBE_MAX_SLEEP_INTERVAL_SECONDS,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
            }
        ],
        "keepvideo": False,
    }

    node_path = which("node")
    if node_path:
        ydl_opts["js_runtimes"] = {"node": {"path": node_path}}
    if source.max_items:
        ydl_opts["playlistend"] = source.max_items

    return ydl_opts


def classify_file(file_path: Path) -> str:
    lower_name = file_path.name.lower()
    ext = file_path.suffix.lower()

    if ext in AUDIO_EXTENSIONS:
        return "audio"
    if ext in THUMBNAIL_EXTENSIONS:
        return "thumbnails"
    if lower_name.endswith(".info.json"):
        return "metadata"
    if lower_name.endswith(".description"):
        return "metadata"
    if ext in {".json", ".txt", ".csv", ".xml"}:
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
        entries: list[dict[str, Any]] = []
        for entry in info.get("entries", []) or []:
            if isinstance(entry, dict):
                entries.append(entry)
        return entries
    return [info]


def build_item_manifest(item_dir: Path, source: SourceConfig, entry: dict[str, Any]) -> dict[str, Any]:
    grouped_files: dict[str, list[str]] = {}
    for category in ("audio", "metadata", "thumbnails", "other"):
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
        "source_name": source.name,
        "dataset_type": source.dataset_type,
        "purpose": source.purpose,
        "source_url": source.url,
        "tags": source.tags,
        "id": entry.get("id"),
        "title": entry.get("title"),
        "uploader": entry.get("uploader"),
        "channel": entry.get("channel"),
        "webpage_url": entry.get("webpage_url"),
        "duration_seconds": entry.get("duration"),
        "downloaded_at": datetime.now().isoformat(timespec="seconds"),
        "grouped_files": grouped_files,
    }


def write_item_manifests(tool_root: Path, source: SourceConfig, info: dict[str, Any]) -> None:
    root = channel_root(tool_root, source)
    for entry in iter_entry_dicts(info):
        entry_id = entry.get("id")
        if not entry_id:
            continue

        item_dir = root / "items" / str(entry_id)
        if not item_dir.exists():
            continue

        organize_item_directory(item_dir)
        metadata_dir = item_dir / "metadata"
        metadata_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = metadata_dir / "manifest.json"
        manifest = build_item_manifest(item_dir, source, entry)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def write_source_manifest(tool_root: Path, source: SourceConfig, probe_info: dict[str, Any] | None = None) -> None:
    root = channel_root(tool_root, source)
    root.mkdir(parents=True, exist_ok=True)
    sources_dir = root / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        **asdict(source),
        "slug": slugify(source.name),
        "source_entry_key": source_entry_key(source),
        "channel_title": probe_info.get("title") if probe_info else None,
        "channel_id": probe_info.get("channel_id") if probe_info else None,
        "extractor": probe_info.get("extractor_key") if probe_info else None,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    (sources_dir / f"{source_entry_key(source)}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_channel_manifest(tool_root: Path, source: SourceConfig) -> None:
    root = channel_root(tool_root, source)
    items_root = root / "items"
    item_manifests = sorted(items_root.rglob("metadata/manifest.json")) if items_root.exists() else []

    payload = {
        "source_name": source.name,
        "slug": slugify(source.name),
        "dataset_type": source.dataset_type,
        "purpose": source.purpose,
        "source_url": source.url,
        "tags": source.tags,
        "item_count": len(item_manifests),
        "source_entries": [],
        "items": [],
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }

    sources_dir = root / "sources"
    if sources_dir.exists():
        for source_manifest in sorted(sources_dir.glob("*.json")):
            data = json.loads(source_manifest.read_text(encoding="utf-8"))
            payload["source_entries"].append(
                {
                    "source_entry_key": data.get("source_entry_key"),
                    "source_url": data.get("url"),
                    "purpose": data.get("purpose"),
                    "tags": data.get("tags", []),
                    "path": str(source_manifest),
                }
            )

    for manifest_path in item_manifests:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["items"].append(
            {
                "id": data.get("id"),
                "title": data.get("title"),
                "duration_seconds": data.get("duration_seconds"),
                "webpage_url": data.get("webpage_url"),
                "item_dir": str(manifest_path.parents[1]),
            }
        )

    (root / "channel_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_dataset_summary(tool_root: Path) -> Path:
    root = dataset_root(tool_root)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "music_channels": [],
        "ambient_channels": [],
    }

    for dataset_type in ("music", "ambient"):
        manifests = sorted((root / dataset_type).rglob("channel_manifest.json")) if (root / dataset_type).exists() else []
        target_key = "music_channels" if dataset_type == "music" else "ambient_channels"
        for manifest_path in manifests:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload[target_key].append(
                {
                    "slug": data.get("slug"),
                    "source_name": data.get("source_name"),
                    "item_count": data.get("item_count"),
                    "path": str(manifest_path.parent),
                }
            )

    summary_path = root / "dataset_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary_path


def crawl_source(tool_root: Path, source: SourceConfig) -> Path:
    probe_info: dict[str, Any] | None
    try:
        probe_info = pre_extract_info(source.url)
    except Exception:
        probe_info = None

    write_source_manifest(tool_root, source, probe_info)
    ydl_opts = build_ydl_options(tool_root, source)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(source.url, download=True)

    if not isinstance(info, dict):
        if isinstance(probe_info, dict):
            info = probe_info
        else:
            raise RuntimeError(f"Could not extract metadata for source: {source.name}")

    write_item_manifests(tool_root, source, info)
    write_channel_manifest(tool_root, source)
    return channel_root(tool_root, source)
