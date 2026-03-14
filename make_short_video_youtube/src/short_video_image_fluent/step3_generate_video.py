import argparse
import json
import os
import sys
import re
import math
import csv
import difflib
import requests
import base64
from pathlib import Path
from datetime import datetime
from io import BytesIO

from dotenv import load_dotenv
from openai import OpenAI
from faster_whisper import WhisperModel
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from proglog import ProgressBarLogger

import imageio_ffmpeg
ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

# Try to load moviepy (handle different versions)
try:
    from moviepy.video.io.VideoFileClip import VideoFileClip
    from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
    from moviepy.video.VideoClip import ColorClip, ImageClip, VideoClip
    from moviepy.audio.io.AudioFileClip import AudioFileClip
except ImportError:
    try:
        from moviepy import VideoFileClip, AudioFileClip, CompositeVideoClip, ColorClip, ImageClip, VideoClip
    except ImportError:
        from moviepy.editor import VideoFileClip, AudioFileClip, CompositeVideoClip, ColorClip, ImageClip, VideoClip


APP_NAME = "SocialHarvester"
APP_STEP = "Step 3: Generate Video"
APP_VERSION = "1.0.0"

IMAGE_MODEL = "google/gemini-3.1-flash-image-preview"
TEXT_MODEL = "google/gemini-2.5-flash"

# Video Layout Configuration
VIDEO_WIDTH = 1440
VIDEO_HEIGHT = 2560
TOP_HEIGHT = int(VIDEO_HEIGHT * 0.3)
BOTTOM_HEIGHT = VIDEO_HEIGHT - TOP_HEIGHT

FONT_SIZE = 65
FONT_PATH = "arialbd.ttf"
TITLE_COLOR = "green"
TEXT_COLOR = "black"
HIGHLIGHT_COLOR = "orange"

SYNC_OFFSET = 0.14
MIN_GAP_FILL = 0.4


class SingleLineRenderLogger(ProgressBarLogger):
    def __init__(self, label: str = "RENDER", width: int = 36, progress_callback=None):
        super().__init__()
        self.label = label
        self.width = width
        self._last_percent = -1
        self._active_bar: str | None = None
        self._bar_totals: dict[str, float] = {}
        self._progress_callback = progress_callback

    def _print_progress(self, percent: int) -> None:
        percent = max(0, min(100, int(percent)))
        filled = int(self.width * percent / 100)
        bar = "#" * filled + "-" * (self.width - filled)
        print(f"\r[{self.label}] [{bar}] {percent:3d}%", end="", flush=True)
        if self._progress_callback is not None:
            self._progress_callback(percent)

    def start(self) -> None:
        self._last_percent = 0
        self._print_progress(0)

    def bars_callback(self, bar, attr, value, old_value=None):
        if attr == "total":
            try:
                total = float(value)
            except Exception:
                return
            if total > 0:
                self._bar_totals[bar] = total
                if self._active_bar is None or bar in {"frame_index", "t"}:
                    self._active_bar = bar
            return

        if attr != "index":
            return

        if self._active_bar is None:
            self._active_bar = bar
        elif bar != self._active_bar:
            if bar in {"frame_index", "t"} and self._active_bar not in {"frame_index", "t"}:
                self._active_bar = bar
            elif self._active_bar not in self._bar_totals and bar in self._bar_totals:
                self._active_bar = bar
            else:
                return

        total = self._bar_totals.get(self._active_bar)
        if not total:
            info = self.bars.get(self._active_bar, {})
            try:
                total = float(info.get("total") or 0.0)
            except Exception:
                total = 0.0
            if total <= 0:
                return
            self._bar_totals[self._active_bar] = total

        try:
            index = float(value)
        except Exception:
            return

        percent = int((index / total) * 100)
        if percent != self._last_percent:
            self._last_percent = percent
            self._print_progress(percent)

    def finish(self) -> None:
        if self._last_percent < 100:
            self._print_progress(100)
        print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate 9:16 Short Video from Content and Audio.")
    parser.add_argument("--project-dir", type=Path, help="Path to the specific project directory")
    parser.add_argument("--font", default=FONT_PATH, help="Path to TrueType font file")
    
    return parser.parse_args()


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_rendered_video(video_path: Path) -> tuple[bool, float, str]:
    if not video_path.exists():
        return False, 0.0, "Missing output video file."

    try:
        file_size = video_path.stat().st_size
    except OSError as exc:
        return False, 0.0, f"Cannot read output file metadata: {exc}"

    if file_size <= 0:
        return False, 0.0, "Output video file is empty."

    clip = None
    try:
        clip = VideoFileClip(str(video_path))
        duration = float(clip.duration or 0.0)
    except Exception as exc:
        return False, 0.0, f"Cannot open rendered video: {exc}"
    finally:
        if clip is not None:
            clip.close()

    if duration <= 0.0:
        return False, duration, "Rendered video duration is invalid."

    return True, duration, ""


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
                    if proj_dir.is_dir() and \
                       (proj_dir / "01_content" / "content.json").exists() and \
                       (proj_dir / "02_audio" / "audio.wav").exists():
                        candidates.append(proj_dir)
    
    if not candidates:
        raise RuntimeError(f"No valid project directories found with Phase 1 & 2 completed in {base_output_dir}")
    
    candidates.sort(key=lambda p: p.stat().st_ctime, reverse=True)
    return candidates[0]


def generate_image_prompt(client: OpenAI, topic: str, text: str) -> str:
    print("[INFO] Designing Prompt for Image Generation...")
    
    sys_prompt = """You are an expert AI Image Prompt Designer. 
Your job is to read an English listening practice topic and script, and create ONE highly detailed prompt optimized for Google's Gemini Image model.

The style MUST be: "comic collage" / "hand-drawn comic book aesthetic" / "minimalist and engaging visual". 
Use the following strict template structure for your output (Do NOT return JSON or markdown codeblocks, just the final formatted text block as described below):

Create an image of a [Theme/Concept]. [Character/Subject]. [Setting/Environment]. [Lighting & Color Palette]. [Background & Details]. The artwork should have a hand-drawn comic collage aesthetic, with clean lines, expressive character design, and soft vibrant colors. [Mood/Emotion]."""
    
    user_prompt = f"Topic: {topic}\n\nScript: {text}\n\nGenerate the single paragraph image prompt based on the template."
    
    response = client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
    )
    final_prompt = response.choices[0].message.content.strip()
    print(f"[INFO] Generated Prompt: {final_prompt[:100]}...")
    return final_prompt

# --- API IMAGE GENERATION (Commented out for manual testing) ---
# def generate_and_save_image(client: OpenAI, prompt: str, out_path: Path):
#     print(f"[INFO] Requesting Image from {IMAGE_MODEL} API...")
#     if out_path.exists():
#         print("[INFO] Image already exists, skipping generation.")
#         return
#         
#     response = client.images.generate(
#         prompt=prompt,
#         model=IMAGE_MODEL,
#         n=1,
#         response_format="b64_json",
#         size="1440x2560" # Requesting the exact vertical resolution if supported
#     )
#     
#     b64_data = response.data[0].b64_json
#     if not b64_data:
#         raise RuntimeError("Image Generation API did not return base64 data.")
#         
#     image_data = base64.b64decode(b64_data)
#     image = Image.open(BytesIO(image_data))
#     image.save(out_path)
#     print(f"[INFO] Saved Cover Image to: {out_path}")
# -------------------------------------------------------------

# =========================================================================================
# VIDEO RENDERING & TIMING LOGIC (Adapted from create_karaoke_video.py)
# =========================================================================================

def get_timings(audio_path):
    print("[STT] Running Faster Whisper to extract precise word timestamps...")
    device = "cuda" if os.environ.get("CUDA_VISIBLE_DEVICES") != "-1" else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    whisper_model = WhisperModel("large-v3", device=device, compute_type=compute_type)
    
    segments, _ = whisper_model.transcribe(str(audio_path), word_timestamps=True)
    all_words = []
    for s in segments:
        if s.words:
            for w in s.words:
                all_words.append({'word': w.word.strip(), 'start': w.start, 'end': w.end})
    return all_words


def create_text_layout(text, width, height, font_size, color_name, title_text=None, align="justify"):
    img = Image.new('RGBA', (width, height), (0,0,0,0))
    draw = ImageDraw.Draw(img)
    
    def load_font(size):
        try:
            return ImageFont.truetype(FONT_PATH, size)
        except Exception:
            return ImageFont.load_default()

    font = load_font(font_size)
    
    # Title Drawing
    start_y = 0
    if title_text:
        t_font = load_font(int(font_size*1.6))
        lines = []
        c_line = []
        for w in title_text.split():
            if draw.textbbox((0,0), " ".join(c_line+[w]), font=t_font)[2] < width*0.9: c_line.append(w)
            else: lines.append(c_line); c_line = [w]
        if c_line: lines.append(c_line)
        
        y = 50
        for l in lines:
            ls = " ".join(l)
            bb = draw.textbbox((0,0), ls, font=t_font)
            lx = (width - (bb[2]-bb[0]))//2
            draw.text((lx, y), ls, font=t_font, fill=TITLE_COLOR)
            y += int(font_size*2)
        start_y = y + 40
        
    # Body Text Layout
    max_w = width - 160 
    available_height = height - start_y - 20
    if available_height < 60: available_height = height - start_y

    def build_lines(active_font):
        lines = []; c_line = []
        def get_wh(t):
            b = draw.textbbox((0,0), t, font=active_font)
            return (b[2]-b[0]), (b[3]-b[1])
        words = text.split()
        for w in words:
            if get_wh(" ".join(c_line + [w]))[0] <= max_w: c_line.append(w)
            else: lines.append(c_line); c_line = [w]
        if c_line: lines.append(c_line)
        return lines, get_wh

    body_font_size = font_size
    line_spacing_factor = 2.0
    while True:
        font = load_font(body_font_size)
        lines, get_wh = build_lines(font)
        try:
            ascent, descent = font.getmetrics()
            base_line_h = ascent + descent
        except Exception:
            base_line_h = get_wh("Ag")[1]
        total_h = (base_line_h * line_spacing_factor) * len(lines)
        if total_h <= available_height or body_font_size <= 18:
            break
        body_font_size -= 2

    if total_h > available_height and len(lines) > 0:
        line_spacing_factor = max(1.2, available_height / (base_line_h * len(lines)))
        total_h = (base_line_h * line_spacing_factor) * len(lines)

    if not title_text: start_y = (height - total_h)//2
    curr_y = start_y
    layout_items = []
    space_w, _ = get_wh(" ")
    left_margin = (width - max_w) // 2
    
    for li, line in enumerate(lines):
        sum_word_w = sum([get_wh(w)[0] for w in line])
        gap = space_w
        if align == "justify" and len(line) > 1 and li < len(lines) - 1:
            extra = max_w - sum_word_w
            gap = extra / (len(line) - 1) if extra > 0 else space_w
            if gap > space_w * 3.0: gap = space_w
            curr_x = left_margin
        else:
            curr_x = left_margin
            
        lh = base_line_h
        line_top = curr_y
        line_bottom = curr_y + lh
        for w in line:
            ww, _ = get_wh(w)
            draw.text((int(round(curr_x)), int(round(curr_y))), w, font=font, fill=color_name)
            p_x = 10; p_y = 8
            layout_items.append({
                'text': w,
                'bbox': (curr_x - p_x, line_top - p_y, curr_x + ww + p_x, line_bottom + p_y),
                'line': li
            })
            curr_x += ww + gap
        curr_y += lh * line_spacing_factor
        
    return img, layout_items


def build_word_timings(layout, karaoke_timings):
    def tokenize(s): return re.findall(r"[A-Za-z0-9]+", s.lower())

    layout_tokens = [(t, idx) for idx, item in enumerate(layout) for t in tokenize(item['text'])]
    timing_tokens = []; timing_starts = []; timing_ends = []
    
    for kw in karaoke_timings:
        for t in tokenize(kw['word']):
            timing_tokens.append(t)
            timing_starts.append(kw['start'])
            timing_ends.append(kw['end'])

    sm = difflib.SequenceMatcher(a=[t for t, _ in layout_tokens], b=timing_tokens, autojunk=False)
    word_times = [{'start': None, 'end': None} for _ in range(len(layout))]
    
    for i, j, n in sm.get_matching_blocks():
        for k in range(n):
            li = layout_tokens[i + k][1]; ts = timing_starts[j + k]; te = timing_ends[j + k]
            if word_times[li]['start'] is None or ts < word_times[li]['start']: word_times[li]['start'] = ts
            if word_times[li]['end'] is None or te > word_times[li]['end']: word_times[li]['end'] = te

    # Interpolate missing timestamps (for punctuation or un-matched words)
    for i in range(len(word_times)):
        if word_times[i]['start'] is None or word_times[i]['end'] is None:
            prev_end = None
            for p in range(i-1, -1, -1):
                if word_times[p]['end'] is not None:
                    prev_end = word_times[p]['end']
                    break
            
            next_start = None
            for n in range(i+1, len(word_times)):
                if word_times[n]['start'] is not None:
                    next_start = word_times[n]['start']
                    break
                    
            if prev_end is not None and next_start is not None:
                word_times[i]['start'] = prev_end
                word_times[i]['end'] = next_start
            elif prev_end is not None:
                word_times[i]['start'] = prev_end
                word_times[i]['end'] = prev_end + 0.3
            elif next_start is not None:
                word_times[i]['start'] = max(0.0, next_start - 0.3)
                word_times[i]['end'] = next_start
            else:
                word_times[i]['start'] = 0.0
                word_times[i]['end'] = 0.3

    # Smart Gap Filling
    sentence_endings = ('.', '!', '?', ':', ';', ',') 
    for i in range(len(word_times) - 1):
        curr = word_times[i]; nxt = word_times[i+1]
        raw_text = layout[i]['text'].strip()
        has_punctuation = raw_text.endswith(sentence_endings)
        
        if curr['end'] is not None and nxt['start'] is not None:
             gap = nxt['start'] - curr['end']
             if gap > 0:
                 if not has_punctuation: curr['end'] = nxt['start']
                 elif raw_text.endswith(',') and gap < MIN_GAP_FILL: curr['end'] = nxt['start']

    # Sync Offset
    for wt in word_times:
        if wt['start'] is not None: wt['start'] += SYNC_OFFSET
        if wt['end'] is not None: wt['end'] += SYNC_OFFSET
            
    return word_times


class HighlightRenderer(VideoClip):
    def __init__(self, timings, layout, box_color, size, duration):
        # Moviepy VideoClip expects a make_frame keyword in v2, but v1 doesn't 
        super().__init__()
        self.timings = timings
        self.layout = layout
        self.box_color = box_color
        self.size = size
        self.duration = duration
        self.ismask = False
        
        self.line_bounds = {}
        for item in self.layout:
            line = item.get("line", 0); y1 = item["bbox"][1]; y2 = item["bbox"][3]
            if line not in self.line_bounds: self.line_bounds[line] = [y1, y2]
            else:
                self.line_bounds[line][0] = min(self.line_bounds[line][0], y1)
                self.line_bounds[line][1] = max(self.line_bounds[line][1], y2)
        
        # This handles cross-compatibility for MoviePy v1.x and v2.x
        self.make_frame = self._make_frame_impl
        self.get_frame = self._make_frame_impl
        
    def _make_frame_impl(self, t):
        frame_img = Image.new('RGBA', self.size, (0,0,0,0))
        draw = ImageDraw.Draw(frame_img)
        segments_by_line = {line: [] for line in self.line_bounds.keys()}
        
        for i, item in enumerate(self.layout):
            timing = self.timings[i]
            if timing["start"] is None or timing["end"] is None or t < timing["start"]: continue
            x1, y1, x2, y2 = item["bbox"]; w = max(0.0, x2 - x1); line = item.get("line", 0)
            
            if t >= timing["end"] or timing["end"] <= timing["start"]: right = x2
            else:
                progress = min(1.0, max(0.0, (t - timing["start"]) / max(timing["end"] - timing["start"], 1e-6)))
                right = x1 + (w * progress)

            if right - x1 >= 1.0: segments_by_line[line].append((x1, right))

        for i in range(len(self.layout) - 1):
            if self.layout[i].get("line") != self.layout[i + 1].get("line"): continue
            if self.timings[i]["end"] is None or self.timings[i + 1]["start"] is None: continue
            
            line = self.layout[i].get("line", 0)
            prev_end = self.timings[i]["end"]
            next_start = self.timings[i + 1]["start"]
            
            if t <= prev_end: continue
            gap_left = self.layout[i]["bbox"][2]; gap_right = self.layout[i + 1]["bbox"][0]
            if gap_right <= gap_left: continue
            
            progress = 1.0 if next_start <= prev_end else min(1.0, max(0.0, (t - prev_end) / max(next_start - prev_end, 1e-6)))
            if progress <= 0.0: continue
            
            conn_right = gap_left + (gap_right - gap_left) * progress
            if conn_right - gap_left >= 1.0: segments_by_line[line].append((gap_left, conn_right))

        for line, segments in segments_by_line.items():
            if not segments: continue
            segments.sort(key=lambda s: s[0])
            merged = []; cur_l, cur_r = segments[0]
            for l, r in segments[1:]:
                if l <= cur_r + 0.5: cur_r = max(cur_r, r)
                else: merged.append((cur_l, cur_r)); cur_l, cur_r = l, r
            merged.append((cur_l, cur_r))

            y1, y2 = self.line_bounds.get(line, (0, 0))
            h = max(0.0, y2 - y1)
            for l, r in merged:
                w = max(0.0, r - l)
                if w < 1.0 or h < 1.0: continue
                radius = min(12, w / 2.0, h / 2.0)
                draw.rounded_rectangle((l, y1, r, y2), radius=radius, fill=self.box_color)
                
        return np.array(frame_img)


def render_video(
    image_path: Path,
    audio_path: Path,
    out_path: Path,
    title: str,
    text: str,
    karaoke_timings: list,
    progress_callback=None,
):
    audio_clip = AudioFileClip(str(audio_path))
    duration = audio_clip.duration
    
    # TOP SECTION (Image)
    top_img_clip = ImageClip(str(image_path))
    ratio_img = top_img_clip.w / top_img_clip.h
    ratio_slot = VIDEO_WIDTH / TOP_HEIGHT
    
    if ratio_img > ratio_slot:
        vid = top_img_clip.resized(height=TOP_HEIGHT)
        vid_layer = vid.cropped(x1=(vid.w - VIDEO_WIDTH)//2, width=VIDEO_WIDTH)
    else:
        vid = top_img_clip.resized(width=VIDEO_WIDTH)
        vid_layer = vid.cropped(y1=(vid.h - TOP_HEIGHT)//2, height=TOP_HEIGHT)
        
    vid_layer = vid_layer.with_duration(duration).with_position(('center', 'top'))

    # BOTTOM SECTION (BG + Text + Highlight)
    bg_bottom_path = "D:/work/Personal_project/make_short_video_youtube/image/image_background/ChatGPT Image 13_35_23 23 thg 1, 2026.png"
    if os.path.exists(bg_bottom_path):
        bg_bottom_clip = ImageClip(bg_bottom_path)
        ratio_bg = bg_bottom_clip.w / bg_bottom_clip.h
        ratio_slot = VIDEO_WIDTH / BOTTOM_HEIGHT
        
        if ratio_bg > ratio_slot:
            bg_vid = bg_bottom_clip.resized(height=BOTTOM_HEIGHT)
            bg_bottom = bg_vid.cropped(x1=(bg_vid.w - VIDEO_WIDTH)//2, width=VIDEO_WIDTH)
        else:
            bg_vid = bg_bottom_clip.resized(width=VIDEO_WIDTH)
            bg_bottom = bg_vid.cropped(y1=(bg_vid.h - BOTTOM_HEIGHT)//2, height=BOTTOM_HEIGHT)
            
        bg_bottom = bg_bottom.with_duration(duration).with_position(('center', 'bottom'))
    else:
        bg_bottom = ColorClip(size=(VIDEO_WIDTH, BOTTOM_HEIGHT), color=(20, 20, 20)).with_duration(duration).with_position(('center', 'bottom'))
    
    img_text, layout = create_text_layout(text, VIDEO_WIDTH, BOTTOM_HEIGHT, FONT_SIZE, TEXT_COLOR, title_text=title, align="justify")
    clip_text = ImageClip(np.array(img_text)).with_duration(duration).with_position((0, TOP_HEIGHT))
    
    word_timings = build_word_timings(layout, karaoke_timings)
    
    highlight_clip = HighlightRenderer(
        timings=word_timings, 
        layout=layout, 
        box_color=HIGHLIGHT_COLOR, 
        size=(VIDEO_WIDTH, BOTTOM_HEIGHT), 
        duration=duration
    ).with_position((0, TOP_HEIGHT))
    
    # COMPOSE & EXPORT
    final = CompositeVideoClip([vid_layer, bg_bottom, highlight_clip, clip_text], size=(VIDEO_WIDTH, VIDEO_HEIGHT))
    final = final.with_audio(audio_clip).with_duration(duration)
    
    # Đặt file tạm audio vào cùng thư mục output để tránh xung đột
    # khi chạy nhiều terminal song song (mỗi project có file tạm riêng)
    temp_audio_path = out_path.parent / f"TEMP_MPY_{out_path.stem}_audio.m4a"

    progress_logger = SingleLineRenderLogger(label="RENDER", progress_callback=progress_callback)
    progress_logger.start()

    # Ưu tiên GPU (NVIDIA NVENC), fallback về CPU (libx264) nếu không hỗ trợ
    try:
        print("[INFO] Attempting GPU render with h264_nvenc...")
        final.write_videofile(
            str(out_path),
            fps=30,
            codec="h264_nvenc",
            audio_codec="aac",
            threads=4,
            logger=progress_logger,
            temp_audiofile=str(temp_audio_path),
        )
        print("[INFO] GPU render (h264_nvenc) successful.")
    except Exception as nvenc_err:
        print(f"\n[WARN] h264_nvenc failed ({nvenc_err}). Falling back to CPU (libx264)...")
        # Reset progress bar cho lần render lại
        progress_logger = SingleLineRenderLogger(label="RENDER (CPU)", progress_callback=progress_callback)
        progress_logger.start()
        final.write_videofile(
            str(out_path),
            fps=30,
            codec="libx264",
            audio_codec="aac",
            threads=4,
            logger=progress_logger,
            temp_audiofile=str(temp_audio_path),
        )
        print("[INFO] CPU render (libx264) successful.")

    progress_logger.finish()

    # Dọn file tạm nếu MoviePy không tự xóa
    if temp_audio_path.exists():
        try:
            temp_audio_path.unlink()
        except OSError:
            pass


def main():
    print(f"{APP_NAME} - {APP_STEP} (v{APP_VERSION})")
    args = parse_args()
    global FONT_PATH
    FONT_PATH = args.font
    
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
    audio_file = proj_dir / "02_audio" / "audio.wav"
    
    if not content_file.exists() or not audio_file.exists():
        raise SystemExit("Missing content.json or audio.wav. Ensure Phase 1 and 2 completed.")
        
    with open(content_file, "r", encoding="utf-8") as f:
        content_data = json.load(f)
        
    topic = content_data.get("topic", "Daily Routines")
    title = content_data.get("title_en", topic)
    text = content_data.get("text_en", "")
    
    vid_dir = proj_dir / "03_video"
    vid_dir.mkdir(parents=True, exist_ok=True)
    img_path = vid_dir / "cover.png"
    out_mp4 = vid_dir / "final_short.mp4"
    render_status_path = vid_dir / "render_status.json"

    render_status = {
        "status": "rendering",
        "success": False,
        "progress_percent": 0,
        "project_dir": str(proj_dir),
        "video_path": str(out_mp4),
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_json(render_status_path, render_status)
    
    client = load_env_and_get_client(project_root)
    
    # 1. Image Protocol
    if not img_path.exists():
        prompt = generate_image_prompt(client, topic, text)
        prompt_file = vid_dir / "image_prompt.txt"
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(prompt)
            
        print("\n" + "="*80)
        print("ACTION REQUIRED: Manual Image Generation")
        print("Please use the following prompt to generate an image manually:")
        print(f"\n{prompt}\n")
        print(f"Prompt also saved to: {prompt_file}")
        print("="*80 + "\n")
        
        while not img_path.exists():
            print(f"Goal: Save the image to this exact path: {img_path}")
            user_input = input("Enter the absolute path to your generated image to copy it automatically\n(Or simply press ENTER if you already saved it there manually): ").strip()
            
            if user_input:
                user_img_path = Path(user_input.strip('"\''))
                if user_img_path.exists():
                    import shutil
                    shutil.copy2(user_img_path, img_path)
                    print(f"[INFO] Successfully copied {user_img_path} to {img_path}")
                else:
                    print(f"[ERROR] File not found: {user_img_path}")
            else:
                if not img_path.exists():
                    print(f"[ERROR] Image not found at {img_path}. Please try again.")
                    
    print(f"[INFO] Image validated at: {img_path}")
    
    # --- IF YOU WANT TO USE THE API DIRECTLY, COMMENT OUT THE WHILE LOOP ABOVE
    # --- AND UNCOMMENT THE LINE BELOW:
    # generate_and_save_image(client, prompt, img_path)
        
    # 2. Timing Protocol
    timings = get_timings(audio_file)
    
    # 3. Render Video
    def on_render_progress(percent: int) -> None:
        render_status["progress_percent"] = int(percent)
        render_status["updated_at"] = datetime.now().isoformat(timespec="seconds")
        write_json(render_status_path, render_status)

    try:
        render_video(
            image_path=img_path,
            audio_path=audio_file,
            out_path=out_mp4,
            title=title,
            text=text,
            karaoke_timings=timings,
            progress_callback=on_render_progress,
        )

        ok, duration_sec, error_message = validate_rendered_video(out_mp4)
        if not ok:
            raise RuntimeError(error_message)

        render_status.update(
            {
                "status": "completed",
                "success": True,
                "progress_percent": 100,
                "completed_at": datetime.now().isoformat(timespec="seconds"),
                "duration_sec": round(duration_sec, 3),
                "file_size_bytes": out_mp4.stat().st_size,
            }
        )
        write_json(render_status_path, render_status)
    except Exception as exc:
        render_status.update(
            {
                "status": "failed",
                "success": False,
                "error": str(exc),
                "failed_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        write_json(render_status_path, render_status)
        raise

    print(f"\n[DONE] Project Video Successfully Generated: {out_mp4}")

if __name__ == "__main__":
    main()
