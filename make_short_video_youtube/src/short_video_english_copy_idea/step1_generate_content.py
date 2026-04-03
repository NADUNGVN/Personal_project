from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

APP_NAME = "SocialHarvester CopyIdea"
APP_STEP = "Step 1: Prepare Multi-Session Content"
APP_VERSION = "1.1.0"

DEFAULT_TARGET_DURATION = 180
DEFAULT_DIFFICULTY = "A2-B1"
DEFAULT_WPM = 120.0

CONTENT_MODE_TAG = "manual_multi_session"
MANUAL_MODEL_TAG = "manual_input_no_llm"

DEFAULT_FALLBACK_HASHTAGS = [
    "#EnglishListening",
    "#LearnEnglish",
    "#EnglishPractice",
    "#SlowEnglish",
]

HASHTAG_STOPWORDS = {
    "a", "an", "and", "are", "at", "be", "but", "by", "for", "from", "had", "has", "have",
    "he", "her", "his", "i", "if", "in", "is", "it", "its", "me", "my", "of", "on", "or",
    "our", "she", "so", "that", "the", "their", "them", "there", "they", "this", "to", "us",
    "was", "we", "were", "with", "you", "your",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare manual multi-session content JSON for copy-idea pipeline.")
    parser.add_argument("--project-title", help="Overall project title (optional)")
    parser.add_argument("--title-en", help="Single session title (optional shortcut mode)")
    parser.add_argument("--text-en", help="Single session text (optional shortcut mode)")
    parser.add_argument("--sessions-file", type=Path, help="JSON file containing sessions")
    parser.add_argument("--hashtags", help="Optional hashtags (comma or space separated)")
    parser.add_argument("--difficulty", default=DEFAULT_DIFFICULTY, help=f"Difficulty label (default: {DEFAULT_DIFFICULTY})")
    parser.add_argument(
        "--target-duration",
        type=int,
        default=DEFAULT_TARGET_DURATION,
        help=f"Target narration duration in seconds (default: {DEFAULT_TARGET_DURATION})",
    )
    parser.add_argument("--project-id", help="Optional project id. If omitted, auto-generated.")
    parser.add_argument("--output-root", type=Path, default=None, help="Base output path. Default: <script_dir>/output/long_video")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs and resolved paths only.")
    return parser.parse_args()


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_title_en(title: str) -> str:
    return normalize_whitespace(title).upper()


def prompt_required(prompt_text: str) -> str:
    while True:
        value = input(prompt_text).strip()
        if value:
            return value
        print("Input cannot be empty. Please try again.")


def prompt_optional(prompt_text: str) -> str | None:
    value = input(prompt_text).strip()
    return value or None


def prompt_positive_int(prompt_text: str, default_value: int) -> int:
    while True:
        raw = input(prompt_text).strip()
        if not raw:
            return default_value
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
        print("Please enter a positive integer.")


def prompt_multiline_text() -> str:
    print("Enter text content (multi-line allowed).")
    print("Press ENTER on an empty line to finish, or type END on a new line.")
    while True:
        lines: list[str] = []
        while True:
            line = input()
            if line.strip().upper() == "END":
                break
            if line == "" and lines:
                break
            lines.append(line)

        text = "\n".join(lines).strip()
        if text:
            return text
        print("Text cannot be empty. Please input again.")


def normalize_hashtags(hashtags: Any) -> list[str]:
    if not isinstance(hashtags, list):
        return []

    normalized: list[str] = []
    seen = set()
    for raw in hashtags:
        if not isinstance(raw, str):
            continue
        tag = raw.strip().replace(" ", "")
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = f"#{tag}"
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(tag)
    return normalized


def parse_hashtags_input(raw_hashtags: str | None) -> list[str]:
    if not raw_hashtags:
        return []

    text = raw_hashtags.strip()
    if not text:
        return []

    if "," in text or "\n" in text:
        tokens = [part.strip() for part in re.split(r"[,\n]+", text) if part.strip()]
    else:
        tokens = text.split()
    return normalize_hashtags(tokens)


def generate_hashtags_from_text(title_en: str, text_en: str) -> list[str]:
    candidates: list[str] = []

    def append_candidate(token: str) -> None:
        token = re.sub(r"[^A-Za-z0-9]", "", token)
        if len(token) < 3:
            return
        if token.lower() in HASHTAG_STOPWORDS:
            return
        candidates.append(f"#{token.capitalize()}")

    for source in (title_en, text_en):
        for word in re.findall(r"[A-Za-z][A-Za-z0-9'-]*", source):
            append_candidate(word)

    hashtags = normalize_hashtags(candidates)
    existing_keys = {x.lower() for x in hashtags}
    for default_tag in DEFAULT_FALLBACK_HASHTAGS:
        if len(hashtags) >= 8:
            break
        if default_tag.lower() not in existing_keys:
            hashtags.append(default_tag)
            existing_keys.add(default_tag.lower())

    if len(hashtags) < 4:
        return DEFAULT_FALLBACK_HASHTAGS[:]
    return hashtags[:8]


def count_english_words(text: str) -> int:
    return len(re.findall(r"[A-Za-z][A-Za-z'-]*", text))


def estimate_duration_seconds(word_count: int, wpm: float = DEFAULT_WPM) -> float:
    if word_count <= 0:
        return 0.0
    return (word_count / wpm) * 60.0


def slugify(text: str, fallback: str = "session") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return cleaned[:48] or fallback


def build_project_id() -> str:
    return datetime.now().strftime("%Y-%m-%d/%H%M%S")


def resolve_project_output_path(output_root: Path, topic: str, project_id: str, explicit_project_id: bool) -> Path:
    if "/" in project_id:
        date_folder, time_folder = project_id.split("/", 1)
    else:
        date_folder = datetime.now().strftime("%Y-%m-%d")
        time_folder = project_id

    date_path = output_root / date_folder
    date_path.mkdir(parents=True, exist_ok=True)

    slug = slugify(topic, fallback="copy_idea")
    folder_name = f"{time_folder}_{slug}"
    candidate = date_path / folder_name

    if explicit_project_id:
        return candidate

    if not candidate.exists():
        return candidate

    counter = 2
    while True:
        alt = date_path / f"{folder_name}_{counter}"
        if not alt.exists():
            return alt
        counter += 1


def load_sessions_from_json(file_path: Path) -> tuple[str, list[dict[str, str]]]:
    data = json.loads(file_path.read_text(encoding="utf-8-sig"))

    sessions_raw = None
    project_title = ""
    if isinstance(data, dict):
        project_title = normalize_whitespace(str(data.get("project_title", "")))
        sessions_raw = data.get("sessions")
    elif isinstance(data, list):
        sessions_raw = data

    if not isinstance(sessions_raw, list) or not sessions_raw:
        raise RuntimeError("sessions-file must contain a non-empty sessions list")

    sessions: list[dict[str, str]] = []
    for i, item in enumerate(sessions_raw, 1):
        if not isinstance(item, dict):
            raise RuntimeError(f"Session #{i} must be an object")
        title = normalize_whitespace(str(item.get("title_en", "")))
        text = normalize_whitespace(str(item.get("text_en", "")))
        if not title or not text:
            raise RuntimeError(f"Session #{i} requires title_en and text_en")
        sessions.append({"title_en": title, "text_en": text})

    return project_title, sessions


def collect_sessions_interactive() -> tuple[str, list[dict[str, str]]]:
    project_title = prompt_optional("Project title (optional): ") or ""
    session_count = prompt_positive_int("Number of sessions/stories (default 1): ", default_value=1)

    sessions: list[dict[str, str]] = []
    for idx in range(1, session_count + 1):
        print(f"\nSession {idx}/{session_count}")
        title = prompt_required("Session title EN: ")
        text = prompt_multiline_text()
        sessions.append({"title_en": title, "text_en": text})

    return project_title, sessions


def build_sessions(args: argparse.Namespace) -> tuple[str, list[dict[str, str]]]:
    if args.sessions_file:
        if not args.sessions_file.exists():
            raise RuntimeError(f"sessions-file not found: {args.sessions_file}")
        return load_sessions_from_json(args.sessions_file)

    if args.title_en and args.text_en:
        return (
            normalize_whitespace(args.project_title or ""),
            [{"title_en": normalize_whitespace(args.title_en), "text_en": normalize_whitespace(args.text_en)}],
        )

    return collect_sessions_interactive()


def validate_sessions(sessions: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    if not sessions:
        errors.append("At least one session is required")
        return errors

    for idx, session in enumerate(sessions, 1):
        title = session.get("title_en", "")
        text = session.get("text_en", "")
        if not isinstance(title, str) or not normalize_whitespace(title):
            errors.append(f"Session #{idx}: title_en is empty")
        if not isinstance(text, str) or not normalize_whitespace(text):
            errors.append(f"Session #{idx}: text_en is empty")
        elif count_english_words(text) <= 0:
            errors.append(f"Session #{idx}: text_en must contain English words")
    return errors


def build_manual_warnings(total_text: str, target_duration: int, session_count: int) -> list[str]:
    warnings: list[str] = []
    words = count_english_words(total_text)
    estimate = estimate_duration_seconds(words)
    if words < 180:
        warnings.append("Combined text is short for long-form output (<180 words).")
    if estimate < max(30, target_duration - 20):
        warnings.append(f"Estimated narration duration {estimate:.1f}s may be short for target {target_duration}s.")
    if session_count > 1 and words < 260:
        warnings.append("Multiple sessions detected but total words are still low; short clips may be too brief.")
    return warnings


def persist_content(
    project_dir: Path,
    project_id: str,
    project_title: str,
    sessions: list[dict[str, Any]],
    difficulty: str,
    hashtags: list[str],
    target_duration: int,
) -> Path:
    content_dir = project_dir / "01_content"
    content_dir.mkdir(parents=True, exist_ok=True)

    combined_text = "\n\n".join([s["text_en"] for s in sessions])
    combined_words = count_english_words(combined_text)
    estimate = estimate_duration_seconds(combined_words)

    title_en = normalize_title_en(project_title or sessions[0]["title_en"])
    topic = normalize_whitespace(project_title or sessions[0]["title_en"]).title()

    enriched_sessions: list[dict[str, Any]] = []
    for i, s in enumerate(sessions, 1):
        session_title = normalize_title_en(s["title_en"])
        session_text = normalize_whitespace(s["text_en"])
        enriched_sessions.append(
            {
                "session_id": i,
                "slug": slugify(session_title, fallback=f"session_{i}"),
                "title_en": session_title,
                "text_en": session_text,
                "word_count_en": count_english_words(session_text),
            }
        )

    payload = {
        "project_id": project_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "content_mode": CONTENT_MODE_TAG,
        "model": MANUAL_MODEL_TAG,
        "target_duration_sec": target_duration,
        "estimated_duration_sec": round(estimate, 2),
        "word_count_en": combined_words,
        "topic": topic,
        "title_en": title_en,
        "text_en": combined_text,
        "difficulty": normalize_whitespace(difficulty),
        "hashtags": hashtags,
        "session_count": len(enriched_sessions),
        "sessions": enriched_sessions,
    }

    out_path = content_dir / "content.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    print(f"{APP_NAME} - {APP_STEP} (v{APP_VERSION})")
    args = parse_args()

    project_title, sessions = build_sessions(args)
    errors = validate_sessions(sessions)
    if errors:
        raise SystemExit(f"Failed: validation errors: {errors}")

    combined_text = "\n\n".join([normalize_whitespace(s["text_en"]) for s in sessions])
    title_seed = project_title or sessions[0]["title_en"]

    hashtags = parse_hashtags_input(args.hashtags)
    if not hashtags:
        hashtags = generate_hashtags_from_text(normalize_title_en(title_seed), combined_text)

    explicit_project_id = bool(args.project_id and args.project_id.strip())
    project_id = args.project_id.strip() if explicit_project_id else build_project_id()

    script_dir = Path(__file__).resolve().parent
    output_root = args.output_root or (script_dir / "output" / "long_video")
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    topic_for_folder = normalize_whitespace(title_seed).title()
    print(f"[INFO] Project title: {normalize_title_en(title_seed)}")
    print(f"[INFO] Sessions: {len(sessions)}")
    print(f"[INFO] Project ID: {project_id}")

    if args.dry_run:
        print("[DRY RUN] Setup OK. No file was written.")
        return

    warnings = build_manual_warnings(combined_text, args.target_duration, len(sessions))
    for warning in warnings:
        print(f"[WARN] {warning}")

    project_output_dir = resolve_project_output_path(
        output_root=output_root,
        topic=topic_for_folder,
        project_id=project_id,
        explicit_project_id=explicit_project_id,
    )
    project_id = project_output_dir.name

    out_path = persist_content(
        project_dir=project_output_dir,
        project_id=project_id,
        project_title=project_title,
        sessions=sessions,
        difficulty=args.difficulty,
        hashtags=hashtags,
        target_duration=args.target_duration,
    )
    print(f"[DONE] Content saved: {out_path}")


if __name__ == "__main__":
    main()
