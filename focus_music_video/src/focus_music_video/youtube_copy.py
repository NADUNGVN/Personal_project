from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv


FORBIDDEN_TITLE_PHRASES = [
    "daily no copyright for you",
    "audio library",
    "no copyright",
]


PURPOSE_PROFILES = {
    "lofi_chill_lofi_hiphop_lofi_jazz": {
        "label": "Lo-fi Chill / Lo-fi Hip-hop / Lo-fi Jazz",
        "scene": "Quiet Lake",
        "title_candidates": [
            "{scene} Lo-fi | Soft Beats for Study, Focus & Chill",
            "{scene} Study Session | Lo-fi Beats for Focus & Relax",
            "Drift Into Focus | Calm Lo-fi Beats for Study & Chill",
            "Still Water Lo-fi | Chill Beats for Deep Focus",
            "Soft Afternoon Lo-fi | Study Beats for Work & Relax",
            "{minutes}-Minute {scene} Lo-fi | Focus Beats for Study",
            "{scene} Lo-fi Jazz & Chill Beats | Study / Work / Relax",
            "Gentle Drift Lo-fi | Beats for Reading, Study & Chill",
        ],
        "primary_hashtags": ["#lofi", "#studybeats", "#focusmusic"],
        "extended_hashtags": [
            "#lofihiphop",
            "#lofijazz",
            "#chillbeats",
            "#studymusic",
            "#workmusic",
            "#relaxmusic",
            "#backgroundmusic",
            "#calmvibes",
        ],
        "upload_tags": [
            "lofi",
            "study beats",
            "focus music",
            "lofi hip hop",
            "lofi jazz",
            "chill beats",
            "study music",
            "work music",
            "relaxing music",
            "background music",
            "deep focus music",
            "reading music",
            "calm music",
            "coffee shop lofi",
            "quiet lake lofi",
        ],
        "description_intro": [
            (
                "{title} is a calm {minutes}-minute lo-fi mix built for study, focus, "
                "reading, journaling, and slow evening chill."
            ),
            (
                "This set moves through soft lo-fi, mellow hip-hop textures, and warm jazz "
                "touches without pulling attention away from your work."
            ),
            (
                "Full tracklist and artist / license credits are below so you can find every "
                "song and support the original musicians."
            ),
        ],
    },
    "music_for_study": {
        "label": "Music for Study",
        "scene": "Quiet Desk",
        "title_candidates": [
            "{scene} Study Music | Deep Focus Beats for Reading & Work",
            "Deep Focus Session | Study Music for Work, Reading & Calm",
            "{minutes}-Minute Study Music | Gentle Beats for Focus",
        ],
        "primary_hashtags": ["#studymusic", "#focusmusic", "#deepfocus"],
        "extended_hashtags": [
            "#workmusic",
            "#readingmusic",
            "#calmmusic",
            "#backgroundmusic",
        ],
        "upload_tags": [
            "study music",
            "focus music",
            "deep focus music",
            "reading music",
            "work music",
        ],
        "description_intro": [
            "{title} is designed to keep your attention steady during study, work, and reading sessions.",
            "Expect a clean, calm atmosphere that supports concentration without becoming distracting.",
            "Tracklist and artist / license credits are listed below.",
        ],
    },
    "piano_ambient": {
        "label": "Piano + Ambient",
        "scene": "Still Room",
        "title_candidates": [
            "{scene} Piano Ambient | Soft Music for Focus, Sleep & Relax",
            "Piano + Ambient Calm | Gentle Focus Music for Work & Rest",
            "{minutes}-Minute Piano Ambient | Deep Focus & Sleep",
        ],
        "primary_hashtags": ["#pianoambient", "#ambientmusic", "#relaxmusic"],
        "extended_hashtags": [
            "#sleepmusic",
            "#focusmusic",
            "#calmmusic",
            "#backgroundmusic",
        ],
        "upload_tags": [
            "piano ambient",
            "ambient music",
            "relax music",
            "sleep music",
            "focus music",
        ],
        "description_intro": [
            "{title} blends soft piano and ambient textures for focus, rest, and slow unwinding.",
            "Use it for reading, deep work, quiet evenings, or falling asleep.",
            "Tracklist and artist / license credits are listed below.",
        ],
    },
}


RESEARCH_SOURCES = [
    {
        "title": "YouTube Data API: Videos resource",
        "url": "https://developers.google.com/youtube/v3/docs/videos",
        "note": (
            "`snippet.title` max 100 characters, `snippet.description` max 5000 bytes, "
            "and tags have a 500-character limit."
        ),
    },
    {
        "title": "YouTube API Services: Required Minimum Functionality",
        "url": "https://developers.google.com/youtube/terms/required-minimum-functionality",
        "note": (
            "Upload clients must let users set title and description, and YouTube returns an "
            "error if title exceeds 100 characters or description exceeds 5000 bytes."
        ),
    },
    {
        "title": "YouTube Help: Spam, deceptive practices, & scams policies",
        "url": "https://support.google.com/youtube/answer/2801973",
        "note": (
            "Misleading metadata is prohibited. Titles, thumbnails, and descriptions must match "
            "what is actually in the video."
        ),
    },
    {
        "title": "YouTube Help: Find playlists & videos using hashtags",
        "url": "https://support.google.com/youtube/answer/6390658",
        "note": (
            "Up to three hashtags from the description may appear by the title, more than 60 "
            "hashtags are ignored, and hashtags should be directly related to the content."
        ),
    },
    {
        "title": "Creator Academy: Use music and sound effects from the Audio Library",
        "url": (
            "https://creatoracademy.youtube.com/page/lesson/"
            "manage-copyright-permissions_tools-to-manage-music-in-your-videos_list%3Fhl%3Den-GB"
        ),
        "note": (
            "When a track uses a Creative Commons license, the artist must be credited in the "
            "video description."
        ),
    },
]


@dataclass(slots=True)
class YoutubeCopyResult:
    title_description_path: Path


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return path


def _format_timestamp(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    minutes, remaining_seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{remaining_seconds:02d}"
    return f"{minutes:02d}:{remaining_seconds:02d}"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def _sanitize_title(title: str) -> str | None:
    clean = re.sub(r"\s+", " ", title).strip()
    if not clean:
        return None
    if len(clean) > 100:
        return None
    lowered = clean.casefold()
    if any(phrase in lowered for phrase in FORBIDDEN_TITLE_PHRASES):
        return None
    return clean


def _parse_song_and_artist(raw_title: str) -> tuple[str, str]:
    title = raw_title.strip()
    if " by " not in title:
        return title, "Unknown Artist"
    song, artist = title.rsplit(" by ", 1)
    return song.strip(), artist.strip()


def _humanize_purpose(purpose: str) -> str:
    profile = PURPOSE_PROFILES.get(purpose)
    if profile:
        return profile["label"]
    return purpose.replace("_", " ").title()


def _load_source_context(config_path: Path, source_name: str) -> dict:
    config = _read_json(config_path)
    matches = [
        item
        for item in config.get("sources", [])
        if item.get("name") == source_name and item.get("enabled", True)
    ]
    if not matches:
        return {
            "purpose": "lofi_chill_lofi_hiphop_lofi_jazz",
            "tags": ["lofi", "study beats", "focus music"],
        }

    purpose = matches[0].get("purpose") or "lofi_chill_lofi_hiphop_lofi_jazz"
    tags = _dedupe([tag for item in matches for tag in item.get("tags", []) if tag])
    return {"purpose": purpose, "tags": tags}


def _build_title_candidates(
    purpose: str,
    minutes: int,
    scene_label: str | None,
) -> list[str]:
    profile = PURPOSE_PROFILES.get(purpose, PURPOSE_PROFILES["lofi_chill_lofi_hiphop_lofi_jazz"])
    scene = scene_label or profile["scene"]
    candidates = []
    for template in profile["title_candidates"]:
        candidate = template.format(scene=scene, minutes=minutes)
        clean = _sanitize_title(candidate)
        if clean:
            candidates.append(clean)
    return _dedupe(candidates)


def _build_tracklist_lines(tracks: list[dict]) -> list[str]:
    lines = []
    for track in tracks:
        song, artist = _parse_song_and_artist(track["title"])
        lines.append(f"{_format_timestamp(track['start_seconds'])} {song} — {artist}")
    return lines


def _build_credit_lines(tracks: list[dict]) -> list[str]:
    lines = ["🎵 Music Credits:", ""]
    for track in tracks:
        lines.append(f"Track {track['index']}: {track['title']}")
        lines.append("")
        lines.extend(track.get("credits", []))
        lines.append("")
    return lines


def _build_description(
    title: str,
    purpose: str,
    minutes: int,
    tracklist_lines: list[str],
    credit_lines: list[str],
    primary_hashtags: list[str],
    extended_hashtags: list[str],
    track_count: int,
) -> str:
    profile = PURPOSE_PROFILES.get(purpose, PURPOSE_PROFILES["lofi_chill_lofi_hiphop_lofi_jazz"])
    intro_lines = [
        line.format(title=title, minutes=minutes) for line in profile["description_intro"]
    ]

    body_lines = [
        *intro_lines,
        "",
        f"This mix contains {track_count} tracks curated into one continuous session.",
        "",
        "Tracklist",
        *tracklist_lines,
        "",
        "Artist / License Credits",
        "Please support the original artists, stream the songs, and follow the listed license links.",
        "",
        *credit_lines,
        "",
        "Hashtags",
        " ".join(primary_hashtags),
        " ".join(extended_hashtags),
    ]
    return "\n".join(body_lines).strip()


def _build_title_description_bundle(title: str, description: str) -> str:
    return "\n".join(
        [
            "Title",
            title,
            "",
            "Description",
            description,
        ]
    ).strip()


def _build_upload_tags(purpose: str, scene_label: str | None, source_tags: list[str]) -> list[str]:
    profile = PURPOSE_PROFILES.get(purpose, PURPOSE_PROFILES["lofi_chill_lofi_hiphop_lofi_jazz"])
    scene_terms = []
    if scene_label:
        scene_terms = [scene_label.lower(), f"{scene_label.lower()} lofi"]

    combined = _dedupe(profile["upload_tags"] + source_tags + scene_terms)
    serialized = []
    current_length = 0
    for tag in combined:
        addition = len(tag) + (2 if serialized else 0)
        if current_length + addition > 500:
            break
        serialized.append(tag)
        current_length += addition
    return serialized


def _build_llm_prompt(
    *,
    source_name: str,
    mix_name: str,
    purpose_label: str,
    scene_label: str,
    duration_seconds: float,
    recommended_title: str,
    title_candidates: list[str],
    tracklist_lines: list[str],
    credit_lines: list[str],
    primary_hashtags: list[str],
    extended_hashtags: list[str],
    upload_tags: list[str],
) -> str:
    duration_minutes = math.ceil(duration_seconds / 60.0)
    prompt_lines = [
        "Write YouTube metadata for one focus-music video.",
        "",
        "Hard constraints:",
        "- Title must be <= 100 characters.",
        "- Description must be <= 5000 bytes.",
        "- Metadata must match the actual content and mood of the video.",
        "- Do not use or echo source branding such as `DAILY No Copyright For You`, `Audio Library`, or generic `No Copyright` phrases in the title or opening hook.",
        "- Include full artist / license credits in the description.",
        "- Use only relevant hashtags. Up to 3 can be primary hashtags near the title.",
        "- Keep the opening description viewer-focused, then include tracklist and full credits lower down.",
        "",
        "Context:",
        f"- Internal source: `{source_name}`",
        f"- Mix name: `{mix_name}`",
        f"- Purpose: `{purpose_label}`",
        f"- Visual scene label: `{scene_label}`",
        f"- Duration: approximately {duration_minutes} minutes",
        "",
        "Recommended title baseline:",
        f"- {recommended_title}",
        "",
        "Candidate titles:",
        *[f"- {candidate}" for candidate in title_candidates],
        "",
        "Tracklist:",
        *[f"- {line}" for line in tracklist_lines],
        "",
        "Credits to preserve verbatim when possible:",
        *[f"- {line}" for line in credit_lines if line],
        "",
        "Hashtags:",
        f"- Primary: {' '.join(primary_hashtags)}",
        f"- Extended: {' '.join(extended_hashtags)}",
        "",
        "Upload tags:",
        f"- {', '.join(upload_tags)}",
        "",
        "Return plain text in exactly this format:",
        "Title",
        "<one single title line>",
        "",
        "Description",
        "<full final description>",
    ]
    return "\n".join(prompt_lines)


def _load_openai_setting(name: str, env_path: Path) -> str | None:
    if os.getenv(name):
        return os.getenv(name)
    if not env_path.exists():
        return None
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != name:
            continue
        return value.strip().strip("\"'")
    return None


def _extract_title_description(raw_text: str, fallback_title: str) -> tuple[str, str]:
    clean = raw_text.strip()
    if not clean:
        raise ValueError("LLM returned empty metadata output.")

    title_match = re.search(r"(?im)^title\s*$\n(.+)", clean)
    desc_match = re.search(r"(?ims)^description\s*$\n(.+)$", clean)

    title = fallback_title
    if title_match:
        title = title_match.group(1).strip()
    else:
        first_line = clean.splitlines()[0].strip()
        if first_line:
            title = first_line

    description = ""
    if desc_match:
        description = desc_match.group(1).strip()
    else:
        lines = clean.splitlines()
        description = "\n".join(lines[1:]).strip() if len(lines) > 1 else clean

    sanitized_title = _sanitize_title(title) or fallback_title
    description_bytes = description.encode("utf-8")
    if len(description_bytes) > 5000:
        description = description_bytes[:5000].decode("utf-8", errors="ignore").rstrip()

    return sanitized_title, description


def _call_llm_for_youtube_copy(
    *,
    source_name: str,
    mix_name: str,
    purpose_label: str,
    scene_label: str,
    duration_seconds: float,
    recommended_title: str,
    title_candidates: list[str],
    tracklist_lines: list[str],
    credit_lines: list[str],
    primary_hashtags: list[str],
    extended_hashtags: list[str],
    upload_tags: list[str],
    env_path: Path,
    model: str | None,
) -> tuple[str, str]:
    load_dotenv(dotenv_path=env_path)
    api_key = _load_openai_setting("OPENROUTER_API_KEY", env_path)
    if not api_key:
        raise RuntimeError(
            "Missing OPENROUTER_API_KEY. Set it in the environment or in D:\\work\\Personal_project\\.env"
        )

    selected_model = (
        model
        or _load_openai_setting("OPENROUTER_MODEL", env_path)
        or "google/gemini-2.5-flash"
    )
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )
    prompt = _build_llm_prompt(
        source_name=source_name,
        mix_name=mix_name,
        purpose_label=purpose_label,
        scene_label=scene_label,
        duration_seconds=duration_seconds,
        recommended_title=recommended_title,
        title_candidates=title_candidates,
        tracklist_lines=tracklist_lines,
        credit_lines=credit_lines,
        primary_hashtags=primary_hashtags,
        extended_hashtags=extended_hashtags,
        upload_tags=upload_tags,
    )
    response = client.chat.completions.create(
        model=selected_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert YouTube content strategist and copywriter for study, "
                    "lofi, and focus music videos. Write metadata that is accurate, searchable, "
                    "non-misleading, and artist-credit safe."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0.7,
        max_tokens=2200,
    )
    content = response.choices[0].message.content or ""
    return _extract_title_description(content, recommended_title)


def generate_youtube_copy(
    *,
    source_name: str,
    mix_name: str,
    config_path: str | Path,
    output_root: str | Path,
    scene_label: str | None = None,
    model: str | None = None,
) -> YoutubeCopyResult:
    output_root_path = Path(output_root).resolve()
    mix_root = output_root_path / source_name / mix_name
    manifest_path = mix_root / "metadata" / "mix_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing mix manifest: {manifest_path}")

    config_path = Path(config_path).resolve()
    metadata_dir = mix_root / "metadata"
    project_root = Path(__file__).resolve().parents[3]
    env_path = project_root / ".env"
    manifest = _read_json(manifest_path)
    source_context = _load_source_context(config_path, source_name)
    purpose = source_context["purpose"]
    profile = PURPOSE_PROFILES.get(purpose, PURPOSE_PROFILES["lofi_chill_lofi_hiphop_lofi_jazz"])
    purpose_label = _humanize_purpose(purpose)
    active_scene_label = scene_label or profile["scene"]

    duration_seconds = float(manifest["total_duration_seconds"])
    minutes = math.ceil(duration_seconds / 60.0)
    tracks = manifest["tracks"]

    title_candidates = _build_title_candidates(purpose, minutes, active_scene_label)
    recommended_title = title_candidates[0]
    tracklist_lines = _build_tracklist_lines(tracks)
    credit_lines = _build_credit_lines(tracks)
    primary_hashtags = profile["primary_hashtags"]
    extended_hashtags = profile["extended_hashtags"]
    upload_tags = _build_upload_tags(purpose, active_scene_label, source_context["tags"])
    final_title, final_description = _call_llm_for_youtube_copy(
        source_name=source_name,
        mix_name=mix_name,
        purpose_label=purpose_label,
        scene_label=active_scene_label,
        duration_seconds=duration_seconds,
        recommended_title=recommended_title,
        title_candidates=title_candidates,
        tracklist_lines=tracklist_lines,
        credit_lines=credit_lines,
        primary_hashtags=primary_hashtags,
        extended_hashtags=extended_hashtags,
        upload_tags=upload_tags,
        env_path=env_path,
        model=model,
    )
    title_description_path = _write_text(
        metadata_dir / "youtube_title_description.txt",
        _build_title_description_bundle(final_title, final_description),
    )
    for stale_name in [
        "youtube_title_final.txt",
        "youtube_description_full.txt",
        "youtube_title_candidates.txt",
        "youtube_llm_prompt.md",
        "youtube_research_notes.md",
        "youtube_copy_package.json",
    ]:
        (metadata_dir / stale_name).unlink(missing_ok=True)

    return YoutubeCopyResult(
        title_description_path=title_description_path,
    )
