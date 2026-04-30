from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from focus_music_audio_dataset.config import add_source, default_config_path, init_config, load_config
from focus_music_audio_dataset.crawler import crawl_source, write_dataset_summary
from focus_music_audio_dataset.models import PURPOSE_LABELS, SourceConfig
from focus_music_audio_dataset.utils import slugify
from focus_music_video.mix_builder import build_audio_mix
from focus_music_video.mix_video_renderer import render_mix_video
from focus_music_video.production_cleanup import cleanup_production_folder
from focus_music_video.youtube_copy import PURPOSE_PROFILES
from focus_music_video.youtube_copy import YoutubeCopyResult, generate_youtube_copy


RENDER_DEFAULTS = {
    "width": 2560,
    "height": 1440,
    "fps": 30,
    "codec": "h264_nvenc",
    "preset": "p6",
    "cq": 17,
    "background_codec": "libx264",
    "background_preset": "slow",
    "background_quality": 14,
}


@dataclass(slots=True)
class ChannelChoice:
    name: str
    dataset_type: str
    purpose: str
    tags: list[str]


def _prompt_non_empty(label: str, default: str | None = None) -> str:
    while True:
        prompt = label
        if default:
            prompt += f" [{default}]"
        prompt += ": "
        raw = input(prompt).strip()
        if raw:
            return raw
        if default:
            return default
        print("Value is required.")


def _prompt_choice(label: str, options: list[tuple[str, str]]) -> str:
    print(label)
    for index, (_, text) in enumerate(options, start=1):
        print(f"  {index}. {text}")

    while True:
        raw = input("Choose a number: ").strip()
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1][0]
        print("Invalid selection.")


def _prompt_existing_file(label: str) -> Path:
    while True:
        value = Path(_prompt_non_empty(label)).expanduser().resolve()
        if value.exists() and value.is_file():
            return value
        print(f"File not found: {value}")


def _default_tags_for_purpose(purpose: str) -> list[str]:
    mapping = {
        "lofi_chill_lofi_hiphop_lofi_jazz": ["lofi", "chill", "lofi hiphop", "lofi jazz"],
        "music_for_study": ["study", "focus", "deep work", "revision"],
        "piano_ambient": ["piano", "ambient", "calm", "sleep"],
    }
    return mapping.get(purpose, []).copy()


def _load_existing_channels(config_path: Path) -> list[ChannelChoice]:
    if not config_path.exists():
        return []

    loaded = load_config(config_path)
    grouped: dict[str, ChannelChoice] = {}
    for source in loaded.sources:
        key = slugify(source.name)
        current = grouped.get(key)
        if current is None:
            grouped[key] = ChannelChoice(
                name=source.name,
                dataset_type=source.dataset_type,
                purpose=source.purpose,
                tags=source.tags.copy(),
            )
            continue

        for tag in source.tags:
            if tag not in current.tags:
                current.tags.append(tag)

    return sorted(grouped.values(), key=lambda item: item.name.casefold())


def _collect_new_channel(default_name: str | None = None) -> ChannelChoice:
    name = _prompt_non_empty("Ten channel", default=default_name)
    dataset_type = _prompt_choice(
        "Chon bucket du lieu:",
        [
            ("music", "music"),
            ("ambient", "ambient"),
        ],
    )
    purpose = _prompt_choice(
        "Chon muc dich kenh:",
        [
            ("lofi_chill_lofi_hiphop_lofi_jazz", PURPOSE_LABELS["lofi_chill_lofi_hiphop_lofi_jazz"]),
            ("music_for_study", PURPOSE_LABELS["music_for_study"]),
            ("piano_ambient", PURPOSE_LABELS["piano_ambient"]),
        ],
    )
    return ChannelChoice(
        name=name,
        dataset_type=dataset_type,
        purpose=purpose,
        tags=_default_tags_for_purpose(purpose),
    )


def _choose_channel(config_path: Path) -> ChannelChoice:
    existing = _load_existing_channels(config_path)
    if not existing:
        print("[INFO] Chua co channel nao trong config. Tao channel moi.")
        return _collect_new_channel()

    mode = _prompt_choice(
        "Chon channel de luu nguon audio:",
        [
            ("existing", "Dung channel co san"),
            ("new", "Tao channel moi"),
        ],
    )
    if mode == "new":
        return _collect_new_channel()

    options = [
        (
            str(index),
            f"{item.name} [{item.dataset_type}] | {PURPOSE_LABELS.get(item.purpose, item.purpose)}",
        )
        for index, item in enumerate(existing, start=1)
    ]
    selected = _prompt_choice("Chon channel co san:", options)
    choice = existing[int(selected) - 1]
    print(
        f"[INFO] Su dung channel: {choice.name} [{choice.dataset_type}] - "
        f"{PURPOSE_LABELS.get(choice.purpose, choice.purpose)}"
    )
    return ChannelChoice(
        name=choice.name,
        dataset_type=choice.dataset_type,
        purpose=choice.purpose,
        tags=choice.tags.copy(),
    )


def _collect_urls() -> list[str]:
    mode = _prompt_choice(
        "Buoc 1 - Chon co che lay audio:",
        [
            ("single", "Tao voi 1 URL"),
            ("multiple", "Tao voi nhieu URL"),
        ],
    )
    if mode == "single":
        return [_prompt_non_empty("YouTube URL")]

    print("Nhap nhieu YouTube URL.")
    print("Ket thuc bang 1 dong chi co: END")
    urls: list[str] = []
    while True:
        raw = input("YouTube URL: ").strip()
        if raw == "END":
            break
        if raw:
            urls.append(raw)
    if not urls:
        raise ValueError("No URLs provided.")
    return list(dict.fromkeys(urls))


def _prompt_output_name(output_root: Path, channel_name: str) -> str:
    default_name = f"session_{datetime.now():%Y%m%d_%H%M%S}"
    while True:
        name = _prompt_non_empty("Ten folder san xuat", default=default_name)
        target = output_root / channel_name / name
        if not target.exists():
            return name
        print(f"Folder da ton tai: {target}")


def _youtube_identity(url: str) -> str:
    parsed = urlparse(url.strip())
    query = parse_qs(parsed.query)
    video_ids = query.get("v")
    if video_ids and video_ids[0].strip():
        return f"video:{video_ids[0].strip()}"
    if parsed.netloc in {"youtu.be", "www.youtu.be"} and parsed.path.strip("/"):
        return f"video:{parsed.path.strip('/')}"
    return url.strip()


def _ensure_sources_in_config(config_path: Path, sources: list[SourceConfig]) -> None:
    init_config(config_path.parents[1])
    existing_identities: set[str] = set()
    if config_path.exists():
        loaded = load_config(config_path)
        existing_identities = {_youtube_identity(source.url) for source in loaded.sources}

    for source in sources:
        normalized_url = source.url.strip()
        identity = _youtube_identity(normalized_url)
        if identity in existing_identities:
            print(f"[INFO] URL da co trong config, bo qua them moi: {normalized_url}")
            continue
        add_source(config_path, source)
        existing_identities.add(identity)
        print(f"[OK] Added source to config: {source.name} -> {normalized_url}")


def _crawl_selected_sources(audio_dataset_root: Path, sources: list[SourceConfig]) -> Path:
    for index, source in enumerate(sources, start=1):
        print(f"[STEP 1] Crawl {index}/{len(sources)}: {source.url}")
        try:
            crawl_source(audio_dataset_root, source)
        except Exception as exc:
            print(f"[WARN] Crawl failed for {source.url}: {exc}")
    return write_dataset_summary(audio_dataset_root)


def _prompt_video_overlay_options() -> tuple[bool, bool]:
    print("Chon overlay cho video:")
    print("  1. Co time dem nguoc")
    print("  2. Co thanh bar am thanh")
    while True:
        raw = input("Nhap 1, 2, hoac 1,2 [1,2]: ").strip()
        if not raw:
            return True, True
        parts = {part.strip() for part in raw.split(",") if part.strip()}
        if parts and parts.issubset({"1", "2"}):
            return "1" in parts, "2" in parts
        print("Gia tri khong hop le.")


def _choose_visual_input() -> tuple[str, Path | None, bool, bool]:
    mode = _prompt_choice(
        "Buoc 2 - Chon co che edit video:",
        [
            ("image", "Chon hinh anh"),
            ("video", "Chon video"),
            ("edit_later", "Edit video (thiet ke sau)"),
        ],
    )
    if mode == "edit_later":
        return mode, None, True, True
    if mode == "image":
        return mode, _prompt_existing_file("Duong dan hinh anh"), True, True
    background_path = _prompt_existing_file("Duong dan video")
    show_countdown, show_visualizer = _prompt_video_overlay_options()
    return mode, background_path, show_countdown, show_visualizer


def _default_scene_label(purpose: str) -> str:
    profile = PURPOSE_PROFILES.get(purpose, PURPOSE_PROFILES["lofi_chill_lofi_hiphop_lofi_jazz"])
    return str(profile["scene"])


def _load_env_setting(env_path: Path, name: str) -> str | None:
    if os.getenv(name):
        return os.getenv(name)
    if not env_path.exists():
        return None
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip("\"'")
    return None


def run_interactive_production(tool_root: Path) -> None:
    audio_dataset_root = tool_root / "audio_dataset"
    config_path = default_config_path(audio_dataset_root)
    output_root = tool_root / "productions"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    init_config(audio_dataset_root)

    print("[STEP 1/4] Audio ingest + audio_final")
    urls = list(dict.fromkeys(_collect_urls()))
    channel = _choose_channel(config_path)
    mix_name = _prompt_output_name(output_root, channel.name)

    selected_sources = [
        SourceConfig(
            name=channel.name,
            dataset_type=channel.dataset_type,
            purpose=channel.purpose,
            url=url,
            tags=channel.tags.copy(),
            enabled=True,
        )
        for url in urls
    ]
    _ensure_sources_in_config(config_path, selected_sources)
    summary_path = _crawl_selected_sources(audio_dataset_root, selected_sources)
    print(f"[OK] Dataset summary: {summary_path}")
    mix_result = build_audio_mix(
        source_name=channel.name,
        mix_name=mix_name,
        config_path=config_path,
        dataset_root=audio_dataset_root / "dataset",
        output_root=output_root,
        selected_urls=urls,
    )
    print(f"[OK] audio_final: {mix_result.audio_path}")

    print("[STEP 2/4] Video input")
    visual_mode, background_path, show_countdown, show_visualizer = _choose_visual_input()
    if visual_mode == "edit_later":
        print("[TODO] Che do 'Edit video' chua duoc thiet ke. Quy trinh tam dung sau buoc audio.")
        return

    env_path = tool_root.parent / ".env"
    has_openrouter_key = _load_env_setting(env_path, "OPENROUTER_API_KEY") is not None
    skip_youtube_copy = not has_openrouter_key

    print("[STEP 3/4] Render final video")
    render_result = render_mix_video(
        source_name=channel.name,
        mix_name=mix_name,
        background_path=background_path,
        output_root=output_root,
        show_countdown=show_countdown,
        show_visualizer=show_visualizer,
        **RENDER_DEFAULTS,
    )
    print(f"[OK] final_video: {render_result.video_path}")

    youtube_copy_result: YoutubeCopyResult | None = None
    if skip_youtube_copy:
        print("[WARN] Missing OPENROUTER_API_KEY. Buoc 4 se bo qua title/description.")
    else:
        print("[STEP 4/4] Title + description")
        scene_label = _prompt_non_empty(
            "Scene label cho title/description",
            default=_default_scene_label(channel.purpose),
        )
        youtube_copy_result = generate_youtube_copy(
            source_name=channel.name,
            mix_name=mix_name,
            config_path=config_path,
            output_root=output_root,
            scene_label=scene_label,
        )
        print(f"[OK] title_description: {youtube_copy_result.title_description_path}")

    cleanup_result = cleanup_production_folder(
        source_name=channel.name,
        mix_name=mix_name,
        output_root=output_root,
        aggressive=False,
    )
    if cleanup_result.removed_paths:
        print(f"[OK] Removed {len(cleanup_result.removed_paths)} intermediate files")
