import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, "input")
STORY_DETAILS_FILE = os.path.join(INPUT_DIR, "story_details.json")
TOPICS_FILE = os.path.join(INPUT_DIR, "topics.txt")
CURRENT_OUT_DIR_FILE = os.path.join(INPUT_DIR, "current_output_dir.txt")

# Support both <project>/.env and <workspace>/.env
for env_path in (
    os.path.join(BASE_DIR, ".env"),
    os.path.join(os.path.dirname(BASE_DIR), ".env"),
):
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path)
        break

def setup_env():
    os.makedirs(INPUT_DIR, exist_ok=True)
    
PIPELINE_STEPS = [
    {
        "script": "story_generator.py",
        "label": "AI Storyteller (Davis) evaluates and writes folklore script",
        "icon": "[STORY]",
    },
    {
        "script": "story_tts.py",
        "label": "Generate speech with VibeVoice (Davis)",
        "icon": "[TTS]",
    },
    {
        "script": "video_renderer.py",
        "label": "Render storytelling video",
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
        import shutil
        i = 0
        while self._running:
            elapsed = time.time() - self._start_time
            m, s = divmod(int(elapsed), 60)
            frame = self.FRAMES[i % len(self.FRAMES)]
            info = f"  {frame} [{self.step_num}/{self.total_steps}] {self.label} ... {m:02d}:{s:02d}"
            if self._last_info:
                info += f" | {self._last_info}"
                
            try:
                term_width = shutil.get_terminal_size((80, 20)).columns
            except Exception:
                term_width = 80
                
            if term_width > 0 and len(info) >= term_width:
                info = info[:term_width - 4] + "..."
                
            sys.stdout.write(f"\r\033[K{info}")
            sys.stdout.flush()
            i += 1
            time.sleep(0.12)

    def update_info(self, text: str):
        clean = text.strip().replace("\r", "").replace("\n", " ")
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

# ================= UI HELPERS =================
FLOW_NEW = "1"
FLOW_CONTINUE = "2"

def choose_flow_mode() -> str:
    print("\nSelect storytelling action:")
    print("1) Tell a new story")
    print("2) Continue existing story project by path")
    while True:
        choice = input("Choose action (1/2): ").strip()
        if choice in {FLOW_NEW, FLOW_CONTINUE}:
            return choice
        print("Invalid choice. Please enter 1 or 2.")

def clean_user_path(raw_path: str) -> str:
    cleaned = raw_path.strip().strip('"').strip("'")
    return os.path.abspath(os.path.expanduser(cleaned))

def prompt_project_dir() -> str:
    while True:
        raw = input("Enter existing project folder path: ").strip()
        if not raw:
            print("Path cannot be empty. Please try again.")
            continue
            
        path = clean_user_path(raw)
        if not os.path.exists(path):
            print(f"Path does not exist: {path}")
            continue
        if not os.path.isdir(path):
            print(f"Path is not a folder: {path}")
            continue
        return path

def inspect_project(project_dir: str):
    """
    Returns: (start_step_index, topic, safe_topic_name)
    """
    files = os.listdir(project_dir)
    safe_topic_name = None
    for f in files:
        if f.endswith("_script.json"):
            safe_topic_name = f.replace("_script.json", "")
            break
            
    if not safe_topic_name:
        for f in files:
            if f.endswith("_podcast.mp3"):
                safe_topic_name = f.replace("_podcast.mp3", "")
                break
                
    if not safe_topic_name:
        safe_topic_name = os.path.basename(project_dir)
        
    start_step = 1
    
    script_file = os.path.join(project_dir, f"{safe_topic_name}_script.json")
    mp3_file = os.path.join(project_dir, f"{safe_topic_name}_podcast.mp3")
    video_file = os.path.join(project_dir, f"{safe_topic_name}_Final_Video.mp4")
    
    if os.path.exists(script_file) and os.path.getsize(script_file) > 0:
        start_step = 2
            
    if os.path.exists(mp3_file) and os.path.getsize(mp3_file) > 0:
        start_step = 3
        
    if os.path.exists(video_file) and os.path.getsize(video_file) > 0:
        start_step = 4
        
    # Attempt to read topic from topic file if available in the source dir
    topic = ""
    # Since topic is not perfectly bound to the project output in vibe-voice, 
    # we will prompt the user if we can't extract it.
    topic = input(f"Please confirm the story title for {project_dir}: ").strip()
        
    return start_step, topic, safe_topic_name

def main():
    os.chdir(BASE_DIR)
    setup_env()

    print("\n" + "=" * 64)
    print("  📜 DAVIS STORYTELLING PIPELINE")
    print("=" * 64)

    flow_mode = choose_flow_mode()

    if flow_mode == FLOW_NEW:
        print("\n[STORY DETAILS]")
        story_title = input("Enter the Story Title (e.g., The Story of Saint Giong): ").strip()
        if not story_title:
            print("Story Title is required!")
            sys.exit(1)
            
        story_origin = input("Enter the Origin of the Story (e.g., Vietnam, Greek Mythology): ").strip()
        if not story_origin:
            print("Origin is required!")
            sys.exit(1)
            
        print("Enter a brief synopsis or content of the story (Press ENTER on empty line to finish):")
        synopsis_lines = []
        while True:
            line = input()
            if not line.strip():
                break
            synopsis_lines.append(line)
        story_synopsis = "\n".join(synopsis_lines)
        
        if not story_synopsis:
            print("Synopsis is required!")
            sys.exit(1)
            
        story_details = {
            "title": story_title,
            "origin": story_origin,
            "synopsis": story_synopsis
        }
        
        with open(STORY_DETAILS_FILE, "w", encoding="utf-8") as f:
            json.dump(story_details, f, indent=2, ensure_ascii=False)
            
        # Write to TOPICS_FILE for legacy compatibility
        with open(TOPICS_FILE, "w", encoding="utf-8") as f:
            f.write(story_title + "\n")

        date_str = datetime.now().strftime("%d_%m_%Y")
        safe_topic_name = "".join([c for c in story_title if c.isalnum() or c == " "]).rstrip().replace(" ", "_")
        dynamic_out_dir = os.path.join(BASE_DIR, "output", date_str, safe_topic_name)
        os.makedirs(dynamic_out_dir, exist_ok=True)
        
        with open(CURRENT_OUT_DIR_FILE, "w", encoding="utf-8") as f:
            f.write(dynamic_out_dir)
            
        OUTPUT_DIR = dynamic_out_dir
        start_step = 1
        topic = story_title

    else:
        project_dir = prompt_project_dir()
        start_step, topic, safe_topic_name = inspect_project(project_dir)
        OUTPUT_DIR = project_dir
        
        with open(TOPICS_FILE, "w", encoding="utf-8") as f:
            f.write(topic + "\n")
            
        with open(CURRENT_OUT_DIR_FILE, "w", encoding="utf-8") as f:
            f.write(project_dir)
            
        if start_step > len(PIPELINE_STEPS):
            print(f"\n✅ Pipeline completed for this project: {project_dir}")
            return
            
        print(f"\nContinuing from Step {start_step}...")

    total = len(PIPELINE_STEPS)

    print("\n" + "=" * 64)
    print(f"  Title: {topic}")
    print(f"  Output: {OUTPUT_DIR}")
    print("=" * 64 + "\n")

    for i, step in enumerate(PIPELINE_STEPS, start=1):
        if i >= start_step:
            run_step(step["script"], step["label"], step["icon"], i, total)
        else:
            print(f"  ⏩ Skipped Step {i}: {step['label']} (Already Completed)")

    print("\n" + "=" * 64)
    print(f"  🎉 COMPLETE! Outputs are in: {OUTPUT_DIR}")
    print("=" * 64 + "\n")


if __name__ == "__main__":
    main()
