import argparse
import json
import os
import sys
import re
import time
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

APP_NAME = "SocialHarvester"
APP_STEP = "Step 4: Generate YouTube Metadata"
APP_VERSION = "1.0.0"

DEFAULT_MODEL = "google/gemini-2.5-flash"

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate YouTube Title and Description from Content JSON.")
    parser.add_argument("--project-dir", type=Path, help="Path to the specific project directory")
    parser.add_argument(
        "--strict-llm",
        action="store_true",
        help="If set, fail when LLM metadata generation fails (no fallback).",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Retry count for LLM requests on transient network failures (default: 2).",
    )
    return parser.parse_args()

def load_env_and_get_client(project_dir: Path) -> OpenAI:
    curr = project_dir.resolve()
    env_targets = []
    for _ in range(4):
        env_targets.append(curr / ".env")
        if curr.parent == curr:
            break
        curr = curr.parent

    for env_path in env_targets:
        if env_path.exists():
            load_dotenv(dotenv_path=env_path)
            break
            
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing OPENROUTER_API_KEY. Add it to your .env file.")
        
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

def resolve_latest_project_dir(base_output_dir: Path) -> Path:
    candidates = []
    if base_output_dir.exists():
        for topic_dir in base_output_dir.iterdir():
            if topic_dir.is_dir():
                for proj_dir in topic_dir.iterdir():
                    if proj_dir.is_dir() and (proj_dir / "01_content" / "content.json").exists():
                        candidates.append(proj_dir)
    
    if not candidates:
        raise RuntimeError(f"No valid project directories found in {base_output_dir}")
    
    candidates.sort(key=lambda p: p.stat().st_ctime, reverse=True)
    return candidates[0]

def load_template(project_root: Path) -> str:
    template_path = project_root / "content" / "youtube_content.md"
    if not template_path.exists():
        print(f"[WARNING] YouTube template not found at {template_path}. Using a default template format.")
        return """# YOUTUBE VIDEO METADATA\n\n## TIÊU ĐỀ (TITLE)\n\n[Your Catchy Title] | English Reading & Listening Practice ([Difficulty])\n\n## MÔ TẢ (DESCRIPTION)\n\n🚀 The Story: [Topic]\n[Short engaging hook based on the text]\n\n"[An engaging quote from the script]"\n\n🎧 Key Vocabulary:\n- [Word 1]\n- [Word 2]\n\n📝 How to use this video:\n1️⃣ Listen and read along with the highlighted text\n2️⃣ Pause and repeat to practice speaking\n3️⃣ Watch daily to build habits and confidence\n\n🌟 About this channel:\nThis video is made for English learners who want to build confidence through real-life listening and reading practice.\n\n---\n#englishforbeginners #learnenglish #englishlistening"""
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()

def generate_youtube_metadata(
    client: OpenAI,
    topic: str,
    text: str,
    difficulty: str,
    hashtags: list,
    template: str,
    max_retries: int = 2,
) -> str:
    print("[INFO] Generating YouTube Metadata using LLM...")
    
    sys_prompt = f"""You are an expert YouTube SEO Manager and Content Creator for an English learning channel.
Your task is to take a video's topic, script, difficulty level, and keywords, and format them into a highly engaging YouTube Title and Description.

CRITICAL: You MUST strictly follow the structural format of the provided Markdown Template.
- Do NOT use any markdown formatting such as asterisks (**bold**, *italic*). Output plain text only for all sections.
- Translate the summary/hook to Vietnamese or keep it English based on what looks natural for the target audience in the template (if the template uses English for the hook, use English). 
- Ensure the Title follows the `Catchy Hook | English Reading & Listening Practice (Level)` format.
- Extract 8-10 highly relevant vocabulary words from the script for the 'Key Vocabulary' section.
- Incorporate the provided hashtags at the bottom of the description.

TEMPLATE TO FOLLOW STRICLY:
{template}
"""
    hashtags_str = " ".join(hashtags)
    user_prompt = f"Topic: {topic}\nDifficulty: {difficulty}\nScript: {text}\nProvided Hashtags: {hashtags_str}\n\nGenerate the complete Markdown string for the Tiêu đề and Mô tả exactly following the template structure."
    
    retries = max(0, int(max_retries))
    for attempt in range(retries + 1):
        try:
            response = client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
            )
            metadata = response.choices[0].message.content.strip()
            if metadata:
                return metadata
            raise RuntimeError("LLM returned empty metadata content.")
        except Exception as exc:
            if attempt >= retries:
                raise
            wait_sec = min(8, 2 ** attempt)
            print(
                f"[WARN] LLM request failed (attempt {attempt + 1}/{retries + 1}): {exc}. "
                f"Retrying in {wait_sec}s..."
            )
            time.sleep(wait_sec)

    raise RuntimeError("Unexpected metadata generation retry flow.")


def normalize_hashtags(hashtags: list) -> list[str]:
    out = []
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
        out.append(tag)
    return out


def extract_vocabulary(text: str, limit: int = 10) -> list[str]:
    stopwords = {
        "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for", "from", "had", "has", "have",
        "he", "her", "his", "i", "if", "in", "is", "it", "its", "me", "my", "of", "on", "or", "our", "she",
        "so", "that", "the", "their", "them", "there", "they", "this", "to", "was", "we", "were", "with",
        "you", "your",
    }
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", text.lower())
    filtered = [w for w in words if len(w) >= 4 and w not in stopwords]
    counts = Counter(filtered)
    return [w for w, _ in counts.most_common(limit)]


def generate_youtube_metadata_fallback(topic: str, text: str, difficulty: str, hashtags: list) -> str:
    hashtags = normalize_hashtags(hashtags) or ["#englishlistening", "#learnenglish", "#englishpractice"]
    hashtags_line = " ".join(hashtags)

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    hook = sentences[0] if sentences else text.strip()
    quote = sentences[1] if len(sentences) > 1 else (sentences[0] if sentences else "")
    if len(hook) > 220:
        hook = hook[:217].rstrip() + "..."
    if len(quote) > 180:
        quote = quote[:177].rstrip() + "..."

    vocab = extract_vocabulary(text, limit=10)
    vocab_lines = "\n".join([f"- {w}" for w in vocab]) if vocab else "- routine\n- confidence\n- practice"

    title = f"{topic} | English Reading & Listening Practice ({difficulty})"
    return (
        "YOUTUBE VIDEO METADATA\n\n"
        "TIÊU ĐỀ (TITLE)\n\n"
        f"{title}\n\n"
        "MÔ TẢ (DESCRIPTION)\n\n"
        f"🚀 The Story: {topic}\n"
        f"{hook}\n\n"
        f"\"{quote}\"\n\n"
        "🎧 Key Vocabulary:\n"
        f"{vocab_lines}\n\n"
        "📝 How to use this video:\n"
        "1️⃣ Listen and read along with the highlighted text\n"
        "2️⃣ Pause and repeat to practice speaking\n"
        "3️⃣ Watch daily to build habits and confidence\n\n"
        "🌟 About this channel:\n"
        "This video is made for English learners who want to build confidence through real-life listening and reading practice.\n\n"
        "---\n"
        f"{hashtags_line}\n\n"
        "_Generated by local fallback because LLM connection was unavailable._\n"
    )

def main():
    print(f"{APP_NAME} - {APP_STEP} (v{APP_VERSION})")
    args = parse_args()
    
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parents[1]
    base_output_dir = script_dir / "output" / "short_video"
    
    proj_dir = args.project_dir
    if not proj_dir:
        print("[INFO] No --project-dir provided. Resolving latest valid project...")
        proj_dir = resolve_latest_project_dir(base_output_dir)
            
    proj_dir = proj_dir.resolve()
    print(f"[INFO] Target Project: {proj_dir}")
    
    content_file = proj_dir / "01_content" / "content.json"
    if not content_file.exists():
        raise SystemExit("Missing content.json. Ensure Phase 1 completed.")
        
    with open(content_file, "r", encoding="utf-8") as f:
        content_data = json.load(f)
        
    topic = content_data.get("topic", "Daily Routines")
    text = content_data.get("text_en", "")
    difficulty = content_data.get("difficulty", "A2-B1")
    hashtags = content_data.get("hashtags", ["#englishlistening"])
    
    template_str = load_template(project_root)
    metadata_source = "llm"

    try:
        client = load_env_and_get_client(project_root)
        metadata = generate_youtube_metadata(
            client,
            topic,
            text,
            difficulty,
            hashtags,
            template_str,
            max_retries=args.max_retries,
        )
    except Exception as exc:
        if args.strict_llm:
            raise
        print(f"[WARN] LLM metadata generation failed: {exc}")
        print("[INFO] Falling back to local metadata generator...")
        metadata = generate_youtube_metadata_fallback(topic, text, difficulty, hashtags)
        metadata_source = "local_fallback"
    
    out_file = proj_dir / "04_metadata" / "youtube_metadata.md"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(metadata)

    status_file = proj_dir / "04_metadata" / "metadata_status.json"
    status_payload = {
        "source": metadata_source,
        "model": DEFAULT_MODEL if metadata_source == "llm" else "none",
    }
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(status_payload, f, ensure_ascii=False, indent=2)

    print(f"\n[DONE] YouTube Metadata Successfully Generated: {out_file}")
    print(f"[INFO] Metadata source: {metadata_source}")

if __name__ == "__main__":
    main()
