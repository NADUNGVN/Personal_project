import json
from pathlib import Path

import sys
sys.path.append(r"d:\work\Personal_project\make_video_reading\long_video\src")
from render_long_video import get_whisper_timings, chunk_words_into_screens, create_screen_layouts

def main():
    audio_path = r"d:\work\Personal_project\make_video_reading\long_video\audio\ElevenLabs_2026-04-04T09_48_36_Adam - Articulate Engineering Professor_pvc_sp70_s66_sb75_se25_b_m2 (1).mp3"
    text_path = r"d:\work\Personal_project\make_video_reading\long_video\text\1.txt"
    
    with open(text_path, 'r', encoding='utf-8') as f:
        text_data = f.read()
        
    raw_words = get_whisper_timings(audio_path, source_text_data=text_data)
    
    screens = chunk_words_into_screens(raw_words)
    layouts, font = create_screen_layouts(screens)
    
    with open(r"d:\work\Personal_project\make_video_reading\long_video\out.txt", 'w', encoding='utf-8') as f:
        f.write("Mẫu 10 từ đầu sau khi ghép difflib:\n")
        for w in raw_words[:10]:
            f.write(f"- {w}\n")
            
        f.write("\nChi tiết Render của màn hình đầu tiên:\n")
        f.write(f"Bắt đầu render: {layouts[0]['t_start_render']} -> {layouts[0]['t_end_render']}\n")
        f.write("Các từ trong màn 1:\n")
        for w in layouts[0]['words']:
            f.write(f"[{w['start_t']:.2f} - {w['end_t']:.2f}] Text: '{w['text']}' at X:{w['x1']}, Y:{w['y1']}\n")

if __name__ == '__main__':
    main()
