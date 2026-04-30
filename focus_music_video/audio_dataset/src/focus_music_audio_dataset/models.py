from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


VALID_DATASET_TYPES = {"music", "ambient"}
VALID_PURPOSES = {
    "lofi_chill_lofi_hiphop_lofi_jazz",
    "music_for_study",
    "piano_ambient",
}
PURPOSE_LABELS = {
    "lofi_chill_lofi_hiphop_lofi_jazz": "Lo-fi Chill / Lo-fi Hip-hop / Lo-fi Jazz",
    "music_for_study": "Music for Study",
    "piano_ambient": "Piano + Ambient",
}


@dataclass(slots=True)
class SourceConfig:
    name: str
    dataset_type: str
    purpose: str
    url: str
    tags: list[str] = field(default_factory=list)
    max_items: int | None = None
    enabled: bool = True


@dataclass(slots=True)
class LoadedConfig:
    config_file: Path
    sources: list[SourceConfig]
