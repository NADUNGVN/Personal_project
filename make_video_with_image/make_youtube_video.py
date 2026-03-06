import os
import sys
import subprocess
import json
import time
import threading
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, "input")
TOPICS_FILE = os.path.join(INPUT_DIR, "topics.txt")

# Read dynamic output directory if it exists, otherwise default to "output"
CURRENT_OUT_DIR_FILE = os.path.join(INPUT_DIR, "current_output_dir.txt")
if os.path.exists(CURRENT_OUT_DIR_FILE):
    with open(CURRENT_OUT_DIR_FILE, "r", encoding="utf-8") as f:
        OUTPUT_DIR = f.read().strip()
else:
    OUTPUT_DIR = os.path.join(BASE_DIR, "output")
    
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(INPUT_DIR, exist_ok=True)

# ================= PIPELINE STEPS =================
PIPELINE_STEPS = [
    {"script": "podcast_generator.py", "label": "Tạo kịch bản Podcast (LLM)",           "icon": "📝"},
    {"script": "kokoro_tts.py",        "label": "Chuyển văn bản thành giọng nói (TTS)",  "icon": "🎙️"},
    {"script": "video_renderer.py",    "label": "Render Video (Karaoke + Visualizer)",   "icon": "🎬"},
]

# ================= SPINNER + PROGRESS BAR =================
class PipelineSpinner:
    """Hiển thị thanh tiến trình xoay tròn trên 1 dòng duy nhất."""
    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, label, step_num, total_steps):
        self.label = label
        self.step_num = step_num
        self.total_steps = total_steps
        self._running = False
        self._thread = None
        self._start_time = 0
        self._last_info = ""

    def _spin(self):
        i = 0
        while self._running:
            elapsed = time.time() - self._start_time
            m, s = divmod(int(elapsed), 60)
            frame = self.FRAMES[i % len(self.FRAMES)]
            info = f"  {frame} [{self.step_num}/{self.total_steps}] {self.label} ... {m:02d}:{s:02d}"
            if self._last_info:
                info += f"  | {self._last_info}"
            sys.stdout.write(f"\r\033[K{info}")
            sys.stdout.flush()
            i += 1
            time.sleep(0.12)

    def update_info(self, text):
        """Cập nhật thông tin phụ hiện trên cùng dòng."""
        clean = text.strip().replace("\r", "").replace("\n", " ")
        if len(clean) > 60:
            clean = clean[:57] + "..."
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
        icon = "✅" if success else "❌"
        sys.stdout.write(f"\r\033[K  {icon} [{self.step_num}/{self.total_steps}] {self.label}  ({m:02d}:{s:02d})\n")
        sys.stdout.flush()

# ================= CORE FUNCTIONS =================
def run_step(script_name, label, icon, step_num, total_steps):
    """Chạy 1 script con và hiện thanh spinner gọn gàng."""
    spinner = PipelineSpinner(f"{icon}  {label}", step_num, total_steps)
    spinner.start()

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    process = subprocess.Popen(
        [sys.executable, f"scripts/{script_name}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        env=env
    )

    log_lines = []
    for line in iter(process.stdout.readline, ''):
        log_lines.append(line)
        stripped = line.strip()
        if stripped:
            spinner.update_info(stripped)

    process.stdout.close()
    return_code = process.wait()

    if return_code != 0:
        spinner.stop(success=False)
        print(f"\n  ❌ {script_name} thất bại với mã lỗi {return_code}")
        print("  --- CHI TIẾT LỖI (15 DÒNG CUỐI) ---")
        for err_line in log_lines[-15:]:
            print("  " + err_line.rstrip())
        print("  -----------------------------------")
        sys.exit(return_code)
    else:
        spinner.stop(success=True)

def generate_youtube_metadata(topic, base_name):
    if not OPENROUTER_API_KEY:
        print("  ⚠ Bỏ qua: Không tìm thấy OPENROUTER_API_KEY")
        return

    json_path = os.path.join(OUTPUT_DIR, f"{base_name}_script.json")
    subs_path = os.path.join(OUTPUT_DIR, f"{base_name}_subtitles.json")
    
    if not os.path.exists(json_path):
        print(f"  ⚠ Bỏ qua: Không tìm thấy {json_path}")
        return

    with open(json_path, 'r', encoding='utf-8') as f:
        script_data = json.load(f)
        
    script_text = "\n".join([
        item.get('text_display', '')
        for item in script_data.get('script', [])
        if item.get('type') == 'dialogue'
    ])
    
    # Extract exact timestamps from subtitles
    timestamps_text = "0:00 Welcome to English Podcast Everyday\\n"
    if os.path.exists(subs_path) and script_data:
        with open(subs_path, 'r', encoding='utf-8') as f:
            subtitles_data = json.load(f)
            
        script_headings = [item.get("title", "Section") for item in script_data.get('script', []) if item.get("type") == "heading"]
        
        timestamps_list = []
        heading_idx = 0
        for sub in subtitles_data:
            if sub.get("type") == "heading":
                start_sec = int(sub.get("start_time_sec", 0))
                mins = start_sec // 60
                secs = start_sec % 60
                
                # Get the clean short title from script.json
                title = script_headings[heading_idx] if heading_idx < len(script_headings) else sub.get("text", "Section")
                
                # Bỏ qua Outro/Intro nếu quá nhiều hoặc lặp lại
                if heading_idx == 0:
                    pass # Đã fix cứng 0:00 ở trên
                else:
                    timestamps_list.append(f"{mins}:{secs:02d} {title}")
                heading_idx += 1
                
        if len(timestamps_list) > 0:
            timestamps_text += "\\n".join(timestamps_list)
        else:
            timestamps_text += "1:50 [Insert Chapter 1]\\n4:30 [Insert Chapter 2]\\n7:00 Outro"
    else:
        timestamps_text += "1:50 [Insert Chapter 1]\\n4:30 [Insert Chapter 2]\\n7:00 Outro"

    prompt = f"""
I have generated a podcast video about the topic: "{topic}".
Here is the raw script of the podcast we generated:
---
{script_text}
---

Please generate the YouTube Title, Description, and Tags formatted exactly like the example below.
Adapt the bullet points in the "What you will learn" section to match the actual curriculum found in the script.
CRITICAL: For the "TIMESTAMPS" section, you MUST strictly use the exact timestamps provided below. Do not invent or change the times.

EXAMPLE FORMAT:
Title: {topic}

🎧 Max & Mia Podcast – Intermediate Conversations for Real Life!
Unlock your English fluency with natural, real-world conversations.

Are you ready to take your English to the next level? In today’s episode, Max and Mia guide you through everyday English conversations at an intermediate level (A2–B1–B2). Whether you're chatting with coworkers, neighbors, or friends, these phrases and expressions will help you speak more naturally and confidently.

This episode is perfect if you:
- Want to improve your listening skills through real conversation
- Are tired of just memorizing grammar and vocabulary
- Need a fun and simple way to practice shadowing
- Love learning with friendly voices and clear subtitles

💡 Remember: every word, every sentence, every conversation brings you closer to fluency. So grab your favorite drink, relax, and practice with Max and Mia — your English-learning friends!

🎯 Tags:
english podcast for learning english, english for beginners, intermediate english podcast, A2 B1 B2 english listening, english conversation with subtitles, daily english routine, english listening practice, podcast shadowing english, english speaking practice, max and mia english

📄 Transcription:
https://drive.google.com/file/d/1gWB8...

___________________________________________________________________________
📝 What you will learn in this episode:
- [Insert point 1 based on script]
- [Insert point 2 based on script]
- [Insert point 3 based on script]

___________________________________________________________________________
⏱️ TIMESTAMPS:
{timestamps_text}
"""

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )

    try:
        response = client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[
                {"role": "system", "content": "You are an expert YouTube content creator and copywriter."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        content = response.choices[0].message.content.strip()

        md_file = os.path.join(OUTPUT_DIR, f"{base_name}_youtube_content.md")
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(content)

    except Exception as e:
        print(f"\n  ⚠ Lỗi khi gọi API: {e}")

# ================= MAIN =================
def main():
    import argparse

    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    parser = argparse.ArgumentParser(description="YouTube Video Production Pipeline")
    parser.add_argument("--topic", type=str, help="Topic for the video/podcast")
    args = parser.parse_args()

    topic = args.topic
    if not topic:
        topic = input("Nhập chủ đề video (Nội dung chính): ").strip()

    if not topic:
        print("Chủ đề không được để trống!")
        sys.exit(1)

    os.makedirs(INPUT_DIR, exist_ok=True)

    with open(TOPICS_FILE, "w", encoding="utf-8") as f:
        f.write(topic + "\n")

    # --- TẠO THƯ MỤC OUTPUT ĐỘNG THEO NGÀY VÀ CHỦ ĐỀ ---
    from datetime import datetime
    date_str = datetime.now().strftime("%d_%m_%Y")
    safe_topic_name = "".join([c for c in topic if c.isalnum() or c == ' ']).rstrip().replace(" ", "_")
    dynamic_out_dir = os.path.join(BASE_DIR, "output", date_str, safe_topic_name)
    os.makedirs(dynamic_out_dir, exist_ok=True)
    
    # Save the dynamic output dir to a state file so other scripts can read it
    with open(CURRENT_OUT_DIR_FILE, "w", encoding="utf-8") as f:
        f.write(dynamic_out_dir)
        
    global OUTPUT_DIR
    OUTPUT_DIR = dynamic_out_dir
    # -------------------------------------------------------------

    total = len(PIPELINE_STEPS) + 1

    print(f"\n{'='*50}")
    print(f"  🎬  YOUTUBE VIDEO PIPELINE")
    print(f"  📌  Chủ đề: {topic}")
    print(f"  📂  Thư mục lưu: {dynamic_out_dir}/")
    print(f"{'='*50}\n")

    for i, step in enumerate(PIPELINE_STEPS, start=1):
        run_step(step["script"], step["label"], step["icon"], i, total)

    spinner = PipelineSpinner("📄  Sinh Title & Description cho YouTube", total, total)
    spinner.start()
    generate_youtube_metadata(topic, safe_topic_name)
    spinner.stop(success=True)

    print(f"\n{'='*50}")
    print(f"  🎉  HOÀN TẤT! Output trong thư mục: {OUTPUT_DIR}/")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    main()
