from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


APP_NAME = "SocialHarvester"
APP_STEP = "Step 1: Generate Short Content"
APP_VERSION = "1.1.0"

DEFAULT_MODEL = "google/gemini-2.5-flash"
DEFAULT_TARGET_DURATION = 55
DEFAULT_DIFFICULTY = "A2-B1"
DEFAULT_THEME = "Daily routines"
DEFAULT_WPM = 120.0
MAX_RETRIES = 2

MODE_LLM_FULL = "1"
MODE_LLM_FROM_TITLE = "2"
MODE_MANUAL = "3"

MODE_LABELS = {
    MODE_LLM_FULL: "LLM full generation from theme/topic",
    MODE_LLM_FROM_TITLE: "User provides title, LLM generates text",
    MODE_MANUAL: "User provides title + text (no LLM)",
}

MANUAL_MODEL_TAG = "manual_input_no_llm"

REQUIRED_FIELDS = [
    "topic",
    "title_en",
    "text_en",
    "difficulty",
    "hashtags",
]

DEFAULT_FALLBACK_HASHTAGS = [
    "#EnglishListening",
    "#LearnEnglish",
    "#EnglishPractice",
    "#DailyEnglish",
]

HASHTAG_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "had",
    "has",
    "have",
    "he",
    "her",
    "his",
    "i",
    "if",
    "in",
    "is",
    "it",
    "its",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "she",
    "so",
    "that",
    "the",
    "their",
    "them",
    "there",
    "they",
    "this",
    "to",
    "us",
    "was",
    "we",
    "were",
    "with",
    "you",
    "your",
}

SYSTEM_PROMPT = """You are an expert curriculum designer and content creator for English listening practice.

Your task is to generate short, highly engaging monologue scripts based on a provided theme.
CRITICAL: You must generate a COMPLETELY RANDOM and UNIQUE topic every time. Do not default to "Morning Routine" or "Evening Routine". Pick highly specific, varied, and unexpected daily moments (e.g., "Trying to find lost keys before work", "My chaotic Sunday meal prep", "Waiting for the bus in the rain").

Focus on natural spoken English, using common idioms, conversational fillers, and practical vocabulary suitable for the target difficulty level.

You must output ONLY valid JSON, with no markdown and no extra text.
The JSON must include these keys:
- topic (string, a highly specific situation generated from the broad theme, e.g., "My 10-minute speed-cleaning routine")
- title_en (string, uppercase style, short, catchy)
- text_en (string, 100-120 English words, clear, one topic, spoken conversational tone)
- difficulty (string, e.g. A2-B1)
- hashtags (array of 4-8 strings, each starts with #)

Content constraints for High-Quality Listening Practice:
- text_en MUST sound like a real person talking naturally (use contractions like "I'm", "doesn't", casual transitions).
- Include 1-2 useful phrasal verbs or everyday expressions appropriate for the difficulty.
- Keep text_en engaging for a ~50-60s narration at normal speed.
- Avoid overly formal, textbook-style sentences.
"""

TEXT_ONLY_SYSTEM_PROMPT = """You are an expert English script writer for short listening practice videos.
You are given a title and you must produce only the narration text.
Return strict JSON with exactly one key: text_en.
Rules for text_en:
- 100-120 English words.
- Natural 1-person spoken monologue.
- Conversational and practical vocabulary suitable for the requested difficulty.
- Must match the given title closely.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate short-reel content JSON using OpenRouter or manual input.",
    )
    parser.add_argument(
        "--content-mode",
        choices=[MODE_LLM_FULL, MODE_LLM_FROM_TITLE, MODE_MANUAL],
        default=MODE_LLM_FULL,
        help=(
            "1=LLM full generation from theme/topic, "
            "2=provide title + LLM generates text, "
            "3=provide title + text manually"
        ),
    )
    parser.add_argument(
        "--theme",
        default=DEFAULT_THEME,
        help=f"Broad theme to base the topic on (default: '{DEFAULT_THEME}')",
    )
    parser.add_argument("--topic", help="Specific topic for mode 1 (overrides theme generation)")
    parser.add_argument(
        "--title-en",
        help="User-provided English title (required for mode 2 and mode 3)",
    )
    parser.add_argument(
        "--text-en",
        help="User-provided English narration text (required for mode 3)",
    )
    parser.add_argument(
        "--hashtags",
        help="Optional custom hashtags. Use comma-separated or space-separated values.",
    )
    parser.add_argument(
        "--difficulty",
        default=DEFAULT_DIFFICULTY,
        help=f"Difficulty label (default: {DEFAULT_DIFFICULTY})",
    )
    parser.add_argument(
        "--target-duration",
        type=int,
        default=DEFAULT_TARGET_DURATION,
        help=f"Target narration duration in seconds (default: {DEFAULT_TARGET_DURATION})",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"OpenRouter model (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--project-id",
        help="Optional project id. If omitted, auto-generated from date/time.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Base output path. Default: <script_dir>/output/short_video",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not call API. Only validate setup and print the resolved mode/settings.",
    )
    return parser.parse_args()


def load_env(project_dir: Path) -> None:
    env_candidates = [
        project_dir / ".env",
        project_dir.parent / ".env",
        project_dir.parent.parent / ".env",
    ]
    for env_path in env_candidates:
        if env_path.exists():
            load_dotenv(dotenv_path=env_path)


def ensure_api_key() -> str:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing OPENROUTER_API_KEY. Add it to your .env file.")
    return api_key


def resolve_project_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def topic_to_slug(topic: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", topic).strip("_")
    return cleaned.lower()[:48] or "short_topic"


def read_topic_from_file(project_dir: Path) -> str:
    topic_file = project_dir / "input" / "topics.txt"
    if not topic_file.exists():
        return ""
    return topic_file.read_text(encoding="utf-8").strip()


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_title_en(title: str) -> str:
    return normalize_whitespace(title).upper()


def derive_topic_from_title(title_en: str) -> str:
    title = normalize_whitespace(title_en)
    if not title:
        return "User Provided Topic"
    return title.title() if title.isupper() else title


def count_english_words(text: str) -> int:
    return len(re.findall(r"[A-Za-z][A-Za-z'-]*", text))


def estimate_duration_seconds(word_count: int, wpm: float = DEFAULT_WPM) -> float:
    if word_count <= 0:
        return 0.0
    return (word_count / wpm) * 60.0


def build_user_prompt(
    theme_or_topic: str,
    difficulty: str,
    target_duration: int,
    is_specific_topic: bool = False,
) -> str:
    if is_specific_topic:
        theme_instruction = f"Topic: {theme_or_topic}\nRequirements:\n1) Use exactly this topic."
    else:
        theme_instruction = (
            f"Theme/Category: {theme_or_topic}\n"
            "Requirements:\n1) Invent a specific, relatable `topic` based on this Theme."
        )

    return f"""Create one short English listening practice monologue.

{theme_instruction}
Difficulty: {difficulty}
Target duration: ~{target_duration} seconds.

Additional Requirements:
2) text_en must be 100-120 English words. It should be a 1-person monologue (e.g., someone talking about their experience).
3) Ensure the tone is conversational and natural for listening practice.
4) Return valid JSON only."""


def build_title_to_text_prompt(title_en: str, difficulty: str, target_duration: int) -> str:
    return f"""Generate one short English listening monologue from this fixed title.

Title (must stay unchanged conceptually): {title_en}
Difficulty: {difficulty}
Target duration: ~{target_duration} seconds.

Return JSON only with exactly this schema:
{{
  "text_en": "<100-120 English words>"
}}
"""


def strip_code_fence(text: str) -> str:
    content = text.strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    return content.strip()


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


def validate_payload(
    payload: dict[str, Any],
    target_duration: int,
    *,
    enforce_word_window: bool = True,
    enforce_duration_window: bool = True,
) -> list[str]:
    errors: list[str] = []

    for field in REQUIRED_FIELDS:
        if field not in payload:
            errors.append(f"Missing field: {field}")

    for field in ("topic", "title_en", "text_en", "difficulty"):
        if field in payload and not isinstance(payload[field], str):
            errors.append(f"Field must be string: {field}")
        elif field in payload and not payload[field].strip():
            errors.append(f"Field is empty: {field}")

    hashtags = normalize_hashtags(payload.get("hashtags"))
    if len(hashtags) < 4 or len(hashtags) > 8:
        errors.append("hashtags must contain 4-8 items")

    if "title_en" in payload and isinstance(payload["title_en"], str):
        title_en = payload["title_en"].strip()
        if title_en != title_en.upper():
            errors.append("title_en should be uppercase")
        if len(title_en) > 80:
            errors.append("title_en is too long (>80 chars)")

    text_en = payload.get("text_en", "")
    if isinstance(text_en, str):
        words = count_english_words(text_en)
        if words <= 0:
            errors.append("text_en must contain English words")
        elif enforce_word_window and (words < 100 or words > 120):
            errors.append(f"text_en should be 100-120 English words (current: {words})")

        if words > 0 and enforce_duration_window:
            estimate = estimate_duration_seconds(words)
            if estimate < max(12, target_duration - 10) or estimate > target_duration + 10:
                errors.append(
                    f"Estimated narration duration is out of range: {estimate:.1f}s for target {target_duration}s"
                )

    return errors


def build_manual_mode_warnings(content: dict[str, Any], target_duration: int) -> list[str]:
    warnings: list[str] = []
    text_en = content.get("text_en", "")
    if not isinstance(text_en, str):
        return warnings

    words = count_english_words(text_en)
    if words < 100 or words > 120:
        warnings.append(
            f"Manual text has {words} words (recommended 100-120 for ~{target_duration}s videos)."
        )
    if words > 0:
        estimate = estimate_duration_seconds(words)
        if estimate < max(12, target_duration - 10) or estimate > target_duration + 10:
            warnings.append(
                f"Estimated duration {estimate:.1f}s may not match target {target_duration}s."
            )
    return warnings


def call_llm_full_content(
    client: OpenAI,
    model: str,
    theme_or_topic: str,
    difficulty: str,
    target_duration: int,
    is_specific_topic: bool = False,
) -> dict[str, Any]:
    prompt = build_user_prompt(theme_or_topic, difficulty, target_duration, is_specific_topic)

    for attempt in range(1, MAX_RETRIES + 2):
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        raw_text = response.choices[0].message.content or "{}"
        cleaned = strip_code_fence(raw_text)

        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            if attempt <= MAX_RETRIES:
                prompt += f"\n\nPrevious attempt failed JSON parsing: {exc}. Return strict JSON only."
                continue
            raise RuntimeError(f"Failed to parse JSON from model after retries: {exc}") from exc

        errors = validate_payload(payload, target_duration)
        if not errors:
            payload["hashtags"] = normalize_hashtags(payload.get("hashtags"))
            payload["title_en"] = normalize_title_en(payload.get("title_en", ""))
            payload["topic"] = normalize_whitespace(payload.get("topic", ""))
            payload["text_en"] = normalize_whitespace(payload.get("text_en", ""))
            payload["difficulty"] = normalize_whitespace(payload.get("difficulty", difficulty))
            return payload

        if attempt <= MAX_RETRIES:
            prompt += f"\n\nPrevious attempt had validation errors: {errors}. Fix all issues."
            continue
        raise RuntimeError(f"Validation failed after retries: {errors}")

    raise RuntimeError("Unexpected generation error.")


def call_llm_text_from_title(
    client: OpenAI,
    model: str,
    title_en: str,
    difficulty: str,
    target_duration: int,
) -> str:
    prompt = build_title_to_text_prompt(title_en, difficulty, target_duration)

    for attempt in range(1, MAX_RETRIES + 2):
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": TEXT_ONLY_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        raw_text = response.choices[0].message.content or "{}"
        cleaned = strip_code_fence(raw_text)

        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            if attempt <= MAX_RETRIES:
                prompt += f"\n\nPrevious attempt failed JSON parsing: {exc}. Return strict JSON only."
                continue
            raise RuntimeError(f"Failed to parse JSON from model after retries: {exc}") from exc

        text_en = payload.get("text_en", "")
        if not isinstance(text_en, str) or not text_en.strip():
            if attempt <= MAX_RETRIES:
                prompt += "\n\nPrevious attempt missed `text_en`. Return strict JSON with `text_en`."
                continue
            raise RuntimeError("Model did not return a valid `text_en`.")

        text_en = normalize_whitespace(text_en)
        words = count_english_words(text_en)
        estimate = estimate_duration_seconds(words)
        if words < 100 or words > 120:
            if attempt <= MAX_RETRIES:
                prompt += f"\n\nPrevious attempt had {words} words. Must be 100-120 words."
                continue
            raise RuntimeError(f"text_en should be 100-120 English words (current: {words})")

        if estimate < max(12, target_duration - 10) or estimate > target_duration + 10:
            if attempt <= MAX_RETRIES:
                prompt += (
                    f"\n\nPrevious attempt duration estimate was {estimate:.1f}s; "
                    f"target is {target_duration}s (+/- 10s)."
                )
                continue
            raise RuntimeError(
                f"Estimated narration duration is out of range: {estimate:.1f}s for target {target_duration}s"
            )

        return text_en

    raise RuntimeError("Unexpected generation error while creating text from title.")


def build_project_id() -> str:
    return datetime.now().strftime("%Y-%m-%d/%H%M%S")


def resolve_project_output_path(
    output_root: Path,
    topic: str,
    project_id: str,
    explicit_project_id: bool,
) -> Path:
    if "/" in project_id:
        date_folder, time_folder = project_id.split("/", 1)
    else:
        date_folder = datetime.now().strftime("%Y-%m-%d")
        time_folder = project_id

    date_path = output_root / date_folder
    date_path.mkdir(parents=True, exist_ok=True)

    slug = topic_to_slug(topic)
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


def persist_content(
    project_dir: Path,
    project_id: str,
    content: dict[str, Any],
    model: str,
    target_duration: int,
    content_mode: str,
) -> Path:
    content_dir = project_dir / "01_content"
    content_dir.mkdir(parents=True, exist_ok=True)

    text_en = content.get("text_en", "")
    word_count = count_english_words(text_en) if isinstance(text_en, str) else 0
    estimate = estimate_duration_seconds(word_count)

    payload = {
        "project_id": project_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "content_mode": content_mode,
        "model": model,
        "target_duration_sec": target_duration,
        "estimated_duration_sec": round(estimate, 2),
        "word_count_en": word_count,
        **content,
    }

    out_path = content_dir / "content.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def require_non_empty(value: str | None, error_message: str) -> str:
    if value is None:
        raise RuntimeError(error_message)
    cleaned = normalize_whitespace(value)
    if not cleaned:
        raise RuntimeError(error_message)
    return cleaned


def build_content_mode_2(
    client: OpenAI,
    model: str,
    title_en: str,
    difficulty: str,
    target_duration: int,
    custom_hashtags: str | None,
) -> dict[str, Any]:
    title_normalized = normalize_title_en(title_en)
    topic = derive_topic_from_title(title_normalized)
    text_en = call_llm_text_from_title(
        client=client,
        model=model,
        title_en=title_normalized,
        difficulty=difficulty,
        target_duration=target_duration,
    )

    hashtags = parse_hashtags_input(custom_hashtags)
    if not hashtags:
        hashtags = generate_hashtags_from_text(title_normalized, text_en)

    content = {
        "topic": topic,
        "title_en": title_normalized,
        "text_en": text_en,
        "difficulty": difficulty,
        "hashtags": hashtags,
    }

    errors = validate_payload(content, target_duration)
    if errors:
        raise RuntimeError(f"Mode 2 content validation failed: {errors}")
    return content


def build_content_mode_3(
    title_en: str,
    text_en: str,
    difficulty: str,
    target_duration: int,
    custom_hashtags: str | None,
) -> tuple[dict[str, Any], list[str]]:
    title_normalized = normalize_title_en(title_en)
    text_normalized = normalize_whitespace(text_en)
    topic = derive_topic_from_title(title_normalized)

    hashtags = parse_hashtags_input(custom_hashtags)
    if not hashtags:
        hashtags = generate_hashtags_from_text(title_normalized, text_normalized)

    content = {
        "topic": topic,
        "title_en": title_normalized,
        "text_en": text_normalized,
        "difficulty": difficulty,
        "hashtags": hashtags,
    }

    errors = validate_payload(
        content,
        target_duration,
        enforce_word_window=False,
        enforce_duration_window=False,
    )
    if errors:
        raise RuntimeError(f"Mode 3 content validation failed: {errors}")

    warnings = build_manual_mode_warnings(content, target_duration)
    return content, warnings


def main() -> None:
    print(f"{APP_NAME} - {APP_STEP} (v{APP_VERSION})")
    args = parse_args()

    project_dir = resolve_project_dir()
    load_env(project_dir)

    explicit_project_id = bool(args.project_id and args.project_id.strip())
    project_id = args.project_id.strip() if explicit_project_id else build_project_id()

    script_dir = Path(__file__).resolve().parent
    output_root = args.output_root or (script_dir / "output" / "short_video")
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    mode = args.content_mode
    print(f"[INFO] Content mode: {mode} - {MODE_LABELS.get(mode, 'Unknown mode')}")
    print(f"[INFO] Project ID: {project_id}")

    if args.dry_run:
        if mode == MODE_LLM_FROM_TITLE:
            require_non_empty(args.title_en, "Mode 2 requires --title-en.")
        elif mode == MODE_MANUAL:
            require_non_empty(args.title_en, "Mode 3 requires --title-en.")
            require_non_empty(args.text_en, "Mode 3 requires --text-en.")
        print("[DRY RUN] Setup OK. No API call executed.")
        return

    try:
        content: dict[str, Any]
        model_tag = args.model

        if mode == MODE_LLM_FULL:
            theme = args.theme
            topic = args.topic or read_topic_from_file(project_dir)
            is_specific_topic = bool(topic and topic.strip())
            prompt_input = topic.strip() if is_specific_topic else theme.strip()

            print(f"[INFO] Using {'Topic' if is_specific_topic else 'Theme'}: {prompt_input}")
            api_key = ensure_api_key()
            client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=api_key,
            )
            content = call_llm_full_content(
                client=client,
                model=args.model,
                theme_or_topic=prompt_input,
                difficulty=args.difficulty,
                target_duration=args.target_duration,
                is_specific_topic=is_specific_topic,
            )

        elif mode == MODE_LLM_FROM_TITLE:
            title_en = require_non_empty(args.title_en, "Mode 2 requires --title-en.")
            print(f"[INFO] Using user title for generation: {title_en}")

            api_key = ensure_api_key()
            client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=api_key,
            )
            content = build_content_mode_2(
                client=client,
                model=args.model,
                title_en=title_en,
                difficulty=args.difficulty,
                target_duration=args.target_duration,
                custom_hashtags=args.hashtags,
            )

        elif mode == MODE_MANUAL:
            title_en = require_non_empty(args.title_en, "Mode 3 requires --title-en.")
            text_en = require_non_empty(args.text_en, "Mode 3 requires --text-en.")
            print("[INFO] Using fully manual content (no LLM call).")

            content, warnings = build_content_mode_3(
                title_en=title_en,
                text_en=text_en,
                difficulty=args.difficulty,
                target_duration=args.target_duration,
                custom_hashtags=args.hashtags,
            )
            for warning in warnings:
                print(f"[WARN] {warning}")
            model_tag = MANUAL_MODEL_TAG

        else:
            raise RuntimeError(f"Unsupported mode: {mode}")

        generated_topic = content.get("topic", "Generated Topic")
        print(f"[INFO] Content Ready. Topic: {generated_topic}")

        project_output_dir = resolve_project_output_path(
            output_root=output_root,
            topic=generated_topic,
            project_id=project_id,
            explicit_project_id=explicit_project_id,
        )
        project_id = project_output_dir.name

        output_preview = project_output_dir / "01_content" / "content.json"
        print(f"[INFO] Topic Folder: {project_output_dir.parent.name}")
        print(f"[INFO] Output: {output_preview}")

        out_path = persist_content(
            project_dir=project_output_dir,
            project_id=project_id,
            content=content,
            model=model_tag,
            target_duration=args.target_duration,
            content_mode=mode,
        )
    except Exception as exc:
        raise SystemExit(f"Failed: {exc}") from exc

    print(f"[DONE] Content saved: {out_path}")


if __name__ == "__main__":
    main()
