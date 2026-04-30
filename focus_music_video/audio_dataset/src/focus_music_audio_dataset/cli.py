from __future__ import annotations

import argparse
import sys
from pathlib import Path

from focus_music_audio_dataset.config import add_source, default_config_path, init_config, load_config
from focus_music_audio_dataset.models import PURPOSE_LABELS, SourceConfig
from focus_music_audio_dataset.utils import slugify


def _tool_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a structured YouTube audio dataset for focus music and ambient sound sources."
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init-config", help="Create an empty youtube_channels.json working file")

    interactive_parser = subparsers.add_parser("interactive", help="Open the interactive wizard")
    interactive_parser.add_argument(
        "--config",
        default=str(default_config_path(_tool_root())),
        help="Path to youtube_channels.json",
    )

    add_parser = subparsers.add_parser("add-source", help="Add one YouTube source interactively")
    add_parser.add_argument(
        "--config",
        default=str(default_config_path(_tool_root())),
        help="Path to youtube_channels.json",
    )
    add_parser.add_argument("--url", help="YouTube channel / playlist / video URL")
    add_parser.add_argument("--name", help="Channel name stored locally")
    add_parser.add_argument("--dataset-type", choices=["music", "ambient"], help="Dataset bucket")
    add_parser.add_argument(
        "--purpose",
        choices=sorted(PURPOSE_LABELS),
        help="Target channel purpose",
    )
    add_parser.add_argument("--probe", action="store_true", help="Probe YouTube metadata to suggest a detected name")
    add_parser.add_argument("--max-items", type=int, help="Optional per-source item cap")
    add_parser.add_argument("--tag", action="append", help="Optional extra tag. Can be repeated.")

    validate_parser = subparsers.add_parser("validate-config", help="Validate current source config")
    validate_parser.add_argument(
        "--config",
        default=str(default_config_path(_tool_root())),
        help="Path to youtube_channels.json",
    )

    crawl_parser = subparsers.add_parser("crawl", help="Download audio dataset from configured YouTube sources")
    crawl_parser.add_argument(
        "--config",
        default=str(default_config_path(_tool_root())),
        help="Path to youtube_channels.json",
    )
    crawl_parser.add_argument(
        "--source",
        action="append",
        help="Optional source name or slug to crawl. Can be repeated.",
    )

    return parser


def _command_init_config() -> int:
    path = init_config(_tool_root())
    print(f"[OK] Config ready: {path}")
    return 0


def _prompt_non_empty(label: str, default: str | None = None) -> str:
    while True:
        prompt = f"{label}"
        if default:
            prompt += f" [{default}]"
        prompt += ": "
        value = input(prompt).strip()
        if value:
            return value
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


def _prompt_yes_no(label: str, default: bool = True) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        raw = input(label + suffix).strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("Please answer y or n.")


def _default_tags_for_purpose(purpose: str) -> list[str]:
    mapping = {
        "lofi_chill_lofi_hiphop_lofi_jazz": ["lofi", "chill", "lofi hiphop", "lofi jazz"],
        "music_for_study": ["study", "focus", "deep work", "revision"],
        "piano_ambient": ["piano", "ambient", "calm", "sleep"],
    }
    return mapping.get(purpose, []).copy()


def _ensure_config_path(config_path: Path) -> Path:
    if config_path.exists():
        return config_path
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text('{\n  "sources": []\n}\n', encoding="utf-8")
    return config_path


def _collect_channel_metadata(default_name: str | None = None) -> tuple[str, str, str, list[str]]:
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
    tags = _default_tags_for_purpose(purpose)
    return name, dataset_type, purpose, tags


def _load_existing_channels(config_path: Path) -> list[tuple[str, str, str, list[str], int]]:
    if not config_path.exists():
        return []

    loaded = load_config(config_path)
    grouped: dict[str, dict[str, object]] = {}

    for source in loaded.sources:
        key = slugify(source.name)
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = {
                "name": source.name,
                "dataset_type": source.dataset_type,
                "purpose": source.purpose,
                "tags": source.tags.copy(),
                "count": 1,
            }
            continue

        existing["count"] = int(existing["count"]) + 1
        current_tags = list(existing["tags"])
        for tag in source.tags:
            if tag not in current_tags:
                current_tags.append(tag)
        existing["tags"] = current_tags

    channels: list[tuple[str, str, str, list[str], int]] = []
    for item in grouped.values():
        channels.append(
            (
                str(item["name"]),
                str(item["dataset_type"]),
                str(item["purpose"]),
                list(item["tags"]),
                int(item["count"]),
            )
        )
    channels.sort(key=lambda value: value[0].casefold())
    return channels


def _choose_existing_or_create_channel(
    config_path: Path,
    default_name: str | None = None,
) -> tuple[str, str, str, list[str]]:
    existing_channels = _load_existing_channels(config_path)
    if not existing_channels:
        print("[INFO] Chua co channel nao trong config. Tao channel moi.")
        return _collect_channel_metadata(default_name=default_name)

    use_existing = _prompt_choice(
        "Chon cach gan URL vao channel:",
        [
            ("existing", "Dung channel co san"),
            ("new", "Tao channel moi"),
        ],
    )
    if use_existing == "new":
        return _collect_channel_metadata(default_name=default_name)

    options = [
        (
            str(index),
            (
                f"{name} [{dataset_type}] | "
                f"{PURPOSE_LABELS.get(purpose, purpose)} | "
                f"{count} source"
            ),
        )
        for index, (name, dataset_type, purpose, _, count) in enumerate(existing_channels, start=1)
    ]
    selected = _prompt_choice("Chon channel co san:", options)
    name, dataset_type, purpose, tags, _ = existing_channels[int(selected) - 1]
    print(f"[INFO] Su dung channel: {name} [{dataset_type}] - {PURPOSE_LABELS.get(purpose, purpose)}")
    return name, dataset_type, purpose, tags.copy()


def _save_source_entry(
    *,
    config_path: Path,
    url: str,
    name: str,
    dataset_type: str,
    purpose: str,
    tags: list[str],
    max_items: int | None = None,
) -> None:
    source = SourceConfig(
        name=name,
        dataset_type=dataset_type,
        purpose=purpose,
        url=url,
        tags=tags,
        max_items=max_items,
        enabled=True,
    )
    add_source(config_path, source)
    print(f"[OK] Added source: {name} -> {url}")


def _run_single_url_wizard(config_path: Path) -> int:
    url = _prompt_non_empty("YouTube URL")
    name, dataset_type, purpose, tags = _choose_existing_or_create_channel(config_path)
    _save_source_entry(
        config_path=config_path,
        url=url,
        name=name,
        dataset_type=dataset_type,
        purpose=purpose,
        tags=tags,
    )
    print(f"[OK] Config updated: {config_path}")
    return 0


def _run_multi_url_wizard(config_path: Path) -> int:
    print("Nhap nhieu YouTube URL cho channel nay.")
    print("Ket thuc bang 1 dong chi co: END")
    urls: list[str] = []
    while True:
        url = input("YouTube URL: ").strip()
        if url == "END":
            break
        if url:
            urls.append(url)

    if not urls:
        raise ValueError("No URLs provided.")

    name, dataset_type, purpose, tags = _choose_existing_or_create_channel(config_path)

    for index, url in enumerate(urls, start=1):
        print(f"URL {index}/{len(urls)}: {url}")
        _save_source_entry(
            config_path=config_path,
            url=url,
            name=name,
            dataset_type=dataset_type,
            purpose=purpose,
            tags=tags,
        )

    print(f"[OK] Config updated: {config_path}")
    return 0


def _command_interactive(args: argparse.Namespace) -> int:
    config_path = _ensure_config_path(Path(args.config).resolve())
    mode = _prompt_choice(
        "Chon co che tao source:",
        [
            ("single", "Tao voi 1 URL"),
            ("multiple", "Tao voi nhieu URL"),
        ],
    )
    if mode == "single":
        return _run_single_url_wizard(config_path)
    return _run_multi_url_wizard(config_path)


def _command_add_source(args: argparse.Namespace) -> int:
    config_path = Path(args.config).resolve()
    _ensure_config_path(config_path)

    url = args.url or _prompt_non_empty("YouTube URL")

    probe_info = None
    if args.probe:
        try:
            from focus_music_audio_dataset.crawler import pre_extract_info

            probe_info = pre_extract_info(url)
        except Exception:
            probe_info = None

    detected_name = None
    if isinstance(probe_info, dict):
        detected_name = (
            probe_info.get("channel")
            or probe_info.get("uploader")
            or probe_info.get("title")
        )
        if detected_name:
            print(f"[INFO] Detected source title: {detected_name}")

    if args.name and args.dataset_type and args.purpose:
        name = args.name
        dataset_type = args.dataset_type
        purpose = args.purpose
        tags = args.tag or _default_tags_for_purpose(purpose)
    else:
        suggested_name = args.name or detected_name
        name, dataset_type, purpose, tags = _choose_existing_or_create_channel(
            config_path,
            default_name=suggested_name,
        )
        if args.dataset_type:
            dataset_type = args.dataset_type
        if args.purpose:
            purpose = args.purpose
            if not args.tag:
                tags = _default_tags_for_purpose(purpose)
        if args.tag:
            tags = args.tag

    if args.name and not (args.dataset_type and args.purpose):
        if _prompt_yes_no("Giu ten channel tu CLI va bo qua ten da chon?", default=False):
            name = args.name

    _save_source_entry(
        config_path=config_path,
        url=url,
        name=name,
        dataset_type=dataset_type,
        purpose=purpose,
        tags=tags,
        max_items=args.max_items,
    )
    print(f"[OK] Config updated: {config_path}")
    return 0


def _command_validate_config(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    print(f"[OK] Loaded config: {config.config_file}")
    if not config.sources:
        print("- No sources configured yet.")
        return 0
    for source in config.sources:
        purpose_label = PURPOSE_LABELS.get(source.purpose, source.purpose)
        print(f"- {source.name} [{source.dataset_type}] purpose={purpose_label}")
        print(f"  URL: {source.url}")
        print(f"  Enabled: {source.enabled} | max_items={source.max_items}")
        if source.tags:
            print(f"  Tags: {', '.join(source.tags)}")
    return 0


def _command_crawl(args: argparse.Namespace) -> int:
    from focus_music_audio_dataset.crawler import crawl_source, write_dataset_summary

    config = load_config(args.config)
    selected = config.sources

    if args.source:
        allowed = {slugify(value) for value in args.source}
        selected = [
            source
            for source in config.sources
            if slugify(source.name) in allowed
        ]
        if not selected:
            raise ValueError("No matching sources found for --source")

    selected = [source for source in selected if source.enabled]
    if not selected:
        raise ValueError("No enabled sources to crawl.")

    for source in selected:
        output_path = crawl_source(_tool_root(), source)
        print(f"[OK] Crawled {source.name}: {output_path}")

    summary_path = write_dataset_summary(_tool_root())
    print(f"[OK] Dataset summary: {summary_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    if not effective_argv:
        default_args = argparse.Namespace(config=str(default_config_path(_tool_root())))
        return _command_interactive(default_args)

    parser = _build_parser()
    args = parser.parse_args(effective_argv)

    if args.command == "init-config":
        return _command_init_config()
    if args.command == "interactive":
        return _command_interactive(args)
    if args.command == "add-source":
        return _command_add_source(args)
    if args.command == "validate-config":
        return _command_validate_config(args)
    if args.command == "crawl":
        return _command_crawl(args)

    parser.print_help()
    return 1
