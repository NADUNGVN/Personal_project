import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime

from dotenv import load_dotenv
from openai import OpenAI


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, "input")
TOPICS_FILE = os.path.join(INPUT_DIR, "topics.txt")
CURRENT_OUT_DIR_FILE = os.path.join(INPUT_DIR, "current_output_dir.txt")

for env_path in (
    os.path.join(BASE_DIR, ".env"),
    os.path.join(os.path.dirname(BASE_DIR), ".env"),
):
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path)
        break

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

if os.path.exists(CURRENT_OUT_DIR_FILE):
    with open(CURRENT_OUT_DIR_FILE, "r", encoding="utf-8") as f:
        OUTPUT_DIR = f.read().strip()
else:
    OUTPUT_DIR = os.path.join(BASE_DIR, "output")

os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

PIPELINE_STEPS = [
    {
        "script": "podcast_generator.py",
        "label": "Generate podcast script (LLM)",
        "icon": "[SCRIPT]",
    },
    {
        "script": "vibevoice_tts.py",
        "label": "Generate speech with VibeVoice",
        "icon": "[TTS]",
    },
    {
        "script": "video_renderer.py",
        "label": "Render karaoke video",
        "icon": "[VIDEO]",
    },
]


class PipelineSpinner:
    FRAMES = ["|", "/", "-", "\\"]

    def __init__(self, label: str, step_num: int, total_steps: int):
        self.label = label
        self.step_num = step_num
        self.total_steps = total_steps
        self._running = False
        self._thread = None
        self._start_time = 0.0
        self._last_info = ""

    def _spin(self):
        i = 0
        while self._running:
            elapsed = time.time() - self._start_time
            m, s = divmod(int(elapsed), 60)
            frame = self.FRAMES[i % len(self.FRAMES)]
            info = f"  {frame} [{self.step_num}/{self.total_steps}] {self.label} ... {m:02d}:{s:02d}"
            if self._last_info:
                info += f" | {self._last_info}"
            sys.stdout.write(f"\r\033[K{info}")
            sys.stdout.flush()
            i += 1
            time.sleep(0.12)

    def update_info(self, text: str):
        clean = text.strip().replace("\r", "").replace("\n", " ")
        if len(clean) > 80:
            clean = clean[:77] + "..."
        self._last_info = clean

    def start(self):
        self._start_time = time.time()
        self._running = True
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self, success=True):
        self._running = False
        if self._thread:
            self._thread.join()
        elapsed = time.time() - self._start_time
        m, s = divmod(int(elapsed), 60)
        status = "OK" if success else "FAIL"
        sys.stdout.write(
            f"\r\033[K  [{status}] [{self.step_num}/{self.total_steps}] {self.label} ({m:02d}:{s:02d})\n"
        )
        sys.stdout.flush()


def run_step(script_name: str, label: str, icon: str, step_num: int, total_steps: int):
    spinner = PipelineSpinner(f"{icon} {label}", step_num, total_steps)
    spinner.start()

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    process = subprocess.Popen(
        [sys.executable, os.path.join("scripts", script_name)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=BASE_DIR,
    )

    log_lines = []
    for line in iter(process.stdout.readline, ""):
        log_lines.append(line)
        stripped = line.strip()
        if stripped:
            spinner.update_info(stripped)

    process.stdout.close()
    return_code = process.wait()

    if return_code != 0:
        spinner.stop(success=False)
        print(f"\n  [ERROR] {script_name} failed with exit code {return_code}")
        print("  --- LAST 20 LINES ---")
        for err_line in log_lines[-20:]:
            print("  " + err_line.rstrip())
        print("  ---------------------")
        sys.exit(return_code)

    spinner.stop(success=True)


def _extract_timestamp_lines(script_data: dict, subtitles_data: list) -> str:
    heading_titles = [
        item.get("title", item.get("text_display", "Section"))
        for item in script_data.get("script", [])
        if item.get("type") == "heading"
    ]

    lines = ["0:00 Welcome to English Podcast Everyday"]
    heading_idx = 0

    for sub in subtitles_data:
        if sub.get("type") != "heading":
            continue

        start_sec = int(sub.get("start_time_sec", 0))
        mins = start_sec // 60
        secs = start_sec % 60

        title = heading_titles[heading_idx] if heading_idx < len(heading_titles) else sub.get("text", "Section")

        if heading_idx == 0:
            # First heading is forced to 0:00 intro line
            heading_idx += 1
            continue

        lines.append(f"{mins}:{secs:02d} {title}")
        heading_idx += 1

    if len(lines) == 1:
        lines.extend([
            "1:50 Chapter 1",
            "4:30 Chapter 2",
            "7:00 Outro",
        ])

    return "\n".join(lines)


def generate_youtube_metadata(topic: str, base_name: str):
    if not OPENROUTER_API_KEY:
        print("  [WARN] Skip metadata: OPENROUTER_API_KEY missing")
        return

    json_path = os.path.join(OUTPUT_DIR, f"{base_name}_script.json")
    subs_path = os.path.join(OUTPUT_DIR, f"{base_name}_subtitles.json")

    if not os.path.exists(json_path):
        print(f"  [WARN] Skip metadata: missing {json_path}")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        script_data = json.load(f)

    script_text = "\n".join(
        item.get("text_display", "")
        for item in script_data.get("script", [])
        if item.get("type") == "dialogue"
    )

    if os.path.exists(subs_path):
        with open(subs_path, "r", encoding="utf-8") as f:
            subtitles_data = json.load(f)
    else:
        subtitles_data = []

    timestamps_text = _extract_timestamp_lines(script_data, subtitles_data)

    prompt = f"""
I have generated a podcast video about the topic: "{topic}".
Here is the raw script of the podcast:
---
{script_text}
---

Please generate YouTube Title, Description, and Tags.

CRITICAL: For the TIMESTAMPS section, use these exact timestamps and do not change times:
{timestamps_text}

Output in this structure:
- Title
- Description
- Tags
- What you will learn (3-6 bullets)
- TIMESTAMPS
"""

    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)

    try:
        response = client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[
                {"role": "system", "content": "You are an expert YouTube content creator and copywriter."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
        )
        content = response.choices[0].message.content.strip()

        md_file = os.path.join(OUTPUT_DIR, f"{base_name}_youtube_content.md")
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(content)

    except Exception as exc:
        print(f"\n  [WARN] Metadata API call failed: {exc}")


def main():
    import argparse

    os.chdir(BASE_DIR)

    parser = argparse.ArgumentParser(description="VibeVoice YouTube Video Production Pipeline")
    parser.add_argument("--topic", type=str, help="Topic for the video/podcast")
    args = parser.parse_args()

    topic = args.topic.strip() if args.topic else ""
    if not topic:
        topic = input("Enter video topic: ").strip()

    if not topic:
        print("Topic cannot be empty")
        sys.exit(1)

    with open(TOPICS_FILE, "w", encoding="utf-8") as f:
        f.write(topic + "\n")

    date_str = datetime.now().strftime("%d_%m_%Y")
    safe_topic_name = "".join([c for c in topic if c.isalnum() or c == " "]).rstrip().replace(" ", "_")
    dynamic_out_dir = os.path.join(BASE_DIR, "output", date_str, safe_topic_name)
    os.makedirs(dynamic_out_dir, exist_ok=True)

    with open(CURRENT_OUT_DIR_FILE, "w", encoding="utf-8") as f:
        f.write(dynamic_out_dir)

    global OUTPUT_DIR
    OUTPUT_DIR = dynamic_out_dir

    total = len(PIPELINE_STEPS) + 1

    print("\n" + "=" * 64)
    print("  VIBEVOICE VIDEO PIPELINE")
    print(f"  Topic: {topic}")
    print(f"  Output: {dynamic_out_dir}")
    print("=" * 64 + "\n")

    for i, step in enumerate(PIPELINE_STEPS, start=1):
        run_step(step["script"], step["label"], step["icon"], i, total)

    spinner = PipelineSpinner("[META] Generate YouTube title/description", total, total)
    spinner.start()
    generate_youtube_metadata(topic, safe_topic_name)
    spinner.stop(success=True)

    print("\n" + "=" * 64)
    print(f"  COMPLETE. Outputs are in: {OUTPUT_DIR}")
    print("=" * 64 + "\n")


if __name__ == "__main__":
    main()
