"""
utils.py — Shared utilities for the YouTube Video Pipeline.
Import this module from any script in the project.
"""
import os


def make_safe_topic_name(topic: str) -> str:
    """
    Convert a topic string into a filesystem-safe directory/file name.
    
    Example:
        "Talking About Your Week" -> "Talking_About_Your_Week"
        "Hello, World! 2026" -> "Hello_World_2026"
    """
    return "".join([c for c in topic if c.isalnum() or c == ' ']).rstrip().replace(" ", "_")


def read_topic_from_file(topics_file: str) -> str:
    """
    Read and return the topic string from the topics.txt state file.
    Exits with an error if the file is missing or empty.
    """
    import sys
    if not os.path.exists(topics_file):
        print(f"Error: topics.txt not found at {topics_file}. Run make_youtube_video.py first.")
        sys.exit(1)
    with open(topics_file, "r", encoding="utf-8") as f:
        topic = f.read().strip()
    if not topic:
        print("Error: Topic is empty in topics.txt.")
        sys.exit(1)
    return topic


def read_output_dir(current_out_dir_file: str, fallback_dir: str) -> str:
    """
    Read the dynamic output directory from the state file.
    Falls back to fallback_dir if the state file does not exist.
    """
    if os.path.exists(current_out_dir_file):
        with open(current_out_dir_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    return fallback_dir
