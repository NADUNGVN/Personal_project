from __future__ import annotations

import argparse
import json
import shutil
import re
from pathlib import Path
from datetime import datetime

# MoviePy compatibility imports
try:
    from moviepy.video.io.VideoFileClip import VideoFileClip
except ImportError:
    try:
        from moviepy import VideoFileClip
    except ImportError:
        from moviepy.editor import VideoFileClip

APP_NAME = "SocialHarvester CopyIdea"
APP_STEP = "Step 4: Build Final Outputs (Long + Shorts)"
APP_VERSION = "1.0.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create final long outputs and short clips by sessions.")
    parser.add_argument("--project-dir", type=Path, help="Path to the specific project directory")
    parser.add_argument(
        "--min-short-sec",
        type=float,
        default=8.0,
        help="Minimum target duration per short when possible (default: 8s)",
    )
    return parser.parse_args()


def normalize_text(text: str) -> str:
    return " ".join((text or "").split())


def is_nonempty_file(path: Path) -> bool:
    try:
        return path.exists() and path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def resolve_latest_project_dir(base_output_dir: Path) -> Path:
    candidates = []
    if base_output_dir.exists():
        for date_dir in base_output_dir.iterdir():
            if not date_dir.is_dir():
                continue
            for proj_dir in date_dir.iterdir():
                if not proj_dir.is_dir():
                    continue
                if (proj_dir / "03_video" / "long_video_16x9.mp4").exists() and (proj_dir / "03_video" / "long_video_9x16.mp4").exists():
                    candidates.append(proj_dir)

    if not candidates:
        raise RuntimeError(f"No valid project directories found in {base_output_dir}")

    candidates.sort(key=lambda p: p.stat().st_ctime, reverse=True)
    return candidates[0]


def slugify(text: str, fallback: str = "session") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return cleaned[:48] or fallback


def count_words(text: str) -> int:
    return len(re.findall(r"[A-Za-z][A-Za-z'-]*", text or ""))


def load_sessions(content: dict) -> list[dict]:
    sessions = content.get("sessions")
    if isinstance(sessions, list) and sessions:
        out = []
        for i, s in enumerate(sessions, 1):
            title = normalize_text(str(s.get("title_en", "")))
            text = normalize_text(str(s.get("text_en", "")))
            out.append(
                {
                    "session_id": int(s.get("session_id", i)),
                    "title_en": title or f"SESSION {i}",
                    "text_en": text,
                    "word_count_en": int(s.get("word_count_en", count_words(text))),
                    "slug": slugify(str(s.get("slug", title or f"session_{i}")), fallback=f"session_{i}"),
                }
            )
        return out

    title = normalize_text(str(content.get("title_en") or content.get("topic") or "SESSION 1"))
    text = normalize_text(str(content.get("text_en", "")))
    return [
        {
            "session_id": 1,
            "title_en": title,
            "text_en": text,
            "word_count_en": count_words(text),
            "slug": slugify(title, fallback="session_1"),
        }
    ]


def compute_segments(sessions: list[dict], total_duration: float, min_short_sec: float) -> list[dict]:
    n = len(sessions)
    if n <= 0:
        return []

    total_duration = max(1.0, float(total_duration))
    min_short_sec = max(1.0, float(min_short_sec))

    weights = [max(1, int(s.get("word_count_en", 0))) for s in sessions]
    sum_weights = float(sum(weights))

    raw_durations = [total_duration * (w / sum_weights) for w in weights]

    # Try to enforce a practical minimum short duration when possible.
    max_possible_min = total_duration / n
    effective_min = min(min_short_sec, max_possible_min)

    durations = [max(effective_min, d) for d in raw_durations]
    scale = total_duration / sum(durations)
    durations = [d * scale for d in durations]

    segments: list[dict] = []
    cursor = 0.0
    for i, (session, dur) in enumerate(zip(sessions, durations), 1):
        start = cursor
        end = total_duration if i == n else min(total_duration, start + dur)
        if end - start < 0.3:
            end = min(total_duration, start + 0.3)
        cursor = end

        segments.append(
            {
                "session_id": int(session.get("session_id", i)),
                "title_en": session.get("title_en", f"SESSION {i}"),
                "slug": session.get("slug", f"session_{i}"),
                "word_count_en": int(session.get("word_count_en", 0)),
                "start_sec": round(start, 3),
                "end_sec": round(end, 3),
                "duration_sec": round(end - start, 3),
            }
        )

    return segments


def cut_segments(source_video: Path, segments: list[dict], out_dir: Path, suffix: str) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    produced: list[dict] = []

    clip = VideoFileClip(str(source_video))
    try:
        for i, seg in enumerate(segments, 1):
            start = float(seg["start_sec"])
            end = float(seg["end_sec"])
            if end <= start:
                continue

            name = f"short_{i:02d}_{seg['slug']}_{suffix}.mp4"
            out_path = out_dir / name

            sub = clip.subclipped(start, end)
            try:
                sub.write_videofile(
                    str(out_path),
                    fps=30,
                    codec="libx264",
                    audio_codec="aac",
                    threads=4,
                    logger=None,
                )
            finally:
                try:
                    sub.close()
                except Exception:
                    pass

            produced.append(
                {
                    "session_id": seg["session_id"],
                    "slug": seg["slug"],
                    "title_en": seg["title_en"],
                    "start_sec": seg["start_sec"],
                    "end_sec": seg["end_sec"],
                    "duration_sec": seg["duration_sec"],
                    "path": str(out_path),
                }
            )
    finally:
        clip.close()

    return produced


def main() -> None:
    print(f"{APP_NAME} - {APP_STEP} (v{APP_VERSION})")
    args = parse_args()

    script_dir = Path(__file__).resolve().parent
    base_output_dir = script_dir / "output" / "long_video"

    proj_dir = args.project_dir
    if not proj_dir:
        print("[INFO] No --project-dir provided. Resolving latest valid project...")
        proj_dir = resolve_latest_project_dir(base_output_dir)

    proj_dir = proj_dir.resolve()
    print(f"[INFO] Target Project: {proj_dir}")

    content_file = proj_dir / "01_content" / "content.json"
    long_16 = proj_dir / "03_video" / "long_video_16x9.mp4"
    long_9 = proj_dir / "03_video" / "long_video_9x16.mp4"

    if not is_nonempty_file(content_file):
        raise SystemExit("Missing/invalid 01_content/content.json")
    if not is_nonempty_file(long_16) or not is_nonempty_file(long_9):
        raise SystemExit("Missing long video outputs in 03_video")

    content = json.loads(content_file.read_text(encoding="utf-8"))
    sessions = load_sessions(content)

    long_ref = VideoFileClip(str(long_9))
    try:
        total_duration = float(long_ref.duration or 0.0)
    finally:
        long_ref.close()

    if total_duration <= 0:
        raise SystemExit("Invalid long video duration")

    segments = compute_segments(sessions, total_duration, args.min_short_sec)

    out_root = proj_dir / "04_outputs"
    long_dir = out_root / "long"
    shorts_16_dir = out_root / "shorts_16x9"
    shorts_9_dir = out_root / "shorts_9x16"

    long_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(long_16, long_dir / "long_video_16x9.mp4")
    shutil.copy2(long_9, long_dir / "long_video_9x16.mp4")

    print("[INFO] Cutting short clips from long outputs...")
    shorts_16 = cut_segments(long_16, segments, shorts_16_dir, suffix="16x9")
    shorts_9 = cut_segments(long_9, segments, shorts_9_dir, suffix="9x16")

    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "project_dir": str(proj_dir),
        "total_duration_sec": round(total_duration, 3),
        "session_count": len(sessions),
        "segments": segments,
        "outputs": {
            "long_16x9": str(long_dir / "long_video_16x9.mp4"),
            "long_9x16": str(long_dir / "long_video_9x16.mp4"),
            "shorts_16x9": shorts_16,
            "shorts_9x16": shorts_9,
        },
    }

    manifest_path = out_root / "outputs_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    status_path = out_root / "output_status.json"
    status_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "generated_at": manifest["generated_at"],
                "manifest_path": str(manifest_path),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n[DONE] Final outputs created:")
    print(f"- Long outputs: {long_dir}")
    print(f"- Shorts 16:9: {shorts_16_dir}")
    print(f"- Shorts 9:16: {shorts_9_dir}")
    print(f"- Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
