from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from focus_music_video.ffmpeg_tools import concat_audio_tracks, probe_duration


CREDIT_KEYS = [
    "Music:",
    "License:",
    "Free Download / Stream:",
    "Music promoted by Audio Library:",
]

TITLE_PREFIX_PATTERN = re.compile(r"^\s*DAILY No Copyright For You\s*[–—-]\s*", re.IGNORECASE)
LEADING_BRACKET_TAG_PATTERN = re.compile(r"^\s*(?:\[[^\]]+\]\s*)+", re.IGNORECASE)
TRAILING_DECORATION_PATTERN = re.compile(r"[\s\u266a\u266b\U0001F3B5\U0001F3B6]+$")
MUSIC_LINE_URL_PATTERN = re.compile(r"\s+https?://\S+\s*$")
QUOTED_SEGMENT_PATTERN = re.compile(r"[\"“”'‘’]\s*([^\"“”'‘’]+?)\s*[\"“”'‘’]")


@dataclass(slots=True)
class MixTrack:
    index: int
    video_id: str
    title: str
    duration_seconds: float
    start_seconds: float
    audio_path: Path
    webpage_url: str
    credits: list[str]


@dataclass(slots=True)
class SkippedMixItem:
    video_id: str
    reason: str


@dataclass(slots=True)
class MixBuildResult:
    source_name: str
    dataset_type: str
    mix_name: str
    output_dir: Path
    audio_path: Path
    tracklist_path: Path
    credits_path: Path
    description_blocks_path: Path
    manifest_path: Path
    total_duration_seconds: float
    tracks: list[MixTrack]
    skipped_items: list[SkippedMixItem]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_video_id(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    video_ids = query.get("v")
    if video_ids and video_ids[0].strip():
        return video_ids[0].strip()

    if parsed.netloc in {"youtu.be", "www.youtu.be"} and parsed.path.strip("/"):
        return parsed.path.strip("/")

    raise ValueError(f"Could not extract YouTube video id from URL: {url}")


def _format_timestamp(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _pick_audio_file(item_dir: Path) -> Path:
    audio_dir = item_dir / "audio"
    candidates = sorted(path for path in audio_dir.iterdir() if path.is_file())
    if not candidates:
        raise FileNotFoundError(f"No audio file found in: {audio_dir}")
    return candidates[0]


def _clean_track_title(raw_title: str, credits: list[str]) -> str:
    title = TITLE_PREFIX_PATTERN.sub("", raw_title.strip())
    title = LEADING_BRACKET_TAG_PATTERN.sub("", title).strip()
    quoted = QUOTED_SEGMENT_PATTERN.search(title)
    if quoted:
        candidate = TRAILING_DECORATION_PATTERN.sub("", quoted.group(1)).strip()
        if candidate:
            return candidate

    title = (
        title.replace('"', " ")
        .replace("“", " ")
        .replace("”", " ")
        .replace("'", " ")
        .replace("‘", " ")
        .replace("’", " ")
    )
    title = re.sub(r"\s+", " ", title).strip(" -|:/")
    title = TRAILING_DECORATION_PATTERN.sub("", title).strip()
    if title:
        return title

    music_line = next((line for line in credits if line.startswith("Music:")), "")
    if music_line:
        content = music_line[len("Music:") :].strip()
        content = MUSIC_LINE_URL_PATTERN.sub("", content).strip()
        if content:
            return content
    return raw_title.strip() or "Unknown Track"


def _is_separator_line(value: str) -> bool:
    if not value:
        return False
    return all(char in {"_", "-", "=", " ", "\t"} for char in value)


def _extract_generic_credit_lines(lines: list[str]) -> list[str]:
    cleaned = [line for line in lines if line and not _is_separator_line(line)]
    if len(cleaned) > 1:
        cleaned = cleaned[1:]

    if not cleaned:
        return []

    keywords = (
        "license",
        "credit",
        "copyright",
        "free to use",
        "use this music",
        "download",
        "stream",
        "song name",
        "tag",
        "mention",
        "permission",
        "promoted by",
    )

    captured: list[str] = []
    started = False
    for line in cleaned:
        lowered = line.casefold()
        if any(keyword in lowered for keyword in keywords):
            started = True
            captured.append(line)
            if len(captured) >= 8:
                break
            continue

        if started:
            captured.append(line)
            if len(captured) >= 8:
                break

    if captured:
        return captured
    return cleaned[:6]


def _extract_credit_lines(description_path: Path) -> list[str]:
    text = description_path.read_text(encoding="utf-8", errors="ignore")
    lines = [line.strip() for line in text.splitlines()]
    credits: list[str] = []
    for key in CREDIT_KEYS:
        match = next((line for line in lines if line.startswith(key)), None)
        if not match:
            generic = _extract_generic_credit_lines(lines)
            if generic:
                return generic
            raise ValueError(f"Missing credit line '{key}' in {description_path}")
        credits.append(match)
    return credits


def _load_source_entries(config_path: Path, source_name: str) -> list[dict]:
    payload = _read_json(config_path)
    entries = [
        entry
        for entry in payload.get("sources", [])
        if entry.get("enabled", True) and entry.get("name") == source_name
    ]
    if not entries:
        raise ValueError(f"No enabled source entries found for '{source_name}' in {config_path}")
    return entries


def build_audio_mix(
    source_name: str,
    mix_name: str,
    config_path: str | Path,
    dataset_root: str | Path,
    output_root: str | Path,
    audio_bitrate: str = "192k",
    selected_urls: list[str] | None = None,
) -> MixBuildResult:
    config_file = Path(config_path).resolve()
    dataset_base = Path(dataset_root).resolve()
    output_base = Path(output_root).resolve()

    source_entries = _load_source_entries(config_file, source_name)
    dataset_types = {entry["dataset_type"] for entry in source_entries}
    if len(dataset_types) != 1:
        raise ValueError(
            f"Source '{source_name}' maps to multiple dataset types: {sorted(dataset_types)}"
        )

    dataset_type = next(iter(dataset_types))
    channel_root = dataset_base / dataset_type / source_name
    items_root = channel_root / "items"
    if not items_root.exists():
        raise FileNotFoundError(f"Dataset items directory not found: {items_root}")

    ordered_video_ids: list[str] = []
    seen_ids: set[str] = set()
    source_urls = selected_urls if selected_urls else [str(entry["url"]) for entry in source_entries]
    for url in source_urls:
        video_id = _extract_video_id(url)
        if video_id in seen_ids:
            continue
        seen_ids.add(video_id)
        ordered_video_ids.append(video_id)

    tracks: list[MixTrack] = []
    skipped_items: list[SkippedMixItem] = []
    current_start_seconds = 0.0
    concat_inputs: list[Path] = []

    for video_id in ordered_video_ids:
        item_dir = items_root / video_id
        metadata_dir = item_dir / "metadata"
        try:
            manifest = _read_json(metadata_dir / "manifest.json")
            description_path = metadata_dir / f"{video_id}.description"
            credits = _extract_credit_lines(description_path)
            title = _clean_track_title(str(manifest.get("title", "")).strip(), credits)
            audio_path = _pick_audio_file(item_dir)
            duration_seconds = probe_duration(audio_path)
            if duration_seconds <= 0:
                raise ValueError(f"Invalid duration in {metadata_dir / 'manifest.json'}")
        except (FileNotFoundError, ValueError) as exc:
            skipped_items.append(
                SkippedMixItem(
                    video_id=video_id,
                    reason=str(exc),
                )
            )
            continue

        concat_inputs.append(audio_path)
        tracks.append(
            MixTrack(
                index=len(tracks) + 1,
                video_id=video_id,
                title=title,
                duration_seconds=duration_seconds,
                start_seconds=current_start_seconds,
                audio_path=audio_path,
                webpage_url=str(manifest.get("webpage_url") or ""),
                credits=credits,
            )
        )
        current_start_seconds += duration_seconds

    if not concat_inputs:
        skipped_summary = "; ".join(
            f"{item.video_id}: {item.reason}" for item in skipped_items[:3]
        )
        raise ValueError(
            f"No usable crawled items found for '{source_name}'. "
            f"Details: {skipped_summary or 'no valid items were available'}"
        )

    output_dir = output_base / source_name / mix_name
    audio_dir = output_dir / "audio"
    metadata_dir = output_dir / "metadata"
    audio_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)

    audio_path = audio_dir / "audio_final.m4a"
    tracklist_path = metadata_dir / "tracklist.txt"
    credits_path = metadata_dir / "music_credits.txt"
    description_blocks_path = metadata_dir / "youtube_description_blocks.md"
    manifest_path = metadata_dir / "mix_manifest.json"

    concat_audio_tracks(concat_inputs, audio_path, audio_bitrate=audio_bitrate)

    tracklist_text = "\n".join(
        f"{_format_timestamp(track.start_seconds)} {track.title}" for track in tracks
    )
    tracklist_path.write_text(tracklist_text + "\n", encoding="utf-8")

    credit_sections: list[str] = ["🎵 Music Credits:"]
    for track in tracks:
        credit_sections.extend(
            [
                "",
                f"Track {track.index}: {track.title}",
                "",
                *track.credits,
            ]
        )
    credits_text = "\n".join(credit_sections).strip() + "\n"
    credits_path.write_text(credits_text, encoding="utf-8")

    combined_text = (
        "Tracklist (Cho người xem)\n"
        f"{tracklist_text}\n\n"
        "Phần Bản quyền (Cho YouTube & Tác giả)\n"
        f"{credits_text}"
    )
    description_blocks_path.write_text(combined_text, encoding="utf-8")

    manifest_payload = {
        "source_name": source_name,
        "dataset_type": dataset_type,
        "mix_name": mix_name,
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "selected_source_urls": source_urls,
        "output": {
            "directory": str(output_dir),
            "audio": str(audio_path),
            "tracklist": str(tracklist_path),
            "music_credits": str(credits_path),
            "description_blocks": str(description_blocks_path),
        },
        "total_duration_seconds": current_start_seconds,
        "requested_item_count": len(ordered_video_ids),
        "track_count": len(tracks),
        "skipped_item_count": len(skipped_items),
        "skipped_items": [asdict(item) for item in skipped_items],
        "tracks": [
            {
                **asdict(track),
                "audio_path": str(track.audio_path),
            }
            for track in tracks
        ],
    }
    manifest_path.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return MixBuildResult(
        source_name=source_name,
        dataset_type=dataset_type,
        mix_name=mix_name,
        output_dir=output_dir,
        audio_path=audio_path,
        tracklist_path=tracklist_path,
        credits_path=credits_path,
        description_blocks_path=description_blocks_path,
        manifest_path=manifest_path,
        total_duration_seconds=current_start_seconds,
        tracks=tracks,
        skipped_items=skipped_items,
    )
