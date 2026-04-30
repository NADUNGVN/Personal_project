"""
video_renderer.py — Landscape Story Video Renderer

Layout (1920 × 1080 — Landscape / YouTube Long Form):
  ┌─────────────────────────────┐
  │      IMAGE (static)         │  top 2/3  → 1920 × 720 px
  ├─────────────────────────────┤
  │  📖  TEXT STORY (karaoke)  │  bottom 1/3 → 1920 × 360 px
  │  Word-by-word highlight     │
  └─────────────────────────────┘
"""

from __future__ import annotations

import difflib
import json
import math
import os
import re
import sys
import traceback

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR             = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_DIR            = os.path.join(BASE_DIR, "input")
STORY_DETAILS_FILE   = os.path.join(INPUT_DIR, "story_details.json")
CURRENT_OUT_DIR_FILE = os.path.join(INPUT_DIR, "current_output_dir.txt")
IMAGE_INPUT_PATH     = os.path.join(INPUT_DIR, "img", "image.png")

if os.path.exists(CURRENT_OUT_DIR_FILE):
    with open(CURRENT_OUT_DIR_FILE, "r", encoding="utf-8") as _f:
        OUTPUT_DIR = _f.read().strip()
else:
    OUTPUT_DIR = os.path.join(BASE_DIR, "output")

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
VIDEO_W      = 1920
VIDEO_H      = 1080
IMAGE_H      = int(VIDEO_H * 2 / 3)   # 720
TEXT_PANEL_H = VIDEO_H - IMAGE_H      # 360
TEXT_PANEL_Y = IMAGE_H

# Typography
FONT_SIZE_STORY   = 34
LINE_GAP          = 20
TEXT_MARGIN_X     = 80
LINES_PER_PANEL   = 5

# Colours
COLOR_BG          = (255, 255, 255)
COLOR_TEXT        = (0, 0, 0)
COLOR_BOX         = (255, 140, 0) # Orange highlight box

# Faster-Whisper settings
WHISPER_MODEL_SIZE = "base.en"

# Render settings
TESTING_MODE          = True
TESTING_DURATION_SEC  = 30
OUTPUT_FPS            = 24


# ===========================================================================
# Helpers
# ===========================================================================

def make_safe_name(text: str) -> str:
    return "".join(c for c in text if c.isalnum() or c == " ").rstrip().replace(" ", "_")

def get_target_files():
    if not os.path.exists(STORY_DETAILS_FILE):
        raise FileNotFoundError(f"story_details.json not found: {STORY_DETAILS_FILE}")
    with open(STORY_DETAILS_FILE, "r", encoding="utf-8") as f:
        story = json.load(f)
    title     = story.get("title", "Unknown Story")
    safe_name = make_safe_name(title)
    mp3_path  = os.path.join(OUTPUT_DIR, f"{safe_name}_podcast.mp3")
    subs_path = os.path.join(OUTPUT_DIR, f"{safe_name}_subtitles.json")
    if not os.path.exists(mp3_path):
        raise FileNotFoundError(f"MP3 not found: {mp3_path}")
    if not os.path.exists(subs_path):
        raise FileNotFoundError(f"Subtitles JSON not found: {subs_path}")
    return mp3_path, subs_path, safe_name, title

def load_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\calibrib.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    print(f"  [Font] System bold font not found, using PIL default")
    return ImageFont.load_default()

# ===========================================================================
# Image panel preparation
# ===========================================================================

def prepare_image_panel(image_path: str) -> Image.Image:
    """Load image and scale width to VIDEO_W, then center-crop/pad height."""
    img = Image.open(image_path).convert("RGB")
    sw, sh = img.size
    
    scale = VIDEO_W / sw
    new_w = VIDEO_W
    new_h = int(sh * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    
    if new_h >= IMAGE_H:
        t = (new_h - IMAGE_H) // 2
        return img.crop((0, t, VIDEO_W, t + IMAGE_H))
    else:
        res = Image.new("RGB", (VIDEO_W, IMAGE_H), (0,0,0))
        t = (IMAGE_H - new_h) // 2
        res.paste(img, (0, t))
        return res

# ===========================================================================
# Word-level timestamp extraction
# ===========================================================================

def extract_word_timestamps(mp3_path: str, subtitles: list) -> list:
    from faster_whisper import WhisperModel

    print(f"  [Whisper] Loading model '{WHISPER_MODEL_SIZE}' …")
    try:
        model = WhisperModel(WHISPER_MODEL_SIZE, device="cuda", compute_type="float16")
    except Exception:
        print("  [Whisper] CUDA unavailable — falling back to CPU")
        model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")

    print("  [Whisper] Transcribing with word timestamps …")
    segments, _ = model.transcribe(mp3_path, word_timestamps=True)

    w_words = []
    for seg in segments:
        for wd in seg.words:
            w_words.append({
                "word":  wd.word.strip(),
                "start": float(wd.start),
                "end":   float(wd.end),
            })

    # Ground-truth word list
    gt_words = []
    for sub in subtitles:
        if sub.get("duration_sec", 0) <= 0: continue
        text  = sub.get("text", "")
        words = re.findall(r"\S+", text)
        for w in words:
            gt_words.append({
                "word":    w,
                "start":   sub.get("start_time_sec", 0.0),
                "end":     sub.get("end_time_sec",   0.0),
                "matched": False,
            })

    def clean(txt): return re.sub(r"[^a-zA-Z0-9]", "", txt).lower()
    gt_clean = [clean(x["word"]) for x in gt_words]
    w_clean  = [clean(x["word"]) for x in w_words]

    matcher = difflib.SequenceMatcher(None, gt_clean, w_clean, autojunk=False)
    for match in matcher.get_matching_blocks():
        for i in range(match.size):
            gi, wi = match.a + i, match.b + i
            if gt_clean[gi] and w_clean[wi]:
                gt_words[gi]["start"]   = w_words[wi]["start"]
                gt_words[gi]["end"]     = w_words[wi]["end"]
                gt_words[gi]["matched"] = True

    for i in range(len(gt_words)):
        if gt_words[i]["matched"]: continue
        left_t = right_t = None
        for j in range(i - 1, -1, -1):
            if gt_words[j]["matched"]: left_t = gt_words[j]["end"]; break
        for j in range(i + 1, len(gt_words)):
            if gt_words[j]["matched"]: right_t = gt_words[j]["start"]; break
        if left_t  is None: left_t  = gt_words[i]["start"]
        if right_t is None: right_t = gt_words[i]["end"]
        if right_t < left_t: right_t = left_t + 0.05

        k0 = i
        while k0 > 0 and not gt_words[k0 - 1]["matched"]: k0 -= 1
        k1 = i
        while k1 < len(gt_words) - 1 and not gt_words[k1 + 1]["matched"]: k1 += 1
        n = k1 - k0 + 1
        pos = i - k0
        step = (right_t - left_t) / (n + 1)
        gt_words[i]["start"] = left_t + step * (pos + 1)
        gt_words[i]["end"]   = gt_words[i]["start"] + step * 0.8

    matched = sum(1 for w in gt_words if w.get("matched"))
    print(f"  [Whisper] Aligned {matched}/{len(gt_words)} words ({100 * matched // max(1, len(gt_words))}% matched)")
    return gt_words


# ===========================================================================
# Karaoke screen chunking
# ===========================================================================

def wrap_and_justify(words, font, max_w, x_offset):
    sp = font.getlength(" ")
    lines = []; cur = []; cw = 0.0
    
    for w in words:
        ww = font.getlength(w["word"])
        if cur and cw + sp + ww > max_w:
            lines.append(cur); cur = [w]; cw = ww
        else:
            cur.append(w); cw += (sp + ww) if cur[:-1] else ww
    if cur: lines.append(cur)
    
    positioned_lines = []
    for line in lines:
        total_word_w = sum(font.getlength(w["word"]) for w in line)
        if len(line) > 1:
            gap = (max_w - total_word_w) / (len(line) - 1)
            if gap > sp * 3.5:
                gap = sp
                start_x = x_offset + (max_w - (total_word_w + gap * (len(line) - 1))) / 2
            else:
                start_x = x_offset
        else:
            gap = sp
            start_x = x_offset + (max_w - total_word_w) / 2
            
        pos_line = []
        x = start_x
        for w in line:
            ww = font.getlength(w["word"])
            pos_line.append({
                "word": w["word"],
                "start": w["start"],
                "end": w["end"],
                "x": x,
                "w": ww
            })
            x += ww + gap
        positioned_lines.append(pos_line)
    return positioned_lines

def to_panels(lines, n):
    return [{"lines":lines[i:i+n],
             "start":lines[i][0]["start"],
             "end":lines[min(i+n,len(lines))-1][-1]["end"]}
            for i in range(0,len(lines),n)]


# ===========================================================================
# Per-frame composer
# ===========================================================================

def make_frame_composer(image_panel: Image.Image, panels: list,
                         font: ImageFont.FreeTypeFont, total_duration: float):
    base = Image.new("RGB", (VIDEO_W, VIDEO_H), COLOR_BG)
    base.paste(image_panel, (0, 0))
    base_arr = np.array(base)
    line_h = FONT_SIZE_STORY + 10

    def make_frame(t: float) -> np.ndarray:
        panel = None
        for p in panels:
            if p["start"] <= t <= p["end"] + 0.8: 
                panel = p; break
        if panel is None: 
            return base_arr.copy()

        img = Image.fromarray(base_arr.copy())
        draw = ImageDraw.Draw(img)
        
        lines = panel["lines"]
        total_h = len(lines) * line_h + (len(lines) - 1) * LINE_GAP
        start_y = TEXT_PANEL_Y + (TEXT_PANEL_H - total_h) // 2

        # 1. Draw orange highlight boxes connected
        for i, line in enumerate(lines):
            y = start_y + i * (line_h + LINE_GAP)
            y1 = y - 4
            y2 = y + line_h + 4
            segments = []
            
            for w_idx, w in enumerate(line):
                if t >= w["start"]:
                    if t >= w["end"] or w["end"] <= w["start"]:
                        prog = 1.0
                    else:
                        prog = min(1.0, max(0.0, (t - w["start"]) / (w["end"] - w["start"])))
                    
                    if prog > 0:
                        l = w["x"] - 6
                        r = w["x"] + w["w"] * prog + 6
                        segments.append((l, r))
                        
                # Gap segment to the next word
                if w_idx < len(line) - 1:
                    next_w = line[w_idx + 1]
                    prev_end = w["end"]
                    next_start = next_w["start"]
                    if t > prev_end:
                        if next_start <= prev_end:
                            prog = 1.0
                        else:
                            prog = min(1.0, max(0.0, (t - prev_end) / max(next_start - prev_end, 1e-6)))
                        if prog > 0:
                            gap_left = w["x"] + w["w"] + 6
                            gap_right = next_w["x"] - 6
                            if gap_right > gap_left:
                                conn_right = gap_left + (gap_right - gap_left) * prog
                                segments.append((gap_left, conn_right))
                                
            if not segments:
                continue
                
            segments.sort(key=lambda s: s[0])
            merged = []
            cur_l, cur_r = segments[0]
            for l, r in segments[1:]:
                if l <= cur_r + 0.5:
                    cur_r = max(cur_r, r)
                else:
                    merged.append((cur_l, cur_r))
                    cur_l, cur_r = l, r
            merged.append((cur_l, cur_r))
            
            for l, r in merged:
                if r - l > 4:
                    try:
                        draw.rounded_rectangle((l, y1, r, y2), radius=8, fill=COLOR_BOX)
                    except:
                        draw.rectangle((l, y1, r, y2), fill=COLOR_BOX)

        # 2. Draw text
        for i, line in enumerate(lines):
            y = start_y + i * (line_h + LINE_GAP)
            for w in line:
                draw.text((w["x"], y), w["word"], font=font, fill=COLOR_TEXT)

        return np.array(img)

    return make_frame


# ===========================================================================
# Main render pipeline
# ===========================================================================

def create_story_video():
    from moviepy import AudioFileClip, VideoClip

    mp3_path, subs_path, base_name, title = get_target_files()

    print(f"\n{'='*60}")
    print(f"  VIDEO RENDERER — '{title}'")
    print(f"  Output dir: {OUTPUT_DIR}")
    print(f"{'='*60}\n")

    with open(subs_path, "r", encoding="utf-8") as f:
        subtitles = json.load(f)

    # Word-level timestamps (Whisper + cache)
    cache_path = os.path.join(OUTPUT_DIR, f"{base_name}_whisper_cache.json")
    use_cache  = False
    if os.path.exists(cache_path):
        if os.path.getmtime(cache_path) > os.path.getmtime(mp3_path):
            use_cache = True

    if use_cache:
        print("  [Whisper] Cache valid — loading cached timestamps …")
        with open(cache_path, "r", encoding="utf-8") as f:
            words_data = json.load(f)
    else:
        print("  [Whisper] Running alignment …")
        words_data = extract_word_timestamps(mp3_path, subtitles)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(words_data, f, ensure_ascii=False, indent=2)

    # Prepare typography & wrap words
    font = load_font(FONT_SIZE_STORY)
    print(f"  [Font]   Size={FONT_SIZE_STORY}px")

    max_w = VIDEO_W - TEXT_MARGIN_X * 2
    lines = wrap_and_justify(words_data, font, max_w, TEXT_MARGIN_X)
    panels = to_panels(lines, LINES_PER_PANEL)
    print(f"  [Layout] {len(words_data)} words → {len(lines)} lines → {len(panels)} panels")

    # Prepare assets
    if not os.path.exists(IMAGE_INPUT_PATH):
        import glob
        img_candidates = glob.glob(os.path.join(INPUT_DIR, "img", "*.png")) + glob.glob(os.path.join(INPUT_DIR, "img", "*.jpg"))
        if img_candidates:
            image_to_load = img_candidates[0]
        else:
            raise FileNotFoundError(f"Image not found: {IMAGE_INPUT_PATH}")
    else:
        image_to_load = IMAGE_INPUT_PATH
        
    image_panel = prepare_image_panel(image_to_load)
    print(f"  [Image]  Loaded & resized to {VIDEO_W}×{IMAGE_H}")

    audio          = AudioFileClip(mp3_path)
    total_duration = audio.duration
    print(f"  [Audio]  Duration = {total_duration:.1f}s")

    make_frame = make_frame_composer(image_panel, panels, font, total_duration)

    print(f"\n  Rendering {VIDEO_W}×{VIDEO_H} @ {OUTPUT_FPS}fps …")
    video = VideoClip(make_frame, duration=total_duration)
    video = video.with_audio(audio)

    if TESTING_MODE:
        video   = video.subclipped(0, min(TESTING_DURATION_SEC, total_duration))
        out_file = os.path.join(OUTPUT_DIR, f"{base_name}_Preview_Test.mp4")
        print(f"  [TEST]  Rendering only first {TESTING_DURATION_SEC}s")
    else:
        out_file = os.path.join(OUTPUT_DIR, f"{base_name}_Final_Video.mp4")

    video.write_videofile(
        out_file,
        fps            = OUTPUT_FPS,
        codec          = "libx264",
        audio_codec    = "aac",
        threads        = 4,
        ffmpeg_params  = ["-pix_fmt", "yuv420p"],
        logger         = None,
    )

    print(f"\n{'='*60}")
    print(f"  ✅  Done! Video saved to:")
    print(f"      {out_file}")
    print(f"{'='*60}\n")


def main():
    try:
        create_story_video()
    except FileNotFoundError as exc:
        print(f"\n  ❌  Missing file: {exc}")
        print("  Make sure story_tts.py ran successfully first.")
        sys.exit(1)
    except ValueError as exc:
        print(f"\n  ❌  Data error: {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n  ⚠  Render cancelled by user (Ctrl+C).")
        sys.exit(0)
    except Exception:
        print("\n  ❌  Unexpected error during render:")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
