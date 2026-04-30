from __future__ import annotations

import json
from pathlib import Path

from focus_music_audio_dataset.models import LoadedConfig, SourceConfig, VALID_DATASET_TYPES, VALID_PURPOSES
from focus_music_audio_dataset.utils import slugify


def template_config_path(tool_root: Path) -> Path:
    return tool_root / "config" / "youtube_channels.template.json"


def default_config_path(tool_root: Path) -> Path:
    return tool_root / "config" / "youtube_channels.json"


def empty_config_payload() -> dict:
    return {"sources": []}


def init_config(tool_root: Path) -> Path:
    config_path = default_config_path(tool_root)
    if config_path.exists():
        return config_path

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(empty_config_payload(), ensure_ascii=False, indent=2), encoding="utf-8")
    return config_path


def load_config(config_file: str | Path) -> LoadedConfig:
    path = Path(config_file).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_sources = payload.get("sources", [])

    sources: list[SourceConfig] = []
    for item in raw_sources:
        source = SourceConfig(
            name=item["name"],
            dataset_type=item["dataset_type"],
            purpose=item["purpose"],
            url=item["url"],
            tags=item.get("tags", []),
            max_items=item.get("max_items"),
            enabled=item.get("enabled", True),
        )
        validate_source(source)
        sources.append(source)

    return LoadedConfig(config_file=path, sources=sources)


def save_config(config_file: str | Path, sources: list[SourceConfig]) -> Path:
    path = Path(config_file).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "sources": [
            {
                "name": source.name,
                "dataset_type": source.dataset_type,
                "purpose": source.purpose,
                "url": source.url,
                "tags": source.tags,
                "max_items": source.max_items,
                "enabled": source.enabled,
            }
            for source in sources
        ]
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def add_source(config_file: str | Path, source: SourceConfig) -> Path:
    path = Path(config_file).resolve()
    if path.exists():
        loaded = load_config(path)
        sources = loaded.sources
    else:
        sources = []

    validate_source(source)

    for existing in sources:
        if existing.url.strip() == source.url.strip():
            raise ValueError(f"Source URL already exists in config: {source.url}")

    sources.append(source)
    return save_config(path, sources)


def validate_source(source: SourceConfig) -> None:
    if source.dataset_type not in VALID_DATASET_TYPES:
        valid = ", ".join(sorted(VALID_DATASET_TYPES))
        raise ValueError(f"Invalid dataset_type '{source.dataset_type}' for {source.name}. Expected: {valid}")
    if source.purpose not in VALID_PURPOSES:
        valid = ", ".join(sorted(VALID_PURPOSES))
        raise ValueError(f"Invalid purpose '{source.purpose}' for {source.name}. Expected: {valid}")
    if "youtube.com" not in source.url and "youtu.be" not in source.url:
        raise ValueError(f"Source '{source.name}' is not a YouTube URL: {source.url}")
    if source.max_items is not None and source.max_items <= 0:
        raise ValueError(f"max_items must be > 0 for source '{source.name}'")
