from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class CleanupResult:
    removed_paths: list[Path]


def cleanup_production_folder(
    *,
    source_name: str,
    mix_name: str,
    output_root: str | Path,
    aggressive: bool = False,
) -> CleanupResult:
    base_output_root = Path(output_root).resolve()
    mix_root = base_output_root / source_name / mix_name
    if not mix_root.exists():
        raise FileNotFoundError(f"Missing production folder: {mix_root}")

    removed_paths: list[Path] = []

    video_dir = mix_root / "video"
    if video_dir.exists():
        for path in video_dir.iterdir():
            if not path.is_file():
                continue
            if path.name == "final_video_focus_ui.mp4":
                continue
            if (
                path.name.startswith("preview_")
                or path.name.startswith("visualizer_overlay_")
                or path.name == "prepared_background.mp4"
            ):
                path.unlink(missing_ok=True)
                removed_paths.append(path)

    metadata_dir = mix_root / "metadata"
    if metadata_dir.exists():
        metadata_remove = {
            "youtube_description_blocks.md",
        }
        if aggressive:
            metadata_remove.update(
                {
                    "tracklist.txt",
                    "music_credits.txt",
                }
            )

        for name in metadata_remove:
            path = metadata_dir / name
            if path.exists():
                path.unlink(missing_ok=True)
                removed_paths.append(path)

    return CleanupResult(removed_paths=removed_paths)
