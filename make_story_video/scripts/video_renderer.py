import json
import math
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_DIR = os.path.join(BASE_DIR, "input")
CURRENT_OUT_DIR_FILE = os.path.join(INPUT_DIR, "current_output_dir.txt")
STORY_DETAILS_FILE = os.path.join(INPUT_DIR, "story_details.json")

if os.path.exists(CURRENT_OUT_DIR_FILE):
    with open(CURRENT_OUT_DIR_FILE, "r", encoding="utf-8") as f:
        OUTPUT_DIR = f.read().strip()
else:
    OUTPUT_DIR = os.path.join(BASE_DIR, "output")
    

def get_target_files():
    if not os.path.exists(STORY_DETAILS_FILE):
        raise FileNotFoundError(f"Cannot find story details: {STORY_DETAILS_FILE}")

    with open(STORY_DETAILS_FILE, "r", encoding="utf-8") as f:
        story_details = json.load(f)

    title = story_details.get("title", "Unknown Story")
    safe_topic_name = "".join([c for c in title if c.isalnum() or c == " "]).rstrip().replace(" ", "_")

    mp3_path = os.path.join(OUTPUT_DIR, f"{safe_topic_name}_podcast.mp3")
    json_path = os.path.join(OUTPUT_DIR, f"{safe_topic_name}_subtitles.json")

    return mp3_path, json_path, safe_topic_name

def render_placeholder():
    try:
        mp3_path, json_path, base_name = get_target_files()
        print(f"Loaded MP3: {mp3_path}")
        print(f"Loaded Subtitles: {json_path}")
    except Exception as e:
        print(f"Error resolving paths: {e}")
        sys.exit(1)
        
    print("\n---------------------------------------------------------")
    print("  [PLACEHOLDER] VIDEO RENDERER IS PENDING REQUIREMENTS")
    print("---------------------------------------------------------")
    print("Audio generation is fully complete.")
    print("Awaiting further details on how the Storytelling visual")
    print("elements should be customized before final render.")
    
    # Just touch a dummy video file so the pipeline thinks it succeeded
    out_file = os.path.join(OUTPUT_DIR, f"{base_name}_Final_Video.mp4")
    with open(out_file, "w") as f:
        f.write("DUMMY VIDEO FILE - PENDING RENDERER IMPLEMENTATION")
        
    print(f"\nPlaceholder video created at: {out_file}")

if __name__ == "__main__":
    render_placeholder()
