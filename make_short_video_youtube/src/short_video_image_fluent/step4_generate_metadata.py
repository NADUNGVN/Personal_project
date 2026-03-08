import argparse
import json
import os
import sys
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
        return """# YOUTUBE VIDEO METADATA\n\n## TIÊU ĐỀ (TITLE)\n\n[Your Catchy Title] | English Reading & Listening Practice ([Difficulty])\n\n## MÔ TẢ (DESCRIPTION)\n\n🚀 **The Story: [Topic]**\n[Short engaging hook based on the text]\n\n"[An engaging quote from the script]"\n\n🎧 **Key Vocabulary:**\n- [Word 1]\n- [Word 2]\n\n📝 **How to use this video:**\n1️⃣ Listen and read along with the highlighted text\n2️⃣ Pause and repeat to practice speaking\n3️⃣ Watch daily to build habits and confidence\n\n🌟 **About this channel:**\nThis video is made for English learners who want to build confidence through real-life listening and reading practice.\n\n---\n#englishforbeginners #learnenglish #englishlistening"""
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()

def generate_youtube_metadata(client: OpenAI, topic: str, text: str, difficulty: str, hashtags: list, template: str) -> str:
    print("[INFO] Generating YouTube Metadata using LLM...")
    
    sys_prompt = f"""You are an expert YouTube SEO Manager and Content Creator for an English learning channel.
Your task is to take a video's topic, script, difficulty level, and keywords, and format them into a highly engaging YouTube Title and Description.

CRITICAL: You MUST strictly follow the structural format of the provided Markdown Template.
- Translate the summary/hook to Vietnamese or keep it English based on what looks natural for the target audience in the template (if the template uses English for the hook, use English). 
- Ensure the Title follows the `Catchy Hook | English Reading & Listening Practice (Level)` format.
- Extract 8-10 highly relevant vocabulary words from the script for the 'Key Vocabulary' section.
- Incorporate the provided hashtags at the bottom of the description.

TEMPLATE TO FOLLOW STRICLY:
{template}
"""
    hashtags_str = " ".join(hashtags)
    user_prompt = f"Topic: {topic}\nDifficulty: {difficulty}\nScript: {text}\nProvided Hashtags: {hashtags_str}\n\nGenerate the complete Markdown string for the Tiêu đề and Mô tả exactly following the template structure."
    
    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
    )
    metadata = response.choices[0].message.content.strip()
    return metadata

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
    
    client = load_env_and_get_client(project_root)
    template_str = load_template(project_root)
    
    metadata = generate_youtube_metadata(client, topic, text, difficulty, hashtags, template_str)
    
    out_file = proj_dir / "04_metadata" / "youtube_metadata.md"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(metadata)
        
    print(f"\n[DONE] YouTube Metadata Successfully Generated: {out_file}")

if __name__ == "__main__":
    main()
